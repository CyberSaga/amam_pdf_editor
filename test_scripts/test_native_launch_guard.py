"""Quit-gate class guard (Astra round 9): no native launch point and no unbounded GUI-side wait may
exist outside the registry chokepoint.

The class: a ``QThread.start`` / ``QProcess.start`` / ``startDetached`` call reachable without the
admission check of ``WorkerRegistry`` (``start_owned`` / ``start_owned_child``), or a GUI-thread wait on
a thread that can block longer than the quit ceiling.  This is one structural check over the whole
production tree, not a list of sites: a new launch anywhere fails it.

How a launch is recognised (heuristic, stated so a reviewer can judge the gap):
  * a ``.start(...)`` call whose receiver is bound (``x = QThread(...)``, ``QProcess(...)``, a
    ``*factory*(...)`` call, a subclass of either, an alias ``u = t``) or whose name contains
    ``process`` / ``thread`` (timers are not launches; ``threading.Thread`` in a child is excluded);
  * any ``.startDetached(...)``;
  * the call is allowed only inside the ``worker_registry`` module, inside the callable handed to
    ``start_owned_child`` / a ``child_launcher`` (admission is checked before it is called), or at an
    ALLOWLIST entry below (each with the reason it is covered elsewhere).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN = ("main.py", "controller", "view", "src", "utils")

# (relative path, qualified function name or "*") -> why the launch is covered elsewhere.
LAUNCH_ALLOWLIST = {
    ("controller/worker_registry.py", "*"): "the chokepoint itself: start_owned / start_owned_child",
    ("view/ext_b_subset_worker.py", "*"): (
        "view-owned (view never imports the controller): refuse_new_ext_b_threads() closes its own "
        "admission from main._begin_shutdown and live_ext_b_subset_threads() is part of the quit gate"
    ),
    ("src/printing/subprocess_runner.py", "PrintSubprocessRunner.start"): (
        "only reachable as the ``start`` callable of start_owned_child in print_coordinator "
        "(pinned by test_print_runner_is_launched_only_through_start_owned_child)"
    ),
}

# (relative path, qualified function name) -> why a blocking thread wait is acceptable there.
WAIT_ALLOWLIST = {
    ("controller/page_render_coordinator.py", "PageRenderCoordinator.wait_for_done"): (
        "user-initiated synchronous join (save / close-pending), bounded by its timeout, never a quit path"
    ),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator.wait_for_done"): (
        "user-initiated synchronous join (save / close-pending), bounded by its timeout, never a quit path"
    ),
    ("controller/text_commit_coordinator.py", "TextCommitPreviewCoordinator.wait_for_done"): (
        "user-initiated synchronous join (save / close-pending), bounded by its timeout, never a quit path"
    ),
    ("controller/scan_verifier.py", "ScanVerifier.shutdown"): (
        "test-only blocking API: no production caller (the quit gate uses cancel() and alive())"
    ),
}

_LAUNCHER_CALLS = {"start_owned_child", "_child_launcher", "child_launcher"}


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def _class_names(tree: ast.AST, seed: set[str]) -> set[str]:
    names = set(seed)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name not in names:
                bases = {b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
                         for b in node.bases}
                if bases & names:
                    names.add(node.name)
                    changed = True
    return names


def _bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(names bound to a native thread/process construction or factory result, python-thread names)."""
    native = _class_names(tree, {"QThread", "QProcess"})
    bound: set[str] = set()
    python_threads: set[str] = set()
    assigns = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None]
    changed = True
    while changed:
        changed = False
        for node in assigns:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            kind = None
            if isinstance(value, ast.Call):
                name = _call_name(value)
                if name == "Thread":
                    kind = "py"
                elif name in native or (name is not None and "factory" in name.lower()):
                    kind = "native"
            elif isinstance(value, (ast.Name, ast.Attribute)) and ast.unparse(value) in bound:
                kind = "native"  # alias: u = t
            if kind is None:
                continue
            for target in targets:
                key = ast.unparse(target)
                if kind == "py":
                    if key not in python_threads:
                        python_threads.add(key)
                        changed = True
                elif key not in bound:
                    bound.add(key)
                    changed = True
    return bound, python_threads


def _qualname_map(tree: ast.AST) -> dict[int, str]:
    """id(node) -> qualified name of the innermost enclosing function (class-qualified), '' at module."""
    out: dict[int, str] = {}

    def visit(node: ast.AST, qual: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, f"{qual}.{child.name}" if qual else child.name)
            else:
                out[id(child)] = qual
                visit(child, qual)

    visit(tree, "")
    return out


def _exempt_spans(tree: ast.AST) -> list[tuple[int, int]]:
    """Line spans of callables handed to start_owned_child / a child launcher as the ``start``."""
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _call_name(node) in _LAUNCHER_CALLS):
            continue
        arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "start"), None)
        target = functions.get(arg.id) if isinstance(arg, ast.Name) else arg
        if isinstance(target, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((target.lineno, target.end_lineno or target.lineno))
    return spans


def _is_native_receiver(receiver: ast.expr, bound: set[str], python_threads: set[str], classes: set[str]) -> bool:
    if isinstance(receiver, ast.Call):
        name = _call_name(receiver)
        return name in classes or (name is not None and "factory" in name.lower())
    text = ast.unparse(receiver)
    if text in python_threads:
        return False
    if text in bound:
        return True
    segment = text.split(".")[-1].lower()
    return ("timer" not in segment) and (
        "process" in segment or "thread" in segment or segment in {"proc", "t"} and text in bound
    )


def native_launch_violations(source: str, rel: str, *, allowlist: dict | None = None) -> list[str]:
    allowed = LAUNCH_ALLOWLIST if allowlist is None else allowlist
    tree = ast.parse(source)
    bound, python_threads = _bindings(tree)
    classes = _class_names(tree, {"QThread", "QProcess"})
    qual = _qualname_map(tree)
    spans = _exempt_spans(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr == "startDetached":
            is_launch = True
        elif attr == "start":
            is_launch = _is_native_receiver(node.func.value, bound, python_threads, classes)
        else:
            continue
        if not is_launch:
            continue
        if any(lo <= node.lineno <= hi for lo, hi in spans):
            continue
        if (rel, "*") in allowed or (rel, qual.get(id(node), "")) in allowed:
            continue
        found.append(f"{rel}:{node.lineno} native launch {ast.unparse(node.func)}() outside the registry chokepoint")
    return sorted(found)


def thread_wait_violations(source: str, rel: str, *, allowlist: dict | None = None) -> list[str]:
    """``<thread-ish>.wait()`` or ``.wait(N)`` with ``N`` not the literal 0, outside WAIT_ALLOWLIST."""
    allowed = WAIT_ALLOWLIST if allowlist is None else allowlist
    tree = ast.parse(source)
    bound, python_threads = _bindings(tree)
    qual = _qualname_map(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "wait"):
            continue
        text = ast.unparse(node.func.value)
        segment = text.split(".")[-1].lower()
        if text in python_threads or not (text in bound or "thread" in segment or "worker" in segment):
            continue
        if len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0:
            continue
        if (rel, qual.get(id(node), "")) in allowed:
            continue
        found.append(f"{rel}:{node.lineno} {text}.wait(...) blocks the GUI thread (use wait(0) and re-poll)")
    return sorted(found)


def _files(entries: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for entry in entries:
        path = REPO_ROOT / entry
        out.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return out


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


# ---- the outcome checks over the real tree -----------------------------------------------------


def test_no_native_launch_point_exists_outside_the_registry_chokepoint():
    offenders: list[str] = []
    for path in _files(SCAN):
        offenders.extend(native_launch_violations(path.read_text(encoding="utf-8-sig"), _rel(path)))
    assert offenders == [], "\n".join(offenders)


def test_no_gui_side_thread_wait_other_than_wait_zero_in_controller():
    offenders: list[str] = []
    for path in _files(("controller",)):
        rel = _rel(path)
        if rel == "controller/worker_registry.py":
            continue
        offenders.extend(thread_wait_violations(path.read_text(encoding="utf-8-sig"), rel))
    assert offenders == [], "\n".join(offenders)


def test_every_allowlist_entry_still_names_an_existing_function_with_a_reason():
    for (rel, qualname), reason in {**LAUNCH_ALLOWLIST, **WAIT_ALLOWLIST}.items():
        assert reason.strip(), (rel, qualname)
        path = REPO_ROOT / rel
        assert path.is_file(), f"stale allowlist entry {rel}"
        if qualname != "*":
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            names = {qual for qual in _qualname_map(tree).values()}
            assert qualname in names, f"stale allowlist entry {rel}::{qualname}"


def test_print_runner_is_launched_only_through_start_owned_child():
    tree = ast.parse((REPO_ROOT / "controller/print_coordinator.py").read_text(encoding="utf-8-sig"))
    firsts = [ast.unparse(n.args[0]) for n in ast.walk(tree)
              if isinstance(n, ast.Call) and _call_name(n) == "start_owned_child" and n.args]
    assert "runner.start" in firsts


# ---- injected-source proofs: the guard has teeth -------------------------------------------------


def test_guard_flags_a_bound_alias_and_a_bare_start():
    source = (
        "from PySide6.QtCore import QThread\n"
        "def f(r):\n"
        "    t = QThread()\n"
        "    u = t\n"
        "    u.start()\n"
        "    r.start_owned(t)\n"
    )
    assert [v.split()[0] for v in native_launch_violations(source, "controller/x.py")] == ["controller/x.py:5"]


def test_guard_flags_a_receiver_that_is_an_injected_process_factory_result():
    source = (
        "class A:\n"
        "    def go(self):\n"
        "        self._process = self._process_factory()\n"
        "        p = self._process\n"
        "        p.start('prog', [])\n"
    )
    assert len(native_launch_violations(source, "src/x.py")) == 1


def test_guard_flags_start_detached_and_a_chained_construction():
    source = (
        "from PySide6.QtCore import QProcess, QThread\n"
        "def f():\n"
        "    QProcess.startDetached('x')\n"
        "    QThread().start()\n"
    )
    assert len(native_launch_violations(source, "view/x.py")) == 2


def test_guard_ignores_timers_and_python_threads_in_a_child_process():
    source = (
        "import threading\n"
        "def f(self):\n"
        "    self._timer.start(5)\n"
        "    thread = threading.Thread(target=f)\n"
        "    thread.start()\n"
    )
    assert native_launch_violations(source, "src/x.py") == []


def test_guard_accepts_a_start_inside_the_callable_handed_to_start_owned_child():
    source = (
        "def f(self, registry, process):\n"
        "    def launch():\n"
        "        process.start('p', [])\n"
        "    registry.start_owned_child(launch, alive=lambda: True)\n"
        "    self._child_launcher(lambda: process.start('p', []), lambda: True)\n"
    )
    assert native_launch_violations(source, "src/x.py") == []
    bare = "def f(process):\n    process.start('p', [])\n"
    assert len(native_launch_violations(bare, "src/x.py")) == 1


def test_wait_guard_flags_unbounded_and_positive_waits_and_accepts_wait_zero():
    source = (
        "def _on_finished(self, worker):\n"
        "    worker.wait()\n"
        "    self._thread.wait(1000)\n"
        "    worker.wait(0)\n"
    )
    found = thread_wait_violations(source, "controller/x.py")
    assert [v.split()[0] for v in found] == ["controller/x.py:2", "controller/x.py:3"]
    allowed = {("controller/x.py", "_on_finished"): "reason"}
    assert thread_wait_violations(source, "controller/x.py", allowlist=allowed) == []
    assert re.search(r"wait", found[0])
