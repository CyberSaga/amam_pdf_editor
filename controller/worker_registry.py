"""The one owner of controller-created background workers that can outlive a window.

Class closed here: a worker thread still running when the event loop exits because the object that
owned it (a window context, a retired primary controller) was no longer reachable from teardown,
or because it was started after shutdown had already begun.  A controller starts its QThread through
``start_owned`` (register + start in one step, refused once shutdown closed admission); a child
process starts through ``start_owned_child`` (same admission, alive until the child exited); other
workers register themselves.  Application teardown asks THIS registry, not the window contexts,
what is still running.

An entry provides two non-blocking calls: ``cancel()`` (ask it to stop; never waits, idempotent) and
``alive() -> bool`` (is anything of it still running).  The quit gate in ``main`` closes admission,
cancels, and polls ``alive()``; nothing here blocks the GUI thread.  Qt-free at import: QtCore and
``shiboken6`` are imported where needed.

QThread deletion (``dispose=True``) is owned here: ``QThread.deleteLater`` queued while the thread
is still inside a ``finished`` handler makes the GUI thread block in ``~QThread`` until the handler
returns, so the registry calls it, on the GUI thread, only once ``wait(0)`` succeeded.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Hard ceiling from the first quit request.  Past it the process logs the survivors and leaves
#: with ``os._exit``: a normal exit with a live Python thread under PySide6 can deadlock in
#: ExitProcess.  The longest uncancellable step known is one OCR page.
QUIT_CEILING_MS = 30000


def require_gui_thread(what: str) -> None:
    """Raise unless called on the GUI thread (skipped while no ``QCoreApplication`` exists).

    Starting, sweeping and closing admission finalise QThread wrappers, which must not happen on a
    background caller.  An explicit raise, not ``assert``: ``-O`` strips asserts."""
    from PySide6.QtCore import QCoreApplication, QThread

    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() is not app.thread():
        raise RuntimeError(f"{what} must be called on the GUI thread")


class _ThreadEntry:
    """Adapter of a bare ``QThread`` whose owner drops its own reference before it has finished."""

    def __init__(self, thread: Any, cancel: Callable[[], None] | None, dispose: bool = False) -> None:
        self._thread = thread
        self._cancel = cancel
        self.dispose_when_done = dispose
        self._disposed = False
        #: False from admission until ``start()`` returned: such an entry is never swept as idle.
        self.started = False

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel()

    def alive(self) -> bool:
        import shiboken6

        if not self.started:
            return True
        # A deleted C++ thread cannot be running; any other error is NOT "done" (W2).  isRunning()
        # turns False as soon as ``finished`` is emitted, while a handler on the thread may still
        # run; only ``wait(0)`` means the OS thread has exited.
        if not shiboken6.isValid(self._thread):
            return False
        return not self._thread.wait(0)

    def awaiting_exit(self) -> bool:
        """``finished`` was emitted but the OS thread has not exited yet (a handler is still running)."""
        import shiboken6

        return (self.started and shiboken6.isValid(self._thread)
                and self._thread.isFinished() and not self._thread.wait(0))

    def dispose(self) -> None:
        """Queue the C++ object's deletion (GUI thread, after ``alive()`` turned False).  Idempotent."""
        import shiboken6

        if self._disposed or not self.dispose_when_done:
            return
        self._disposed = True
        if shiboken6.isValid(self._thread):
            self._thread.deleteLater()

    def __repr__(self) -> str:
        return f"<tracked thread {self._thread!r}>"


class _ChildEntry:
    """A child process admitted through ``start_owned_child``: alive until its ``alive`` callable says
    the process exited (the owner's own finished handler clears whatever that callable reads)."""

    def __init__(self, cancel: Callable[[], None] | None, alive: Callable[[], bool], label: str) -> None:
        self._cancel = cancel
        self._alive = alive
        self._label = label
        self.started = False

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel()

    def alive(self) -> bool:
        return True if not self.started else bool(self._alive())

    def __repr__(self) -> str:
        return f"<child process {self._label}>"


class WorkerRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: list[Any] = []
        self._admission_closed = False
        self._reaper: Any = None

    # ---- admission: once shutdown began, nothing may start ------------------------------------

    @property
    def admission_closed(self) -> bool:
        return self._admission_closed

    def close_admission(self) -> None:
        """Refuse every later ``start_owned``.  Idempotent; entries admitted earlier are untouched."""
        require_gui_thread("close_admission")
        with self._lock:
            self._admission_closed = True

    def open_admission(self) -> None:
        """Accept starts again: a new ``main.run`` (and tests) begin with admission open."""
        with self._lock:
            self._admission_closed = False

    def start_owned(self, thread: Any, cancel: Callable[[], None] | None = None, *,
                    dispose: bool = False) -> bool:
        """Register ``thread`` and start it in one step, unless admission is closed.

        ``False`` means refused: the thread was NOT started and is not registered; the caller undoes
        its own state and drops its references.  The refused thread is discarded here (its signal
        connections are cut and it is queued for deletion on the GUI thread: it never emitted
        ``finished``, so nothing else would ever clean it up).  ``cancel`` must be non-blocking and
        idempotent: the quit gate calls it on every poll pass.  ``dispose=True``: the registry deletes
        the QThread once it has exited (the caller must NOT connect ``finished`` to ``deleteLater``).
        GUI thread only."""
        require_gui_thread("start_owned")
        entry = _ThreadEntry(thread, cancel, dispose)
        # Finished thread entries are swept here and in ``alive()``, on the caller's (GUI) thread.
        # No ``finished`` connection drops them: that signal is emitted on the worker thread itself,
        # and releasing the last reference to the QThread wrapper from inside its own thread aborts
        # the process ("Destroyed while thread is still running").
        self._sweep()
        with self._lock:
            if self._admission_closed:
                logger.warning("worker start refused: shutdown in progress (%r)", thread)
                refused = True
            else:
                refused = False
                self._workers.append(entry)
        if refused:
            self._discard_unstarted(thread)
            return False
        if dispose:
            self._connect_reaper(thread)
        try:
            thread.start()
        except BaseException:
            self.unregister(entry)
            raise
        entry.started = True
        return True

    def start_owned_child(self, start: Callable[[], None], alive: Callable[[], bool],
                          cancel: Callable[[], None] | None = None, *, label: str = "child") -> bool:
        """Admission for a child PROCESS: register, then call ``start()``, unless admission is closed.

        ``False``: refused, ``start`` was not called.  The entry stays alive until ``alive()`` is
        False, i.e. until the owner's own finished handling saw the process exit; ``cancel`` is
        repeated on every poll pass like a thread's.  GUI thread only."""
        require_gui_thread("start_owned_child")
        entry = _ChildEntry(cancel, alive, label)
        self._sweep()
        with self._lock:
            if self._admission_closed:
                logger.warning("child start refused: shutdown in progress (%s)", label)
                return False
            self._workers.append(entry)
        try:
            start()
        except BaseException:
            self.unregister(entry)
            raise
        entry.started = True
        return True

    @staticmethod
    def _discard_unstarted(thread: Any) -> None:
        """A refused thread never ran: cut its connections (a ``finished`` lambda capturing the thread
        and its owner is a reference cycle) and queue its deletion on the GUI thread."""
        import shiboken6

        if not shiboken6.isValid(thread):
            return
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # "Failed to disconnect": nothing connected
            for signal_name in ("started", "finished"):
                try:
                    getattr(thread, signal_name).disconnect()
                except (RuntimeError, TypeError):
                    pass
        thread.deleteLater()

    # ---- GUI-side deletion of finished threads -------------------------------------------------

    def _connect_reaper(self, thread: Any) -> None:
        from PySide6.QtCore import QObject, QTimer, Slot

        if self._reaper is None:
            registry = self

            class _Reaper(QObject):
                """Lives on the GUI thread; ``finished`` reaches it as a queued call."""

                def __init__(self) -> None:
                    super().__init__()
                    self._armed = False

                @Slot()
                def sweep(self) -> None:
                    self._armed = False
                    if registry._sweep() and not self._armed:
                        # A finished thread is still inside a handler: look again shortly.
                        self._armed = True
                        QTimer.singleShot(20, self.sweep)

            self._reaper = _Reaper()
        thread.finished.connect(self._reaper.sweep)

    def _sweep(self) -> bool:
        """Drop finished thread entries, deleting the ``dispose`` ones; ``True`` when a thread has
        emitted ``finished`` but is still inside a handler (a later sweep must look again)."""
        require_gui_thread("sweep")
        waiting = False
        for entry in self.registered():
            if not isinstance(entry, (_ThreadEntry, _ChildEntry)):
                continue
            if not entry.alive():
                self.unregister(entry)
                if isinstance(entry, _ThreadEntry):
                    entry.dispose()
            elif isinstance(entry, _ThreadEntry) and entry.awaiting_exit():
                waiting = True
        return waiting

    # ---- registration --------------------------------------------------------------------------

    def register(self, worker: Any) -> None:
        with self._lock:
            if not any(w is worker for w in self._workers):
                self._workers.append(worker)

    def unregister(self, worker: Any) -> None:
        with self._lock:
            self._workers = [w for w in self._workers if w is not worker]

    def registered(self) -> list[Any]:
        with self._lock:
            return list(self._workers)

    def cancel_all(self, repeat: bool = False) -> None:
        """Ask every entry to stop, without waiting.  Safe to repeat (the quit gate does, so an entry
        admitted before admission closed is cancelled too).  A failing ``cancel`` is logged (at debug
        on a repeat pass) and the entry stays registered: only ``alive()`` decides whether it is done."""
        for worker in self.registered():
            try:
                worker.cancel()
            except Exception:
                logger.log(logging.DEBUG if repeat else logging.WARNING,
                           "worker cancel failed: %r", worker, exc_info=True)

    def alive(self) -> list[Any]:
        """The entries still running.  An entry whose ``alive()`` is False is dropped (a ``dispose``
        thread is queued for deletion); one whose ``alive()`` raises is treated as running (it is
        never assumed done).  GUI thread only: dropping an entry releases its QThread wrapper."""
        require_gui_thread("alive")
        running: list[Any] = []
        for worker in self.registered():
            try:
                is_alive = bool(worker.alive())
            except Exception:
                logger.warning("worker alive() failed: %r", worker, exc_info=True)
                is_alive = True
            if is_alive:
                running.append(worker)
            else:
                self.unregister(worker)
                if isinstance(worker, _ThreadEntry):
                    worker.dispose()
        return running


_REGISTRY = WorkerRegistry()


def get_registry() -> WorkerRegistry:
    """The application-wide registry."""
    return _REGISTRY
