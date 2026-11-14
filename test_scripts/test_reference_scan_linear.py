"""Indirect-reference scans stay linear on a long digit run (quadratic-regex guard)."""

from __future__ import annotations

import re
import time

import fitz
import pytest

from model import page_snapshot, save_compaction
from model.text_commit import inspect as text_inspect
from model.text_commit import verify as text_verify

_OLD = re.compile(r"(\d+)\s+\d+\s+R(?![A-Za-z0-9])")
_DIGITS = 30_000
_BOUND_S = 0.5

_NORMAL_TEXTS = [
    "<< /Type /Page /Parent 3 0 R /Contents 12 0 R >>",
    "[1 0 R 2 0 R\n3   0\nR 4 0 R]",
    "<</A 1 0 R/B[2 0 R 3 0 R]/C<</D 4 0 R>>>>",
    "<< /K 1 0 RG /L 2 0 R /M 3 0 Rx /N 4 0 R9 >>",
    "(12 0 R) 7 0 R",
    "<< /X 10\t0\r\nR /Y 123456 65535 R>>",
    "5 6 7 0 R",
    "x12 0 R 3 4 R",
    "no refs here 1 2 3",
    "",
]


def _digit_doc() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page()
    doc.xref_set_key(page.xref, "Foo", "(" + "1" * _DIGITS + ")")
    return doc


@pytest.mark.parametrize("text", _NORMAL_TEXTS)
def test_snapshot_ref_scan_matches_old_regex(text: str) -> None:
    assert page_snapshot._RE_REF.findall(text) == _OLD.findall(text)


@pytest.mark.parametrize("text", _NORMAL_TEXTS)
def test_compaction_ref_scan_matches_old_regex(text: str) -> None:
    assert save_compaction._RE_REF.findall(text) == _OLD.findall(text)


def test_ref_scan_known_values() -> None:
    text = "<< /A 12 0 R /B [3 0 R] /C 1 0 RG /D 5\n\n 0\nR >>"
    assert save_compaction._RE_REF.findall(text) == ["12", "3", "5"]
    assert page_snapshot._RE_REF.findall(text) == ["12", "3", "5"]


@pytest.mark.parametrize(
    "pattern",
    [
        page_snapshot._RE_REF,
        save_compaction._RE_REF,
        text_inspect._XREF_REF_RE,
        text_verify._INDIRECT_REF_RE,
    ],
)
def test_pattern_linear_on_digit_run(pattern: re.Pattern[str]) -> None:
    text = "1" * _DIGITS + " x"
    start = time.perf_counter()
    pattern.findall(text)
    assert time.perf_counter() - start < _BOUND_S


def test_reachable_xrefs_linear_on_long_digit_string() -> None:
    doc = _digit_doc()
    try:
        start = time.perf_counter()
        reachable = save_compaction.reachable_xrefs(doc)
        elapsed = time.perf_counter() - start
        assert 1 in reachable
        assert elapsed < _BOUND_S
    finally:
        doc.close()


def test_capture_page_graph_linear_when_parser_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_text: str):
        raise ValueError("over budget")

    monkeypatch.setattr(page_snapshot, "parse_pdf_value", refuse)
    doc = _digit_doc()
    try:
        start = time.perf_counter()
        snap = page_snapshot.capture_page_graph(doc, 0, xref_epoch=0)
        elapsed = time.perf_counter() - start
        assert snap is not None
        assert elapsed < _BOUND_S
    finally:
        doc.close()
