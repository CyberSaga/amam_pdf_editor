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
running = [t for t in gc.get_objects() if isinstance(t, QThread) and shiboken6.isValid(t) and t.isRunning()]
stamp("running_qthreads", len(running))
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
        assert (tmp_path / "running_qthreads").read_text() == "0", "a QThread was still running when exec returned"
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
