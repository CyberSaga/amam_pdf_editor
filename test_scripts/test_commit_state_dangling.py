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


def _typed_reference_walk(text: str) -> set[int]:
    """An independent typed walk of one printed object: the targets of every ``n g R`` that is a real
    reference (strings, hex strings and comments are skipped as units, names are single tokens)."""
    ws, delims = " \t\r\n\f\0", "()<>[]{}/%"
    toks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in ws:
            i += 1
        elif c == "(":
            depth = 0
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                depth += (text[i] == "(") - (text[i] == ")")
                i += 1
                if depth == 0:
                    break
            toks.append("<str>")
        elif text.startswith("<<", i) or text.startswith(">>", i):
            toks.append(text[i : i + 2])
            i += 2
        elif c == "<":
            i = text.index(">", i) + 1
            toks.append("<hex>")
        elif c == "%":
            while i < n and text[i] not in "\r\n":
                i += 1
        elif c in "[]{}>)":
            toks.append(c)
            i += 1
        elif c == "/":
            j = i + 1
            while j < n and text[j] not in ws and text[j] not in delims:
                j += 1
            toks.append("/name")
            i = j
        else:
            j = i
            while j < n and text[j] not in ws and text[j] not in delims:
                j += 1
            toks.append(text[i:j])
            i = j
    return {
        int(toks[k]) for k in range(len(toks) - 2) if toks[k].isdigit() and toks[k + 1].isdigit() and toks[k + 2] == "R" and int(toks[k]) != 0
    }


_TYPED_CORPUS = [
    "<< /A 9001 0 R >>",  # a real reference in a dictionary
    "<< /A [9002 0 R 9003 0 R] >>",  # in an array
    "<< /Note (9004 0 R) >>",  # a string: not a reference
    "<< /Note (nested (9005 0 R) and \\) 9006 0 R still string) /B 9007 0 R >>",  # nested parens, escaped paren
    "<< /Note <3939303820302052> /B 9009 0 R >>",  # a hex string spelling a reference
    "<< /Note (a \\\\) /B 9010 0 R >>",  # escaped backslash then a real reference
    "<< /K#209011 9012 0 R >>",  # a name that merely ends in digits
    "<< /D << /E (9013 0 R) /F 9014 0 R >> /G [ (9015 0 R) 9016 0 R ] >>",  # mixed nesting
    "<< /A 9017 0 R /Note (tail 9018 0 R) >>",
]


def test_recorded_references_equal_a_typed_object_walk_across_every_syntax_class() -> None:
    """Astra B4 (class: lexical scan standing in for a typed walk).  For each corpus object the references
    the digest table records equal those an independent typed walk finds (strings, hex strings and
    comments contribute none; names, arrays and dictionaries are kept)."""
    for text in _TYPED_CORPUS:
        doc, _stream, side = _base()
        doc.update_object(side, text)
        got = {t for s, t in digest_table(_reopen(doc)).dangling if s == side}
        assert got == _typed_reference_walk(text), text


def test_a_harmless_string_added_to_a_declared_stream_is_not_a_dangling_change() -> None:
    doc, stream, _side = _base()
    before = _reopen(doc)
    doc.xref_set_key(stream, "Note", "(9999 0 R)")
    after = _reopen(doc)
    ws = WriteSet(after.page_xref(0), frozenset({stream}), frozenset())
    assert undeclared(digest_table(before), digest_table(after), ws) == []
    doc.xref_set_key(stream, "Note", "<393939392030205220>")
    ws = WriteSet(after.page_xref(0), frozenset({stream}), frozenset())
    assert undeclared(digest_table(before), digest_table(_reopen(doc)), ws) == []


def test_rule_b_catches_a_dangling_reference_in_a_declared_stream() -> None:
    doc, stream, side = _base()
    before = doc.tobytes(garbage=0)
    doc.xref_set_key(stream, "Extra", "9999 0 R")
    after = doc.tobytes(garbage=0)
    got = vo.rule_b("delete", before, after, page_xref=fitz.open(stream=after, filetype="pdf").page_xref(0), stream_xrefs=[stream], new_xrefs=[])
    assert got == [f"rule B: object {stream} changed outside the declared write set"]
