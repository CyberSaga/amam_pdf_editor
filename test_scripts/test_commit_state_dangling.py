"""D23: the digest table records references to objects that do not exist (dangling references)."""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.vector_paths.commit_state import WriteSet, digest_table, undeclared  # noqa: E402
from test_scripts import vector_oracles as vo  # noqa: E402


def _base() -> tuple[fitz.Document, int, int]:
    """One page with a content stream; returns (doc, content-stream xref, a plain side object xref)."""
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(fitz.Rect(0, 0, 10, 10), fill=(0, 0, 0))
    page.clean_contents()
    doc.update_stream(page.get_contents()[0], b"0 0 10 10 re f\n", compress=False)
    side = doc.get_new_xref()
    doc.update_object(side, "<< /Note (side) >>")
    return doc, page.get_contents()[0], side


def _reopen(doc: fitz.Document) -> fitz.Document:
    return fitz.open(stream=doc.tobytes(garbage=0), filetype="pdf")


def test_a_declared_stream_gaining_a_dangling_reference_is_reported() -> None:
    doc, stream, side = _base()
    before = _reopen(doc)
    doc.xref_set_key(stream, "Extra", "9999 0 R")  # a declared stream may change; a dangling reference may not appear
    after = _reopen(doc)
    ws = WriteSet(after.page_xref(0), frozenset({stream}), frozenset())
    assert undeclared(digest_table(before), digest_table(after), ws) == [stream]


def test_a_free_slot_target_is_dangling() -> None:
    doc, stream, side = _base()
    before = _reopen(doc)
    doc.xref_set_key(stream, "Extra", f"{side} 0 R")
    mid = _reopen(doc)
    ws = WriteSet(mid.page_xref(0), frozenset({stream}), frozenset())
    assert undeclared(digest_table(before), digest_table(mid), ws) == []  # a live target is not dangling
    doc.update_object(side, "null")
    after = _reopen(doc)
    ws2 = WriteSet(after.page_xref(0), frozenset({stream, side}), frozenset())
    assert undeclared(digest_table(mid), digest_table(after), ws2) == [stream]


def test_a_commit_that_removes_the_target_of_an_untouched_object_is_reported() -> None:
    doc, stream, side = _base()
    holder = doc.get_new_xref()
    doc.update_object(holder, f"<< /Ref {side} 0 R >>")
    before = _reopen(doc)
    doc.update_object(side, "null")
    after = _reopen(doc)
    ws = WriteSet(after.page_xref(0), frozenset({side}), frozenset())
    assert undeclared(digest_table(before), digest_table(after), ws) == [holder]


def test_a_dangling_reference_that_was_already_there_is_not_a_change() -> None:
    doc, stream, side = _base()
    doc.update_object(side, "<< /Note (side) /Gone 9999 0 R /Nope 0 0 R >>")
    before, after = _reopen(doc), _reopen(doc)
    tb, ta = digest_table(before), digest_table(after)
    assert tb == ta
    assert tb.dangling  # the pre-existing dangling reference is recorded ...
    assert undeclared(tb, ta, WriteSet(after.page_xref(0), frozenset(), frozenset())) == []  # ... and is not a change


def test_reference_zero_is_not_dangling() -> None:
    doc, stream, side = _base()
    doc.update_object(side, "<< /A 0 0 R >>")
    assert not digest_table(_reopen(doc)).dangling


def test_rule_b_catches_a_dangling_reference_in_a_declared_stream() -> None:
    doc, stream, side = _base()
    before = doc.tobytes(garbage=0)
    doc.xref_set_key(stream, "Extra", "9999 0 R")
    after = doc.tobytes(garbage=0)
    got = vo.rule_b("delete", before, after, page_xref=fitz.open(stream=after, filetype="pdf").page_xref(0), stream_xrefs=[stream], new_xrefs=[])
    assert got == [f"rule B: object {stream} changed outside the declared write set"]
