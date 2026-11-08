"""Full saves write object streams, without the unreachable objects (CF17 size).

A ``garbage=1`` full save (the CF17 in-place rewrite and every unsigned Save
As) wrote every object as a top-level ``N 0 obj``: a file that came in with
object streams grew by half (``pdf.pdf`` 32.5 MB -> 50.5 MB).  The full save
now passes ``use_objstms=1``.  MuPDF's ``garbage=1`` + ``use_objstms=1`` in ONE
write packs the unreachable objects into the object stream as well (their xref
entry reads free, their bytes are still in the file), which would put a deleted
note's text back on disk; and it adds the containers to the LIVE document.  So
the pruned ``garbage=1`` serialization is reopened and that copy is written
with ``garbage=0`` + ``use_objstms=1``: the numbering and the epoch are kept,
the live document is never touched, and nothing unreachable reaches the file.

``restore_page_graph`` must also never overwrite a container (an object or
cross-reference stream) the reopened file holds at a number a snapshot taken
on a shorter table uses: that slot is no longer free.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import fitz
import pytest

from model.page_snapshot import PageSnapshotStale, capture_page_graph, restore_page_graph
from model.pdf_model import PDFModel

MARKER = "OBJSTM-UNREACHABLE-MARKER-40417"
USER_PW = "user-secret"


def _make_pdf(path: Path, *, encrypted: bool = False) -> Path:
    """Three text pages with a saved note each, a classic xref table (no object streams)."""
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 120), f"body text {index}")
        page.add_text_annot(fitz.Point(40 + 60 * index, 50), f"note {index}").update()
    kwargs: dict = {"garbage": 0}
    if encrypted:
        kwargs.update(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-secret", user_pw=USER_PW,
                      permissions=int(fitz.PDF_PERM_PRINT))
    doc.save(str(path), **kwargs)
    doc.close()
    data = path.read_bytes()
    assert b"/ObjStm" not in data and b"\nxref" in data, "fixture: a classic table"
    return path


def _needle_in_file(path: Path, needle: str) -> bool:
    """``needle`` in the raw bytes or in any inflatable stream (object streams included)."""
    data = path.read_bytes()
    raw = needle.encode("ascii")
    if raw in data:
        return True
    position = 0
    while True:
        start = data.find(b"stream", position)
        if start < 0:
            return False
        position = start + len(b"stream")
        try:
            if raw in zlib.decompressobj().decompress(data[position:].lstrip(b"\r\n")):
                return True
        except zlib.error:
            continue


def _spy_full_saves(model: PDFModel, monkeypatch) -> list[str]:
    calls: list[str] = []
    original = model._full_save_to_path

    def _spy(path: str):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(model, "_full_save_to_path", _spy)
    return calls


def _notes(model: PDFModel) -> list[tuple[int, str]]:
    return [(int(n["xref"]), n["text"]) for n in model.tools.annotation.get_all_annotations()]


def _file_notes(path: Path, password: str | None = None) -> list[tuple[int, str]]:
    doc = fitz.open(str(path))
    try:
        if password is not None:
            assert doc.authenticate(password)
        assert not doc.is_repaired, "the saved file must open without a repair"
        return [(annot.xref, annot.info.get("content", "")) for page in doc for annot in page.annots()]
    finally:
        doc.close()


def _add_unreachable_marker(model: PDFModel) -> int:
    """An object nothing refers to, holding ``MARKER`` (a deleted / replaced object)."""
    xref = model.doc.get_new_xref()
    model.doc.update_object(xref, f"<< /Type /Annot /Subtype /Text /Contents ({MARKER}) >>")
    return xref


def _assert_conformant(path: Path) -> None:
    from model.pdf_validator import check_pdf_conformance

    assert check_pdf_conformance(str(path)) == []


def test_in_place_full_save_packs_object_streams_without_unreachable_objects(
    tmp_path: Path, monkeypatch
) -> None:
    path = _make_pdf(tmp_path / "notes.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        full_saves = _spy_full_saves(model, monkeypatch)
        notes = _notes(model)
        epoch = model.xref_epoch
        _add_unreachable_marker(model)
        model.note_saved_content_replaced()
        model.save_as(str(path))
        assert full_saves == [str(path)], "the CF17 full save must run"
        assert model.secure_save_required is False
        assert model.xref_epoch == epoch, "the numbering is kept"
        assert _notes(model) == notes, "every note keeps its xref"

        # The reopened handle still appends a pure addition.
        model.tools.annotation.add_annotation(1, fitz.Point(300, 50), "added after")
        model.save_as(str(path))
        assert full_saves == [str(path)], "the next unedited save appends"
    finally:
        model.close()

    data = path.read_bytes()
    assert data.count(b"%%EOF") == 2
    first_revision = data[: data.find(b"%%EOF")]
    assert b"/ObjStm" in first_revision, "the full save must write object streams"
    assert not _needle_in_file(path, MARKER), "an unreachable object must not reach the file"
    file_notes = _file_notes(path)
    assert set(notes) <= set(file_notes), "the saved notes keep their xrefs"
    assert sorted(text for _x, text in file_notes) == ["added after", "note 0", "note 1", "note 2"]
    _assert_conformant(path)


def test_save_as_full_save_packs_object_streams_and_leaves_the_live_doc_alone(
    tmp_path: Path, monkeypatch
) -> None:
    source = _make_pdf(tmp_path / "notes.pdf")
    output = tmp_path / "copy.pdf"
    original = source.read_bytes()
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        full_saves = _spy_full_saves(model, monkeypatch)
        notes = _notes(model)
        epoch = model.xref_epoch
        orphan = _add_unreachable_marker(model)
        length = model.doc.xref_length()
        model.save_as(str(output))
        assert full_saves == [str(output)]
        assert model.xref_epoch == epoch
        assert model.doc.xref_length() == length, "no container was added to the live document"
        assert MARKER in model.doc.xref_object(orphan), "the live document keeps its objects (undo)"
        assert _notes(model) == notes
    finally:
        model.close()

    assert source.read_bytes() == original, "Save As leaves the source untouched"
    assert b"/ObjStm" in output.read_bytes()
    assert not _needle_in_file(output, MARKER)
    assert _file_notes(output) == notes
    _assert_conformant(output)


def test_encrypted_full_save_keeps_the_encryption_with_object_streams(
    tmp_path: Path, monkeypatch
) -> None:
    path = _make_pdf(tmp_path / "encrypted.pdf", encrypted=True)
    model = PDFModel()
    try:
        model.open_pdf(str(path), password=USER_PW)
        original_permissions = model.doc.permissions
        original_encryption = model.doc.metadata["encryption"]
        full_saves = _spy_full_saves(model, monkeypatch)
        notes = _notes(model)
        epoch = model.xref_epoch
        _add_unreachable_marker(model)
        model.note_saved_content_replaced()
        model.save_as(str(path))
        assert full_saves == [str(path)]
        assert model.xref_epoch == epoch
        assert _notes(model) == notes
    finally:
        model.close()

    assert b"/ObjStm" in path.read_bytes()
    doc = fitz.open(str(path))
    try:
        assert doc.needs_pass, "the encryption must survive the save"
        assert doc.authenticate(USER_PW)
        assert doc.permissions == original_permissions
        assert doc.metadata["encryption"] == original_encryption
        assert doc.authenticate("owner-secret") & 4
        assert "body text 1" in doc[1].get_text()
        for xref in range(1, doc.xref_length()):
            try:
                assert MARKER not in doc.xref_object(xref)
            except RuntimeError:
                continue
    finally:
        doc.close()
    assert _file_notes(path, USER_PW) == notes


def test_secure_full_save_packs_object_streams(tmp_path: Path, monkeypatch) -> None:
    """The garbage=4 rewrite (renumbers, sanitises) takes object streams as well."""
    path = _make_pdf(tmp_path / "secure.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_unreachable_marker(model)
        model.secure_save_required = True
        model.save_as(str(path))
        assert full_saves == [str(path)]
        assert sorted(text for _x, text in _notes(model)) == ["note 0", "note 1", "note 2"]
    finally:
        model.close()

    assert b"/ObjStm" in path.read_bytes()
    assert not _needle_in_file(path, MARKER)
    assert sorted(text for _x, text in _file_notes(path)) == ["note 0", "note 1", "note 2"]
    _assert_conformant(path)


# ------------------------------------------------ page snapshots vs containers


def test_page_snapshot_restore_never_overwrites_a_container(tmp_path: Path) -> None:
    """A redo whose snapshot was taken on a longer table than the one a full
    save reopened: its stream record sits at the number the save gave an
    object stream.  Overwriting that container would orphan every object
    packed in it, so the restore must refuse (stale) and change nothing."""
    base = tmp_path / "base.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=300).insert_text((40, 120), "body text")
    doc.save(str(base), garbage=0)
    doc.close()

    longer = fitz.open(str(base))
    try:
        length = longer.xref_length()
        extra = longer.get_new_xref()
        assert extra == length
        longer.update_object(extra, "<<>>")
        longer.update_stream(extra, b"0 0 m 10 10 l S")
        page_xref = longer.page_xref(0)
        _kind, contents = longer.xref_get_key(page_xref, "Contents")
        longer.xref_set_key(page_xref, "Contents", f"[{contents} {extra} 0 R]")
        snapshot = capture_page_graph(longer, 0, xref_epoch=7)
    finally:
        longer.close()

    shorter = fitz.open(str(base))
    packed = tmp_path / "packed.pdf"
    try:
        shorter.save(str(packed), garbage=0, use_objstms=1)
    finally:
        shorter.close()
    live = fitz.open(str(packed))
    try:
        assert "/Type/ObjStm" in live.xref_object(extra, compressed=True), "fixture: a container at the record's number"
        before = live.xref_object(extra, compressed=True)
        with pytest.raises(PageSnapshotStale):
            restore_page_graph(live, 0, snapshot, xref_epoch=7)
        assert live.xref_object(extra, compressed=True) == before
        assert "body text" in live[0].get_text()
    finally:
        live.close()


def test_textbox_redo_after_pruning_and_packing_preserves_document(tmp_path):
    from model.edit_commands import AddTextboxCommand

    path = _make_pdf(tmp_path / "redo.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        command = AddTextboxCommand(
            model=model, page_num=1, visual_rect=fitz.Rect(50, 160, 350, 250),
            text="redo text", font="helv", size=12.0, color=(0, 0, 0),
            before_page_snapshot_bytes=model._capture_page_snapshot_strict(0),
        )
        model.command_manager.execute(command)
        assert "redo text" in model.doc[0].get_text()
        assert model.command_manager.undo() is True
        model.save_as(str(path))
        assert "redo text" not in model.doc[0].get_text()
        assert model.command_manager.redo() is True
        assert "redo text" in model.doc[0].get_text()
        model.save_as(str(path))
    finally:
        model.close()
    _assert_conformant(path)
    with fitz.open(path) as saved:
        assert not saved.is_repaired
        assert "redo text" in saved[0].get_text()


@pytest.mark.parametrize("in_place", [False, True])
def test_packed_save_failure_keeps_target_live_edits_and_cleans_stages(tmp_path, monkeypatch, in_place):
    path = _make_pdf(tmp_path / "source.pdf")
    output = path if in_place else tmp_path / "existing.pdf"
    if not in_place:
        output.write_bytes(b"existing user file")
    original_target = output.read_bytes()
    original_save = fitz.Document.save
    stages = []
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        note = model.tools.annotation.get_all_annotations()[0]
        model.tools.annotation.update_annotation(note["xref"], "unsaved edit")
        original_private = model.private_temp_file

        def private_file(*args, **kwargs):
            result = original_private(*args, **kwargs)
            stages.append(Path(result))
            return result

        def fail_packed(doc, target, *args, **kwargs):
            if kwargs.get("use_objstms"):
                Path(target).write_bytes(b"partial output")
                raise OSError("injected packed write failure")
            return original_save(doc, target, *args, **kwargs)

        monkeypatch.setattr(model, "private_temp_file", private_file)
        monkeypatch.setattr(fitz.Document, "save", fail_packed)
        with pytest.raises(OSError, match="injected"):
            model.save_as(str(output))
        assert output.read_bytes() == original_target
        assert any(n["text"] == "unsaved edit" for n in model.tools.annotation.get_all_annotations())
        assert all(not stage.exists() for stage in stages)
        assert not list(output.parent.glob(f".{output.name}.*"))
        monkeypatch.setattr(fitz.Document, "save", original_save)
        model.save_as(str(output))
    finally:
        model.close()
    with fitz.open(output) as saved:
        assert any(a.info["content"] == "unsaved edit" for page in saved for a in page.annots())
