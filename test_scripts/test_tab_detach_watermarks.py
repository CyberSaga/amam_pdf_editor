"""F17-COH-2 follow-up: a detached tab carries the session's watermark list, saved or not."""
from __future__ import annotations

from pathlib import Path

import fitz

from controller.session_transfer import SessionTransferPayload
from model.pdf_model import PDFModel


def _pdf(path: Path) -> None:
    with fitz.open() as doc:
        doc.new_page().insert_text((40, 60), "DETACH")
        doc.new_page().insert_text((40, 60), "TWO")
        doc.save(str(path))


def _detach(source: PDFModel, destination: PDFModel) -> str:
    payload = SessionTransferPayload.from_model(
        source, source.get_active_session_id(), current_page=0, scale=1.0, color_profile="srgb"
    )
    return destination.import_session_transfer(payload)


def _texts(model: PDFModel) -> list[str]:
    return [wm["text"] for wm in model.get_print_watermarks()]


def test_unsaved_added_watermark_survives_a_detach(tmp_path) -> None:
    path = tmp_path / "a.pdf"
    _pdf(path)
    source, destination = PDFModel(), PDFModel()
    try:
        source.open_pdf(str(path))
        source.tools.watermark.add_watermark([1, 2], "DRAFT")
        sid = _detach(source, destination)
        assert _texts(destination) == ["DRAFT"]
        assert destination.session_has_unsaved_changes(sid) is True
    finally:
        source.close()
        destination.close()


def test_saved_then_removed_watermark_stays_removed_after_a_detach(tmp_path) -> None:
    path = tmp_path / "b.pdf"
    _pdf(path)
    source, destination = PDFModel(), PDFModel()
    try:
        source.open_pdf(str(path))
        wm_id = source.tools.watermark.add_watermark([1], "GONE")
        source.save_as(str(tmp_path / "saved.pdf"))
        assert _texts(source) == ["GONE"]
        assert source.tools.watermark.remove_watermark(wm_id)
        sid = _detach(source, destination)
        assert _texts(destination) == []
        assert destination.session_has_unsaved_changes(sid) is True
    finally:
        source.close()
        destination.close()


def test_a_clean_session_detach_keeps_its_saved_watermark_and_stays_clean(tmp_path) -> None:
    path = tmp_path / "c.pdf"
    _pdf(path)
    source, destination = PDFModel(), PDFModel()
    try:
        source.open_pdf(str(path))
        source.tools.watermark.add_watermark([2], "KEEP")
        saved = tmp_path / "saved_c.pdf"
        source.save_as(str(saved))
        sid = _detach(source, destination)
        assert _texts(destination) == ["KEEP"]
        assert destination.get_print_watermarks()[0]["pages"] == [2]
        assert destination.session_has_unsaved_changes(sid) is False
    finally:
        source.close()
        destination.close()
