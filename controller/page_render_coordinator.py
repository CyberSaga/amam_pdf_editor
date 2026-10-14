from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import fitz
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage

from model.color_profile import safe_to_fitz_colorspace
from utils.helpers import pixmap_to_qimage
from utils.render_limits import safe_render_scale


_THREAD_TOKEN_PROPERTY = "page_render_token"


@dataclass(frozen=True)
class PageRenderIdentity:
    token: str
    session_id: str
    generation: int
    revision: int
    page_index: int
    quality: str
    rendered_scale: float
    target_scale: float
    color_profile: str
    device_pixel_ratio: float


@dataclass(frozen=True)
class PageRenderRequest:
    identity: PageRenderIdentity
    snapshot_bytes: bytes


class _PageRenderWorker(QObject):
    rendered = Signal(object, object)
    failed = Signal(object, object)
    finished = Signal(object, bool)

    def __init__(self, request: PageRenderRequest) -> None:
        super().__init__()
        self._request: PageRenderRequest | None = request
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        request = self._request
        if request is None:
            return
        identity = request.identity
        doc: fitz.Document | None = None
        succeeded = False
        try:
            if self._cancelled.is_set() or QThread.currentThread().isInterruptionRequested():
                return
            doc = fitz.open(stream=request.snapshot_bytes, filetype="pdf")
            if identity.page_index < 0 or identity.page_index >= len(doc):
                raise ValueError(f"page_index={identity.page_index} out of range")
            page = doc[identity.page_index]
            physical_scale = safe_render_scale(
                page,
                identity.rendered_scale * identity.device_pixel_ratio,
            )
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(physical_scale, physical_scale),
                annots=True,
                colorspace=safe_to_fitz_colorspace(identity.color_profile),
            )
            if self._cancelled.is_set() or QThread.currentThread().isInterruptionRequested():
                return
            self.rendered.emit(identity, pixmap_to_qimage(pixmap))
            succeeded = True
        except Exception as exc:
            if not self._cancelled.is_set():
                self.failed.emit(identity, exc)
        finally:
            if doc is not None:
                doc.close()
            self._request = None
            self.finished.emit(identity, succeeded)


class PageRenderCoordinator(QObject):
    """Own one page-raster thread and retain only the latest replacement request."""

    def __init__(
        self,
        *,
        result_consumer: Callable[[PageRenderIdentity, QImage], None],
        failure_consumer: Callable[[PageRenderIdentity, Exception], None],
        identity_matches: Callable[[PageRenderIdentity], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._result_consumer = result_consumer
        self._failure_consumer = failure_consumer
        self._identity_matches = identity_matches
        self._active: PageRenderRequest | None = None
        self._pending: PageRenderRequest | None = None
        self._threads: dict[str, tuple[QThread, _PageRenderWorker]] = {}
        self._cancelled_tokens: set[str] = set()

    @property
    def active_token(self) -> str | None:
        return self._active.identity.token if self._active is not None else None

    @property
    def has_active_job(self) -> bool:
        return self._active is not None or self._pending is not None

    def request(
        self,
        *,
        session_id: str,
        generation: int,
        revision: int,
        page_index: int,
        quality: str,
        rendered_scale: float,
        target_scale: float,
        color_profile: str,
        device_pixel_ratio: float,
        snapshot_bytes: bytes,
    ) -> str:
        identity = PageRenderIdentity(
            token=str(uuid.uuid4()),
            session_id=session_id,
            generation=generation,
            revision=revision,
            page_index=page_index,
            quality=quality,
            rendered_scale=float(rendered_scale),
            target_scale=float(target_scale),
            color_profile=color_profile,
            device_pixel_ratio=float(device_pixel_ratio),
        )
        request = PageRenderRequest(identity=identity, snapshot_bytes=snapshot_bytes)
        if self._active is not None:
            self._cancel_active()
            self._pending = request
        else:
            self._start_worker(request)
        return identity.token

    def cancel(self, session_id: str | None = None) -> None:
        pending = self._pending
        if pending is not None and (
            session_id is None or pending.identity.session_id == session_id
        ):
            self._pending = None
        active = self._active
        if active is not None and (
            session_id is None or active.identity.session_id == session_id
        ):
            self._cancel_active()

    def wait_for_done(self, timeout_ms: int = 1000) -> bool:
        self.cancel()
        stopped = True
        for thread, _worker in list(self._threads.values()):
            thread.requestInterruption()
            thread.quit()
            stopped = thread.wait(timeout_ms) and stopped
        return stopped

    def _cancel_active(self) -> None:
        active = self._active
        if active is None:
            return
        token = active.identity.token
        self._cancelled_tokens.add(token)
        entry = self._threads.get(token)
        if entry is not None:
            thread, worker = entry
            worker.cancel()
            thread.requestInterruption()

    def _start_worker(self, request: PageRenderRequest) -> None:
        identity = request.identity
        thread = QThread(self)
        worker = _PageRenderWorker(request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.rendered.connect(self._accept_result)
        worker.failed.connect(self._accept_failure)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        # GATE15-3: never connect a child thread's signal to a lambda that captures
        # ``self``.  The connection lives on a child QThread of this QObject, so the
        # lambda kept this coordinator's Python wrapper alive until the thread was
        # destroyed -- and the thread's own deleteLater then dropped the last
        # reference from inside the thread's destruction (the wrapper deleted the
        # C++ coordinator, which deleted the very thread being destroyed: native
        # abort in an unrelated later processEvents).  A bound-slot connection
        # holds no strong reference and is severed with the receiver; the token
        # travels on the thread itself and is read back through ``sender()``.
        thread.setProperty(_THREAD_TOKEN_PROPERTY, identity.token)
        thread.finished.connect(self._on_thread_finished_signal)
        thread.finished.connect(thread.deleteLater)
        self._active = request
        self._threads[identity.token] = (thread, worker)
        thread.start()

    def _is_current(self, identity: PageRenderIdentity) -> bool:
        active = self._active
        return bool(
            active is not None
            and active.identity == identity
            and identity.token not in self._cancelled_tokens
            and self._identity_matches(identity)
        )

    @Slot(object, object)
    def _accept_result(self, identity: PageRenderIdentity, image: QImage) -> None:
        if self._is_current(identity):
            self._result_consumer(identity, image)

    @Slot(object, object)
    def _accept_failure(self, identity: PageRenderIdentity, exc: Exception) -> None:
        if self._is_current(identity):
            self._failure_consumer(identity, exc)

    @Slot()
    def _on_thread_finished_signal(self) -> None:
        sender = self.sender()
        token = sender.property(_THREAD_TOKEN_PROPERTY) if sender is not None else None
        if isinstance(token, str):
            self._thread_finished(token)

    def _thread_finished(self, token: str) -> None:
        entry = self._threads.pop(token, None)
        if entry is not None:
            thread, _worker = entry
            thread.wait(1000)
        self._cancelled_tokens.discard(token)
        if self._active is not None and self._active.identity.token == token:
            self._active = None
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._start_worker(pending)
