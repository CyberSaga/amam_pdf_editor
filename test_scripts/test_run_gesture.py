"""run_gesture (A6.8 review): the deadline starts before the gesture, a late answer fails, and the
pump keeps running after ``done`` so work the answer queued is measured."""
from __future__ import annotations

from test_scripts.gui_stall_probe import run_gesture


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep_ms(self, ms: int) -> None:
        self.now += ms / 1000.0


class _App:
    def __init__(self, clock: _Clock, on_pump=None) -> None:
        self.clock = clock
        self.pumps = 0
        self.on_pump = on_pump

    def processEvents(self) -> None:  # noqa: N802 (Qt name)
        self.pumps += 1
        if self.on_pump:
            self.on_pump(self)


def test_a_gesture_that_eats_the_timeout_fails_even_if_it_is_done_afterwards(qapp):
    clock = _Clock()
    app = _App(clock)
    state = {"done": False}

    def gesture():
        clock.now += 10.0  # blocks past the whole timeout
        state["done"] = True

    gap, finished = run_gesture(
        app, gesture, lambda: state["done"], timeout_s=5.0, clock=clock, sleep_ms=clock.sleep_ms
    )
    assert finished is False


def test_an_answer_delivered_by_a_pump_after_the_deadline_fails(qapp):
    clock = _Clock()
    state = {"done": False, "armed": False}

    def on_pump(app):
        if state["armed"]:
            clock.now += 100.0  # the pump itself blocks past the deadline
            state["done"] = True

    app = _App(clock, on_pump)
    gap, finished = run_gesture(
        app,
        lambda: state.update(armed=True),
        lambda: state["done"],
        timeout_s=1.0,
        clock=clock,
        sleep_ms=clock.sleep_ms,
    )
    assert finished is False


def test_an_answer_inside_the_deadline_finishes_and_the_loop_keeps_pumping_after_it(qapp):
    clock = _Clock()
    app = _App(clock)
    state = {"done": False}
    pumps_at_done: list[int] = []

    def done():
        if state["done"] and not pumps_at_done:
            pumps_at_done.append(app.pumps)
        return state["done"]

    def on_pump(a):
        if a.pumps >= 30:
            state["done"] = True

    app.on_pump = on_pump
    gap, finished = run_gesture(
        app, lambda: None, done, timeout_s=5.0, settle_ms=60.0, clock=clock, sleep_ms=clock.sleep_ms
    )
    assert finished is True
    assert app.pumps - pumps_at_done[0] >= 60  # 60 ms at 1 ms per pump


def test_a_blocking_slot_queued_by_the_answer_counts_toward_the_gap(qapp):

    clock = _Clock()
    state = {"done": False, "fired": False}

    def on_pump(a):
        if a.pumps >= 30:
            state["done"] = True
        if state["done"] and not state["fired"] and a.pumps >= 40:
            state["fired"] = True
            clock.now += 0.5  # a 500 ms redraw in the settle window

    app = _App(clock, on_pump)
    # The real QTimer heartbeat ticks inside a real processEvents; drive it by hand here.
    real_pump = app.processEvents

    def pump():
        real_pump()
        qapp.processEvents()

    app.processEvents = pump  # type: ignore[method-assign]
    gap, finished = run_gesture(
        app, lambda: None, lambda: state["done"], timeout_s=5.0, settle_ms=60.0, clock=clock, sleep_ms=clock.sleep_ms
    )
    assert finished is True
    assert state["fired"] is True
    assert gap >= 400.0


def test_work_dispatched_by_the_final_pump_counts_toward_the_gap(qapp):
    clock = _Clock()
    state = {"done_at": None, "fired": False}

    def done():
        if state["done_at"] is None and app.pumps >= 30:
            state["done_at"] = clock.now
        return state["done_at"] is not None

    app = _App(clock)

    def pump():
        app.pumps += 1
        qapp.processEvents()  # the real heartbeat ticks here, before the block below
        at = state["done_at"]
        # settle pumps run only while clock < done_at + 60 ms, so this is the final pump
        if at is not None and not state["fired"] and clock.now >= at + 0.06:
            state["fired"] = True
            clock.now += 0.5  # work this pump dispatched, after the heartbeat tick

    app.processEvents = pump  # type: ignore[method-assign]
    gap, finished = run_gesture(
        app, lambda: None, done, timeout_s=5.0, settle_ms=60.0, clock=clock, sleep_ms=clock.sleep_ms
    )
    assert finished is True
    assert state["fired"] is True
    assert gap >= 400.0


def test_a_stale_dropped_signal_does_not_finish_while_a_text_job_is_pending(qapp):
    from PySide6.QtCore import QObject, Signal

    from test_scripts.gui_stall_probe import CombinedAnswerWatch

    class _Probe(QObject):
        text_index_ready = Signal(int)
        probe_failed = Signal(str, int, str)
        probe_dropped = Signal(str, int)
        table_ready = Signal(int)

        def __init__(self) -> None:
            super().__init__()
            self.pending = True

        def has_pending_text(self, page_num: int) -> bool:
            return self.pending

    probe = _Probe()
    watch = CombinedAnswerWatch.__new__(CombinedAnswerWatch)
    watch._probe = probe
    watch.page_num = 0

    class _Done:
        def done(self) -> bool:
            return True

        def reset(self) -> None:
            pass

    from test_scripts.gui_stall_probe import TextAnswerWatch

    watch.tables = _Done()
    watch.text = TextAnswerWatch(probe, 0)
    probe.probe_dropped.emit("text", 0)  # a stale job of the same page
    assert watch.done() is False
    probe.text_index_ready.emit(0)
    assert watch.done() is True
    watch.reset()
    probe.pending = False
    assert watch.done() is True  # nothing requested, nothing pending
