"""Background Ext-B font subsetting for the inline editor's live preview.

Owner decision C on F13-EXTB-PERF-1 (S14-EXTB-PREVIEW-WORKER): the fontTools work
that draws a NEW set of CJK Ext-B characters (``utils.cjk_ext_b_font``: cmap load,
subset, save; 0.12-0.25 s) must not run on the GUI thread.  ``PreviewRenderer`` asks
the caches only (``cached_only=True``) and draws a transient ``.notdef`` frame on a
miss; the editor then hands the markup to an ``ExtBSubsetService``, whose
``QThread`` fills the (thread-safe) caches and reports back through a signal, and the
editor re-renders.

Rules (``QThread`` + Signals only; ``threading.Thread`` is banned in ``view/``):

* one worker at a time per service; while it runs only the LATEST request is kept
  (older ones are superseded, never started);
* the thread touches no Qt object and no ``fitz`` object: it only calls
  ``warm_ext_b_subsets`` and emits a signal, which reaches the service on the GUI
  thread as a queued call;
* a thread object is parentless and held by a module registry until it has
  finished, so closing the editor (or destroying the service) never destroys a
  running ``QThread``; the cache it fills stays valid for the next editor;
* ``QCoreApplication.aboutToQuit`` waits for every live thread (app teardown).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

from utils.cjk_ext_b_font import warm_ext_b_subsets

logger = logging.getLogger(__name__)

_LIVE_THREADS: list[ExtBSubsetThread] = []
_quit_hooked_for: QCoreApplication | None = None
_DEFAULT_WAIT_MS = 15000


class ExtBSubsetThread(QThread):
    """Runs ``warm_ext_b_subsets(html)`` once and emits ``subsets_done(html, ok)``."""

    subsets_done = Signal(str, bool)

    def __init__(self, html: str) -> None:
        super().__init__()  # parentless: see the module docstring
        self._html = html

    def run(self) -> None:
        ok = True
        try:
            warm_ext_b_subsets(self._html)
        except Exception:
            ok = False
            logger.warning("Ext-B preview subset failed", exc_info=True)
        self.subsets_done.emit(self._html, ok)


def _reap() -> None:
    _LIVE_THREADS[:] = [t for t in _LIVE_THREADS if not t.isFinished()]


def live_ext_b_subset_threads() -> list[ExtBSubsetThread]:
    """The worker threads not yet finished (after dropping the finished ones)."""
    _reap()
    return list(_LIVE_THREADS)


def wait_for_ext_b_subset_threads(timeout_ms: int = _DEFAULT_WAIT_MS) -> bool:
    """Block until every live worker thread has finished (app teardown, tests).
    ``True`` when none is left; a thread still running after ``timeout_ms`` stays
    registered (it is never destroyed while running)."""
    for thread in list(_LIVE_THREADS):
        thread.wait(timeout_ms)
    _reap()
    return not _LIVE_THREADS


def _register(thread: ExtBSubsetThread) -> None:
    global _quit_hooked_for
    _reap()
    _LIVE_THREADS.append(thread)
    app = QCoreApplication.instance()
    if app is not None and app is not _quit_hooked_for:
        _quit_hooked_for = app
        app.aboutToQuit.connect(wait_for_ext_b_subset_threads)


class ExtBSubsetService(QObject):
    """Subsets the Ext-B fonts a markup needs on a worker thread; latest request wins.

    ``subsets_ready(html, ok)`` is emitted on the owner's thread when the worker for
    ``html`` has finished.  The service decides nothing about staleness: the
    requester compares ``html`` with what it currently wants and drops the rest."""

    subsets_ready = Signal(str, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: ExtBSubsetThread | None = None
        self._running_html: str | None = None
        self._queued: str | None = None
        self._closed = False

    def request(self, html: str) -> None:
        """Ask for ``html``'s subsets.  Ignored after ``close()``."""
        if self._closed:
            return
        if self._thread is not None:
            # One worker at a time: the newest request replaces any queued one.
            self._queued = None if html == self._running_html else html
            return
        self._start(html)

    def close(self) -> None:
        """Forget queued work and never signal again.  A running thread finishes
        by itself (it only fills the cache) and is reaped by the registry."""
        self._closed = True
        self._queued = None
        try:
            self.subsets_ready.disconnect()
        except (RuntimeError, TypeError):
            pass  # nothing connected

    def _start(self, html: str) -> None:
        thread = ExtBSubsetThread(html)
        thread.subsets_done.connect(self._on_done)
        self._thread = thread
        self._running_html = html
        _register(thread)
        thread.start()

    @Slot(str, bool)
    def _on_done(self, html: str, ok: bool) -> None:
        self._thread = None
        self._running_html = None
        queued, self._queued = self._queued, None
        if self._closed:
            return
        self.subsets_ready.emit(html, ok)
        if queued is not None and not self._closed:
            self._start(queued)
