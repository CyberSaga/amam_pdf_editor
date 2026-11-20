"""Card A3b: protocol v2 of the object-probe child (typed outcomes, memory containment order)."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from src.object_probe import helper_main
from src.object_probe.memory_limit import ContainmentError

REPO_ROOT = Path(__file__).resolve().parents[1]


class RecordingStream:
    def __init__(self, data: bytes, log: list):
        self._buf = io.BytesIO(data)
        self._log = log

    def readline(self, limit: int = -1) -> bytes:
        self._log.append("header")
        return self._buf.readline(limit)

    def read(self, n: int = -1) -> bytes:
        self._log.append("payload")
        return self._buf.read(n)


def _request(kind="tables", payloads=(b"AB",), mem=1 << 30, v=2) -> bytes:
    header = {"v": v, "kind": kind, "sizes": [len(p) for p in payloads]}
    if mem is not None:
        header["mem"] = mem
    return json.dumps(header).encode("utf-8") + b"\n" + b"".join(payloads)


def _run_main(monkeypatch, data: bytes, log: list):
    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=RecordingStream(data, log)))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=out))
    code = helper_main.main()
    return code, [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_protocol_version_is_two():
    assert helper_main.PROTOCOL_VERSION == 2


def test_header_is_read_before_the_limit_and_payloads_after(monkeypatch):
    log: list = []

    def limit(mem):
        log.append(("limit", mem))

    monkeypatch.setattr(helper_main, "apply_job_memory_limit", limit)
    monkeypatch.setitem(helper_main._KINDS, "tables", lambda payloads: {"v": 2, "status": "complete", "rects": []})
    code, answers = _run_main(monkeypatch, _request(mem=123 * 1024 * 1024), log)
    assert code == 0
    assert answers == [{"v": 2, "status": "complete", "rects": []}]
    assert log[0] == "header"
    limit_at = log.index(("limit", 123 * 1024 * 1024))
    assert "payload" not in log[:limit_at]
    assert "payload" in log[limit_at:]


def test_containment_failure_answers_without_payloads_or_handler(monkeypatch):
    log: list = []
    called = []

    def limit(mem):
        raise ContainmentError("no job")

    monkeypatch.setattr(helper_main, "apply_job_memory_limit", limit)
    monkeypatch.setitem(helper_main._KINDS, "tables", lambda payloads: called.append(True))
    code, answers = _run_main(monkeypatch, _request(), log)
    assert code == 0 and called == []
    assert answers == [{"v": 2, "status": "containment_failed"}]
    assert "payload" not in log


def test_memory_error_in_the_handler_is_resource_limited(monkeypatch):
    def handler(payloads):
        raise MemoryError

    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    monkeypatch.setitem(helper_main._KINDS, "tables", handler)
    code, answers = _run_main(monkeypatch, _request(), [])
    assert code == 0 and answers == [{"v": 2, "status": "resource_limited"}]


def test_payload_memory_error_returns_typed_json(monkeypatch):
    """N3: reading the payloads is inside the guarded block, so a MemoryError there is still
    answered with a typed line (exit 0, no rects) instead of escaping main()."""
    called = []

    def read_payloads(stream, sizes):
        raise MemoryError

    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    monkeypatch.setattr(helper_main, "_read_payloads", read_payloads)
    monkeypatch.setitem(helper_main._KINDS, "tables", lambda payloads: called.append(True))
    code, answers = _run_main(monkeypatch, _request(), [])
    assert code == 0 and called == []
    assert answers == [{"v": 2, "status": "resource_limited"}]


def test_payload_read_failure_is_analysis_failed(monkeypatch):
    def read_payloads(stream, sizes):
        raise ValueError("short read")

    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    monkeypatch.setattr(helper_main, "_read_payloads", read_payloads)
    code, answers = _run_main(monkeypatch, _request(), [])
    assert code == 0 and answers == [{"v": 2, "status": "analysis_failed"}]


def _table_page_bytes() -> bytes:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        for r in range(4):
            for c in range(3):
                cell = fitz.Rect(100 + c * 120, 200 + r * 30, 100 + (c + 1) * 120, 200 + (r + 1) * 30)
                page.draw_rect(cell, color=(0, 0, 0), width=1)
                page.insert_text((cell.x0 + 5, cell.y0 + 20), f"R{r}C{c}", fontsize=11)
        return doc.tobytes()


def test_find_tables_returning_none_is_analysis_failed_not_resource_limited(monkeypatch):
    """D2: a swallowed native failure (find_tables() is None) never claims a cause."""
    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    monkeypatch.setattr(fitz.Page, "find_tables", lambda self, *a, **k: None)
    code, answers = _run_main(monkeypatch, _request(payloads=(_table_page_bytes(),)), [])
    assert code == 0 and answers == [{"v": 2, "status": "analysis_failed"}]


def test_a_normal_table_page_is_complete_with_rects(monkeypatch):
    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    code, answers = _run_main(monkeypatch, _request(payloads=(_table_page_bytes(),)), [])
    assert code == 0 and len(answers) == 1
    assert answers[0]["status"] == "complete" and len(answers[0]["rects"]) == 1


@pytest.mark.parametrize("exc", ["detection", "other"])
def test_other_failures_are_analysis_failed(monkeypatch, exc):
    from model.table_objects import TableDetectionFailed

    def handler(payloads):
        raise TableDetectionFailed() if exc == "detection" else RuntimeError("boom")

    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    monkeypatch.setitem(helper_main._KINDS, "tables", handler)
    code, answers = _run_main(monkeypatch, _request(), [])
    assert code == 0 and answers == [{"v": 2, "status": "analysis_failed"}]


@pytest.mark.parametrize(
    "data",
    [
        _request(v=1),
        _request(mem=None),
        _request(mem=0),
        _request(mem=-5),
        b"x" * 70000,
        b"not json\n",
    ],
    ids=["v1", "no_mem", "zero_mem", "negative_mem", "no_newline_long", "garbage"],
)
def test_bad_headers_are_refused(monkeypatch, data):
    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    with pytest.raises(ValueError):
        _run_main(monkeypatch, data, [])


def test_v1_header_makes_the_real_child_exit_nonzero():
    header = json.dumps({"v": 1, "kind": "tables", "sizes": []}).encode("utf-8") + b"\n"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--object-probe"],
        input=header, capture_output=True, timeout=60, cwd=REPO_ROOT,
    )
    assert result.returncode != 0 and result.stdout == b""


@pytest.mark.needs_fixtures
def test_real_child_on_the_cad_sample_is_complete_and_empty():
    import time

    from src.object_probe.helper_main import PROTOCOL_VERSION  # noqa: F401
    from src.render_worker.admission import object_probe_memory_limit
    from src.render_worker.memory import read_system_memory

    sample = REPO_ROOT / "test_files" / "cad_vector" / "before.pdf"
    if not sample.exists():
        pytest.skip("owner's CAD sample not present")
    from model import table_objects

    with fitz.open(str(sample)) as doc:
        payload = table_objects.scratch_page_bytes(doc, 1)
    limit = object_probe_memory_limit(read_system_memory())
    assert limit is not None
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--object-probe"],
        input=json.dumps({"v": 2, "kind": "tables", "sizes": [len(payload)], "mem": limit}).encode() + b"\n" + payload,
        capture_output=True, timeout=600, cwd=REPO_ROOT,
    )
    elapsed = time.perf_counter() - started
    answer = next(json.loads(x) for x in result.stdout.splitlines() if x.startswith(b'{"v"'))
    print(f"sample child time {elapsed:.1f}s")
    assert answer == {"v": 2, "status": "complete", "rects": []}
