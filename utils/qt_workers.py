"""Helpers for QObject workers that run in a QThread.

A worker whose own ``finished`` signal is connected to its own ``deleteLater`` is
destroyed by its worker thread's event processing. Its Python wrapper must then take
the GIL while Qt's signal-slot mutex (a small pool shared by many objects) is held; if
the GUI thread, which holds the GIL, needs the same pooled mutex for an unrelated
``connect``/``disconnect`` (for example ``QMenu.addAction``), both threads wait forever.
``retire_worker_with`` keeps the worker alive until its thread has finished and then
drops the last reference on the GUI thread, where destruction already holds the GIL.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Slot

_retirements: set[_Retirement] = set()


class _Retirement(QObject):
    """GUI-thread owner of one finished worker; releasing it destroys the worker."""

    def __init__(self, worker: QObject) -> None:
        super().__init__()
        self._worker: QObject | None = worker

    @Slot()
    def release(self) -> None:
        self._worker = None
        _retirements.discard(self)
        self.deleteLater()


def retire_worker_with(thread: QThread, worker: QObject) -> _Retirement:
    """Destroy ``worker`` on the GUI thread once ``thread`` has finished.

    Call from the GUI thread, in place of ``worker.finished.connect(worker.deleteLater)``.
    Returns the retirement: a caller whose start was refused (the thread never runs, so never
    emits ``finished``) calls ``release()`` on it, or the retirement leaks.
    """
    retirement = _Retirement(worker)
    _retirements.add(retirement)
    thread.finished.connect(retirement.release)
    return retirement
