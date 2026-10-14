"""Red-light tests for Tier 0 persistence across save/reopen paths (plan Task 9).

Boundary doctrine pinned throughout this file: a Tier 0 commit promises
supported *live-commit* semantics and tested save/reopen *content* survival
-- it never promises whole-file byte or xref identity after a full save or
garbage collection (``page_fingerprint``/plan tokens hash xref numbers and
are legitimately invalidated by ``garbage=4`` rewrites). "Unchanged" is
always proven via ``model.text_commit.inspect.page_fingerprint`` or a direct
xref/stream comparison -- never whole-file ``tobytes()``/``read_bytes()``
equality, because the trailer ``/ID`` is never byte-stable (see PITFALLS).
The one legitimate whole-file assertion is that ``save_as`` to a *different*
path leaves the original on-disk file's bytes untouched.

Most tests below are CHARACTERIZATION tests: they pin save-chokepoint
behavior (``PDFModel._save_doc`` / ``save_as`` / ``_full_save_to_path`` /
``_atomic_full_save``, all funneling through ``encryption=PDF_ENCRYPT_KEEP``)
that already works today and are expected to PASS at Red -- each is marked
inline. The encrypted-document tests are the exception: they demonstrate a
real, currently-uncaught defect (see the docstring on each) and are expected
to FAIL at Red, same as everything in test_text_commit_boundaries.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import CommitTier, TextCommitSettings  # noqa: E402
from model.text_commit.inspect import page_fingerprint  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica
DOWNSTREAM = "Downstream line stays"


def _add_tier0_page(doc: fitz.Document) -> fitz.Page:
    """Append a raw literal-Tj page (the Tier 0 eligible fixture) to ``doc``."""
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
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return page


def _write_tier0_pdf(path: Path) -> None:
    doc = fitz.open()
    _add_tier0_page(doc)
    doc.save(str(path), garbage=0)
    doc.close()


def _open(
    path: Path, settings: TextCommitSettings, password: str | None = None
) -> PDFModel:
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path), password=password)
    model.ensure_page_index_built(1)
    return model


def _edit(model: PDFModel, probe: str, new_text: str, page_num: int = 1, **kwargs):
    page_idx = page_num - 1
    block = next(
        b for b in model.block_manager.get_blocks(page_idx) if probe in (b.text or "")
    )
    return model.edit_text(
        page_num,
        fitz.Rect(block.layout_rect),
        new_text,
        original_text=block.text,
        **kwargs,
    )


# ---------------------------------------------------------------- unencrypted


def test_tier0_commit_survives_incremental_save_and_reopen(tmp_path):
    """CHARACTERIZATION (passes today): a Tier 0 patch is a plain
    ``doc.update_stream`` on an existing object, so ``can_save_incrementally``
    stays true; ``save_as`` back to the original path takes the incremental
    branch (save_as, pdf_model.py:3688-3704) and the original bytes remain a
    verbatim prefix of the saved file."""
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    original_bytes = pdf_path.read_bytes()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        fingerprint_after_commit = page_fingerprint(model.doc, model.doc[0])

        assert model.doc.can_save_incrementally()
        model.save_as(str(pdf_path))
    finally:
        model.close()

    saved_bytes = pdf_path.read_bytes()
    assert len(saved_bytes) > len(original_bytes)
    assert saved_bytes[: len(original_bytes)] == original_bytes  # incremental prefix

    reopened = fitz.open(str(pdf_path))
    try:
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert DOWNSTREAM in text
    finally:
        reopened.close()

    # A fresh session's fingerprint of the reopened page matches the
    # in-session post-commit fingerprint: xref numbers and decoded stream
    # bytes both survived the incremental round-trip untouched.
    model2 = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert page_fingerprint(model2.doc, model2.doc[0]) == fingerprint_after_commit
    finally:
        model2.close()


def test_tier0_commit_survives_full_save_and_reopen(tmp_path):
    """CHARACTERIZATION (passes today) + explicit doctrine pin: forcing the
    ``secure_save_required`` atomic ``garbage=4`` rewrite (pdf_model.py:3114
    -3163) renumbers xrefs, so ``page_fingerprint`` identity is explicitly
    NOT asserted here -- only that the edit and the annotation survive the
    rewrite semantically."""
    pdf_path = tmp_path / "tier0.pdf"
    doc = fitz.open()
    page = _add_tier0_page(doc)
    page.add_highlight_annot(fitz.Rect(72, 660, 200, 715))
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

        model.secure_save_required = True  # force the atomic garbage=4 path
        model.save_as(str(pdf_path))

        text = model.doc[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert DOWNSTREAM in text
        assert len(list(model.doc[0].annots())) == 1
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
        assert len(list(reopened[0].annots())) == 1
    finally:
        reopened.close()


def test_save_as_new_path_preserves_edit_and_leaves_original_untouched(tmp_path):
    """CHARACTERIZATION (passes today): the one legitimate whole-file byte
    assertion in this suite -- saving to a brand-new path is a plain
    ``_save_doc`` call on the still-open original handle, so the original
    file on disk is never touched."""
    original_path = tmp_path / "original.pdf"
    new_path = tmp_path / "saved_copy.pdf"
    _write_tier0_pdf(original_path)
    original_bytes_before = original_path.read_bytes()

    model = _open(original_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        model.save_as(str(new_path))
    finally:
        model.close()

    assert original_path.read_bytes() == original_bytes_before

    reopened = fitz.open(str(new_path))
    try:
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
    finally:
        reopened.close()


def test_legacy_edit_then_tier0_edit_both_persist(tmp_path):
    """CHARACTERIZATION (passes today): apply_pending_redactions (pdf_model.py
    :3360-3386) cleans the legacy-edited page's pending entry through
    clean_contents at save time but skips the fidelity-protected Tier 0 page
    entirely -- both edits, and the Tier 0 page's downstream text, survive
    reopen."""
    pdf_path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    _add_tier0_page(doc)  # page 1 (1-based): Tier 0 eligible
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 100), "Legacy Text Here", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    # The legacy leg needs a tiered refusal of a growing edit; critique step
    # 12 made Tier 1 (which admits it) the default, so pin Tier 0.
    model = _open(pdf_path, TextCommitSettings(engine="tiered", max_tier=0))
    try:
        model.ensure_page_index_built(2)
        # UI step 7 (no silent legacy): the legacy leg needs the explicit
        # rebuild consent (request flag + accepting confirm).
        result_legacy = _edit(
            model,
            "Legacy Text Here",
            "Legacy Text Changed",
            page_num=2,
            allow_rebuild=True,
            confirm_fallback=lambda _chain: True,
        )
        assert result_legacy is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY
        assert any(e["page_idx"] == 1 for e in model.pending_edits)
        assert 1 not in model.fidelity_protected_pages

        result_tier0 = _edit(model, TARGET, REPLACEMENT, page_num=1)
        assert result_tier0 is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert 0 in model.fidelity_protected_pages

        model.save_as(str(pdf_path))
        # page 1's pending legacy entry was cleaned; page 0 was never queued
        assert model.pending_edits == []
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        assert "Legacy Text Changed" in reopened[1].get_text()
        text0 = reopened[0].get_text()
        assert REPLACEMENT in text0
        assert TARGET not in text0
        assert DOWNSTREAM in text0
    finally:
        reopened.close()


def test_reopen_after_save_allows_fresh_tier0_edit(tmp_path):
    """CHARACTERIZATION (passes today): plan tokens/fingerprints are legitimately
    session-local -- a brand-new PDFModel session over the saved file can
    prepare and commit an independent Tier 0 edit with no cross-session
    leakage of stale state."""
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)

    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        model.save_as(str(pdf_path))
    finally:
        model.close()

    model2 = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        # "Downstream line static" is advance-neutral vs DOWNSTREAM in Helvetica
        # (both text_length to 120.696pt @ 12pt) -- keeps this edit Tier 0 eligible.
        result = _edit(model2, DOWNSTREAM, "Downstream line static")
        assert result is EditTextResult.SUCCESS
        assert model2.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        text = model2.doc[0].get_text()
        assert "Downstream line static" in text
        assert REPLACEMENT in text  # first session's edit still present
    finally:
        model2.close()


# ------------------------------------------------------------------ encrypted


def test_encrypted_doc_tier0_commit_and_save_keeps_encryption(tmp_path):
    """RED -- real defect, not a missing-feature gap.

    ``TieredCommitEngine.prepare`` (model/text_commit/engine.py:95) proves
    every candidate on a scratch copy via
    ``fitz.open("pdf", self._doc.tobytes())`` -- called with the *default*
    ``encryption`` argument (``NONE``) directly on the *live*, authenticated
    document handle. This is precisely the operation
    ``test_worker_snapshot_before_edit_does_not_corrupt_later_encrypted_save``
    (test_scripts/test_secure_persistence.py) already documents as a known
    PyMuPDF 1.27.1 AES-256 quirk: calling ``tobytes(encryption=NONE)`` on the
    live handle silently poisons its internal crypt state, so a *later*
    ``encryption=KEEP`` save on that same handle produces a file that no
    longer decrypts -- even though the save reports success. Reproduced
    directly against fitz (no model involved) alongside this suite; every
    Tier 0 *attempt* on an encrypted document (not just successful commits)
    triggers it, because ``prepare()`` always builds the scratch copy before
    classification is even known. The fix belongs in engine.py: build the
    scratch copy the same way ``capture_worker_snapshot_bytes`` does --
    from an isolated clone, never ``self._doc`` directly.
    """
    pdf_path = tmp_path / "enc.pdf"
    doc = fitz.open()
    _add_tier0_page(doc)
    doc.save(
        str(pdf_path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"), password="user-secret")
    try:
        result = _edit(model, TARGET, REPLACEMENT)
        assert result is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert REPLACEMENT in model.doc[0].get_text()  # live session still fine

        model.save_as(str(pdf_path))
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        assert reopened.needs_pass  # encryption must survive the save
        assert reopened.authenticate("user-secret") != 0
        text = reopened[0].get_text()
        assert REPLACEMENT in text
        assert TARGET not in text
    finally:
        reopened.close()


def test_encrypted_full_save_back_reauthenticates_live_session(tmp_path):
    """RED -- same defect as above, via the ``secure_save_required`` atomic
    full-save chokepoint (_atomic_full_save, pdf_model.py:3114-3163) instead
    of the incremental path: the live doc handle's crypt state is poisoned by
    ``TieredCommitEngine.prepare``'s scratch copy before the save ever runs,
    so the *reopened* live session comes back unable to decrypt content
    regardless of which save chokepoint is used."""
    pdf_path = tmp_path / "enc_full.pdf"
    doc = fitz.open()
    _add_tier0_page(doc)
    doc.save(
        str(pdf_path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()

    model = _open(pdf_path, TextCommitSettings(engine="tiered"), password="user-secret")
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        model.secure_save_required = True  # force the full/atomic rewrite path
        model.save_as(str(pdf_path))

        # live session must still be able to render/extract after the
        # encrypted save-back (per _reopen_doc_after_save's contract)
        assert REPLACEMENT in model.doc[0].get_text()

        model.ensure_page_index_built(1)
        result = _edit(model, DOWNSTREAM, "Downstream line static")  # advance-neutral
        assert result is EditTextResult.SUCCESS
    finally:
        model.close()

    reopened = fitz.open(str(pdf_path))
    try:
        assert reopened.needs_pass
        assert reopened.authenticate("user-secret") != 0
        assert REPLACEMENT in reopened[0].get_text()
    finally:
        reopened.close()


# ------------------------------------------- part 5 / Stage C: undo after a save
#
# A Tier 0 commit retains forward/inverse PatchSets keyed by xref.  A full save
# that REPLACES the live handle with ``garbage=4`` (``secure_save_required``,
# the product's own switch) renumbers the document, so every retained xref
# points at the wrong object.  History is keyed by PAGE: the command must find
# its stream again on the page it belongs to, or refuse with zero mutation --
# never strand the user with an edit that can no longer be undone.

JUNK_OBJECTS = 5  # unreferenced objects ahead of the page so garbage=4 renumbers


def _write_renumberable_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    for _ in range(JUNK_OBJECTS):
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Junk 1 >>")
    for _ in range(pages):
        _add_tier0_page(doc)
    doc.save(str(path), garbage=0)
    doc.close()


def _edit_cmd(model: PDFModel, probe: str, new_text: str, page_num: int = 1):
    """The edit exactly as the controller wraps it: one undoable command."""
    from model.edit_commands import EditTextCommand

    page_idx = page_num - 1
    block = next(
        b for b in model.block_manager.get_blocks(page_idx) if probe in (b.text or "")
    )
    command = EditTextCommand(
        model=model,
        page_num=page_num,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font=block.font,
        size=block.size,
        color=block.color,
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(page_idx),
        old_block_id=None,
        old_block_text=block.text,
    )
    model.command_manager.execute(command)
    assert command.result is EditTextResult.SUCCESS
    return command


def _content_stream_bytes(model: PDFModel, page_idx: int = 0) -> list[bytes]:
    page = model.doc[page_idx]
    return [model.doc.xref_stream(x) or b"" for x in page.get_contents()]


def _renumbering_full_save(model: PDFModel, path: Path) -> None:
    """The garbage=4 save over the open file; the live handle is replaced."""
    page_xref_before = model.doc[0].xref
    model.secure_save_required = True
    model.save_as(str(path))
    assert model.doc[0].xref != page_xref_before, "the fixture must really renumber"


def test_undo_and_redo_after_a_renumbering_full_save_still_work(tmp_path):
    """RED before: the full save renumbered the page and stream xrefs, the
    retained inverse PatchSet targets the old page xref, and undo is refused
    STALE_UNDO for the rest of the session (the edit can never be undone)."""
    pdf_path = tmp_path / "renumber.pdf"
    _write_renumberable_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        original_streams = _content_stream_bytes(model)
        command = _edit_cmd(model, TARGET, REPLACEMENT)
        assert command._tier0_active and not command._pre_protected
        committed_streams = _content_stream_bytes(model)
        assert committed_streams != original_streams

        _renumbering_full_save(model, pdf_path)
        assert 0 in model.fidelity_protected_pages
        assert _content_stream_bytes(model) == committed_streams

        assert model.command_manager.undo() is True
        assert TARGET in model.doc[0].get_text()
        assert REPLACEMENT not in model.doc[0].get_text()
        assert _content_stream_bytes(model) == original_streams
        assert 0 not in model.fidelity_protected_pages  # pre-edit membership restored

        assert model.command_manager.redo() is True
        assert REPLACEMENT in model.doc[0].get_text()
        assert _content_stream_bytes(model) == committed_streams
        assert 0 in model.fidelity_protected_pages

        # and the translated pair keeps working for another full cycle
        assert model.command_manager.undo() is True
        assert _content_stream_bytes(model) == original_streams
        assert model.command_manager.redo() is True
        assert _content_stream_bytes(model) == committed_streams
    finally:
        model.close()


def test_two_edits_on_a_page_both_undo_and_redo_after_a_renumbering_save(tmp_path):
    """RED before: each command's history is keyed by the old xrefs, so the
    second edit's undo is refused and the first can never be reached."""
    pdf_path = tmp_path / "renumber2.pdf"
    _write_renumberable_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        original_streams = _content_stream_bytes(model)
        _edit_cmd(model, TARGET, REPLACEMENT)
        after_first = _content_stream_bytes(model)
        _edit_cmd(model, DOWNSTREAM, "Downstream line static")  # advance-neutral
        after_second = _content_stream_bytes(model)
        assert len({tuple(original_streams), tuple(after_first), tuple(after_second)}) == 3

        _renumbering_full_save(model, pdf_path)

        assert model.command_manager.undo() is True
        assert _content_stream_bytes(model) == after_first
        assert model.command_manager.undo() is True
        assert _content_stream_bytes(model) == original_streams
        assert model.command_manager.redo() is True
        assert _content_stream_bytes(model) == after_first
        assert model.command_manager.redo() is True
        assert _content_stream_bytes(model) == after_second
    finally:
        model.close()


def test_undo_after_a_renumbering_save_refuses_when_the_stream_changed_since(tmp_path):
    """Fail closed: the stream is found again only by its exact committed
    bytes.  If anything rewrote it after the save, undo is refused with zero
    mutation and the command stays on the undo stack (never a guess)."""
    pdf_path = tmp_path / "renumber3.pdf"
    _write_renumberable_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        _edit_cmd(model, TARGET, REPLACEMENT)
        _renumbering_full_save(model, pdf_path)
        stream_xref = model.doc[0].get_contents()[0]
        tampered = (model.doc.xref_stream(stream_xref) or b"") + b"\n% tampered\n"
        model.doc.update_stream(stream_xref, tampered)

        assert model.command_manager.undo() is False
        assert model.command_manager.undo_count == 1
        assert model.last_commit_outcome.status.value == "stale_plan"
        assert model.doc.xref_stream(stream_xref) == tampered  # zero mutation
        assert 0 in model.fidelity_protected_pages
    finally:
        model.close()


def test_undo_after_a_renumbering_save_never_touches_a_stream_shared_with_another_page(
    tmp_path,
):
    """A content stream that two pages share is not patched in place (it
    would silently edit the other page too): refuse with zero mutation."""
    pdf_path = tmp_path / "renumber_shared.pdf"
    _write_renumberable_pdf(pdf_path, pages=2)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        model.ensure_page_index_built(2)
        _edit_cmd(model, TARGET, REPLACEMENT, page_num=2)
        model.secure_save_required = True
        model.save_as(str(pdf_path))
        # make page 1 share page 2's committed stream (what garbage=4's
        # duplicate merge does for two pages with identical content)
        shared = model.doc[1].get_contents()[0]
        model.doc.xref_set_key(model.doc[0].xref, "Contents", f"{shared} 0 R")
        assert set(model.doc[0].get_contents()) == set(model.doc[1].get_contents())
        before = _content_stream_bytes(model, 1)

        assert model.command_manager.undo() is False
        assert _content_stream_bytes(model, 1) == before
        assert REPLACEMENT in model.doc[1].get_text()
    finally:
        model.close()


def test_undo_survives_a_non_renumbering_full_save_over_the_open_file(tmp_path):
    """GUARD (green before and after): the non-secure full save over the open
    file (temp + copy + reopen, garbage=0) preserves xrefs, so the retained
    patch sets still replay as-is."""
    pdf_path = tmp_path / "full_plain.pdf"
    _write_renumberable_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        original_streams = _content_stream_bytes(model)
        _edit_cmd(model, TARGET, REPLACEMENT)
        model.use_incremental_save = False
        page_xref = model.doc[0].xref
        model.save_as(str(pdf_path))
        assert model.doc[0].xref == page_xref
        assert model.command_manager.undo() is True
        assert _content_stream_bytes(model) == original_streams
        assert model.command_manager.redo() is True
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


WATERMARK = "WMARKX"


def _watermarked_session(tmp_path: Path, *, page: int = 1):
    pdf_path = tmp_path / "wm.pdf"
    _write_renumberable_pdf(pdf_path, pages=2)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    model.ensure_page_index_built(1)
    model.tools.watermark.add_watermark([page], WATERMARK)
    return model, pdf_path


def _saved_text(path: Path, page_index: int = 0) -> str:
    with fitz.open(str(path)) as saved:
        return saved[page_index].get_text()


@pytest.mark.parametrize("mode", ["incremental", "full", "secure"])
def test_undo_redo_survive_a_watermark_save_over_the_open_file(tmp_path, mode):
    """M9-2 (RED before): the prepared-doc (watermark) branch of ``save_as``
    reopened the TARGET as the live handle, so page 1's /Contents carried the
    baked overlay, the xref epoch was dropped and the Tier 0 inverse patch of
    an earlier edit on that page went stale (undo/redo returned False for the
    rest of the session).  The live handle must stay the UNBAKED live doc."""
    model, pdf_path = _watermarked_session(tmp_path)
    try:
        original_streams = _content_stream_bytes(model)
        _edit_cmd(model, TARGET, REPLACEMENT)
        if mode == "full":
            model.use_incremental_save = False
        elif mode == "secure":
            model.secure_save_required = True
        model.save_as(str(pdf_path))
        saved = _saved_text(pdf_path)
        assert WATERMARK in saved and REPLACEMENT in saved  # disk has both
        assert WATERMARK not in model.doc[0].get_text()  # live doc stays unbaked
        if mode != "secure":  # garbage=4 legitimately renumbers the streams
            assert _content_stream_bytes(model) != original_streams
        assert model.command_manager.undo() is True
        assert TARGET in model.doc[0].get_text()
        assert model.command_manager.redo() is True
        assert REPLACEMENT in model.doc[0].get_text()
        assert model.command_manager.undo() is True
        if mode != "secure":
            assert _content_stream_bytes(model) == original_streams
    finally:
        model.close()


def test_watermark_save_over_the_open_file_does_not_stack_copies(tmp_path):
    """The live handle no longer reads the baked target, so repeated Ctrl+S
    writes exactly one overlay each time (TODOS 'stacks another copy per
    save')."""
    model, pdf_path = _watermarked_session(tmp_path)
    try:
        for _ in range(3):
            model.save_as(str(pdf_path))
        assert _saved_text(pdf_path).count(WATERMARK) == 1
        # an undone edit is saved without the edit and still with ONE overlay
        _edit_cmd(model, TARGET, REPLACEMENT)
        model.save_as(str(pdf_path))
        assert model.command_manager.undo() is True
        model.save_as(str(pdf_path))
        text = _saved_text(pdf_path)
        assert TARGET in text and REPLACEMENT not in text
        assert text.count(WATERMARK) == 1
    finally:
        model.close()


def test_watermark_on_another_page_keeps_undo_and_the_session_off_the_target(tmp_path):
    """Page 2 only: undo of the page-1 edit worked before and still does; the
    live handle reads a private temp copy, not the user's file, afterwards."""
    model, pdf_path = _watermarked_session(tmp_path, page=2)
    try:
        _edit_cmd(model, TARGET, REPLACEMENT)
        model.save_as(str(pdf_path))
        backing = model._backing_file(model.doc)
        assert backing is not None and backing != pdf_path.resolve()
        assert Path(model.temp_dir.name).resolve() in backing.resolve().parents
        assert _saved_text(pdf_path, 1).count(WATERMARK) == 1
        assert model.command_manager.undo() is True
    finally:
        model.close()


def test_watermark_save_survives_a_failed_private_copy_reopen(tmp_path, monkeypatch):
    """If the recovery copy cannot be reopened by path the session falls back
    to the in-memory copy (still unbaked, still undoable) and the target is
    complete."""
    model, pdf_path = _watermarked_session(tmp_path)
    try:
        _edit_cmd(model, TARGET, REPLACEMENT)
        real_reopen = model._reopen_doc_after_save

        def flaky(path):
            if Path(path).name.startswith("recover_"):
                raise OSError("locked")
            return real_reopen(path)

        monkeypatch.setattr(model, "_reopen_doc_after_save", flaky)
        model.save_as(str(pdf_path))
        monkeypatch.undo()
        assert WATERMARK in _saved_text(pdf_path)
        assert WATERMARK not in model.doc[0].get_text()
        assert list(Path(model.temp_dir.name).glob("recover_*.pdf")) == []
        assert model.command_manager.undo() is True
    finally:
        model.close()


@pytest.mark.parametrize("mode", ["incremental", "full", "secure"])
def test_a_reopened_watermark_stays_one_copy_through_edit_save_and_undo(tmp_path, mode):
    """F17-COH-2 (RED before): the watermark this build baked into the file
    came back on reopen as the live overlay ON TOP of the baked ink, so every
    Ctrl+S after a reopen baked one more copy.  A reopened session must behave
    like the unbaked session M9-2 keeps: a text edit on the watermarked page,
    Ctrl+S and undo work, and the file holds exactly one copy each cycle."""
    model, pdf_path = _watermarked_session(tmp_path)
    try:
        model.save_as(str(pdf_path))
    finally:
        model.close()
    # Never back to TARGET: page 1 would then equal page 2 byte for byte and the
    # secure save's garbage=4 merges the two streams (a separate undo limit).
    edits = [(TARGET, REPLACEMENT), (REPLACEMENT, "Price 2026")]
    for cycle, (old, new) in enumerate(edits):
        model = _open(pdf_path, TextCommitSettings(engine="tiered"))
        try:
            assert [wm["text"] for wm in model.tools.watermark.get_watermarks()] == [WATERMARK]
            _edit_cmd(model, old, new)
            if mode == "full":
                model.use_incremental_save = False
            elif mode == "secure":
                model.secure_save_required = True
            model.save_as(str(pdf_path))
            saved = _saved_text(pdf_path)
            assert saved.count(WATERMARK) == 1, f"cycle {cycle}"
            assert new in saved and DOWNSTREAM in saved
            assert model.command_manager.undo() is True
            assert old in model.doc[0].get_text()
            assert model.command_manager.redo() is True
        finally:
            model.close()


def test_undo_survives_a_garbage_save_to_a_new_path(tmp_path):
    """RED before: ``save_as`` to a new path under ``secure_save_required``
    writes the LIVE handle with ``garbage=4`` and MuPDF renumbers that handle
    in memory too (measured: the page xref changes with no reopen), so the
    retained xref-keyed patch sets go stale on every secure save, not only on
    a save over the open file."""
    pdf_path = tmp_path / "orig.pdf"
    _write_renumberable_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        original_streams = _content_stream_bytes(model)
        _edit_cmd(model, TARGET, REPLACEMENT)
        page_xref = model.doc[0].xref
        model.secure_save_required = True  # garbage=4 to a NEW path
        model.save_as(str(tmp_path / "copy.pdf"))
        assert model.doc[0].xref != page_xref, "the fixture must really renumber"
        assert model.command_manager.undo() is True
        assert _content_stream_bytes(model) == original_streams
        assert model.command_manager.redo() is True
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_page_xref_layout_never_walks_page_annots(tmp_path, monkeypatch):
    """RED before (V1 review fix-up 2): the layout iterated ``page.annots()``
    (O(n^2) on a dense page, 80 ms on a 367-annotation page) on every Tier
    0/1 commit and relocation.  Only the annotation identity is needed, so
    ``annot_xrefs()`` (one cheap array read) must be used."""
    from model.edit_commands import EditTextCommand

    pdf_path = tmp_path / "annots.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "hello")
    first = page.add_text_annot((100, 100), "a")
    second = page.add_highlight_annot(fitz.Rect(72, 60, 120, 80))
    expected = (first.xref, second.xref)
    doc.save(str(pdf_path))
    doc.close()

    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]

        def _forbidden(self, *args, **kwargs):
            raise AssertionError("_page_xref_layout must not iterate page.annots()")

        monkeypatch.setattr(fitz.Page, "annots", _forbidden)
        layout = EditTextCommand._page_xref_layout(page)
        assert layout[0] == page.xref
        # annot_xrefs() also lists the text annot's Popup; identity only.
        assert set(expected) <= set(layout[3])
        assert tuple(layout[3]) == tuple(entry[0] for entry in page.annot_xrefs())
        assert layout[1] == tuple(page.get_contents())
    finally:
        doc.close()


# --------------------- part 5 final review: relocation admits ONLY a renumbering
#
# The relocation rescue re-derived the page fingerprint from the CURRENT page, so
# after a layout change only the patched stream's bytes were checked: a font,
# ExtGState, annotation, /Rotate, box or extra content stream changed outside the
# undo stack was accepted (before part 5 that was STALE_UNDO, zero mutation).  The
# command now stores a renumbering-invariant fingerprint at commit and relocates
# only when the current page still matches it.


def _mutate_add_font(model: PDFModel) -> None:
    model.doc[0].insert_font(fontname="cour")


def _mutate_add_annot(model: PDFModel) -> None:
    model.doc[0].add_text_annot((300, 300), "added outside the undo stack")


def _mutate_ocr_stream(model: PDFModel) -> None:
    from types import SimpleNamespace

    span = SimpleNamespace(bbox=(72, 100, 200, 120), text="ocr", confidence=0.9)
    assert model.apply_ocr_spans(1, [span]) == 1


def _mutate_rotate(model: PDFModel) -> None:
    model.doc[0].set_rotation(90)


def _mutate_cropbox(model: PDFModel) -> None:
    model.doc[0].set_cropbox(fitz.Rect(10, 10, 500, 700))


def _mutate_extgstate(model: PDFModel) -> None:
    page = model.doc[0]
    model.doc.xref_set_key(
        page.xref, "Resources/ExtGState", "<< /GS9 << /Type /ExtGState /CA 0.5 >> >>"
    )


def _mutate_extra_stream(model: PDFModel) -> None:
    """A content stream OTHER than the patched one is added to /Contents."""
    page = model.doc[0]
    page.insert_text((72, 300), "late", fontsize=9)
    assert len(page.get_contents()) > 1


def _write_renumberable_ocmd_pdf(path: Path) -> None:
    """Round-3 N1 fixture: a second content stream drawn under ``/OC /MC0 BDC``
    whose property entry is an OCMD with ``/P /AnyOn`` (the visibility policy,
    a NAME -- not the back-pointer ``/P`` of an annotation or structure element)."""
    doc = fitz.open()
    for _ in range(JUNK_OBJECTS):
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Junk 1 >>")
    page = _add_tier0_page(doc)
    ocg = doc.get_new_xref()
    doc.update_object(ocg, "<< /Type /OCG /Name (L1) >>")
    ocmd = doc.get_new_xref()
    doc.update_object(ocmd, f"<< /Type /OCMD /OCGs {ocg} 0 R /P /AnyOn >>")
    doc.xref_set_key(
        doc.pdf_catalog(),
        "OCProperties",
        f"<< /OCGs [{ocg} 0 R] /D << /ON [{ocg} 0 R] /Order [{ocg} 0 R] >> >>",
    )
    doc.xref_set_key(page.xref, "Resources/Properties", f"<< /MC0 {ocmd} 0 R >>")
    stream = doc.get_new_xref()
    doc.update_object(stream, "<<>>")
    doc.update_stream(stream, b"/OC /MC0 BDC 0 0 1 rg 300 300 100 100 re f EMC")
    contents = [*page.get_contents(), stream]
    doc.xref_set_key(
        page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in contents) + "]"
    )
    doc.save(str(path), garbage=0)
    doc.close()


def _mutate_ocmd_policy(model: PDFModel) -> None:
    """Flip the OCMD visibility policy: /P is the policy here, not a back-pointer."""
    doc = model.doc
    _, value = doc.xref_get_key(doc[0].xref, "Resources/Properties/MC0")
    ocmd = int(value.split()[0])
    doc.xref_set_key(ocmd, "P", "/AllOff")
    assert doc.xref_get_key(ocmd, "P")[1] == "/AllOff"


_OUTSIDE_FIXTURES = {"ocmd_policy": _write_renumberable_ocmd_pdf}

_OUTSIDE_MUTATIONS = {
    "ocmd_policy": _mutate_ocmd_policy,
    "font": _mutate_add_font,
    "annot": _mutate_add_annot,
    "ocr_stream": _mutate_ocr_stream,
    "rotate": _mutate_rotate,
    "cropbox": _mutate_cropbox,
    "extgstate": _mutate_extgstate,
    "extra_stream": _mutate_extra_stream,
}


@pytest.mark.parametrize("renumber", [False, True], ids=["plain", "after_renumber"])
@pytest.mark.parametrize("mutation", sorted(_OUTSIDE_MUTATIONS))
def test_undo_refuses_when_anything_but_a_renumbering_changed_the_page(
    tmp_path, mutation, renumber
):
    """RED before: font, annot, ocr_stream and extra_stream in both modes (the
    layout moved, the relocation re-derived the fingerprint from the current
    page, and undo patched a page that had changed since the commit); extgstate,
    rotate and cropbox only in ``after_renumber`` (without a renumbering the
    layout does not move, so ``page_fingerprint`` already refused: those three
    ``plain`` cases are GUARDs).  Required: STALE_UNDO, zero mutation, the
    command stays on the stack."""
    pdf_path = tmp_path / f"outside_{mutation}.pdf"
    _OUTSIDE_FIXTURES.get(mutation, _write_renumberable_pdf)(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        command = _edit_cmd(model, TARGET, REPLACEMENT)
        assert command._tier0_active
        if renumber:
            _renumbering_full_save(model, pdf_path)
        _OUTSIDE_MUTATIONS[mutation](model)
        page_bytes = _content_stream_bytes(model)
        forward, inverse = command._tier0_forward_patchset, command._tier0_inverse_patchset

        assert model.command_manager.undo() is False
        assert command.result is EditTextResult.STALE_UNDO
        assert model.command_manager.undo_count == 1
        assert _content_stream_bytes(model) == page_bytes
        assert command._tier0_active
        assert (command._tier0_forward_patchset, command._tier0_inverse_patchset) == (
            forward,
            inverse,
        )
    finally:
        model.close()


def _write_renumberable_rich_pdf(path: Path) -> None:
    """Two pages; page 1 carries a non-ASCII text annotation, a GoTo link to
    page 2 and an ExtGState: everything a content-based fingerprint must see
    identically before and after garbage=4 renumbers and re-serializes it."""
    doc = fitz.open()
    for _ in range(JUNK_OBJECTS):
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Junk 1 >>")
    for _ in range(2):
        _add_tier0_page(doc)
    first = doc[0]
    first.add_text_annot((300, 300), "café ☃ note")
    first.insert_link(
        {
            "kind": fitz.LINK_GOTO,
            "from": fitz.Rect(10, 10, 60, 30),
            "page": 1,
            "to": fitz.Point(0, 0),
        }
    )
    doc.xref_set_key(
        first.xref, "Resources/ExtGState", "<< /GS9 << /Type /ExtGState /CA 0.5 >> >>"
    )
    doc.save(str(path), garbage=0)
    doc.close()


def test_undo_redo_after_a_renumbering_save_on_a_rich_page_still_work(tmp_path):
    """GUARD (green before and after): annotations, links and ExtGState on the
    page must not make a TRUE renumbering look like a foreign change."""
    pdf_path = tmp_path / "rich.pdf"
    _write_renumberable_rich_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        original_streams = _content_stream_bytes(model)
        _edit_cmd(model, TARGET, REPLACEMENT)
        committed_streams = _content_stream_bytes(model)
        _renumbering_full_save(model, pdf_path)
        assert model.command_manager.undo() is True
        assert _content_stream_bytes(model) == original_streams
        assert model.command_manager.redo() is True
        assert _content_stream_bytes(model) == committed_streams
        assert model.command_manager.undo() is True
        assert _content_stream_bytes(model) == original_streams
    finally:
        model.close()


@pytest.mark.parametrize("raise_on_call", [1, 2], ids=["first_call", "second_call"])
@pytest.mark.parametrize("undo_step", [True, False], ids=["undo", "redo"])
def test_a_raising_relocation_helper_is_stale_with_zero_mutation(
    tmp_path, monkeypatch, raise_on_call, undo_step
):
    """RED before: a RuntimeError inside the relocation escaped undo()/redo()
    (or, raised after the splice, left the page mutated).  Required: STALE
    with zero mutation and an unchanged, consistent command."""
    import model.edit_commands as edit_commands

    pdf_path = tmp_path / "raising.pdf"
    _write_renumberable_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        command = _edit_cmd(model, TARGET, REPLACEMENT)
        if not undo_step:
            assert model.command_manager.undo() is True
        _renumbering_full_save(model, pdf_path)
        page_bytes = _content_stream_bytes(model)
        forward, inverse = command._tier0_forward_patchset, command._tier0_inverse_patchset
        active = command._tier0_active
        protected = set(model.fidelity_protected_pages)

        real = edit_commands.page_fingerprint
        calls = {"n": 0}

        def _flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= raise_on_call:
                raise RuntimeError("simulated MuPDF failure")
            return real(*args, **kwargs)

        monkeypatch.setattr(edit_commands, "page_fingerprint", _flaky)

        if undo_step:
            assert model.command_manager.undo() is False
            assert command.result is EditTextResult.STALE_UNDO
            assert model.command_manager.undo_count == 1
        else:
            assert model.command_manager.redo() is False
            assert model.command_manager.redo_count == 1
        assert _content_stream_bytes(model) == page_bytes
        assert (command._tier0_forward_patchset, command._tier0_inverse_patchset) == (
            forward,
            inverse,
        )
        assert command._tier0_active == active
        assert set(model.fidelity_protected_pages) == protected
    finally:
        model.close()


@pytest.mark.parametrize("undo_step", [True, False], ids=["undo", "redo"])
def test_a_write_then_raise_replay_leaves_the_stream_as_committed(
    tmp_path, monkeypatch, undo_step
):
    """RED before (round-3 N2): on the plain (non-relocated) replay path
    ``update_stream`` wrote the replayed bytes and then raised; the handler
    reported STALE ("zero mutation") but the stream already held the replayed
    bytes while the command still believed its previous state.  Required: the
    stream is put back, STALE, the command unchanged and the next replay works."""
    pdf_path = tmp_path / "writefail.pdf"
    _write_renumberable_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        original = _content_stream_bytes(model)
        command = _edit_cmd(model, TARGET, REPLACEMENT)
        committed = _content_stream_bytes(model)
        assert committed != original
        if not undo_step:
            assert model.command_manager.undo() is True
        before = _content_stream_bytes(model)
        forward, inverse = command._tier0_forward_patchset, command._tier0_inverse_patchset
        active = command._tier0_active

        real = fitz.Document.update_stream
        calls = {"n": 0}

        def _write_then_raise(self, xref, data, *args, **kwargs):
            calls["n"] += 1
            result = real(self, xref, data, *args, **kwargs)
            if calls["n"] == 1:
                raise RuntimeError("simulated failure AFTER the write")
            return result

        monkeypatch.setattr(fitz.Document, "update_stream", _write_then_raise)
        if undo_step:
            assert model.command_manager.undo() is False
            assert command.result is EditTextResult.STALE_UNDO
            assert model.command_manager.undo_count == 1
        else:
            assert model.command_manager.redo() is False
            assert model.command_manager.redo_count == 1
        monkeypatch.setattr(fitz.Document, "update_stream", real)

        assert _content_stream_bytes(model) == before
        assert (command._tier0_forward_patchset, command._tier0_inverse_patchset) == (
            forward,
            inverse,
        )
        assert command._tier0_active == active

        # The command is still consistent: the replay that failed now works.
        if undo_step:
            assert model.command_manager.undo() is True
            assert _content_stream_bytes(model) == original
        else:
            assert model.command_manager.redo() is True
            assert _content_stream_bytes(model) == committed
    finally:
        model.close()


# --- R10 MBT-1: uncollected PyMuPDF cycle garbage pinned the file at the install --------
#
# ``Page.first_annot`` / ``Annot.next`` register each walked annotation in a
# strong ``Page._annot_refs`` dict while the annotation holds a strong parent
# page, so a walk over 2+ annotations leaves Page<->Annot cycles.  ``Document.close``
# does not release them: the MuPDF file handle stays open until the cyclic GC
# runs and, on Windows, ``os.replace`` over that file raises PermissionError
# (WinError 5).  ``page_fingerprint`` (every Tier 0 edit) walked the list that way.


def _live_pymupdf_objects() -> tuple[int, int]:
    import gc

    names = [type(o).__name__ for o in gc.get_objects()]
    return names.count("Annot"), names.count("Page")


def _annotated_pdf(path: Path, annots: int) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    for i in range(annots):
        page.add_highlight_annot(fitz.Rect(20, 20 + 30 * i, 120, 40 + 30 * i))
    doc.save(str(path))
    doc.close()
    return path


class _GcOff:
    """Make cycle garbage deterministic: no automatic generation collection."""

    def __enter__(self):
        import gc

        self._was_enabled = gc.isenabled()
        gc.collect()
        gc.disable()
        return self

    def __exit__(self, *exc):
        import gc

        if self._was_enabled:
            gc.enable()
        gc.collect()


@pytest.mark.parametrize("annots", [2, 3, 5])
def test_the_fingerprint_annotation_walk_leaves_no_page_annot_cycle(tmp_path, annots):
    from model.text_commit.inspect import _annotation_entries

    pdf_path = _annotated_pdf(tmp_path / "annots.pdf", annots)
    with _GcOff():
        doc = fitz.open(str(pdf_path))
        page = doc[0]
        baseline = _live_pymupdf_objects()
        entries = _annotation_entries(page)
        assert len(entries) == annots
        assert _live_pymupdf_objects() == baseline
        del page
        doc.close()
        del doc
        # nothing from the walk is left for the cyclic GC
        assert _live_pymupdf_objects()[0] == 0


def test_annotation_lookup_by_xref_leaves_no_page_annot_cycle(tmp_path):
    pdf_path = _annotated_pdf(tmp_path / "annots.pdf", 3)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(pdf_path))
    try:
        xrefs = [x for x, _kind, _id in model.doc[0].annot_xrefs()]
        with _GcOff():
            baseline = _live_pymupdf_objects()
            for xref in xrefs:
                found = model.tools.annotation._find_annotation(xref)
                assert found is not None and found[1].xref == xref
                del found
            assert _live_pymupdf_objects() == baseline
    finally:
        model.close()


def test_replace_file_retries_once_after_a_collection(tmp_path, monkeypatch):
    import gc
    import os

    from utils import path_staging

    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    real_replace = os.replace
    events: list[str] = []

    def flaky(a, b):
        events.append("replace")
        if events.count("replace") == 1:
            raise PermissionError(13, "locked")
        return real_replace(a, b)

    real_collect = gc.collect

    def spy_collect(*args):
        events.append("gc")
        return real_collect(*args)

    monkeypatch.setattr(path_staging.os, "replace", flaky)
    monkeypatch.setattr(path_staging.gc, "collect", spy_collect)
    path_staging.replace_file(src, dst)
    assert events == ["replace", "gc", "replace"]
    assert dst.read_bytes() == b"new" and not src.exists()


def test_replace_file_reraises_a_lock_that_survives_the_collection(tmp_path, monkeypatch):
    from utils import path_staging

    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    calls = {"n": 0}

    def always_locked(a, b):
        calls["n"] += 1
        raise PermissionError(13, "locked")

    monkeypatch.setattr(path_staging.os, "replace", always_locked)
    with pytest.raises(PermissionError):
        path_staging.replace_file(src, dst)
    assert calls["n"] == 2  # one retry, not a loop
    assert dst.read_bytes() == b"old"


def test_replace_file_does_not_collect_when_the_first_replace_works(tmp_path, monkeypatch):
    import gc

    from utils import path_staging

    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(b"new")

    def no_collect(*args):
        raise AssertionError("gc.collect on the happy path")

    monkeypatch.setattr(gc, "collect", no_collect)
    path_staging.replace_file(src, dst)
    assert dst.read_bytes() == b"new"


@pytest.mark.skipif(sys.platform != "win32", reason="an open handle blocks os.replace on Windows only")
def test_write_via_staging_over_a_file_pinned_by_uncollected_cycle_garbage(tmp_path):
    """The retry after a failed Ctrl+S: the target is held only by cycle garbage."""
    from utils.path_staging import write_via_staging

    target = _annotated_pdf(tmp_path / "pinned.pdf", 3)
    with _GcOff():
        doc = fitz.open(str(target))
        page = doc[0]
        annot = page.first_annot
        while annot is not None:  # the PyMuPDF walk that pins the file
            annot = annot.next
        del page, annot
        doc.close()
        del doc
        write_via_staging(target, lambda stage: Path(stage).write_bytes(b"%PDF-new"))
    assert target.read_bytes() == b"%PDF-new"


def _highlights_baked_then_reopened(tmp_path: Path, annots: int):
    model, pdf_path = _watermarked_session(tmp_path)
    try:
        for _ in range(annots):
            model.tools.annotation.add_highlight(1, fitz.Rect(70, 80, 200, 112), (1.0, 1.0, 0.0, 0.5))
        model.save_as(str(pdf_path))  # bake the watermark + the highlights into the file
    finally:
        model.close()
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    return model, pdf_path


@pytest.mark.parametrize("annots", [1, 2, 3])
def test_ctrl_s_after_a_tier0_edit_on_a_page_with_annotations_installs_over_the_open_file(
    tmp_path, annots
):
    """R10 MBT-1: with 2+ annotations the Tier 0 edit's fingerprint left cycle
    garbage pinning the file, so the prepared-clone install over the open file
    raised PermissionError (session rebound to recover_*.pdf, target unwritten,
    retry failing the same way)."""
    model, pdf_path = _highlights_baked_then_reopened(tmp_path, annots)
    try:
        # the baked watermark is a pending attachment again after the reopen
        assert model.tools.watermark.get_watermarks()
        with _GcOff():
            _edit_cmd(model, TARGET, REPLACEMENT)
            before = pdf_path.read_bytes()
            model.save_as(str(pdf_path))  # must not raise
            assert pdf_path.read_bytes() != before
        assert REPLACEMENT in _saved_text(pdf_path)
        assert WATERMARK in _saved_text(pdf_path)
        assert model.has_unsaved_changes() is False
    finally:
        model.close()


def test_install_stage_over_open_file_survives_cycle_garbage_pinning_the_target(tmp_path):
    """Chokepoint guard, independent of which code created the garbage: a
    stray Page<->Annot cycle (any caller) must not break the install."""
    model, pdf_path = _highlights_baked_then_reopened(tmp_path, 3)
    try:
        _edit_cmd(model, TARGET, REPLACEMENT)
        with _GcOff():
            page = model.doc[0]
            annot = page.first_annot
            while annot is not None:  # raw PyMuPDF walk, outside the repo's helpers
                annot = annot.next
            del page, annot
            model.save_as(str(pdf_path))
        assert REPLACEMENT in _saved_text(pdf_path)
        assert model.has_unsaved_changes() is False
    finally:
        model.close()
