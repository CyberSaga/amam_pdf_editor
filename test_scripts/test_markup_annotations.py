from __future__ import annotations

import ast
from pathlib import Path

import fitz
import pytest

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from model.tools.annotation_tool import AnnotationTool
from view.pdf_view import PDFView


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "first markup line", fontsize=12)
    page.insert_text((72, 115), "second markup line", fontsize=12)
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize(
    ("signal_name", "command_type", "annot_type"),
    [
        ("sig_add_underline", "add_underline", "Underline"),
        ("sig_add_strikeout", "add_strikeout", "StrikeOut"),
    ],
)
def test_controller_records_markup_snapshot_and_undo_redo(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal_name: str,
    command_type: str,
    annot_type: str,
) -> None:
    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    try:
        controller.activate()
        controller.open_pdf(str(_make_pdf(tmp_path / f"{command_type}.pdf")))
        monkeypatch.setattr(controller, "_invalidate_active_render_state", lambda **_kwargs: None)
        monkeypatch.setattr(controller, "show_page", lambda _page: None)
        monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)

        signal = getattr(view, signal_name)
        signal.emit(1, fitz.Rect(68, 77, 190, 120), (0.8, 0.1, 0.2, 0.7))

        command = model.command_manager._undo_stack[-1]
        assert command._command_type == command_type
        page = model.doc[0]
        assert [annot.type[1] for annot in page.annots()] == [annot_type]

        monkeypatch.setattr(controller, "_refresh_after_command", lambda _command: None)
        controller.undo()
        assert list(model.doc[0].annots() or []) == []
        controller.redo()
        page = model.doc[0]
        assert [annot.type[1] for annot in page.annots()] == [annot_type]
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_controller_records_rectangle_appearance_snapshot_and_undo_redo(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = PDFModel()
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    try:
        controller.activate()
        controller.open_pdf(str(_make_pdf(tmp_path / "rect_appearance.pdf")))
        monkeypatch.setattr(controller, "_invalidate_active_render_state", lambda **_kwargs: None)
        monkeypatch.setattr(controller, "show_page", lambda _page: None)
        monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)

        view.sig_add_rect.emit(
            1,
            fitz.Rect(40, 130, 180, 200),
            (1.0, 0.0, 0.0, 0.8),
            (0.0, 1.0, 0.0, 0.8),
            2.5,
        )

        command = model.command_manager._undo_stack[-1]
        assert command._command_type == "add_rect"
        page = model.doc[0]
        annot = next(page.annots())
        assert annot.colors["stroke"] == pytest.approx([1.0, 0.0, 0.0])
        assert annot.colors["fill"] == pytest.approx([0.0, 1.0, 0.0])
        assert annot.border["width"] == pytest.approx(2.5)

        monkeypatch.setattr(controller, "_refresh_after_command", lambda _command: None)
        controller.undo()
        assert list(model.doc[0].annots() or []) == []
        controller.redo()
        page = model.doc[0]
        assert [annot.type[1] for annot in page.annots()] == ["Square"]
    finally:
        model.close()
        view.close()
        qapp.processEvents()


class _DocStub:
    """Minimal stand-in providing the ``.doc`` attribute AnnotationTool needs."""

    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc


def test_toggle_annotations_visibility_sets_and_clears_hidden_flag() -> None:
    """F11-ANN-6: the toggle used a constant PyMuPDF 1.27 does not define."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "toggle target", fontsize=12)
    note = page.add_text_annot((300, 300), "a note")
    free = page.add_freetext_annot(fitz.Rect(72, 200, 250, 240), "free text", fontsize=11)
    marker = page.add_highlight_annot(fitz.Rect(72, 78, 150, 94))
    note_xref, free_xref, marker_xref = note.xref, free.xref, marker.xref
    tool = AnnotationTool(_DocStub(doc))
    try:
        tool.toggle_annotations_visibility(False)
        page = doc[0]
        assert page.load_annot(note_xref).flags & fitz.PDF_ANNOT_IS_HIDDEN
        assert page.load_annot(free_xref).flags & fitz.PDF_ANNOT_IS_HIDDEN
        # Only Text / FreeText are toggled; markup annotations stay visible.
        assert not page.load_annot(marker_xref).flags & fitz.PDF_ANNOT_IS_HIDDEN

        tool.toggle_annotations_visibility(True)
        page = doc[0]
        assert not page.load_annot(note_xref).flags & fitz.PDF_ANNOT_IS_HIDDEN
        assert not page.load_annot(free_xref).flags & fitz.PDF_ANNOT_IS_HIDDEN
    finally:
        doc.close()


def test_toggle_annotations_visibility_without_document_is_noop() -> None:
    AnnotationTool(_DocStub(None)).toggle_annotations_visibility(False)  # type: ignore[arg-type]


def test_every_fitz_attribute_used_in_source_exists() -> None:
    """Guard for the F11-ANN-6 bug class: ``fitz.<name>`` that this PyMuPDF lacks.

    Such a name only fails when its line runs, so one-click features can ship broken.
    """
    root = Path(__file__).resolve().parent.parent
    missing: list[str] = []
    for package in ("model", "controller", "view", "utils"):
        for path in sorted((root / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "fitz"
                    and not hasattr(fitz, node.attr)
                ):
                    missing.append(f"{path.relative_to(root)}:{node.lineno} fitz.{node.attr}")
    assert missing == []
