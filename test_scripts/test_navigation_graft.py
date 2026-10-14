"""F16-NAV-3: ``NavigationGraft`` copies pages together with their navigation data.

The merge / export / import entry points are covered in ``test_merge_composition.py``
and ``test_headless_merge.py``; this module pins the graft itself: the object
reader, the name and number trees (``/Kids``), legacy ``/Dests``, label prefixes
that need escaping, repeated and reordered pages, and the PyMuPDF behaviour the
graft exists to compensate for.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model import navigation_graft as ng  # noqa: E402
from model.navigation_graft import NavigationGraft  # noqa: E402
from test_scripts.navigation_fixtures import _add_link, link_targets, make_nav_pdf  # noqa: E402


def _blank(pages: int) -> fitz.Document:
    doc = fitz.open()
    for index in range(pages):
        doc.new_page(width=300, height=300).insert_text((20, 40), f"P{index + 1}")
    return doc


def _reopen(doc: fitz.Document) -> fitz.Document:
    return fitz.open("pdf", doc.tobytes())


def _graft(src: fitz.Document, pages: list[int] | None = None) -> fitz.Document:
    dst = fitz.open()
    graft = NavigationGraft(dst)
    graft.copy_pages(src, pages)
    graft.finish()
    return _reopen(dst)


# --- the object reader --------------------------------------------------------


def test_reader_parses_strings_names_refs_arrays_and_dictionaries() -> None:
    tok, end = ng._parse(r"<</A[1 0 R (a\(b\)\\c\101) <FEFF0041> /N#20x 3.5 null]/B<</C true>>>> tail")
    assert tok.kind == "dict" and end == len(r"<</A[1 0 R (a\(b\)\\c\101) <FEFF0041> /N#20x 3.5 null]/B<</C true>>>>")
    items = tok.val["A"].val
    assert [item.kind for item in items] == ["ref", "str", "str", "name", "atom", "atom"]
    assert items[0].val == 1
    assert items[1].val == b"a(b)\\cA"
    assert items[2].val == b"\xfe\xff\x00A"
    assert items[3].val == "N x"
    assert tok.val["B"].val["C"].text == "true"
    # the element text is kept verbatim: a destination array is copied by its text
    assert tok.val["A"].text.startswith("[1 0 R (a")


@pytest.mark.parametrize("text", ["[1 2", "<</A 1", "(open", "<AB", "<</A>>", ")", ""])
def test_reader_rejects_malformed_objects(text: str) -> None:
    with pytest.raises(ValueError):
        ng._parse(text)


def test_reader_refuses_runaway_nesting() -> None:
    with pytest.raises(ValueError):
        ng._parse("[" * 200 + "]" * 200)


# --- what PyMuPDF alone does (the reason the graft exists) -----------------------


def test_pymupdf_insert_pdf_alone_drops_named_and_fit_links_and_all_navigation(tmp_path: Path) -> None:
    """Pin: when this starts failing PyMuPDF copies them itself and the graft would duplicate."""
    path = tmp_path / "nav.pdf"
    make_nav_pdf(path)
    src = fitz.open(path)
    dst = fitz.open()
    dst.insert_pdf(src)
    try:
        assert len(src[0].get_links()) == 5
        assert len(dst[0].get_links()) == 2  # only the explicit GoTo and the URI survive
        assert dst.get_toc() == [] and dst.get_page_labels() == [] and dst.resolve_names() == {}
    finally:
        dst.close()
        src.close()


def test_graft_does_not_duplicate_the_links_pymupdf_copies(tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    make_nav_pdf(path)
    src = fitz.open(path)
    merged = _graft(src)
    try:
        assert len(merged[0].get_links()) == 5
        assert sorted(link_targets(merged, 0)) == [80, 600, 662, 712]  # the URI link has no destination
    finally:
        merged.close()
        src.close()


# --- name trees ---------------------------------------------------------------


def test_names_from_a_kids_tree_and_legacy_dests_are_merged_and_links_follow() -> None:
    src = _blank(3)
    catalog = src.pdf_catalog()
    left = src.get_new_xref()
    right = src.get_new_xref()
    root = src.get_new_xref()
    src.update_object(left, f"<</Names[(alpha)[{src[0].xref} 0 R/Fit](beta)<</D[{src[1].xref} 0 R/FitH 10]>>]>>")
    src.update_object(right, f"<</Names[(gamma)[{src[2].xref} 0 R/XYZ 5 6 null]]>>")
    src.update_object(root, f"<</Kids[{left} 0 R {right} 0 R]>>")
    src.xref_set_key(catalog, "Names", f"<</Dests {root} 0 R>>")
    src.xref_set_key(catalog, "Dests", f"<</legacy[{src[1].xref} 0 R/Fit]>>")
    _add_link(src, src[0], "10 10 50 50", "<</S/GoTo/D/legacy>>")
    _add_link(src, src[0], "10 60 50 100", "<</S/GoTo/D(gamma)>>")

    merged = _graft(src, [1, 2, 0])  # reordered: source pages 2, 3, 1

    try:
        names = merged.resolve_names()
        assert set(names) == {"alpha", "beta", "gamma", "legacy"}
        assert names["alpha"]["page"] == 2  # source page 1 is now the last page
        assert names["beta"]["page"] == 0 and names["gamma"]["page"] == 1 and names["legacy"]["page"] == 0
        assert names["gamma"]["to"] == (5.0, 6.0)
        # the legacy-name link and the tree-name link both resolve in the merged name tree
        assert link_targets(merged, 2) == {250: "legacy", 200: "gamma"}
    finally:
        merged.close()
        src.close()


def test_a_name_whose_page_was_not_copied_is_dropped_with_its_links() -> None:
    src = _blank(3)
    catalog = src.pdf_catalog()
    leaf = src.get_new_xref()
    src.update_object(leaf, f"<</Names[(kept)[{src[0].xref} 0 R/Fit](gone)[{src[2].xref} 0 R/Fit]]>>")
    src.xref_set_key(catalog, "Names", f"<</Dests {leaf} 0 R>>")
    _add_link(src, src[0], "10 10 50 50", "<</S/GoTo/D(gone)>>")
    _add_link(src, src[0], "10 60 50 100", "<</S/GoTo/D(kept)>>")

    merged = _graft(src, [0, 1])

    try:
        assert set(merged.resolve_names()) == {"kept"}
        assert sorted(link_targets(merged, 0).values()) == ["kept"]
    finally:
        merged.close()
        src.close()


def test_non_ascii_name_bytes_round_trip_into_the_merged_tree() -> None:
    src = _blank(2)
    key = "<FEFF7AE0>"  # a UTF-16 text string: exact bytes matter, not a decoded name
    leaf = src.get_new_xref()
    src.update_object(leaf, f"<</Names[{key}[{src[1].xref} 0 R/Fit]]>>")
    src.xref_set_key(src.pdf_catalog(), "Names", f"<</Dests {leaf} 0 R>>")
    _add_link(src, src[0], "10 10 50 50", f"<</S/GoTo/D{key}>>")

    merged = _graft(src)

    try:
        kind, value = merged.xref_get_key(merged.pdf_catalog(), "Names/Dests")
        assert kind == "xref"
        assert "<FEFF7AE0>" in merged.xref_object(int(value.split()[0]), compressed=True).upper()
        link = merged[0].get_links()[0]
        # the link carries the same key bytes as the tree entry and as the source link
        assert link["kind"] == fitz.LINK_NAMED and link["nameddest"] == src[0].get_links()[0]["nameddest"]
        assert "/D<FEFF7AE0>" in merged.xref_object(link["xref"], compressed=True).upper()
    finally:
        merged.close()
        src.close()


# --- page labels --------------------------------------------------------------


def test_label_prefix_with_parentheses_and_backslash_is_written_escaped() -> None:
    src = _blank(3)
    src.xref_set_key(src.pdf_catalog(), "PageLabels", r"<</Nums[0<</P(A-\(\\)/S/D/St 4>>]>>")

    merged = _graft(src)

    try:
        assert ng._read_label_rules(merged) == [(0, "A-(\\", "D", 4)]
        # PyMuPDF's own get_label() mis-reads an escaped prefix, so the written rule is checked raw
        assert r"/P(A-\(\\)" in merged.xref_get_key(merged.pdf_catalog(), "PageLabels")[1]
    finally:
        merged.close()
        src.close()


def test_labels_from_a_number_tree_with_kids_and_a_gap_before_the_first_rule() -> None:
    src = _blank(5)
    low = src.get_new_xref()
    high = src.get_new_xref()
    root = src.get_new_xref()
    src.update_object(low, "<</Nums[2<</S/a>>]>>")
    src.update_object(high, "<</Nums[4<</S/D/P(X)>>]>>")
    src.update_object(root, f"<</Kids[{low} 0 R {high} 0 R]>>")
    src.xref_set_key(src.pdf_catalog(), "PageLabels", f"{root} 0 R")

    merged = _graft(src)

    try:
        # pages before the first rule have no label; the rules re-emerge unchanged
        assert [merged[i].get_label() for i in range(5)] == ["", "", "a", "b", "X1"]
    finally:
        merged.close()
        src.close()


# --- repeated and reordered pages ----------------------------------------------


def test_a_page_copied_twice_keeps_its_links_on_both_copies_and_one_bookmark() -> None:
    src = _blank(3)
    _add_link(src, src[0], "10 10 50 50", f"<</S/GoTo/D[{src[1].xref} 0 R/Fit]>>")
    src.set_toc([[1, "First", 1], [1, "Second", 2]])

    merged = _graft(src, [0, 1, 0])

    try:
        assert link_targets(merged, 0) == {250: 1}
        assert link_targets(merged, 2) == {250: 1}
        assert [row[1:3] for row in merged.get_toc()] == [["First", 1], ["Second", 2]]
    finally:
        merged.close()
        src.close()


def test_an_explicit_goto_across_insert_runs_is_restored() -> None:
    """insert_pdf keeps a GoTo only when the target is in the same call's page range."""
    src = _blank(3)
    _add_link(src, src[0], "10 10 50 50", f"<</S/GoTo/D[{src[1].xref} 0 R/XYZ 1 2 0]>>")
    plain = fitz.open()
    plain.insert_pdf(src, from_page=1, to_page=1)
    plain.insert_pdf(src, from_page=0, to_page=0)
    assert plain[1].get_links() == []  # PyMuPDF drops it: target page 2 is in the other call

    merged = _graft(src, [1, 0])  # two runs

    try:
        assert link_targets(merged, 1) == {250: 0}
    finally:
        merged.close()
        plain.close()
        src.close()


def test_a_bookmark_to_a_page_that_was_not_copied_is_dropped_and_children_are_promoted() -> None:
    src = _blank(4)
    src.set_toc([[1, "Part", 1], [2, "Chapter", 2], [3, "Section", 3], [1, "Tail", 4]])

    merged = _graft(src, [1, 2])  # "Part" and "Tail" are gone

    try:
        assert [(row[0], row[1], row[2]) for row in merged.get_toc()] == [(1, "Chapter", 1), (2, "Section", 2)]
    finally:
        merged.close()
        src.close()


def test_a_broken_outline_does_not_stop_the_page_copy(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    src = _blank(2)
    src.set_toc([[1, "One", 1]])

    def boom(*_args, **_kwargs):
        raise RuntimeError("outline walk failed")

    monkeypatch.setattr(ng, "_read_outline", boom)
    with caplog.at_level("WARNING", logger="model.navigation_graft"):
        merged = _graft(src)
    try:
        assert len(merged) == 2
        assert merged.get_toc() == []
        assert "outline not carried" in caplog.text
    finally:
        merged.close()
        src.close()


def test_copy_pages_returns_the_target_indices_and_inserts_at_start_at() -> None:
    src = _blank(2)
    dst = _blank(3)
    try:
        graft = NavigationGraft(dst, keep_names=False, outline=False, labels=False)
        assert graft.copy_pages(src, [0, 1], start_at=1) == [1, 2]
        assert graft.copy_pages(src, []) == []
        graft.finish()
        assert [dst[i].get_text().strip() for i in range(5)] == ["P1", "P1", "P2", "P2", "P3"]
    finally:
        dst.close()
        src.close()
