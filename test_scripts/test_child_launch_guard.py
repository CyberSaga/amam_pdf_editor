"""Every app child launch goes through src.render_worker.launch (frozen builds re-run the app exe).

In a PyInstaller build sys.executable is the app exe, so a hard-coded ``-m <module>`` child would
start a second GUI instead of the worker. The helper owns the frozen/non-frozen argv; this guard
fails when a production launch site bypasses it.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ("main.py", "controller", "model", "view", "utils", "src")
HELPER = "src/render_worker/launch.py"
# Sites that name an interpreter without composing a "-m" child argv (reviewed individually):
#   process_client.py / subprocess_runner.py: only the default program handed to the helper.
#   pdf_optimizer.py: reads sys.executable for a path heuristic, no launch.
INTERPRETER_ALLOWLIST = {
    HELPER,
    "src/render_worker/process_client.py",
    "src/printing/subprocess_runner.py",
    "model/pdf_optimizer.py",
}
CHILD_MODULES = {"src.render_worker.worker_main", "src.printing.helper_main"}


def _production_files() -> list[Path]:
    files: list[Path] = []
    for entry in PRODUCTION:
        path = REPO_ROOT / entry
        files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return files


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _violations_in(source: str, rel: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=rel)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == "-m" or node.value in CHILD_MODULES:
                found.append(f"{rel}:{node.lineno} hard-codes child launch {node.value!r}")
        elif isinstance(node, ast.Attribute) and node.attr in {"executable", "_base_executable"}:
            if isinstance(node.value, ast.Name) and node.value.id == "sys" and rel not in INTERPRETER_ALLOWLIST:
                found.append(f"{rel}:{node.lineno} reads sys.{node.attr} outside the allowlist")
    return found


def test_no_production_launch_site_bypasses_the_helper() -> None:
    found: list[str] = []
    for path in _production_files():
        rel = _rel(path)
        if rel != HELPER:
            found.extend(_violations_in(path.read_text(encoding="utf-8-sig"), rel))
    assert found == []


def test_guard_has_teeth() -> None:
    bad = "p.start(sys.executable, ['-m', 'src.render_worker.worker_main'])"
    assert len(_violations_in(bad, "controller/x.py")) == 3
    assert _violations_in("p.start(program, args)", "controller/x.py") == []


def test_helper_non_frozen_uses_dash_m(monkeypatch) -> None:
    from src.render_worker import launch

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert launch.child_launch("render") == (sys.executable, ["-m", "src.render_worker.worker_main"])
    assert launch.child_launch("print", ["job.json"], python_executable="py") == (
        "py", ["-m", "src.printing.helper_main", "job.json"])


def test_helper_frozen_reruns_the_app_exe(monkeypatch) -> None:
    from src.render_worker import launch

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert launch.child_launch("render") == (sys.executable, ["--render-worker"])
    assert launch.child_launch("print", ["job.json"]) == (sys.executable, ["--print-helper", "job.json"])


def test_helper_rejects_unknown_kind() -> None:
    from src.render_worker import launch

    with pytest.raises(ValueError):
        launch.child_launch("nope")


def test_main_dispatches_children_before_the_app_identity_import() -> None:
    source = (REPO_ROOT / "main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    dispatch = next(n.lineno for n in tree.body if isinstance(n, ast.If) and "--render-worker" in ast.unparse(n.test))
    ident = next(n.lineno for n in tree.body
                 if isinstance(n, ast.ImportFrom) and n.module == "utils.app_identity")
    assert dispatch < ident
    assert "--print-helper" in source
    assert "--recent-probe" in source


def _run_main(*args: str, stdin: bytes = b"", timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), *args],
        input=stdin, capture_output=True, timeout=timeout, cwd=REPO_ROOT,
    )


def test_print_helper_with_missing_job_exits_nonzero_without_traceback(tmp_path) -> None:
    result = _run_main("--print-helper", str(tmp_path / "missing-job.json"))
    assert result.returncode != 0
    assert b"Traceback" not in result.stderr
    assert result.stderr.strip() != b""


def test_print_helper_with_corrupt_job_exits_nonzero_without_traceback(tmp_path) -> None:
    job = tmp_path / "job.json"
    job.write_text("{not json", encoding="utf-8")
    result = _run_main("--print-helper", str(job))
    assert result.returncode != 0
    assert b"Traceback" not in result.stderr


def test_print_helper_without_job_arg_exits_nonzero() -> None:
    result = _run_main("--print-helper")
    assert result.returncode != 0
    assert b"Traceback" not in result.stderr


def test_render_worker_flag_runs_worker_and_never_starts_the_gui(tmp_path) -> None:
    """Real dispatch: ready frame on stdout, quit -> exit 0, quiet stderr, and no Qt import.

    A stub PySide6 that raises on import sits first on PYTHONPATH, so a Qt import placed above
    the dispatch (or a branch that falls through into the GUI path) kills the child.
    """
    from src.render_worker.protocol import FrameDecoder, encode_prefix

    stub = tmp_path / "PySide6"
    stub.mkdir()
    (stub / "__init__.py").write_text("raise ImportError('Qt must not load in a child')", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "main.py"), "--render-worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=REPO_ROOT, env=env,
    )
    try:
        decoder = FrameDecoder(max_body=1 << 20)
        frames: list = []
        while not frames:
            chunk = proc.stdout.read1(4096)
            assert chunk, "worker closed stdout before sending ready"
            frames = list(decoder.feed(chunk))
        assert frames[0].header["type"] == "ready"
        proc.stdin.write(encode_prefix({"type": "quit"}, 0))
        proc.stdin.flush()
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0
        stderr = proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
        for stream in (proc.stdout, proc.stderr):
            stream.close()
    assert stderr.strip() == b""


def test_print_helper_events_are_utf8_whatever_the_console_codepage(monkeypatch) -> None:
    import io

    from src.printing import helper_main

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", stream)
    helper_main._force_utf8_stdout()
    helper_main._stdout_emit({"event": "failed", "message": "列印失敗"})
    assert "列印失敗" in raw.getvalue().decode("utf-8")


def test_print_helper_tolerates_missing_stdout(monkeypatch) -> None:
    from src.printing import helper_main

    monkeypatch.setattr(sys, "stdout", None)
    helper_main._force_utf8_stdout()


def test_helper_recent_probe_non_frozen_is_the_isolated_script(monkeypatch) -> None:
    from src.render_worker import launch

    monkeypatch.delattr(sys, "frozen", raising=False)
    program, args = launch.child_launch("recent-probe")
    assert program == getattr(sys, "_base_executable", sys.executable)
    assert args == ["-I", "-S", "-u", str(REPO_ROOT / "utils" / "recent_file_worker.py")]


def test_helper_recent_probe_frozen_reruns_the_app_exe(monkeypatch) -> None:
    from src.render_worker import launch

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert launch.child_launch("recent-probe") == (sys.executable, ["--recent-probe"])


def _qt_forbidden_env(tmp_path) -> dict[str, str]:
    stub = tmp_path / "PySide6"
    stub.mkdir()
    (stub / "__init__.py").write_text("raise ImportError('Qt must not load in a child')", encoding="utf-8")
    return {**os.environ, "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", "")}


def test_recent_probe_flag_answers_the_batch_and_never_starts_the_gui(tmp_path) -> None:
    """Real dispatch: one ``[index, available]`` line per path, exit 0, quiet stderr, no Qt import."""
    import json

    present = tmp_path / "present.pdf"
    present.write_bytes(b"%PDF-1.4")
    batch = json.dumps([str(present), str(tmp_path / "missing.pdf")]).encode("utf-8") + b"\n"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--recent-probe"],
        input=batch, capture_output=True, timeout=60, cwd=REPO_ROOT, env=_qt_forbidden_env(tmp_path),
    )
    assert result.returncode == 0
    assert [json.loads(line) for line in result.stdout.splitlines()] == [[0, True], [1, False]]
    assert result.stderr.strip() == b""


def test_recent_probe_flag_with_garbage_stdin_exits_70_without_results(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--recent-probe"],
        input=b"not json\n", capture_output=True, timeout=60, cwd=REPO_ROOT, env=_qt_forbidden_env(tmp_path),
    )
    assert result.returncode == 70
    assert result.stdout == b""
