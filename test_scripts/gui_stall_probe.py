"""H5 harness (plans/cad-vector-object-editing-handoff.md): run a GUI gesture to COMPLETION under a
0 ms heartbeat and report the longest gap between two heartbeats and whether it finished.

The gap includes the gesture's own blocking time: a click that freezes the window for 12 s shows
up as a 12,000 ms gap, however the freeze is split between the handler and what follows it.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QThread, QTimer


def run_gesture(
    app,
    gesture: Callable[[], object],
    done: Callable[[], bool],
    *,
    timeout_s: float = 180.0,
) -> tuple[float, bool]:
    """Return ``(max_gap_ms, finished)``.

    ``gesture`` runs once on the calling (GUI) thread; the event loop is then pumped until
    ``done()`` is true or ``timeout_s`` passes.  ``finished`` is the value of ``done()`` at the end.
    """
    state = {"last": time.perf_counter(), "max": 0.0}

    def tick() -> None:
        now = time.perf_counter()
        state["max"] = max(state["max"], (now - state["last"]) * 1000.0)
        state["last"] = now

    timer = QTimer()
    timer.setInterval(0)
    timer.timeout.connect(tick)
    timer.start()
    try:
        for _ in range(20):  # the heartbeat is running before the gesture starts
            app.processEvents()
            QThread.msleep(1)
        state["last"] = time.perf_counter()
        state["max"] = 0.0
        gesture()
        deadline = time.perf_counter() + timeout_s
        while not done() and time.perf_counter() < deadline:
            app.processEvents()
            QThread.msleep(1)
        app.processEvents()
        return state["max"], bool(done())
    finally:
        timer.stop()
