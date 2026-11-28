from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from typing import Callable

import fitz
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from controller.worker_registry import get_registry
from model.page_raster import rasterize_thumbnail
from src.render_worker.process_client import DocSource, JobOutcome, RenderJob, count_fallback
from utils.helpers import qimage_from_samples


@dataclass(frozen=True)
class ThumbnailFileSource:
    """Immutable identity and authentication data for a clean PDF on disk."""

    path: str
    size: int
    mtime_ns: int
    password: str | None


@dataclass(frozen=True)
class ThumbnailRequest:
    token: str
    session_id: str
    generation: int
    start: int
    end: int
    color_profile: str


class _ThumbnailWorker(QObject):
    batch_ready = Signal(str, str, int, int, object)
    failed = Signal(str, str, int, object)
    finished = Signal(str, str, int, bool)

    def __init__(self, request: ThumbnailRequest, source: ThumbnailFileSource) -> None:
        super().__init__()
        self._request = request
        self._source = source
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        doc: fitz.Document | None = None
        succeeded = False
        try:
            stat = os.stat(self._source.path)
            if stat.st_size != self._source.size or stat.st_mtime_ns != self._source.mtime_ns:
                raise RuntimeError("thumbnail source changed after dispatch")
            doc = fitz.open(self._source.path)
            if doc.needs_pass:
                password = self._source.password
                if password is None or doc.authenticate(password) == 0:
                    raise RuntimeError("thumbnail source authentication failed")
            end = min(self._request.end, len(doc))
            for page_index in range(self._request.start, end):
                if self._cancelled.is_set() or QThread.currentThread().isInterruptionRequested():
                    break
                raster = rasterize_thumbnail(doc, page_index, self._request.color_profile)
                image = qimage_from_samples(
                    raster.samples, raster.width, raster.height, raster.stride, raster.alpha,
                )
                if self._cancelled.is_set() or QThread.currentThread().isInterruptionRequested():
                    break
                self.batch_ready.emit(
                    self._request.token,
                    self._request.session_id,
                    self._request.generation,
                    page_index,
                    [image],
                )
            succeeded = not self._cancelled.is_set()
        except Exception as exc:  # worker failures are handed back to the GUI fallback
            self.failed.emit(
                self._request.token,
                self._request.session_id,
                self._request.generation,
                exc,
            )
        finally:
            if doc is not None:
                doc.close()
            self.finished.emit(
                self._request.token,
                self._request.session_id,
                self._request.generation,
                succeeded,
            )


class ThumbnailCoordinator(QObject):
    """Select a file worker or a one-page-per-turn live thumbnail renderer."""

    def __init__(
        self,
        *,
        source_resolver: Callable[[ThumbnailRequest], ThumbnailFileSource | None],
        live_renderer: Callable[[int, str], QImage],
        batch_consumer: Callable[[int, list[QImage]], None],
        identity_matches: Callable[[str, int], bool],
        parent: QObject | None = None,
        backend=None,
        owner: str | None = None,
        process_source_resolver: Callable[[ThumbnailRequest], DocSource | None] | None = None,
        process_failure_consumer: Callable[[str, int, str], None] | None = None,
        process_page_allowed: Callable[[str, int], bool] | None = None,
        live_allowed: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_resolver = source_resolver
        self._live_renderer = live_renderer
        self._batch_consumer = batch_consumer
        self._identity_matches = identity_matches
        self._active: ThumbnailRequest | None = None
        self._threads: dict[str, tuple[QThread, _ThumbnailWorker]] = {}
        self._backend = backend
        self._owner = owner
        self._process_source_resolver = process_source_resolver
        self._process_failure_consumer = process_failure_consumer
        self._process_page_allowed = process_page_allowed
        # False while the live document must not be read (a write transaction is in flight): a live render waits.
        self._live_allowed = live_allowed
        self._process_jobs: dict[str, tuple[ThumbnailRequest, int, DocSource]] = {}
        self._process_images: dict[int, QImage] = {}
        self._process_image_tokens: dict[int, str] = {}
        self._process_credits: set[str] = set()
        self._process_retries: list[int] = []
        self._process_next = self._process_emit = 0
        self._process_document: DocSource | None = None
        if backend is not None:
            backend.job_done.connect(self._process_done)
            revoked = getattr(backend, 'image_revoked', None)
            if revoked is not None:
                revoked.connect(self._process_image_revoked)

    @property
    def has_active_job(self) -> bool:
        return self._active is not None

    def request(
        self,
        session_id: str,
        generation: int,
        start: int,
        end: int,
        color_profile: str,
    ) -> str:
        # Cancellation deliberately precedes source selection. A synchronous fallback
        # can therefore never leave the superseded file worker running as an owner.
        self.cancel()
        request = ThumbnailRequest(
            token=str(uuid.uuid4()),
            session_id=session_id,
            generation=generation,
            start=start,
            end=max(start, end),
            color_profile=color_profile,
        )
        if (self._backend is not None and self._process_source_resolver is not None
                and not getattr(self._backend, 'unavailable', False)):
            document = self._process_source_resolver(request)
            if document is not None:
                self._active = request
                self._process_document = document
                self._process_next = self._process_emit = request.start
                self._submit_process_page(request, request.start, document)
                return request.token
        source = self._source_resolver(request)
        self._active = request
        if source is None:
            QTimer.singleShot(0, lambda req=request: self._render_live_page(req, req.start))
        else:
            self._start_worker(request, source)
        return request.token

    def cancel(self, session_id: str | None = None) -> None:
        active = self._active
        if session_id is not None and active is not None and active.session_id != session_id:
            return
        self._active = None
        self._process_document = None
        process_jobs, self._process_jobs = self._process_jobs, {}
        self._process_images.clear()
        for token in self._process_image_tokens.values():
            self._result_consumed(token)
        self._process_image_tokens.clear()
        self._process_retries.clear()
        for token in process_jobs:
            self._backend.cancel(token)
        for thread, worker in list(self._threads.values()):
            worker.cancel()
            thread.requestInterruption()

    def _submit_process_page(self, request, page, document):
        if not self._is_current(request.token, request.session_id, request.generation):
            return
        if not document.is_current():
            self.cancel()
            return
        if self._process_emit >= request.end:
            self._active = None
            return
        window_for = getattr(self._backend, 'window_for', None)
        advertised = window_for(document) if window_for else getattr(self._backend, 'thumbnail_window', 1)
        window = min(3, max(1, advertised))
        # Completed images count towards the window too: an out-of-order tail
        # cannot accumulate behind a slow first page.
        while (self._is_current(request.token, request.session_id, request.generation)
               and len(self._process_jobs) + len(self._process_images) < window
               and (self._process_retries or self._process_next < request.end)):
            if self._process_retries:
                page = self._process_retries.pop(0)
            else:
                page = self._process_next
                self._process_next += 1
            token = uuid.uuid4().hex
            self._process_jobs[token] = (request, page, document)
            if self._process_page_allowed and not self._process_page_allowed(request.session_id, page):
                self._process_done(token, JobOutcome('quarantined'))
            else:
                self._backend.submit(RenderJob(token, self._owner, 'thumb', document,
                                               page, 1., request.color_profile, 'thumb'))

    @Slot(str, object)
    def _process_done(self, token, outcome):
        pending = self._process_jobs.pop(token, None)
        if pending is None:
            return
        request, page, document = pending
        if outcome.status == 'image':
            self._process_credits.add(token)
        try:
            self._complete_process_page(request, page, document, outcome, token)
        finally:
            if token not in self._process_image_tokens.values():
                self._result_consumed(token)

    def _result_consumed(self, token):
        if token not in self._process_credits:
            return
        self._process_credits.discard(token)
        consumed = getattr(self._backend, 'result_consumed', None)
        if consumed:
            consumed(token)

    @Slot(str)
    def _process_image_revoked(self, token):
        request, document = self._active, self._process_document
        for page, image_token in list(self._process_image_tokens.items()):
            if image_token != token:
                continue
            self._process_image_tokens.pop(page)
            self._process_images.pop(page, None)
            self._result_consumed(token)
            if (request is not None and document is not None
                    and document.is_current()
                    and self._is_current(request.token, request.session_id, request.generation)):
                self._process_retries.append(page)
                QTimer.singleShot(0, lambda: self._submit_process_page(request, page, document))
            return

    def _complete_process_page(self, request, page, document, outcome, token):
        if not self._is_current(request.token, request.session_id, request.generation):
            return
        if not document.is_current():
            self.cancel()
            return
        if outcome.status in {'owner_released', 'stale'}:
            self.cancel()
            return
        if outcome.status in {'cancelled', 'capacity'}:
            self._process_retries.append(page)
            QTimer.singleShot(100 if outcome.status == 'capacity' else 0,
                              lambda: self._submit_process_page(request, page, document))
            return
        if outcome.status == 'image':
            image = outcome.image
        elif outcome.status in {'transport_lost', 'timeout', 'quarantined'}:
            if outcome.status != 'quarantined' and self._process_failure_consumer:
                self._process_failure_consumer(request.session_id, page, outcome.status)
            image = QImage(16, 16, QImage.Format_RGB888)
            image.fill(0xD3D3D3)
        else:
            count_fallback(self._backend.metrics, outcome)
            if self._live_allowed is not None and not self._live_allowed():
                self._process_retries.append(page)  # the live fallback reads the document: try the page again later
                QTimer.singleShot(100, lambda: self._submit_process_page(request, page, document))
                return
            image = self._live_renderer(page, request.color_profile)
        if not document.is_current():
            self.cancel()
            return
        if not self._is_current(request.token, request.session_id, request.generation):
            return
        self._process_images[page] = image
        self._process_image_tokens[page] = token
        while (self._is_current(request.token, request.session_id, request.generation)
               and document.is_current()
               and self._process_emit in self._process_images):
            start = self._process_emit
            image = self._process_images.pop(start)
            image_token = self._process_image_tokens.pop(start)
            self._process_emit += 1
            try:
                self._accept_batch(request.token, request.session_id, request.generation, start, [image])
            finally:
                self._result_consumed(image_token)
        if not document.is_current():
            self.cancel()
            return
        QTimer.singleShot(0, lambda: self._submit_process_page(request, page + 1, document))

    def wait_for_done(self, timeout_ms: int = 3000) -> bool:
        stopped = True
        for thread, _worker in list(self._threads.values()):
            thread.quit()
            stopped = thread.wait(timeout_ms) and stopped
        return stopped

    def _start_worker(self, request: ThumbnailRequest, source: ThumbnailFileSource) -> None:
        thread = QThread(self)
        worker = _ThumbnailWorker(request, source)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.batch_ready.connect(self._accept_batch)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._worker_finished)
        self._threads[request.token] = (thread, worker)

        def cancel_thread() -> None:  # non-blocking, idempotent: the quit gate repeats it
            worker.cancel()
            thread.requestInterruption()

        if not get_registry().start_owned(thread, cancel_thread, dispose=True):
            # Shutdown began: nothing started, so no page is rendered live either.
            self._threads.pop(request.token, None)
            self._active = None

    def _is_current(self, token: str, session_id: str, generation: int) -> bool:
        active = self._active
        return bool(
            active is not None
            and active.token == token
            and active.session_id == session_id
            and active.generation == generation
            and self._identity_matches(session_id, generation)
        )

    @Slot(str, str, int, int, object)
    def _accept_batch(
        self,
        token: str,
        session_id: str,
        generation: int,
        start: int,
        images: list[QImage],
    ) -> None:
        if not self._is_current(token, session_id, generation):
            return
        self._batch_consumer(start, images)

    def _render_live_page(self, request: ThumbnailRequest, page_index: int) -> None:
        if not self._is_current(request.token, request.session_id, request.generation):
            return
        if page_index >= request.end:
            self._active = None
            return
        if self._live_allowed is not None and not self._live_allowed():
            QTimer.singleShot(100, lambda req=request, page=page_index: self._render_live_page(req, page))
            return
        image = self._live_renderer(page_index, request.color_profile)
        self._accept_batch(
            request.token,
            request.session_id,
            request.generation,
            page_index,
            [image],
        )
        # Exactly one MuPDF render occurs per callback. The next page is handed to
        # Qt so input and painting events get an event-loop turn between pages.
        QTimer.singleShot(0, lambda req=request, page=page_index + 1: self._render_live_page(req, page))

    @Slot(str, str, int, object)
    def _worker_failed(self, token: str, session_id: str, generation: int, _exc: Exception) -> None:
        if not self._is_current(token, session_id, generation):
            return
        request = self._active
        if request is not None:
            QTimer.singleShot(0, lambda req=request: self._render_live_page(req, req.start))

    @Slot(str, str, int, bool)
    def _worker_finished(
        self,
        token: str,
        session_id: str,
        generation: int,
        succeeded: bool,
    ) -> None:
        if succeeded and self._is_current(token, session_id, generation):
            self._active = None
        QTimer.singleShot(0, lambda tok=token: self._thread_finished(tok))

    def _thread_finished(self, token: str) -> None:
        # No wait here: the thread is registry-owned (``dispose=True``), joined with ``wait(0)`` on the
        # GUI thread and deleted afterwards; ``cancel_thread`` keeps the worker referenced until then.
        self._threads.pop(token, None)
