from __future__ import annotations

from pathlib import Path
import fitz
import pytest
from controller.pdf_controller import PDFController
from model.edit_commands import SnapshotCommand
from model.page_snapshot import PageSnapshotStale
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view
from view.pdf_view import PDFView


def _source(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    orphan = doc.get_new_xref()
    doc.update_object(orphan, "<< /Unreachable true >>")
    for index in range(3):
        page.add_text_annot((40 + index * 100, 50), f"note {index + 1}").update()
    doc.save(path, garbage=0)
    doc.close()
    return path


def _note_map(model):
    return {n["text"]: n["xref"] for n in model.tools.annotation.get_all_annotations()}


def _fail_pack(monkeypatch):
    original = fitz.Document.save
    def save(doc, target, *args, **kwargs):
        if kwargs.get("use_objstms"):
            raise OSError("injected second-pass failure")
        return original(doc, target, *args, **kwargs)
    monkeypatch.setattr(fitz.Document, "save", save)
    return original


def test_failed_secure_pack_publishes_the_already_changed_numbering(tmp_path, monkeypatch):
    path = _source(tmp_path / "notes.pdf")
    original_bytes = path.read_bytes()
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        note = _note_map(model)["note 1"]
        before_bytes = model._capture_doc_snapshot()
        model.tools.annotation.update_annotation(note, "edited note 1")
        model.command_manager.record(SnapshotCommand(
            model=model, command_type="update_annotation", affected_pages=[1],
            before_bytes=before_bytes, after_bytes=model._capture_doc_snapshot(),
            description="note update",
        ))
        assert model.has_unsaved_changes(), "fixture must use the controller command contract"
        model.secure_save_required = True
        before = _note_map(model)
        epoch = model.xref_epoch
        live = model.doc
        snapshot = model._capture_page_snapshot_strict(0)
        original_save = _fail_pack(monkeypatch)
        with pytest.raises(OSError, match="second-pass"):
            model.save_as(str(path))
        assert _note_map(model) != before, "fixture must actually renumber"
        assert set(_note_map(model)) == set(before)
        assert model.doc is live
        assert model.xref_epoch != epoch, "xref consumers must see renumbering even when packing fails"
        assert model.has_unsaved_changes()
        with pytest.raises(PageSnapshotStale):
            model._restore_page_from_snapshot(0, snapshot)
        assert path.read_bytes() == original_bytes
        monkeypatch.setattr(fitz.Document, "save", original_save)
        model.save_as(str(path))
    finally:
        model.close()
    with fitz.open(path) as saved:
        assert not saved.is_repaired
        assert [a.info["content"] for a in saved[0].annots()] == ["edited note 1", "note 2", "note 3"]


def test_failed_secure_pack_refreshes_the_open_note_before_its_next_edit(qapp, tmp_path, monkeypatch):
    path = _source(tmp_path / "notes.pdf")
    original_bytes = path.read_bytes()
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    failures = []
    monkeypatch.setattr(controller, "_report_save_failure", lambda prefix, exc: failures.append(str(exc)))
    try:
        controller.open_pdf(str(path))
        controller.load_annotations()
        dto = next(dict(n) for n in view._annotation_dtos if n["text"] == "note 2")
        view._show_floating_note(dto)
        popup = view._floating_note
        popup.editor.setPlainText("pending note 2")
        model.secure_save_required = True
        old_xref = popup.xref
        _fail_pack(monkeypatch)
        assert controller._save_active_document_to(str(path), "test failure") is False
        qapp.processEvents()
        new_xref = _note_map(model)["note 2"]
        assert new_xref != old_xref
        assert view._floating_note is popup
        assert popup.xref == new_xref
        assert popup.editor.toPlainText() == "pending note 2"
        popup.save_button.click()
        qapp.processEvents()
        assert set(_note_map(model)) == {"note 1", "pending note 2", "note 3"}
        assert failures == ["injected second-pass failure"]
        assert path.read_bytes() == original_bytes
    finally:
        dispose_pdf_view(view, controller, model)
        qapp.processEvents()


def test_successful_secure_pack_notifies_live_renumbering_once(tmp_path, monkeypatch):
    path = _source(tmp_path / "notes.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.secure_save_required = True
        calls = []
        original = model._note_live_doc_serialized
        def note(doc, garbage):
            if garbage >= 2 and doc is model.doc:
                calls.append(garbage)
            return original(doc, garbage)
        monkeypatch.setattr(model, "_note_live_doc_serialized", note)
        model.save_as(str(path))
        assert calls == [4]
    finally:
        model.close()


@pytest.mark.parametrize("clone", [False, True])
def test_numbering_preserving_or_clone_pack_failure_does_not_change_live_epoch(tmp_path, monkeypatch, clone):
    path = _source(tmp_path / "notes.pdf")
    model = PDFModel()
    copied = None
    try:
        model.open_pdf(str(path))
        epoch, notes = model.xref_epoch, _note_map(model)
        if clone:
            copied = fitz.open("pdf", model.doc.tobytes())
        _fail_pack(monkeypatch)
        with pytest.raises(OSError, match="second-pass"):
            model._save_doc_packed(copied if clone else model.doc, tmp_path / "packed.pdf", garbage=4 if clone else 1)
        assert model.xref_epoch == epoch
        assert _note_map(model) == notes
    finally:
        if copied is not None:
            copied.close()
        model.close()
