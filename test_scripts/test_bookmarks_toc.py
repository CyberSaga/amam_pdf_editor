from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

from controller.pdf_controller import PDFController
from model.edit_commands import SnapshotCommand
from model.pdf_model import PDFModel
from test_scripts.navigation_fixtures import link_targets, outline_attrs
from view.pdf_view import PDFView


def _make_pdf(path: Path, pages: int = 5) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((30, 50), f"PAGE-{index + 1}")
    doc.save(path)
    doc.close()


def test_toc_set_get_round_trip_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "toc.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        entries = [[1, "One", 1], [2, "Child", 2], [1, "Three", 3]]
        assert model.set_toc(entries) is True
        assert model.get_toc() == entries
        assert model.set_toc(entries) is False

        for invalid in (
            [[2, "bad", 1]],
            [[1, "", 1]],
            [[1, "bad page", 0]],
            [[1, "bad page", 6]],
            [[1, "root", 1], [3, "jump", 2]],
        ):
            with pytest.raises((TypeError, ValueError)):
                model.set_toc(invalid)
        assert model.get_toc() == entries
    finally:
        model.close()


def test_insert_blank_page_shifts_bookmarks_with_original_content(tmp_path: Path) -> None:
    path = tmp_path / "insert.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, "P1", 1], [1, "P2", 2], [1, "P5", 5]])
        model.insert_blank_page(2)
        assert model.get_toc() == [[1, "P1", 1], [1, "P2", 3], [1, "P5", 6]]
    finally:
        model.close()


def test_delete_pages_remaps_deleted_targets_to_nearest_survivor(tmp_path: Path) -> None:
    path = tmp_path / "delete.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, f"P{i}", i] for i in range(1, 6)])
        model.delete_pages([2, 4])
        assert model.get_toc() == [
            [1, "P1", 1],
            [1, "P2", 2],
            [1, "P3", 2],
            [1, "P4", 3],
            [1, "P5", 3],
        ]
    finally:
        model.close()


def test_move_page_remaps_bookmarks_by_final_index(tmp_path: Path) -> None:
    path = tmp_path / "move.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, f"P{i}", i] for i in range(1, 6)])
        model.move_page(0, 2)
        assert model.get_toc() == [
            [1, "P1", 3],
            [1, "P2", 1],
            [1, "P3", 2],
            [1, "P4", 4],
            [1, "P5", 5],
        ]
    finally:
        model.close()


def test_delete_all_placeholder_clamps_every_bookmark_to_page_one(tmp_path: Path) -> None:
    path = tmp_path / "all.pdf"
    _make_pdf(path, pages=3)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.set_toc([[1, "A", 1], [1, "B", 3]])
        model.delete_pages([1, 2, 3])
        assert model.blank_placeholder_active is True
        assert model.get_toc() == [[1, "A", 1], [1, "B", 1]]
    finally:
        model.close()


def test_view_toc_tree_preserves_nesting_and_emits_navigation(qapp) -> None:
    view = PDFView()
    activated: list[int] = []
    view.sig_bookmark_activated.connect(activated.append)
    try:
        view.populate_toc([[1, "Root", 1], [2, "Child", 3], [1, "Other", 5]])
        assert view.bookmark_tree.topLevelItemCount() == 2
        root = view.bookmark_tree.topLevelItem(0)
        assert root.text(0) == "Root"
        assert root.childCount() == 1
        child = root.child(0)
        assert child.text(0) == "Child"
        view._on_bookmark_activated(child, 0)
        assert activated == [2]
    finally:
        view.close()
        qapp.processEvents()


def test_controller_toc_update_records_snapshot() -> None:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = MagicMock()
    controller.model.doc.__len__ = lambda _self=None: 5
    controller.model._capture_doc_snapshot.side_effect = [b"before", b"after"]
    controller.model.set_toc.return_value = True
    controller.model.command_manager = MagicMock()
    controller.view = MagicMock(current_page=0)
    controller._worker_snapshot_cache = None
    controller.load_toc = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()

    controller.update_toc([[1, "Root", 1]])

    command = controller.model.command_manager.record.call_args.args[0]
    assert isinstance(command, SnapshotCommand)
    assert command._command_type == "update_toc"
    controller.load_toc.assert_called_once_with()


def test_reset_empty_ui_clears_bookmark_panel() -> None:
    """Closing the last tab must clear the bookmark tree, like annotations/watermarks."""
    controller = PDFController.__new__(PDFController)
    controller.view = MagicMock()

    controller._reset_empty_ui()

    controller.view.populate_toc.assert_called_once_with([])


def test_move_bookmark_up_preserves_selection_after_rebuild(qapp) -> None:
    view = PDFView()
    view.sig_toc_changed.connect(view.populate_toc)
    try:
        view.populate_toc([[1, "A", 1], [1, "B", 2], [1, "C", 3]])
        view.bookmark_tree.setCurrentItem(view.bookmark_tree.topLevelItem(1))

        view._move_selected_bookmark(-1)

        current = view.bookmark_tree.currentItem()
        assert current is not None
        assert current.text(0) == "B"
        assert view.bookmark_tree.indexOfTopLevelItem(current) == 0
    finally:
        view.close()
        qapp.processEvents()


def test_move_bookmark_down_preserves_selection_after_rebuild(qapp) -> None:
    view = PDFView()
    view.sig_toc_changed.connect(view.populate_toc)
    try:
        view.populate_toc([[1, "A", 1], [1, "B", 2], [1, "C", 3]])
        view.bookmark_tree.setCurrentItem(view.bookmark_tree.topLevelItem(0))

        view._move_selected_bookmark(1)

        current = view.bookmark_tree.currentItem()
        assert current is not None
        assert current.text(0) == "A"
        assert view.bookmark_tree.indexOfTopLevelItem(current) == 1
    finally:
        view.close()
        qapp.processEvents()


def test_move_child_bookmark_preserves_selection_after_rebuild(qapp) -> None:
    view = PDFView()
    view.sig_toc_changed.connect(view.populate_toc)
    try:
        view.populate_toc([[1, "Root", 1], [2, "C1", 2], [2, "C2", 3]])
        root = view.bookmark_tree.topLevelItem(0)
        view.bookmark_tree.setCurrentItem(root.child(1))

        view._move_selected_bookmark(-1)

        current = view.bookmark_tree.currentItem()
        assert current is not None
        assert current.text(0) == "C2"
        parent = current.parent()
        assert parent is not None
        assert parent.indexOfChild(current) == 0
    finally:
        view.close()
        qapp.processEvents()


def test_move_bookmark_boundary_noop_leaves_selection_intact(qapp) -> None:
    """Moving the first sibling up is a no-op and must not clear the selection."""
    view = PDFView()
    emitted: list[object] = []
    view.sig_toc_changed.connect(emitted.append)
    try:
        view.populate_toc([[1, "A", 1], [1, "B", 2]])
        first = view.bookmark_tree.topLevelItem(0)
        view.bookmark_tree.setCurrentItem(first)

        view._move_selected_bookmark(-1)

        assert emitted == []
        assert view.bookmark_tree.currentItem() is first
    finally:
        view.close()
        qapp.processEvents()


# --- F16-NAV-1: the outline is edited in place, never regenerated in simple form ---


def _make_nav_pdf(path: Path) -> None:
    """Outline with a positioned target, colour, bold, collapse state and a URI item."""
    doc = fitz.open()
    for index in range(6):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"PAGE-{index + 1}", fontsize=20)
    doc.set_toc(
        [
            [
                1,
                "Intro",
                2,
                {
                    "kind": fitz.LINK_GOTO,
                    "page": 1,
                    "to": fitz.Point(0, 500),
                    "color": (1, 0, 0),
                    "bold": True,
                },
            ],
            [1, "Website", -1, {"kind": fitz.LINK_URI, "uri": "https://example.com/"}],
            [1, "Chapter 4", 4, {"kind": fitz.LINK_GOTO, "page": 3, "to": fitz.Point(0, 300)}],
            [2, "Section 4.1", 5],
            [1, "Last", 6],
        ]
    )
    doc.save(path)
    doc.close()


def _make_src_pdf(path: Path) -> None:
    doc = fitz.open()
    for index in range(3):
        doc.new_page(width=595, height=842).insert_text((72, 100), f"SRC-{index + 1}")
    doc.save(path)
    doc.close()


def _outline_objects(doc: fitz.Document) -> dict[str, str]:
    titles = [row[1] for row in doc.get_toc()]
    return {
        title: doc.xref_object(xref, compressed=True)
        for title, xref in zip(titles, doc.get_outline_xrefs())
    }


def _reopened_attrs(model: PDFModel, path: Path) -> dict[str, tuple]:
    model.save_as(str(path))
    reopened = fitz.open(path)
    try:
        return outline_attrs(reopened)
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "operation",
    ["insert_front", "insert_end", "move", "insert_file", "delete_unbookmarked"],
)
def test_structural_ops_keep_every_outline_attribute(tmp_path: Path, operation: str) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    src = tmp_path / "src.pdf"
    _make_src_pdf(src)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        attrs_before = outline_attrs(model.doc)
        objects_before = _outline_objects(model.doc)
        assert attrs_before["Website"][0] == fitz.LINK_URI
        assert attrs_before["Intro"][1] == (0.0, 500.0)

        if operation == "insert_front":
            model.insert_blank_page(1)
            expected_pages = [3, -1, 5, 6, 7]
        elif operation == "insert_end":
            model.insert_blank_page(7)
            expected_pages = [2, -1, 4, 5, 6]
        elif operation == "move":
            model.move_page(5, 0)
            expected_pages = [3, -1, 5, 6, 1]
        elif operation == "insert_file":
            model.insert_pages_from_file(str(src), [1, 2], 1)
            expected_pages = [4, -1, 6, 7, 8]
        else:
            model.delete_pages([1])
            expected_pages = [1, -1, 3, 4, 5]

        assert [row[2] for row in model.get_toc()] == expected_pages
        assert outline_attrs(model.doc) == attrs_before
        # Outline items reference page objects, so no item needs rewriting at all.
        assert _outline_objects(model.doc) == objects_before
        assert _reopened_attrs(model, tmp_path / "saved.pdf") == attrs_before
    finally:
        model.close()


def test_deleting_a_bookmarked_page_retargets_only_that_item(tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        attrs_before = outline_attrs(model.doc)
        objects_before = _outline_objects(model.doc)

        model.delete_pages([2])

        assert [row[2] for row in model.get_toc()] == [2, -1, 3, 4, 5]
        attrs_after = outline_attrs(model.doc)
        intro_xref = model.get_toc_rows()[0][3]
        # Retargeted to the survivor page as a whole-page view (valid on any geometry).
        assert model.doc.xref_get_key(intro_xref, "A/D")[1].endswith("0 R/Fit]")
        # Style survives the retarget (PyMuPDF greys a deleted target to 0.8).
        assert attrs_after["Intro"][4] == (1.0, 0.0, 0.0)
        assert attrs_after["Intro"][5] is True
        objects_after = _outline_objects(model.doc)
        for title in ("Website", "Chapter 4", "Section 4.1", "Last"):
            assert objects_after[title] == objects_before[title]
            assert attrs_after[title] == attrs_before[title]
        reopened = _reopened_attrs(model, tmp_path / "saved.pdf")
        assert reopened["Website"] == attrs_before["Website"]
        assert reopened["Chapter 4"] == attrs_before["Chapter 4"]
        assert reopened["Intro"][4:6] == ((1.0, 0.0, 0.0), True)
    finally:
        model.close()


def test_delete_all_and_placeholder_import_keep_outline_style(tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    src = tmp_path / "src.pdf"
    _make_src_pdf(src)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        attrs_before = outline_attrs(model.doc)

        model.delete_pages([1, 2, 3, 4, 5, 6])
        assert model.blank_placeholder_active is True
        assert [row[2] for row in model.get_toc()] == [1, -1, 1, 1, 1]
        attrs = outline_attrs(model.doc)
        assert attrs["Website"] == attrs_before["Website"]
        assert attrs["Intro"][4:6] == ((1.0, 0.0, 0.0), True)
        assert attrs["Chapter 4"][7] == attrs_before["Chapter 4"][7]
        assert attrs["Last"][4] is None

        model.insert_pages_from_file(str(src), [1, 2], 1)
        assert model.blank_placeholder_active is False
        assert [row[2] for row in model.get_toc()] == [1, -1, 1, 1, 1]
        attrs = outline_attrs(model.doc)
        assert attrs["Website"] == attrs_before["Website"]
        assert attrs["Intro"][4:6] == ((1.0, 0.0, 0.0), True)
        assert attrs["Last"][4] is None
    finally:
        model.close()


def test_panel_rename_keeps_uri_and_other_bookmarks_untouched(tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        attrs_before = outline_attrs(model.doc)
        objects_before = _outline_objects(model.doc)
        rows = model.get_toc_rows()
        assert [row[:3] for row in rows] == model.get_toc()
        assert rows[1][2] == -1

        rows[0][1] = "Renamed"
        assert model.set_toc(rows) is True

        assert [row[1] for row in model.get_toc()] == [
            "Renamed",
            "Website",
            "Chapter 4",
            "Section 4.1",
            "Last",
        ]
        attrs_after = outline_attrs(model.doc)
        assert attrs_after["Renamed"] == attrs_before["Intro"]
        objects_after = _outline_objects(model.doc)
        for title in ("Website", "Chapter 4", "Section 4.1", "Last"):
            assert objects_after[title] == objects_before[title]
        assert model.set_toc(model.get_toc_rows()) is False
        reopened = _reopened_attrs(model, tmp_path / "saved.pdf")
        assert reopened["Renamed"] == attrs_before["Intro"]
        assert reopened["Website"] == attrs_before["Website"]
    finally:
        model.close()


def test_panel_reorder_delete_add_and_repage_keep_attributes(tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        attrs_before = outline_attrs(model.doc)
        intro, website, chapter, section, _last = model.get_toc_rows()

        chapter_moved = [chapter[0], chapter[1], 2, chapter[3]]
        rows = [website, chapter_moved, section, intro, [1, "New", 3]]
        assert model.set_toc(rows) is True

        assert model.get_toc() == [
            [1, "Website", -1],
            [1, "Chapter 4", 2],
            [2, "Section 4.1", 5],
            [1, "Intro", 2],
            [1, "New", 3],
        ]
        attrs = outline_attrs(model.doc)
        assert attrs["Website"] == attrs_before["Website"]
        assert attrs["Intro"] == attrs_before["Intro"]
        assert attrs["Section 4.1"] == attrs_before["Section 4.1"]
        assert attrs["Chapter 4"][7] == attrs_before["Chapter 4"][7]
        assert attrs["Chapter 4"][4:7] == attrs_before["Chapter 4"][4:7]
        assert "Last" not in attrs

        # Giving a URI bookmark a page makes it a page bookmark, by explicit request.
        rows = model.get_toc_rows()
        rows[0][2] = 3
        assert model.set_toc(rows) is True
        assert model.get_toc()[0] == [1, "Website", 3]
        assert outline_attrs(model.doc)["Website"][0] != fitz.LINK_URI

        reopened_path = tmp_path / "saved.pdf"
        model.save_as(str(reopened_path))
        reopened = fitz.open(reopened_path)
        try:
            assert reopened.get_toc() == model.get_toc()
        finally:
            reopened.close()
    finally:
        model.close()


def test_set_toc_rejects_a_keyless_row_without_a_page(tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        before = model.get_toc()
        with pytest.raises(ValueError):
            model.set_toc([[1, "Website", -1]])
        with pytest.raises(ValueError):
            model.set_toc([[1, "Bad key", -1, 999999]])
        assert model.get_toc() == before
    finally:
        model.close()


def test_view_round_trips_outline_keys_and_rename_reaches_the_model(qapp, tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    model = PDFModel()
    view = PDFView()
    activated: list[int] = []
    view.sig_bookmark_activated.connect(activated.append)
    view.sig_toc_changed.connect(model.set_toc)
    try:
        model.open_pdf(str(path))
        attrs_before = outline_attrs(model.doc)
        rows = model.get_toc_rows()
        view.populate_toc(rows)
        assert view._toc_entries_from_tree() == rows

        website = view.bookmark_tree.topLevelItem(1)
        view._on_bookmark_activated(website, 0)
        assert activated == []

        # The GUI rename path: editing the title column emits sig_toc_changed.
        view.bookmark_tree.topLevelItem(0).setText(0, "Renamed")
        assert [row[1] for row in model.get_toc()][:2] == ["Renamed", "Website"]
        attrs = outline_attrs(model.doc)
        assert attrs["Website"] == attrs_before["Website"]
        assert attrs["Renamed"] == attrs_before["Intro"]
    finally:
        view.close()
        qapp.processEvents()
        model.close()


def test_controller_load_toc_passes_keyed_rows_to_the_view() -> None:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.get_toc_rows.return_value = [[1, "A", 1, 7]]
    controller.view = MagicMock()

    controller.load_toc()

    controller.view.populate_toc.assert_called_once_with([[1, "A", 1, 7]])


def test_set_toc_of_simple_rows_is_a_no_op_on_an_outline_with_a_uri(tmp_path: Path) -> None:
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        objects_before = _outline_objects(model.doc)
        assert model.set_toc(model.get_toc()) is False
        assert _outline_objects(model.doc) == objects_before
    finally:
        model.close()


def test_straighten_page_keeps_the_bookmarks_into_the_replaced_page(tmp_path: Path) -> None:
    """Straighten replaces the page object; its bookmarks must move to the new one."""
    path = tmp_path / "nav.pdf"
    _make_nav_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        attrs_before = outline_attrs(model.doc)
        objects_before = _outline_objects(model.doc)
        pages_before = model.get_toc()

        assert model.straighten_page(2, angle_degrees=4.0) is True

        assert model.get_toc() == pages_before
        assert outline_attrs(model.doc) == attrs_before
        objects_after = _outline_objects(model.doc)
        for title in ("Website", "Chapter 4", "Section 4.1", "Last"):
            assert objects_after[title] == objects_before[title]
        assert _reopened_attrs(model, tmp_path / "saved.pdf") == attrs_before
    finally:
        model.close()


# --- F16-NAV-3: outline_ops.append_items writes bookmarks carried over from another document ---


def _blank(pages: int) -> fitz.Document:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=595, height=842)
    return doc


def test_append_items_builds_a_tree_with_style_collapse_and_uri() -> None:
    from model import outline_ops

    doc = _blank(4)
    try:
        items = [
            outline_ops.ImportedItem(1, "One", doc.page_xref(1), "/XYZ 0 342 null", None, "[1 0 0]", "2", False),
            outline_ops.ImportedItem(1, "Web", None, "", "(https://example.com/)", None, None, False),
            outline_ops.ImportedItem(1, "Closed", doc.page_xref(3), "/Fit", None, None, None, True),
            outline_ops.ImportedItem(2, "Child", doc.page_xref(2), "", None, None, None, False),
            outline_ops.ImportedItem(5, "Deep", doc.page_xref(0), "", None, None, None, False),
        ]
        assert outline_ops.append_items(doc, items) == 5

        rows = doc.get_toc(simple=False)
        # a level that skips (5 after 2) is clamped to one below the previous item
        assert [(row[0], row[1], row[2]) for row in rows] == [
            (1, "One", 2),
            (1, "Web", -1),
            (1, "Closed", 4),
            (2, "Child", 3),
            (3, "Deep", 1),
        ]
        one = rows[0][3]
        assert (one["to"].x, one["to"].y) == (0.0, 500.0) and one["bold"] is True and one["color"] == (1.0, 0.0, 0.0)
        assert rows[1][3]["kind"] == fitz.LINK_URI and rows[1][3]["uri"] == "https://example.com/"
        assert rows[2][3]["collapse"] is True
        assert doc.xref_get_key(doc.get_outline_xrefs()[2], "Count") == ("int", "-2")
    finally:
        doc.close()


def test_append_items_appends_after_the_existing_outline() -> None:
    from model import outline_ops

    doc = _blank(3)
    try:
        doc.set_toc([[1, "Old", 1], [2, "Old child", 2]])
        old_objects = {xref: doc.xref_object(xref, compressed=True) for xref in doc.get_outline_xrefs()}
        outline_ops.append_items(
            doc, [outline_ops.ImportedItem(1, "New", doc.page_xref(2), "/Fit", None, None, None, False)]
        )
        assert [(row[0], row[1], row[2]) for row in doc.get_toc()] == [
            (1, "Old", 1),
            (2, "Old child", 2),
            (1, "New", 3),
        ]
        # the existing items keep their own keys; only tree pointers were touched
        for xref, text in old_objects.items():
            assert "/Title" in doc.xref_object(xref, compressed=True) and "/Title" in text
        assert outline_ops.append_items(doc, []) == 0
    finally:
        doc.close()


# --- F16-NAV-1a: names, named links and /OpenAction follow a deleted or replaced page ---


def _make_dest_pdf(path: Path, tree: str = "flat") -> None:
    """Four pages; chap2 -> 2, chap3 -> 3, chap4 -> 4 (``<</D>>`` form), a legacy /Dests.

    Page 1 carries one link per destination encoding.  ``tree`` is ``flat`` (one
    leaf) or ``kids`` (a root with three kids, the last one holding only a name
    of page 3, so deleting page 3 empties it).
    """
    doc = fitz.open()
    for index in range(4):
        doc.new_page(width=595, height=842).insert_text((72, 100), f"PAGE-{index + 1}")
    px = [doc.page_xref(i) for i in range(4)]
    catalog = doc.pdf_catalog()

    def obj(text: str) -> int:
        xref = doc.get_new_xref()
        doc.update_object(xref, text)
        return xref

    c2 = f"(chap2)[{px[1]} 0 R/XYZ 0 400 null]"
    c3 = f"(chap3)[{px[2]} 0 R/XYZ 0 400 null]"
    c4 = f"(chap4)<</D[{px[3]} 0 R/Fit]>>"
    if tree == "flat":
        root = obj(f"<</Names[{c2}{c3}{c4}(chapx)[{px[2]} 0 R/Fit](zzz)[{px[3]} 0 R/Fit]]>>")
    else:
        kid_a = obj(f"<</Limits[(chap2)(chap3)]/Names[{c2}{c3}]>>")
        kid_b = obj(f"<</Limits[(chap4)(zzz)]/Names[{c4}(zzz)[{px[3]} 0 R/Fit]]>>")
        kid_c = obj(f"<</Limits[(chapx)(chapx)]/Names[(chapx)[{px[2]} 0 R/Fit]]>>")
        root = obj(f"<</Kids[{kid_a} 0 R {kid_b} 0 R {kid_c} 0 R]>>")
    doc.xref_set_key(catalog, "Names", f"<</Dests {root} 0 R>>")
    legacy = obj(f"<</old3[{px[2]} 0 R/Fit]/my#20two[{px[1]} 0 R/Fit]>>")
    doc.xref_set_key(catalog, "Dests", f"{legacy} 0 R")
    doc.xref_set_key(catalog, "OpenAction", f"[{px[2]} 0 R/Fit]")

    rects = iter(range(10, 400, 30))

    def link(action: str) -> str:
        top = next(rects)
        return f"<</Type/Annot/Subtype/Link/Rect[10 {top} 50 {top + 20}]/Border[0 0 0]{action}>>"

    links = [
        link("/A<</S/GoTo/D(chap3)>>"),  # dead name via /A
        link("/Dest(chap3)"),  # dead name via /Dest
        link(f"/A<</S/GoTo/D[{px[2]} 0 R/Fit]>>"),  # explicit, dead
        link("/A<</S/GoTo/D(chap2)>>"),  # live name
        link(f"/A<</S/GoTo/D[{px[1]} 0 R/Fit]>>"),  # explicit, live
        link("/A<</S/GoTo/D(old3)>>"),  # dead legacy name
        link("/A<</S/URI/URI(http://example.org/)>>"),  # URI
        link("/A<</S/GoTo/D(chap4)>>"),  # live name, <</D>> value
        link("/A<</S/GoTo/D/my#20two>>"),  # live legacy name written as a name object
        link("/A<</S/GoTo/D(chapx)>>"),  # dead name (alone in the emptied kid)
    ]
    refs = [f"{obj(text)} 0 R" for text in links]
    doc.xref_set_key(px[0], "Annots", "[" + " ".join(refs) + "]")
    doc.save(path)
    doc.close()


def _names_of(doc: fitz.Document) -> dict[bytes, str]:
    from model.navigation_graft import _read_name_entries

    read = _read_name_entries(doc)
    assert read is not None
    return read[0]


def _page_objects(doc: fitz.Document) -> int:
    return sum(1 for xref in range(1, doc.xref_length()) if doc.xref_get_key(xref, "Type") == ("name", "/Page"))


# Top edge (y0 of the link rect as PyMuPDF reports it) of link k of ``_make_dest_pdf``.
def _top(k: int) -> int:
    return 812 - 30 * k


@pytest.mark.parametrize("tree", ["flat", "kids"])
def test_deleting_a_page_drops_its_names_the_links_using_them_and_the_open_action(
    tmp_path: Path, tree: str
) -> None:
    src = tmp_path / "dests.pdf"
    out = tmp_path / "out.pdf"
    _make_dest_pdf(src, tree)
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        assert model.delete_pages([3]) == [3]
        model.save_as(str(out))
    finally:
        model.close()

    doc = fitz.open(out)
    try:
        assert len(doc) == 3
        names = set(_names_of(doc))
        assert {b"chap2", b"chap4", b"zzz"} <= names
        assert b"chap3" not in names and b"chapx" not in names
        resolved = {name: dest["page"] for name, dest in doc.resolve_names().items()}
        assert resolved["chap2"] == 1 and resolved["chap4"] == 2 and resolved["zzz"] == 2
        assert resolved["my two"] == 1
        assert "chap3" not in resolved and "old3" not in resolved and "chapx" not in resolved

        # Exactly the live links stay: chap2, explicit page 2, URI (not listed), chap4, my two.
        assert link_targets(doc, 0) == {
            _top(3): "chap2",
            _top(4): 1,
            _top(7): "chap4",
            _top(8): "my two",
        }
        assert sum(1 for link in doc[0].get_links() if link["kind"] == fitz.LINK_URI) == 1
        assert doc.xref_get_key(doc.pdf_catalog(), "OpenAction") == ("null", "null")
        # Nothing keeps the deleted page object (and its content) in the file.
        assert _page_objects(doc) == 3
    finally:
        doc.close()


def test_name_tree_limits_and_emptied_kids_follow_the_deleted_names(tmp_path: Path) -> None:
    src = tmp_path / "dests.pdf"
    _make_dest_pdf(src, "kids")
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        root_xref = int(model.doc.xref_get_key(model.doc.pdf_catalog(), "Names/Dests")[1].split()[0])
        kid_xrefs = [int(token) for token in re.findall(r"(\d+) 0 R", model.doc.xref_get_key(root_xref, "Kids")[1])]
        untouched_before = model.doc.xref_object(kid_xrefs[1], compressed=True)
        model.delete_pages([3])
        kids_after = model.doc.xref_get_key(root_xref, "Kids")[1]
        assert kids_after.count(" R") == 2  # the emptied kid left the tree
        assert model.doc.xref_get_key(kid_xrefs[0], "Limits")[1] == "[(chap2)(chap2)]"
        assert model.doc.xref_get_key(kid_xrefs[0], "Names")[1].count("chap") == 1
        # A node without a dead name is not rewritten.
        assert model.doc.xref_object(kid_xrefs[1], compressed=True) == untouched_before
    finally:
        model.close()


def test_deleting_every_page_leaves_no_dead_navigation(tmp_path: Path) -> None:
    src = tmp_path / "dests.pdf"
    out = tmp_path / "out.pdf"
    _make_dest_pdf(src)
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        assert model.delete_pages([1, 2, 3, 4]) == [1, 2, 3, 4]
        model.save_as(str(out))
    finally:
        model.close()
    doc = fitz.open(out)
    try:
        assert len(doc) == 1
        assert _names_of(doc) == {}
        assert doc.xref_get_key(doc.pdf_catalog(), "OpenAction") == ("null", "null")
        assert doc[0].get_links() == []
        assert _page_objects(doc) == 1
    finally:
        doc.close()


def test_a_name_defined_twice_keeps_its_links_while_one_definition_lives(tmp_path: Path) -> None:
    src = tmp_path / "dup.pdf"
    out = tmp_path / "out.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    px = [doc.page_xref(i) for i in range(3)]
    leaf = doc.get_new_xref()
    doc.update_object(leaf, f"<</Names[(dup)[{px[2]} 0 R/Fit]]>>")
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</Dests {leaf} 0 R>>")
    legacy = doc.get_new_xref()
    doc.update_object(legacy, f"<</dup[{px[1]} 0 R/Fit]>>")
    doc.xref_set_key(doc.pdf_catalog(), "Dests", f"{legacy} 0 R")
    annot = doc.get_new_xref()
    doc.update_object(annot, "<</Type/Annot/Subtype/Link/Rect[10 10 50 30]/A<</S/GoTo/D(dup)>>>>")
    doc.xref_set_key(px[0], "Annots", f"[{annot} 0 R]")
    doc.save(src)
    doc.close()
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        model.delete_pages([3])
        model.save_as(str(out))
    finally:
        model.close()
    doc = fitz.open(out)
    try:
        assert [link["kind"] for link in doc[0].get_links()] == [fitz.LINK_NAMED]
        assert doc.resolve_names()["dup"]["page"] == 1
    finally:
        doc.close()


def test_names_of_surviving_pages_and_the_legacy_dictionary_are_not_rewritten(tmp_path: Path) -> None:
    src = tmp_path / "dests.pdf"
    _make_dest_pdf(src)
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        catalog = model.doc.pdf_catalog()
        legacy_xref = int(model.doc.xref_get_key(catalog, "Dests")[1].split()[0])
        legacy_before = model.doc.xref_object(legacy_xref, compressed=True)
        names_before = _names_of(model.doc)
        model.delete_pages([1])  # nothing is named for page 1
        assert model.doc.xref_object(legacy_xref, compressed=True) == legacy_before
        assert _names_of(model.doc) == names_before
        assert model.doc.xref_get_key(catalog, "OpenAction")[0] == "array"
    finally:
        model.close()


def _first_outline_xref(doc: fitz.Document) -> int:
    return int(doc.get_outline_xrefs()[0])


def test_bookmark_that_names_a_deleted_destination_moves_to_the_survivor(tmp_path: Path) -> None:
    src = tmp_path / "dests.pdf"
    _make_dest_pdf(src)
    doc = fitz.open(src)
    item = doc.get_new_xref()
    root = doc.get_new_xref()
    doc.update_object(root, f"<</Type/Outlines/First {item} 0 R/Last {item} 0 R/Count 1>>")
    doc.update_object(item, f"<</Title(Chapter 3)/Parent {root} 0 R/Dest(chap3)>>")
    doc.xref_set_key(doc.pdf_catalog(), "Outlines", f"{root} 0 R")
    doc.saveIncr()
    doc.close()
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        model.delete_pages([3])
        # Old page 4 is the nearest survivor and is page 3 now.
        assert model.get_toc() == [[1, "Chapter 3", 3]]
        assert model.doc.xref_get_key(_first_outline_xref(model.doc), "Dest")[0] == "array"
    finally:
        model.close()


def test_straighten_keeps_names_links_and_open_action_on_the_replacement_page(tmp_path: Path) -> None:
    src = tmp_path / "dests.pdf"
    out = tmp_path / "out.pdf"
    _make_dest_pdf(src)
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        assert model.straighten_page(3, angle_degrees=4.0) is True
        model.save_as(str(out))
    finally:
        model.close()
    doc = fitz.open(out)
    try:
        assert len(doc) == 4
        names = _names_of(doc)
        assert {b"chap2", b"chap3", b"chap4"} <= set(names)
        new_page_ref = f"{doc.page_xref(2)} 0 R"
        assert names[b"chap3"].startswith(f"[{new_page_ref}")
        assert "/XYZ 0 400 null" in " ".join(names[b"chap3"].split())  # the view is kept
        resolved = {name: dest["page"] for name, dest in doc.resolve_names().items()}
        assert resolved["chap3"] == 2 and resolved["old3"] == 2
        targets = link_targets(doc, 0)
        assert targets[_top(0)] == "chap3"
        by_top = {round(link["from"].y0): link for link in doc[0].get_links()}
        assert by_top[_top(1)]["nameddest"] == "chap3" and by_top[_top(1)]["page"] == 2  # /Dest form
        assert targets[_top(2)] == 2  # the explicit link into the old page 3 follows the new one
        assert targets[_top(4)] == 1
        assert doc.xref_get_key(doc.pdf_catalog(), "OpenAction")[1].startswith(f"[{new_page_ref}")
        assert _page_objects(doc) == 4
    finally:
        doc.close()
