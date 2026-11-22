"""The one owner of controller-created background workers that can outlive a window.

Class closed here: a worker thread still running when the event loop exits because the object that
owned it (a window context, a retired primary controller) was no longer reachable from teardown,
or because it was started after shutdown had already begun.  A controller starts its QThread through
``start_owned`` (register + start in one step, refused once shutdown closed admission); other
workers register themselves.  Application teardown asks THIS registry, not the window contexts,
what is still running.

An entry provides two non-blocking calls: ``cancel()`` (ask it to stop; never waits, idempotent) and
``alive() -> bool`` (is anything of it still running).  The quit gate in ``main`` closes admission,
cancels, and polls ``alive()``; nothing here blocks the GUI thread.  Qt-free except for the optional
``shiboken6`` validity check used by the thread adapter.
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


class _ThreadEntry:
    """Adapter of a bare ``QThread`` whose owner drops its own reference before it has finished."""

    def __init__(self, thread: Any, cancel: Callable[[], None] | None) -> None:
        self._thread = thread
        self._cancel = cancel
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

    def __repr__(self) -> str:
        return f"<tracked thread {self._thread!r}>"


class WorkerRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: list[Any] = []
        self._admission_closed = False

    # ---- admission: once shutdown began, no thread may start ----------------------------------

    @property
    def admission_closed(self) -> bool:
        return self._admission_closed

    def close_admission(self) -> None:
        """Refuse every later ``start_owned``.  Idempotent; entries admitted earlier are untouched."""
        with self._lock:
            self._admission_closed = True

    def open_admission(self) -> None:
        """Accept starts again: a new ``main.run`` (and tests) begin with admission open."""
        with self._lock:
            self._admission_closed = False

    def start_owned(self, thread: Any, cancel: Callable[[], None] | None = None) -> bool:
        """Register ``thread`` and start it in one step, unless admission is closed.

        ``False`` means refused: the thread was NOT started and is not registered; the caller undoes
        its own state and drops the thread (it never emitted ``finished``, so nothing else will clean
        it up).  ``cancel`` must be non-blocking and idempotent: the quit gate calls it on every
        poll pass."""
        entry = _ThreadEntry(thread, cancel)
        # Finished thread entries are swept here and in ``alive()``, on the caller's (GUI) thread.
        # No ``finished`` connection drops them: that signal is emitted on the worker thread itself,
        # and releasing the last reference to the QThread wrapper from inside its own thread aborts
        # the process ("Destroyed while thread is still running").
        for stale in self.registered():
            if isinstance(stale, _ThreadEntry) and not stale.alive():
                self.unregister(stale)
        with self._lock:
            if self._admission_closed:
                logger.warning("worker start refused: shutdown in progress (%r)", thread)
                return False
            self._workers.append(entry)
        try:
            thread.start()
        except BaseException:
            self.unregister(entry)
            raise
        entry.started = True
        return True

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
        """The entries still running.  An entry whose ``alive()`` is False is dropped; one whose
        ``alive()`` raises is treated as running (it is never assumed done)."""
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
        return running


_REGISTRY = WorkerRegistry()


def get_registry() -> WorkerRegistry:
    """The application-wide registry."""
    return _REGISTRY
