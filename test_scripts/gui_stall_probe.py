"""H5 harness (plans/cad-vector-object-editing-handoff.md): run a GUI gesture to COMPLETION under a
0 ms heartbeat and report the longest gap between two heartbeats and whether it finished.

The gap includes the gesture's own blocking time: a click that freezes the window for 12 s shows
up as a 12,000 ms gap, however the freeze is split between the handler and what follows it.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QThread, QTimer


class TableAnswerWatch:
    """Settle condition for a gesture that waits for one page's table analysis (card A4).

    Fed by the coordinator's own ``tables_ready`` / ``probe_failed`` signals, so polling ``done`` is
    free.  The earlier predicate (``cached_table_rects`` plus ``table_analysis_failed``) built one
    or two scratch copies of the page per call (about 7 ms each on the CAD sample), which put the
    predicate itself into the measured heartbeat gap.  ``status`` is ``"ready"`` for a stored answer
    or the failure status of ``probe_failed`` (``no_headroom``, ``analysis_failed``, ...).
    ``no_headroom`` marks nothing, so only this signal can tell it from "still running".  A stale
    answer (the page changed meanwhile) emits nothing: the watch keeps waiting and the caller times
    out, which is right, because that is a real bug.
    """

    def __init__(self, probe, page_num: int) -> None:
        self.page_num = int(page_num)
        self.status: str | None = None
        probe.tables_ready.connect(self._on_ready)
        probe.probe_failed.connect(self._on_failed)

    def reset(self) -> None:
        self.status = None

    def done(self) -> bool:
        return self.status is not None

    def _on_ready(self, page_num: int) -> None:
        if int(page_num) == self.page_num:
            self.status = "ready"

    def _on_failed(self, kind: str, page_num: int, status: str) -> None:
        if kind == "tables" and int(page_num) == self.page_num:
            self.status = str(status)


class TextAnswerWatch:
    """Settle condition for a gesture that waits for one page's text index job (card A6.8).

    Same shape as ``TableAnswerWatch``.  ``status`` is ``"ready"`` for ``text_index_ready``, the
    failure status of ``probe_failed`` for kind ``"text"``, or ``"dropped"`` for ``probe_dropped``
    (the job was cancelled or went stale; the gesture's replay logic owns what follows).
    """

    def __init__(self, probe, page_num: int) -> None:
        self.page_num = int(page_num)
        self.status: str | None = None
        probe.text_index_ready.connect(self._on_ready)
        probe.probe_failed.connect(self._on_failed)
        probe.probe_dropped.connect(self._on_dropped)

    def reset(self) -> None:
        self.status = None

    def done(self) -> bool:
        return self.status is not None

    def _on_ready(self, page_num: int) -> None:
        if int(page_num) == self.page_num:
            self.status = "ready"

    def _on_failed(self, kind: str, page_num: int, status: str) -> None:
        if kind == "text" and int(page_num) == self.page_num:
            self.status = str(status)

    def _on_dropped(self, kind: str, page_num: int) -> None:
        if kind == "text" and int(page_num) == self.page_num:
            self.status = "dropped"


class CombinedAnswerWatch:
    """Done when the table answer has arrived and, if the gesture requested a text job, the text
    answer too (card A6.8).

    "Requested" is read from the coordinator: a text job of the page still waiting or running
    keeps the watch open; no job and no answer means the gesture asked for none (an in-process or
    already-built page).  Polling costs a dict scan, no page copy.
    """

    def __init__(self, probe, page_num: int) -> None:
        self._probe = probe
        self.page_num = int(page_num)
        self.tables = TableAnswerWatch(probe, page_num)
        self.text = TextAnswerWatch(probe, page_num)

    @property
    def status(self) -> str | None:
        return self.tables.status

    def reset(self) -> None:
        self.tables.reset()
        self.text.reset()

    def done(self) -> bool:
        if not self.tables.done():
            return False
        return self.text.done() or not self._probe.has_pending_text(self.page_num)


def run_gesture(
    app,
    gesture: Callable[[], object],
    done: Callable[[], bool],
    *,
    timeout_s: float = 180.0,
    settle_ms: float = 60.0,
    clock: Callable[[], float] = time.perf_counter,
    sleep_ms: Callable[[int], object] = QThread.msleep,
) -> tuple[float, bool]:
    """Return ``(max_gap_ms, finished)``.

    ``gesture`` runs once on the calling (GUI) thread; the event loop is then pumped until
    ``done()`` is true.  The deadline starts BEFORE the gesture, and ``finished`` is true only when
    ``done()`` was seen true inside the loop before the deadline: an answer that arrives in a pump
    after the deadline (or after the loop gave up) is a failure, not a result.  Once done, the loop
    keeps pumping for ``settle_ms`` so work the answer queued (a ``call_later`` redraw) runs inside
    the measured window and its blocking time counts toward the longest gap.
    """
    state = {"last": clock(), "max": 0.0}

    def tick() -> None:
        now = clock()
        state["max"] = max(state["max"], (now - state["last"]) * 1000.0)
        state["last"] = now

    timer = QTimer()
    timer.setInterval(0)
    timer.timeout.connect(tick)
    timer.start()
    try:
        for _ in range(20):  # the heartbeat is running before the gesture starts
            app.processEvents()
            sleep_ms(1)
        state["last"] = clock()
        state["max"] = 0.0
        deadline = clock() + timeout_s
        gesture()
        finished = False
        while clock() < deadline:
            if done():
                finished = clock() <= deadline
                break
            app.processEvents()
            sleep_ms(1)
        if finished:
            settle_end = clock() + settle_ms / 1000.0
            while clock() < settle_end:
                app.processEvents()
                sleep_ms(1)
        app.processEvents()
        return state["max"], finished
    finally:
        timer.stop()
