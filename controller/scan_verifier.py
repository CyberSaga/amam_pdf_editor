"""Background lex of long content streams, so a writer never lexes one on the GUI thread.

A writer (move, rotate, resize, delete of a native image) never uses an offset the child reported
(A4 class): it lexes the decoded stream itself.  That costs about 150 ms per MB, so for a stream over
``MUTATION_INLINE_SCAN_LIMIT_BYTES`` the lex runs here, in one ``QThread`` at a time, and the result
comes back by signal to the GUI thread, which keeps it through the model as a *verified scan*.

The trust rule is unchanged: the scan stored is the one ``scan_stream`` produced in THIS process from
the decoded bytes, never a child's row.  A job belongs to ``(handle generation, page, content key)``;
a result whose handle, page or stream changed meanwhile is dropped, and a failed or cancelled job
records nothing.  The bytes a job holds are bounded by the page decode cap.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import shiboken6
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from controller.worker_registry import get_registry
from model import content_scan
from model.pdf_content_ops import PAGE_DECODE_CAP_BYTES, STREAM_DECODE_CAP_BYTES

logger = logging.getLogger(__name__)

#: how long a request waits before its worker starts (see ``ScanVerifier.request``)
START_DELAY_MS = 150


@dataclass
class _Request:
    generation: int
    page_num: int
    key: bytes
    stream: bytes


class _LexThread(QThread):
    """Lexes one decoded stream; the result is read from ``scan`` after ``finished``."""

    def __init__(self, request: _Request, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.request = request
        self.scan: content_scan.StreamScan | None = None
        self.cancelled = False

    def run(self) -> None:
        try:
            if content_scan.content_key(self.request.stream) != self.request.key:
                return  # the bytes are not what the request named: nothing is recorded
            self.scan = content_scan.scan_stream(self.request.stream, lambda: self.cancelled)
        except content_scan.ScanStopped:
            self.scan = None  # cancelled or shutting down: nothing is recorded
        except BaseException:  # a failed lex records nothing (MemoryError included)
            logger.warning("background scan verification failed", exc_info=True)
            self.scan = None


class ScanVerifier(QObject):
    """One worker at a time over a queue of requests; ``verified(page)`` per stored scan, ``idle()``
    when the queue and the worker are empty."""

    verified = Signal(int)
    idle = Signal()

    def __init__(self, model, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._queue: deque[_Request] = deque()
        self._running: _LexThread | None = None
        self._stopped = False  # set by ``shutdown`` / ``retire``: nothing new starts
        # Application teardown drains the registry, not the window contexts: a retired window's
        # worker must stay reachable until it has finished.
        get_registry().register(self)

    def is_busy(self) -> bool:
        return self._running is not None or bool(self._queue)

    def _queued_bytes(self) -> int:
        held = sum(len(r.stream) for r in self._queue)
        if self._running is not None:
            held += len(self._running.request.stream)
        return held

    def request(self, generation: int, page_num: int, key: bytes, stream: bytes) -> bool:
        """Queue a lex of ``stream`` (decoded, content key ``key``); ``False`` when there is nothing
        to do (already verified, queued or running) or it is over a decode cap."""
        if self._stopped or content_scan.verified_scan(key) is not None:
            return False
        if len(stream) > STREAM_DECODE_CAP_BYTES:
            return False
        if any(r.key == key for r in self._queue) or (self._running is not None and self._running.request.key == key):
            return False
        if self._queued_bytes() + len(stream) > PAGE_DECODE_CAP_BYTES:
            return False
        self._queue.append(_Request(int(generation), int(page_num), key, stream))
        if self._running is None:
            # The worker competes with the GUI thread for the interpreter lock: start it after the
            # gesture that asked (its redraw, the click it resolves) has run, not inside it.
            QTimer.singleShot(START_DELAY_MS, self._pump)
        return True

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Blocking: cancel everything and wait for the worker, at most ``timeout_ms``.  ``True`` when
        no worker is running afterwards.  The lex checks the cancel flag every few thousand tokens, so
        this returns quickly; a worker that did not finish in time stays owned and registered
        (``False``), and no new request is accepted after this call.  Repeatable: each call is a
        fresh pass that waits again for a survivor."""
        self._stopped = True
        self._queue.clear()
        worker = self._running
        if worker is None:
            get_registry().unregister(self)
            return True
        worker.cancelled = True
        if not worker.wait(max(0, int(timeout_ms))):
            logger.warning("scan verification worker still running after %d ms", timeout_ms)
            return False
        if self._running is worker:
            self._running = None  # its queued finished signal then finds nothing to do
        get_registry().unregister(self)
        return True

    def retire(self) -> None:
        """Non-blocking: the owning window is going away.  Cancel, accept nothing new, and stay in the
        registry until the running worker finished, so a later application teardown still waits for it."""
        self._stopped = True
        self._queue.clear()
        if self._running is None:
            get_registry().unregister(self)
        else:
            self._running.cancelled = True

    def cancel(self) -> None:
        """Registry protocol, non-blocking: cancel and accept nothing new (same as ``retire``)."""
        self.retire()

    def alive(self) -> bool:
        """Registry protocol: is a lex thread of this verifier still running.  A deleted C++ thread
        cannot be running; any other state is read from the thread itself."""
        worker = self._running
        # ``wait(0)``, not ``isRunning()``: that turns False at ``finished`` while a handler still runs.
        return worker is not None and shiboken6.isValid(worker) and not worker.wait(0)

    def cancel_all(self) -> None:
        """Forget every queued request; a running lex stops at its next check, its result is dropped."""
        self._queue.clear()
        if self._running is not None:
            self._running.cancelled = True
        self._emit_idle_if_done()

    def _pump(self) -> None:
        if self._stopped or self._running is not None or not self._queue:
            return
        worker = _LexThread(self._queue.popleft())
        self._running = worker
        get_registry().register(self)  # idempotent; the registry drops an idle entry at a quit poll
        worker.finished.connect(lambda w=worker: self._on_finished(w))

        def cancel_worker() -> None:  # the lex checks this flag every few thousand tokens
            worker.cancelled = True

        if not get_registry().start_owned(worker, cancel_worker, dispose=True):
            # Shutdown began: nothing started (the registry discarded the worker) and nothing more will be.
            self._running = None
            self._stopped = True
            self._queue.clear()
            get_registry().unregister(self)
            self._emit_idle_if_done()

    def _on_finished(self, worker: _LexThread) -> None:
        if self._running is worker:
            self._running = None
        # No wait here (a GUI-thread callback must not block): ``run()`` has returned, so ``request``
        # and ``scan`` are final, and the registry (``dispose=True``) joins the thread with ``wait(0)``
        # and deletes it afterwards.
        request, scan = worker.request, worker.scan
        if scan is not None and not worker.cancelled and self._is_current(request):
            if self._model.store_verified_scan(request.key, scan):
                self.verified.emit(request.page_num)
        self._pump()
        if self._stopped and self._running is None:
            get_registry().unregister(self)  # shut down and idle: nothing left to drain
        self._emit_idle_if_done()

    def _is_current(self, request: _Request) -> bool:
        """The handle, the page and the stream the request named are still what the document holds."""
        model = self._model
        if model.doc is None or request.generation != model.handle_generation:
            return False
        if request.page_num < 1 or request.page_num > len(model.doc):
            return False
        return request.key in model.image_scan_set_key(request.page_num)

    def _emit_idle_if_done(self) -> None:
        if not self.is_busy():
            self.idle.emit()
