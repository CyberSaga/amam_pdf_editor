"""The one owner of controller-created background workers that can outlive a window.

Class closed here: a worker thread still running when the event loop exits because the object that
owned it (a window context, a retired primary controller) was no longer reachable from teardown.
A worker registers itself at creation and unregisters when it has been shut down and is idle;
application teardown drains THIS registry, not the window contexts.

A registered worker provides ``shutdown(timeout_ms) -> bool``: cancel everything, wait at most
``timeout_ms`` and answer ``True`` when no thread of it is running afterwards.  Qt-free on purpose
(no widgets, no Model); the workers bring their own QThreads.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

#: total wait of one teardown drain
DEFAULT_DRAIN_TIMEOUT_MS = 5000


class WorkerRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: list[Any] = []

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

    def shutdown_all(self, timeout_ms: int = DEFAULT_DRAIN_TIMEOUT_MS) -> list[Any]:
        """Cancel every registered worker and wait up to ``timeout_ms`` in total.  Returns the workers
        still alive (they stay registered, so a later drain waits for them again).  Safe to call
        repeatedly; every call is a fresh pass."""
        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
        survivors: list[Any] = []
        for worker in self.registered():
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            try:
                done = bool(worker.shutdown(remaining_ms))
            except RuntimeError:
                done = True  # the Qt object is already deleted: nothing of it can still run
            except Exception:
                logger.warning("worker shutdown failed: %r", worker, exc_info=True)
                done = False
            if done:
                self.unregister(worker)
            else:
                survivors.append(worker)
        return survivors


_REGISTRY = WorkerRegistry()


def get_registry() -> WorkerRegistry:
    """The application-wide registry."""
    return _REGISTRY
