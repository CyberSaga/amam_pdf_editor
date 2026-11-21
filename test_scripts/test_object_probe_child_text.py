"""Card A6.3: child kind ``text`` (one-page scratch copy + 0-based page index in, ``entry`` out)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from model import table_objects
from model.text_block import extract_page_entry, page_entry_from_json, page_entry_to_json
from src.object_probe import helper_main
from src.render_worker.admission import object_probe_memory_limit
from src.render_worker.memory import read_system_memory
from utils import object_probe_platform

REPO_ROOT = Path(__file__).resolve().parents[1]


def _scratch_bytes() -> bytes:
    with fitz.open() as doc:
        doc.new_page(width=595, height=842)
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Hello child text index", fontsize=12.5)
        page.insert_text((72, 130), "Second line", fontsize=9.25, color=(0.1, 0.2, 0.3))
        return table_objects.scratch_page_bytes(doc, 2)


def _spawn(kind: str, payloads: list[bytes]) -> tuple[subprocess.CompletedProcess, list[dict]]:
    if not object_probe_platform.contained_probe_supported():
        pytest.skip("no contained object-probe child on this platform")
    limit = object_probe_memory_limit(read_system_memory())
    if limit is None:
        pytest.skip("no memory headroom for the child")
    header = {"v": 2, "kind": kind, "sizes": [len(p) for p in payloads], "mem": limit}
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--object-probe"],
        input=json.dumps(header).encode() + b"\n" + b"".join(payloads),
        capture_output=True, timeout=300, cwd=REPO_ROOT,
    )
    answers = [json.loads(x) for x in result.stdout.splitlines() if x.startswith(b'{"v"')]
    return result, answers


def _run_child(kind: str, payloads: list[bytes]) -> tuple[int, list[dict]]:
    result, answers = _spawn(kind, payloads)
    return result.returncode, answers


def test_text_kind_is_registered():
    assert "text" in helper_main._KINDS


def test_real_child_answers_the_entry_of_the_scratch_copy():
    payload = _scratch_bytes()
    code, answers = _run_child("text", [payload, b"1"])
    assert code == 0 and len(answers) == 1
    answer = answers[0]
    assert answer["v"] == 2 and answer["status"] == "complete" and "entry" in answer
    with fitz.open(stream=payload, filetype="pdf") as doc:
        expected = extract_page_entry(1, doc[0])
    got = page_entry_from_json(answer["entry"])
    assert got.spans and got.blocks
    assert page_entry_to_json(got) == page_entry_to_json(expected)
    assert got == expected


def test_child_tools_state_equals_the_apps():
    from model import fitz_setup

    fitz_setup.apply_production_tools()
    expected = bool(fitz.TOOLS.set_small_glyph_heights())
    assert expected is True
    payload = _scratch_bytes()
    code, answers = _run_child("text", [payload, b"0"])
    assert code == 0 and answers[0]["status"] == "complete"
    # Glyph heights differ with the flag: the child's entry must equal one extracted under the app's flag.
    with fitz.open(stream=payload, filetype="pdf") as doc:
        assert page_entry_from_json(answers[0]["entry"]) == extract_page_entry(0, doc[0])
    fitz.TOOLS.set_small_glyph_heights(False)
    try:
        with fitz.open(stream=payload, filetype="pdf") as doc:
            other = extract_page_entry(0, doc[0])
        assert page_entry_from_json(answers[0]["entry"]) != other
    finally:
        fitz.TOOLS.set_small_glyph_heights(True)


def test_apply_production_tools_sets_small_glyph_heights():
    from model import fitz_setup

    fitz.TOOLS.set_small_glyph_heights(False)
    try:
        fitz_setup.apply_production_tools()
        assert bool(fitz.TOOLS.set_small_glyph_heights()) is True
    finally:
        fitz.TOOLS.set_small_glyph_heights(True)


@pytest.mark.parametrize(
    "payloads",
    [[b"not a pdf", b"0"], [_scratch_bytes(), b"notanumber"], [_scratch_bytes(), b"-1"], [_scratch_bytes()]],
    ids=["corrupt_pdf", "bad_index", "negative_index", "missing_index"],
)
def test_bad_text_payloads_give_analysis_failed(payloads):
    code, answers = _run_child("text", payloads)
    assert code == 0 and answers == [{"v": 2, "status": "analysis_failed"}]


def test_runner_parse_accepts_entry_for_the_text_kind_only():
    from controller.object_probe_runner import ObjectProbeRunner

    entry = {"blocks": []}
    ok = json.dumps({"v": 2, "status": "complete", "entry": entry}).encode() + b"\n"
    assert ObjectProbeRunner._parse(ok, "text") == {"v": 2, "status": "complete", "entry": entry}
    # A complete answer with no result payload, or a failure carrying one, is dropped.
    assert ObjectProbeRunner._parse(json.dumps({"v": 2, "status": "complete"}).encode(), "text") is None
    failed = {"v": 2, "status": "analysis_failed", "entry": entry}
    assert ObjectProbeRunner._parse(json.dumps(failed).encode(), "text") is None


@pytest.mark.parametrize(
    ("kind", "result"),
    [
        ("text", {"entry": None}),
        ("text", {"entry": []}),
        ("text", {"entry": "x"}),
        ("text", {"rects": []}),
        ("text", {"scans": []}),
        ("text", {"entry": {}, "rects": []}),
        ("tables", {"entry": {}}),
        ("tables", {"rects": None}),
        ("tables", {"scans": []}),
        ("scan", {"rects": []}),
        ("scan", {"entry": {}}),
        ("scan", {"scans": "x"}),
    ],
)
def test_runner_parse_rejects_a_result_that_does_not_match_the_kind(kind, result):
    from controller.object_probe_runner import ObjectProbeRunner

    line = json.dumps({"v": 2, "status": "complete", **result}).encode()
    assert ObjectProbeRunner._parse(line, kind) is None


def test_runner_parse_accepts_each_kinds_own_result():
    from controller.object_probe_runner import ObjectProbeRunner

    for kind, result in (("tables", {"rects": []}), ("scan", {"scans": []}), ("text", {"entry": {}})):
        answer = {"v": 2, "status": "complete", **result}
        assert ObjectProbeRunner._parse(json.dumps(answer).encode(), kind) == answer


def test_text_answer_cap_is_defined_once_and_shared():
    from controller import object_probe_runner
    from src.object_probe import helper_main, limits

    assert limits.TEXT_ANSWER_MAX_BYTES == 2 * 1024 * 1024
    assert helper_main.TEXT_ANSWER_MAX_BYTES is limits.TEXT_ANSWER_MAX_BYTES
    assert object_probe_runner.TEXT_ANSWER_MAX_BYTES is limits.TEXT_ANSWER_MAX_BYTES


def _dense_page_bytes(cols: int = 90, rows: int = 90) -> bytes:
    with fitz.open() as doc:
        page = doc.new_page(width=cols * 24 + 100, height=rows * 24 + 100)
        for r in range(rows):
            for c in range(cols):
                page.insert_text((50 + c * 24, 50 + r * 24), "x", fontsize=8)
        return doc.tobytes()


def test_a_dense_page_answer_over_the_cap_is_resource_limited():
    from model.text_block import extract_page_entry as extract
    from src.object_probe.limits import TEXT_ANSWER_MAX_BYTES

    payload = _dense_page_bytes()
    with fitz.open(stream=payload, filetype="pdf") as doc:
        entry = extract(0, doc[0])
    assert len(entry.spans) >= 8000
    assert len(json.dumps(page_entry_to_json(entry)).encode()) > TEXT_ANSWER_MAX_BYTES
    code, answers = _run_child("text", [payload, b"0"])
    assert code == 0 and answers == [{"v": 2, "status": "resource_limited"}]


def test_a_malformed_page_label_is_not_echoed_to_stderr():
    result, answers = _spawn("text", [_scratch_bytes(), b"private-page-label"])
    assert result.returncode == 0 and answers == [{"v": 2, "status": "analysis_failed"}]
    assert b"private-page-label" not in result.stderr
    assert b"private-page-label" not in result.stdout


def test_measured_decode_and_install_cost_of_a_cap_sized_answer():
    """Records the GUI-side cost of the largest answer the cap lets through (see the card report)."""
    import time

    from model.text_block import TextBlockManager, page_entry_from_json
    from src.object_probe.limits import TEXT_ANSWER_MAX_BYTES

    with fitz.open(stream=_dense_page_bytes(74, 74), filetype="pdf") as doc:
        entry = extract_page_entry(0, doc[0])
    data = json.dumps(page_entry_to_json(entry)).encode()
    assert len(data) <= TEXT_ANSWER_MAX_BYTES
    start = time.perf_counter()
    mgr = TextBlockManager()
    mgr.install_page_entry(0, page_entry_from_json(json.loads(data)))
    ms = (time.perf_counter() - start) * 1000
    print(f"parse+decode+install {len(data)} bytes ({len(entry.spans)} spans): {ms:.1f} ms")
    assert mgr.page_state(0) == "clean"


def test_child_module_stays_qt_free_and_controller_free(tmp_path):
    code = (
        "import sys; from src.object_probe import helper_main as h; "
        "h._answer_text([open(sys.argv[1],'rb').read(), b'0']); "
        "bad=[m for m in sys.modules if m.startswith(('PySide6','controller','view'))]; "
        "print('BAD', bad)"
    )
    tmp = tmp_path / "copy.pdf"
    tmp.write_bytes(_scratch_bytes())
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp)], capture_output=True, timeout=120, cwd=REPO_ROOT, text=True
    )
    assert "BAD []" in result.stdout, result.stdout + result.stderr
