from __future__ import annotations

import re
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from utils.qt_workers import retire_worker_with

ROOT = Path(__file__).resolve().parents[1]


class _Worker(QObject):
    finished = Signal()

    @Slot()
    def run(self) -> None:
        self.finished.emit()


def _wait(qapp: QApplication, predicate, timeout_ms: int = 5000) -> bool:
    deadline = timeout_ms / 1000.0
    timer = threading.Event()
    elapsed = 0.0
    while not predicate() and elapsed < deadline:
        qapp.processEvents()
        timer.wait(0.005)
        elapsed += 0.005
    qapp.processEvents()
    return predicate()


def test_retired_worker_is_destroyed_on_the_gui_thread_after_its_thread_finished(qapp):
    destroyed_on: list[int] = []
    thread = QThread()
    worker = _Worker()
    worker.moveToThread(thread)
    worker.destroyed.connect(lambda *_: destroyed_on.append(threading.get_ident()), Qt.ConnectionType.DirectConnection)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    retire_worker_with(thread, worker)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    del worker
    assert _wait(qapp, lambda: bool(destroyed_on))
    assert destroyed_on == [threading.get_ident()]


def test_retired_worker_survives_until_its_thread_finishes(qapp):
    gate = threading.Event()

    class Blocking(_Worker):
        @Slot()
        def run(self) -> None:
            gate.wait(5)
            self.finished.emit()

    destroyed: list[bool] = []
    thread = QThread()
    worker = Blocking()
    worker.moveToThread(thread)
    worker.destroyed.connect(lambda *_: destroyed.append(True), Qt.ConnectionType.DirectConnection)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    retire_worker_with(thread, worker)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    del worker
    qapp.processEvents()
    QTimer.singleShot(0, lambda: None)
    qapp.processEvents()
    assert destroyed == [], "the last Python reference was dropped while the worker's thread still ran it"
    gate.set()
    assert _wait(qapp, lambda: bool(destroyed))


def test_no_worker_schedules_its_own_deferred_delete_from_its_thread():
    # A worker moved to a QThread that connects its own finished signal to
    # deleteLater is destroyed by the worker thread's event processing; its Python
    # wrapper then needs the GIL while Qt's signal-slot mutex is held, and the GUI
    # thread (holding the GIL) waits on that mutex: a rare freeze (PITFALLS).
    pattern = re.compile(r"worker\.finished\.connect\(\s*worker\.deleteLater\s*\)")
    offenders = []
    for folder in ("controller", "view", "model", "utils", "src"):
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "moveToThread" in text and pattern.search(text):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
