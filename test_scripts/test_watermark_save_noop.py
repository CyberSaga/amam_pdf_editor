"""Product save must not mutate non-target objects when no watermark exists.

Measured by the UI real-corpus umbrella: saving a document that never had
watermarks wrote an empty ``__pdf_editor_watermarks`` attachment, changing the
Catalog and appending new objects. These tests pin the save contract through
``PDFModel.save_as`` on the incremental save-back-to-original path.

The second half pins the reopen contract (F17-COH-2): a watermark this build
saved is drawn ONCE after a reopen -- in the view, in print, in the next save
and in an optimized copy -- and stays editable (remove / change replaces the
saved copy).
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import numpy as np
import pytest

from model.pdf_model import PDFModel
from model.tools.watermark_tool import WatermarkTool
from src.printing.helper_main import _build_snapshot_bytes

_EMBED = WatermarkTool.WATERMARK_EMBED_NAME


def _make_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(str(path))
    doc.close()


def _appended_non_xref(before_len: int, doc: fitz.Document) -> list[int]:
    # Mirrors the umbrella filter: an incremental save may append an XRef
    # stream, anything else is a new object.
    return [
        xref
        for xref in range(before_len, doc.xref_length())
        if doc.xref_get_key(xref, "Type") != ("name", "/XRef")
    ]


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "plain.pdf"
    _make_pdf(path)
    return path


def _open_model(path) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def test_save_without_watermarks_leaves_catalog_and_objects_untouched(pdf_path):
    with fitz.open(str(pdf_path)) as source:
        catalog_before = source.xref_object(source.pdf_catalog(), compressed=True)
        xref_len_before = source.xref_length()
        assert _EMBED not in source.embfile_names()

    model = _open_model(pdf_path)
    try:
        assert model.use_incremental_save
        assert model.doc.can_save_incrementally()
        assert model.tools.watermark.get_watermarks() == []
        model.save_as(str(pdf_path))
    finally:
        model.close_all_sessions()

    with fitz.open(str(pdf_path)) as reopened:
        assert reopened.xref_object(reopened.pdf_catalog(), compressed=True) == catalog_before
        assert _appended_non_xref(xref_len_before, reopened) == []
        assert _EMBED not in reopened.embfile_names()
        assert reopened.embfile_count() == 0


def test_save_without_watermarks_does_not_touch_live_doc(pdf_path):
    model = _open_model(pdf_path)
    try:
        catalog_before = model.doc.xref_object(model.doc.pdf_catalog(), compressed=True)
        xref_len_before = model.doc.xref_length()
        sid = model.get_active_session_id()
        assert model.tools.prepare_doc_for_save(sid) is None
        assert model.doc.xref_object(model.doc.pdf_catalog(), compressed=True) == catalog_before
        assert model.doc.xref_length() == xref_len_before
        assert _EMBED not in model.doc.embfile_names()
    finally:
        model.close_all_sessions()


def test_watermarks_round_trip_through_save(tmp_path, pdf_path):
    # Guard: pre-existing behaviour that the fix must keep.
    out = tmp_path / "wm.pdf"
    model = _open_model(pdf_path)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    reopened = _open_model(out)
    try:
        texts = [wm["text"] for wm in reopened.tools.watermark.get_watermarks()]
        assert texts == ["DRAFT"]
    finally:
        reopened.close_all_sessions()


def test_removed_watermarks_do_not_reload_after_save(tmp_path, pdf_path):
    # Guard: a previous attachment is rewritten as an empty list (pinned
    # existing behaviour), so no stale watermark data survives.
    out = tmp_path / "wm.pdf"
    model = _open_model(pdf_path)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    model = _open_model(out)
    try:
        (wm,) = model.tools.watermark.get_watermarks()
        assert model.tools.watermark.remove_watermark(wm["id"])
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    with fitz.open(str(out)) as reopened:
        assert _EMBED in reopened.embfile_names()
        assert json.loads(reopened.embfile_get(_EMBED).decode("utf-8")) == []

    final = _open_model(out)
    try:
        assert final.tools.watermark.get_watermarks() == []
    finally:
        final.close_all_sessions()


def test_unreadable_embed_tree_falls_back_to_clearing(pdf_path, monkeypatch):
    # Guard for fail-closed: if the attachment list cannot be read, keep the
    # old clear-and-rewrite path instead of skipping (never leave stale data).
    model = _open_model(pdf_path)
    try:
        calls: list[list[dict]] = []
        tool = model.tools.watermark
        monkeypatch.setattr(
            tool, "_write_watermarks_embed", lambda doc, wms: calls.append(list(wms))
        )
        monkeypatch.setattr(
            type(model.doc),
            "embfile_names",
            lambda self: (_ for _ in ()).throw(RuntimeError("broken names tree")),
        )
        assert tool.prepare_doc_for_save(model.get_active_session_id(), model.doc) is None
        assert calls == [[]]
    finally:
        monkeypatch.undo()
        model.close_all_sessions()


# --- F17-COH-2: a watermark this build saved is not stacked on reopen ----------
# The save bakes the watermark into the file (for other readers) AND stores its
# parameters in the attachment (so it stays editable here).  On reopen the
# parameters came back as the live overlay ON TOP of the baked ink: view and
# print drew two copies while the file held one, every Ctrl+S after a reopen
# baked one more, and removing the watermark could not remove the baked copy.
# Files written before the baked ink was marked keep the owner-accepted doubled
# look (PITFALLS F15-G5-GEOM, no migration); see the two guards at the end.
_WM = "DRAFT"


def _saved_with_watermark(tmp_path: Path, pdf_path: Path, name: str = "wm.pdf") -> Path:
    out = tmp_path / name
    model = _open_model(pdf_path)
    try:
        model.tools.watermark.add_watermark([1], _WM)
        model.save_as(str(out))
    finally:
        model.close_all_sessions()
    return out


def _page_text(source: Path | bytes, page_index: int = 0) -> str:
    doc = fitz.open("pdf", source) if isinstance(source, bytes) else fitz.open(str(source))
    try:
        return doc[page_index].get_text()
    finally:
        doc.close()


def _printed_text(model: PDFModel) -> str:
    """Page 1 of what the print helper receives: the snapshot plus its stamps."""
    data = _build_snapshot_bytes(model.capture_print_snapshot_bytes(), model.get_print_watermarks())
    return _page_text(data)


def _pixels_differing_from_file(model: PDFModel, path: Path) -> int:
    """Pixels where the on-screen page 1 and the page as a PDF reader draws it differ."""
    view = model.get_page_pixmap(1, 0.5)
    with fitz.open(str(path)) as doc:
        disk = doc[0].get_pixmap(matrix=fitz.Matrix(0.5, 0.5), annots=True)
    assert (view.width, view.height, view.n) == (disk.width, disk.height, disk.n)
    a = np.frombuffer(view.samples, dtype=np.uint8).reshape(view.height, view.width, view.n)
    b = np.frombuffer(disk.samples, dtype=np.uint8).reshape(disk.height, disk.width, disk.n)
    return int(np.count_nonzero(np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 8))


def test_reopened_watermark_is_drawn_once_in_view_print_and_every_save(tmp_path, pdf_path):
    out = _saved_with_watermark(tmp_path, pdf_path)
    assert _page_text(out).count(_WM) == 1
    for cycle in range(3):
        model = _open_model(out)
        try:
            assert [wm["text"] for wm in model.tools.watermark.get_watermarks()] == [_WM]
            assert not model.has_unsaved_changes()
            assert _pixels_differing_from_file(model, out) == 0, f"cycle {cycle}: view != file"
            assert _printed_text(model).count(_WM) == 1, f"cycle {cycle}: print"
            model.save_as(str(out))  # Ctrl+S over the open file
        finally:
            model.close_all_sessions()
        text = _page_text(out)
        assert text.count(_WM) == 1, f"cycle {cycle}: file"
        assert "hello world" in text


def test_save_reopen_cycles_leave_the_saved_page_contents_unchanged(tmp_path, pdf_path):
    """Two watermarks, one of two lines: three insert_text calls per bake.  The
    saved page must be the same after every reopen + Ctrl+S -- no extra copy and
    no extra wrapping ``q`` / ``Q`` streams (MuPDF counts marked content at the
    top level as unbalanced and ``insert_text`` then wraps the page again)."""
    out = tmp_path / "wm.pdf"
    model = _open_model(pdf_path)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT\nCOPY")
        model.tools.watermark.add_watermark([1], "SECOND", angle=0)
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    def saved_streams() -> list[bytes]:
        with fitz.open(str(out)) as doc:
            return [doc.xref_stream(x) for x in doc[0].get_contents()]

    first = saved_streams()
    for cycle in range(3):
        model = _open_model(out)
        try:
            model.save_as(str(out))
        finally:
            model.close_all_sessions()
        assert saved_streams() == first, f"cycle {cycle}"
    text = _page_text(out)
    assert (text.count("DRAFT"), text.count("COPY"), text.count("SECOND")) == (1, 1, 1)


def test_removing_a_reopened_watermark_removes_its_saved_copy(tmp_path, pdf_path):
    out = _saved_with_watermark(tmp_path, pdf_path)
    model = _open_model(out)
    try:
        (wm,) = model.tools.watermark.get_watermarks()
        assert model.tools.watermark.remove_watermark(wm["id"])
        # The page now looks exactly like the original without a watermark.
        assert _pixels_differing_from_file(model, pdf_path) == 0
        assert _WM not in _printed_text(model)
        model.save_as(str(out))
    finally:
        model.close_all_sessions()
    text = _page_text(out)
    assert _WM not in text and "hello world" in text


def test_changing_a_reopened_watermark_replaces_its_saved_copy(tmp_path, pdf_path):
    out = _saved_with_watermark(tmp_path, pdf_path)
    model = _open_model(out)
    try:
        (wm,) = model.tools.watermark.get_watermarks()
        assert model.tools.watermark.update_watermark(wm["id"], text="FINAL")
        printed = _printed_text(model)
        assert printed.count("FINAL") == 1 and _WM not in printed
        model.save_as(str(out))
    finally:
        model.close_all_sessions()
    text = _page_text(out)
    assert text.count("FINAL") == 1 and _WM not in text


@pytest.mark.parametrize("dirty", [False, True], ids=["clean_session", "dirty_session"])
def test_optimized_copy_of_a_reopened_watermark_holds_one_copy(tmp_path, pdf_path, dirty):
    out = _saved_with_watermark(tmp_path, pdf_path)
    opt = tmp_path / "opt.pdf"
    model = _open_model(out)
    try:
        if dirty:
            (wm,) = model.tools.watermark.get_watermarks()
            assert model.tools.watermark.update_watermark(wm["id"], opacity=0.5)
        model.save_optimized_copy(str(opt))
    finally:
        model.close_all_sessions()
    assert _page_text(opt).count(_WM) == 1
    # The default preset cleans the content streams, which merges the baked
    # watermark into the page's single stream: a reopen must still draw it once.
    model = _open_model(opt)
    try:
        assert [wm["text"] for wm in model.tools.watermark.get_watermarks()] == [_WM]
        assert _pixels_differing_from_file(model, opt) == 0
        assert _printed_text(model).count(_WM) == 1
        model.save_as(str(opt))
    finally:
        model.close_all_sessions()
    text = _page_text(opt)
    assert text.count(_WM) == 1 and "hello world" in text


def test_optimize_working_copy_of_a_reopened_watermark_holds_one_copy(tmp_path, pdf_path):
    out = _saved_with_watermark(tmp_path, pdf_path)
    model = _open_model(out)
    try:
        working = model._build_working_doc_for_optimized_copy(model.get_active_session_id())
        try:
            assert working[0].get_text().count(_WM) == 1
        finally:
            working.close()
    finally:
        model.close_all_sessions()


@pytest.mark.parametrize("layout", ["indirect_contents_array", "merged_by_clean_contents"])
def test_reopen_finds_the_saved_watermark_in_other_content_layouts(tmp_path, pdf_path, layout):
    """Another tool may keep ``/Contents`` as an indirect array, or merge the
    page's streams into one (``clean_contents``); the reopened page must still
    show one copy and keep its own text."""
    out = _saved_with_watermark(tmp_path, pdf_path)
    moved = tmp_path / "moved.pdf"
    with fitz.open(str(out)) as doc:
        page = doc[0]
        if layout == "merged_by_clean_contents":
            page.clean_contents()
            assert len(page.get_contents()) == 1
        else:
            kind, value = doc.xref_get_key(page.xref, "Contents")
            assert kind == "array"
            array_xref = doc.get_new_xref()
            doc.update_object(array_xref, value)
            doc.xref_set_key(page.xref, "Contents", f"{array_xref} 0 R")
        doc.save(str(moved), garbage=1)
    model = _open_model(moved)
    try:
        assert _pixels_differing_from_file(model, moved) == 0
        assert _printed_text(model).count(_WM) == 1
        assert "hello world" in model.doc[0].get_text()
        model.save_as(str(moved))
    finally:
        model.close_all_sessions()
    text = _page_text(moved)
    assert text.count(_WM) == 1 and "hello world" in text


def test_unmarked_ink_of_an_older_build_is_left_as_page_content(tmp_path, pdf_path):
    """Guard (owner-accepted, no migration): ink baked before the marker
    existed cannot be told apart from the page's own text, so it stays."""
    old = tmp_path / "old.pdf"
    with fitz.open(str(pdf_path)) as doc:
        doc[0].insert_text((150, 450), _WM, fontsize=48)
        stored = [{"id": "old-build-1", "pages": [1], "text": _WM}]
        doc.embfile_add(_EMBED, json.dumps(stored).encode("utf-8"))
        doc.save(str(old))
        streams_before = [doc.xref_stream(x) for x in doc[0].get_contents()]
    model = _open_model(old)
    try:
        assert [wm["text"] for wm in model.tools.watermark.get_watermarks()] == [_WM]
        page = model.doc[0]
        assert [model.doc.xref_stream(x) for x in page.get_contents()] == streams_before
    finally:
        model.close_all_sessions()


def test_saved_watermark_without_its_stored_parameters_stays_page_content(tmp_path, pdf_path):
    """Guard: when another tool dropped the attachment, the marked ink is the
    only copy left and must not be removed."""
    out = _saved_with_watermark(tmp_path, pdf_path)
    bare = tmp_path / "bare.pdf"
    with fitz.open(str(out)) as doc:
        doc.embfile_del(_EMBED)
        doc.save(str(bare), garbage=1)
    model = _open_model(bare)
    try:
        assert model.tools.watermark.get_watermarks() == []
        assert _printed_text(model).count(_WM) == 1
        assert _pixels_differing_from_file(model, bare) == 0
    finally:
        model.close_all_sessions()


# --- F17-COH-3 / F17-COH-4: the saved and the derived files ---------------------
# A watermark belongs to its page: Save after a reorder / delete must bake it onto
# THAT page, and a PDF derived from the session (export pages, merge to a new
# file) carries it too, drawn once when this app reopens it.


def _labelled_pdf(path: Path, labels: list[str]) -> Path:
    doc = fitz.open()
    for label in labels:
        page = doc.new_page()
        page.insert_text((72, 100), label, fontsize=12.0)
    doc.save(str(path))
    doc.close()
    return path


def _stamped(path: Path) -> list[str]:
    """First word of every page of ``path`` that carries the watermark text, once."""
    with fitz.open(str(path)) as doc:
        texts = [page.get_text() for page in doc]
    assert all(text.count(_WM) <= 1 for text in texts), texts
    return [text.split()[0] for text in texts if _WM in text]


def test_a_watermark_is_saved_on_its_page_after_a_reorder_and_a_delete(tmp_path):
    source = _labelled_pdf(tmp_path / "abc.pdf", ["AAA", "BBB", "CCC"])
    out = tmp_path / "out.pdf"
    model = _open_model(source)
    try:
        model.tools.watermark.add_watermark([2], _WM)  # BBB
        model.move_page(1, 0)  # BBB, AAA, CCC
        model.delete_pages([2])  # BBB, CCC
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    assert _stamped(out) == ["BBB"]
    with fitz.open(str(out)) as saved:
        assert [page.get_text().split()[0] for page in saved] == ["BBB", "CCC"]
    reopened = _open_model(out)
    try:
        assert [wm["pages"] for wm in reopened.tools.watermark.get_watermarks()] == [[1]]
        assert _pixels_differing_from_file(reopened, out) == 0  # page 1: one copy
        assert _printed_text(reopened).count(_WM) == 1
    finally:
        reopened.close_all_sessions()


def test_a_pdf_exported_with_a_pending_watermark_reopens_with_one_copy(tmp_path):
    source = _labelled_pdf(tmp_path / "abc.pdf", ["AAA", "BBB", "CCC"])
    out = tmp_path / "export.pdf"
    model = _open_model(source)
    try:
        model.tools.watermark.add_watermark([2], _WM)
        model.export_pages([2], str(out), as_image=False)
        # The session itself did not change.
        assert [wm["pages"] for wm in model.tools.watermark.get_watermarks()] == [[2]]
        assert _WM not in model.doc[1].get_text()
    finally:
        model.close_all_sessions()

    assert _stamped(out) == ["BBB"]
    reopened = _open_model(out)
    try:
        assert [wm["pages"] for wm in reopened.tools.watermark.get_watermarks()] == [[1]]
        assert _pixels_differing_from_file(reopened, out) == 0
        assert _printed_text(reopened).count(_WM) == 1
        reopened.save_as(str(out))
    finally:
        reopened.close_all_sessions()
    assert _stamped(out) == ["BBB"]


def test_a_merged_new_file_with_a_pending_watermark_reopens_with_one_copy(tmp_path):
    source = _labelled_pdf(tmp_path / "ab.pdf", ["AAA", "BBB"])
    extra = _labelled_pdf(tmp_path / "x.pdf", ["XXX"])
    out = tmp_path / "merged.pdf"
    model = _open_model(source)
    try:
        model.tools.watermark.add_watermark([2], _WM)
        merged = model.compose_merged_document(
            [{"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}]
        )
        try:
            model.save_external_document(merged, out)
        finally:
            merged.close()
    finally:
        model.close_all_sessions()

    assert _stamped(out) == ["BBB"]
    reopened = _open_model(out)
    try:
        assert [wm["pages"] for wm in reopened.tools.watermark.get_watermarks()] == [[3]]
        assert _printed_text(reopened).count(_WM) == 0  # page 1 is XXX: unmarked
        with fitz.open(str(out)) as disk:
            view = reopened.get_page_pixmap(3, 0.5)
            mismatched = _pixmap_difference(view, disk[2])
        assert mismatched == 0
    finally:
        reopened.close_all_sessions()


def _pixmap_difference(view: fitz.Pixmap, page: fitz.Page) -> int:
    disk = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), annots=True)
    assert (view.width, view.height, view.n) == (disk.width, disk.height, disk.n)
    a = np.frombuffer(view.samples, dtype=np.uint8).reshape(view.height, view.width, view.n)
    b = np.frombuffer(disk.samples, dtype=np.uint8).reshape(disk.height, disk.width, disk.n)
    return int(np.count_nonzero(np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 8))
