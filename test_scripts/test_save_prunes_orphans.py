"""Save-time pruning of unreachable objects (round 6, P3a; Model only, no Qt).

Owner report: a 222 KB copy of ecc-dwg.pdf saved as 5.9 MB after a rebuild +
Ctrl+Z.  ``restore_page_graph`` only writes the snapshot's own records back, so
the objects an undone command created stay in the live document, unreachable;
the non-secure full save used ``garbage=0`` and wrote every one of them, and an
incremental save would append them.  The fix prunes at the save chokepoint
(``garbage=1`` keeps the numbering, never mutates the live doc) and falls back
from an incremental save to the pruned full save only when the session-created
unreachable objects carry a large stream payload.

Fixtures are synthetic PDFs built in ``tmp_path`` (or copies made there); the
real-corpus files under ``test_files`` are only read or copied, never written.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from model.pdf_model import PDFModel  # noqa: E402

ORPHAN_BYTES = 200_000
SMALL_LIMIT = 20_000


# ---------------------------------------------------------------- helpers


def _make_pdf(path: Path, *, encrypted: bool = False) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hello world", fontsize=12.0)
    if encrypted:
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
            permissions=fitz.PDF_PERM_PRINT,
        )
    else:
        doc.save(str(path))
    doc.close()
    return path


def _open(
    path: Path, *, incremental: bool, password: str | None = None, secure: bool | None = None
) -> PDFModel:
    """``secure``, when given, sets the session's ``secure_save_required`` latch right
    after the open; left out, the latch stays whatever the open left it."""
    model = PDFModel()
    model.open_pdf(str(path), password=password)
    model.use_incremental_save = incremental
    if secure is not None:
        model.secure_save_required = secure
    return model


def _new_object(doc: fitz.Document, text: str) -> int:
    """Allocate a new xref, write ``text`` as its object and return the xref."""
    xref = doc.get_new_xref()
    doc.update_object(xref, text)
    return xref


def _add_orphan(doc: fitz.Document, size: int = ORPHAN_BYTES) -> int:
    xref = _new_object(doc, "<<>>")
    doc.update_stream(xref, b"A" * size, compress=False)
    return xref


def _spy_full_saves(model: PDFModel, monkeypatch) -> list[str]:
    calls: list[str] = []
    original = model._full_save_to_path

    def _spy(path: str):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(model, "_full_save_to_path", _spy)
    return calls


def _eof_count(path: Path) -> int:
    return path.read_bytes().count(b"%%EOF")


def _names_in(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


def _assert_encrypted_file_has_text(path: Path, needle: str) -> None:
    """The file on disk still needs the user password and carries ``needle``."""
    disk = fitz.open(str(path))
    try:
        assert disk.needs_pass, "the encryption must survive the save"
        assert disk.authenticate("user-secret")
        assert needle in disk[0].get_text()
    finally:
        disk.close()


def _assert_no_unreachable_in_file(path: Path) -> None:
    """The saved file at ``path`` holds no unreachable object."""
    from model.save_compaction import unreachable_xrefs

    saved = fitz.open(str(path))
    try:
        assert unreachable_xrefs(saved) == []
    finally:
        saved.close()


def _record_snapshot(
    model: PDFModel,
    mutate: Callable[[], list[int] | None],
    *,
    command_type: str,
    description: str,
    affected_pages: list[int] | None = None,
) -> None:
    """Record ``mutate`` the way ``PDFController`` records a page op: snapshot, mutate,
    snapshot, then a ``SnapshotCommand``.  ``affected_pages`` defaults to what
    ``mutate`` returns."""
    from model.edit_commands import SnapshotCommand

    before = model._capture_doc_snapshot()
    pages = mutate()
    after = model._capture_doc_snapshot()
    model.command_manager.record(
        SnapshotCommand(
            model=model,
            command_type=command_type,
            affected_pages=pages if affected_pages is None else affected_pages,
            before_bytes=before,
            after_bytes=after,
            description=description,
        )
    )


# ---------------------------------------------------------------- the module


def test_reachable_xrefs_edge_cases(tmp_path) -> None:
    from model.save_compaction import reachable_xrefs, unreachable_xrefs

    empty = fitz.open()  # catalog + page tree only
    try:
        assert unreachable_xrefs(empty) == []
        assert 1 in reachable_xrefs(empty)  # /Root
    finally:
        empty.close()

    doc = fitz.open(str(_make_pdf(tmp_path / "e.pdf")))
    try:
        length = doc.xref_length()
        assert unreachable_xrefs(doc) == []
        assert unreachable_xrefs(doc, from_xref=length) == []
        assert unreachable_xrefs(doc, from_xref=length + 50) == []

        a, b = doc.get_new_xref(), doc.get_new_xref()
        doc.update_object(a, f"<< /Other {b} 0 R >>")
        doc.update_object(b, f"<< /Other {a} 0 R >>")  # an orphan cycle
        assert unreachable_xrefs(doc) == [a, b]
        assert unreachable_xrefs(doc, from_xref=b) == [b]
        assert a not in reachable_xrefs(doc) and b not in reachable_xrefs(doc)

        _new_object(doc, "<< /Type /ObjStm /N 0 /First 0 >>")
        _new_object(doc, "<< /Type /XRef >>")
        _new_object(doc, "<< /Linearized 1 /L 100 >>")
        _new_object(doc, "null")
        reported = unreachable_xrefs(doc)
        assert reported == [a, b]  # ObjStm / XRef / Linearized / null never reported
    finally:
        doc.close()


def test_reachability_follows_trailer_info_and_encrypt_refs(tmp_path) -> None:
    from model.save_compaction import reachable_xrefs

    path = _make_pdf(tmp_path / "enc.pdf", encrypted=True)
    doc = fitz.open(str(path))
    try:
        assert doc.authenticate("user-secret")
        reachable = reachable_xrefs(doc)
        trailer = doc.pdf_trailer()
        refs = {int(m) for m in re.findall(r"(\d+)\s+\d+\s+R", trailer)}
        assert refs, "the fixture trailer must carry /Root, /Info or /Encrypt refs"
        assert refs <= reachable
        assert "Encrypt" in trailer
    finally:
        doc.close()


def test_the_scan_is_bounded_by_xref_length_not_the_stale_trailer_size(tmp_path) -> None:
    from model.save_compaction import unreachable_xrefs

    doc = fitz.open(str(_make_pdf(tmp_path / "s.pdf")))
    try:
        # The in-memory trailer keeps the /Size it was opened with.
        trailer_size = int(doc.pdf_trailer().split("/Size")[1].split()[0])
        orphans = [_add_orphan(doc, 10) for _ in range(3)]
        assert max(orphans) >= trailer_size  # beyond the stale /Size
        assert unreachable_xrefs(doc) == orphans
    finally:
        doc.close()


def test_orphan_fallback_threshold_constant_is_64_kib() -> None:
    from model.save_compaction import ORPHAN_FALLBACK_MIN_BYTES

    assert ORPHAN_FALLBACK_MIN_BYTES == 64 * 1024


# ---------------------------------------------------------------- full saves


def test_full_save_frees_an_unreachable_stream_and_keeps_numbering(tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False)
    try:
        page_xref = model.doc.page_xref(0)
        epoch = model.xref_epoch
        orphan = _add_orphan(model.doc)
        model.save_as(str(path))
        assert path.stat().st_size < SMALL_LIMIT
        assert model.doc.xref_object(orphan) == "null"
        assert model.doc.page_xref(0) == page_xref
        assert model.xref_epoch == epoch
        assert model.doc.xref_length() > orphan  # numbering kept: no slot compaction
    finally:
        model.close()


def test_save_as_another_path_prunes_output_but_not_the_live_doc(tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    out = tmp_path / "copy.pdf"
    model = _open(path, incremental=False)
    try:
        orphan = _add_orphan(model.doc)
        model.save_as(str(out))
        assert out.stat().st_size < SMALL_LIMIT
        reopened = fitz.open(str(out))
        try:
            assert reopened.xref_object(orphan) == "null"
        finally:
            reopened.close()
        assert len(model.doc.xref_stream_raw(orphan)) == ORPHAN_BYTES  # live doc untouched
    finally:
        model.close()


def test_save_as_new_path_then_save_again_prunes_both_and_keeps_the_live_orphan(tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    first = tmp_path / "first.pdf"
    model = _open(path, incremental=True)
    try:
        orphan = _add_orphan(model.doc)
        model.save_as(str(first))
        size_first = first.stat().st_size
        assert size_first < SMALL_LIMIT
        model.save_as(str(first))  # Ctrl+S on the new path
        assert first.stat().st_size < SMALL_LIMIT
        assert len(model.doc.xref_stream_raw(orphan)) == ORPHAN_BYTES
        reopened = fitz.open(str(first))
        try:
            assert reopened.xref_object(orphan) == "null"
        finally:
            reopened.close()
    finally:
        model.close()


def test_encrypted_same_path_non_secure_save_prunes_and_keeps_the_password(tmp_path) -> None:
    path = _make_pdf(tmp_path / "enc.pdf", encrypted=True)
    model = _open(path, incremental=False, password="user-secret")
    try:
        epoch = model.xref_epoch
        orphan = _add_orphan(model.doc)
        model.save_as(str(path))
        assert path.stat().st_size < SMALL_LIMIT
        # an unauthenticated encrypted handle cannot extract text
        assert "hello world" in model.doc[0].get_text(), "the reopened handle must be re-authenticated"
        assert model.doc.xref_object(orphan) == "null"
        assert model.xref_epoch == epoch
    finally:
        model.close()
    _assert_encrypted_file_has_text(path, "hello world")


@pytest.mark.parametrize("same_path", [True, False])
def test_the_prepared_doc_branch_prunes_the_output(tmp_path, same_path) -> None:
    """A PDF watermark makes ``save_as`` write a prepared clone (own numbering);
    that non-secure write prunes too."""
    path = _make_pdf(tmp_path / "doc.pdf")
    out = path if same_path else tmp_path / "wm.pdf"
    model = _open(path, incremental=False)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        _add_orphan(model.doc)
        model.save_as(str(out))
    finally:
        model.close()
    assert out.stat().st_size < SMALL_LIMIT
    _assert_no_unreachable_in_file(out)


def test_the_secure_path_never_uses_garbage_1(tmp_path, monkeypatch) -> None:
    """Characterization: secure_save_required keeps the garbage=4 rewrite for
    every serialization (the pruning change touches only the non-secure writes)."""
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        _add_orphan(model.doc)
        model.secure_save_required = True
        calls: list[int] = []
        original = model._save_doc

        def _spy(doc, target, *, garbage=0, incremental=False):
            calls.append(garbage)
            return original(doc, target, garbage=garbage, incremental=incremental)

        monkeypatch.setattr(model, "_save_doc", _spy)
        model.save_as(str(path))
        assert calls and all(g == 4 for g in calls), calls
    finally:
        model.close()


# ---------------------------------------------------------------- incremental fallback


def test_incremental_save_with_a_large_session_orphan_falls_back_to_a_pruned_full_save(
    tmp_path, monkeypatch
) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    original_size = path.stat().st_size
    model = _open(path, incremental=True)
    try:
        assert model.doc.can_save_incrementally()
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_orphan(model.doc)
        model.save_as(str(path))
        assert full_saves == [str(path)], "the orphan payload must force the pruned full save"
    finally:
        model.close()
    assert path.stat().st_size < original_size + SMALL_LIMIT
    assert _eof_count(path) == 1
    _assert_no_unreachable_in_file(path)


def test_orphans_below_the_threshold_keep_the_incremental_save(tmp_path, monkeypatch) -> None:
    from model.save_compaction import ORPHAN_FALLBACK_MIN_BYTES

    path = _make_pdf(tmp_path / "doc.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_orphan(model.doc, ORPHAN_FALLBACK_MIN_BYTES - 1)
        model.save_as(str(path))
        assert full_saves == []
    finally:
        model.close()
    saved = path.read_bytes()
    assert saved[: len(original)] == original  # an appended revision
    assert _eof_count(path) == 2


def test_orphans_at_the_threshold_fall_back_and_several_orphans_are_summed(
    tmp_path, monkeypatch
) -> None:
    from model.save_compaction import ORPHAN_FALLBACK_MIN_BYTES

    half = ORPHAN_FALLBACK_MIN_BYTES // 2
    for label, sizes in (("one", [ORPHAN_FALLBACK_MIN_BYTES]), ("two", [half, half])):
        path = _make_pdf(tmp_path / f"{label}.pdf")
        model = _open(path, incremental=True)
        try:
            full_saves = _spy_full_saves(model, monkeypatch)
            for size in sizes:
                _add_orphan(model.doc, size)
            model.save_as(str(path))
            assert full_saves == [str(path)], label
        finally:
            model.close()
        assert _eof_count(path) == 1, label


def test_reachable_new_objects_never_trigger_the_fallback(tmp_path, monkeypatch) -> None:
    """A big but REACHABLE new stream (an attached payload) is a real edit."""
    path = _make_pdf(tmp_path / "doc.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        xref = _add_orphan(model.doc, 100_000)
        model.doc.xref_set_key(model.doc.page_xref(0), "Payload", f"{xref} 0 R")
        model.save_as(str(path))
        assert full_saves == []
        assert model.persisted_xref_length == model.doc.xref_length()
    finally:
        model.close()
    assert path.read_bytes()[: len(original)] == original


def test_add_textbox_only_session_stays_incremental(tmp_path, monkeypatch) -> None:
    """``save_as`` runs ``clean_contents`` on the touched page, which replaces
    /Contents and orphans the session's own content stream -- small, so the save
    stays incremental (pinned: small orphans are not worth losing the append-only
    revision)."""
    from model.save_compaction import ORPHAN_FALLBACK_MIN_BYTES, unreachable_xrefs

    path = _make_pdf(tmp_path / "doc.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        model.add_textbox(1, fitz.Rect(100, 200, 300, 260), "Hello box", font="helv", size=12)
        base = model.persisted_xref_length
        orphans = unreachable_xrefs(model.doc, from_xref=base)
        orphan_bytes = sum(
            len(model.doc.xref_stream_raw(x)) for x in orphans if model.doc.xref_is_stream(x)
        )
        assert orphan_bytes < ORPHAN_FALLBACK_MIN_BYTES
        model.save_as(str(path))
        assert full_saves == []
    finally:
        model.close()
    assert path.read_bytes()[: len(original)] == original
    assert _eof_count(path) == 2


# ------------------------------------------- signed documents never leave the append-only save


def _make_signed_pdf(
    path: Path,
    *,
    signed: bool = True,
    watermark_embed: bool = False,
    sig_flags: int | None = 3,
    field_shape: str = "inline",
) -> Path:
    """Two text pages; page 1 carries a signature widget (``/V`` set when ``signed``).

    ``sig_flags`` is the AcroForm ``/SigFlags`` value; ``None`` omits the key, which
    ISO 32000 allows (default 0) and which PyMuPDF reads back as ``-1``.

    ``field_shape`` picks how the widget is reached from ``/Root /AcroForm`` (all
    legal ISO 32000 shapes): ``"inline"`` (``/Fields [w]``), ``"indirect_fields"``
    (``/Fields N 0 R`` -> ``[w]``), ``"inline_dict_indirect_fields"`` (an inline
    ``/AcroForm << /Fields N 0 R >>``), ``"indirect_kids"`` (``/Fields [p]`` where the
    parent ``p`` has ``/Kids N 0 R`` -> ``[w]``) and ``"inline_dict_nested_decoy"``
    (an inline ``/AcroForm`` whose ``/DR`` sub-dictionary carries its own ``/Fields``
    key ahead of the real one).

    ``watermark_embed`` adds the editor's ``__pdf_editor_watermarks`` attachment, which
    every file this editor saved after a watermark carries."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "Contract page one", fontsize=12.0)
    doc.new_page().insert_text((72, 100), "Page two body", fontsize=12.0)
    value = ""
    if signed:
        sigv = _new_object(
            doc,
            "<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached"
            " /ByteRange [0 0 0 0] /Contents <00000000> >>",
        )
        value = f" /V {sigv} 0 R"
    widget = _new_object(
        doc,
        f"<< /Type /Annot /Subtype /Widget /FT /Sig /T (Sig1) /Rect [72 600 272 650] /F 4"
        f"{value} /P {doc.page_xref(0)} 0 R >>",
    )
    doc.xref_set_key(doc.page_xref(0), "Annots", f"[{widget} 0 R]")
    flags = "" if sig_flags is None else f" /SigFlags {sig_flags}"
    # ``acroform`` is the catalog's /AcroForm value: an inline dictionary or a reference.
    if field_shape == "inline_dict_nested_decoy":
        decoy = _new_object(doc, "<< /FT /Tx /T (Decoy) >>")
        acroform = f"<< /DR << /Fields [{decoy} 0 R] >> /Fields [{widget} 0 R]{flags} >>"
    elif field_shape == "inline_dict_indirect_fields":
        fields_array = _new_object(doc, f"[{widget} 0 R]")
        acroform = f"<< /Fields {fields_array} 0 R{flags} >>"
    elif field_shape == "inline":
        acroform = f"{_new_object(doc, f'<< /Fields [{widget} 0 R]{flags} >>')} 0 R"
    elif field_shape == "indirect_fields":
        fields_array = _new_object(doc, f"[{widget} 0 R]")
        acroform = f"{_new_object(doc, f'<< /Fields {fields_array} 0 R{flags} >>')} 0 R"
    elif field_shape == "indirect_kids":
        kids = _new_object(doc, f"[{widget} 0 R]")
        parent = _new_object(doc, f"<< /FT /Sig /T (SigParent) /Kids {kids} 0 R >>")
        doc.xref_set_key(widget, "Parent", f"{parent} 0 R")
        acroform = f"{_new_object(doc, f'<< /Fields [{parent} 0 R]{flags} >>')} 0 R"
    else:
        raise ValueError(f"unknown field_shape {field_shape!r}")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", acroform)
    if watermark_embed:
        doc.embfile_add("__pdf_editor_watermarks", b"[]")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def test_a_signed_document_keeps_the_incremental_save_despite_a_large_session_orphan(
    tmp_path, monkeypatch
) -> None:
    """A full rewrite moves bytes inside the signature's /ByteRange and breaks it;
    the signed revision must stay a byte prefix even when that costs file size."""
    from model.text_commit.inspect import document_has_a_signed_signature

    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        assert document_has_a_signed_signature(model.doc)
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_orphan(model.doc)
        assert model._session_orphans_block_incremental() is False
        model.save_as(str(path))
        assert full_saves == [], "a signed document must never be rewritten by the orphan fallback"
    finally:
        model.close()
    assert path.read_bytes()[: len(original)] == original
    assert _eof_count(path) == 2


def test_an_unsigned_signature_placeholder_still_takes_the_pruned_full_save(
    tmp_path, monkeypatch
) -> None:
    """``/SigFlags`` alone declares a field; only a non-null ``/V`` is a signature."""
    path = _make_signed_pdf(tmp_path / "template.pdf", signed=False)
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_orphan(model.doc)
        assert model._session_orphans_block_incremental() is True
        model.save_as(str(path))
        assert full_saves == [str(path)]
    finally:
        model.close()
    assert _eof_count(path) == 1


def test_a_signed_document_that_cannot_be_probed_is_treated_as_signed(
    tmp_path, monkeypatch
) -> None:
    """The signature probe is fail-closed, so an unreadable form tree keeps the append-only save."""
    path = _make_signed_pdf(tmp_path / "unreadable.pdf", signed=False)
    model = _open(path, incremental=True)
    try:
        _add_orphan(model.doc)

        def _boom(*_a, **_k):
            raise RuntimeError("unreadable")

        monkeypatch.setattr(model.doc, "xref_get_key", _boom, raising=False)
    except Exception:
        model.close()
        raise
    try:
        assert model._session_orphans_block_incremental() is False
    finally:
        monkeypatch.undo()
        model.close()


# --------------- /SigFlags is optional: a signed field without it is still signed (R9)


@pytest.mark.parametrize("sig_flags", [None, 0])
def test_a_signed_field_is_signed_even_when_sigflags_is_absent_or_zero(tmp_path, sig_flags) -> None:
    """PyMuPDF's ``get_sigflags()`` is ``-1`` for an absent key; the signature itself is
    the non-null ``/V`` on a ``/FT /Sig`` field, whatever ``/SigFlags`` says."""
    from model.text_commit.inspect import document_has_a_signed_signature

    path = _make_signed_pdf(tmp_path / "noflags.pdf", sig_flags=sig_flags)
    doc = fitz.open(str(path))
    try:
        assert doc.get_sigflags() <= 0, "fixture is vacuous: /SigFlags must be absent or 0"
        assert document_has_a_signed_signature(doc) is True
    finally:
        doc.close()


@pytest.mark.parametrize("sig_flags", [None, 0, 3])
def test_an_unsigned_placeholder_stays_unsigned_whatever_sigflags_says(tmp_path, sig_flags) -> None:
    from model.text_commit.inspect import document_has_a_signed_signature

    path = _make_signed_pdf(tmp_path / "placeholder.pdf", signed=False, sig_flags=sig_flags)
    doc = fitz.open(str(path))
    try:
        assert document_has_a_signed_signature(doc) is False
    finally:
        doc.close()


def test_a_document_without_an_acroform_is_unsigned(tmp_path) -> None:
    from model.text_commit.inspect import document_has_a_signed_signature

    path = _make_pdf(tmp_path / "plain.pdf")
    doc = fitz.open(str(path))
    try:
        assert document_has_a_signed_signature(doc) is False
    finally:
        doc.close()


def test_a_sigflags_without_fields_is_still_treated_as_signed(tmp_path) -> None:
    """``/SigFlags`` declaring signatures over an unreadable/empty field tree stays fail-closed."""
    from model.text_commit.inspect import document_has_a_signed_signature

    path = tmp_path / "empty_fields.pdf"
    doc = fitz.open()
    doc.new_page()
    acroform = _new_object(doc, "<< /Fields [] /SigFlags 3 >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{acroform} 0 R")
    doc.save(str(path), garbage=0)
    doc.close()
    reopened = fitz.open(str(path))
    try:
        assert document_has_a_signed_signature(reopened) is True
    finally:
        reopened.close()


def test_signed_doc_without_sigflags_keeps_the_append_save_despite_a_large_orphan(
    tmp_path, monkeypatch
) -> None:
    path = _make_signed_pdf(tmp_path / "noflags.pdf", sig_flags=None)
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_orphan(model.doc)
        assert model._session_orphans_block_incremental() is False
        model.save_as(str(path))
        assert full_saves == [], "a signed document must never be rewritten by the orphan fallback"
    finally:
        model.close()
    assert path.read_bytes().startswith(original)
    assert _eof_count(path) == 2


def test_signed_doc_without_sigflags_undo_then_save_as_keeps_the_signed_revision_as_prefix(
    tmp_path,
) -> None:
    """The in-memory-handle flow (SnapshotCommand undo, then a save) appends too."""
    path = _make_signed_pdf(tmp_path / "noflags.pdf", sig_flags=None)
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        assert model.doc.name != str(path), "undo must have left an in-memory handle"
        model.save_as(str(path))
    finally:
        model.close()
    # The undo leaves nothing to append (a net-zero state), so no new %%EOF is expected;
    # what matters is that the signed revision was not rewritten.
    assert path.read_bytes().startswith(original), "signed revision must stay an exact byte prefix"


def test_signed_doc_without_sigflags_refuses_a_text_edit_on_every_page(tmp_path) -> None:
    """The text-edit gate shares the probe: editing any page would move signed bytes."""
    from model.text_commit.inspect import page_has_widgets_or_signatures

    path = _make_signed_pdf(tmp_path / "noflags.pdf", sig_flags=None)
    doc = fitz.open(str(path))
    try:
        assert page_has_widgets_or_signatures(doc, doc[1]) is True
    finally:
        doc.close()


# ------ R10 F10-SIG-1: an INDIRECT /Fields or /Kids array is a legal shape, not "unparseable"

_UNSIGNED_FORM_TARGET = "Price 2024"
_UNSIGNED_FORM_REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica


def _make_unsigned_form_pdf(path: Path, shape: str) -> Path:
    """One widget-free text page and an UNSIGNED AcroForm (no ``/FT /Sig`` anywhere,
    no ``/SigFlags``) whose field tree is reached through ``shape``.

    ``indirect_fields_empty`` is the real ``test_files/test-large-file.pdf`` shape
    (``/Fields 18 0 R`` -> ``[ ]``).  The ``*_to_dict`` / ``*_to_free`` shapes point the
    indirect ``/Fields`` at something that is NOT an array; those must stay fail-closed."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), _UNSIGNED_FORM_TARGET, fontsize=12.0)
    catalog = doc.pdf_catalog()

    def _obj(text: str) -> int:
        return _new_object(doc, text)

    def _acroform(body: str) -> None:
        doc.xref_set_key(catalog, "AcroForm", f"{_obj(f'<< {body} >>')} 0 R")

    if shape == "indirect_fields_empty":
        _acroform(f"/Fields {_obj('[ ]')} 0 R")
    elif shape == "indirect_fields_tx":
        tx = _obj("<< /FT /Tx /T (name) /V (hello) >>")
        _acroform(f"/Fields {_obj(f'[ {tx} 0 R ]')} 0 R")
    elif shape == "inline_dict_indirect_fields":
        doc.xref_set_key(catalog, "AcroForm", f"<< /Fields {_obj('[ ]')} 0 R >>")
    elif shape == "indirect_kids":
        kid = _obj("<< /T (kid) >>")
        parent = _obj(f"<< /FT /Tx /T (parent) /Kids {_obj(f'[ {kid} 0 R ]')} 0 R >>")
        doc.xref_set_key(kid, "Parent", f"{parent} 0 R")
        _acroform(f"/Fields [ {parent} 0 R ]")
    elif shape == "indirect_fields_to_dict":
        _acroform(f"/Fields {_obj('<< /Foo 1 >>')} 0 R")
    elif shape == "indirect_fields_to_free":
        _acroform(f"/Fields {doc.get_new_xref()} 0 R")
    else:
        raise ValueError(f"unknown shape {shape!r}")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


_UNSIGNED_INDIRECT_SHAPES = (
    "indirect_fields_empty",
    "indirect_fields_tx",
    "inline_dict_indirect_fields",
    "indirect_kids",
)


@pytest.mark.parametrize("shape", _UNSIGNED_INDIRECT_SHAPES)
def test_an_unsigned_form_reached_through_an_indirect_array_is_unsigned(tmp_path, shape) -> None:
    """Round 9 made the field walk run for every AcroForm; an indirect ``/Fields`` or
    ``/Kids`` (kind ``"xref"``) was then read as "unparseable" and fail-closed to
    "signed", refusing text edits on every page of a form nobody signed."""
    from model.text_commit.inspect import (
        document_has_a_signed_signature,
        page_has_widgets_or_signatures,
    )

    path = _make_unsigned_form_pdf(tmp_path / f"{shape}.pdf", shape)
    doc = fitz.open(str(path))
    try:
        assert doc.get_sigflags() == -1, "fixture is vacuous: /SigFlags must be absent"
        assert document_has_a_signed_signature(doc) is False
        assert page_has_widgets_or_signatures(doc, doc[0]) is False
    finally:
        doc.close()


@pytest.mark.parametrize("shape", _UNSIGNED_INDIRECT_SHAPES)
def test_text_edit_on_an_unsigned_form_with_an_indirect_array_is_applied(tmp_path, shape) -> None:
    """The user-visible half: ``PDFModel.edit_text`` must not hard-reject the edit."""
    from model.text_commit.dto import TextCommitSettings
    from model.edit_commands import EditTextResult

    path = _make_unsigned_form_pdf(tmp_path / f"{shape}.pdf", shape)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(path))
    try:
        model.ensure_page_index_built(1)
        block = next(
            b for b in model.block_manager.get_blocks(0) if _UNSIGNED_FORM_TARGET in (b.text or "")
        )
        result = model.edit_text(
            1,
            fitz.Rect(block.layout_rect),
            _UNSIGNED_FORM_REPLACEMENT,
            font=block.font,
            size=block.size,
            original_text=_UNSIGNED_FORM_TARGET,
        )
        assert result is not EditTextResult.REJECTED_UNSUPPORTED
        assert _UNSIGNED_FORM_REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_unsigned_form_with_an_indirect_fields_array_takes_the_pruned_full_save(
    tmp_path, monkeypatch
) -> None:
    """The save gate shares the probe: an unsigned file must not be pinned to the
    append-only save (which keeps every session orphan) just because /Fields is indirect."""
    path = _make_unsigned_form_pdf(tmp_path / "form.pdf", "indirect_fields_empty")
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_orphan(model.doc)
        assert model._session_orphans_block_incremental() is True
        model.save_as(str(path))
        assert full_saves == [str(path)]
    finally:
        model.close()
    assert _eof_count(path) == 1


@pytest.mark.parametrize("shape", ["indirect_fields_to_dict", "indirect_fields_to_free"])
def test_an_indirect_fields_reference_to_a_non_array_stays_fail_closed(tmp_path, shape) -> None:
    from model.text_commit.inspect import document_has_a_signed_signature

    path = _make_unsigned_form_pdf(tmp_path / f"{shape}.pdf", shape)
    doc = fitz.open(str(path))
    try:
        assert document_has_a_signed_signature(doc) is True
    finally:
        doc.close()


_LEGAL_FIELD_SHAPES = (
    "indirect_fields",
    "inline_dict_indirect_fields",
    "indirect_kids",
    "inline_dict_nested_decoy",
)


@pytest.mark.parametrize("field_shape", _LEGAL_FIELD_SHAPES)
@pytest.mark.parametrize("sig_flags", [None, 3])
def test_a_signed_field_reached_through_any_legal_field_shape_is_signed(
    tmp_path, field_shape, sig_flags
) -> None:
    """The resolution must find the signature, not merely stop failing closed.  The
    nested-decoy shape pins that an inline ``/AcroForm`` is read by key, never by
    pattern-matching its serialization (a ``/DR`` sub-dict's ``/Fields`` is not the form's)."""
    from model.text_commit.inspect import (
        document_has_a_signed_signature,
        page_has_widgets_or_signatures,
    )

    path = _make_signed_pdf(tmp_path / "signed.pdf", sig_flags=sig_flags, field_shape=field_shape)
    doc = fitz.open(str(path))
    try:
        assert document_has_a_signed_signature(doc) is True
        assert page_has_widgets_or_signatures(doc, doc[1]) is True
    finally:
        doc.close()


@pytest.mark.parametrize("field_shape", _LEGAL_FIELD_SHAPES)
def test_an_unsigned_placeholder_reached_through_any_legal_field_shape_is_unsigned(
    tmp_path, field_shape
) -> None:
    from model.text_commit.inspect import document_has_a_signed_signature

    path = _make_signed_pdf(
        tmp_path / "placeholder.pdf", signed=False, sig_flags=None, field_shape=field_shape
    )
    doc = fitz.open(str(path))
    try:
        assert document_has_a_signed_signature(doc) is False
    finally:
        doc.close()


_LARGE_PDF = ROOT / "test_files" / "test-large-file.pdf"


@pytest.mark.skipif(not _LARGE_PDF.exists(), reason="gitignored real-corpus fixture absent")
def test_real_corpus_unsigned_form_with_indirect_empty_fields_is_unsigned() -> None:
    """``test-large-file.pdf``: ``/AcroForm << ... /Fields 18 0 R >>``, ``18 0 obj [ ]``,
    no ``/SigFlags``, no signature widget.  Opened read-only."""
    from model.text_commit.inspect import document_has_a_signed_signature

    doc = fitz.open(str(_LARGE_PDF))
    try:
        assert document_has_a_signed_signature(doc) is False
    finally:
        doc.close()


@pytest.mark.parametrize("undo_first", [True, False])
def test_signed_doc_add_cjk_textbox_then_save_keeps_the_signed_revision_as_prefix(
    tmp_path, monkeypatch, undo_first
) -> None:
    """The reproduced flow: an embedded CJK font left unreachable by undo (>64 KiB)."""
    from model.edit_commands import AddTextboxCommand

    path = _make_signed_pdf(tmp_path / "signed_flow.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        cmd = AddTextboxCommand(
            model=model,
            page_num=2,
            visual_rect=fitz.Rect(72, 200, 400, 400),
            text="你好世界 簽署測試" * 3,
            font="cjk",
            size=14.0,
            color=(0, 0, 0),
            before_page_snapshot_bytes=model._capture_page_snapshot_strict(1),
        )
        model.command_manager.execute(cmd)
        if undo_first:
            model.command_manager.undo()
        model.save_as(str(path))
        assert full_saves == []
    finally:
        model.close()
    assert path.read_bytes()[: len(original)] == original


# ----------------------- signed documents: an in-memory handle still appends (R7-1)


def _record_highlight(model: PDFModel, page_num: int = 1) -> None:
    """Record a highlight as ``PDFController.add_highlight`` does (a SnapshotCommand)."""
    _record_snapshot(
        model,
        lambda: model.tools.annotation.add_highlight(
            page_num, fitz.Rect(72, 90, 200, 110), (1.0, 1.0, 0.0, 1.0)
        ),
        command_type="add_highlight",
        affected_pages=[page_num],
        description="hl",
    )


def _highlights_in(doc: fitz.Document) -> int:
    return sum(1 for page in doc for annot in page.annots() or [] if annot.type[0] == 8)


def _highlight_count(path: Path) -> int:
    doc = fitz.open(str(path))
    try:
        return _highlights_in(doc)
    finally:
        doc.close()


@pytest.mark.parametrize("redo", [False, True])
def test_signed_doc_snapshot_undo_redo_then_save_keeps_the_signed_revision_as_prefix(
    tmp_path, redo
) -> None:
    """Undo/redo of a SnapshotCommand installs an in-memory handle (no file to append
    to); the save must still append to the signed file, not rewrite it (R7-1)."""
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        assert model.doc.name != str(path), "undo must have left an in-memory handle"
        if redo:
            model.command_manager.redo()
        else:
            _record_highlight(model)
        model.save_as(str(path))
    finally:
        model.close()
    data = path.read_bytes()
    assert data.startswith(original), "signed revision must stay an exact byte prefix"
    assert data.count(b"%%EOF") == 2
    assert _highlight_count(path) == 1
    reopened = fitz.open(str(path))
    try:
        assert len(reopened) == 2
        assert "Contract page one" in reopened[0].get_text()
    finally:
        reopened.close()


def test_signed_doc_undo_save_removes_the_undone_edit_but_keeps_the_prefix(tmp_path) -> None:
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        model.save_as(str(path))
    finally:
        model.close()
    assert path.read_bytes().startswith(original)
    assert _highlight_count(path) == 0


def test_signed_doc_saves_twice_after_undo_and_the_session_stays_editable(tmp_path) -> None:
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        _record_highlight(model)
        model.save_as(str(path))
        first = path.read_bytes()
        _record_highlight(model, page_num=2)
        model.save_as(str(path))
        assert model.doc.page_count == 2
    finally:
        model.close()
    data = path.read_bytes()
    assert data.startswith(original) and data.startswith(first)
    assert _highlight_count(path) == 2


def test_signed_xref_stream_source_saves_repeatedly_by_appending(tmp_path, monkeypatch) -> None:
    """R8-SIG-B: the appended xref stream takes a new object number in the FILE.

    The live handle never saw that number, so its next new object (a highlight
    on page 2) was allocated onto the file's /XRef container; the next save then
    declined the append and fully rewrote the signed file.  The live table must
    skip every number the appended revision used, on every save.
    """
    path = _make_xref_stream_signed_pdf(tmp_path / "signed_xref.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    full_saves = _spy_full_saves(model, monkeypatch)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        _record_highlight(model)
        model.save_as(str(path))
        first = path.read_bytes()
        assert first.startswith(original) and full_saves == []
        file_len = fitz.open(str(path))
        try:
            appended_len = int(file_len.xref_length())
        finally:
            file_len.close()
        assert int(model.doc.xref_length()) >= appended_len, "live table must skip the appended xref stream"
        _record_highlight(model, page_num=2)
        model.save_as(str(path))
        second = path.read_bytes()
        assert full_saves == [], "the second save must append, not rewrite the signed file"
        assert second.startswith(first)
        _record_highlight(model)
        model.save_as(str(path))
        assert full_saves == []
        assert path.read_bytes().startswith(second)
    finally:
        model.close()
    assert path.read_bytes().startswith(original)
    assert _highlight_count(path) == 3


def test_signed_xref_stream_source_undo_after_a_save_still_appends_the_next_save(
    tmp_path, monkeypatch
) -> None:
    """R8-SIG-B: undo reinstalls an older, shorter table; the floor must outlive that handle."""
    path = _make_xref_stream_signed_pdf(tmp_path / "signed_xref.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    full_saves = _spy_full_saves(model, monkeypatch)
    try:
        _record_highlight(model)
        model.command_manager.undo()  # the live handle is in memory: the append path
        _record_highlight(model)
        model.save_as(str(path))
        first = path.read_bytes()
        assert model.reserved_xref_length > 0
        _record_highlight(model, page_num=2)
        model.command_manager.undo()
        model.command_manager.undo()  # an older, shorter table is reinstalled
        assert int(model.doc.xref_length()) >= model.reserved_xref_length
        _record_highlight(model, page_num=2)
        model.save_as(str(path))
        assert full_saves == []
        assert path.read_bytes().startswith(first)
    finally:
        model.close()
    assert path.read_bytes().startswith(original)
    assert _highlight_count(path) == 1


def test_signed_xref_stream_source_save_as_then_save_again_keeps_appending(
    tmp_path, monkeypatch
) -> None:
    """R8-SIG-B: the same collision after a Save As (the handle is rebound to a private copy)."""
    path = _make_xref_stream_signed_pdf(tmp_path / "signed_xref.pdf")
    original = path.read_bytes()
    copy = tmp_path / "copy.pdf"
    model = _open(path, incremental=True)
    full_saves = _spy_full_saves(model, monkeypatch)
    try:
        _record_highlight(model)
        model.save_as(str(copy))
        first = copy.read_bytes()
        _record_highlight(model, page_num=2)
        model.save_as(str(copy))
        assert full_saves == []
        assert copy.read_bytes().startswith(first)
    finally:
        model.close()
    assert path.read_bytes() == original
    assert copy.read_bytes().startswith(original)
    assert _highlight_count(copy) == 2


def test_signed_doc_save_as_a_new_name_keeps_the_signed_revision_as_prefix(tmp_path) -> None:
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    copy = tmp_path / "copy.pdf"
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.save_as(str(copy))
    finally:
        model.close()
    assert path.read_bytes() == original, "the source file is not touched by a Save As"
    assert copy.read_bytes().startswith(original)
    assert _highlight_count(copy) == 1


def test_signed_doc_page_delete_undo_redo_save_keeps_the_prefix(tmp_path) -> None:
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        _record_snapshot(
            model,
            lambda: model.doc.delete_page(1),
            command_type="delete_pages",
            affected_pages=[2],
            description="del",
        )
        model.command_manager.undo()
        model.command_manager.redo()
        model.save_as(str(path))
    finally:
        model.close()
    assert path.read_bytes().startswith(original)
    reopened = fitz.open(str(path))
    try:
        assert len(reopened) == 1
    finally:
        reopened.close()


def test_unsigned_doc_after_snapshot_undo_still_takes_the_pruned_full_save(tmp_path) -> None:
    path = _make_signed_pdf(tmp_path / "template.pdf", signed=False)
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        _record_highlight(model)
        model.save_as(str(path))
    finally:
        model.close()
    assert _eof_count(path) == 1
    assert _highlight_count(path) == 1


def test_signed_doc_with_the_secure_latch_still_gets_the_sanitising_rewrite(
    tmp_path, monkeypatch
) -> None:
    """A redaction/metadata latch exists to drop old bytes: it overrides the append.
    SIG-DIALOG: the rewrite invalidates the signature, so it needs the user's consent."""
    import model.signed_append_save as signed_append_save
    from model.pdf_model import SignatureWouldBreakError

    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        model.secure_save_required = True
        calls: list[object] = []
        monkeypatch.setattr(
            signed_append_save, "try_append_state_onto_source", lambda *a, **k: calls.append(a) or "x"
        )
        with pytest.raises(SignatureWouldBreakError) as excinfo:
            model.save_as(str(path))
        assert excinfo.value.reason_code == "secure_latch"
        assert path.read_bytes() == original
        model.save_as(str(path), allow_signature_loss=True)
        assert calls == []
    finally:
        model.close()
    assert _eof_count(path) == 1


def test_signed_append_failure_falls_back_to_the_full_save(tmp_path, monkeypatch) -> None:
    """SIG-DIALOG: the fallback only runs with the user's consent."""
    import model.signed_append_save as signed_append_save
    from model.pdf_model import SignatureWouldBreakError

    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.command_manager.undo()
        _record_highlight(model)

        def _boom(*_a, **_k):
            raise RuntimeError("replay exploded")

        monkeypatch.setattr(signed_append_save, "try_append_state_onto_source", _boom)
        with pytest.raises(SignatureWouldBreakError) as excinfo:
            model.save_as(str(path))
        assert excinfo.value.reason_code == "append_error"
        assert path.read_bytes() == original
        model.save_as(str(path), allow_signature_loss=True)
    finally:
        model.close()
    assert _eof_count(path) == 1
    assert _highlight_count(path) == 1
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")], "no staging leftovers"


def test_append_state_refuses_an_unsigned_source(tmp_path) -> None:
    """The append exists to protect signatures: an unsigned source is left to the caller."""
    from model.signed_append_save import append_state_onto_source

    path = _make_signed_pdf(tmp_path / "template.pdf", signed=False)
    doc = fitz.open(str(path))
    try:
        stage = tmp_path / "stage.pdf"
        assert append_state_onto_source(doc, path, stage) is False
        assert not stage.exists()
    finally:
        doc.close()


def test_append_state_reproduces_the_state_object_for_object(tmp_path) -> None:
    from model.signed_append_save import append_state_onto_source

    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    state = fitz.open("pdf", original)
    state[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
    state.delete_page(1)
    state = fitz.open("pdf", state.tobytes(garbage=0))
    try:
        stage = tmp_path / "stage.pdf"
        assert append_state_onto_source(state, path, stage) is True
        data = stage.read_bytes()
        assert data.startswith(original)
        out = fitz.open(str(stage))
        try:
            assert len(out) == 1
            assert [a.type[0] for a in out[0].annots()].count(8) == 1
        finally:
            out.close()
    finally:
        state.close()


def test_append_state_handles_a_source_with_object_and_xref_streams(tmp_path) -> None:
    """Containers are file structure: they are neither nulled nor reported as a difference."""
    from model.signed_append_save import append_state_onto_source

    path = _make_xref_stream_signed_pdf(tmp_path / "objstm.pdf", pages=40)
    original = path.read_bytes()
    state = fitz.open("pdf", original)
    state[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
    state.delete_page(5)
    state = fitz.open("pdf", state.tobytes(garbage=0))
    try:
        stage = tmp_path / "stage.pdf"
        assert append_state_onto_source(state, path, stage) is True
        assert stage.read_bytes().startswith(original)
        out = fitz.open(str(stage))
        try:
            assert len(out) == len(state)
            assert [a.type[0] for a in out[0].annots()].count(8) == 1
        finally:
            out.close()
    finally:
        state.close()


def _make_xref_stream_signed_pdf(path: Path, *, pages: int = 10) -> Path:
    """The signed fixture plus ``pages`` filler pages, re-saved with object streams and an
    xref stream (Acrobat/Office style)."""
    src = fitz.open(str(_make_signed_pdf(path.with_name("classic_" + path.name))))
    for number in range(pages):
        src.new_page().insert_text((72, 100), f"filler {number}")
    src.save(str(path), garbage=0, use_objstms=1, deflate=True)
    src.close()
    original = path.read_bytes()
    assert b"/ObjStm" in original and b"/XRef" in original
    return path


def test_signed_xref_stream_source_save_as_keeps_the_signed_revision_as_prefix(tmp_path) -> None:
    """R8-SIG-A: a file-backed live handle carries a real (regenerated-/ID) xref-stream object.

    The container slot of the live document is not null (unlike an in-memory
    ``state``), and after an edit its trailer ``/ID`` differs from the file's.
    That is file structure: it must neither decline the append nor be replayed.
    """
    path = _make_xref_stream_signed_pdf(tmp_path / "signed_xref.pdf")
    original = path.read_bytes()
    copy = tmp_path / "copy.pdf"
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        model.save_as(str(copy))
    finally:
        model.close()
    assert path.read_bytes() == original, "the source file is not touched by a Save As"
    data = copy.read_bytes()
    assert data.startswith(original), "signed revision must stay an exact byte prefix"
    assert data.count(b"%%EOF") == 2
    assert _highlight_count(copy) == 1


def test_append_state_accepts_a_file_backed_state_whose_xref_stream_object_differs(
    tmp_path,
) -> None:
    from model.signed_append_save import append_state_onto_source

    path = _make_xref_stream_signed_pdf(tmp_path / "signed_xref.pdf")
    original = path.read_bytes()
    state = fitz.open(str(path))
    try:
        # MuPDF regenerates the second trailer /ID after an edit; in an xref-stream
        # file the trailer IS the container object, so the slot now differs.
        state.xref_set_key(
            -1, "ID", "[<00112233445566778899AABBCCDDEEFF><FFEEDDCCBBAA99887766554433221100>]"
        )
        container = [
            x for x in range(1, int(state.xref_length())) if "/Type /XRef" in state.xref_object(x)
        ]
        assert len(container) == 1 and "00112233" in state.xref_object(container[0])
        state[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
        stage = tmp_path / "stage.pdf"
        assert append_state_onto_source(state, path, stage) is True
        assert stage.read_bytes().startswith(original)
        out = fitz.open(str(stage))
        try:
            assert [a.type[0] for a in out[0].annots()].count(8) == 1
        finally:
            out.close()
    finally:
        state.close()


def test_a_container_object_in_a_content_slot_declines_the_replay(tmp_path) -> None:
    """A real object in a container's place, or a container in a content slot, is another lineage."""
    from model.signed_append_save import _Declined, _differing_xrefs

    path = _make_xref_stream_signed_pdf(tmp_path / "signed_xref.pdf")
    base = fitz.open(str(path))
    state = fitz.open(str(path))
    try:
        container = next(
            x for x in range(1, int(base.xref_length())) if "/Type /XRef" in base.xref_object(x)
        )
        state.update_object(container, "<< /Type /Marker >>")
        with pytest.raises(_Declined):
            _differing_xrefs(state, base)
        state.update_object(container, base.xref_object(container, compressed=True))
        content = base.page_xref(0)
        state.update_object(content, "<< /Type /XRef >>")
        with pytest.raises(_Declined):
            _differing_xrefs(state, base)
    finally:
        state.close()
        base.close()


@pytest.mark.parametrize(
    ("undo_first", "save_over_source"), [(True, True), (True, False), (False, False)]
)
def test_signed_doc_with_the_watermark_attachment_keeps_the_signed_revision_as_prefix(
    tmp_path, undo_first, save_over_source
) -> None:
    """EXT-2: ``prepare_doc_for_save`` rewrites the attachment's inline Filespec on the
    live document; MuPDF prints that dictionary with its keys in another order after a
    reopen.  A key-order-only difference is the same object and must not decline the
    append (which would fully rewrite the file and break the signature)."""
    path = _make_signed_pdf(tmp_path / "signed.pdf", watermark_embed=True)
    original = path.read_bytes()
    target = path if save_over_source else tmp_path / "copy.pdf"
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        if undo_first:
            model.command_manager.undo()
            _record_highlight(model)
        model.save_as(str(target))
    finally:
        model.close()
    data = target.read_bytes()
    assert data.startswith(original), "signed revision must stay an exact byte prefix"
    assert data.count(b"%%EOF") == 2
    assert _highlight_count(target) == 1
    reopened = fitz.open(str(target))
    try:
        assert reopened.embfile_names() == ["__pdf_editor_watermarks"]
    finally:
        reopened.close()


def test_differing_xrefs_ignores_dictionary_key_order_but_not_a_changed_value(tmp_path) -> None:
    """EXT-2 chokepoint: the comparison is on the object tree, not on its print order."""
    from model.signed_append_save import _differing_xrefs

    state = fitz.open()
    base = fitz.open()
    try:
        for doc in (state, base):
            doc.new_page()
            doc.get_new_xref()
        xref = int(state.xref_length()) - 1
        state.update_object(xref, "<< /A 1 /B << /Type /Filespec /F (x) >> /C [ 1.5 /N ] >>")
        base.update_object(xref, "<< /C [ 1.5 /N ] /B << /F (x) /Type /Filespec >> /A 1 >>")
        assert _differing_xrefs(state, base) == []
        # array order, a nested value, a tiny real change and a string are all real differences
        for changed in (
            "<< /A 1 /B << /Type /Filespec /F (x) >> /C [ /N 1.5 ] >>",
            "<< /A 1 /B << /Type /Filespec /F (y) >> /C [ 1.5 /N ] >>",
            "<< /A 1 /B << /Type /Filespec /F (x) >> /C [ 1.5000001 /N ] >>",
            "<< /A 2 /B << /Type /Filespec /F (x) >> /C [ 1.5 /N ] >>",
        ):
            state.update_object(xref, changed)
            assert _differing_xrefs(state, base) == [xref], changed
    finally:
        state.close()
        base.close()


def test_append_state_refuses_an_encrypted_state_document(tmp_path) -> None:
    from model.signed_append_save import append_state_onto_source

    path = _make_signed_pdf(tmp_path / "signed.pdf")
    enc = _make_pdf(tmp_path / "enc.pdf", encrypted=True)
    doc = fitz.open(str(enc))
    try:
        doc.authenticate("user-secret")
        stage = tmp_path / "stage.pdf"
        assert append_state_onto_source(doc, path, stage) is False
        assert not stage.exists()
        # R9 M9-1: declining must not touch the live handle.  Reading ``needs_pass``
        # on an authenticated handle makes MuPDF drop its crypt key, so every
        # object not decoded yet decrypts to garbage and the text reads ''.
        assert [page.get_text() for page in doc] == ["hello world\n"]
    finally:
        doc.close()


def _make_encrypted_signed_pdf(path: Path) -> Path:
    """The signed two-page fixture re-saved with a user password (AES-256)."""
    plain = _make_signed_pdf(path.with_name("plain_" + path.name))
    doc = fitz.open(str(plain))
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
        permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE,
    )
    doc.close()
    return path


def _live_text(model: PDFModel) -> list[str]:
    return [page.get_text() for page in model.doc]


def _encrypted_file_text_and_highlights(path: Path) -> tuple[list[str], int]:
    doc = fitz.open(str(path))
    try:
        assert doc.needs_pass and doc.authenticate("user-secret"), "the encryption must survive"
        text = [page.get_text() for page in doc]
        highlights = _highlights_in(doc)
        return text, highlights
    finally:
        doc.close()


_SIGNED_TEXT = ["Contract page one\n", "Page two body\n"]


@pytest.mark.parametrize("scenario", ["save_as_new_path", "undo_then_save_over_original"])
def test_encrypted_signed_save_keeps_the_live_session_and_the_file_readable(
    tmp_path, scenario
) -> None:
    """R9 M9-1: the signed-append probe ran ``needs_pass`` on the live authenticated
    handle, which clobbered its crypt key; the declined append then fell back to a
    full save that wrote unreadable (blank-text) pages over the user's file."""
    path = _make_encrypted_signed_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True, password="user-secret")
    try:
        _record_highlight(model)
        target = path
        if scenario == "save_as_new_path":
            target = tmp_path / "copy.pdf"
        else:
            _record_highlight(model, 2)
            model.command_manager.undo()  # leaves an in-memory handle
        from model.pdf_model import SignatureWouldBreakError

        # SIG-DIALOG: a user-password source cannot be appended onto, so the save
        # asks first; the declined probe must not blank the live session either.
        with pytest.raises(SignatureWouldBreakError) as excinfo:
            model.save_as(str(target))
        assert excinfo.value.reason_code == "encryption_mismatch"
        assert _live_text(model) == _SIGNED_TEXT, "the declined probe blanked the live session"
        model.save_as(str(target), allow_signature_loss=True)
        assert _live_text(model) == _SIGNED_TEXT, "the live session was blanked by the save"
        assert not model.has_unsaved_changes()
    finally:
        model.close()
    text, highlights = _encrypted_file_text_and_highlights(target)
    assert text == _SIGNED_TEXT
    assert highlights >= 1


def test_signed_owner_only_encrypted_doc_still_appends_after_an_undo(tmp_path) -> None:
    """R9 M9-1 must not over-decline: an owner-password-only source needs no user
    password, so the in-memory handle still appends and the signature stays intact."""
    path, original = _make_owner_only_signed_pdf(tmp_path)
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        _record_highlight(model, 2)
        model.command_manager.undo()
        assert model.doc.name != str(path), "undo must have left an in-memory handle"
        model.save_as(str(path))
        assert _live_text(model) == _SIGNED_TEXT
    finally:
        model.close()
    data = path.read_bytes()
    assert data.startswith(original), "signed revision must stay an exact byte prefix"
    assert data.count(b"%%EOF") == 2


def _make_owner_only_signed_pdf(
    tmp_path: Path, encryption: int = fitz.PDF_ENCRYPT_AES_256
) -> tuple[Path, bytes]:
    """The signed fixture re-saved with an owner password only (opens unprompted)."""
    plain = _make_signed_pdf(tmp_path / "plain_signed.pdf")
    path = tmp_path / "owner_only.pdf"
    doc = fitz.open(str(plain))
    doc.save(
        str(path),
        encryption=encryption,
        owner_pw="owner-secret",
        user_pw="",
        permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE,
    )
    doc.close()
    return path, path.read_bytes()


@pytest.mark.parametrize(
    "encryption",
    [fitz.PDF_ENCRYPT_AES_256, fitz.PDF_ENCRYPT_AES_128, fitz.PDF_ENCRYPT_RC4_128],
)
def test_state_level_append_accepts_a_live_new_stream_on_an_owner_only_file(
    tmp_path, encryption
) -> None:
    """H10-1: a stream created in the live, unsaved handle prints its PLAINTEXT
    ``/Length`` while the appended (encrypted) file prints the ciphertext length
    (IV + padding).  The stream bytes are identical, so the append must not decline
    over that derived entry (it did, and the caller fully rewrote the signed file)."""
    from model.signed_append_save import append_state_onto_source

    path, original = _make_owner_only_signed_pdf(tmp_path, encryption)
    base = fitz.open(str(path))
    state = fitz.open("pdf", base.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP))
    base.close()
    state[0].add_highlight_annot(fitz.Rect(72, 90, 200, 110))
    stage = tmp_path / "stage.pdf"
    try:
        assert append_state_onto_source(state, path, stage) is True
        assert [page.get_text() for page in state] == _SIGNED_TEXT
    finally:
        state.close()
    data = stage.read_bytes()
    assert data.startswith(original)
    assert data.count(b"%%EOF") == 2
    check = fitz.open(str(stage))
    try:
        assert not check.needs_pass
        assert sum(1 for page in check for _ in page.annots() or []) == 1
    finally:
        check.close()


@pytest.mark.parametrize("scenario", ["save_as_new_path", "undo_then_ctrl_s"])
def test_owner_only_aes_signed_doc_keeps_the_signed_revision_after_a_live_highlight(
    tmp_path, scenario
) -> None:
    """H10-1 end to end: Save As / post-undo Ctrl+S of an owner-only encrypted signed
    file keeps the signed revision as an exact prefix."""
    path, original = _make_owner_only_signed_pdf(tmp_path)
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        target = path
        if scenario == "save_as_new_path":
            target = tmp_path / "saved_as.pdf"
        else:
            _record_highlight(model, 2)
            model.command_manager.undo()
            _record_highlight(model, 2)
        model.save_as(str(target))
        assert _live_text(model) == _SIGNED_TEXT
    finally:
        model.close()
    data = target.read_bytes()
    assert data.startswith(original), "signed revision must stay an exact byte prefix"
    assert data.count(b"%%EOF") == 2


def test_same_record_ignores_only_the_derived_stream_length(tmp_path) -> None:
    """H10-1 chokepoint: ``/Length`` of a stream is derived from its bytes, so it is
    skipped when (and only when) both records are streams with equal raw bytes."""
    from model.signed_append_save import _same_record

    raw = b"q 1 0 0 1 0 0 cm Q"
    live = ("<< /Type /XObject /Length 18 >>", raw)
    disk = ("<< /Length 48 /Type /XObject >>", raw)
    assert _same_record(live, disk)
    # a real dictionary difference still counts
    assert not _same_record(live, ("<< /Type /Font /Length 48 >>", raw))
    # different stream bytes still count, whatever the lengths say
    assert not _same_record(live, (disk[0], raw + b" "))
    # a non-stream object keeps /Length as an ordinary entry
    assert not _same_record(("<< /Length 1 >>", None), ("<< /Length 2 >>", None))
    # a stream against a non-stream never matches
    assert not _same_record(live, (live[0], None))


def test_append_state_refuses_an_encrypted_state_over_a_plain_source(tmp_path) -> None:
    """The encryption setups differ: replaying would write an unprotected copy of a
    protected session, so the append declines (and leaves the live handle readable)."""
    from model.signed_append_save import append_state_onto_source

    plain = _make_signed_pdf(tmp_path / "plain_signed.pdf")
    protected = _make_encrypted_signed_pdf(tmp_path / "protected.pdf")
    state = fitz.open(str(protected))
    try:
        assert state.authenticate("user-secret")
        stage = tmp_path / "stage.pdf"
        assert append_state_onto_source(state, plain, stage) is False
        assert not stage.exists()
        assert [page.get_text() for page in state] == _SIGNED_TEXT
    finally:
        state.close()


def test_needs_pass_is_only_read_where_the_handle_is_known_unauthenticated() -> None:
    """R9 M9-1 guard: ``needs_pass`` is only safe on a freshly opened (not yet
    authenticated) handle; on an authenticated one the read poisons the crypt key.
    Every ``needs_pass`` read in ``model/`` and ``controller/`` must sit in a
    function that provably only sees such a handle.  A new site fails here until
    it is audited and added -- use ``is_encrypted`` / ``metadata['encryption']`` /
    ``DocumentSession.auth_level`` for anything that can be a live document."""
    import ast

    audited = {
        ("controller/thumbnail_coordinator.py", "run"),
        ("model/pdf_model.py", "_guard_foreign_doc"),
        ("model/pdf_model.py", "open_pdf"),
        # F11-OPEN-1: read once on the fresh ``fitz.open(stream=...)`` handle, before authenticate.
        ("model/pdf_model.py", "import_session_transfer"),
        ("model/pdf_model.py", "_open_numbering_clone"),
        # S17-ENC-MERGE: the one place a KEEP serialization is reopened and unlocked (fresh handle, read before authenticate).
        ("model/pdf_model.py", "_open_authenticated"),
        ("model/pdf_model.py", "_atomic_full_save"),
        ("model/pdf_model.py", "_reauthenticate_if_needed"),
        ("model/tools/watermark_tool.py", "prepare_doc_for_save"),
        ("model/pdf_optimizer.py", "_open_optimize_snapshot"),
        ("model/text_commit/engine.py", "_build_scratch_copy"),
        ("model/text_commit/preview.py", "_session_snapshot_bytes"),
        ("model/text_commit/verify.py", "_ocg_membership_status"),
        ("model/pdf_validator.py", "check_pdf_conformance"),
        ("model/signed_append_save.py", "_replay_decline"),
    }
    found: set[tuple[str, str]] = set()
    for folder in ("model", "controller"):
        for source in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8-sig"))
            rel = source.relative_to(ROOT).as_posix()
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(func):
                    if isinstance(node, ast.Attribute) and node.attr == "needs_pass":
                        found.add((rel, func.name))
                    elif isinstance(node, ast.Constant) and node.value == "needs_pass":
                        found.add((rel, func.name))
    assert found <= audited, f"unaudited needs_pass reads (poison a live handle): {sorted(found - audited)}"


# ---------------------------------------------------------------- the watermark


def test_persisted_xref_length_tracks_open_incremental_and_full_saves(tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        assert model.persisted_xref_length == model.doc.xref_length()
        # a small reachable addition: incremental, the watermark follows
        xref = _add_orphan(model.doc, 10)
        model.doc.xref_set_key(model.doc.page_xref(0), "Tiny", f"{xref} 0 R")
        assert model.doc.xref_length() > model.persisted_xref_length
        model.save_as(str(path))
        assert model.persisted_xref_length == model.doc.xref_length()

        # a full save reopens the file: the watermark is the reopened table
        model.use_incremental_save = False
        _add_orphan(model.doc, 10)
        model.save_as(str(path))
        assert model.persisted_xref_length == model.doc.xref_length()
    finally:
        model.close()


def test_the_fast_path_skips_the_reachability_scan_when_nothing_was_added(
    tmp_path, monkeypatch
) -> None:
    import model.save_compaction as save_compaction

    path = _make_pdf(tmp_path / "doc.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        assert model.persisted_xref_length == model.doc.xref_length()

        def _forbidden(*_a, **_k):
            raise AssertionError("the BFS must not run when xref_length == the watermark")

        monkeypatch.setattr(save_compaction, "unreachable_xrefs", _forbidden)
        monkeypatch.setattr(save_compaction, "reachable_xrefs", _forbidden)
        full_saves = _spy_full_saves(model, monkeypatch)
        model.save_as(str(path))
        assert full_saves == []
    finally:
        model.close()
    assert path.read_bytes().startswith(original[:1024])


def test_an_unknown_watermark_takes_the_safe_full_save(tmp_path, monkeypatch) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        model._set_persisted_xref_length(None)
        full_saves = _spy_full_saves(model, monkeypatch)
        model.save_as(str(path))
        assert full_saves == [str(path)]
    finally:
        model.close()


def test_orphans_persisted_by_an_earlier_incremental_save_sit_below_the_watermark(
    tmp_path, monkeypatch
) -> None:
    """Accepted residual risk (documented): an orphan an earlier incremental
    save already wrote is below the new watermark, so a later incremental save
    never sees it; only a full save prunes it."""
    from model.save_compaction import ORPHAN_FALLBACK_MIN_BYTES, unreachable_xrefs

    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        _add_orphan(model.doc, ORPHAN_FALLBACK_MIN_BYTES - 1)
        model.save_as(str(path))  # small: incremental, persisted
        assert full_saves == []
        assert unreachable_xrefs(model.doc, from_xref=model.persisted_xref_length) == []
        model.save_as(str(path))  # still incremental: below the watermark
        assert full_saves == []
        model.use_incremental_save = False
        model.save_as(str(path))  # a full save finally prunes it
        assert path.stat().st_size < SMALL_LIMIT
    finally:
        model.close()


# ------------------------------------- repeated incremental saves on one handle (EXT-1)


def _xref_chain(path: Path) -> list[str]:
    """Walk the file's ``startxref`` -> ``/Prev`` chain; return its problems.

    ``fitz.open`` repairs a broken chain silently, which is why the older
    multi-save tests never noticed one.  This walks the raw bytes the way a
    strict reader (qpdf, a signature validator) does: every revision's
    ``startxref`` must point at a real xref section, no section may be visited
    twice, and the walk must end.  The list is the problems found, or, when
    clean, ``["revisions=<n>"]`` with the number of revisions in the chain.
    """
    data = path.read_bytes()
    starts = list(re.finditer(rb"startxref\s+(\d+)", data))
    if not starts:
        return ["no startxref"]
    offset = int(starts[-1].group(1))
    seen: set[int] = set()
    while True:
        if offset in seen:
            return [f"loop detected at {offset}"]
        seen.add(offset)
        if not 0 <= offset < len(data):
            return [f"offset {offset} out of range"]
        if data.startswith(b"xref", offset):
            end = data.find(b"startxref", offset)
            section = data[offset:end]
            trailer = section.rfind(b"trailer")
            if trailer < 0:
                return [f"no trailer in the section at {offset}"]
            head = section[trailer:]
        elif re.match(rb"\d+\s+\d+\s+obj", data[offset : offset + 32]):
            stream = data.find(b"stream", offset)
            head = data[offset:stream]
        else:
            return [f"xref not found at {offset}"]
        prev = re.search(rb"/Prev\s+(\d+)", head)
        if prev is None:
            return [f"revisions={len(seen)}"]
        offset = int(prev.group(1))


def _assert_clean_chain(path: Path, revisions: int) -> None:
    assert _xref_chain(path) == [f"revisions={revisions}"], path.read_bytes()[-400:]
    assert _eof_count(path) == revisions


def _assert_walkable_chain(path: Path) -> None:
    chain = _xref_chain(path)
    assert chain[0].startswith("revisions="), chain


def test_xref_chain_walker_flags_a_broken_chain(tmp_path) -> None:
    """Guard the guard: the walker must not pass the corrupt file EXT-1 produced."""
    path = _make_pdf(tmp_path / "doc.pdf")
    doc = fitz.open(str(path))
    try:
        doc.xref_set_key(doc.page_xref(0), "Marker", "1")
        doc.save(str(path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        doc.xref_set_key(doc.page_xref(0), "Marker", "2")  # same handle, second save
        doc.save(str(path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    finally:
        doc.close()
    assert _xref_chain(path) not in (["revisions=2"], ["revisions=3"])


def test_repeated_incremental_saves_on_one_handle_append_a_clean_revision_each(tmp_path) -> None:
    """EXT-1: PyMuPDF appends at the ORIGINAL end of file on every incremental save
    from a handle that already saved once, overwriting the earlier revision and
    pointing ``/Prev`` into the overwritten bytes.  The session must hand the
    next save a fresh handle, so each save appends after the previous one."""
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        epoch = model.xref_epoch
        _record_highlight(model)
        model.save_as(str(path))
        first = path.read_bytes()
        _assert_clean_chain(path, 2)
        assert model.xref_epoch == epoch, "an incremental save keeps the numbering"
        assert model.doc.name == str(path) and not model.doc.is_closed

        _record_highlight(model)
        model.save_as(str(path))
        assert path.read_bytes().startswith(first), "the earlier revision must stay a byte prefix"
        _assert_clean_chain(path, 3)

        model.command_manager.undo()  # a SnapshotCommand: in-memory handle, full save
        model.save_as(str(path))
        _assert_walkable_chain(path)
    finally:
        model.close()
    assert len(fitz.open(str(path))) == 1
    assert _highlight_count(path) == 1


def test_a_same_length_second_revision_does_not_loop_the_xref_chain(tmp_path) -> None:
    """EXT-1 case (a): an edit, a save, an undo and a save of equal length made
    ``/Prev`` equal to its own ``startxref`` and MuPDF then opened 0 pages."""
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        for value in ("1", "2"):
            model.doc.xref_set_key(model.doc.page_xref(0), "Marker", value)
            model.save_as(str(path))
        model.doc.xref_set_key(model.doc.page_xref(0), "Marker", "1")
        model.save_as(str(path))
    finally:
        model.close()
    _assert_clean_chain(path, 4)
    reopened = fitz.open(str(path))
    try:
        assert len(reopened) == 1
        assert reopened.xref_get_key(reopened.page_xref(0), "Marker") == ("int", "1")
    finally:
        reopened.close()


def test_repeated_saves_with_no_edits_keep_the_chain_valid(tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        for _ in range(3):
            model.save_as(str(path))
            _assert_walkable_chain(path)
    finally:
        model.close()
    assert len(fitz.open(str(path))) == 1


def test_repeated_incremental_saves_keep_an_encrypted_session_unlocked(tmp_path) -> None:
    path = _make_pdf(tmp_path / "enc.pdf", encrypted=True)
    model = _open(path, incremental=True, password="user-secret")
    try:
        for value in ("1", "2", "3"):
            model.doc.xref_set_key(model.doc.page_xref(0), "Marker", value)
            model.save_as(str(path))
            assert not model.doc.is_encrypted, "the reopened handle must be re-authenticated"
            assert model.doc.page_count == 1
            assert "hello world" in model.doc[0].get_text()
    finally:
        model.close()
    _assert_walkable_chain(path)


def test_a_failed_reopen_after_an_incremental_save_forces_the_next_save_to_a_full_one(
    tmp_path, monkeypatch
) -> None:
    """If the handle cannot be replaced after an incremental save, it is spent:
    the next save may not append from it again (that is the EXT-1 corruption)."""
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        real_reopen = model._reopen_doc_after_save
        calls: list[str] = []

        def _flaky(target: str):
            calls.append(target)
            if len(calls) == 1:
                raise OSError("reopen failed (injected)")
            return real_reopen(target)

        monkeypatch.setattr(model, "_reopen_doc_after_save", _flaky)
        model.doc.xref_set_key(model.doc.page_xref(0), "Marker", "1")
        model.save_as(str(path))
        assert full_saves == []
        model.doc.xref_set_key(model.doc.page_xref(0), "Marker", "2")
        model.save_as(str(path))
        assert full_saves == [str(path)], "a spent handle must take the full save"
        assert model.doc.xref_get_key(model.doc.page_xref(0), "Marker") == ("int", "2")
    finally:
        model.close()
    _assert_walkable_chain(path)
    reopened = fitz.open(str(path))
    try:
        assert len(reopened) == 1
        assert reopened.xref_get_key(reopened.page_xref(0), "Marker") == ("int", "2")
    finally:
        reopened.close()


def test_real_file_saved_repeatedly_passes_a_strict_reader(tmp_path) -> None:
    """EXT-1 on a real file: ``test_files/1.pdf`` carries the editor's watermark
    attachment, which every save re-adds, so even zero edits dirtied it.  qpdf
    (through pikepdf) is the strict reader the old multi-save tests lacked."""
    import shutil

    pikepdf = pytest.importorskip("pikepdf")
    source = ROOT / "test_files" / "1.pdf"
    if not source.is_file():
        pytest.skip("test_files/1.pdf not available")
    path = tmp_path / "real.pdf"
    shutil.copy(source, path)
    model = _open(path, incremental=True)
    try:
        for step in range(3):
            if step:
                model.tools.annotation.add_highlight(
                    1, fitz.Rect(72, 90 + 20 * step, 200, 105 + 20 * step), (1.0, 1.0, 0.0, 1.0)
                )
            model.save_as(str(path))
            with pikepdf.open(str(path)) as checked:
                assert checked.check_pdf_syntax() == [], f"save {step}"
    finally:
        model.close()


def test_signed_doc_repeated_incremental_saves_keep_the_signed_prefix_and_a_valid_chain(
    tmp_path,
) -> None:
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = _open(path, incremental=True)
    try:
        for value in ("1", "2", "3"):
            model.doc.xref_set_key(model.doc.page_xref(0), "Marker", value)
            model.save_as(str(path))
            assert path.read_bytes().startswith(original)
    finally:
        model.close()
    _assert_walkable_chain(path)
    assert _eof_count(path) == 4


# ---------------------------------------------------------------- undo / redo across saves


def test_tier0_undo_and_redo_survive_a_non_secure_pruning_save(tmp_path) -> None:
    """Non-secure counterpart of the garbage=4 relocation tests: the pruning
    full save over the open file keeps the numbering, so the retained PatchSet
    replays as-is (no STALE) and the stream bytes round-trip exactly."""
    import test_text_commit_persistence as persistence
    from model.text_commit.dto import TextCommitSettings

    pdf_path = tmp_path / "tier0.pdf"
    persistence._write_renumberable_pdf(pdf_path)
    model = persistence._open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        original_streams = persistence._content_stream_bytes(model)
        persistence._edit_cmd(model, persistence.TARGET, persistence.REPLACEMENT)
        committed = persistence._content_stream_bytes(model)
        assert committed != original_streams
        model.use_incremental_save = False
        page_xref = model.doc[0].xref
        orphan = _add_orphan(model.doc)
        epoch = model.xref_epoch
        model.save_as(str(pdf_path))
        assert pdf_path.stat().st_size < SMALL_LIMIT
        assert model.doc.xref_object(orphan) == "null"
        assert model.doc[0].xref == page_xref
        assert model.xref_epoch == epoch
        assert persistence._content_stream_bytes(model) == committed

        assert model.command_manager.undo() is True
        assert persistence._content_stream_bytes(model) == original_streams
        assert model.doc[0].xref == page_xref
        assert model.command_manager.redo() is True
        assert persistence._content_stream_bytes(model) == committed
        assert persistence.REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_rebuild_undo_save_writes_no_orphans_and_redo_survives(tmp_path) -> None:
    import test_page_snapshot_identity as tpsi
    from model.save_compaction import unreachable_xrefs

    path = tpsi._layered_pdf(tmp_path / "layered.pdf")
    model = tpsi._open(path)
    try:
        pristine = tpsi._state(model)
        tpsi._do_rebuild(model)
        rebuilt = tpsi._state(model)
        assert model.command_manager.undo() is True
        assert unreachable_xrefs(model.doc), "the undone rebuild must leave live orphans"
        out = tmp_path / "saved.pdf"
        model.save_as(str(out))
        _assert_no_unreachable_in_file(out)
        assert model.command_manager.redo() is True
        tpsi._assert_state_equal(tpsi._state(model), rebuilt)
        assert model.command_manager.undo() is True
        tpsi._assert_state_equal(tpsi._state(model), pristine)
    finally:
        model.close()


def test_undo_after_a_pruning_save_redoes_into_slots_the_save_freed(tmp_path, monkeypatch) -> None:
    """rebuild kept -> save -> undo -> save -> redo -> save, every step: the page
    text and render are right, ``xref_length`` never shrinks, and a FULL save
    leaves no unreachable object.  After the first save the rebuild's objects sit
    below the persisted watermark, so an incremental save after the undo cannot
    detect them (the documented residual risk): there the unreachable set is only
    allowed to hold objects an earlier save already persisted."""
    import test_page_snapshot_identity as tpsi
    from model.save_compaction import unreachable_xrefs

    path = tpsi._layered_pdf(tmp_path / "layered.pdf")
    model = tpsi._open(path)
    try:
        full_saves = _spy_full_saves(model, monkeypatch)
        tpsi._do_rebuild(model)
        replacement = tpsi.nsl.REPLACEMENT
        target = tpsi.nsl.TARGET
        lengths: list[int] = [model.doc.xref_length()]
        previous_size = 0

        def _check(label: str, want_text: str, absent: str) -> None:
            nonlocal previous_size
            before_full = len(full_saves)
            model.save_as(str(path))
            lengths.append(model.doc.xref_length())
            assert lengths[-1] >= lengths[-2], f"{label}: xref_length shrank"
            assert want_text in model.doc[0].get_text(), label
            assert absent not in model.doc[0].get_text(), label
            assert model.doc[0].get_pixmap(dpi=40).samples != b"", label
            saved = fitz.open(str(path))
            try:
                assert want_text in saved[0].get_text(), label
                unreachable = unreachable_xrefs(saved)
                if len(full_saves) > before_full:
                    assert unreachable == [], f"{label}: a full save must prune everything"
                else:
                    assert max(unreachable, default=0) < previous_size, (
                        f"{label}: an incremental save may only carry objects "
                        "persisted by an earlier save"
                    )
                previous_size = saved.xref_length()
            finally:
                saved.close()

        _check("save kept rebuild", replacement, target)
        assert model.command_manager.undo() is True
        _check("save after undo", target, replacement)
        assert model.command_manager.redo() is True
        _check("save after redo", replacement, target)
    finally:
        model.close()


def test_undo_of_a_whole_doc_snapshot_between_a_rebuild_and_a_save_still_restores(tmp_path) -> None:
    import test_page_snapshot_identity as tpsi

    path = tpsi._layered_pdf(tmp_path / "layered.pdf")
    model = tpsi._open(path)
    try:
        pristine = tpsi._state(model)
        tpsi._do_rebuild(model)
        epoch = model.xref_epoch
        _record_snapshot(
            model,
            lambda: model.doc[0].set_rotation(90),
            command_type="rotate_pages",
            affected_pages=[1],
            description="rotate",
        )
        model.use_incremental_save = False
        model.save_as(str(path))
        assert model.xref_epoch == epoch  # pruning keeps the numbering
        _assert_no_unreachable_in_file(path)
        assert model.command_manager.undo() is True  # the SnapshotCommand
        assert model.xref_epoch == epoch
        assert model.command_manager.undo() is True  # the rebuild, in place
        tpsi._assert_state_equal(tpsi._state(model), pristine, ignore=("page_xref",))
    finally:
        model.close()


# ---------------------------------------------------------------- PERS-1: a live handle never reads a file its session gave up


def _make_three_page_pdf(path: Path) -> Path:
    doc = fitz.open()
    for i in range(3):
        doc.new_page().insert_text((72, 100), f"ORIGINAL PAGE {i + 1}", fontsize=12.0)
    doc.save(str(path))
    doc.close()
    return path


def _page_texts(path: Path) -> list[str]:
    doc = fitz.open(str(path))
    try:
        return [page.get_text().strip() for page in doc]
    finally:
        doc.close()


def _live_texts(model: PDFModel) -> list[str]:
    return [model.doc[i].get_text().strip() for i in range(len(model.doc))]


@pytest.mark.parametrize("rewrite", ["plain_full_save", "orphan_fallback", "watermarked_save_as"])
@pytest.mark.parametrize("tab1_watermark", [False, True])
def test_save_as_away_then_rewriting_the_original_in_another_tab_leaves_the_first_tab_intact(
    tmp_path, rewrite, tab1_watermark
) -> None:
    """Tab 1 Save-As'd A to B; tab 2 reopens A and rewrites it in place (the
    default Ctrl+S after a legacy rebuild).  Tab 1 must not read A any more:
    its unread pages used to turn blank and its next save clobbered a good B."""
    a = _make_three_page_pdf(tmp_path / "A.pdf")
    b = tmp_path / "B.pdf"
    model = PDFModel()
    try:
        model.open_pdf(str(a))
        tab1 = model.get_active_session_id()
        model.doc[0].insert_text((72, 300), "TAB1 EDIT")
        model.edit_count += 1
        if tab1_watermark:
            model.tools.watermark.add_watermark([1], "DRAFT")  # prepared-doc save branch
        model.save_as(str(b))

        model.open_pdf(str(a), append=True)
        tab2 = model.get_active_session_id()
        assert tab2 != tab1
        model.doc[1].insert_text((72, 300), "TAB2 EDIT")
        # grow page 1's own stream so every later object moves in the rewritten
        # file: a tab still reading A at the old offsets would read garbage
        grown = model.doc[0].get_contents()[0]
        model.doc.update_stream(grown, model.doc.xref_stream(grown) + b"\n% pad\n" * 2000)
        model.edit_count += 1
        if rewrite == "orphan_fallback":
            model.use_incremental_save = True
            _add_orphan(model.doc)
        elif rewrite == "plain_full_save":
            model.use_incremental_save = False
        else:
            model.use_incremental_save = False
            model.tools.watermark.add_watermark([2], "DRAFT")
        model.save_as(str(a))
        assert "TAB2 EDIT" in _page_texts(a)[1]

        model.activate_session(tab1)
        live = _live_texts(model)
        assert live[1] == "ORIGINAL PAGE 2" and live[2] == "ORIGINAL PAGE 3", live
        assert "ORIGINAL PAGE 1" in live[0] and "TAB1 EDIT" in live[0], live
        model.doc[2].insert_text((72, 400), "TAB1 SECOND EDIT")
        model.edit_count += 1
        model.save_as(str(b))
    finally:
        model.close()
    saved = _page_texts(b)
    assert "ORIGINAL PAGE 1" in saved[0] and "TAB1 EDIT" in saved[0], saved
    assert saved[1] == "ORIGINAL PAGE 2" and "TAB2" not in saved[1], saved
    assert "ORIGINAL PAGE 3" in saved[2] and "TAB1 SECOND EDIT" in saved[2], saved


def test_save_as_another_path_keeps_the_live_numbering_and_epoch_while_dropping_the_source_file(
    tmp_path,
) -> None:
    path = _make_three_page_pdf(tmp_path / "A.pdf")
    out = tmp_path / "copy.pdf"
    model = _open(path, incremental=False)
    try:
        orphan = _add_orphan(model.doc)
        epoch = model.xref_epoch
        page_xrefs = [model.doc.page_xref(i) for i in range(3)]
        model.save_as(str(out))
        assert model.xref_epoch == epoch
        assert [model.doc.page_xref(i) for i in range(3)] == page_xrefs
        assert len(model.doc.xref_stream_raw(orphan)) == ORPHAN_BYTES  # live doc not pruned
        assert Path(model.doc.name or "").resolve() != path.resolve(), "the handle must not read A any more"
        assert _live_texts(model) == [f"ORIGINAL PAGE {i + 1}" for i in range(3)]
        # a second Save As must not stack another materialised copy
        temp_files = list(Path(model.temp_dir.name).glob("live_*.pdf"))
        model.save_as(str(tmp_path / "copy2.pdf"))
        assert list(Path(model.temp_dir.name).glob("live_*.pdf")) == temp_files
        path.write_bytes(b"clobbered")  # A is free: the live doc is unaffected
        assert _live_texts(model) == [f"ORIGINAL PAGE {i + 1}" for i in range(3)]
    finally:
        model.close()


def test_encrypted_save_as_another_path_keeps_the_live_handle_authenticated(tmp_path) -> None:
    path = _make_pdf(tmp_path / "enc.pdf", encrypted=True)
    out = tmp_path / "enc_copy.pdf"
    model = _open(path, incremental=False, password="user-secret")
    try:
        model.save_as(str(out))
        path.write_bytes(b"clobbered")
        assert "hello world" in model.doc[0].get_text()
    finally:
        model.close()


def test_save_as_refuses_a_target_another_tab_still_reads_even_when_its_path_moved_on(tmp_path) -> None:
    """The path map is not the whole truth: a session whose handle still reads a
    file must block writes to it (the guard reads the live handles)."""
    a = _make_three_page_pdf(tmp_path / "A.pdf")
    c = _make_three_page_pdf(tmp_path / "C.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(a))
        tab1 = model.get_active_session_id()
        model.open_pdf(str(c), append=True)
        # simulate a session whose bookkeeping moved on while its handle did not
        session = model._sessions_by_id[tab1]
        model._path_to_session_id.pop(session.canonical_path, None)
        session.canonical_path = model._canonicalize_path(str(tmp_path / "elsewhere.pdf"))
        before = a.read_bytes()
        with pytest.raises(RuntimeError):
            model.save_as(str(a))
        assert a.read_bytes() == before
    finally:
        model.close()


@pytest.mark.parametrize("target_of", ["active", "other_tab"])
def test_external_exports_refuse_to_overwrite_a_file_an_open_tab_reads(tmp_path, target_of) -> None:
    a = _make_three_page_pdf(tmp_path / "A.pdf")
    c = _make_three_page_pdf(tmp_path / "C.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(a))
        model.open_pdf(str(c), append=True)  # active = C
        target = c if target_of == "active" else a
        before = target.read_bytes()
        with pytest.raises(RuntimeError):
            model.export_pages([1], str(target))
        extra = fitz.open()
        extra.new_page()
        try:
            with pytest.raises(RuntimeError):
                model.save_external_document(extra, target)
        finally:
            extra.close()
        assert target.read_bytes() == before
        free = tmp_path / "free.pdf"
        model.export_pages([1], str(free))
        assert _page_texts(free) == ["ORIGINAL PAGE 1"]
    finally:
        model.close()


def test_closing_a_save_as_session_removes_its_private_live_copy(tmp_path) -> None:
    path = _make_three_page_pdf(tmp_path / "A.pdf")
    model = _open(path, incremental=False)
    try:
        sid = model.get_active_session_id()
        model.save_as(str(tmp_path / "copy.pdf"))
        assert len(_live_copies(model)) == 1
        model.close_session(sid)
        assert _live_copies(model) == []
    finally:
        model.close()


def test_save_as_of_an_in_memory_doc_makes_no_private_copy(tmp_path) -> None:
    path = _make_three_page_pdf(tmp_path / "A.pdf")
    model = _open(path, incremental=False)
    try:
        model._roundtrip_live_doc(garbage=0, deflate=False)  # in-memory handle: nothing lazy on disk
        assert model._backing_file(model.doc) is None  # name is just "pdf"
        model.save_as(str(tmp_path / "copy.pdf"))
        assert _live_copies(model) == []
    finally:
        model.close()



# ------------------------------------- private live copy survives no reinstall (round 6 FS-2)


def _live_copies(model: PDFModel) -> list[Path]:
    return sorted(Path(model.temp_dir.name).glob("live_*.pdf"))


def test_snapshot_restore_after_save_as_removes_the_private_live_copy(tmp_path) -> None:
    """A whole-document snapshot restore swaps the handle for an in-memory doc;
    the ``live_*.pdf`` it was reading must go with the closed handle."""
    path = _make_three_page_pdf(tmp_path / "A.pdf")
    model = _open(path, incremental=False)
    try:
        sid = model.get_active_session_id()
        model.save_as(str(tmp_path / "copy.pdf"))
        assert len(_live_copies(model)) == 1
        model._restore_doc_from_snapshot(model._capture_doc_snapshot())
        assert model._backing_file(model.doc) is None  # now in-memory
        assert len(model.doc) == 3
        assert _live_copies(model) == []
        model.close_session(sid)
        assert _live_copies(model) == []
    finally:
        model.close()


def test_roundtrip_live_doc_after_save_as_removes_the_private_live_copy(tmp_path) -> None:
    path = _make_three_page_pdf(tmp_path / "A.pdf")
    model = _open(path, incremental=False)
    try:
        model.save_as(str(tmp_path / "copy.pdf"))
        assert len(_live_copies(model)) == 1
        model._roundtrip_live_doc(garbage=1, deflate=True)
        assert model._backing_file(model.doc) is None
        assert len(model.doc) == 3
        assert _live_copies(model) == []
    finally:
        model.close()


def test_snapshot_command_undo_after_save_as_leaves_no_live_copy_once_tabs_close(tmp_path) -> None:
    """Open -> Save As -> page op -> undo -> close, three times on one model."""
    model = PDFModel()
    try:
        for i in range(3):
            src = _make_three_page_pdf(tmp_path / f"src{i}.pdf")
            sid = model.open_pdf(str(src), append=True)
            model.save_as(str(tmp_path / f"out{i}.pdf"))
            _record_snapshot(
                model,
                lambda: model.delete_pages([1]),
                command_type="delete_pages",
                description="delete",
            )
            model.command_manager.undo()
            assert len(model.doc) == 3
            model.command_manager.redo()
            assert len(model.doc) == 2
            model.close_session(sid)
            assert _live_copies(model) == []
        assert list(Path(model.temp_dir.name).iterdir()) == []
    finally:
        model.close()


def test_reinstall_after_rebind_to_recovery_copy_removes_that_copy_too(tmp_path) -> None:
    """The session rebound to a ``recover_*.pdf`` is the same bug class."""
    path = _make_three_page_pdf(tmp_path / "A.pdf")
    model = _open(path, incremental=False)
    try:
        recovery = Path(model.temp_dir.name) / "recover_test.pdf"
        model._save_doc(model.doc, str(recovery))
        epoch = model.xref_epoch
        model.doc.close()
        assert model._rebind_to_recovery_copy(recovery, epoch)
        assert model._model_temp_file_of(model.doc) == recovery.resolve()
        model._restore_doc_from_snapshot(model._capture_doc_snapshot())
        assert not recovery.exists()
        assert len(model.doc) == 3
    finally:
        model.close()


def test_reinstall_onto_the_same_private_copy_keeps_it(tmp_path) -> None:
    """Re-binding to the file the handle already reads must not delete it."""
    path = _make_three_page_pdf(tmp_path / "A.pdf")
    model = _open(path, incremental=False)
    try:
        model.save_as(str(tmp_path / "copy.pdf"))
        (private,) = _live_copies(model)
        old = model.doc
        old.close()
        model.doc = fitz.open(str(private))
        assert private.exists()
        assert len(model.doc) == 3
    finally:
        model.close()


# ---------------------------------------------------------------- failed install over the open file (PERS-2)


def _page_text(path: Path) -> str:
    doc = fitz.open(str(path))
    try:
        return doc[0].get_text()
    finally:
        doc.close()


def _edit_and_orphan(model: PDFModel, *, orphan: bool) -> None:
    model.doc[0].insert_text((72, 150), "MY EDIT", fontsize=12.0)
    model.edit_count += 1
    if orphan:
        # random bytes: compression cannot shrink them below the 64 KiB threshold
        xref = _new_object(model.doc, "<<>>")
        model.doc.update_stream(xref, os.urandom(ORPHAN_BYTES), compress=False)


def _fail_install(patch, how: str) -> None:
    """Make the step that overwrites the target file fail (``how``)."""
    import model.pdf_model as pm

    real_replace = pm.os.replace

    if how == "copy":

        def _copy2(src, dst, *a, **k):
            raise PermissionError(13, "Permission denied (injected)")

        patch.setattr(pm.shutil, "copy2", _copy2)
    elif how == "partial_copy":

        def _partial(src, dst, *a, **k):
            data = Path(src).read_bytes()
            Path(dst).write_bytes(data[: len(data) // 2])
            raise OSError(28, "No space left on device (injected)")

        patch.setattr(pm.shutil, "copy2", _partial)
    elif how == "replace":

        def _replace(src, dst, *a, **k):
            if Path(str(src)).name.startswith("."):
                raise PermissionError(13, "sharing violation (injected)")
            return real_replace(src, dst, *a, **k)

        patch.setattr(pm.os, "replace", _replace)
    else:  # pragma: no cover
        raise AssertionError(how)


@pytest.mark.parametrize("how", ["copy", "partial_copy", "replace"])
@pytest.mark.parametrize("route", ["orphan_fallback", "plain_full_save"])
def test_a_failed_overwrite_of_the_open_file_keeps_the_session_edits_and_the_real_error(
    tmp_path, monkeypatch, how, route
) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    before = path.read_bytes()
    model = _open(path, incremental=(route == "orphan_fallback"))
    try:
        _edit_and_orphan(model, orphan=(route == "orphan_fallback"))
        if route == "orphan_fallback":
            assert model._session_orphans_block_incremental()
        with monkeypatch.context() as patch:
            _fail_install(patch, how)
            with pytest.raises(OSError) as raised:
                model.save_as(str(path))
        assert raised.value.errno in (13, 28), "the retry must not mask the real error"
        # the target is byte-identical (no truncation), the session is alive and still dirty
        assert path.read_bytes() == before
        assert not model.doc.is_closed
        assert "MY EDIT" in model.doc[0].get_text()
        assert model.edit_count == 1
        # a retry once the obstacle is gone installs the edit
        model.save_as(str(path))
        assert "MY EDIT" in _page_text(path)
        assert "MY EDIT" in model.doc[0].get_text()
        assert model.edit_count == 0
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf"], "no staging file is left"


def test_a_failed_install_after_the_close_rebinds_the_live_doc_with_numbering_and_epoch(
    tmp_path, monkeypatch
) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False)
    try:
        _edit_and_orphan(model, orphan=False)
        epoch, length = model.xref_epoch, model.doc.xref_length()
        with monkeypatch.context() as patch:
            _fail_install(patch, "replace")
            with pytest.raises(PermissionError):
                model.save_as(str(path))
        assert model.xref_epoch == epoch, "garbage=1 keeps the numbering: snapshots stay valid"
        assert model.doc.xref_length() == length
        backing = model._backing_file(model.doc)
        assert backing is not None and backing != path.resolve()
        assert model._model_temp_file_of(model.doc) is not None
        sid = model.get_active_session_id()
        model.close_session(sid)
        assert list(Path(model.temp_dir.name).glob("*.pdf")) == []
    finally:
        model.close()


def test_a_failed_install_over_an_encrypted_file_keeps_the_live_handle_authenticated(
    tmp_path, monkeypatch
) -> None:
    path = _make_pdf(tmp_path / "enc.pdf", encrypted=True)
    model = _open(path, incremental=False, password="user-secret")
    try:
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            _fail_install(patch, "replace")
            with pytest.raises(PermissionError):
                model.save_as(str(path))
        assert "MY EDIT" in model.doc[0].get_text(), "the rebound handle must be re-authenticated"
        model.save_as(str(path))
    finally:
        model.close()
    _assert_encrypted_file_has_text(path, "MY EDIT")


@pytest.mark.parametrize("how", ["copy", "replace"])
def test_a_failed_overwrite_in_the_prepared_doc_branch_keeps_the_session_edits(
    tmp_path, monkeypatch, how
) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    before = path.read_bytes()
    model = _open(path, incremental=False)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            _fail_install(patch, how)
            with pytest.raises(PermissionError) as raised:
                model.save_as(str(path))
        assert raised.value.errno == 13
        assert path.read_bytes() == before
        assert not model.doc.is_closed
        assert "MY EDIT" in model.doc[0].get_text()
        model.save_as(str(path))
        assert "MY EDIT" in _page_text(path)
    finally:
        model.close()


def test_an_incremental_save_failure_still_falls_back_to_the_full_save(tmp_path, monkeypatch) -> None:
    """Characterization: only the *incremental attempt* is retried as a full save."""
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=True)
    try:
        _edit_and_orphan(model, orphan=False)
        real = model._save_doc

        def _boom(doc, target, *, garbage=0, incremental=False):
            if incremental:
                raise RuntimeError("incremental unavailable (injected)")
            return real(doc, target, garbage=garbage, incremental=incremental)

        monkeypatch.setattr(model, "_save_doc", _boom)
        model.save_as(str(path))
    finally:
        model.close()
    assert "MY EDIT" in _page_text(path)


# ---------------------------------------------------------------- the secure sibling of PERS-2 (FS-1)


@pytest.mark.parametrize("encrypted", [False, True])
def test_a_failed_secure_overwrite_of_the_open_file_keeps_the_session_edits(
    tmp_path, monkeypatch, encrypted
) -> None:
    import model.pdf_model as pm

    path = _make_pdf(tmp_path / "doc.pdf", encrypted=encrypted)
    before = path.read_bytes()
    model = _open(path, incremental=False, password="user-secret" if encrypted else None, secure=True)
    try:
        _edit_and_orphan(model, orphan=False)
        epoch_before = model.xref_epoch
        seen: list[int] = []
        with monkeypatch.context() as patch:
            _fail_install(patch, "replace")
            failing_replace = pm.os.replace

            def _spy(src, dst, *a, **k):
                seen.append(model.xref_epoch)
                return failing_replace(src, dst, *a, **k)

            patch.setattr(pm.os, "replace", _spy)
            with pytest.raises(PermissionError) as raised:
                model.save_as(str(path))
        assert raised.value.errno == 13, "the real error must surface"
        # the garbage=4 save renumbered the live doc (new epoch); the rebind keeps that epoch
        epoch = seen[-1]
        assert epoch != epoch_before
        assert path.read_bytes() == before, "the target is untouched"
        assert not model.doc.is_closed
        assert "MY EDIT" in model.doc[0].get_text(), "the unsaved edit must not be lost"
        assert model.edit_count == 1, "the session is still dirty"
        assert model.xref_epoch == epoch, "the rebind keeps the numbering the save produced"
        backing = model._backing_file(model.doc)
        assert backing is not None and backing != path.resolve()
        assert model._model_temp_file_of(model.doc) is not None
        # a retry once the obstacle is gone installs the edit, sanitised
        model.save_as(str(path))
        if not encrypted:
            assert "MY EDIT" in _page_text(path)
        assert "MY EDIT" in model.doc[0].get_text()
        assert model.edit_count == 0
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf"], "no staging file is left"
    if encrypted:
        _assert_encrypted_file_has_text(path, "MY EDIT")


def test_a_secure_save_whose_reopen_fails_keeps_the_session_alive_on_a_copy(
    tmp_path, monkeypatch
) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False, secure=True)
    try:
        _edit_and_orphan(model, orphan=False)
        real_reopen = model._reopen_doc_after_save
        target = str(path.resolve())

        def _flaky(p):
            if str(p) == target:
                raise RuntimeError("reopen failed (injected)")
            return real_reopen(p)

        monkeypatch.setattr(model, "_reopen_doc_after_save", _flaky)
        model.save_as(str(path))  # the target IS written; only the reopen failed
        monkeypatch.undo()
        assert "MY EDIT" in _page_text(path), "the save itself succeeded"
        assert not model.doc.is_closed, "the session must not be left on a closed handle"
        assert "MY EDIT" in model.doc[0].get_text()
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf"]


def test_a_failed_secure_overwrite_in_the_prepared_doc_branch_rebinds_to_the_live_doc(
    tmp_path, monkeypatch
) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    before = path.read_bytes()
    model = _open(path, incremental=False, secure=True)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        _edit_and_orphan(model, orphan=False)
        live_before = model.doc[0].get_text()
        with monkeypatch.context() as patch:
            _fail_install(patch, "replace")
            with pytest.raises(PermissionError):
                model.save_as(str(path))
        assert path.read_bytes() == before
        assert not model.doc.is_closed
        # the recovery copy is the LIVE doc, not the staged watermark clone
        assert model.doc[0].get_text() == live_before
        model.save_as(str(path))
        assert "MY EDIT" in _page_text(path)
    finally:
        model.close()


def test_a_secure_save_that_cannot_make_its_recovery_copy_leaves_everything_untouched(
    tmp_path, monkeypatch
) -> None:
    import model.pdf_model as pm

    path = _make_pdf(tmp_path / "doc.pdf")
    before = path.read_bytes()
    model = _open(path, incremental=False, secure=True)
    try:
        _edit_and_orphan(model, orphan=False)
        live = model.doc

        def _boom(*a, **k):
            raise OSError(28, "No space left on device (injected)")

        monkeypatch.setattr(pm.shutil, "copy2", _boom)
        with pytest.raises(OSError):
            model.save_as(str(path))
        monkeypatch.undo()
        assert model.doc is live and not live.is_closed, "the live handle was never closed"
        assert path.read_bytes() == before
        assert "MY EDIT" in model.doc[0].get_text()
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf"]


def test_a_successful_secure_overwrite_of_the_open_file_leaves_no_recovery_copy(tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False, secure=True)
    try:
        _edit_and_orphan(model, orphan=False)
        model.save_as(str(path))
        assert "MY EDIT" in _page_text(path)
        assert "MY EDIT" in model.doc[0].get_text()
        assert model._backing_file(model.doc) == path.resolve()
        assert list(Path(model.temp_dir.name).glob("*.pdf")) == []
        assert model.persisted_xref_length == model.doc.xref_length()
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf"]


def test_a_failed_snapshot_restore_keeps_the_current_doc(monkeypatch, tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False)
    try:
        live = model.doc
        with pytest.raises(Exception):
            model._restore_doc_from_snapshot(b"not a pdf")
        assert model.doc is live and not live.is_closed
    finally:
        model.close()


# ------------------------------- double failure: the replace and every reopen fail (ERR-1)


def _reopen_always_fails(_path):
    raise RuntimeError("reopen failed (injected)")


def _recovery_copies(model: PDFModel) -> list[Path]:
    return sorted(Path(model.temp_dir.name).glob("recover_*.pdf")) + sorted(
        Path(model.temp_dir.name).glob("save_*.pdf")
    )


@pytest.mark.parametrize("secure", [False, True], ids=["plain", "secure"])
def test_replace_failure_with_a_failing_recovery_reopen_keeps_the_session_in_memory(
    tmp_path, monkeypatch, secure
) -> None:
    """The recovery file cannot be opened by path: the session must still survive
    (opened from the file's bytes) instead of staying on the closed handle."""
    path = _make_pdf(tmp_path / "doc.pdf")
    before = path.read_bytes()
    model = _open(path, incremental=False, secure=secure)
    try:
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            _fail_install(patch, "replace")
            patch.setattr(model, "_reopen_doc_after_save", _reopen_always_fails)
            with pytest.raises(PermissionError) as raised:
                model.save_as(str(path))
        assert raised.value.errno == 13, "the real error must surface"
        assert path.read_bytes() == before, "the target is untouched"
        assert not model.doc.is_closed, "the session must not be left on a closed handle"
        assert "MY EDIT" in model.doc[0].get_text(), "the unsaved edit must not be lost"
        assert model.edit_count == 1, "the session is still dirty"
        assert _recovery_copies(model) == [], "an in-memory session needs no recovery file"
        # the obstacle is gone: a retry installs the edit
        model.save_as(str(path))
        assert "MY EDIT" in _page_text(path)
        assert model.edit_count == 0
    finally:
        model.close()


@pytest.mark.parametrize("secure", [False, True], ids=["plain", "secure"])
def test_written_target_with_failing_reopens_keeps_the_session_alive(tmp_path, monkeypatch, secure) -> None:
    """The target holds the edit; neither reopen works by path: no false failure."""
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False, secure=secure)
    try:
        _edit_and_orphan(model, orphan=False)
        monkeypatch.setattr(model, "_reopen_doc_after_save", _reopen_always_fails)
        model.save_as(str(path))  # must not raise: the file was written, the session lives on
        monkeypatch.undo()
        assert "MY EDIT" in _page_text(path)
        assert not model.doc.is_closed
        assert "MY EDIT" in model.doc[0].get_text()
        assert model.edit_count == 0, "the save completed"
        assert _recovery_copies(model) == []
    finally:
        model.close()


@pytest.mark.parametrize("secure", [False, True], ids=["plain", "secure"])
def test_replace_failure_when_the_session_cannot_be_rebound_preserves_the_recovery_copy(
    tmp_path, monkeypatch, secure
) -> None:
    """Nothing can reopen the recovery copy: it is the only copy of the edits, so it
    must survive and the error must say where it is (not a plain retryable failure)."""
    from model.pdf_model import SaveRecoveryError

    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False, secure=secure)
    try:
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            _fail_install(patch, "replace")
            patch.setattr(model, "_reopen_doc_after_save", _reopen_always_fails)
            patch.setattr(model, "_open_recovery_in_memory", _reopen_always_fails)
            with pytest.raises(SaveRecoveryError) as raised:
                model.save_as(str(path))
        assert isinstance(raised.value.__cause__, PermissionError)
        assert raised.value.target_written is False
        survivors = _recovery_copies(model)
        assert len(survivors) == 1, "the only copy holding the edits must survive"
        assert "MY EDIT" in _page_text(survivors[0])
        assert raised.value.recovery_path == survivors[0]
        assert str(survivors[0]) in str(raised.value), "the user is told where the edits are"
        assert "MY EDIT" not in _page_text(path)
    finally:
        model.close()


@pytest.mark.parametrize("secure", [False, True], ids=["plain", "secure"])
def test_written_target_when_the_session_cannot_be_rebound_says_the_file_was_saved(
    tmp_path, monkeypatch, secure
) -> None:
    from model.pdf_model import SaveRecoveryError

    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False, secure=secure)
    try:
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            patch.setattr(model, "_reopen_doc_after_save", _reopen_always_fails)
            patch.setattr(model, "_open_recovery_in_memory", _reopen_always_fails)
            with pytest.raises(SaveRecoveryError) as raised:
                model.save_as(str(path))
        assert raised.value.target_written is True
        assert "MY EDIT" in _page_text(path), "the target was written"
        survivors = _recovery_copies(model)
        assert len(survivors) == 1 and "MY EDIT" in _page_text(survivors[0])
        assert str(path.resolve()) in str(raised.value)
    finally:
        model.close()


# ---------------------------------------------------------------- long target paths (FS-3)
#
# The hidden staging file beside the target used to be ``.{stem}.{uuid32}.<tag>.pdf``:
# 38-42 characters longer than the target.  A target that opens and edits fine at
# 235 characters then failed every save back to its own path on default Windows
# (LongPathsEnabled=0, MAX_PATH 260) with WinError 3.  A stem over ~209 characters
# also overflowed the 255-character name limit.


def _ext(path) -> str:
    """Extended-length spelling so the TEST can build/inspect >=248-char dirs on Windows."""
    text = str(path)
    return "\\\\?\\" + text if os.name == "nt" and not text.startswith("\\\\?\\") else text


def _deep_pdf(tmp_path: Path, total_len: int, stem: str) -> Path:
    """A PDF whose full path is exactly ``total_len`` characters, in nested dirs."""
    name = f"{stem}.pdf"
    remaining = total_len - len(name) - 1 - len(str(tmp_path))
    assert remaining >= 0, "tmp_path too long for the requested length"
    folder = tmp_path
    while remaining > 0:
        comp = min(remaining - 1, 100)
        if remaining - (comp + 1) == 1:  # never leave a lone separator
            comp -= 1
        folder = folder / ("d" * comp)
        remaining -= comp + 1
    os.makedirs(_ext(folder), exist_ok=True)
    target = folder / name
    assert len(str(target)) == total_len
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(_ext(target))
    doc.close()
    return target


def _no_leftovers(target: Path) -> None:
    assert os.listdir(_ext(target.parent)) == [target.name], "a staging file was left behind"


@pytest.mark.parametrize("secure", [False, True], ids=["plain", "secure"])
@pytest.mark.parametrize(
    "total_len,stem",
    [
        (235, "報" * 70),  # long CJK stem: old sibling = 235 + 42 = 277 > 259
        (255, "a"),  # short stem, deep folder: even a short staging name needs the extended form
    ],
    ids=["long_stem_235", "short_stem_255"],
)
def test_save_over_the_open_file_works_for_paths_near_the_windows_limit(
    tmp_path, total_len, stem, secure
) -> None:
    target = _deep_pdf(tmp_path, total_len, stem)
    model = PDFModel()
    try:
        model.open_pdf(str(target))
        model.use_incremental_save = False
        model.secure_save_required = secure
        _edit_and_orphan(model, orphan=False)
        model.save_as(str(target))
        assert not model.doc.is_closed
        assert "MY EDIT" in model.doc[0].get_text()
        assert model.edit_count == 0
    finally:
        model.close()
    with fitz.open(_ext(target)) as reopened:
        assert "MY EDIT" in reopened[0].get_text()
    _no_leftovers(target)


def test_secure_export_to_a_deep_new_path_stages_without_overflowing(tmp_path) -> None:
    """``save_external_document`` -> ``_atomic_full_save`` to a path that is not open."""
    target = _deep_pdf(tmp_path, 255, "a")
    out = target.with_name("b.pdf")
    model = PDFModel()
    try:
        model.secure_save_required = True
        doc = fitz.open()
        doc.new_page().insert_text((72, 100), "EXPORTED", fontsize=12.0)
        model.save_external_document(doc, out)
        doc.close()
    finally:
        model.close()
    with fitz.open(_ext(out)) as reopened:
        assert "EXPORTED" in reopened[0].get_text()
    assert sorted(os.listdir(_ext(target.parent))) == ["a.pdf", "b.pdf"]


def test_staging_sibling_name_is_independent_of_the_target_stem(tmp_path) -> None:
    from utils.path_staging import staging_sibling

    long_stem = tmp_path / ("報" * 250 + ".pdf")
    short = tmp_path / "a.pdf"
    for target in (long_stem, short):
        sibling = staging_sibling(target, "install")
        assert sibling.parent == target.parent
        assert sibling.name.startswith(".") and sibling.name.endswith(".install.pdf")
        assert len(sibling.name) <= 30, sibling.name
    assert staging_sibling(short, "install") != staging_sibling(short, "install"), "unique per call"


def test_extended_length_path_only_rewrites_what_does_not_fit() -> None:
    from utils.path_staging import WIN_MAX_FILE_PATH, extended_length_path

    short = os.path.abspath("x" * 10)
    assert extended_length_path(short) == short
    if os.name == "nt":
        long_path = "C:\\" + "d" * (WIN_MAX_FILE_PATH + 5)
        assert extended_length_path(long_path) == "\\\\?\\" + long_path
        assert extended_length_path("\\\\?\\" + long_path) == "\\\\?\\" + long_path
        unc = "\\\\srv\\share\\" + "d" * (WIN_MAX_FILE_PATH + 5)
        assert extended_length_path(unc).startswith("\\\\?\\UNC\\srv\\share\\")
    else:
        long_path = "/" + "d" * (WIN_MAX_FILE_PATH + 5)
        assert extended_length_path(long_path) == long_path


def test_strip_extended_prefix_inverts_extended_length_path() -> None:
    from utils.path_staging import strip_extended_prefix

    assert strip_extended_prefix(r"\\?\C:\a\b.pdf") == r"C:\a\b.pdf"
    unc = r"\\?\UNC\srv\share\b.pdf"
    assert strip_extended_prefix(unc) == r"\\srv\share\b.pdf"
    assert strip_extended_prefix(r"C:\a\b.pdf") == r"C:\a\b.pdf"
    assert strip_extended_prefix("/tmp/b.pdf") == "/tmp/b.pdf"


# ------------------------------------------- LS-2: no in-place write of a user file


def _partial_writer(monkeypatch) -> None:
    """``Document.save`` to a path behaves like MuPDF's path output on a full disk:
    open the destination for writing (truncating it), write part, raise."""
    real_save = fitz.Document.save

    def _failing(self, filename, *a, **k):
        if isinstance(filename, (str, os.PathLike)):
            with open(filename, "wb") as handle:
                handle.write(b"%PDF-1.7\n% partial")
            raise RuntimeError("injected: write failed mid-file (disk full)")
        return real_save(self, filename, *a, **k)  # in-memory streams (tobytes) are unaffected

    monkeypatch.setattr(fitz.Document, "save", _failing)


def _go_in_memory(model: PDFModel) -> None:
    """What a SnapshotCommand undo/redo leaves: a live doc with no file behind it."""
    model._restore_doc_from_snapshot(model.doc.tobytes())
    assert model._backing_file(model.doc) is None


def _assert_intact(path: Path, before: bytes) -> None:
    assert path.read_bytes() == before, "the user's last good file was overwritten in place"
    assert "hello world" in _page_text(path)


@pytest.mark.parametrize("route", ["same_path", "other_existing_path"])
@pytest.mark.parametrize("backing", ["file", "memory"])
def test_a_failed_full_save_never_truncates_an_existing_target(tmp_path, monkeypatch, route, backing) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    other = _make_pdf(tmp_path / "other.pdf")
    target = path if route == "same_path" else other
    before = target.read_bytes()
    model = _open(path, incremental=False)
    try:
        if backing == "memory":
            _go_in_memory(model)
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            _partial_writer(patch)
            with pytest.raises(RuntimeError, match="injected"):
                model.save_as(str(target))
        _assert_intact(target, before)
        assert not model.doc.is_closed
        assert "MY EDIT" in model.doc[0].get_text(), "the live edits survive the failed save"
        assert model.edit_count == 1
        model.save_as(str(target))  # a retry once the disk has room
        assert "MY EDIT" in _page_text(target)
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf", "other.pdf"], "no staging file is left"


@pytest.mark.parametrize("route", ["same_path", "other_existing_path"])
@pytest.mark.parametrize("backing", ["file", "memory"])
def test_a_failed_prepared_doc_save_never_truncates_an_existing_target(
    tmp_path, monkeypatch, route, backing
) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    other = _make_pdf(tmp_path / "other.pdf")
    target = path if route == "same_path" else other
    before = target.read_bytes()
    model = _open(path, incremental=False)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        if backing == "memory":
            _go_in_memory(model)
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            _partial_writer(patch)
            with pytest.raises(RuntimeError, match="injected"):
                model.save_as(str(target))
        _assert_intact(target, before)
        assert "MY EDIT" in model.doc[0].get_text()
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf", "other.pdf"], "no staging file is left"


def test_a_failed_external_export_never_truncates_an_existing_target(tmp_path, monkeypatch) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    existing = _make_pdf(tmp_path / "export.pdf")
    before = existing.read_bytes()
    model = _open(path, incremental=False)
    try:
        with monkeypatch.context() as patch:
            _partial_writer(patch)
            with pytest.raises(RuntimeError, match="injected"):
                model.export_pages([1], str(existing))
        _assert_intact(existing, before)
        model.export_pages([1], str(existing))
        assert "hello world" in _page_text(existing)
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf", "export.pdf"], "no staging file is left"


def test_a_failed_save_to_a_new_path_leaves_no_partial_file(tmp_path, monkeypatch) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False)
    try:
        _go_in_memory(model)
        with monkeypatch.context() as patch:
            _partial_writer(patch)
            with pytest.raises(RuntimeError, match="injected"):
                model.save_as(str(tmp_path / "new.pdf"))
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf"]


def test_a_successful_in_memory_save_over_the_original_replaces_it_and_leaves_no_staging(tmp_path) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    model = _open(path, incremental=False)
    try:
        _go_in_memory(model)
        _edit_and_orphan(model, orphan=False)
        model.save_as(str(path))
        assert "MY EDIT" in _page_text(path)
        assert model.edit_count == 0
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf"]


@pytest.mark.parametrize("fmt", ["png", "jpg", "tiff"])
def test_a_failed_image_export_never_truncates_an_existing_image(tmp_path, monkeypatch, fmt) -> None:
    path = _make_pdf(tmp_path / "doc.pdf")
    target = tmp_path / f"page.{fmt}"
    model = _open(path, incremental=False)
    try:
        model.export_pages([1], str(target), as_image=True, dpi=72, image_format=fmt)
        before = target.read_bytes()
        assert len(before) > 100

        def _truncating(self, filename, *a, **k):
            with open(filename, "wb") as handle:
                handle.write(b"partial")
            raise RuntimeError("injected: write failed mid-file (disk full)")

        with monkeypatch.context() as patch:
            patch.setattr(fitz.Pixmap, "save", _truncating)
            patch.setattr(fitz.Pixmap, "pil_save", _truncating)
            with pytest.raises(RuntimeError):
                model.export_pages([1], str(target), as_image=True, dpi=72, image_format=fmt)
        assert target.read_bytes() == before, "the existing image was overwritten in place"
        model.export_pages([1], str(target), as_image=True, dpi=72, image_format=fmt)  # retry works
        assert target.read_bytes()[:4] == before[:4]
    finally:
        model.close()
    assert _names_in(tmp_path) == ["doc.pdf", target.name], "no staging file is left"



# ---------------------------------------------------------------- F10-FS-1: a foreign writer rewrote the session's file


def _pages_pdf(path: Path, text: str, pages: int) -> Path:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"{text} p{i + 1}", fontsize=12.0)
    doc.save(str(path))
    doc.close()
    return path


def _insert_page_like_the_controller(model: PDFModel) -> None:
    """``PDFController.insert_blank_page``: snapshot, insert, snapshot, record."""
    _record_snapshot(
        model,
        lambda: model.insert_blank_page(1),
        command_type="insert_blank_page",
        description="insert blank page",
    )


def _overwrite_in_place(target: Path, data: bytes) -> None:
    """A foreign in-place writer (Explorer copy-overwrite, ``copy /y``, ``open('wb')``)."""
    with open(target, "r+b") as handle:
        handle.write(data)
        handle.truncate()


def _assert_refused_as_changed_on_disk(model: PDFModel, path: Path) -> None:
    from model.pdf_model import SourceChangedOnDiskError

    with pytest.raises(SourceChangedOnDiskError):
        model.save_as(str(path))


@pytest.mark.parametrize("edit", ["snapshot_command", "bare_insert"])
@pytest.mark.parametrize("incremental", [True, False], ids=["incremental", "full"])
@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_save_over_a_file_a_foreign_writer_replaced_is_refused_not_reported_as_success(
    tmp_path, edit, incremental
) -> None:
    """F10-FS-1: MuPDF holds the file with a share mode that lets any in-place
    writer rewrite it; the live handle then reads the foreign bytes.  Ctrl+S
    used to return normally (app path: a hybrid of foreign objects and the
    session's xref update) or die on the hidden staging file.  It must refuse
    up front, leave the foreign file byte for byte, and keep the session dirty."""
    src = _pages_pdf(tmp_path / "doc.pdf", "hello", 3)
    ext = _pages_pdf(tmp_path / "ext.pdf", "EXTERNAL", 9)
    model = _open(src, incremental=incremental)
    try:
        if edit == "snapshot_command":
            _insert_page_like_the_controller(model)
        else:
            model.insert_blank_page(1)  # no command recorded: the session reads clean
        dirty = edit == "snapshot_command"
        assert model.has_unsaved_changes() is dirty
        _overwrite_in_place(src, ext.read_bytes())
        foreign = src.read_bytes()

        _assert_refused_as_changed_on_disk(model, src)

        assert src.read_bytes() == foreign, "the foreign file was written over"
        assert model.has_unsaved_changes() is dirty, "a refused save must not mark the session saved"
        _assert_refused_as_changed_on_disk(model, src)  # the refusal sticks: no silent second try
        assert src.read_bytes() == foreign
        # Save As to a new path is still the way out.
        model.save_as(str(tmp_path / "rescued.pdf"))
        assert model.has_unsaved_changes() is False
    finally:
        model.close()
    assert not [p.name for p in tmp_path.iterdir() if p.name.startswith(".")], "no staging file is left"


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_save_after_save_as_refuses_to_clobber_a_foreign_rewrite_of_the_new_file(tmp_path) -> None:
    """F10-FS-1 (p5 section 4): after Save As the live handle reads a private
    copy, so nothing holds the new file; a foreign rewrite of it was silently
    replaced by the session's pages on the next Ctrl+S."""
    src = _pages_pdf(tmp_path / "doc.pdf", "hello", 3)
    copy = tmp_path / "copy.pdf"
    model = _open(src, incremental=True)
    try:
        model.save_as(str(copy))
        ext = _pages_pdf(tmp_path / "ext.pdf", "EXTERNAL", 9)
        _overwrite_in_place(copy, ext.read_bytes())
        foreign = copy.read_bytes()

        _assert_refused_as_changed_on_disk(model, copy)

        assert copy.read_bytes() == foreign
        assert len(_page_texts(copy)) == 9
    finally:
        model.close()


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_a_same_size_same_mtime_foreign_rewrite_is_still_detected(tmp_path) -> None:
    """``copy /y`` and Explorer keep the SOURCE's modification time, so size +
    mtime alone can miss a same-length rewrite: the content digest catches it."""
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open(src, incremental=True)
    try:
        before = src.stat()
        data = bytearray(src.read_bytes())
        data[-20] ^= 0x01
        rewritten = bytes(data)
        _overwrite_in_place(src, rewritten)
        os.utime(src, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert src.stat().st_size == before.st_size
        assert src.stat().st_mtime_ns == before.st_mtime_ns

        _assert_refused_as_changed_on_disk(model, src)

        assert src.read_bytes() == rewritten
    finally:
        model.close()


@pytest.mark.parametrize("incremental", [True, False], ids=["incremental", "full"])
def test_the_sessions_own_saves_never_trip_the_changed_on_disk_gate(tmp_path, incremental) -> None:
    """Guard: every write the session makes itself refreshes the baseline, so a
    run of Ctrl+S / Save As / Ctrl+S never refuses (incremental, full, the
    orphan fallback, a deleted target, the secure rewrite)."""
    src = _pages_pdf(tmp_path / "doc.pdf", "hello", 2)
    model = _open(src, incremental=incremental)
    try:
        for _ in range(2):
            _insert_page_like_the_controller(model)
            model.save_as(str(src))
        _add_orphan(model.doc)  # incremental -> the pruned full-save fallback
        model.edit_count += 1
        model.save_as(str(src))
        model.save_as(str(src))
        other = tmp_path / "other.pdf"
        model.save_as(str(other))
        _insert_page_like_the_controller(model)
        model.save_as(str(other))
        model.save_as(str(other))
        # A vanished target is recreated, not refused.  The session's deny-write
        # lock (OD-FS1-LOCK) refuses the delete, so drop it for the delete (as
        # on a share without the lock); the save takes it back.
        from utils import file_share_lock

        with file_share_lock.suspended(other):
            other.unlink()
        model.save_as(str(other))
        assert other.is_file()
        if sys.platform == "win32":
            assert file_share_lock.is_locked(other)
        model.secure_save_required = True
        model.save_as(str(other))
        model.save_as(str(other))
        assert model.has_unsaved_changes() is False
    finally:
        model.close()


def test_a_save_that_failed_after_writing_the_target_does_not_lock_the_session_out(
    tmp_path, monkeypatch
) -> None:
    """A save that wrote the target but failed later (reopen failed) changed the
    file itself: the next Ctrl+S must not take that for a foreign writer."""
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open(src, incremental=False)
    try:
        _edit_and_orphan(model, orphan=False)
        with monkeypatch.context() as patch:
            patch.setattr(model, "_reopen_doc_after_save", _reopen_always_fails)
            model.save_as(str(src))  # rebinds to the recovery copy (target written)
        model.doc[0].insert_text((72, 200), "SECOND", fontsize=12.0)
        model.edit_count += 1
        model.save_as(str(src))
        assert "SECOND" in _page_texts(src)[0]
    finally:
        model.close()


# ---------------------------------------------------------------- H10-2: declared xref size


def _declaring_xref_stream_file(
    src: Path, dst: Path, slots: int, padding: int = 0, *, index_gap: bool = False
) -> Path:
    """``src`` (classic table) rewritten as a one-revision xref stream declaring ``slots`` slots.

    Every slot past the real objects is free, so the Flate-compressed table stays a
    few KB however large ``slots`` is -- the hostile shape of H10-2.  ``padding`` comment
    lines are written between the last object and the table (a file that is really big).
    ``index_gap`` writes rows only for the real objects and the last slot
    (``/Index [0 n slots-1 1]``): every slot in between has no entry at all.
    """
    import zlib

    data = src.read_bytes()
    offset = int(re.search(rb"startxref\s+(\d+)", data[data.rfind(b"startxref") :]).group(1))
    assert data[offset : offset + 4] == b"xref"
    head = re.compile(rb"\s*(\d+)\s+(\d+)\s*\n").match(data, offset + 4)
    first, count = int(head.group(1)), int(head.group(2))
    rows = data[head.end() : head.end() + 20 * count]
    trailer = re.search(rb"trailer\s*<<(.*?)>>\s*startxref", data[offset:], re.S).group(1)
    container = count
    pad = b"% padding\n" * padding
    new_offset = offset + len(pad)
    body = bytearray()
    numbers = [*range(container + 1), slots - 1] if index_gap else range(slots)
    for number in numbers:
        if number == container:
            kind, where, gen = 1, new_offset, 0
        elif first <= number < first + count:
            row = rows[20 * (number - first) : 20 * (number - first) + 20]
            kind = 1 if row[17:18] == b"n" else 0
            where, gen = int(row[:10]), int(row[11:16])
        else:
            kind, where, gen = 0, 0, 0
        body += kind.to_bytes(1, "big") + where.to_bytes(4, "big") + gen.to_bytes(2, "big")
    stream = zlib.compress(bytes(body), 9)
    entries = re.sub(rb"/Size\s+\d+", b"", trailer).strip()
    index = f"0 {container + 1} {slots - 1} 1" if index_gap else f"0 {slots}"
    obj = (
        f"{container} 0 obj\n<< /Type /XRef /Size {slots} /W [1 4 2] /Index [{index}] "
        f"/Filter /FlateDecode /Length {len(stream)} ".encode()
        + entries
        + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n"
    )
    tail = b"startxref\n" + str(new_offset).encode() + b"\n%%EOF\n"
    dst.write_bytes(data[:offset] + pad + obj + tail)
    return dst


class _CountingDoc:
    """Delegates to a document and counts the calls made through it."""

    def __init__(self, doc: fitz.Document) -> None:
        self._doc = doc
        self.calls: dict[str, int] = {}

    def __getattr__(self, name):
        attr = getattr(self._doc, name)
        if not callable(attr):
            return attr

        def counted(*args, **kwargs):
            self.calls[name] = self.calls.get(name, 0) + 1
            return attr(*args, **kwargs)

        return counted


def _spy_on_the_xref_walk(monkeypatch) -> list[int]:
    import model.signed_append_save as signed_append_save

    walks: list[int] = []

    def _declined(*_args):
        walks.append(1)
        raise signed_append_save._Declined

    monkeypatch.setattr(signed_append_save, "_differing_xrefs", _declined)
    return walks


def _spy_on_source_reads(monkeypatch) -> list[int]:
    """The xrefs ``signed_append_save._source`` is asked for (one per slot read)."""
    import model.signed_append_save as signed_append_save

    reads: list[int] = []
    original_source = signed_append_save._source

    def _counting(doc, xref, length, **kwargs):
        reads.append(xref)
        return original_source(doc, xref, length, **kwargs)

    monkeypatch.setattr(signed_append_save, "_source", _counting)
    return reads


# Above the default ``MAX_UNBACKED_XREF_SLOTS`` (100 000), so the census-less guard
# refuses it; free rows compress, so the file stays a few KB.
SPARSE_SLOTS = 200_000


def _hostile_signed_pdf(tmp_path: Path) -> Path:
    """The signed fixture as a few-KB ``hostile.pdf`` declaring ``SPARSE_SLOTS`` xref slots (H10-2)."""
    return _declaring_xref_stream_file(
        _make_signed_pdf(tmp_path / "signed.pdf"), tmp_path / "hostile.pdf", slots=SPARSE_SLOTS
    )


def _highlighted_state(path: Path) -> fitz.Document:
    state = fitz.open(str(path))
    state[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
    return state


def test_a_tiny_file_declaring_a_huge_xref_table_appends_and_keeps_the_signature(
    tmp_path,
) -> None:
    """H10-2: 28 KB declaring 4M slots made every signed append walk 4M slots twice in
    Python (~70 s); round 10 declined it instead, which fully rewrote the file and lost
    the signature.  The diff now reads only slots in use, so the append runs."""
    import model.signed_append_save as signed_append_save

    path = _hostile_signed_pdf(tmp_path)
    assert path.stat().st_size < 15_000
    original = path.read_bytes()
    state = _highlighted_state(path)
    stage = tmp_path / "stage.pdf"
    try:
        assert int(state.xref_length()) > SPARSE_SLOTS and not state.is_repaired
        assert signed_append_save.append_state_onto_source(state, path, stage) is True
    finally:
        state.close()
    assert stage.read_bytes().startswith(original)
    out = fitz.open(str(stage))
    try:
        assert not out.is_repaired
        assert [a.type[0] for a in out[0].annots()].count(8) == 1
    finally:
        out.close()


def test_the_signed_append_reads_only_slots_in_use(tmp_path, monkeypatch) -> None:
    """The replay and the verification look at the slots either side holds an object
    for, not at every declared slot (a full walk reads >= 400 000 slots here)."""
    import model.signed_append_save as signed_append_save

    path = _hostile_signed_pdf(tmp_path)
    calls = _spy_on_source_reads(monkeypatch)
    state = _highlighted_state(path)
    try:
        assert signed_append_save.append_state_onto_source(state, path, tmp_path / "s.pdf") is True
    finally:
        state.close()
    assert 0 < len(calls) < 1_000, len(calls)


def test_in_use_census_semantics(tmp_path) -> None:
    """``_in_use_xrefs`` is MuPDF's own view of which slots hold an object."""
    assert hasattr(fitz.mupdf, "ll_pdf_object_exists"), "PyMuPDF bump: census primitive gone"
    assert hasattr(fitz, "_as_pdf_document"), "PyMuPDF bump: census primitive gone"
    from model.signed_append_save import _in_use_xrefs

    signed = _make_signed_pdf(tmp_path / "signed.pdf")
    doc = fitz.open(str(signed))
    try:
        length = int(doc.xref_length())
        census = _in_use_xrefs(doc)
        assert census is not None and 0 not in census
        assert census == {x for x in range(1, length) if doc.xref_object(x) != "null"}
        padding = doc.get_new_xref()  # reserved, never written
        annot = doc[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
        length, incremental = int(doc.xref_length()), doc.can_save_incrementally()
        census = _in_use_xrefs(doc)
        assert padding not in census
        assert annot.xref in census, "an unsaved new object is in use"
        assert (int(doc.xref_length()), doc.can_save_incrementally()) == (length, incremental)
    finally:
        doc.close()

    throwaway = fitz.open(str(signed))
    objstm = tmp_path / "objstm.pdf"
    throwaway.save(str(objstm), garbage=0, use_objstms=1)
    throwaway.close()
    assert b"/ObjStm" in objstm.read_bytes()
    doc = fitz.open(str(objstm))
    try:
        length = int(doc.xref_length())
        assert _in_use_xrefs(doc) == {
            x for x in range(1, length) if doc.xref_object(x) != "null"
        }, "object-stream members are in use"
    finally:
        doc.close()

    gap = _declaring_xref_stream_file(signed, tmp_path / "gap.pdf", SPARSE_SLOTS, index_gap=True)
    doc = fitz.open(str(gap))
    try:
        assert int(doc.xref_length()) == SPARSE_SLOTS and not doc.is_repaired
        census = _in_use_xrefs(doc)
        assert census and max(census) < 100
        middle = SPARSE_SLOTS // 2
        assert middle not in census
        with pytest.raises((RuntimeError, ValueError, fitz.mupdf.FzErrorBase)):
            doc.xref_object(middle)  # why ``_source`` catches: a gap slot raises
    finally:
        doc.close()


def _diff_or_declined(state, base, census):
    import model.signed_append_save as signed_append_save

    try:
        return signed_append_save._differing_xrefs(state, base, census)
    except signed_append_save._Declined:
        return "declined"


@pytest.mark.parametrize("fixture", ["control", "objstm", "owner_only_aes"])
@pytest.mark.parametrize("backing", ["file", "memory"])
def test_the_census_diff_equals_the_full_walk(tmp_path, fixture, backing) -> None:
    import model.signed_append_save as signed_append_save

    if fixture == "control":
        path = _make_signed_pdf(tmp_path / "signed.pdf")
    elif fixture == "objstm":
        path = _make_xref_stream_signed_pdf(tmp_path / "objstm.pdf")
    else:
        path, _ = _make_owner_only_signed_pdf(tmp_path)
    live = tmp_path / "live.pdf"
    live.write_bytes(path.read_bytes())
    state = _highlighted_state(live)
    second = state[1]
    second.delete_annot(second.add_highlight_annot(fitz.Rect(72, 90, 150, 105)))
    state.new_page().insert_text((72, 100), "a new page")
    if backing == "memory":
        state = fitz.open("pdf", state.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP))
    base = fitz.open(str(path))
    try:
        while int(base.xref_length()) < int(state.xref_length()):
            base.get_new_xref()
        census = signed_append_save._in_use_xrefs(state)
        assert census is not None
        with_census = _diff_or_declined(state, base, census)
        full_walk = _diff_or_declined(state, base, None)
        assert with_census == full_walk
        assert with_census, "the edit must show up as a difference"
    finally:
        base.close()
        state.close()


def test_without_the_census_the_unbacked_guard_still_declines_before_any_walk(
    tmp_path, monkeypatch
) -> None:
    """A PyMuPDF without the census primitive keeps round 10's bound on the full walk."""
    import model.signed_append_save as signed_append_save

    path = _hostile_signed_pdf(tmp_path)
    monkeypatch.setattr(signed_append_save, "_in_use_xrefs", lambda _doc: None)
    walks = _spy_on_the_xref_walk(monkeypatch)
    state = _highlighted_state(path)
    stage = tmp_path / "stage.pdf"
    try:
        assert signed_append_save.append_state_onto_source(state, path, stage) is False
    finally:
        state.close()
    assert walks == [], "the declined table must not be walked"
    assert not stage.exists()


def test_a_missing_base_census_declines_instead_of_walking_the_whole_table(
    tmp_path, monkeypatch
) -> None:
    """The size guard is skipped once the state census exists, so a base/check census
    that fails must decline, never fall back to walking every declared slot."""
    import model.signed_append_save as signed_append_save

    path = _hostile_signed_pdf(tmp_path)
    real = signed_append_save._in_use_xrefs
    state = _highlighted_state(path)
    monkeypatch.setattr(
        signed_append_save, "_in_use_xrefs", lambda doc: real(doc) if doc is state else None
    )
    calls = _spy_on_source_reads(monkeypatch)
    try:
        assert signed_append_save.append_state_onto_source(state, path, tmp_path / "s.pdf") is False
    finally:
        state.close()
    assert len(calls) < 1_000


def test_the_append_declines_a_state_that_grew_past_the_growth_cap(tmp_path, monkeypatch) -> None:
    """``get_new_xref`` costs ~12 us a call: the pad loop is bounded by its own cap."""
    import model.signed_append_save as signed_append_save

    monkeypatch.setattr(signed_append_save, "MAX_APPEND_GROWTH_SLOTS", 1)
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    state = _highlighted_state(path)
    try:
        for _ in range(3):
            _new_object(state, "<< /Kind /Filler >>")
        assert signed_append_save.append_state_onto_source(state, path, tmp_path / "s.pdf") is False
    finally:
        state.close()


def test_the_same_declared_table_appends_when_the_floor_or_the_file_backs_it(
    tmp_path, monkeypatch
) -> None:
    """The refusal is about unbacked slots only: under the floor, or backed by file size, the
    signature-preserving append still runs and reproduces the live state."""
    import model.signed_append_save as signed_append_save

    signed = _make_signed_pdf(tmp_path / "signed.pdf")
    small = _declaring_xref_stream_file(signed, tmp_path / "small.pdf", slots=20_000)
    # 50 KB: backs 20 000 slots
    padded = _declaring_xref_stream_file(
        signed, tmp_path / "padded.pdf", slots=20_000, padding=5_000
    )
    cases = [(small, 100_000), (padded, 1_000)]
    for index, (path, floor) in enumerate(cases):
        monkeypatch.setattr(signed_append_save, "MAX_UNBACKED_XREF_SLOTS", floor, raising=False)
        original = path.read_bytes()
        state = fitz.open(str(path))
        try:
            assert not state.is_repaired
            state[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
            stage = tmp_path / f"stage{index}.pdf"
            assert signed_append_save.append_state_onto_source(state, path, stage) is True, path
            assert stage.read_bytes().startswith(original)
        finally:
            state.close()
        out = fitz.open(str(stage))
        try:
            assert [a.type[0] for a in out[0].annots()].count(8) == 1
        finally:
            out.close()


def test_xref_slots_are_unbacked_boundaries() -> None:
    from model.signed_append_save import (
        MAX_UNBACKED_XREF_SLOTS,
        XREF_SLOTS_PER_SOURCE_BYTE,
        xref_slots_are_unbacked,
    )

    assert not xref_slots_are_unbacked(0, 0)
    assert not xref_slots_are_unbacked(MAX_UNBACKED_XREF_SLOTS, 0)
    assert xref_slots_are_unbacked(MAX_UNBACKED_XREF_SLOTS + 1, 0)
    backed = 3_000_000
    size = backed // XREF_SLOTS_PER_SOURCE_BYTE
    assert not xref_slots_are_unbacked(backed, size)
    assert xref_slots_are_unbacked(backed + 1, size)
    # the 28 KB / 4M-slot file of H10-2 and its 8 388 607-slot MuPDF-maximum sibling
    assert xref_slots_are_unbacked(4_000_000, 28_638)
    assert xref_slots_are_unbacked(8_388_607, 28_638)


def test_the_xref_walk_skips_the_stream_probe_for_slots_free_on_both_sides(tmp_path) -> None:
    """H10-2: the walk read ``xref_object`` + ``xref_is_stream`` on both documents for every
    slot, 8.6 us a slot.  A slot null on both sides has nothing to compare."""
    from model.signed_append_save import _differing_xrefs

    path = _declaring_xref_stream_file(
        _make_signed_pdf(tmp_path / "signed.pdf"), tmp_path / "wide.pdf", slots=20_000
    )
    state = _CountingDoc(fitz.open(str(path)))
    base = _CountingDoc(fitz.open(str(path)))
    try:
        assert _differing_xrefs(state, base) == []
        for counted in (state, base):
            assert counted.calls["xref_object"] >= 19_000, "every slot is still looked at"
            assert counted.calls.get("xref_is_stream", 0) < 200, counted.calls
    finally:
        state._doc.close()
        base._doc.close()


@pytest.mark.parametrize("scenario", ["save_as_copy", "undo_then_ctrl_s"])
def test_a_signed_save_as_of_a_sparse_table_keeps_the_signature(
    tmp_path, caplog, scenario
) -> None:
    """End to end (H10-2): Save As of a file-backed session, and Ctrl+S after an undo
    (a memory-backed handle), both append onto the signed bytes instead of the round-10
    decline's full rewrite."""
    import logging

    path = _hostile_signed_pdf(tmp_path)
    original = path.read_bytes()
    target = tmp_path / "copy.pdf" if scenario == "save_as_copy" else path
    model = _open(path, incremental=True)
    try:
        _record_highlight(model)
        if scenario == "undo_then_ctrl_s":
            model.command_manager.undo()
            _record_highlight(model)
        with caplog.at_level(logging.WARNING):
            model.save_as(str(target))
    finally:
        model.close()
    assert target.read_bytes().startswith(original), "the signed revision must stay a prefix"
    assert _highlight_count(target) == 1
    assert not any(
        "falling back to a full rewrite" in record.getMessage() for record in caplog.records
    )


# ---------------------------------------------------------------- F10-FS-2: Save As to a name Windows rewrites


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows drops a trailing dot/space from a file name")
@pytest.mark.parametrize("typed", ["t2.pdf.", "t3.pdf ", "t4.pdf. .", "t5.pdf .. "])
def test_save_as_to_a_name_with_a_trailing_dot_or_space_keeps_the_session_findable(tmp_path, typed) -> None:
    """F10-FS-2: Windows strips a trailing dot/space when it creates the file, but
    the session key was computed from the typed spelling before the file existed:
    the key matched no later lookup and opening the file again made a second tab."""
    src = _pages_pdf(tmp_path / "t.pdf", "hello", 1)
    stored = tmp_path / typed.rstrip(". ")
    model = PDFModel()
    try:
        sid = model.open_pdf(str(src), append=True)
        model.insert_blank_page(1)
        model.save_as(str(tmp_path / typed))

        assert stored.exists(), "the file lands under the stripped name"
        # Every spelling of the file finds the one session ...
        assert model.find_session_by_path(str(stored)) == sid
        assert model.find_session_by_path(str(tmp_path / typed)) == sid
        # ... and reopening it (Explorer, recent files) reuses the tab.
        assert model.open_pdf(str(stored), append=True) == sid
        assert len(model.session_ids) == 1
        # The key is the one an open of the stored file would have computed.
        assert model._sessions_by_id[sid].canonical_path == model._canonicalize_path(str(stored))
    finally:
        model.close()


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows drops a trailing dot/space from a file name")
def test_canonical_path_of_a_not_yet_existing_name_matches_the_name_windows_will_create(tmp_path) -> None:
    """F10-FS-2 chokepoint: the key of a path that does not exist yet must already be
    the key the file will have once written (the pre-write Save As guards use it)."""
    model = PDFModel()
    try:
        for typed in ("new.pdf.", "new.pdf ", "new.pdf. "):
            assert model._canonicalize_path(str(tmp_path / typed)) == model._canonicalize_path(
                str(tmp_path / "new.pdf")
            )
        # Inner dots / spaces and the dot segments are real names and stay as typed.
        assert model._canonicalize_path(str(tmp_path / "a. b.pdf")) != model._canonicalize_path(
            str(tmp_path / "a.b.pdf")
        )
        assert model._canonicalize_path(str(tmp_path / "sub" / "..")) == model._canonicalize_path(str(tmp_path))
    finally:
        model.close()


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows drops a trailing dot/space from a file name")
def test_save_as_onto_another_tabs_file_through_a_trailing_dot_spelling_is_still_refused(tmp_path) -> None:
    """F10-FS-2 guard direction: ``other.pdf.`` names the file the other tab holds."""
    a = _pages_pdf(tmp_path / "a.pdf", "a", 1)
    b = _pages_pdf(tmp_path / "b.pdf", "b", 1)
    model = PDFModel()
    try:
        model.open_pdf(str(a), append=True)
        sid_b = model.open_pdf(str(b), append=True)
        model.insert_blank_page(1)
        with pytest.raises(RuntimeError):
            model.save_as(str(tmp_path / "a.pdf."))
        assert _page_texts(a) == ["a p1"]
        assert model.get_active_session_id() == sid_b
    finally:
        model.close()


# ---------------------------------------------------------------- F10-FS-3: Save As that only changes the name's case


def _fs_ignores_case(directory: Path) -> bool:
    probe = directory / "CaseProbe.tmp"
    probe.write_bytes(b"")
    try:
        return (directory / "caseprobe.tmp").exists()
    finally:
        probe.unlink()


@pytest.mark.skipif(sys.platform != "win32", reason="the case-insensitive file system under test is the Windows one")
@pytest.mark.parametrize("mode", ["incremental", "full", "secure"])
def test_save_as_that_only_changes_the_case_renames_the_file_on_disk(tmp_path, mode) -> None:
    """F10-FS-3: ``Path('A.pdf').resolve()`` returns the on-disk spelling ``a.pdf``, so the
    request was routed as "save over the open file" and installed under the OLD name while
    the session, the tab and the next Ctrl+S message all said ``A.pdf``."""
    assert _fs_ignores_case(tmp_path)
    src = _pages_pdf(tmp_path / "a.pdf", "hello", 1)
    model = _open(src, incremental=mode == "incremental", secure=mode == "secure")
    try:
        sid = model.get_active_session_id()
        model.insert_blank_page(1)
        model.save_as(str(tmp_path / "A.pdf"))

        assert _names_in(tmp_path) == ["A.pdf"], "the file on disk carries the spelling the user asked for"
        assert len(fitz.open(str(tmp_path / "A.pdf"))) == 2, "the edit landed"
        session = model._sessions_by_id[sid]
        assert session.display_name == "A.pdf"
        assert Path(session.original_path).name == "A.pdf"
        assert Path(model.saved_path).name == "A.pdf"
        assert model.find_session_by_path(str(tmp_path / "a.pdf")) == sid
        assert model.find_session_by_path(str(tmp_path / "A.pdf")) == sid
        assert model.has_unsaved_changes() is False
        assert len(model.doc) == 2, "the live handle reads the renamed file"

        # The session survives: a further edit and a plain Ctrl+S-style save work.
        model.insert_blank_page(1)
        model.save_as(model.saved_path)
        assert _names_in(tmp_path) == ["A.pdf"]
        assert len(fitz.open(str(tmp_path / "A.pdf"))) == 3
    finally:
        model.close()


@pytest.mark.skipif(sys.platform != "win32", reason="the case-insensitive file system under test is the Windows one")
def test_save_as_onto_an_existing_file_keeps_the_typed_case(tmp_path) -> None:
    """F10-FS-3 chokepoint (``write_via_staging``): overwriting ``b.pdf`` through ``B.pdf``
    leaves ``B.pdf``, not the stale spelling."""
    from utils.path_staging import write_via_staging

    (tmp_path / "b.pdf").write_bytes(b"old")
    write_via_staging(str(tmp_path / "B.pdf"), lambda stage: Path(stage).write_bytes(b"new"))
    assert _names_in(tmp_path) == ["B.pdf"]
    assert (tmp_path / "B.pdf").read_bytes() == b"new"


def test_resolve_as_requested_only_restores_a_case_difference(tmp_path) -> None:
    from utils.path_staging import resolve_as_requested

    real = tmp_path / "real.pdf"
    real.write_bytes(b"x")
    # A name that differs by more than case is the resolved (symlink / 8.3) name, untouched.
    assert resolve_as_requested(str(real)) == real.resolve()
    assert resolve_as_requested(str(tmp_path / "missing.pdf")) == (tmp_path / "missing.pdf").resolve()
    if _fs_ignores_case(tmp_path):
        assert resolve_as_requested(str(tmp_path / "REAL.pdf")).name == "REAL.pdf"
        assert resolve_as_requested(str(tmp_path / "REAL.pdf")).parent == tmp_path.resolve()


# ---------------------------------------------------------------- F11-FS-3: Ctrl+S must not undo an external case-only rename


def _memory_backed_session_renamed_externally(tmp_path, *, secure: bool):
    """``report.pdf`` opened, edited, undone (live doc memory-backed), then renamed to
    ``Report.pdf`` by another program (Explorer): the stored path keeps the old spelling."""
    src = _pages_pdf(tmp_path / "report.pdf", "R", 2)
    model = _open(src, incremental=False, secure=secure)
    _insert_page_like_the_controller(model)
    model.command_manager.undo()
    assert model.doc.name != str(src), "precondition: the live handle does not read the file"
    os.rename(src, tmp_path / "Report.pdf")
    assert _names_in(tmp_path) == ["Report.pdf"]
    model.doc[0].add_text_annot((200, 200), "x")
    model.edit_count += 1
    return model


@pytest.mark.skipif(sys.platform != "win32", reason="the case-insensitive file system under test is the Windows one")
@pytest.mark.parametrize("secure", [False, True])
@pytest.mark.parametrize("via", ["save_as", "save_session_as"])
@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_ctrl_s_keeps_the_spelling_another_program_gave_the_file(tmp_path, secure, via) -> None:
    """F11-FS-3: Ctrl+S replays ``saved_path or original_path`` - a STALE spelling after an
    external case-only rename - which is not a typed request.  Restoring it renamed the file back."""
    model = _memory_backed_session_renamed_externally(tmp_path, secure=secure)
    try:
        sid = model.get_active_session_id()
        ctrl_s = model.saved_path or model.original_path
        assert Path(ctrl_s).name == "report.pdf", "precondition: the stored spelling is the stale one"
        if via == "save_as":
            model.save_as(ctrl_s)
        else:
            model.save_session_as(sid, ctrl_s)

        assert _names_in(tmp_path) == ["Report.pdf"], "the on-disk name survives a plain save"
        assert len(fitz.open(str(tmp_path / "Report.pdf"))) == 2
        session = model._sessions_by_id[sid]
        assert Path(session.original_path).name == "Report.pdf"
        assert session.display_name == "Report.pdf"
        assert Path(model.saved_path).name == "Report.pdf", "the stale spelling is healed"
        assert model.find_session_by_path(str(tmp_path / "report.pdf")) == sid
        # A second Ctrl+S (now with the healed spelling) is stable.
        model.save_as(model.saved_path)
        assert _names_in(tmp_path) == ["Report.pdf"]
    finally:
        model.close()


@pytest.mark.skipif(sys.platform != "win32", reason="the case-insensitive file system under test is the Windows one")
@pytest.mark.parametrize("secure", [False, True])
@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_a_typed_case_change_still_wins_after_an_external_rename(tmp_path, secure) -> None:
    """F11-FS-3 guard: only the STORED spelling is "no request"; a different typed spelling
    of the same file (F10-FS-3's rule) still names the file."""
    model = _memory_backed_session_renamed_externally(tmp_path, secure=secure)
    try:
        model.save_as(str(tmp_path / "REPORT.pdf"))
        assert _names_in(tmp_path) == ["REPORT.pdf"]
        assert Path(model.saved_path).name == "REPORT.pdf"
    finally:
        model.close()


@pytest.mark.skipif(sys.platform != "win32", reason="the case-insensitive file system under test is the Windows one")
@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_the_stored_name_typed_for_another_file_keeps_its_case(tmp_path) -> None:
    """F11-FS-3 guard: the same NAME typed for a different file is a typed request."""
    model = _memory_backed_session_renamed_externally(tmp_path, secure=False)
    try:
        other = tmp_path / "sub"
        other.mkdir()
        (other / "Report.pdf").write_bytes(b"old")
        model.save_as(str(other / "report.pdf"))
        assert _names_in(other) == ["report.pdf"]
        assert _names_in(tmp_path) == ["Report.pdf", "sub"]
    finally:
        model.close()


def test_on_disk_spelling_only_adopts_a_case_only_difference(tmp_path) -> None:
    from utils.path_staging import on_disk_spelling

    real = tmp_path / "Real.pdf"
    real.write_bytes(b"x")
    assert on_disk_spelling(str(real)) == str(real)
    missing = str(tmp_path / "missing.pdf")
    assert on_disk_spelling(missing) == missing
    if _fs_ignores_case(tmp_path):
        stale = str(tmp_path / "real.pdf")
        assert on_disk_spelling(stale) == str(tmp_path / "Real.pdf")


# ---------------------------------------------------------------- F11-FS-1


def _foreign_incremental_revision(path: Path, *, text: str = "FOREIGN CLAUSE") -> None:
    """Another program appends a revision (page 2 gets ``text``); the old bytes stay a prefix."""
    foreign = fitz.open(str(path))
    foreign[1].insert_text((72, 300), text, fontsize=12.0)
    foreign.save(str(path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    foreign.close()


def _memory_backed_signed_session(path: Path) -> PDFModel:
    """A signed file's session whose live doc is memory-backed (after a SnapshotCommand undo)."""
    model = _open(path, incremental=True)
    _insert_page_like_the_controller(model)
    model.command_manager.undo()
    model.doc[0].add_text_annot((300, 300), "my note")
    model.edit_count += 1
    assert model.doc.name != str(path), "the live doc must be memory-backed for this scenario"
    return model


def _revision_count(path: Path) -> int:
    doc = fitz.open(str(path))
    try:
        return int(doc.version_count)
    finally:
        doc.close()


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_signed_save_as_never_embeds_a_foreign_revision_of_the_source_as_its_prefix(tmp_path) -> None:
    """F11-FS-1: ``append_state_onto_source`` read ``original_path``'s CURRENT bytes as
    the signed prefix.  Ctrl+S was refused after another program appended a revision
    (F10-FS-1), but Save As to a new path wrote the foreign revision into the new
    file's history.  The prefix is the bytes the session opened (and signed): the
    output is those bytes + the session's one revision, same as without the foreign
    write."""
    path = _make_signed_pdf(tmp_path / "contract.pdf")
    original = path.read_bytes()
    out = tmp_path / "contract_copy.pdf"
    model = _memory_backed_signed_session(path)
    try:
        _foreign_incremental_revision(path)
        foreign = path.read_bytes()
        assert foreign.startswith(original) and foreign != original

        _assert_refused_as_changed_on_disk(model, path)  # Ctrl+S analogue: unchanged behaviour
        model.save_as(str(out))
    finally:
        model.close()

    data = out.read_bytes()
    assert data.startswith(original), "the signed revision the session opened is the prefix"
    assert not data.startswith(foreign), "the other program's revision is not embedded"
    assert b"FOREIGN CLAUSE" not in data
    assert _revision_count(out) == 2, "original + the session's revision, nothing else"
    assert path.read_bytes() == foreign, "the source is not touched by a Save As"
    saved = fitz.open(str(out))
    try:
        assert len(saved) == 2
        assert saved[0].first_annot is not None
        assert "FOREIGN" not in saved[1].get_text()
    finally:
        saved.close()


def test_signed_save_as_after_a_mtime_only_touch_still_appends_onto_the_source(tmp_path) -> None:
    """F11-FS-1 guard: the baseline compares bytes, so a touched-but-identical source (backup
    tool, ``os.utime``) must keep the append-only save that preserves the signature."""
    path = _make_signed_pdf(tmp_path / "contract.pdf")
    original = path.read_bytes()
    out = tmp_path / "contract_copy.pdf"
    model = _memory_backed_signed_session(path)
    try:
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        model.save_as(str(out))
    finally:
        model.close()
    assert out.read_bytes().startswith(original)
    assert _revision_count(out) == 2


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_signed_save_as_after_a_foreign_in_place_rewrite_does_not_embed_the_foreign_file(tmp_path) -> None:
    """F11-FS-1: when the source is no longer the bytes the session opened and the old bytes are
    not a recoverable prefix (a same-size patch of page 2's text, numbering untouched, so the
    replay would still accept it), the append is declined: the new file is the session's own
    full save, never a copy of the foreign file."""
    path = _make_signed_pdf(tmp_path / "contract.pdf")
    original = path.read_bytes()
    out = tmp_path / "contract_copy.pdf"
    model = _memory_backed_signed_session(path)
    try:
        needle = b"<506167652074776f20626f6479>"  # "Page two body"
        assert original.count(needle) == 1
        _overwrite_in_place(path, original.replace(needle, b"<506167652054574f20626f6479>"))
        foreign = path.read_bytes()
        assert len(foreign) == len(original) and foreign != original
        from model.pdf_model import SignatureWouldBreakError

        with pytest.raises(SignatureWouldBreakError) as excinfo:  # SIG-DIALOG: asks first
            model.save_as(str(out))
        assert excinfo.value.reason_code == "source_changed"
        assert not out.exists()
        model.save_as(str(out), allow_signature_loss=True)
    finally:
        model.close()
    assert not out.read_bytes().startswith(foreign), "the foreign file is not the new file's prefix"
    saved = fitz.open(str(out))
    try:
        assert len(saved) == 2
        assert saved[0].first_annot is not None, "the session's own state is what was saved"
        assert saved[1].get_text().strip() == "Page two body"
    finally:
        saved.close()


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_signed_save_as_over_a_source_that_vanished_still_degrades_not_crashes(tmp_path) -> None:
    """F11-FS-1 guard: an unreadable source declines the append (existing contract)."""
    path = _make_signed_pdf(tmp_path / "contract.pdf")
    out = tmp_path / "contract_copy.pdf"
    model = _memory_backed_signed_session(path)
    try:
        path.unlink()
        from model.pdf_model import SignatureWouldBreakError

        with pytest.raises(SignatureWouldBreakError) as excinfo:  # SIG-DIALOG: asks first
            model.save_as(str(out))
        assert excinfo.value.reason_code == "source_missing"
        model.save_as(str(out), allow_signature_loss=True)
    finally:
        model.close()
    assert len(fitz.open(str(out))) == 2


@pytest.mark.parametrize("size", [0, 1, 4095, 4096, 4097, 8191, 8192, 8193, 20_000])
def test_edge_digest_of_bytes_matches_the_file_fingerprint_digest(tmp_path, size) -> None:
    """F11-FS-1: the in-memory digest used to compare the source prefix with the baseline is the
    same function of the bytes as the on-disk fingerprint (both edges, same window)."""
    from model.pdf_model import _edge_digest_of_bytes, _file_fingerprint

    data = bytes((i * 7 + 3) % 251 for i in range(size))
    target = tmp_path / f"f{size}.bin"
    target.write_bytes(data)
    fingerprint = _file_fingerprint(target)
    assert fingerprint is not None
    assert fingerprint[0] == size
    assert fingerprint[2] == _edge_digest_of_bytes(data)


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_signed_append_base_is_the_opened_prefix_when_a_large_file_gets_a_foreign_append(tmp_path) -> None:
    """F11-FS-1: on a file larger than both digest windows, the recorded tail window sits in the
    OLD bytes; a foreign append moves the file's own tail, so only the recomputed prefix digest
    matches."""
    path = _pages_pdf(tmp_path / "big.pdf", "hello", 80)
    original = path.read_bytes()
    assert len(original) > 4 * 4096
    model = _open(path, incremental=True)
    try:
        assert model._signed_append_base_bytes(str(path)) == original
        _foreign_incremental_revision(path, text="FOREIGN")
        assert path.read_bytes() != original
        assert model._signed_append_base_bytes(str(path)) == original
        _overwrite_in_place(path, original[:-1])  # truncated: the opened bytes are gone
        assert model._signed_append_base_bytes(str(path)) is None
        assert model._signed_append_base_bytes(str(tmp_path / "missing.pdf")) is None
    finally:
        model.close()
