"""A deleted note must not survive in the saved file (CF5).

An in-place save of an unsigned file-backed document is an incremental append.
MuPDF writes the session objects it still holds, reachable or not, and the
earlier revisions stay in the file, so a deleted Text annotation's ``/Contents``
was still readable from the bytes on disk although the reopened file listed no
annotation.  Deleting an annotation on an UNSIGNED document now records the
CF17 requirement (``note_saved_content_replaced``), which makes the next save
the numbering-preserving ``garbage=1`` full rewrite: the unreachable note is
dropped, every other xref and the epoch are kept (no ``secure_save_required``
latch, no renumbering).  A digitally signed document is left on the append-only save
(the latch would make every later save ask to break the signature).  There
(owner decision, option b) deleting a note this session created overwrites its
now-unreachable objects -- the note, its /Popup, its /AP stream -- with empty
objects ("nulls" them; never frees them, which an xref-stream base would leave
as holes), so the append (in place, or the replay onto the signed source)
carries none of its text, without a dialog, with the signature intact.  "This session created" is
measured against the table the session OPENED, so a note saved into a revision
this session appended is nulled in the next one too.  A note already in the
opened file (the signed revision, or a revision an earlier session appended)
keeps its old bytes, and a note saved earlier this session keeps the bytes of
that earlier append: those residuals are accepted.
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

import fitz
import pytest

from model.pdf_model import PDFModel

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import test_save_prunes_orphans as spo  # noqa: E402

MARKER = "CF5-DELETED-NOTE-MARKER-50917"


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=400, height=300).insert_text((40, 120), "body text")
    doc.save(path)
    doc.close()


def _marker_in_file(path: Path) -> bool:
    """The marker anywhere in the file: raw bytes, or any inflatable stream."""
    data = path.read_bytes()
    needle = MARKER.encode("ascii")
    if needle in data:
        return True
    position = 0
    while True:
        start = data.find(b"stream", position)
        if start < 0:
            return False
        position = start + len(b"stream")
        body = data[position:].lstrip(b"\r\n")
        try:
            if needle in zlib.decompressobj().decompress(body):
                return True
        except zlib.error:
            continue


def _annotation_count(path: Path) -> int:
    doc = fitz.open(path)
    try:
        return sum(len(page.annot_xrefs()) for page in doc)
    finally:
        doc.close()


def test_note_added_and_deleted_in_one_session_is_not_in_the_in_place_save(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        assert model.tools.annotation.delete_annotation(xref) is True
        model.save_as(str(path))
    finally:
        model.close()

    assert not _marker_in_file(path)
    assert _annotation_count(path) == 0


def test_note_saved_earlier_then_deleted_is_not_in_the_in_place_save(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        model.save_as(str(path))
    finally:
        model.close()
    assert _marker_in_file(path)  # the note really reached the disk

    model = PDFModel()
    try:
        model.open_pdf(str(path))
        notes = model.tools.annotation.get_all_annotations()
        assert [note["text"] for note in notes] == [MARKER]
        assert model.tools.annotation.delete_annotation(notes[0]["xref"]) is True
        model.save_as(str(path))
    finally:
        model.close()

    assert not _marker_in_file(path)
    assert _annotation_count(path) == 0


def test_note_deleted_then_saved_as_new_path_is_not_in_the_file(tmp_path: Path) -> None:
    source = tmp_path / "notes.pdf"
    output = tmp_path / "notes-copy.pdf"
    _make_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        model.save_as(str(source))
    finally:
        model.close()

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        xref = model.tools.annotation.get_all_annotations()[0]["xref"]
        assert model.tools.annotation.delete_annotation(xref) is True
        model.save_as(str(output))
    finally:
        model.close()

    assert not _marker_in_file(output)
    assert _annotation_count(output) == 0


def test_deleting_a_note_takes_the_numbering_kept_full_save_not_the_secure_latch(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        assert model.tools.annotation.delete_annotation(999999) is False
        assert model.tools.annotation.delete_annotation(0) is False
        assert model.secure_save_required is False
        assert model.saved_content_replaced is False

        assert model.tools.annotation.delete_annotation(xref) is True
        assert model.secure_save_required is False, "no renumbering garbage=4 latch (CF17 path)"
        assert model.saved_content_replaced is True, "the next save is the garbage=1 full save"
    finally:
        model.close()


def _make_pdf_with_three_saved_notes(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((40, 120), "body text")
    page.add_text_annot(fitz.Point(40, 50), MARKER, icon="Note").update()
    for index, x in enumerate((140, 240), start=2):
        page.add_text_annot(fitz.Point(x, 50), f"note {index}", icon="Note").update()
    doc.save(path)
    doc.close()


@pytest.mark.parametrize("target", ["in_place", "save_as"])
def test_deleting_a_saved_note_keeps_the_other_notes_xrefs_across_the_save(
    tmp_path: Path, monkeypatch, target: str
) -> None:
    """The delete's save is the numbering-preserving full save: the deleted
    note's /Contents leaves the file, the other notes keep their xrefs (live and
    on disk), the epoch does not move and no secure latch is set."""
    path = tmp_path / "notes.pdf"
    _make_pdf_with_three_saved_notes(path)
    output = path if target == "in_place" else tmp_path / "notes-copy.pdf"
    assert _marker_in_file(path), "fixture: the note is on disk"
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        full_saves = spo._spy_full_saves(model, monkeypatch)
        notes = model.tools.annotation.get_all_annotations()
        doomed = next(n["xref"] for n in notes if n["text"] == MARKER)
        kept = [(n["xref"], n["text"]) for n in notes if n["text"] != MARKER]
        epoch = model.xref_epoch
        assert model.tools.annotation.delete_annotation(doomed) is True
        model.save_as(str(output))
        assert full_saves == [str(output)], "the save is the CF17 full save"
        assert model.secure_save_required is False
        assert model.xref_epoch == epoch, "no renumbering"
        assert [(n["xref"], n["text"]) for n in model.tools.annotation.get_all_annotations()] == kept
    finally:
        model.close()

    assert not _marker_in_file(output), "the deleted note's /Contents must not be in the saved bytes"
    assert output.read_bytes().count(b"%%EOF") == 1
    doc = fitz.open(output)
    try:
        assert not doc.is_repaired
        assert [(a.xref, a.info["content"]) for page in doc for a in page.annots()] == kept
    finally:
        doc.close()


# ------------------------------------------------ signed documents (option b)


@pytest.fixture(params=["xref_table", "xref_stream"])
def signed_shape(request) -> str:
    """The signed base's last xref section: a classic table, or an xref STREAM
    with object streams (PDF 1.5+, the usual shape of Acrobat- and Word-signed
    files), where MuPDF's incremental writer leaves a freed object out of every
    section instead of writing an explicit ``f`` entry."""
    return request.param


def _make_signed(path: Path, shape: str) -> Path:
    """``spo._make_signed_pdf`` as a classic xref table, or re-saved with object
    streams so its xref section is a cross-reference stream."""
    if shape == "xref_table":
        return spo._make_signed_pdf(path)
    base = spo._make_signed_pdf(path.with_name(f"table-{path.name}"))
    doc = fitz.open(base)
    try:
        doc.save(path, use_objstms=1, garbage=0)
    finally:
        doc.close()
    data = path.read_bytes()
    assert b"/ObjStm" in data and b"/XRef" in data and b"\nxref" not in data
    return path


def _guard_silent_save(model: PDFModel, monkeypatch) -> tuple[list[str], list[str]]:
    """Record every full save and every signature-loss gate the model takes."""
    full_saves = spo._spy_full_saves(model, monkeypatch)
    gates: list[str] = []
    original = model._signature_loss_gate

    def _gate(reason, *args, **kwargs):
        gates.append(reason)
        return original(reason, *args, **kwargs)

    monkeypatch.setattr(model, "_signature_loss_gate", _gate)
    return full_saves, gates


def _record_note(model: PDFModel, kind: str, mutate) -> None:
    """Record ``mutate`` as the controller's ``_record_annotation_mutation`` does."""

    def _run() -> list[int]:
        assert mutate() not in (False, None)
        return [1]

    spo._record_snapshot(model, _run, command_type=kind, description=kind)


def _note_texts(path: Path) -> list[str]:
    doc = fitz.open(path)
    try:
        assert not doc.is_repaired, "the saved file must open without a repair"
        return [annot.info.get("content", "") for page in doc for annot in page.annots()]
    finally:
        doc.close()


def _assert_signed_prefix_and_clean(path: Path, original: bytes, eof: int) -> None:
    data = path.read_bytes()
    assert data.startswith(original), "the signed revision stays an exact byte prefix"
    assert data.count(b"%%EOF") == eof
    assert not _marker_in_file(path), "the deleted session note must not reach the file"
    assert _note_texts(path) == []
    _assert_clean_structure(path)


def _assert_clean_structure(path: Path) -> None:
    """The overwritten (emptied) slots leave a file that opens unrepaired, can
    append again, passes the app's own conformance check, and has every slot
    below the trailer's /Size defined (no hole an xref stream left out)."""
    from model.pdf_validator import check_pdf_conformance

    doc = fitz.open(path)
    try:
        assert not doc.is_repaired
        assert doc.can_save_incrementally()
        for xref in range(1, doc.xref_length()):
            try:
                doc.xref_object(xref)
            except RuntimeError as exc:
                raise AssertionError(f"xref {xref} is in no xref section: {exc}") from None
    finally:
        doc.close()
    assert check_pdf_conformance(str(path)) == []


def _session_note_objects(model: PDFModel, xref: int) -> tuple[list[int], bytes]:
    """The note's own objects (annot, /Popup, /AP /N) and its appearance stream bytes."""
    doc = model.doc
    popup = int(doc.xref_get_key(xref, "Popup")[1].split()[0])
    ap = int(doc.xref_get_key(xref, "AP/N")[1].split()[0])
    return [xref, popup, ap], doc.xref_stream_raw(ap)


def _assert_objects_gone(path: Path, xrefs: list[int], ap_raw: bytes, original: bytes) -> None:
    """Each of the note's objects is an empty dictionary in the file (a stream:
    ``/Length 0`` and no data) -- defined, never a freed slot or a hole -- and
    its AP bytes are not appended."""
    assert ap_raw not in path.read_bytes()[len(original):]
    doc = fitz.open(path)
    try:
        for xref in xrefs:
            assert xref < doc.xref_length(), f"xref {xref} is beyond /Size"
            text = doc.xref_object(xref, compressed=True).strip()
            if doc.xref_is_stream(xref):
                assert text == "<</Length 0>>", f"stream xref {xref} still holds {text!r}"
                assert doc.xref_stream_raw(xref) == b""
            else:
                assert text == "<<>>", f"xref {xref} still holds {text!r}"
    finally:
        doc.close()


def test_session_note_deleted_on_a_signed_doc_is_not_in_the_in_place_save(
    tmp_path: Path, monkeypatch, signed_shape: str
) -> None:
    """(i) In-place save: an incremental append from the file-backed handle."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        objects, ap_raw = _session_note_objects(model, xref)
        assert model.tools.annotation.delete_annotation(xref) is True
        assert model.secure_save_required is False
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()

    _assert_signed_prefix_and_clean(path, original, eof=2)
    _assert_objects_gone(path, objects, ap_raw, original)


def test_session_note_deleted_on_a_signed_doc_is_not_in_the_save_as_copy(
    tmp_path: Path, monkeypatch, signed_shape: str
) -> None:
    """(ii) Save As: the live state is replayed onto a copy of the signed source."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    output = tmp_path / "signed-copy.pdf"
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        objects, ap_raw = _session_note_objects(model, xref)
        assert model.tools.annotation.delete_annotation(xref) is True
        assert model.secure_save_required is False
        model.save_as(str(output))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()

    assert path.read_bytes() == original, "Save As leaves the source untouched"
    _assert_signed_prefix_and_clean(output, original, eof=2)
    _assert_objects_gone(output, objects, ap_raw, original)


@pytest.mark.parametrize("order", ["delete_then_undo_redo", "undo_redo_then_delete"])
def test_session_note_deleted_on_a_signed_doc_across_undo_redo(
    tmp_path: Path, monkeypatch, order: str, signed_shape: str
) -> None:
    """(iii) Undo/redo installs an in-memory handle, so the save is the signed
    append replay.  ``undo_redo_then_delete`` deletes on that in-memory handle,
    where the session no longer knows the persisted table length."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    note = model.tools.annotation
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        xrefs: list[int] = []
        _record_note(model, "add_annotation", lambda: xrefs.append(note.add_annotation(1, fitz.Point(40, 50), MARKER)) or True)
        objects, ap_raw = _session_note_objects(model, xrefs[0])
        if order == "undo_redo_then_delete":
            model.command_manager.undo()
            model.command_manager.redo()
            assert model.doc.name != str(path), "redo must have left an in-memory handle"
            assert model.persisted_xref_length is None, "the delete must not know the table length"
            _record_note(model, "delete_annotation", lambda: note.delete_annotation(xrefs[0]))
        else:
            _record_note(model, "delete_annotation", lambda: note.delete_annotation(xrefs[0]))
            model.command_manager.undo()
            # Undoing the delete brings the note back intact.
            assert [n["text"] for n in note.get_all_annotations()] == [MARKER]
            model.command_manager.redo()
            assert model.doc.name != str(path), "redo must have left an in-memory handle"
        assert note.get_all_annotations() == []
        assert model.secure_save_required is False
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()

    _assert_signed_prefix_and_clean(path, original, eof=2)
    _assert_objects_gone(path, objects, ap_raw, original)


def test_signed_doc_keeps_appending_silently_after_a_nulled_note(
    tmp_path: Path, monkeypatch, signed_shape: str
) -> None:
    """The emptied slots must not make the saved file need a repair: the next
    edit + Ctrl+S must append again, without a dialog or a full rewrite."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        assert model.tools.annotation.delete_annotation(xref) is True
        model.save_as(str(path))
    finally:
        model.close()
    reopened = fitz.open(path)
    try:
        assert not reopened.is_repaired
        assert reopened.can_save_incrementally()
    finally:
        reopened.close()

    model = spo._open(path, incremental=True)
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        model.tools.annotation.add_annotation(1, fitz.Point(140, 50), "kept note")
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()
    data = path.read_bytes()
    assert data.startswith(original)
    assert data.count(b"%%EOF") == 3
    assert not _marker_in_file(path)
    assert _note_texts(path) == ["kept note"]
    _assert_clean_structure(path)


def _make_signed_pdf_with_note(path: Path) -> Path:
    """A signed PDF whose (only, signed) revision already carries a note with MARKER."""
    unsigned_note = spo._make_signed_pdf(path.with_name("base.pdf"))
    doc = fitz.open(unsigned_note)
    doc[0].add_text_annot(fitz.Point(40, 50), MARKER, icon="Note").update()
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize("handle", ["file_backed", "in_memory"])
def test_note_from_the_signed_revision_deleted_keeps_its_old_bytes(
    tmp_path: Path, monkeypatch, handle: str
) -> None:
    """Regression guard (accepted residual): a note that is part of the signed
    revision is removed from the latest revision only.  Its object in the signed
    bytes is the signed content and stays; it is not redefined in the append.
    ``in_memory`` deletes it on an undo/redo handle (the floor read from disk)."""
    path = _make_signed_pdf_with_note(tmp_path / "signed-note.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        if handle == "in_memory":
            _record_note(model, "update_annotation", lambda: model.tools.annotation.update_annotation(
                model.tools.annotation.get_all_annotations()[0]["xref"], MARKER))
            model.command_manager.undo()
            assert model.persisted_xref_length is None
        notes = model.tools.annotation.get_all_annotations()
        assert [n["text"] for n in notes] == [MARKER]
        xref = notes[0]["xref"]
        objects, _ap_raw = _session_note_objects(model, xref)
        assert model.tools.annotation.delete_annotation(xref) is True
        assert model.secure_save_required is False
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()

    data = path.read_bytes()
    assert data.startswith(original), "the signed revision stays an exact byte prefix"
    assert data.count(b"%%EOF") == 2
    assert MARKER.encode() in original  # EXPECTED: the signed revision keeps the old note
    tail = data[len(original):]
    assert MARKER.encode() not in tail
    for obj in objects:  # the base note's objects are neither redefined nor freed in the append
        assert f"\n{obj} 0 obj".encode() not in tail
    reopened = fitz.open(path)
    try:
        assert MARKER in reopened.xref_object(objects[0])
        for obj in objects[1:]:
            assert reopened.xref_object(obj).strip() != "null"
        assert "/Subtype/Popup" in reopened.xref_object(objects[1], compressed=True)
        assert reopened.xref_stream_raw(objects[2])  # the AP keeps its data
    finally:
        reopened.close()
    assert _note_texts(path) == []


def test_session_note_saved_then_deleted_keeps_its_appended_bytes(tmp_path: Path, monkeypatch) -> None:
    """Regression guard (accepted residual): a note saved into a revision this
    session appended is on disk; deleting it later removes it from the latest
    revision only, still without a dialog."""
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        model.save_as(str(path))
    finally:
        model.close()
    second = path.read_bytes()
    assert MARKER.encode() in second[len(original):]

    model = spo._open(path, incremental=True)
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        xref = model.tools.annotation.get_all_annotations()[0]["xref"]
        assert model.tools.annotation.delete_annotation(xref) is True
        assert model.secure_save_required is False
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()
    data = path.read_bytes()
    assert data.startswith(second)
    assert data.count(b"%%EOF") == 3
    assert MARKER.encode() not in data[len(second):]
    assert _note_texts(path) == []


@pytest.mark.parametrize("target", ["in_place", "save_as"])
def test_note_saved_then_deleted_in_one_session_saves_silently(
    tmp_path: Path, monkeypatch, target: str, signed_shape: str
) -> None:
    """Add, save, delete, save -- one session, no reopen.  The floor is the
    table the session opened, so the note now in the session's own appended
    revision is nulled in the next one: signature-safe, and the file must still
    open unrepaired and keep appending silently."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    output = path if target == "in_place" else tmp_path / "signed-copy.pdf"
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        model.save_as(str(output))
        saved = output.read_bytes()
        assert MARKER.encode() in saved[len(original):]
        xref = model.tools.annotation.get_all_annotations()[0]["xref"]
        assert model.tools.annotation.delete_annotation(xref) is True
        assert model.secure_save_required is False
        model.save_as(str(output))
        model.tools.annotation.add_annotation(1, fitz.Point(140, 50), "kept note")
        model.save_as(str(output))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()
    data = output.read_bytes()
    assert data.startswith(saved), "every revision this session wrote stays a byte prefix"
    assert data.count(b"%%EOF") == 4
    # Not re-appended; revision 2 keeps the bytes it already had (accepted residual).
    assert MARKER.encode() not in data[len(saved):]
    assert _note_texts(output) == ["kept note"]
    _assert_clean_structure(output)


def test_base_note_edited_this_session_then_deleted_keeps_the_edit_in_the_append(
    tmp_path: Path, monkeypatch
) -> None:
    """Pins an accepted residual: a note from the signed revision is not
    nulled, so text typed into it this session (its dictionary changed, then
    unreachable) is written by the append even though it was never on disk."""
    path = _make_signed_pdf_with_note(tmp_path / "signed-note.pdf")
    original = path.read_bytes()
    edited = "CF5-EDITED-BASE-NOTE-61127"
    model = spo._open(path, incremental=True)
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        xref = model.tools.annotation.get_all_annotations()[0]["xref"]
        assert model.tools.annotation.update_annotation(xref, edited) is True
        assert model.tools.annotation.delete_annotation(xref) is True
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()
    data = path.read_bytes()
    assert data.startswith(original)
    assert edited.encode() in data[len(original):]  # residual, see the docstring
    assert _note_texts(path) == []


def test_same_page_reply_deleted_with_the_session_note_is_nulled_too(tmp_path: Path, signed_shape: str) -> None:
    """PyMuPDF's ``delete_annot`` also removes the note's ``/IRT`` replies on its
    page; the session-created ones are nulled with the note."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    original = path.read_bytes()
    reply_marker = "CF5-REPLY-MARKER-77341"
    model = spo._open(path, incremental=True)
    try:
        doc = model.doc
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        reply = model.tools.annotation.add_annotation(1, fitz.Point(140, 50), reply_marker)
        doc.xref_set_key(reply, "IRT", f"{xref} 0 R")
        assert model.tools.annotation.delete_annotation(xref) is True
        assert model.tools.annotation.get_all_annotations() == []
        model.save_as(str(path))
    finally:
        model.close()
    _assert_signed_prefix_and_clean(path, original, eof=2)
    assert reply_marker.encode() not in path.read_bytes()


def _make_signed_pdf_with_inline_annot(path: Path, *, with_note: bool) -> Path:
    """A signed PDF whose page 1 ``/Annots`` also holds a DIRECT (inline) Link dict,
    which ``Page.annot_xrefs()`` reports as xref 0."""
    base = (
        _make_signed_pdf_with_note(path.with_name("inline-base.pdf"))
        if with_note
        else spo._make_signed_pdf(path.with_name("inline-base.pdf"))
    )
    doc = fitz.open(base)
    page_xref = doc.page_xref(0)
    _kind, annots = doc.xref_get_key(page_xref, "Annots")
    inner = annots.strip()[1:-1]
    doc.xref_set_key(
        page_xref,
        "Annots",
        f"[{inner} << /Type /Annot /Subtype /Link /Rect [0 0 10 10] /Border [0 0 0] >>]",
    )
    doc.save(path, garbage=0)
    doc.close()
    return path


@pytest.mark.parametrize("which", ["session_note", "base_note"])
def test_delete_on_a_signed_page_with_an_inline_annotation_dict_succeeds(
    tmp_path: Path, which: str
) -> None:
    """A direct annotation dictionary in ``/Annots`` (xref 0) must not make the
    signed-document pre-scan raise ``bad xref``: the delete has to happen."""
    from model.text_commit.inspect import document_has_a_signed_signature

    path = _make_signed_pdf_with_inline_annot(tmp_path / "inline.pdf", with_note=which == "base_note")
    model = spo._open(path, incremental=True)
    try:
        assert document_has_a_signed_signature(model.doc), "the signed branch must run"
        assert 0 in [x for x, _kind, _name in model.doc[0].annot_xrefs()], "an inline annot is present"
        note = model.tools.annotation
        if which == "session_note":
            xref = note.add_annotation(1, fitz.Point(40, 50), MARKER)
        else:
            xref = note.get_all_annotations()[0]["xref"]
        assert note.delete_annotation(xref) is True
        assert note.get_all_annotations() == []
        assert model.secure_save_required is False
    finally:
        model.close()


def test_delete_succeeds_when_the_nulling_step_fails(tmp_path: Path, monkeypatch) -> None:
    """The nulling is best effort: if it fails after ``delete_annot`` the delete
    still reports success (accepted residual: the note's text may be appended)."""
    import model.tools.annotation_tool as annotation_tool

    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    model = spo._open(path, incremental=True)
    try:
        note = model.tools.annotation
        xref = note.add_annotation(1, fitz.Point(40, 50), MARKER)

        def _boom(_doc):
            raise RuntimeError("synthetic reachability failure")

        monkeypatch.setattr(annotation_tool, "reachable_xrefs", _boom)
        assert note.delete_annotation(xref) is True
        assert note.get_all_annotations() == []
        assert model.secure_save_required is False
    finally:
        model.close()


def _needle_in_bytes(data: bytes, needle: str) -> bool:
    """``needle`` in ``data`` raw or inside any inflatable stream."""
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


@pytest.mark.parametrize("mode", ["in_place", "undo_redo"])
def test_session_note_saved_edited_then_deleted_does_not_append_the_edit(
    tmp_path: Path, monkeypatch, mode: str, signed_shape: str
) -> None:
    """A note this session created and saved is still not in the opened (signed)
    revision: text typed into it after that save, then deleted, must never reach
    the file (the floor is the opened revision's table, not the moving persisted
    watermark).  ``undo_redo`` saves through the signed append replay."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    original = path.read_bytes()
    edited = f"CF5-EDITED-NEVER-ON-DISK-{mode}"
    model = spo._open(path, incremental=True)
    note = model.tools.annotation
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        note.add_annotation(1, fitz.Point(40, 50), "first saved text")
        model.save_as(str(path))
        saved = path.read_bytes()
        xref = note.get_all_annotations()[0]["xref"]
        _record_note(model, "update_annotation", lambda: note.update_annotation(xref, edited))
        _record_note(model, "delete_annotation", lambda: note.delete_annotation(xref))
        if mode == "undo_redo":
            model.command_manager.undo()
            model.command_manager.redo()
            assert model.doc.name != str(path), "redo must have left an in-memory handle"
        assert note.get_all_annotations() == []
        assert model.secure_save_required is False
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()

    data = path.read_bytes()
    assert data.startswith(original), "the signed revision stays an exact byte prefix"
    assert data.startswith(saved), "the session's first revision stays a byte prefix"
    assert data.count(b"%%EOF") == 3
    assert not _needle_in_bytes(data[len(saved):], edited), "the edit never on disk must not be appended"
    assert _note_texts(path) == []
    _assert_clean_structure(path)
    reopened = fitz.open(path)
    try:
        if xref < reopened.xref_length():
            try:
                text = reopened.xref_object(xref)
            except RuntimeError:
                text = "null"
            assert text.strip() == "null" or "first saved text" not in text and edited not in text
    finally:
        reopened.close()


def test_undo_of_deleting_a_note_saved_this_session_restores_it(
    tmp_path: Path, monkeypatch, signed_shape: str
) -> None:
    """The opened-table floor also nulls a note already in a revision this session
    appended; undoing that delete must bring the note back whole, and the save
    after the undo must still append silently."""
    path = _make_signed(tmp_path / "signed.pdf", signed_shape)
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    note = model.tools.annotation
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        xrefs: list[int] = []
        _record_note(model, "add_annotation", lambda: xrefs.append(note.add_annotation(1, fitz.Point(40, 50), MARKER)) or True)
        model.save_as(str(path))
        xref = note.get_all_annotations()[0]["xref"]
        _record_note(model, "delete_annotation", lambda: note.delete_annotation(xref))
        assert note.get_all_annotations() == []
        model.command_manager.undo()
        assert [n["text"] for n in note.get_all_annotations()] == [MARKER]
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()

    data = path.read_bytes()
    assert data.startswith(original)
    # 2: the undone state equals the saved one, so nothing new was appended.
    assert data.count(b"%%EOF") in (2, 3)
    assert _note_texts(path) == [MARKER]
    _assert_clean_structure(path)
    reopened = fitz.open(path)
    try:
        annot = next(reopened[0].annots())
        assert reopened.xref_get_key(annot.xref, "Popup")[0] == "xref"
        ap = int(reopened.xref_get_key(annot.xref, "AP/N")[1].split()[0])
        assert reopened.xref_stream(ap)
        popup = int(reopened.xref_get_key(annot.xref, "Popup")[1].split()[0])
        assert "/Subtype/Popup" in reopened.xref_object(popup, compressed=True)
    finally:
        reopened.close()


def test_a_container_named_in_the_note_text_is_never_emptied(tmp_path: Path, monkeypatch) -> None:
    """The closure walk reads references out of the note's whole source, its
    /Contents string included.  A cross-reference stream (or object stream) the
    session's own append created sits above the floor and nothing refers to it,
    so typing ``N 0 R`` into a note must not get that container overwritten:
    an emptied object stream would orphan every object packed in it."""
    path = _make_signed(tmp_path / "signed.pdf", "xref_stream")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    note = model.tools.annotation
    try:
        full_saves, gates = _guard_silent_save(model, monkeypatch)
        note.add_annotation(1, fitz.Point(40, 50), "kept note")
        model.save_as(str(path))
        doc = model.doc
        floor = model.opened_xref_length
        containers = [
            x for x in range(floor, doc.xref_length())
            if "/Type/XRef" in doc.xref_object(x, compressed=True)
            or "/Type/ObjStm" in doc.xref_object(x, compressed=True)
        ]
        assert containers, "the append on an xref-stream base must have written a container"
        refs = " ".join(f"{x} 0 R" for x in containers)
        xref = note.add_annotation(1, fitz.Point(140, 50), f"{MARKER} see {refs}")
        assert note.delete_annotation(xref) is True
        for container in containers:
            source = doc.xref_object(container, compressed=True)
            assert "/Type/XRef" in source or "/Type/ObjStm" in source, f"container {container} became {source!r}"
        model.save_as(str(path))
        assert (full_saves, gates) == ([], [])
    finally:
        model.close()
    data = path.read_bytes()
    assert data.startswith(original)
    assert not _marker_in_file(path)
    assert _note_texts(path) == ["kept note"]
    _assert_clean_structure(path)


def test_session_note_kept_reachable_by_a_reply_elsewhere_is_not_nulled(tmp_path: Path) -> None:
    """A reply (``/IRT``) on another page survives the delete and keeps the note
    reachable: nulling the note would leave a live reply pointing at nothing,
    so it is left whole (and its text stays in the append: accepted)."""
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    model = spo._open(path, incremental=True)
    try:
        doc = model.doc
        xref = model.tools.annotation.add_annotation(1, fitz.Point(40, 50), MARKER)
        reply = model.tools.annotation.add_annotation(2, fitz.Point(140, 50), "reply")
        doc.xref_set_key(reply, "IRT", f"{xref} 0 R")
        assert model.tools.annotation.delete_annotation(xref) is True
        assert MARKER in doc.xref_object(xref)
        assert doc.xref_get_key(reply, "IRT") == ("xref", f"{xref} 0 R")
        assert [n["text"] for n in model.tools.annotation.get_all_annotations()] == ["reply"]
    finally:
        model.close()
