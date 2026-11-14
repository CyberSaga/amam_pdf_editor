"""An in-place save of an UNSIGNED document must not keep replaced content (CF17).

The default save back to the opened file is an incremental append: the live
document's changed objects are written as a new revision after the old bytes.
Whatever the user REPLACED or REMOVED (a sticky note's old text, the text a
true-text edit replaced, a textbox marker's JSON payload) therefore stayed
readable in the earlier revision of the saved file.  After such an edit the
save back takes the numbering-preserving ``garbage=1`` full rewrite instead
(``PDFModel._saved_content_blocks_incremental``), silently: no dialog, no
latch, the xref numbers and the epoch unchanged.  Pure additions and an
unedited save keep the cheap append; a signed document keeps its append-only
save (owner decision: its residual is accepted).

The scans read EVERY revision of the saved file (each ``%%EOF`` prefix is
opened and every object and decoded stream searched), because a reopen shows
only the newest revision and Flate / object streams hide text from a raw scan.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.object_requests import MoveObjectRequest  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402

OLD_NOTE = "NOTE-OLD-SECRET-5531"
NEW_NOTE = "note new text"
TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica: a Tier 0 commit
DOWNSTREAM = "Downstream line stays"
BOX_TEXT = "BOXSECRET 991"


# ---------------------------------------------------------------- fixtures


def _write_note_pdf(path: Path, *, signed: bool = False) -> Path:
    """One text page whose sticky note (saved on disk) holds ``OLD_NOTE``.

    ``signed`` adds a signed signature widget on a second page (the minimal
    shape ``document_has_a_signed_signature`` recognises)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world", fontsize=12.0)
    page.add_text_annot((300, 300), OLD_NOTE)
    if signed:
        doc.new_page().insert_text((72, 100), "Signed page", fontsize=12.0)
        sig = doc.get_new_xref()
        doc.update_object(
            sig,
            "<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached"
            " /ByteRange [0 0 0 0] /Contents <00000000> >>",
        )
        widget = doc.get_new_xref()
        doc.update_object(
            widget,
            f"<< /Type /Annot /Subtype /Widget /FT /Sig /T (Sig1) /Rect [72 600 272 650] /F 4"
            f" /V {sig} 0 R /P {doc.page_xref(1)} 0 R >>",
        )
        doc.xref_set_key(doc.page_xref(1), "Annots", f"[{widget} 0 R]")
        form = doc.get_new_xref()
        doc.update_object(form, f"<< /Fields [{widget} 0 R] /SigFlags 3 >>")
        doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{form} 0 R")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _write_tier0_pdf(path: Path) -> Path:
    """A raw literal-Tj page (Tier 0 eligible), as in test_text_commit_persistence."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _write_textbox_pdf(path: Path) -> fitz.Rect:
    """An app textbox (page text + JSON marker payload holding ``BOX_TEXT``) saved on disk."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(str(path), garbage=0)
    doc.close()
    rect = fitz.Rect(100, 200, 300, 260)
    model = PDFModel()
    model.open_pdf(str(path))
    try:
        model.add_textbox(1, rect, BOX_TEXT, font="helv", size=12)
        model.save_as(str(path))
    finally:
        model.close()
    assert BOX_TEXT in _payload_texts(path), "fixture: the marker payload must be on disk"
    return rect


def _payload_texts(path: Path) -> list[str]:
    texts: list[str] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            for annot in page.annots():
                try:
                    payload = json.loads(annot.info.get("content") or "")
                except ValueError:
                    continue
                if isinstance(payload, dict) and payload.get("kind") == "textbox":
                    texts.append(str(payload.get("text")))
    return texts


def _open(path: Path) -> PDFModel:
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


# ---------------------------------------------------------------- scanning


def _revisions(data: bytes) -> list[bytes]:
    """Every revision of ``data``: the prefix up to and including each ``%%EOF``."""
    return [data[: m.end()] for m in re.finditer(rb"%%EOF[\r\n]*", data)]


def _revisions_holding(path: Path, marker: str) -> list[int]:
    """Indexes of the revisions of ``path`` whose objects / decoded streams / text hold ``marker``."""
    needle = marker.encode("latin-1")
    hits: list[int] = []
    for index, revision in enumerate(_revisions(path.read_bytes())):
        found = needle in revision
        with fitz.open("pdf", revision) as doc:
            for xref in range(1, doc.xref_length()):
                try:
                    if marker in doc.xref_object(xref, compressed=True):
                        found = True
                    if doc.xref_is_stream(xref) and needle in (doc.xref_stream(xref) or b""):
                        found = True
                except Exception:
                    continue
            for page in doc:
                if marker in page.get_text():
                    found = True
                for annot in page.annots():
                    if marker in (annot.info.get("content") or ""):
                        found = True
        if found:
            hits.append(index)
    return hits


def _assert_reopens_cleanly(path: Path) -> None:
    with fitz.open(str(path)) as doc:
        assert not doc.is_repaired, "the saved file needed a repair to open"


def _spy(model: PDFModel, monkeypatch, name: str) -> list[tuple]:
    calls: list[tuple] = []
    original = getattr(model, name)

    def _wrapper(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(model, name, _wrapper)
    return calls


def _note_xref(model: PDFModel) -> int:
    notes = [a for a in model.tools.annotation.get_all_annotations() if a["kind"] == "note"]
    assert len(notes) == 1
    return int(notes[0]["xref"])


# ---------------------------------------------------------------- (a) sticky note text


def test_editing_a_saved_note_drops_its_old_text_from_every_revision(tmp_path, monkeypatch) -> None:
    path = _write_note_pdf(tmp_path / "note.pdf")
    assert _revisions_holding(path, OLD_NOTE) == [0], "positive control: the scan sees the note"
    model = _open(path)
    try:
        gate = _spy(model, monkeypatch, "_signature_loss_gate")
        xref = _note_xref(model)
        epoch = model.xref_epoch
        assert model.tools.annotation.update_annotation(xref, NEW_NOTE)
        model.save_as(str(path))
        assert gate == [], "no signature prompt for an unsigned document"
        assert model.secure_save_required is False, "no secure latch (no renumbering)"
        assert model.xref_epoch == epoch, "the numbering is kept"
        assert _note_xref(model) == xref, "the note keeps its xref"
        assert model.tools.annotation.update_annotation(xref, NEW_NOTE + " again")
    finally:
        model.close()
    assert _revisions_holding(path, OLD_NOTE) == []
    assert _revisions_holding(path, NEW_NOTE) != []
    _assert_reopens_cleanly(path)


def test_moving_a_saved_note_takes_the_full_save(tmp_path, monkeypatch) -> None:
    path = _write_note_pdf(tmp_path / "move.pdf")
    original = path.read_bytes()
    model = _open(path)
    try:
        full = _spy(model, monkeypatch, "_full_save_to_path")
        xref = _note_xref(model)
        assert model.tools.annotation.move_annotation(xref, fitz.Rect(400, 400, 420, 420))
        model.save_as(str(path))
        assert full == [(str(path),)]
    finally:
        model.close()
    assert not path.read_bytes().startswith(original)
    assert len(_revisions(path.read_bytes())) == 1


# ---------------------------------------------------------------- (b) true-text edit


def _block(model: PDFModel, probe: str):
    return next(b for b in model.block_manager.get_blocks(0) if probe in (b.text or ""))


def test_a_true_text_edit_drops_the_replaced_text_from_every_revision(tmp_path, monkeypatch) -> None:
    path = _write_tier0_pdf(tmp_path / "tier0.pdf")
    assert _revisions_holding(path, TARGET) == [0], "positive control: the scan sees the text"
    model = _open(path)
    try:
        gate = _spy(model, monkeypatch, "_signature_loss_gate")
        epoch = model.xref_epoch
        block = _block(model, TARGET)
        result = model.edit_text(1, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text)
        assert result is EditTextResult.SUCCESS
        model.save_as(str(path))
        assert gate == []
        assert model.secure_save_required is False
        assert model.xref_epoch == epoch
    finally:
        model.close()
    assert _revisions_holding(path, TARGET) == []
    with fitz.open(str(path)) as doc:
        text = doc[0].get_text()
    assert REPLACEMENT in text and DOWNSTREAM in text
    _assert_reopens_cleanly(path)


def test_undoing_a_saved_text_edit_drops_the_saved_edit(tmp_path) -> None:
    """Undo after a save overwrites content that is on disk now (the edit)."""
    path = _write_tier0_pdf(tmp_path / "undo.pdf")
    model = _open(path)
    try:
        block = _block(model, TARGET)
        command = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=REPLACEMENT,
            font=block.font,
            size=block.size,
            color=block.color,
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=block.text,
        )
        model.command_manager.execute(command)
        assert command.result is EditTextResult.SUCCESS
        model.save_as(str(path))
        assert model.command_manager.undo()
        model.save_as(str(path))
    finally:
        model.close()
    assert _revisions_holding(path, REPLACEMENT) == []
    with fitz.open(str(path)) as doc:
        assert TARGET in doc[0].get_text()
    _assert_reopens_cleanly(path)


# ---------------------------------------------------------------- (c) textbox marker payloads


@pytest.mark.parametrize("new_text", ["", "replaced words"], ids=["emptied", "rewritten"])
def test_marker_sync_drops_the_old_payload_from_every_revision(tmp_path, new_text) -> None:
    from model.pdf_object_ops import sync_textbox_markers_after_text_edit

    path = tmp_path / "box.pdf"
    rect = _write_textbox_pdf(path)
    payload_marker = f'"text":"{BOX_TEXT}"'
    assert _revisions_holding(path, payload_marker) != [], "positive control"
    model = _open(path)
    try:
        sync_textbox_markers_after_text_edit(
            model, 1, member_rects=[fitz.Rect(rect)], source_text=BOX_TEXT, new_text=new_text
        )
        assert _payload_texts_live(model) == ([] if not new_text else [new_text])
        model.save_as(str(path))
    finally:
        model.close()
    assert _revisions_holding(path, payload_marker) == []
    assert _payload_texts(path) == ([] if not new_text else [new_text])
    _assert_reopens_cleanly(path)


def _payload_texts_live(model: PDFModel) -> list[str]:
    texts: list[str] = []
    for annot in model.doc[0].annots():
        try:
            payload = json.loads(annot.info.get("content") or "")
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("kind") == "textbox":
            texts.append(str(payload.get("text")))
    return texts


def test_moving_a_saved_textbox_takes_the_full_save(tmp_path, monkeypatch) -> None:
    path = tmp_path / "boxmove.pdf"
    rect = _write_textbox_pdf(path)
    model = _open(path)
    try:
        hit = model.get_object_info_at_point(1, fitz.Point(rect.x0 + 5, rect.y0 + 5))
        assert hit is not None and hit.object_kind == "textbox"
        full = _spy(model, monkeypatch, "_full_save_to_path")
        assert model.move_object(
            MoveObjectRequest(
                object_id=hit.object_id,
                object_kind=hit.object_kind,
                source_page=1,
                destination_page=1,
                destination_rect=fitz.Rect(rect) + (0, 200, 0, 200),
            )
        )
        model.save_as(str(path))
        assert full == [(str(path),)]
    finally:
        model.close()
    assert len(_revisions(path.read_bytes())) == 1
    _assert_reopens_cleanly(path)


# ---------------------------------------------------------------- (d) a removed watermark

WATERMARK = "WMSECRET77"


def test_removing_a_saved_watermark_drops_it_from_every_revision(tmp_path, monkeypatch) -> None:
    """Without a watermark left, the save hands no clone and the live document
    (watermark ink stripped at open, attachment cleared) went out as an append."""
    path = tmp_path / "wm.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(str(path), garbage=0)
    doc.close()
    model = _open(path)
    try:
        model.tools.watermark.add_watermark([1], WATERMARK)
        model.save_as(str(path))
    finally:
        model.close()
    assert _revisions_holding(path, WATERMARK) != [], "positive control: the saved watermark is seen"
    model = _open(path)
    try:
        gate = _spy(model, monkeypatch, "_signature_loss_gate")
        (watermark,) = model.tools.watermark.get_watermarks()
        assert model.tools.watermark.remove_watermark(watermark["id"])
        model.save_as(str(path))
        assert gate == []
    finally:
        model.close()
    assert _revisions_holding(path, WATERMARK) == []
    _assert_reopens_cleanly(path)


# ---------------------------------------------------------------- (d) page straighten

PAGE_TEXT = "STRAIGHT-PAGE-SECRET-4417"


def test_straightening_a_page_drops_its_old_text_and_note_from_every_revision(
    tmp_path, monkeypatch
) -> None:
    """Straighten replaces the page with a raster and deletes the old page (its
    vector text and its sticky note); an append kept both in revision 0."""
    path = tmp_path / "straighten.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), PAGE_TEXT, fontsize=12.0)
    page.add_text_annot((300, 300), OLD_NOTE)
    doc.new_page().insert_text((72, 100), "second page", fontsize=12.0)
    doc.save(str(path), garbage=0)
    doc.close()
    assert _revisions_holding(path, PAGE_TEXT) == [0], "positive control: the scan sees the text"
    assert _revisions_holding(path, OLD_NOTE) == [0], "positive control: the scan sees the note"
    model = _open(path)
    try:
        gate = _spy(model, monkeypatch, "_signature_loss_gate")
        epoch = model.xref_epoch
        assert model.straighten_page(1, angle_degrees=3.0)
        model.save_as(str(path))
        assert gate == [], "no signature prompt for an unsigned document"
        assert model.secure_save_required is False, "no secure latch (no renumbering)"
        assert model.xref_epoch == epoch, "the numbering is kept"
    finally:
        model.close()
    assert _revisions_holding(path, PAGE_TEXT) == []
    assert _revisions_holding(path, OLD_NOTE) == []
    _assert_reopens_cleanly(path)
    with fitz.open(str(path)) as saved:
        assert saved.page_count == 2
        assert saved[0].get_images(), "the straightened raster survives"
        assert "second page" in saved[1].get_text()


# ---------------------------------------------------------------- what stays an append


def test_an_unedited_save_back_stays_the_cheap_append(tmp_path, monkeypatch) -> None:
    path = _write_note_pdf(tmp_path / "plain.pdf")
    original = path.read_bytes()
    model = _open(path)
    try:
        full = _spy(model, monkeypatch, "_full_save_to_path")
        model.save_as(str(path))
        assert full == []
    finally:
        model.close()
    assert path.read_bytes().startswith(original)


def test_a_note_added_and_edited_in_this_session_stays_an_append(tmp_path, monkeypatch) -> None:
    """Nothing on disk is replaced: the new note's own objects are in no revision."""
    path = _write_note_pdf(tmp_path / "add.pdf")
    original = path.read_bytes()
    model = _open(path)
    try:
        full = _spy(model, monkeypatch, "_full_save_to_path")
        xref = model.tools.annotation.add_annotation(1, fitz.Point(100, 400), "fresh note")
        assert model.tools.annotation.update_annotation(xref, "fresh note, edited")
        assert model.tools.annotation.move_annotation(xref, fitz.Rect(120, 420, 140, 440))
        model.save_as(str(path))
        assert full == []
    finally:
        model.close()
    assert path.read_bytes().startswith(original)


def test_after_the_full_save_the_next_unedited_save_appends_again(tmp_path, monkeypatch) -> None:
    path = _write_note_pdf(tmp_path / "again.pdf")
    model = _open(path)
    try:
        xref = _note_xref(model)
        assert model.tools.annotation.update_annotation(xref, NEW_NOTE)
        model.save_as(str(path))
        after_first = path.read_bytes()
        full = _spy(model, monkeypatch, "_full_save_to_path")
        model.save_as(str(path))
        assert full == []
    finally:
        model.close()
    assert path.read_bytes().startswith(after_first)


def test_a_failed_full_save_keeps_the_requirement(tmp_path, monkeypatch) -> None:
    path = _write_note_pdf(tmp_path / "fail.pdf")
    model = _open(path)
    try:
        xref = _note_xref(model)
        assert model.tools.annotation.update_annotation(xref, NEW_NOTE)

        def _boom(_path: str) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(model, "_full_save_to_path", _boom)
        with pytest.raises(OSError):
            model.save_as(str(path))
        monkeypatch.undo()
        model.save_as(str(path))
    finally:
        model.close()
    assert _revisions_holding(path, OLD_NOTE) == []


def test_a_signed_document_keeps_its_append_only_save(tmp_path, monkeypatch) -> None:
    """GUARD (green before and after): signed documents are out of scope; the
    signed revision stays a byte prefix and nothing asks the user."""
    path = _write_note_pdf(tmp_path / "signed.pdf", signed=True)
    original = path.read_bytes()
    model = _open(path)
    try:
        gate = _spy(model, monkeypatch, "_signature_loss_gate")
        full = _spy(model, monkeypatch, "_full_save_to_path")
        xref = _note_xref(model)
        assert model.tools.annotation.update_annotation(xref, NEW_NOTE)
        model.save_as(str(path))
        assert gate == [] and full == []
    finally:
        model.close()
    assert path.read_bytes().startswith(original)
