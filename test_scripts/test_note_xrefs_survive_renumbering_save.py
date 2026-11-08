"""A save that renumbers the live document must not leave stale note xrefs (CF5).

A ``secure_save_required`` save is a ``garbage=4`` rewrite that renumbers the
live document.  The controller's annotation list, the view's hit-test copies
and an open FloatingNote kept the pre-save xrefs, and
``AnnotationTool._find_annotation`` matches on the xref alone: editing note 2
after "delete note 1, <a renumbering latch>, Ctrl+S" rewrote note 3.  A note
delete on its own no longer latches (it takes the numbering-preserving CF17
full save), so the renumbering cases set the latch the way the other user
deletes do (page, TOC, metadata, object delete).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view
from view.pdf_view import PDFView

POINTS = ((40, 50), (140, 50), (240, 50))


def _make_pdf_with_three_notes(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    for index, point in enumerate(POINTS, start=1):
        page.add_text_annot(fitz.Point(*point), f"note {index}", icon="Note").update()
    doc.save(path)
    doc.close()


def _texts(path: Path) -> list[str]:
    doc = fitz.open(path)
    try:
        return [annot.info.get("content", "") for page in doc for annot in page.annots()]
    finally:
        doc.close()


def _open(tmp_path: Path) -> tuple[Path, PDFView, PDFController, PDFModel]:
    path = tmp_path / "notes.pdf"
    _make_pdf_with_three_notes(path)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    controller.load_annotations()
    return path, view, controller, model


def _dto(view: PDFView, text: str) -> dict:
    return next(dict(dto) for dto in view._annotation_dtos if dto["text"] == text)


def _delete_note_one_and_save(qapp, path: Path, view: PDFView, controller: PDFController) -> int:
    controller.delete_annotation(0, _dto(view, "note 1")["xref"])
    qapp.processEvents()
    # Another user delete (page, TOC, metadata, object) latched the renumbering rewrite.
    controller.model.secure_save_required = True
    epoch = controller.model.xref_epoch
    assert controller._save_active_document_to(str(path), "儲存失敗") is True
    qapp.processEvents()
    return epoch


def _edit_through_popup(qapp, view: PDFView, text: str) -> None:
    note = view._floating_note
    assert note is not None
    note.editor.setPlainText(text)
    note.save_button.click()
    qapp.processEvents()


def test_note_picked_after_a_renumbering_save_edits_that_note(qapp, tmp_path: Path) -> None:
    path, view, controller, model = _open(tmp_path)
    try:
        epoch = _delete_note_one_and_save(qapp, path, view, controller)
        assert model.xref_epoch != epoch, "the save must be the renumbering rewrite"

        # The UI path: the hit test hands the view's DTO to the popup.
        view._show_floating_note(_dto(view, "note 2"))
        _edit_through_popup(qapp, view, "note 2 EDITED")

        notes = model.tools.annotation.get_all_annotations()
        assert [note["text"] for note in notes] == ["note 2 EDITED", "note 3"]
        assert [note["xref"] for note in controller.annotations] == [note["xref"] for note in notes]
    finally:
        dispose_pdf_view(view, controller, model)
        qapp.processEvents()
    assert _texts(path) == ["note 2", "note 3"]


def test_note_popup_open_across_a_renumbering_save_edits_its_own_note(qapp, tmp_path: Path) -> None:
    path, view, controller, model = _open(tmp_path)
    try:
        controller.delete_annotation(0, _dto(view, "note 1")["xref"])
        qapp.processEvents()
        model.secure_save_required = True  # another user delete latched the rewrite
        view._show_floating_note(_dto(view, "note 2"))
        epoch = model.xref_epoch
        assert controller._save_active_document_to(str(path), "儲存失敗") is True
        qapp.processEvents()
        assert model.xref_epoch != epoch, "the save must be the renumbering rewrite"

        _edit_through_popup(qapp, view, "note 2 EDITED")

        notes = model.tools.annotation.get_all_annotations()
        assert [note["text"] for note in notes] == ["note 2 EDITED", "note 3"]
    finally:
        dispose_pdf_view(view, controller, model)
        qapp.processEvents()


def test_a_page_delete_latch_save_also_refreshes_the_note_xrefs(qapp, tmp_path: Path) -> None:
    """The refresh is per renumbering save, not per note delete: the older
    latches (page delete here; TOC, metadata, object delete) renumber too."""
    path = tmp_path / "pages.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=300).add_text_annot(fitz.Point(40, 50), "note 1").update()
    second = doc.new_page(width=400, height=300)
    for index, point in enumerate(POINTS[1:], start=2):
        second.add_text_annot(fitz.Point(*point), f"note {index}").update()
    doc.save(path)
    doc.close()
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    try:
        controller.open_pdf(str(path))
        assert model.delete_pages([1]) == [1]
        controller.load_annotations()
        view._show_floating_note(_dto(view, "note 3"))
        epoch = model.xref_epoch
        assert controller._save_active_document_to(str(path), "儲存失敗") is True
        qapp.processEvents()
        assert model.xref_epoch != epoch, "the save must be the renumbering rewrite"

        _edit_through_popup(qapp, view, "note 3 EDITED")
        view._show_floating_note(_dto(view, "note 2"))
        _edit_through_popup(qapp, view, "note 2 EDITED")

        notes = model.tools.annotation.get_all_annotations()
        assert [note["text"] for note in notes] == ["note 2 EDITED", "note 3 EDITED"]
    finally:
        dispose_pdf_view(view, controller, model)
        qapp.processEvents()


def test_a_note_delete_save_keeps_the_numbering_and_the_open_popup(qapp, tmp_path: Path) -> None:
    """A note delete alone takes the numbering-preserving full save (CF17): no
    latch, no new epoch, the other notes keep their xrefs and an open popup
    keeps editing its own note."""
    path, view, controller, model = _open(tmp_path)
    try:
        before = {note["text"]: note["xref"] for note in model.tools.annotation.get_all_annotations()}
        controller.delete_annotation(0, _dto(view, "note 1")["xref"])
        qapp.processEvents()
        assert model.secure_save_required is False
        view._show_floating_note(_dto(view, "note 2"))
        popup = view._floating_note
        epoch = model.xref_epoch
        assert controller._save_active_document_to(str(path), "儲存失敗") is True
        qapp.processEvents()
        assert model.xref_epoch == epoch, "the note delete's save keeps the numbering"
        assert view._floating_note is popup
        notes = model.tools.annotation.get_all_annotations()
        assert {note["text"]: note["xref"] for note in notes} == {
            "note 2": before["note 2"],
            "note 3": before["note 3"],
        }

        _edit_through_popup(qapp, view, "note 2 EDITED")
        notes = model.tools.annotation.get_all_annotations()
        assert [note["text"] for note in notes] == ["note 2 EDITED", "note 3"]
        assert [note["xref"] for note in controller.annotations] == [note["xref"] for note in notes]
    finally:
        dispose_pdf_view(view, controller, model)
        qapp.processEvents()
    assert _texts(path) == ["note 2", "note 3"]


def test_a_save_that_keeps_the_numbering_keeps_the_open_popup(qapp, tmp_path: Path) -> None:
    path, view, controller, model = _open(tmp_path)
    try:
        view._show_floating_note(_dto(view, "note 2"))
        popup = view._floating_note
        epoch = model.xref_epoch
        controller.update_annotation_content(0, _dto(view, "note 3")["xref"], "note 3 EDITED")
        qapp.processEvents()
        assert controller._save_active_document_to(str(path), "儲存失敗") is True
        qapp.processEvents()
        assert model.xref_epoch == epoch, "an unlatched in-place save keeps the numbering"
        assert view._floating_note is popup

        _edit_through_popup(qapp, view, "note 2 EDITED")
        notes = model.tools.annotation.get_all_annotations()
        assert [note["text"] for note in notes] == ["note 1", "note 2 EDITED", "note 3 EDITED"]
    finally:
        dispose_pdf_view(view, controller, model)
        qapp.processEvents()
