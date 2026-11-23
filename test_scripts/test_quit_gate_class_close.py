"""Quit-gate class closure (Astra round 9): scenarios that each leave an execution resource outside
the gate's accounting.  Every test names the round-9 finding it pins; the repo-wide structural
checks live in test_native_launch_guard.py and the real-process invariant in test_quit_gate_process.py."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QProcess, Signal

from controller.worker_registry import WorkerRegistry, get_registry


@pytest.fixture()
def closed_admission():
    """Shutdown began: admission closed on the global registry; reopened afterwards."""
    from view import ext_b_subset_worker

    registry = get_registry()
    registry.close_admission()
    try:
        yield registry
    finally:
        registry.open_admission()
        ext_b_subset_worker.allow_new_ext_b_threads()


class _Sig:
    def connect(self, *_a, **_k) -> None:
        pass

    def disconnect(self, *_a, **_k) -> None:
        pass


class _StubProcess:
    """A QProcess stand-in that records launches; every signal is a no-op."""

    instances: list[_StubProcess] = []

    def __init__(self, *_a, **_k) -> None:
        self.started_with: tuple | None = None
        self.deleted = False
        self.started = _Sig()
        self.readyReadStandardOutput = _Sig()
        self.finished = _Sig()
        self.errorOccurred = _Sig()
        _StubProcess.instances.append(self)

    def setProgram(self, *_a) -> None:
        pass

    def setArguments(self, *_a) -> None:
        pass

    def start(self, *args) -> None:
        self.started_with = args

    def deleteLater(self) -> None:
        self.deleted = True

    def kill(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_stub():
    _StubProcess.instances = []
    yield
    _StubProcess.instances = []


# ---- P2: a cached probe service must not launch while admission is closed ------------------------


def test_a_held_recent_probe_service_does_not_launch_after_admission_closed(qapp, monkeypatch, closed_admission):
    import controller.recent_file_probe as recent

    monkeypatch.setattr(recent, "QProcess", _StubProcess)
    monkeypatch.setattr(recent, "prepare_owned_qprocess_start", lambda: None)
    probe = recent.RecentFileProbe(qapp)  # a service reference held from before the closure
    probe.request(["a.pdf"])
    assert all(p.started_with is None for p in _StubProcess.instances), "a child launched after closure"
    assert probe._process is None
    probe._closing = True


def test_a_held_object_probe_service_does_not_launch_after_admission_closed(qapp, monkeypatch, closed_admission):
    import controller.object_probe_runner as runner_module

    monkeypatch.setattr(runner_module.object_probe_platform, "contained_probe_supported", lambda: True)
    monkeypatch.setattr(runner_module, "object_probe_memory_limit", lambda _mem: 1 << 20)
    monkeypatch.setattr(runner_module, "read_system_memory", lambda: object())
    monkeypatch.setattr(runner_module, "prepare_owned_qprocess_start", lambda: None)
    runner = runner_module.ObjectProbeRunner(qapp, process_factory=_StubProcess)
    runner.submit(object(), "tables", (b"x",))
    assert all(p.started_with is None for p in _StubProcess.instances), "a child launched after closure"
    assert runner._process is None
    runner._closing = True


# ---- P1: the render child launch itself checks admission -----------------------------------------


def test_render_client_refused_launch_starts_no_child_and_closes_the_client(qapp):
    from src.render_worker.process_client import RenderProcessClient
    from test_scripts.test_render_process_client import FakeProcess, job

    made: list[FakeProcess] = []

    def factory(parent=None):
        process = FakeProcess(parent)
        made.append(process)
        return process

    refusals: list[str] = []

    def refuse(start, alive, cancel=None, *, label="child"):
        refusals.append(label)
        return False

    client = RenderProcessClient(process_factory=factory, child_launcher=refuse)
    results: list[tuple[str, str]] = []
    client.job_done.connect(lambda key, outcome: results.append((key, outcome.status)))
    client.submit(job(client, "queued"))
    qapp.processEvents()
    assert refusals == ["render worker"]
    assert all(not hasattr(p, "args") for p in made), "the child was launched although admission refused it"
    assert client._process is None
    assert [status for _key, status in results] == ["owner_released"]


def test_render_client_admitted_launch_is_alive_until_the_process_is_cleared(qapp):
    from src.render_worker.process_client import RenderProcessClient
    from test_scripts.test_render_process_client import FakeProcess

    entries: list[dict] = []

    def admit(start, alive, cancel=None, *, label="child"):
        entries.append({"alive": alive, "label": label})
        start()
        return True

    client = RenderProcessClient(process_factory=FakeProcess, child_launcher=admit)
    try:
        client.start()
        assert len(entries) == 1 and entries[0]["alive"]() is True
        assert hasattr(client._process, "args")
    finally:
        client.shutdown()


def test_render_pool_passes_the_child_launcher_to_every_child(qapp):
    from src.render_worker.process_client import RenderProcessClient
    from src.render_worker.process_pool import RenderProcessPool
    from test_scripts.test_render_process_client import FakeProcess

    seen: list[dict] = []

    def factory(parent, **extra):
        seen.append(extra)
        return RenderProcessClient(parent, process_factory=FakeProcess, **extra)

    def launcher(start, alive, cancel=None, *, label="child"):
        start()
        return True

    pool = RenderProcessPool(client_factory=factory, child_launcher=launcher)
    try:
        assert seen and seen[0].get("child_launcher") is launcher
    finally:
        pool.shutdown()


# ---- P1: the print runner after the child launched ------------------------------------------------


class _StreamingProcess(QObject):
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    bytesWritten = Signal(int)
    finished = Signal(int, object)
    errorOccurred = Signal(object)
    instances: list[_StreamingProcess] = []

    def __init__(self, *_a, **_k) -> None:
        super().__init__()
        self._state = QProcess.ProcessState.NotRunning
        self.killed = False
        self.fail_write = False
        _StreamingProcess.instances.append(self)

    def setWorkingDirectory(self, _path) -> None:
        pass

    def setProcessEnvironment(self, _env) -> None:
        pass

    def start(self, _program, _args) -> None:
        self._state = QProcess.ProcessState.Running

    def state(self):
        return self._state

    def write(self, data):
        if self.fail_write:
            raise MemoryError("injected post-launch failure")
        return len(data)

    def closeWriteChannel(self) -> None:
        pass

    def kill(self) -> None:
        self.killed = True  # the process is still "running" until finished is emitted

    def readAllStandardOutput(self):
        return b""

    def readAllStandardError(self):
        return b""

    def emit_finished(self, code: int = 1) -> None:
        self._state = QProcess.ProcessState.NotRunning
        self.finished.emit(code, QProcess.ExitStatus.NormalExit)


def _runner(tmp_path, *, pdf_bytes=b"x", fail_write=False):
    from src.printing.base_driver import PrintJobOptions
    from src.printing.helper_protocol import PrintHelperJob
    from src.printing.subprocess_runner import PrintSubprocessRunner

    _StreamingProcess.instances = []

    class Proc(_StreamingProcess):
        def __init__(self, *a, **k) -> None:
            super().__init__(*a, **k)
            self.fail_write = fail_write

    job = PrintHelperJob(job_id="j", input_pdf_path=str(tmp_path / "in.pdf"), watermarks=[],
                         options=PrintJobOptions(printer_name="P"))
    return PrintSubprocessRunner(job, process_factory=Proc, work_dir=str(tmp_path), pdf_bytes=pdf_bytes)


def test_print_runner_keeps_and_terminates_a_child_when_streaming_fails_after_launch(qapp, tmp_path):
    runner = _runner(tmp_path, fail_write=True)
    failures: list[object] = []
    finished: list[int] = []
    runner.failed.connect(failures.append)
    runner.finished.connect(lambda: finished.append(1))
    runner.start()  # must not raise: an exception here would unregister a live child
    process = _StreamingProcess.instances[-1]
    assert process.killed, "the launched child was not asked to stop"
    assert runner._process is process, "the live child must stay owned until it exited"
    assert len(failures) == 1 and finished == []
    process.emit_finished()
    assert finished == [1] and runner._process is None


def test_print_runner_maps_a_requested_termination_to_the_cancellation_outcome(qapp, tmp_path):
    from src.printing.errors import PrintHelperTerminatedError

    runner = _runner(tmp_path)
    failures: list[object] = []
    runner.failed.connect(failures.append)
    runner.start()
    process = _StreamingProcess.instances[-1]
    runner.terminate()
    process.errorOccurred.emit(QProcess.ProcessError.Crashed)  # what a killed child reports on Windows
    process.emit_finished()
    assert [type(f) for f in failures] == [PrintHelperTerminatedError]


def test_print_failure_shows_no_modal_dialog_while_shutting_down(qapp, monkeypatch, closed_admission):
    import controller.print_coordinator as pc
    from src.printing.errors import PrintJobSubmissionError

    shown: list[str] = []
    monkeypatch.setattr(pc, "show_error", lambda _parent, text: shown.append(text))
    coordinator = pc.PrintCoordinator(SimpleNamespace(view=QObject()))
    coordinator._hide_print_progress_dialog = lambda: None
    coordinator._on_print_submission_failed(PrintJobSubmissionError("boom"))
    assert shown == [], "a modal error opened during shutdown"
    closed_admission.open_admission()
    coordinator._on_print_submission_failed(PrintJobSubmissionError("boom"))
    assert len(shown) == 1  # control: the dialog still appears in normal operation


# ---- P2: render refusal reaches the batch owner from every dispatch path ---------------------------


def _render_coordinator(refused):
    from controller.page_render_coordinator import PageRenderCoordinator

    return PageRenderCoordinator(
        result_consumer=lambda *_a: None,
        failure_consumer=lambda *_a: None,
        identity_matches=lambda _identity: True,
        refusal_consumer=refused.append,
    )


def _render_request(page: int, *, document=None, snapshot=b"x"):
    from controller.page_render_coordinator import PageRenderIdentity, PageRenderRequest

    identity = PageRenderIdentity(
        token=f"t{page}", session_id="s", generation=1, revision=0, page_index=page, quality="low",
        rendered_scale=1.0, target_scale=1.0, color_profile="srgb", device_pixel_ratio=1.0,
    )
    return PageRenderRequest(identity=identity, snapshot_bytes=snapshot, document=document)


def test_a_deferred_render_refusal_reaches_the_batch_owner(qapp, closed_admission):
    refused: list[object] = []
    coordinator = _render_coordinator(refused)
    active, queued = _render_request(0), _render_request(1)
    coordinator._active = active
    coordinator._pending = queued  # queued behind the active render; admission closes before dispatch
    coordinator._thread_finished(active.identity.token)
    assert refused == [queued.identity], "the pending request was refused silently"
    assert coordinator.has_active_job is False


def test_a_process_to_thread_fallback_refusal_reaches_the_batch_owner(qapp, closed_admission):
    from src.render_worker.process_client import JobOutcome

    refused: list[object] = []
    coordinator = _render_coordinator(refused)
    document = SimpleNamespace(is_current=lambda: True, snapshot_provider=lambda: b"x", watermarks_json=b"[]")
    request = _render_request(0, document=document, snapshot=None)
    coordinator._active = request
    coordinator._backend = SimpleNamespace(metrics={"fallbacks": 0}, result_consumed=lambda _t: None)
    coordinator._consume_process_reply(request.identity.token, JobOutcome("unavailable"))
    assert refused == [request.identity], "the fallback's refusal was discarded"


def test_a_pool_that_answers_owner_released_after_closure_reaches_the_batch_owner(qapp):
    from src.render_worker.process_client import JobOutcome

    refused: list[object] = []
    coordinator = _render_coordinator(refused)
    request = _render_request(0)
    coordinator._active = request
    coordinator._backend = SimpleNamespace(metrics={"fallbacks": 0}, result_consumed=lambda _t: None)
    coordinator._consume_process_reply(request.identity.token, JobOutcome("owner_released"))
    assert refused == [request.identity]


# ---- P2: alive() is a mutating sweep and obeys the GUI-thread rule --------------------------------


def test_registry_alive_refuses_a_non_gui_caller(qapp):
    registry = WorkerRegistry()
    errors: list[BaseException] = []

    def call() -> None:
        try:
            registry.alive()
        except BaseException as exc:  # noqa: BLE001 - recorded
            errors.append(exc)

    worker = threading.Thread(target=call)
    worker.start()
    worker.join(5)
    assert [type(e) for e in errors] == [RuntimeError]


# ---- P2: a losing single-instance launch must not reopen the previous gate ------------------------


def test_a_losing_single_instance_launch_does_not_reopen_admission(qapp, monkeypatch, closed_admission):
    import main as main_module
    from utils import single_instance

    monkeypatch.setattr(single_instance, "running_instance_alive", lambda *_a, **_k: False)
    monkeypatch.setattr(single_instance, "try_become_server", lambda *_a, **_k: None)
    monkeypatch.setattr(main_module, "_hand_off_to_running_instance", lambda _args: 0)
    assert main_module.run(argv=[]) == 0
    assert closed_admission.admission_closed is True, "a handoff that took no ownership reopened admission"


# ---- P1: the scan verifier's GUI-side callbacks do not wait ---------------------------------------


class _FakeLex:
    def __init__(self) -> None:
        from controller.scan_verifier import _Request

        self.request = _Request(1, 1, b"k", b"s")
        self.scan = None
        self.cancelled = False
        self.waits: list[object] = []
        self.deleted = False
        self.joined = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.joined

    def isRunning(self) -> bool:
        return not self.joined

    def deleteLater(self) -> None:
        self.deleted = True


def test_scan_verifier_finish_callback_never_blocks_the_gui_thread(qapp):
    from controller.scan_verifier import ScanVerifier

    verifier = ScanVerifier(SimpleNamespace(doc=None, handle_generation=0))
    worker = _FakeLex()
    verifier._running = worker
    verifier._stopped = True
    verifier._on_finished(worker)
    assert all(w == 0 for w in worker.waits), f"a GUI-thread wait of {worker.waits}"
    get_registry().unregister(verifier)


def test_scan_verifier_alive_reads_the_join_not_isrunning(qapp):
    from controller.scan_verifier import ScanVerifier

    verifier = ScanVerifier(SimpleNamespace(doc=None, handle_generation=0))
    worker = _FakeLex()
    worker.isRunning = lambda: False  # finished emitted, a direct handler is still running
    verifier._running = worker
    try:
        assert verifier.alive() is True
        worker.joined = True
        assert verifier.alive() is False
    finally:
        verifier._running = None
        get_registry().unregister(verifier)
