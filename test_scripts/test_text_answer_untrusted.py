"""Astra A6.3 round 2: the untrusted-child-answer CLASS, closed on the outcome.

Whatever bytes a ``text`` child writes, the runner -> decode -> install chain must end in exactly one
terminal outcome (a valid entry installed, or ``failed``), must start the next queued job, and must
leave every store and page state exactly as it was unless the answer is valid.
"""
from __future__ import annotations

import copy
import dataclasses
import json

import fitz
import pytest
from PySide6.QtCore import QProcess

from model import text_block
from model.text_block import (
    TextBlockManager,
    extract_page_entry,
    page_entry_from_json,
    page_entry_to_json,
)
from src.object_probe.limits import TEXT_ANSWER_MAX_BYTES
from test_scripts.test_object_probe_runner import OK_MEMORY, FakeProcess

NAN = float("nan")
TARGET = 1  # the page the answers are about; the manager already holds pages 0..3


def _doc() -> fitz.Document:
    doc = fitz.open()
    for i in range(4):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"alpha beta page {i}", fontsize=12)
        page.insert_text((72, 200), f"gamma delta {i}", fontsize=10)
        page.insert_text((72, 300), "- bullet one", fontsize=10)
    return doc


@pytest.fixture(autouse=True)
def _runner_env(monkeypatch):
    FakeProcess.instances = []
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: OK_MEMORY)
    monkeypatch.setattr("utils.object_probe_platform.contained_probe_supported", lambda: True)
    yield
    FakeProcess.instances = []


@pytest.fixture(scope="module")
def good():
    """(populated manager snapshot source doc bytes, valid envelope dict for TARGET)."""
    with _doc() as doc:
        entry = extract_page_entry(TARGET, doc[TARGET])
        pdf = doc.tobytes()
    envelope = {"v": 2, "status": "complete", "entry": json.loads(json.dumps(page_entry_to_json(entry)))}
    return pdf, envelope, entry


def _populated(pdf: bytes) -> TextBlockManager:
    mgr = TextBlockManager()
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        mgr.build_index(doc)
    return mgr


def _snapshot(mgr: TextBlockManager) -> dict:
    snap = {name: copy.deepcopy(getattr(mgr, name)) for name in text_block._PAGE_STORES}
    snap["states"] = {i: mgr.page_state(i) for i in range(8)}
    return snap


def _run(qapp, mgr: TextBlockManager, raw: bytes) -> list[str]:
    """Feed ``raw`` as the child's whole stdout; return the terminal outcomes seen."""
    from controller.object_probe_runner import ObjectProbeRunner

    FakeProcess.instances = []
    runner = ObjectProbeRunner(qapp, process_factory=FakeProcess)
    outcomes: list[str] = []

    def on_finished(_job_id, answer):
        if answer.get("status") != "complete":  # a typed refusal (resource_limited, ...): inline fallback
            outcomes.append("failed")
            return
        try:
            mgr.install_page_entry(TARGET, page_entry_from_json(answer["entry"]))
            outcomes.append("installed")
        except Exception as exc:  # the coordinator's catch: anything but ValueError is a defect
            outcomes.append("failed" if type(exc) is ValueError else f"escaped {type(exc).__name__}")

    runner.finished.connect(on_finished)
    runner.failed.connect(lambda _j: outcomes.append("failed"))
    runner.submit(object(), "text", (b"pdf", str(TARGET).encode()))
    runner.submit(object(), "text", (b"pdf", b"2"))  # the queued second job
    proc = FakeProcess.instances[0]
    proc.started.emit()
    proc.out = raw
    proc.readyReadStandardOutput.emit()
    if not proc.killed:
        proc.finished.emit(0, QProcess.ExitStatus.NormalExit)
    else:
        proc.finished.emit(1, QProcess.ExitStatus.CrashExit)
    assert len(FakeProcess.instances) == 2, "the queued job did not start"
    return outcomes


def _line(envelope: dict, **dump) -> bytes:
    return json.dumps(envelope, **dump).encode("utf-8") + b"\n"


def _fields():
    out = []
    for coll, cls in (
        ("blocks", text_block.TextBlock), ("spans", text_block.EditableSpan),
        ("paragraphs", text_block.EditableParagraph), ("fallback_rows", text_block.FallbackRow),
    ):
        for name, kind in text_block._FIELD_KINDS[cls].items():
            out.append((coll, name, kind))
    return out


def _bad_values(kind: str) -> list:
    wrong = 5 if kind in ("str", "str_list") else "wrong"
    values = [None, wrong, NAN, 10**400, True, []]
    if kind in ("rect", "point", "color", "dir", "bbox4"):
        values += [[NAN] * 4, [None] * 2, [10**400] * 4, [float("inf")] * 2]
    if kind == "str":
        values.append(chr(0xD800))
    if kind == "str_list":
        values.append([chr(0xD800)])
    if kind == "int":
        values += [2**31 + 1, -(2**31) - 1, 1.5]
    if kind == "float":
        values += [float("inf"), "12.0"]
    return values


def _named_mutations() -> dict:
    def dup_span(e):
        e["spans"][1]["span_id"] = e["spans"][0]["span_id"]

    def dup_block(e):
        e["blocks"][1]["block_id"] = e["blocks"][0]["block_id"]

    def dup_para(e):
        e["paragraphs"][1]["paragraph_id"] = e["paragraphs"][0]["paragraph_id"]

    def missing_run(e):
        e["paragraphs"][0]["run_ids"] = ["missing"]

    def empty_map(e):
        e["run_map"] = {}

    def swapped_map(e):
        first = next(iter(e["run_map"]))
        other = next(p["paragraph_id"] for p in e["paragraphs"] if p["paragraph_id"] != e["run_map"][first])
        e["run_map"][first] = other

    def extra_map(e):
        e["run_map"][e["spans"][0]["span_id"] + "x"] = e["paragraphs"][0]["paragraph_id"]

    def huge_int(e):
        e["spans"][0]["block_idx"] = 10**400

    def surrogate(e):
        e["spans"][0]["text"] = chr(0xD800)

    def other_page(e):
        for s in e["spans"]:
            s["page_idx"] = 0

    return {
        "dup_span_id": dup_span, "dup_block_id": dup_block, "dup_paragraph_id": dup_para,
        "run_ids_missing": missing_run, "run_map_empty": empty_map, "run_map_swapped": swapped_map,
        "run_map_extra_key": extra_map, "huge_int": huge_int, "lone_surrogate": surrogate,
        "other_page": other_page,
    }


NAMED = _named_mutations()
FIELD_CASES = [
    pytest.param(coll, name, kind, idx, id=f"{coll}.{name}#{idx}")
    for coll, name, kind in _fields()
    for idx in range(len(_bad_values(kind)))
]


def _assert_invalid(qapp, good, raw: bytes) -> None:
    pdf = good[0]
    mgr = _populated(pdf)
    before = _snapshot(mgr)
    assert _run(qapp, mgr, raw) == ["failed"]
    assert _snapshot(mgr) == before


def test_the_unmutated_answer_installs_the_expected_entry(qapp, good):
    pdf, envelope, expected = good
    mgr = _populated(pdf)
    assert _run(qapp, mgr, _line(envelope)) == ["installed"]
    assert mgr.get_blocks(TARGET) == list(expected.blocks)
    assert mgr.get_spans(TARGET) == list(expected.spans)
    assert mgr.get_paragraphs(TARGET) == list(expected.paragraphs)
    assert mgr.get_fallback_rows(TARGET) == list(expected.fallback_rows)
    assert mgr._run_to_paragraph[TARGET] == {r: p.paragraph_id for p in expected.paragraphs for r in p.run_ids}
    assert mgr.page_state(TARGET) == "clean"
    assert mgr.page_state(0) == "clean" and mgr.page_state(2) == "clean"


@pytest.mark.parametrize("name", list(NAMED))
def test_named_invariant_violations_fail_once_and_change_nothing(qapp, good, name):
    envelope = copy.deepcopy(good[1])
    NAMED[name](envelope["entry"])
    _assert_invalid(qapp, good, _line(envelope))


@pytest.mark.parametrize(("coll", "name", "kind", "idx"), FIELD_CASES)
def test_every_field_mutated_fails_once_and_changes_nothing(qapp, good, coll, name, kind, idx):
    envelope = copy.deepcopy(good[1])
    envelope["entry"][coll][0][name] = _bad_values(kind)[idx]
    _assert_invalid(qapp, good, _line(envelope))


@pytest.mark.parametrize("status", [[], {}, None, 7, ["complete"]])
def test_a_non_string_status_is_one_failure(qapp, good, status):
    envelope = copy.deepcopy(good[1])
    envelope["status"] = status
    _assert_invalid(qapp, good, _line(envelope))


@pytest.mark.parametrize("where", ["envelope", "entry_value"])
def test_json_nested_beyond_the_recursion_limit_is_one_failure(qapp, good, where):
    depth = 200_000
    nest = b"[" * depth + b"]" * depth
    if where == "envelope":
        raw = nest + b"\n"
    else:
        head = json.dumps({k: v for k, v in good[1].items() if k != "entry"})[:-1].encode()
        raw = head + b', "entry": {"blocks": ' + nest + b"}}\n"
    _assert_invalid(qapp, good, raw)


def test_padding_to_cap_plus_one_is_one_failure_and_exactly_cap_is_accepted(qapp, good):
    body = json.dumps(good[1]).encode("utf-8")
    _assert_invalid(qapp, good, body + b" " * (TEXT_ANSWER_MAX_BYTES + 1 - len(body)) + b"\n")
    mgr = _populated(good[0])
    assert _run(qapp, mgr, body + b" " * (TEXT_ANSWER_MAX_BYTES - len(body)) + b"\n") == ["installed"]


def test_an_over_cap_stdout_is_one_failure_outcome_and_advances(qapp, good):
    mgr = _populated(good[0])
    before = _snapshot(mgr)
    outcomes = _run(qapp, mgr, b"x" * (TEXT_ANSWER_MAX_BYTES + 100_000))
    assert outcomes == ["failed"]  # resource_limited reaches the decoder, which refuses it
    assert _snapshot(mgr) == before


def test_meaning_preserving_mutations_equal_the_original(qapp, good):
    pdf, envelope, expected = good
    variants = {
        "sorted_keys": _line(envelope, sort_keys=True),
        "indent": _line(envelope, indent=2),
        "spaced": _line(envelope, separators=(" , ", " : ")),
        "ascii_off": _line(envelope, ensure_ascii=False),
        "leading_noise_line": b"advisory text\n" + _line(envelope),
        "trailing_noise_line": _line(envelope) + b"more noise\n",
        "padded_under_cap": json.dumps(envelope).encode() + b" " * 4096 + b"\n",
    }
    reference = None
    for label, raw in variants.items():
        if label == "indent":
            continue  # indent spreads the answer over many lines: not one answer line
        mgr = _populated(pdf)
        assert _run(qapp, mgr, raw) == ["installed"], label
        state = (mgr.get_blocks(TARGET), mgr.get_spans(TARGET), mgr.get_paragraphs(TARGET),
                 mgr._run_to_paragraph[TARGET], mgr._page_plain_lines[TARGET], mgr.get_fallback_rows(TARGET))
        if reference is None:
            reference = state
        assert state == reference, label
    assert reference[1] == list(expected.spans)


def test_the_mutation_table_is_large_enough():
    assert len(NAMED) + len(FIELD_CASES) >= 150
    assert dataclasses.is_dataclass(text_block.PageIndexEntry)
