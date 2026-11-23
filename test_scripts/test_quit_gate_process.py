"""Worker lifetime at exit (Astra W1-W5, round 7): one invariant, observed in a REAL subprocess.

    Before the ceiling, the gated ``app.exec()`` returns only after every owned worker has finished
    and further starts are refused; past the ceiling the process leaves by ``os._exit`` without the
    exec ever returning.

The child runs ``main.run``'s own gate (``main.run_event_loop``) through the quit routes a user or
Qt can take: last-window close of a real document with a render in flight, a direct ``app.quit()``
and the close of a promoted secondary window, each with a registered worker the parent holds.
The parent watches a GUI heartbeat while the worker is held, releases it, and compares the child's
own monotonic markers: ``worker_finished_1`` must precede ``exec_returned``.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CHILD = r'''
import gc
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
work = Path(sys.argv[2])
mode = sys.argv[3]
ceiling_ms = int(sys.argv[4])
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s %(message)s")


def stamp(name, value=None):
    (work / name).write_text(str(time.perf_counter_ns()) if value is None else str(value))


import controller.worker_registry as worker_registry
worker_registry.QUIT_CEILING_MS = ceiling_ms

real_exit = os._exit


def exit_with_stamp(code):
    stamp("leave_at")
    sys.stderr.flush()
    real_exit(code)


os._exit = exit_with_stamp

import fitz
import main
import shiboken6
from PySide6.QtCore import QPoint, QThread, QTimer
from PySide6.QtWidgets import QApplication

pdf_a, pdf_b = work / "a.pdf", work / "b.pdf"
for path in (pdf_a, pdf_b):
    with fitz.open() as doc:
        for n in range(40):
            page = doc.new_page(width=600, height=800)
            for k in range(20):
                page.insert_text((36, 20 + k * 19), f"page {n} line {k} " * 4, fontsize=9)
        doc.save(path)

registry = worker_registry.get_registry()

# A render or thumbnail worker that starts AFTER the accepted close (the visible-render timer chain
# a zoom queued before the close) is held until the parent's release plus a margin: a gate that
# does not own it lets exec return while it still runs.
import controller.page_render_coordinator as prc
import controller.thumbnail_coordinator as thc


def late_hold(cls):
    original = cls.run

    def run(self, *args, **kwargs):
        if (work / "closed_accepted").exists():
            stamp("late_worker_started_" + cls.__name__)
            while not (work / "release").exists():
                time.sleep(0.02)
            time.sleep(0.4)
            stamp("late_worker_finished_" + cls.__name__)
        return original(self, *args, **kwargs)

    cls.run = run


late_hold(prc._PageRenderWorker)
late_hold(thc._ThumbnailWorker)


class Held(QThread):
    """Ignores cancel and ends only when the parent writes ``release``."""

    def __init__(self, tag):
        super().__init__()
        self.tag = tag

    def cancel(self):
        pass

    def alive(self):
        return self.isRunning()

    def run(self):
        if self.tag == "2":
            stamp("second_ran")
            return
        while not (work / "release").exists():
            time.sleep(0.02)
        stamp("worker_finished_" + self.tag)

    def __repr__(self):
        return "<HeldWorker %s>" % self.tag


def start_held(tag):
    worker = Held(tag)
    if hasattr(registry, "start_owned"):
        return registry.start_owned(worker, worker.cancel), worker
    registry.register(worker)
    worker.start()
    return True, worker


argv = [] if mode == "direct_quit" else [str(pdf_a)]
if mode == "promoted_close":
    argv = [str(pdf_a), str(pdf_b)]
startup = main.run(argv=argv, start_event_loop=False)
app = QApplication.instance()
ok, held = start_held("1")
assert ok
startup["view"].closed.connect(lambda: stamp("closed_accepted"))

beats = [0]


def beat():
    beats[0] += 1
    stamp("heartbeat", beats[0])


heartbeat = QTimer()
heartbeat.timeout.connect(beat)
heartbeat.start(50)


def requested():
    stamp("quit_requested")


def stimulate_and_close():
    controller = startup["controller"]
    try:
        controller.change_scale(controller._get_ui_state(controller.model.get_active_session_id()).current_page, 1.7)
    except Exception as exc:
        print("stimulate failed", exc, file=sys.stderr)
    QTimer.singleShot(5, close_primary)


def close_primary():
    requested()
    startup["view"].close()
    if mode == "queued_start":
        QTimer.singleShot(150, attempt_second)


def attempt_second():
    started, _second = start_held("2")
    stamp("second_refused" if not started else "second_started")


def detach_second():
    controller = startup["controller"]
    sid_b = controller.model.get_active_session_id()
    rect = startup["view"].frameGeometry()
    controller.detach_document_session(sid_b, QPoint(rect.right() + 400, rect.top() + 50))


def close_promoted():
    requested()
    startup["view"].close()


if mode in ("last_close", "queued_start"):
    QTimer.singleShot(400, stimulate_and_close)
elif mode == "direct_quit":
    QTimer.singleShot(300, lambda: (requested(), app.quit()))
elif mode == "promoted_close":
    QTimer.singleShot(400, detach_second)
    QTimer.singleShot(1000, lambda: startup["view"].close())  # promotes the detached window
    QTimer.singleShot(1600, close_promoted)

stamp("ready")
if hasattr(main, "run_event_loop"):
    code = main.run_event_loop(startup)
else:
    code = app.exec()
stamp("exec_returned")
running = [t for t in gc.get_objects() if isinstance(t, QThread) and shiboken6.isValid(t)
           and t is not app.thread() and t.isRunning()]  # the GUI thread's own wrapper is not a worker
stamp("running_qthreads", len(running))
stamp("running_qthreads_repr", repr(running))
sys.stderr.flush()
sys.exit(code)
'''


def _spawn(tmp_path: Path, mode: str, ceiling_ms: int) -> subprocess.Popen:
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PDF_EDITOR_RENDER_WORKER"] = "thread"
    return subprocess.Popen(
        [sys.executable, str(script), str(REPO_ROOT), str(tmp_path), mode, str(ceiling_ms)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(REPO_ROOT),
    )


def _wait_for(path: Path, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except (FileNotFoundError, PermissionError):
        return None


def _heartbeat(tmp_path: Path) -> int:
    for _ in range(5):
        value = _read(tmp_path / "heartbeat")
        if value and value.isdigit():
            return int(value)
        time.sleep(0.01)
    return 0


@pytest.mark.parametrize("mode", ["last_close", "direct_quit", "promoted_close", "queued_start"])
def test_exec_returns_only_after_every_owned_worker_finished(tmp_path, mode):
    proc = _spawn(tmp_path, mode, ceiling_ms=60000)
    try:
        assert _wait_for(tmp_path / "quit_requested", 90), "child never reached the quit request"
        time.sleep(0.5)
        before = _heartbeat(tmp_path)
        time.sleep(1.5)  # well past any short drain; the worker is still held
        assert proc.poll() is None, "the process left while a registered worker was running"
        assert not (tmp_path / "worker_finished_1").exists()
        assert not (tmp_path / "exec_returned").exists(), "exec returned while a registered worker was running"
        assert _heartbeat(tmp_path) >= before + 10, "the GUI thread did not keep running while the worker was held"
        (tmp_path / "release").write_text("go")
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        tail = err.decode(errors="replace")[-3000:]
        assert proc.returncode == 0, tail
        finished = int((tmp_path / "worker_finished_1").read_text())
        returned = int((tmp_path / "exec_returned").read_text())
        assert finished < returned, "exec returned before the worker finished"
        for started in tmp_path.glob("late_worker_started_*"):
            done = tmp_path / started.name.replace("started", "finished")
            assert done.exists() and int(done.read_text()) < returned, f"{started.name}: ran past exec"
        assert (tmp_path / "running_qthreads").read_text() == "0", (
            "a QThread was still running when exec returned: " + (tmp_path / "running_qthreads_repr").read_text()
        )
        if mode == "queued_start":
            assert (tmp_path / "second_refused").exists(), tail
            assert not (tmp_path / "second_started").exists()
            assert not (tmp_path / "second_ran").exists()
    finally:
        if proc.poll() is None:
            proc.kill()


def test_ceiling_cuts_a_worker_that_never_finishes_and_exec_never_returns(tmp_path):
    ceiling_ms = 2000
    proc = _spawn(tmp_path, "last_close", ceiling_ms=ceiling_ms)
    try:
        assert _wait_for(tmp_path / "quit_requested", 90), "child never reached the quit request"
        try:
            out, err = proc.communicate(timeout=ceiling_ms / 1000 + 10)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AssertionError("the process outlived the ceiling")
        text = err.decode(errors="replace")
        assert proc.returncode == 0, text[-3000:]
        requested = int((tmp_path / "quit_requested").read_text())
        left = int((tmp_path / "leave_at").read_text())
        elapsed = (left - requested) / 1e9
        print(f"CEILING left {elapsed:.2f}s after the quit request")
        assert ceiling_ms / 1000 - 0.3 <= elapsed <= ceiling_ms / 1000 + 3.0, elapsed
        assert not (tmp_path / "exec_returned").exists(), "exec returned past a still-running worker"
        assert not (tmp_path / "worker_finished_1").exists()
        assert "HeldWorker" in text, "the survivor was not logged"
    finally:
        if proc.poll() is None:
            proc.kill()


# ---- the one outcome check (Astra round 8): the gate may not report completion while ANY execution
# ---- resource still exists outside its accounting.  The child records ACTUAL QThread and QProcess
# ---- starts by patching the Qt classes, independently of the registry, then censuses them.

INVARIANT_CHILD = r'''
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
work = Path(sys.argv[2])
mode = sys.argv[3]
ceiling_ms = int(sys.argv[4])
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s %(message)s")


def stamp(name, value=None):
    (work / name).write_text(str(time.perf_counter_ns()) if value is None else str(value))


import controller.worker_registry as worker_registry
worker_registry.QUIT_CEILING_MS = ceiling_ms

state = {"last_beat": time.perf_counter_ns(), "beats": 0, "max_gap": 0.0}
real_exit = os._exit


def exit_with_stamp(code):
    stamp("leave_at")
    stamp("beat_gap_ms", (time.perf_counter_ns() - state["last_beat"]) / 1e6)
    stamp("beats", state["beats"])
    stamp("max_gap_ms", state["max_gap"])
    sys.stderr.flush()
    real_exit(code)


os._exit = exit_with_stamp

import fitz
import main
import shiboken6
from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication

# ---- independent record of every real start --------------------------------------------------
started_threads = []
started_children = []
late_starts = []
attempts = []

_thread_start = QThread.start
_process_start = QProcess.start


def _closed():
    return (work / "admission_closed").exists()


def thread_start(self, *args, **kwargs):
    started_threads.append(self)
    if _closed():
        late_starts.append("thread " + repr(self))
    return _thread_start(self, *args, **kwargs)


def process_start(self, *args, **kwargs):
    started_children.append(self)
    if _closed():
        late_starts.append("process " + repr(self))
    return _process_start(self, *args, **kwargs)


QThread.start = thread_start
QProcess.start = process_start

_close_admission = worker_registry.WorkerRegistry.close_admission


def close_admission(self):
    stamp("admission_closed")
    return _close_admission(self)


worker_registry.WorkerRegistry.close_admission = close_admission

pdf_a = work / "a.pdf"
with fitz.open() as doc:
    for n in range(5):
        page = doc.new_page(width=600, height=800)
        page.insert_text((36, 40), f"page {n}", fontsize=9)
    doc.save(pdf_a)

registry = worker_registry.get_registry()


def wait_release():
    while not (work / "release").exists():
        time.sleep(0.02)


class Held(QThread):
    """Ignores cancel and ends only when the parent writes ``release``."""

    def __init__(self, tag):
        super().__init__()
        self.tag = tag

    def cancel(self):
        pass

    def run(self):
        wait_release()
        stamp("worker_finished_" + self.tag)

    def __repr__(self):
        return "<HeldWorker %s>" % self.tag


class Quick(QThread):
    """Returns at once; the hold is in a direct ``finished`` handler on the worker thread."""

    def run(self):
        pass

    def __repr__(self):
        return "<QuickWorker>"


def hold_in_handler(thread, forever=False):
    def hold():
        if forever:
            while True:
                time.sleep(0.05)
        wait_release()
        stamp("hold_done")

    thread.finished.connect(hold, Qt.ConnectionType.DirectConnection)


import controller.print_coordinator as pc


class StandInRunner(QObject):
    """A print runner with the production runner's public surface (signals, start, terminate); its
    child ends only when the parent writes ``release``."""

    progress = Signal(str)
    stalled = Signal()
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None

    def start(self):
        code = "import os,sys,time\nwhile not os.path.exists(sys.argv[1]): time.sleep(0.02)\n"
        self._process = QProcess(self)
        self._process.finished.connect(self._done)
        self._process.start(sys.executable, ["-c", code, str(work / "release")])

    def _done(self, *args):
        self._process = None
        stamp("child_exit")
        self.finished.emit()

    def terminate(self):
        pass  # the child ends only on release


class PrintJob:
    pdf_bytes = None
    input_pdf_path = None


pc.PrintCoordinator._create_print_runner = lambda self, job: StandInRunner(self._c.view)

expected_code = 0
startup = main.run(argv=[str(pdf_a)], start_event_loop=False)
app = QApplication.instance()
close_via = "close"


def prepare_print_job():
    """What the print submission thread's ``prepared`` signal does: launch the helper child."""
    startup["controller"]._print_coordinator._on_print_job_prepared(PrintJob())


def requested():
    stamp("quit_requested")


if mode == "a_ctrl_finish_held":
    thread = Quick()
    hold_in_handler(thread)
    assert registry.start_owned(thread, None)

elif mode.startswith("b_extb_finish_held"):
    import view.ext_b_subset_worker as ext_b

    def fake_warm(html):
        while not (work / "ext_go").exists():
            time.sleep(0.01)

    ext_b.warm_ext_b_subsets = fake_warm
    service = ext_b.ExtBSubsetService()
    service.request("<p>x</p>")
    hold_in_handler(ext_b._LIVE_THREADS[-1])
    QTimer.singleShot(150, lambda: stamp("ext_go", "1"))

elif mode == "c_print_child_held":
    QTimer.singleShot(200, prepare_print_job)
    close_via = "exit"
    expected_code = 13

elif mode == "d_second_run":
    thread = Held("1")
    assert registry.start_owned(thread, thread.cancel)
    startup_b = main.run(argv=[], start_event_loop=False)
    close_via = "exit"
    expected_code = 17

elif mode == "e_late_attempt":
    thread = Held("1")
    assert registry.start_owned(thread, thread.cancel)

elif mode == "f_deleter_gui_never_blocked":
    # The production wiring: the registry owns the deletion (``dispose=True``; the sites no longer
    # connect ``finished -> deleteLater``, which blocked the GUI thread in ``~QThread`` while a
    # ``finished`` handler ran).  The worker is held IN run() until the quit was requested, the
    # production wiring is installed first, and the finite-hold direct handler is attached LAST (a
    # handler connected before would stop the signal before any later connection ran).  With
    # QG_MUTANT=early_delete the old ``finished -> deleteLater`` connection is restored: the check
    # must then fail (the GUI thread blocks for the hold).
    class Gated(QThread):
        def run(self):
            while not (work / "quit_requested").exists():
                time.sleep(0.01)
            time.sleep(0.15)

        def __repr__(self):
            return "<GatedWorker>"

    thread = Gated()
    assert registry.start_owned(thread, None, dispose=True)
    if os.environ.get("QG_MUTANT") == "early_delete":
        thread.finished.connect(thread.deleteLater)

    def finite_hold():
        stamp("handler_entered")
        time.sleep(0.8)
        stamp("hold_done")

    thread.finished.connect(finite_hold, Qt.ConnectionType.DirectConnection)

elif mode == "h_idle_pool_replaced":
    # A render pool with NO child at replacement time: the replacement run must still own it, or a
    # queued retry launches a real child after admission closed (Astra round 9).
    pool_a = startup["render_client"]
    idle_child = pool_a.children[0]
    idle_child._parked = True  # no automatic restart after the disposal
    idle_child._dispose()
    deadline = time.time() + 20
    while idle_child._process is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert idle_child._process is None, "the idle child never exited"
    startup_b = main.run(argv=[], start_event_loop=False)
    close_via = "exit"
    expected_code = 17
    # app.exit() returns the loop at once and the drain may be short: attempt the retry the moment
    # admission closed instead of on a fixed delay.
    watch = QTimer()

    def watch_closure():
        if (work / "admission_closed").exists():
            watch.stop()
            attempt_late()

    watch.timeout.connect(watch_closure)
    watch.start(2)

elif mode == "g_never_release":
    thread = Held("1")
    assert registry.start_owned(thread, thread.cancel)

heartbeat = QTimer()


def beat():
    now = time.perf_counter_ns()
    if state["beats"]:
        state["max_gap"] = max(state["max_gap"], (now - state["last_beat"]) / 1e6)
    state["last_beat"] = now
    state["beats"] += 1
    stamp("heartbeat", state["beats"])


heartbeat.timeout.connect(beat)
heartbeat.start(50)


def attempt_late():
    """Every kind of start, attempted AFTER admission closed; each must be refused."""
    before_threads, before_children = len(started_threads), len(started_children)
    if mode == "h_idle_pool_replaced":
        idle_child._parked = False
        idle_child.start()  # the queued retry of the replaced run's pool
        attempts.append(len(started_children) - before_children)
        stamp("attempted")
        return
    second = Held("2")
    registry.start_owned(second, second.cancel)
    import view.ext_b_subset_worker as ext_b2

    ext_b2.ExtBSubsetService().request("<p>late</p>")
    attempts.append(len(started_threads) - before_threads)
    from controller.object_probe_runner import ObjectProbeRunner
    from controller.recent_file_probe import RecentFileProbe

    ObjectProbeRunner.for_app(app).submit(object(), "table", (b"x",))
    RecentFileProbe.for_app(app).request([str(pdf_a)])
    prepare_print_job()
    attempts.append(len(started_children) - before_children)
    stamp("attempted")


def quit_now():
    requested()
    if use_done:
        startup["quit_gate"].request()
        return
    if close_via == "exit":
        app.exit(expected_code)
    else:
        startup["view"].close()
    if mode == "e_late_attempt":
        QTimer.singleShot(150, attempt_late)


use_done = mode.endswith("done_handle")
QTimer.singleShot(500 if mode != "c_print_child_held" else 700, quit_now)
stamp("ready")
if use_done:
    # An embedded host owns the loop: request the quit, pump until the handle says done.
    while not (work / "quit_requested").exists() or not startup["quit_gate"].done():
        app.processEvents()
        time.sleep(0.01)
    code = 0
else:
    code = main.run_event_loop(startup)
stamp("exec_returned")

unjoined = []
for t in started_threads:
    if shiboken6.isValid(t) and not t.wait(0):
        unjoined.append(repr(t))
running_children = []
for p in started_children:
    if shiboken6.isValid(p) and p.state() != QProcess.ProcessState.NotRunning:
        running_children.append(repr(p))
(work / "census.json").write_text(json.dumps({
    "unjoined": unjoined, "children_running": running_children, "late_starts": late_starts,
    "attempts": attempts, "threads": len(started_threads), "children": len(started_children),
    "code": code, "max_gap_ms": state["max_gap"],
}))
sys.stderr.flush()
sys.exit(code)
'''

HOLD_MODES = {
    "a_ctrl_finish_held": 0,
    "b_extb_finish_held": 0,
    "b_extb_finish_held_done_handle": 0,
    "c_print_child_held": 13,
    "d_second_run": 17,
    "e_late_attempt": 0,
}


def _spawn_invariant(tmp_path: Path, mode: str, ceiling_ms: int, *, render_worker: str = "thread",
                     extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    script = tmp_path / "invariant_child.py"
    script.write_text(INVARIANT_CHILD, encoding="utf-8")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PDF_EDITOR_RENDER_WORKER"] = render_worker
    env.update(extra_env or {})
    return subprocess.Popen(
        [sys.executable, str(script), str(REPO_ROOT), str(tmp_path), mode, str(ceiling_ms)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(REPO_ROOT),
    )


@pytest.mark.parametrize("mode", sorted(HOLD_MODES))
def test_gate_reports_done_only_when_every_thread_joined_and_every_child_exited(tmp_path, mode):
    import json

    proc = _spawn_invariant(tmp_path, mode, ceiling_ms=60000)
    try:
        assert _wait_for(tmp_path / "quit_requested", 90), "child never reached the quit request"
        time.sleep(0.5)
        before = _heartbeat(tmp_path)
        time.sleep(1.5)  # past any short drain: the last resource is still held
        assert proc.poll() is None, "the process left while a resource was held"
        assert not (tmp_path / "exec_returned").exists(), "the gate returned while a resource was held"
        assert _heartbeat(tmp_path) >= before + 10, "the GUI thread did not keep running while held"
        (tmp_path / "release").write_text("go")
        try:
            _out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        tail = err.decode(errors="replace")[-3000:]
        assert proc.returncode == HOLD_MODES[mode], tail
        census = json.loads((tmp_path / "census.json").read_text())
        assert census["unjoined"] == [], f"admitted threads not joined at return: {census}\n{tail}"
        assert census["children_running"] == [], f"children still running at return: {census}\n{tail}"
        assert census["late_starts"] == [], f"a start after admission closed was not refused: {census}"
        if mode == "c_print_child_held":
            assert census["children"] >= 1, "the print child never started"
            assert (tmp_path / "child_exit").exists()
        else:
            assert census["threads"] >= 1
        if mode == "e_late_attempt":
            assert (tmp_path / "attempted").exists(), "the late start attempt never occurred"
            assert census["attempts"] == [0, 0], f"a late start reached QThread.start or QProcess.start: {census}"
    finally:
        if proc.poll() is None:
            proc.kill()


def _run_to_completion(tmp_path: Path, mode: str, *, render_worker: str = "thread",
                       extra_env: dict[str, str] | None = None) -> tuple[int, dict, str]:
    import json

    proc = _spawn_invariant(tmp_path, mode, ceiling_ms=60000, render_worker=render_worker, extra_env=extra_env)
    try:
        assert _wait_for(tmp_path / "quit_requested", 90), "child never reached the quit request"
        try:
            _out, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
    finally:
        if proc.poll() is None:
            proc.kill()
    tail = err.decode(errors="replace")[-3000:]
    census_path = tmp_path / "census.json"
    census = json.loads(census_path.read_text()) if census_path.exists() else {}
    return proc.returncode, census, tail


def _deleter_wiring_holds(tmp_path: Path, extra_env: dict[str, str] | None) -> tuple[bool, str]:
    """The invariant for registry-owned thread deletion: the GUI thread keeps beating while a
    ``finished`` handler runs, the handler was really entered, and everything joined."""
    code, census, tail = _run_to_completion(tmp_path, "f_deleter_gui_never_blocked", extra_env=extra_env)
    problems = []
    if code != 0:
        problems.append(f"exit code {code}")
    if not (tmp_path / "handler_entered").exists():
        problems.append("the finished handler was never entered")
    if census.get("max_gap_ms", 1e9) >= 400:
        problems.append(f"the GUI thread was blocked {census.get('max_gap_ms')} ms")
    if census.get("unjoined"):
        problems.append(f"unjoined: {census['unjoined']}")
    return not problems, "; ".join(problems) + "\n" + tail


def test_registry_owned_deletion_never_blocks_the_gui_thread_while_a_finished_handler_runs(tmp_path):
    ok, why = _deleter_wiring_holds(tmp_path, None)
    assert ok, why


def test_the_deletion_invariant_fails_when_finished_deleteLater_is_restored(tmp_path):
    """Mutant proof: the old ``finished -> deleteLater`` wiring makes ~QThread block the GUI thread for
    the handler's hold; the same check must catch it (it was a demonstrated false green)."""
    ok, why = _deleter_wiring_holds(tmp_path, {"QG_MUTANT": "early_delete"})
    assert not ok, "the invariant did not notice the early-delete mutant"


def test_idle_render_pool_of_a_replaced_run_cannot_launch_a_child_after_closure(tmp_path):
    code, census, tail = _run_to_completion(tmp_path, "h_idle_pool_replaced", render_worker="process")
    assert code == 17, tail
    assert (tmp_path / "attempted").exists(), "the late retry never occurred"
    assert census["late_starts"] == [], f"a child launched after admission closed: {census}\n{tail}"
    assert census["children_running"] == [], f"a child outlived the gate: {census}\n{tail}"
    assert census["unjoined"] == []


@pytest.mark.parametrize("mode", ["g_never_release"])
def test_never_released_resource_leaves_by_exit_with_the_heartbeat_alive_to_the_deadline(tmp_path, mode):
    ceiling_ms = 1500
    proc = _spawn_invariant(tmp_path, mode, ceiling_ms=ceiling_ms)
    try:
        assert _wait_for(tmp_path / "quit_requested", 90), (
            "child never reached the quit request: the GUI thread blocked before it (a QThread "
            "deleted by its deleteLater while still inside a finished handler waits for it)"
        )
        try:
            _out, err = proc.communicate(timeout=ceiling_ms / 1000 + 12)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AssertionError("the process outlived the ceiling")
        text = err.decode(errors="replace")
        assert proc.returncode == 0, text[-3000:]
        assert not (tmp_path / "exec_returned").exists(), "a normal return past a held resource"
        elapsed = (int((tmp_path / "leave_at").read_text()) - int((tmp_path / "quit_requested").read_text())) / 1e9
        assert ceiling_ms / 1000 - 0.3 <= elapsed <= ceiling_ms / 1000 + 3.0, elapsed
        gap_ms = float((tmp_path / "beat_gap_ms").read_text())
        assert gap_ms < 400, f"the GUI thread was blocked {gap_ms:.0f} ms before the deadline exit\n{text[-2000:]}"
    finally:
        if proc.poll() is None:
            proc.kill()
