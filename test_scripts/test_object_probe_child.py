"""Card A3: the real ``object-probe`` child (H16) answers like ``table_rects``."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from model import table_objects
from model.pdf_model import PDFModel

REPO_ROOT = Path(__file__).resolve().parents[1]


def _table_pdf(path: Path) -> Path:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        for r in range(4):
            for c in range(3):
                cell = fitz.Rect(100 + c * 120, 200 + r * 30, 100 + (c + 1) * 120, 200 + (r + 1) * 30)
                page.draw_rect(cell, color=(0, 0, 0), width=1)
                page.insert_text((cell.x0 + 5, cell.y0 + 20), f"R{r}C{c}", fontsize=11)
        doc.save(path)
    return path


MEM = 1024 * 1024 * 1024


def _stdin(kind: str, *payloads: bytes, mem: int = MEM, v: int = 2) -> bytes:
    header = {"v": v, "kind": kind, "sizes": [len(p) for p in payloads]}
    if mem is not None:
        header["mem"] = mem
    return json.dumps(header).encode("utf-8") + b"\n" + b"".join(payloads)


def _answer(stdout: bytes) -> dict:
    """The one versioned JSON line (the library may print advisory text next to it)."""
    for line in stdout.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("v") == 2:
            return parsed
    raise AssertionError(f"no answer line in {stdout!r}")


def _qt_forbidden_env(tmp_path) -> dict[str, str]:
    stub = tmp_path / "PySide6"
    stub.mkdir()
    (stub / "__init__.py").write_text("raise ImportError('Qt must not load in a child')", encoding="utf-8")
    return {**os.environ, "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", "")}


def test_real_child_returns_the_same_rectangles_as_table_rects(tmp_path):
    from src.render_worker.launch import child_launch

    model = PDFModel()
    try:
        model.open_pdf(str(_table_pdf(tmp_path / "t.pdf")))
        expected = [tuple(r) for r in table_objects.table_rects(model, 1)]
        payload = table_objects.scratch_page_bytes(model.doc, 1)
    finally:
        model.close()
    assert expected  # the fixture really has a table
    program, args = child_launch("object-probe")
    from src.render_worker.admission import object_probe_memory_limit
    from src.render_worker.memory import read_system_memory

    limit = object_probe_memory_limit(read_system_memory())
    assert limit is not None, "this machine has no headroom for the child"
    result = subprocess.run(
        [program, *args], input=_stdin("tables", payload, mem=limit), capture_output=True, timeout=120, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    answer = _answer(result.stdout)
    assert answer["v"] == 2 and answer["status"] == "complete"
    assert [tuple(r) for r in answer["rects"]] == pytest.approx(expected)


def test_object_probe_flag_dispatches_without_qt(tmp_path):
    payload = fitz.open()
    payload.new_page()
    data = payload.tobytes()
    payload.close()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--object-probe"],
        input=_stdin("tables", data), capture_output=True, timeout=120, cwd=REPO_ROOT,
        env=_qt_forbidden_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert _answer(result.stdout) == {"v": 2, "status": "complete", "rects": []}


def test_child_with_garbage_header_exits_nonzero_without_an_answer(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--object-probe"],
        input=b"not json\n", capture_output=True, timeout=60, cwd=REPO_ROOT, env=_qt_forbidden_env(tmp_path),
    )
    assert result.returncode != 0
    assert result.stdout == b""


def test_child_with_unknown_kind_exits_nonzero(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--object-probe"],
        input=_stdin("bogus"), capture_output=True, timeout=60, cwd=REPO_ROOT, env=_qt_forbidden_env(tmp_path),
    )
    assert result.returncode != 0
    assert result.stdout == b""
