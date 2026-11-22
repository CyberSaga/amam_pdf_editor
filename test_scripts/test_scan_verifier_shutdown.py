"""R1 (Astra round 4): the verification worker never outlives application shutdown.

Class: a QThread still running when the event loop exits.  Outcome checks: after ``shutdown`` /
``retire_background`` the worker thread is finished, it returned quickly (the lex is cooperative),
nothing was recorded, and Qt printed no 'QThread: Destroyed while thread is still running'.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler

import view.pdf_view as pdf_view
from controller.object_probe_coordinator import ObjectProbeCoordinator
from controller.scan_verifier import START_DELAY_MS
from model import content_scan
from model.content_scan import ScanStopped, content_key, scan_stream
from model.pdf_model import PDFModel
from test_scripts.test_scan_verification import _build, _open, _pump_until, _stream


@pytest.fixture(autouse=True)
def _worker_admission_open():
    """A test that ran main's teardown closed thread admission process-wide: reopen it."""
    from controller.worker_registry import get_registry

    get_registry().open_admission()
    yield
    get_registry().open_admission()


@pytest.fixture(scope="module")
def seven_mb_pdf(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("shutdown7") / "seven.pdf"
    _build(path, 330_000)
    return path


@pytest.fixture
def qt_messages():
    messages: list[str] = []
    def capture(_mode, _ctx, msg):
        messages.append(msg)
        if "QThread" in msg:
            sys.__stderr__.write(f"QT: {msg}\n")
            sys.__stderr__.flush()

    previous = qInstallMessageHandler(capture)
    yield messages
    qInstallMessageHandler(previous)


def _start_lexing(qapp, coordinator: ObjectProbeCoordinator, model: PDFModel):
    stream = _stream(model)
    key = content_key(stream)
    assert coordinator.request_verification(1, key, stream)
    assert _pump_until(qapp, lambda: coordinator.scan_verifier._running is not None, 10.0)
    worker = coordinator.scan_verifier._running
    assert worker.isRunning()
    time.sleep(0.05)  # lexing now
    return key, worker


def _flush_deletes(qapp) -> None:
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def test_scan_stream_stops_when_asked_and_is_unchanged_when_never_stopped():
    stream = b"q 1 0 0 1 0 0 cm /A Do Q\n" * 5_000
    assert scan_stream(stream, lambda: False) == scan_stream(stream)
    asked: list[int] = []

    def stop_now() -> bool:
        asked.append(1)
        return True

    with pytest.raises(ScanStopped):
        scan_stream(stream, stop_now)
    assert len(asked) == 1  # stopped at the first check, not after the whole stream


def test_shutdown_with_nothing_running_returns_true_at_once(qapp):
    coordinator = ObjectProbeCoordinator(PDFModel())
    started = time.perf_counter()
    assert coordinator.scan_verifier.shutdown(1000) is True
    assert time.perf_counter() - started < 0.2
    assert not coordinator.scan_verifier.is_busy()


def test_shutdown_while_lexing_finishes_the_worker_quickly_and_records_nothing(qapp, seven_mb_pdf, qt_messages):
    model = _open(seven_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        key, worker = _start_lexing(qapp, coordinator, model)
        started = time.perf_counter()
        assert coordinator.scan_verifier.shutdown(5000) is True
        elapsed = time.perf_counter() - started
        assert worker.isFinished() and not worker.isRunning()
        assert elapsed < 0.5, f"{elapsed * 1000:.0f} ms: the lex did not stop cooperatively (a full lex is ~1 s)"
        assert content_scan.verified_scan(key) is None
        assert not coordinator.scan_verifier.is_busy()
        assert not coordinator.scan_verifier._queue
        assert coordinator.scan_verifier.request(model.handle_generation, 1, key, _stream(model)) is False  # shut down: no new work
        coordinator.scan_verifier.deleteLater()
        _flush_deletes(qapp)
        qapp.processEvents()
        assert content_scan.verified_scan(key) is None  # the finished signal did not store a result
        assert not [m for m in qt_messages if "Destroyed while thread is still running" in m]
    finally:
        model.close()


def test_shutdown_is_bounded_when_a_lex_cannot_stop_and_reports_it(qapp, seven_mb_pdf, monkeypatch):
    model = _open(seven_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    release = {"go": False}
    real = content_scan.scan_stream

    def stubborn(stream, should_stop=None):
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and not release["go"]:
            time.sleep(0.01)  # ignores should_stop
        return real(b"")

    monkeypatch.setattr(content_scan, "scan_stream", stubborn)
    try:
        _key, worker = _start_lexing(qapp, coordinator, model)
        started = time.perf_counter()
        assert coordinator.scan_verifier.shutdown(150) is False
        assert time.perf_counter() - started < 1.0
        assert worker.isRunning()
    finally:
        release["go"] = True
        worker.wait(5000)
        _flush_deletes(qapp)
        model.close()


def test_controller_retire_background_cancels_an_active_verification(qapp, seven_mb_pdf, qt_messages, monkeypatch):
    from controller.pdf_controller import PDFController
    from test_scripts.qt_teardown import dispose_pdf_view

    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel()
    view = pdf_view.PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    try:
        content_scan.clear_scan_cache()
        controller.open_pdf(str(seven_mb_pdf))
        stream = _stream(model)
        key = content_key(stream)
        verifier = controller._object_probe.scan_verifier
        assert verifier.request(model.handle_generation, 1, key, stream)
        assert _pump_until(qapp, lambda: verifier._running is not None, 10.0)
        worker = verifier._running
        time.sleep(0.05)
        controller.retire_background()  # non-blocking: the worker stays registered until it finished
        assert worker.wait(5000)
        assert worker.isFinished()
        assert verifier._stopped and not verifier._queue, "retired: nothing new is accepted or queued"
        assert content_scan.verified_scan(key) is None
        assert not [m for m in qt_messages if "Destroyed while thread is still running" in m]
    finally:
        dispose_pdf_view(view)
        model.close()


def test_scan_stream_asks_to_stop_inside_one_very_long_token():
    # one 200 KiB literal then a few tokens: fewer than STOP_CHECK_TOKENS tokens in all
    stream = b"q (" + b"x" * 200_000 + b") Tj Q\n"
    asked: list[int] = []

    def stop_now() -> bool:
        asked.append(1)
        return True

    with pytest.raises(ScanStopped):
        scan_stream(stream, stop_now)
    assert asked


def _stubborn_lex(monkeypatch, release: dict, seconds: float = 1.5) -> None:
    real = content_scan.scan_stream

    def stubborn(stream, should_stop=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not release["go"]:
            time.sleep(0.01)  # ignores should_stop
        return real(b"")

    monkeypatch.setattr(content_scan, "scan_stream", stubborn)


def test_registry_reports_a_stubborn_worker_as_alive_and_later_drops_it(qapp, seven_mb_pdf, monkeypatch):
    from controller.worker_registry import get_registry

    model = _open(seven_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    verifier = coordinator.scan_verifier
    release = {"go": False}
    _stubborn_lex(monkeypatch, release)
    try:
        assert verifier in get_registry().registered()
        _key, worker = _start_lexing(qapp, coordinator, model)
        started = time.perf_counter()
        get_registry().cancel_all()  # non-blocking
        assert time.perf_counter() - started < 0.5
        assert verifier in get_registry().alive(), "a stubborn lex is still running, so still alive"
        assert worker.isRunning()
        release["go"] = True
        assert worker.wait(5000)
        assert verifier not in get_registry().alive()  # a later poll drops it: no permanent latch
        assert verifier not in get_registry().registered()
    finally:
        release["go"] = True
        worker.wait(5000)
        _flush_deletes(qapp)
        model.close()


def test_registry_cancel_stops_a_cooperative_worker_and_alive_goes_empty(qapp, seven_mb_pdf, qt_messages):
    from controller.worker_registry import get_registry

    model = _open(seven_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        _key, worker = _start_lexing(qapp, coordinator, model)
        started = time.perf_counter()
        get_registry().cancel_all()
        assert _pump_until(qapp, lambda: not get_registry().alive(), 5.0)
        assert time.perf_counter() - started < 1.0, "the lex stops cooperatively"
        assert worker.isFinished()
        _flush_deletes(qapp)
        assert not [m for m in qt_messages if "Destroyed while thread is still running" in m]
    finally:
        model.close()


def test_a_fake_worker_whose_cancel_raises_stays_alive_not_a_crash():
    from controller.worker_registry import WorkerRegistry

    class Broken:
        def cancel(self):
            raise ValueError("boom")

        def alive(self):
            return True

    registry = WorkerRegistry()
    broken = Broken()
    registry.register(broken)
    registry.cancel_all()
    assert registry.alive() == [broken]
    assert registry.registered() == [broken]


def _thread_done(thread) -> bool:
    """Not running; a thread already deleted by its verifier (deleteLater after finished) is done."""
    try:
        return not thread.isRunning()
    except RuntimeError:
        return True


def _quiesce_render_threads(qapp, *controllers) -> None:
    """The open of a 7 MB document starts thumbnail and page-render QThreads; let them finish before
    the harness deletes the views (their teardown is not what this test is about)."""
    def idle() -> bool:
        return not any(
            c._thumbnail_coordinator._threads or c._page_render_coordinator._threads for c in controllers
        )

    assert _pump_until(qapp, idle, 30.0), "render threads did not finish"


def _controller_with_verification(qapp, pdf_path):
    from controller.pdf_controller import PDFController

    model = PDFModel()
    view = pdf_view.PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(pdf_path))
    stream = _stream(model)
    verifier = controller._object_probe.scan_verifier
    assert verifier.request(model.handle_generation, 1, content_key(stream), stream)
    assert _pump_until(qapp, lambda: verifier._running is not None, 10.0)
    return model, view, controller, verifier


def test_promotion_then_immediate_close_waits_for_both_workers(qapp, seven_mb_pdf, qt_messages, monkeypatch):
    """The primary window closes while it verifies, a secondary is promoted and closed at once: the
    retired primary's worker is still joined by teardown."""
    import main
    from test_scripts.qt_teardown import dispose_pdf_view

    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    content_scan.clear_scan_cache()
    startup = main.run(argv=[str(seven_mb_pdf)], start_event_loop=False)
    primary_view = startup["view"]
    primary_controller = startup["controller"]
    primary_verifier = primary_controller._object_probe.scan_verifier
    stream = _stream(startup["model"])
    assert primary_verifier.request(startup["model"].handle_generation, 1, content_key(stream), stream)
    assert _pump_until(qapp, lambda: primary_verifier._running is not None, 10.0)
    primary_worker = primary_verifier._running
    model2, view2, controller2, verifier2 = _controller_with_verification(qapp, seven_mb_pdf)
    secondary_worker = verifier2._running
    startup["secondary_windows"].append({"view": view2, "model": model2, "controller": controller2})
    try:
        primary_view.close()
        _pump_until(qapp, lambda: startup["view"] is view2, 5.0)
        assert startup["view"] is view2, "the secondary was promoted"
        time.sleep(0.05)
        qapp._pdf_owned_shutdown()  # the promoted window closes at once: lastWindowClosed (one request)
        assert _pump_until(qapp, lambda: _thread_done(primary_worker) and _thread_done(secondary_worker), 10.0)
        assert not [m for m in qt_messages if "Destroyed while thread is still running" in m]
    finally:
        for stale in (primary_worker, secondary_worker):
            if not _thread_done(stale):
                stale.wait(5000)
        _quiesce_render_threads(qapp, primary_controller, controller2)
        view2.close()
        primary_view.close()
        dispose_pdf_view(view2)
        model2.close()
        _flush_deletes(qapp)
        qapp.setStyleSheet("")


def test_real_teardown_cancels_every_pass_and_polls_every_registered_worker_wherever_it_is_held(qapp, monkeypatch):
    """Executes main's own teardown function: every registered worker is cancelled, including one no
    window context holds, again on every poll pass (cheap, idempotent: it reaches entries admitted
    after the first pass), and the gate polls (no blocking wait) until none is alive."""
    import main
    from controller.worker_registry import get_registry

    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    startup = main.run(argv=[], start_event_loop=False)

    class Fake:
        def __init__(self, alive_polls: int) -> None:
            self.cancels = 0
            self.polls = 0
            self.alive_polls = alive_polls

        def cancel(self) -> None:
            self.cancels += 1

        def alive(self) -> bool:
            self.polls += 1
            return self.polls <= self.alive_polls

    orphan, stubborn = Fake(0), Fake(5)  # held by no window context at all
    registry = get_registry()
    registry.register(orphan)
    registry.register(stubborn)
    try:
        qapp._pdf_owned_shutdown()
        assert orphan.cancels == 1 and stubborn.cancels == 1
        assert _pump_until(qapp, lambda: stubborn not in registry.registered(), 10.0)
        assert stubborn.polls > 5 and stubborn.cancels > 1, "polled until finished, cancelled on each pass"
        assert orphan not in registry.registered()
    finally:
        registry.unregister(orphan)
        registry.unregister(stubborn)
        startup["view"].close()
        qapp.processEvents()
        qapp.setStyleSheet("")


def test_start_delay_is_positive():
    assert START_DELAY_MS > 0
