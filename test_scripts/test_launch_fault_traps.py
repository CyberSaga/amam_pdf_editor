"""Launch-time fault traps (owner decision 11-25, option d; the second half of the round-10 closing check).

Round 10 of the quit-gate review (plans/cad-m0-h23-review.md) named two P1s that the drain traps of
test_drain_traps.py cannot see, because they need a fault at launch time:

  * P1 1: an exception AFTER the native start (QThread.start returned / the child process launched, then
    the caller raised) drops the registry entry while the thread or child is still alive;
  * P1 2: a replacement `main.run` started from a destroyed-slot during run A's final sweep escapes the
    drain (main.py drain_after_exec returns without rechecking the generation).

Same rule as the drain traps: GREEN against a pinned allowlist of the accepted sites, a NEW site and a STALE
entry both fail, no xfail.  Every production launch goes through the registry chokepoint
(test_native_launch_guard.py), so the fault is injected at the chokepoint for BOTH kinds (thread and child
process) and the census below pins the call sites that share it: a new site must be reviewed here.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess, QThread

from controller.worker_registry import get_registry

REPO_ROOT = Path(__file__).resolve().parents[1]

# (trap, file, qualified function): the accepted round-10 P1 sites.
ACCEPTED = frozenset({
    ("start-then-raise thread", "controller/worker_registry.py", "WorkerRegistry.start_owned"),
    ("start-then-raise child", "controller/worker_registry.py", "WorkerRegistry.start_owned_child"),
    ("replacement run escapes the drain", "main.py", "run.drain_after_exec"),
})

# Every production caller of the chokepoint (file, enclosing function, callee).  A new one fails the census.
LAUNCH_SITES = frozenset({
    ("controller/object_probe_runner.py", "ObjectProbeRunner._start_next", "start_owned_child"),
    ("controller/ocr_coordinator.py", "OcrCoordinator.start_ocr", "start_owned"),
    ("controller/page_render_coordinator.py", "PageRenderCoordinator._start_thread", "start_owned"),
    ("controller/pdf_controller.py", "PDFController._start_optimize_submission", "start_owned"),
    ("controller/print_coordinator.py", "PrintCoordinator._on_print_job_prepared", "start_owned_child"),
    ("controller/print_coordinator.py", "PrintCoordinator._start_print_submission", "start_owned"),
    ("controller/recent_file_probe.py", "RecentFileProbe._launch", "start_owned_child"),
    ("controller/scan_verifier.py", "ScanVerifier._pump", "start_owned"),
    ("controller/search_coordinator.py", "SearchCoordinator.search_text", "start_owned"),
    ("controller/text_commit_coordinator.py", "TextCommitPreviewCoordinator.begin_session", "start_owned"),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator._start_worker", "start_owned"),
    ("controller/vector_edit_coordinator.py", "VectorEditCoordinator._start_in_process", "start_owned"),
    ("controller/vector_edit_coordinator.py", "VectorEditCoordinator._start_load", "start_owned"),
})


def census() -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    paths = [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "controller").glob("*.py"))]
    for path in paths:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == "controller/worker_registry.py":
            continue

        class V(ast.NodeVisitor):
            def __init__(self) -> None:
                self.stack: list[str] = []

            def _scope(self, node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scope

            def visit_Call(self, node):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                if name in ("start_owned", "start_owned_child"):
                    out.add((rel, ".".join(self.stack), name))
                self.generic_visit(node)

        V().visit(ast.parse(path.read_text(encoding="utf-8")))
    return out


class _StartThenFail(QThread):
    """A thread whose caller raises after the native start (the fault the registry must survive)."""

    def __init__(self) -> None:
        super().__init__()
        self.go = False

    def run(self) -> None:
        deadline = time.monotonic() + 20
        while not self.go and time.monotonic() < deadline:
            time.sleep(0.01)

    def start(self, *args):  # type: ignore[override]
        QThread.start(self, *args)
        raise RuntimeError("injected after native start")


def _fault_thread() -> set[tuple[str, str, str]]:
    registry = get_registry()
    thread = _StartThenFail()
    try:
        registry.start_owned(thread, None)
    except RuntimeError:
        pass
    try:
        alive_and_accounted = thread.isRunning() and any(w is not None and getattr(w, "thread", w) is thread
                                                        or w is thread for w in registry.alive())
        dropped = thread.isRunning() and not alive_and_accounted
    finally:
        thread.go = True
        thread.wait(5000)
        for entry in registry.registered():
            registry.unregister(entry)
    return {("start-then-raise thread", "controller/worker_registry.py", "WorkerRegistry.start_owned")} if dropped else set()


def _fault_child(tmp_path: Path) -> set[tuple[str, str, str]]:
    registry = get_registry()
    release = tmp_path / "release_child"
    process = QProcess()

    def start() -> None:
        process.start(sys.executable, ["-c",
            "import os,sys,time\nwhile not os.path.exists(sys.argv[1]): time.sleep(0.02)\n", str(release)])
        assert process.waitForStarted(10000)
        raise RuntimeError("injected after the child launched")

    def running() -> bool:
        return process.state() != QProcess.ProcessState.NotRunning

    try:
        registry.start_owned_child(start, running, process.terminate, label="fault")
    except RuntimeError:
        pass
    try:
        dropped = running() and not registry.alive()
    finally:
        release.write_text("go")
        process.waitForFinished(10000)
        if running():
            process.kill()
            process.waitForFinished(5000)
        for entry in registry.registered():
            registry.unregister(entry)
    return {("start-then-raise child", "controller/worker_registry.py", "WorkerRegistry.start_owned_child")} if dropped else set()


REPLACE_CHILD = r'''
import sys, time, logging
from pathlib import Path
sys.path.insert(0, sys.argv[1])
work = Path(sys.argv[2])
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import fitz
import main
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from controller.worker_registry import get_registry

pdf = work / "a.pdf"
with fitz.open() as doc:
    doc.new_page(width=300, height=300)
    doc.save(pdf)
registry = get_registry()


class Slow(QThread):
    def run(self):
        time.sleep(1.0)
        (work / "b_worker_finished").write_text("1")


def _frames():
    f = sys._getframe(1)
    while f is not None:
        yield f
        f = f.f_back


class Entry:
    """A registry entry whose alive() starts a replacement run, as a destroyed-slot would during the sweep."""

    def __init__(self):
        self.fired = False

    def cancel(self):
        pass

    def alive(self):
        in_final_sweep = any(f.f_code.co_name == "drain_after_exec" for f in _frames())
        if in_final_sweep and not self.fired:
            self.fired = True
            main.run(argv=[], start_event_loop=False)
            worker = Slow()
            assert registry.start_owned(worker, None)
            (work / "replaced").write_text("1")
            return False  # reported finished: the drain's own snapshot is empty
        return not in_final_sweep


startup = main.run(argv=[str(pdf)], start_event_loop=False)
registry.register(Entry())
app = QApplication.instance()
from PySide6.QtCore import QTimer
QTimer.singleShot(500, lambda: app.exit(0))
code = main.run_event_loop(startup)
(work / "drain_returned").write_text("1")
(work / "b_running_at_return").write_text("1" if not (work / "b_worker_finished").exists() else "0")
sys.stdout.flush()
os._exit(0)
'''


def _fault_replacement(tmp_path: Path) -> set[tuple[str, str, str]]:
    script = tmp_path / "replace_child.py"
    script.write_text(REPLACE_CHILD, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script), str(REPO_ROOT), str(tmp_path)],
                          capture_output=True, timeout=120, cwd=str(REPO_ROOT))
    assert (tmp_path / "replaced").exists(), "the replacement run was never started:\n" + proc.stderr.decode(errors="replace")[-2000:]
    assert (tmp_path / "drain_returned").exists(), "the drain never returned:\n" + proc.stderr.decode(errors="replace")[-2000:]
    escaped = (tmp_path / "b_running_at_return").read_text() == "1"
    return {("replacement run escapes the drain", "main.py", "run.drain_after_exec")} if escaped else set()


def observe(tmp_path: Path) -> set[tuple[str, str, str]]:
    return _fault_thread() | _fault_child(tmp_path) | _fault_replacement(tmp_path)


def diff(observed, accepted) -> tuple[set, set]:
    return set(observed) - set(accepted), set(accepted) - set(observed)


@pytest.fixture(scope="module")
def observed(tmp_path_factory, qapp):
    return observe(tmp_path_factory.mktemp("faults"))


def test_launch_fault_traps_see_exactly_the_accepted_sites(observed):
    new, stale = diff(observed, ACCEPTED)
    assert not new, f"NEW launch-fault site(s): {sorted(new)}"
    assert not stale, f"STALE allowlist entr(ies) (fixed: delete from ACCEPTED): {sorted(stale)}"


def test_a_stale_entry_is_caught(observed):
    extra = ("start-then-raise thread", "controller/x.py", "gone")
    assert diff(observed, ACCEPTED | {extra})[1] == {extra}


def test_a_new_site_is_caught(observed):
    extra = ("start-then-raise thread", "controller/x.py", "new")
    assert diff(observed | {extra}, ACCEPTED)[0] == {extra}


def test_every_production_launch_site_is_pinned():
    seen = census()
    assert not (seen - LAUNCH_SITES), f"NEW launch site(s): add a launch-fault review: {sorted(seen - LAUNCH_SITES)}"
    assert not (LAUNCH_SITES - seen), f"STALE launch site(s): {sorted(LAUNCH_SITES - seen)}"
