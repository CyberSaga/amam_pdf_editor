"""R6.1 — characterization tests for ``PDFModel.compose_merged_document``.

This is the low-level merge primitive (``pdf_model.py``): the controller merge
flow (``merge_ordered_sources_into_current`` / ``save_ordered_sources_as_new``)
is exercised by ``test_pdf_merge_workflow.py``, but the model method that
actually stitches the ``fitz.Document`` together had **zero** test references
(census-verified, R6.1). It is exactly the kind of PyMuPDF glue that regresses
silently across a 1.25 -> 1.27 bump, so these tests pin its current behavior:

  * no open document -> ``ValueError``
  * ``source_kind == "current"`` inserts a snapshot of the live doc
  * ``source_kind == "file"`` inserts the foreign file's pages
  * list order is preserved across mixed source kinds
  * unknown ``source_kind`` and a ``"file"`` entry with no ``path`` are skipped
  * an empty / ``None`` source list yields an empty (0-page) document

Assertions check the produced document's page count *and* page text (side
effects / state), not just that an object came back (CLAUDE.md s5.2).
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.edit_commands import SnapshotCommand  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from test_scripts.navigation_fixtures import (  # noqa: E402
    PREFIX,
    labels,
    link_targets,
    make_nav_pdf,
    make_plain_pdf,
    make_rich_src_pdf,
    make_src_pdf,
    outline_attrs,
    resolved_names,
)


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _page_texts(doc: fitz.Document) -> list[str]:
    return ["".join(doc[i].get_text("text").split()) for i in range(len(doc))]


@pytest.fixture()
def model_with_current(tmp_path: Path):
    current = _make_pdf(tmp_path / "Current.pdf", ["CURRENTONE", "CURRENTTWO"])
    model = PDFModel()
    model.open_pdf(str(current))
    try:
        yield model
    finally:
        model.close()


def test_compose_without_open_document_raises() -> None:
    model = PDFModel()
    try:
        with pytest.raises(ValueError):
            model.compose_merged_document([{"source_kind": "current"}])
    finally:
        model.close()


def test_compose_current_source_inserts_live_snapshot(model_with_current) -> None:
    merged = model_with_current.compose_merged_document([{"source_kind": "current"}])
    try:
        assert len(merged) == 2
        assert _page_texts(merged) == ["CURRENTONE", "CURRENTTWO"]
    finally:
        merged.close()


def test_compose_file_source_inserts_foreign_pages(model_with_current, tmp_path: Path) -> None:
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRAPAGE"])
    merged = model_with_current.compose_merged_document(
        [{"source_kind": "file", "path": str(extra)}]
    )
    try:
        assert len(merged) == 1
        assert _page_texts(merged) == ["EXTRAPAGE"]
    finally:
        merged.close()


def test_compose_preserves_list_order_across_mixed_sources(model_with_current, tmp_path: Path) -> None:
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRAPAGE"])
    merged = model_with_current.compose_merged_document(
        [
            {"source_kind": "file", "path": str(extra)},
            {"source_kind": "current"},
        ]
    )
    try:
        # file first, then the two current pages, in declared order.
        assert _page_texts(merged) == ["EXTRAPAGE", "CURRENTONE", "CURRENTTWO"]
    finally:
        merged.close()


def test_compose_skips_unknown_kind_and_pathless_file(model_with_current) -> None:
    merged = model_with_current.compose_merged_document(
        [
            {"source_kind": "mystery"},
            {"source_kind": "file"},  # no path
            {"source_kind": "file", "path": ""},  # empty path
            None,  # malformed entry
        ]
    )
    try:
        assert len(merged) == 0
    finally:
        merged.close()


def test_compose_empty_sources_yields_empty_document(model_with_current) -> None:
    merged_empty = model_with_current.compose_merged_document([])
    merged_none = model_with_current.compose_merged_document(None)  # type: ignore[arg-type]
    try:
        assert len(merged_empty) == 0
        assert len(merged_none) == 0
    finally:
        merged_empty.close()
        merged_none.close()


# --- F16-NAV-3: a merge carries the outline, page labels, named destinations and links ---


def _reopen(doc: fitz.Document) -> fitz.Document:
    """What the controller consumes: the serialized merge, reopened."""
    return fitz.open("pdf", doc.tobytes())


def _names_leaf_text(doc: fitz.Document) -> str:
    kind, value = doc.xref_get_key(doc.pdf_catalog(), "Names/Dests")
    assert kind == "xref"
    return doc.xref_object(int(value.split()[0]), compressed=True)


def _nav_model(tmp_path: Path) -> tuple[PDFModel, Path, fitz.Document]:
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "src.pdf"
    make_nav_pdf(nav)
    make_src_pdf(src)
    model = PDFModel()
    model.open_pdf(str(nav))
    original = fitz.open(nav)
    return model, src, original


def test_merge_keeps_outline_labels_names_and_links_of_every_source(tmp_path: Path) -> None:
    model, src, original = _nav_model(tmp_path)
    try:
        merged = _reopen(
            model.compose_merged_document(
                [{"source_kind": "current"}, {"source_kind": "file", "path": str(src)}]
            )
        )
        try:
            assert len(merged) == 9
            # outline: the current document's five rows, attribute for attribute, then the source's two
            assert [row[1:3] for row in merged.get_toc()] == [
                ["Intro", 2],
                ["Website", -1],
                ["Chapter 4", 4],
                ["Section 4.1", 5],
                ["Last", 6],
                ["Src A", 7],
                ["Src C", 9],
            ]
            attrs = outline_attrs(merged)
            expected = outline_attrs(original)
            assert {title: attrs[title] for title in expected} == expected
            assert expected["Website"][0] == fitz.LINK_URI
            assert expected["Intro"][1] == (0.0, 500.0)
            assert expected["Chapter 4"][7] is True  # collapsed
            assert [row[0] for row in merged.get_toc()] == [1, 1, 1, 2, 1, 1, 1]

            # page labels: the current ones, then the unlabelled source counts 1, 2, 3 again
            assert labels(merged) == [*labels(original), "1", "2", "3"]
            assert (
                fitz.get_pdf_str(PREFIX).upper()
                in merged.xref_get_key(merged.pdf_catalog(), "PageLabels")[1].upper()
            )

            # named destinations: the first source keeps `chap3`, the later one is renamed
            names = merged.resolve_names()
            assert set(names) == {"chap3", "chap3.2"}
            assert names["chap3"]["page"] == 2 and names["chap3"]["to"] == (0.0, 400.0)
            assert names["chap3.2"]["page"] == 7
            assert "/XYZ 0 400 null" in _names_leaf_text(merged)  # the view is copied verbatim

            # links of the current document's first page: explicit, named and /Fit ones
            assert link_targets(merged, 0) == {80: 4, 600: "chap3", 662: 3, 712: 4}
            # links of the source's first page follow the copy (and its renamed destination)
            assert link_targets(merged, 6) == {80: 8, 600: "chap3.2"}
        finally:
            merged.close()
    finally:
        original.close()
        model.close()


def test_merge_keeps_every_source_when_the_file_comes_first(tmp_path: Path) -> None:
    model, src, original = _nav_model(tmp_path)
    try:
        merged = _reopen(
            model.compose_merged_document(
                [{"source_kind": "file", "path": str(src)}, {"source_kind": "current"}]
            )
        )
        try:
            assert [row[1:3] for row in merged.get_toc()] == [
                ["Src A", 1],
                ["Src C", 3],
                ["Intro", 5],
                ["Website", -1],
                ["Chapter 4", 7],
                ["Section 4.1", 8],
                ["Last", 9],
            ]
            # the unlabelled first source counts 1, 2, 3 and the current labels start afresh
            assert labels(merged) == ["1", "2", "3", *labels(original)]
            names = merged.resolve_names()
            assert names["chap3"]["page"] == 1  # the first source owns the plain name
            assert names["chap3.2"]["page"] == 5 and names["chap3.2"]["to"] == (0.0, 400.0)
            assert link_targets(merged, 0) == {80: 2, 600: "chap3"}
            assert link_targets(merged, 3) == {80: 7, 600: "chap3.2", 662: 6, 712: 7}
        finally:
            merged.close()
    finally:
        original.close()
        model.close()


def test_merge_of_documents_without_navigation_invents_none(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    make_plain_pdf(first, 2, "FIRST")
    make_plain_pdf(second, 3, "SECOND")
    model = PDFModel()
    model.open_pdf(str(first))
    try:
        merged = _reopen(
            model.compose_merged_document(
                [{"source_kind": "current"}, {"source_kind": "file", "path": str(second)}]
            )
        )
        try:
            assert len(merged) == 5
            assert merged.get_toc() == []
            assert merged.get_page_labels() == []
            assert merged.resolve_names() == {}
            assert merged.xref_get_key(merged.pdf_catalog(), "PageLabels")[0] == "null"
            assert merged.xref_get_key(merged.pdf_catalog(), "Names")[0] == "null"
            assert merged.xref_get_key(merged.pdf_catalog(), "Outlines")[0] == "null"
        finally:
            merged.close()
    finally:
        model.close()


def test_merge_survives_a_broken_name_tree_and_keeps_the_rest(tmp_path: Path) -> None:
    nav = tmp_path / "nav.pdf"
    make_nav_pdf(nav)
    broken = fitz.open(nav)
    broken.xref_set_key(broken.pdf_catalog(), "Names", "<</Dests 99999 0 R>>")
    broken.save(tmp_path / "broken.pdf")
    broken.close()
    model = PDFModel()
    model.open_pdf(str(tmp_path / "broken.pdf"))
    try:
        merged = _reopen(model.compose_merged_document([{"source_kind": "current"}]))
        try:
            assert len(merged) == 6
            assert [row[1] for row in merged.get_toc()] == ["Intro", "Website", "Chapter 4", "Section 4.1", "Last"]
            assert labels(merged)[:3] == ["i", "ii", "1"]
            assert link_targets(merged, 0)[662] == 3  # the explicit /Fit link still lands on page 4
        finally:
            merged.close()
    finally:
        model.close()


def test_export_pages_carries_the_navigation_of_the_exported_pages_only(tmp_path: Path) -> None:
    nav = tmp_path / "nav.pdf"
    make_nav_pdf(nav)
    out = tmp_path / "export.pdf"
    model = PDFModel()
    model.open_pdf(str(nav))
    try:
        model.export_pages([1, 3, 4, 5], str(out))
    finally:
        model.close()
    exported = fitz.open(out)
    try:
        assert len(exported) == 4
        # Intro (page 2) and Last (page 6) were not exported; the child keeps its level
        assert [row[:3] for row in exported.get_toc()] == [
            [1, "Website", -1],
            [1, "Chapter 4", 3],
            [2, "Section 4.1", 4],
        ]
        assert labels(exported) == ["i", "1", "2", "3"]
        assert exported.resolve_names()["chap3"]["page"] == 1
        assert link_targets(exported, 0) == {80: 3, 600: "chap3", 662: 2, 712: 3}
    finally:
        exported.close()


def test_export_pages_drops_links_and_names_into_pages_that_were_not_exported(tmp_path: Path) -> None:
    nav = tmp_path / "nav.pdf"
    make_nav_pdf(nav)
    out = tmp_path / "export.pdf"
    model = PDFModel()
    model.open_pdf(str(nav))
    try:
        model.export_pages([1, 2], str(out))
    finally:
        model.close()
    exported = fitz.open(out)
    try:
        assert exported.resolve_names() == {}  # chap3 is on page 3
        assert link_targets(exported, 0) == {}  # every link of page 1 points past page 2
        assert [row[1] for row in exported.get_toc()] == ["Intro", "Website"]
    finally:
        exported.close()


def test_insert_pages_from_file_keeps_links_that_pymupdf_drops(tmp_path: Path) -> None:
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "src.pdf"
    make_nav_pdf(nav)
    make_src_pdf(src)
    model = PDFModel()
    model.open_pdf(str(nav))
    try:
        assert model.insert_pages_from_file(str(src), [1, 2], 1) == [1, 2]
        # source page 1 links to source page 2 through its name: the name was imported
        # (renamed, the document owns `chap3`) and the link follows it
        assert link_targets(model.doc, 0) == {600: "chap3.2"}
        # the document's own name and outline items follow their pages
        assert resolved_names(model.doc)["chap3"] == 4
        assert [row[2] for row in model.get_toc()][:5] == [4, -1, 6, 7, 8]
        assert link_targets(model.doc, 2)[662] == 5  # nav page 1's /Fit link followed its page
    finally:
        model.close()


# --- S17-INSERT-NAV: Insert pages from file imports the source outline, names and labels ---


# PyMuPDF reports the prefix of the last page (a UTF-16 hex string) undecoded.
LAST = "<FEFF964493040028>7"


def _insert_rich_source(tmp_path: Path, source_pages: list[int], position: int):
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "rich_src.pdf"
    make_nav_pdf(nav)
    make_rich_src_pdf(src)
    model = PDFModel()
    model.open_pdf(str(nav))
    inserted = model.insert_pages_from_file(str(src), source_pages, position)
    return model, inserted


def test_insert_imports_source_outline_nested_after_the_documents_own(tmp_path: Path) -> None:
    model, inserted = _insert_rich_source(tmp_path, [1, 2, 3, 4], 3)
    try:
        assert inserted == [3, 4, 5, 6]
        assert [(row[0], row[1], row[2]) for row in model.get_toc()] == [
            (1, "Intro", 2),
            (1, "Website", -1),
            (1, "Chapter 4", 8),
            (2, "Section 4.1", 9),
            (1, "Last", 10),
            (1, "Src Part", 3),
            (2, "Src Chapter", 4),
            (3, "Src Section", 5),
            (1, "Src Tail", 6),
        ]
        # the document's own bookmarks keep every attribute (colour, bold, view, collapse)
        reopened = fitz.open("pdf", model.doc.tobytes())
        original = fitz.open(tmp_path / "nav.pdf")
        try:
            attrs = outline_attrs(reopened)
            expected = outline_attrs(original)
        finally:
            reopened.close()
            original.close()
        assert {title: attrs[title] for title in expected} == expected
    finally:
        model.close()


def test_insert_imports_named_destinations_and_renames_a_clash(tmp_path: Path) -> None:
    model, _inserted = _insert_rich_source(tmp_path, [1, 2, 3, 4], 3)
    try:
        # 0-based pages: the document's chap3 (nav page 3) moved to 6, the source's land at 3 and 4
        assert resolved_names(model.doc) == {"chap3": 6, "chap3.2": 3, "srcname": 4}
        leaf = _names_leaf_text(model.doc)
        assert "/XYZ 0 400 null" in leaf and "/XYZ 0 300 null" in leaf  # views copied verbatim
        # the document's own link keeps its name; the source's links follow the (renamed) names
        assert link_targets(model.doc, 0)[600] == "chap3"
        assert link_targets(model.doc, 2) == {600: "chap3.2", 562: "srcname"}
        saved = tmp_path / "saved.pdf"
        model.doc.save(saved)
        reopened = fitz.open(saved)
        try:
            assert {n: i["page"] for n, i in reopened.resolve_names().items()} == {
                "chap3": 6,
                "chap3.2": 3,
                "srcname": 4,
            }
        finally:
            reopened.close()
    finally:
        model.close()


def test_insert_rebuilds_labels_so_every_label_stays_on_its_page(tmp_path: Path) -> None:
    model, _inserted = _insert_rich_source(tmp_path, [1, 2, 3, 4], 3)
    try:
        assert labels(model.doc) == ["i", "ii", "S-1", "S-2", "S-3", "S-4", "1", "2", "3", LAST]
    finally:
        model.close()


def test_insert_at_the_front_and_the_end_rebuilds_labels(tmp_path: Path) -> None:
    for position, expected in (
        (1, ["S-1", "S-2", "i", "ii", "1", "2", "3", LAST]),
        (7, ["i", "ii", "1", "2", "3", LAST, "S-1", "S-2"]),
    ):
        model, _inserted = _insert_rich_source(tmp_path, [1, 2], position)
        try:
            assert labels(model.doc) == expected
        finally:
            model.close()


def test_insert_of_a_label_less_source_still_keeps_the_documents_labels_on_their_pages(tmp_path: Path) -> None:
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "plain.pdf"
    make_nav_pdf(nav)
    make_plain_pdf(src, pages=2)
    model = PDFModel()
    model.open_pdf(str(nav))
    try:
        assert model.insert_pages_from_file(str(src), [1, 2], 2) == [2, 3]
        # NAVPAGE-2 was "ii"; the unlabelled source counts 1, 2 (as in a merge)
        assert labels(model.doc) == ["i", "1", "2", "ii", "1", "2", "3", LAST]
        assert "NAVPAGE-2" in model.doc[3].get_text()
    finally:
        model.close()


def test_insert_into_a_document_without_navigation_adds_only_what_the_source_has(tmp_path: Path) -> None:
    plain = tmp_path / "plain.pdf"
    src = tmp_path / "rich_src.pdf"
    make_plain_pdf(plain, pages=3)
    make_rich_src_pdf(src)
    model = PDFModel()
    model.open_pdf(str(plain))
    try:
        assert model.insert_pages_from_file(str(src), [1, 2, 3, 4], 2) == [2, 3, 4, 5]
        assert [row[1:3] for row in model.get_toc()][:1] == [["Src Part", 2]]
        assert resolved_names(model.doc) == {"chap3": 2, "srcname": 3}
        # the unlabelled document's pages keep the number they showed
        assert labels(model.doc) == ["1", "S-1", "S-2", "S-3", "S-4", "2", "3"]
    finally:
        model.close()

    other = tmp_path / "plain2.pdf"
    make_plain_pdf(other, pages=2, tag="OTHER")
    model = PDFModel()
    model.open_pdf(str(plain))
    try:
        assert model.insert_pages_from_file(str(other), [1, 2], 2) == [2, 3]
        assert model.get_toc() == []
        catalog = model.doc.pdf_catalog()
        assert model.doc.xref_get_key(catalog, "PageLabels")[0] == "null"
        assert model.doc.xref_get_key(catalog, "Names")[0] == "null"
    finally:
        model.close()


def test_insert_of_a_page_range_imports_only_navigation_into_those_pages(tmp_path: Path) -> None:
    model, inserted = _insert_rich_source(tmp_path, [2, 3], 3)
    try:
        assert inserted == [3, 4]
        titles = [row[1] for row in model.get_toc()]
        assert titles[5:] == ["Src Chapter", "Src Section"]  # Part (p1) and Tail (p4) were not copied
        assert resolved_names(model.doc) == {"chap3": 4, "chap3.2": 2, "srcname": 3}
        assert labels(model.doc)[2:4] == ["S-2", "S-3"]
    finally:
        model.close()


def test_insert_keeps_legacy_catalog_dests_and_other_name_trees(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.pdf"
    make_nav_pdf(legacy)
    doc = fitz.open(legacy)
    try:
        # the document's own names live in the legacy catalog /Dests and in a /Kids tree
        catalog = doc.pdf_catalog()
        doc.xref_set_key(catalog, "Dests", f"<</legacy[{doc[4].xref} 0 R/Fit]>>")
        leaf_a, leaf_b, root = doc.get_new_xref(), doc.get_new_xref(), doc.get_new_xref()
        doc.update_object(leaf_a, f"<</Limits[(chap3)(chap3)]/Names[(chap3)[{doc[2].xref} 0 R/XYZ 0 400 null]]>>")
        doc.update_object(leaf_b, f"<</Limits[(zeta)(zeta)]/Names[(zeta)[{doc[5].xref} 0 R/Fit]]>>")
        doc.update_object(root, f"<</Kids[{leaf_a} 0 R {leaf_b} 0 R]>>")
        doc.xref_set_key(catalog, "Names", f"<</Dests {root} 0 R/EmbeddedFiles <</Names[]>>>>")
        doc.saveIncr()
    finally:
        doc.close()
    clash_path = tmp_path / "clash_src.pdf"
    clash = fitz.open()
    clash.new_page()
    clash.new_page()
    names = clash.get_new_xref()
    clash.update_object(names, f"<</Names[(legacy)[{clash[1].xref} 0 R/Fit](zeta)[{clash[0].xref} 0 R/Fit]]>>")
    clash.xref_set_key(clash.pdf_catalog(), "Names", f"<</Dests {names} 0 R>>")
    clash.save(clash_path)
    clash.close()
    model = PDFModel()
    model.open_pdf(str(legacy))
    try:
        assert model.insert_pages_from_file(str(clash_path), [1, 2], 2) == [2, 3]
        assert resolved_names(model.doc) == {
            "chap3": 4,
            "legacy": 6,  # legacy catalog /Dests entry of nav page 5
            "zeta": 7,
            "legacy.2": 2,  # the source's clashing names are renamed, the document's win
            "zeta.2": 1,
        }
        assert model.doc.xref_get_key(model.doc.pdf_catalog(), "Names/EmbeddedFiles")[0] != "null"
    finally:
        model.close()


def test_insert_leaves_an_unreadable_name_tree_alone_and_links_explicitly(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    src = tmp_path / "rich_src.pdf"
    make_nav_pdf(broken)
    make_rich_src_pdf(src)
    doc = fitz.open(broken)
    try:
        # the document's name tree points at a missing kid: re-writing it would lose names
        root = doc.get_new_xref()
        doc.update_object(root, "<</Kids[9999 0 R]>>")
        doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</Dests {root} 0 R>>")
        doc.saveIncr()
    finally:
        doc.close()
    model = PDFModel()
    model.open_pdf(str(broken))
    try:
        leaf_before = model.doc.xref_object(root, compressed=True)
        assert model.insert_pages_from_file(str(src), [1, 2, 3, 4], 3) == [3, 4, 5, 6]
        assert model.doc.xref_object(root, compressed=True) == leaf_before  # untouched
        # the source's named links became explicit ones; its outline and labels still came across
        assert link_targets(model.doc, 2) == {600: 3, 562: 4}
        assert "Src Part" in [row[1] for row in model.get_toc()]
        assert labels(model.doc)[2:6] == ["S-1", "S-2", "S-3", "S-4"]
    finally:
        model.close()


def test_insert_into_a_blank_placeholder_replaces_stale_labels_with_the_sources(tmp_path: Path) -> None:
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "rich_src.pdf"
    make_nav_pdf(nav)
    make_rich_src_pdf(src)
    model = PDFModel()
    model.open_pdf(str(nav))
    try:
        model.delete_pages([1, 2, 3, 4, 5, 6])
        assert model.blank_placeholder_active is True
        assert model.insert_pages_from_file(str(src), [1, 2, 3, 4], 1) == [1, 2, 3, 4]
        assert model.blank_placeholder_active is False
        assert labels(model.doc) == ["S-1", "S-2", "S-3", "S-4"]
        assert resolved_names(model.doc)["srcname"] == 2
        assert "Src Part" in [row[1] for row in model.get_toc()]
    finally:
        model.close()


def test_undo_of_an_insert_restores_outline_names_and_labels_exactly(tmp_path: Path) -> None:
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "rich_src.pdf"
    make_nav_pdf(nav)
    make_rich_src_pdf(src)
    model = PDFModel()
    model.open_pdf(str(nav))
    try:
        toc_before = model.get_toc()
        labels_before = labels(model.doc)
        names_before = resolved_names(model.doc)
        leaf_before = _names_leaf_text(model.doc)
        before = model._capture_doc_snapshot()
        inserted = model.insert_pages_from_file(str(src), [1, 2, 3, 4], 3)
        after = model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=model,
            command_type="insert_pages_from_file",
            affected_pages=inserted,
            before_bytes=before,
            after_bytes=after,
            description="insert",
        )
        model.command_manager.record(cmd)
        assert labels(model.doc) != labels_before

        model.command_manager.undo()
        assert len(model.doc) == 6
        assert model.get_toc() == toc_before
        assert labels(model.doc) == labels_before
        assert resolved_names(model.doc) == names_before
        assert _names_leaf_text(model.doc) == leaf_before

        model.command_manager.redo()
        assert len(model.doc) == 10
        assert labels(model.doc)[2:6] == ["S-1", "S-2", "S-3", "S-4"]
        assert resolved_names(model.doc)["srcname"] == 4
        assert "Src Part" in [row[1] for row in model.get_toc()]
    finally:
        model.close()


# --- F17-COH-4: a PDF written from the session carries its pending watermark ----
# View, image export, print and Save all drew the watermark, but "export pages as
# PDF" and "merge into a new file" built their output from the unbaked live
# document and silently left it out.  Every PDF the app derives from the session's
# pages now runs through the same bake as Save (``WatermarkTool.prepare_derived_document``),
# on the watermark list as it reads for the OUTPUT's page numbers.

_EMBED = "__pdf_editor_watermarks"
_STAMP = "STAMPED"


@pytest.fixture()
def model_with_stamp(tmp_path: Path):
    """Three pages (ONE, TWO, THREE) and a watermark on page 2 only."""
    current = _make_pdf(tmp_path / "Stamped.pdf", ["ONE", "TWO", "THREE"])
    model = PDFModel()
    model.open_pdf(str(current))
    model.tools.watermark.add_watermark([2], _STAMP)
    try:
        yield model
    finally:
        model.close()


def _stamped_pages(doc: fitz.Document) -> list[int]:
    """1-based pages whose text carries the watermark text (exactly once)."""
    counts = [doc[i].get_text("text").count(_STAMP) for i in range(len(doc))]
    assert all(count <= 1 for count in counts), counts
    return [i + 1 for i, count in enumerate(counts) if count]


def _embedded_pages(doc: fitz.Document) -> list[list[int]]:
    import json

    if _EMBED not in doc.embfile_names():
        return []
    return [wm["pages"] for wm in json.loads(doc.embfile_get(_EMBED).decode("utf-8"))]


def _ink_difference(view: fitz.Pixmap, page: fitz.Page) -> int:
    import numpy as np

    disk = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), annots=True)
    assert (view.width, view.height, view.n) == (disk.width, disk.height, disk.n)
    a = np.frombuffer(view.samples, dtype=np.uint8).reshape(view.height, view.width, view.n)
    b = np.frombuffer(disk.samples, dtype=np.uint8).reshape(disk.height, disk.width, disk.n)
    return int(np.count_nonzero(np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 8))


def test_export_pages_as_pdf_bakes_the_pending_watermark_on_the_exported_page(model_with_stamp, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    model_with_stamp.export_pages([2], str(out), as_image=False)

    with fitz.open(str(out)) as exported:
        assert _stamped_pages(exported) == [1]
        assert _page_texts(exported)[0].startswith("TWO")
        assert _embedded_pages(exported) == [[1]]  # the list for the OUTPUT's numbering
        # What the viewer shows for the page is what the exported file draws.
        assert _ink_difference(model_with_stamp.get_page_pixmap(2, 0.5), exported[0]) == 0


def test_export_pages_as_pdf_remaps_the_watermark_to_the_exported_order(model_with_stamp, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    model_with_stamp.export_pages([3, 2, 1, 2], str(out), as_image=False)  # THREE, TWO, ONE, TWO

    with fitz.open(str(out)) as exported:
        assert _page_texts(exported)[0].startswith("THREE") and _page_texts(exported)[2].startswith("ONE")
        assert _stamped_pages(exported) == [2, 4]
        assert _embedded_pages(exported) == [[2, 4]]


def test_export_pages_as_pdf_without_the_watermarked_page_adds_nothing(model_with_stamp, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    model_with_stamp.export_pages([1, 3], str(out), as_image=False)

    with fitz.open(str(out)) as exported:
        assert _stamped_pages(exported) == []
        assert _embedded_pages(exported) == []
        assert exported.embfile_names() == []


def test_export_pages_as_pdf_without_any_watermark_adds_no_attachment(tmp_path: Path) -> None:
    current = _make_pdf(tmp_path / "Plain.pdf", ["ONE", "TWO"])
    model = PDFModel()
    try:
        model.open_pdf(str(current))
        out = tmp_path / "out.pdf"
        model.export_pages([1, 2], str(out), as_image=False)
        with fitz.open(str(out)) as exported:
            assert exported.embfile_names() == []
    finally:
        model.close()


def test_export_pages_does_not_change_the_live_document(model_with_stamp, tmp_path: Path) -> None:
    before = [model_with_stamp.doc[i].get_text("text") for i in range(3)]
    stream_count = [len(model_with_stamp.doc[i].get_contents()) for i in range(3)]
    model_with_stamp.export_pages([1, 2, 3], str(tmp_path / "out.pdf"), as_image=False)
    assert [model_with_stamp.doc[i].get_text("text") for i in range(3)] == before
    assert [len(model_with_stamp.doc[i].get_contents()) for i in range(3)] == stream_count
    assert _EMBED not in model_with_stamp.doc.embfile_names()


def test_compose_bakes_the_pending_watermark_of_the_current_document(model_with_stamp, tmp_path: Path) -> None:
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRAPAGE"])
    merged = model_with_stamp.compose_merged_document(
        [{"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}]
    )
    try:
        assert _page_texts(merged)[0] == "EXTRAPAGE"
        assert _stamped_pages(merged) == [3]  # TWO is page 3 of the merged document
        assert _embedded_pages(merged) == [[3]]
    finally:
        merged.close()


def test_compose_with_the_current_document_twice_stamps_both_copies(model_with_stamp) -> None:
    merged = model_with_stamp.compose_merged_document([{"source_kind": "current"}, {"source_kind": "current"}])
    try:
        assert _stamped_pages(merged) == [2, 5]
        assert _embedded_pages(merged) == [[2, 5]]
    finally:
        merged.close()


def test_compose_without_the_current_document_carries_no_watermark(model_with_stamp, tmp_path: Path) -> None:
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRAPAGE"])
    merged = model_with_stamp.compose_merged_document([{"source_kind": "file", "path": str(extra)}])
    try:
        assert _stamped_pages(merged) == []
        assert merged.embfile_names() == []
    finally:
        merged.close()


def test_compose_for_the_live_document_does_not_bake(model_with_stamp) -> None:
    """Merge-into-current swaps the result in as the live document, which stays unbaked:
    the watermark list follows its pages instead (baking here would draw it twice)."""
    merged, origins = model_with_stamp.compose_merged_document_with_origins(
        [{"source_kind": "current"}], bake_watermarks=False
    )
    try:
        assert origins == [1, 2, 3]
        assert _stamped_pages(merged) == []
        assert merged.embfile_names() == []
    finally:
        merged.close()


def test_compose_reports_which_source_page_each_output_page_came_from(model_with_stamp, tmp_path: Path) -> None:
    extra = _make_pdf(tmp_path / "Extra.pdf", ["E1", "E2"])
    merged, origins = model_with_stamp.compose_merged_document_with_origins(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}],
        bake_watermarks=False,
    )
    try:
        assert origins == [1, 2, 3, None, None, 1, 2, 3]
        assert len(merged) == len(origins)
    finally:
        merged.close()


def test_compose_bakes_into_an_encrypted_kept_container(tmp_path: Path) -> None:
    plain = _make_pdf(tmp_path / "Plain.pdf", ["ONE", "TWO"])
    secret = tmp_path / "Secret.pdf"
    with fitz.open(str(plain)) as source:
        source.save(
            str(secret),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
    model = PDFModel()
    try:
        model.open_pdf(str(secret), password="user")
        model.tools.watermark.add_watermark([2], _STAMP)
        for keep in (False, True):
            merged = model.compose_merged_document([{"source_kind": "current"}], keep_encryption=keep)
            try:
                if merged.needs_pass:
                    assert merged.authenticate("user")
                assert _stamped_pages(merged) == [2], f"keep_encryption={keep}"
            finally:
                merged.close()
    finally:
        model.close()


def test_every_caller_of_save_external_document_runs_the_session_bake() -> None:
    """Bug-class guard (F17-COH-4): a function that writes a PDF built from the session's
    pages through ``save_external_document`` must derive it with the watermark bake --
    ``compose_merged_document`` (bakes unless told not to) or ``prepare_derived_document``.
    A new export path that skips it would drop the pending watermark like these two did."""
    import ast

    root = Path(__file__).resolve().parents[1]
    baked_by: dict[str, bool] = {}
    for relative in ("model/pdf_model.py", "controller/pdf_controller.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8-sig"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
            names = {
                n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "") for n in calls
            }
            if "save_external_document" not in names:
                continue
            no_bake_flag = any(
                kw.arg == "bake_watermarks" and isinstance(kw.value, ast.Constant) and kw.value.value is False
                for n in calls
                for kw in n.keywords
            )
            baked_by[f"{relative}::{func.name}"] = (
                bool(names & {"prepare_derived_document", "_prepare_derived_document", "compose_merged_document"})
                and not no_bake_flag
            )
    found = sorted(baked_by)
    assert found == [
        "controller/pdf_controller.py::save_ordered_sources_as_new",
        "model/pdf_model.py::export_pages",
    ], f"scan found {found}: update the guard if a writer was added or renamed"
    skipped = sorted(key for key, baked in baked_by.items() if not baked)
    assert skipped == [], f"{skipped} write a PDF from the session without the watermark bake"
