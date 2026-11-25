"""Card B6 part 2, helpers (plans/b6-commit-design-astra.md section 1): reference_counts and vector_page_prestate.  Red first."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.vector_paths import commit_state as cs  # noqa: E402

# --------------------------------------------------------------------------- reference_counts


@pytest.mark.parametrize(
    "snapshot, want",
    [
        (b"[5 0 R]", {5: 1}),
        (b"15 0 R", {5: 0, 15: 1}),  # 15 0 R is not a reference to 5
        (b"/K 5 7 R]", {5: 1}),  # any generation counts
        (b"5 0 R 5 0 R /A 5 0 R", {5: 3}),
        (b"5\x000 R", {5: 1}),  # NUL is PDF whitespace
        (b"5 0 R", {5: 1}),  # EOF right after R
        (b"5 0 Rx", {5: 0}),  # R continues into a regular character
        (b"5 0 R/Name", {5: 1}),  # a delimiter ends R
        (b"05 0 R", {5: 1}),  # numeric comparison
        (b"1 5 0 R", {5: 1, 1: 0}),  # the earlier number is not part of the reference
        (b"x5 0 R", {5: 1}),  # a letter before the number is not a digit
        (b"25 0 R 5 0 obj", {5: 0, 25: 1}),
        (b"", {5: 0}),
    ],
)
def test_reference_counts(snapshot, want):
    got = cs.reference_counts(snapshot, list(want))
    assert got == want


def test_reference_counts_has_one_entry_per_distinct_requested_xref_including_zero():
    assert cs.reference_counts(b"3 0 R", [3, 3, 9]) == {3: 1, 9: 0}


def test_reference_counts_scans_stream_payloads_and_strings_too():
    snap = b"1 0 obj\n<< /Length 9 >>\nstream\n5 0 R\nendstream\nendobj (5 0 R)"
    assert cs.reference_counts(snap, [5]) == {5: 2}


# --------------------------------------------------------------------------- vector_page_prestate


def _doc_with_stream(content: bytes = b"0 0 m 1 1 l S", extra: str = ""):
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.insert_text((5, 5), " ")
    xref = page.get_contents()[0]
    doc.update_stream(xref, content)
    if extra:
        doc.xref_set_key(xref, extra.split(" ", 1)[0], extra.split(" ", 1)[1])
    return doc, page, xref


def test_prestate_records_contents_text_digest_and_dictionary():
    doc, page, xref = _doc_with_stream()
    pre = cs.vector_page_prestate(doc, page)
    assert pre.contents is not None and f"{xref} 0 R" in pre.contents  # the exact printed value, array or reference
    assert len(pre.streams) == 1 and pre.streams[0].xref == xref
    assert pre.streams[0].decoded_sha256 == hashlib.sha256(b"0 0 m 1 1 l S").digest()
    keys = [k for k, _ in pre.streams[0].dictionary]
    assert keys == sorted(keys) and "/Length" not in keys


def test_prestate_is_equal_across_a_null_pass_and_differs_on_content_or_dictionary():
    doc, page, xref = _doc_with_stream()
    a = cs.vector_page_prestate(doc, page)
    assert cs.vector_page_prestate(doc, page) == a
    doc.update_stream(xref, b"0 0 m 2 2 l S")
    assert cs.vector_page_prestate(doc, page) != a
    doc2, page2, _ = _doc_with_stream(extra="/Foo 7")
    assert cs.vector_page_prestate(doc2, page2) != cs.vector_page_prestate(*_doc_with_stream()[:2])


def test_prestate_resolves_an_indirect_scalar_value_but_keeps_other_references_identifiable():
    doc, page, xref = _doc_with_stream()
    scalar = doc.get_new_xref()
    doc.update_object(scalar, "42")
    doc.xref_set_key(xref, "Foo", f"{scalar} 0 R")
    target = doc.get_new_xref()
    doc.update_object(target, "<< /A 1 >>")
    doc.xref_set_key(xref, "Bar", f"{target} 0 R")
    items = dict(cs.vector_page_prestate(doc, page).streams[0].dictionary)
    assert items["/Foo"] == "42"
    assert items["/Bar"] == f"{target} 0 R"


def test_prestate_of_an_empty_stream_digests_the_empty_bytes_and_a_page_without_contents_is_none():
    doc, page, _ = _doc_with_stream(b"")
    assert cs.vector_page_prestate(doc, page).streams[0].decoded_sha256 == hashlib.sha256(b"").digest()
    blank = fitz.open()
    pg = blank.new_page()
    pre = cs.vector_page_prestate(blank, pg)
    assert pre.contents is None and pre.streams == ()


# --------------------------------------------------------------------------- save-stable comparison (found on real files, 2026-11-26)


def _digest_of_object(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page()
    x = doc.get_new_xref()
    doc.update_object(x, text)
    return cs.digest_table(doc).entries[x]


def test_digest_ignores_dictionary_key_order_at_every_level_but_not_values():
    a = _digest_of_object("<< /A 1 /B << /X 2 /Y [ << /P 1 /Q 2 >> ] >> >>")
    b = _digest_of_object("<< /B << /Y [ << /Q 2 /P 1 >> ] /X 2 >> /A 1 >>")
    assert a == b
    assert a != _digest_of_object("<< /A 1 /B << /X 3 /Y [ << /P 1 /Q 2 >> ] >> >>")
    assert a != _digest_of_object("<< /A 1 /B << /X 2 /Y [ << /Q 2 /P 1 >> << /Z 1 >> ] >> >>")  # array content


def test_equivalent_survives_a_save_that_drops_object_streams_but_not_a_changed_object(tmp_path):
    doc = fitz.open()
    for _ in range(3):
        doc.new_page().insert_text((10, 10), "x")
    path = tmp_path / "objstm.pdf"
    doc.save(path, use_objstms=1)
    doc.close()
    live = fitz.open(str(path))
    t0 = cs.digest_table(live)
    assert t0.containers, "the fixture must hold an object stream"
    flat = fitz.open("pdf", live.tobytes(garbage=0, use_objstms=0))
    t1 = cs.digest_table(flat)
    assert cs.equivalent(t0, t1) and cs.equivalent(t1, t0)
    flat.update_object(flat.get_new_xref(), "<< /Extra 1 >>")
    assert not cs.equivalent(t0, cs.digest_table(flat))
