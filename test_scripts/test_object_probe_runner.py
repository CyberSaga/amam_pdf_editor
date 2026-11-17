"""Card A3 (plans/cad-vector-object-editing-handoff.md): the App-wide one-shot child runner (H2, H16)."""
from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QObject, QProcess, Signal

from src.render_worker.memory import SystemMemory


class FakeProcess(QObject):
    """Stands in for QProcess: the test drives started / stdout / finished by hand."""

    started = Signal()
    readyReadStandardOutput = Signal()
    finished = Signal(int, QProcess.ExitStatus)
    errorOccurred = Signal(QProcess.ProcessError)
    instances: list[FakeProcess] = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.args = None
        self.written = bytearray()
        self.closed = False
        self.killed = False
        self.out = b""
        FakeProcess.instances.append(self)

    def setProgram(self, program):
        self.program = program

    def setArguments(self, args):
        self.args = list(args)

    def start(self):
        pass

    def write(self, data):
        self.written.extend(bytes(data))

    def closeWriteChannel(self):
        self.closed = True

    def readAllStandardOutput(self):
        data, self.out = self.out, b""
        return data

    def kill(self):
        self.killed = True

    def answer(self, payload: dict, code: int = 0):
        self.out = json.dumps(payload).encode("utf-8") + b"\n"
        self.readyReadStandardOutput.emit()
        self.finished.emit(code, QProcess.ExitStatus.NormalExit)


GIB = 1024 ** 3
OK_MEMORY = SystemMemory(total_phys=32 * GIB, avail_phys=24 * GIB, avail_commit=24 * GIB)
COMPLETE = {"v": 2, "status": "complete", "rects": []}


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch):
    FakeProcess.instances = []
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: OK_MEMORY)
    yield
    FakeProcess.instances = []


def _runner(qapp, **kwargs):
    from controller.object_probe_runner import ObjectProbeRunner

    return ObjectProbeRunner(qapp, process_factory=FakeProcess, **kwargs)


def test_submit_starts_at_once_when_idle_and_writes_the_protocol(qapp):
    runner = _runner(qapp)
    job = runner.submit(object(), "tables", (b"AAA", b"BB"))
    assert len(FakeProcess.instances) == 1
    proc = FakeProcess.instances[0]
    proc.started.emit()
    header, _, rest = bytes(proc.written).partition(b"\n")
    from src.render_worker.admission import object_probe_memory_limit

    assert json.loads(header) == {
        "v": 2, "kind": "tables", "sizes": [3, 2], "mem": object_probe_memory_limit(OK_MEMORY),
    }
    assert rest == b"AAABB"
    assert proc.closed is True
    got = []
    runner.finished.connect(lambda i, ans: got.append((i, ans)))
    proc.answer(COMPLETE)
    assert got == [(job, COMPLETE)]


def test_jobs_run_one_at_a_time_in_fifo_order(qapp):
    runner = _runner(qapp)
    done = []
    runner.finished.connect(lambda i, ans: done.append(i))
    owner = object()
    a = runner.submit(owner, "tables", (b"a",))
    b = runner.submit(owner, "tables", (b"b",))
    c = runner.submit(owner, "tables", (b"c",))
    assert len(FakeProcess.instances) == 1
    FakeProcess.instances[0].started.emit()
    FakeProcess.instances[0].answer(COMPLETE)
    assert len(FakeProcess.instances) == 2
    FakeProcess.instances[1].started.emit()
    assert b"b" in bytes(FakeProcess.instances[1].written)
    FakeProcess.instances[1].answer(COMPLETE)
    FakeProcess.instances[2].started.emit()
    FakeProcess.instances[2].answer(COMPLETE)
    assert done == [a, b, c]


def test_cancel_of_a_waiting_job_drops_it(qapp):
    runner = _runner(qapp)
    done = []
    runner.finished.connect(lambda i, ans: done.append(i))
    owner = object()
    a = runner.submit(owner, "tables", (b"a",))
    b = runner.submit(owner, "tables", (b"b",))
    assert runner.is_waiting(b) is True and runner.is_waiting(a) is False
    runner.cancel(b)
    assert runner.is_waiting(b) is False
    FakeProcess.instances[0].started.emit()
    FakeProcess.instances[0].answer(COMPLETE)
    assert len(FakeProcess.instances) == 1
    assert done == [a]


def test_cancel_of_the_running_job_kills_it_and_stays_silent(qapp):
    runner = _runner(qapp)
    done, failed = [], []
    runner.finished.connect(lambda i, ans: done.append(i))
    runner.failed.connect(failed.append)
    owner = object()
    a = runner.submit(owner, "tables", (b"a",))
    b = runner.submit(owner, "tables", (b"b",))
    runner.cancel(a)
    assert FakeProcess.instances[0].killed is True
    FakeProcess.instances[0].finished.emit(1, QProcess.ExitStatus.CrashExit)
    assert done == [] and failed == []
    assert len(FakeProcess.instances) == 2  # the waiting job moves on
    FakeProcess.instances[1].started.emit()
    FakeProcess.instances[1].answer(COMPLETE)
    assert done == [b]


def test_cancel_owner_drops_waiting_and_kills_running_of_that_owner_only(qapp):
    runner = _runner(qapp)
    done = []
    runner.finished.connect(lambda i, ans: done.append(i))
    one, two = object(), object()
    runner.submit(one, "tables", (b"a",))
    runner.submit(one, "tables", (b"b",))
    c = runner.submit(two, "tables", (b"c",))
    runner.cancel_owner(one)
    assert FakeProcess.instances[0].killed is True
    FakeProcess.instances[0].finished.emit(1, QProcess.ExitStatus.CrashExit)
    assert len(FakeProcess.instances) == 2
    FakeProcess.instances[1].started.emit()
    FakeProcess.instances[1].answer(COMPLETE)
    assert done == [c]


@pytest.mark.parametrize(
    "code,out",
    [
        (3, b'{"v":2,"status":"complete","rects":[]}\n'),
        (0, b"not json\n"),
        (0, b""),
        (0, b'{"v":1,"rects":[]}\n'),
        (0, b'{"v":2,"status":"bogus"}\n'),
        (0, b'{"v":2,"status":"complete"}\n'),
        (0, b'{"v":2,"status":"analysis_failed","rects":[]}\n'),
    ],
)
def test_failure_is_a_bad_exit_code_or_unparsable_or_wrong_version_or_bad_status(qapp, code, out):
    runner = _runner(qapp)
    failed, done = [], []
    runner.failed.connect(failed.append)
    runner.finished.connect(lambda i, ans: done.append(i))
    job = runner.submit(object(), "tables", (b"a",))
    proc = FakeProcess.instances[0]
    proc.out = out
    proc.readyReadStandardOutput.emit()
    proc.finished.emit(code, QProcess.ExitStatus.NormalExit)
    assert failed == [job] and done == []


def test_advisory_text_around_the_answer_line_is_ignored(qapp):
    runner = _runner(qapp)
    got = []
    runner.finished.connect(lambda i, ans: got.append(ans))
    runner.submit(object(), "tables", (b"a",))
    proc = FakeProcess.instances[0]
    proc.out = b'{"v": 2, "status": "complete", "rects": []}\nConsider using the pymupdf_layout package.\r\n'
    proc.readyReadStandardOutput.emit()
    proc.finished.emit(0, QProcess.ExitStatus.NormalExit)
    assert got == [COMPLETE]


@pytest.mark.parametrize("status", ["resource_limited", "analysis_failed", "containment_failed"])
def test_typed_non_complete_answers_are_delivered_without_rects(qapp, status):
    runner = _runner(qapp)
    got = []
    runner.finished.connect(lambda i, ans: got.append(ans))
    runner.submit(object(), "tables", (b"a",))
    FakeProcess.instances[0].answer({"v": 2, "status": status})
    assert got == [{"v": 2, "status": status}]


def test_lease_is_taken_for_the_process_and_released_at_exit(qapp):
    from src.render_worker.admission import object_probe_memory_limit
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=64 * 1024 ** 3)
    runner = _runner(qapp, ledger=ledger)
    runner.submit(object(), "tables", (b"a",))
    limit = object_probe_memory_limit(OK_MEMORY)
    assert ledger.stats()["reserved_bytes"] == limit
    proc = FakeProcess.instances[0]
    proc.started.emit()
    header = json.loads(bytes(proc.written).partition(b"\n")[0])
    assert header["mem"] == limit  # the header's cap equals the lease bytes
    proc.answer(COMPLETE)
    assert ledger.stats()["reserved_bytes"] == 0


def test_no_headroom_starts_no_process_and_answers_no_headroom(qapp, monkeypatch):
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: None)
    runner = _runner(qapp)
    got = []
    runner.finished.connect(lambda i, ans: got.append((i, ans)))
    job = runner.submit(object(), "tables", (b"a",))
    assert FakeProcess.instances == []
    assert got == [(job, {"v": 2, "status": "no_headroom"})]


def test_no_headroom_moves_on_to_the_next_job_when_memory_returns(qapp, monkeypatch):
    readings = [None, OK_MEMORY]
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: readings.pop(0))
    runner = _runner(qapp)
    got = []
    runner.finished.connect(lambda i, ans: got.append((i, ans["status"])))
    first = runner.submit(object(), "tables", (b"a",))
    second = runner.submit(object(), "tables", (b"b",))
    assert got == [(first, "no_headroom")]
    assert len(FakeProcess.instances) == 1
    FakeProcess.instances[0].started.emit()
    FakeProcess.instances[0].answer(COMPLETE)
    assert got[-1] == (second, "complete")


def test_shutdown_with_a_running_child_kills_it_and_stops_after_exit(qapp):
    runner = _runner(qapp)
    stopped = []
    runner.stopped.connect(lambda: stopped.append(True))
    runner.submit(object(), "tables", (b"a",))
    runner.submit(object(), "tables", (b"b",))
    runner.shutdown()
    assert FakeProcess.instances[0].killed is True
    assert stopped == []
    FakeProcess.instances[0].finished.emit(1, QProcess.ExitStatus.CrashExit)
    assert stopped == [True]
    assert len(FakeProcess.instances) == 1  # the waiting job never started


def test_shutdown_when_idle_stops_at_once(qapp):
    runner = _runner(qapp)
    stopped = []
    runner.stopped.connect(lambda: stopped.append(True))
    runner.shutdown()
    assert stopped == [True]


def test_for_app_is_one_runner_per_app(qapp):
    from controller.object_probe_runner import ObjectProbeRunner

    first = ObjectProbeRunner.for_app(qapp)
    try:
        assert ObjectProbeRunner.for_app(qapp) is first
    finally:
        first.shutdown()
        qapp._pdf_object_probe = None


def test_child_is_launched_through_the_shared_helper(qapp):
    from src.render_worker.launch import child_launch

    runner = _runner(qapp)
    runner.submit(object(), "tables", (b"a",))
    proc = FakeProcess.instances[0]
    program, args = child_launch("object-probe")
    assert (proc.program, proc.args) == (program, args)
