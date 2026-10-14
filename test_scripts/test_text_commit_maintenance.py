"""Red-light tests for the clean_contents maintenance policy (plan Task 7).

A fidelity-protected page (one that received a Tier 0 commit) must never
be passed through ``clean_contents`` — not by the interactive maintenance
pass and not by save preparation.  Legacy content rewrites go through one
chokepoint (``mark_page_content_dirty``) which queues the cleanup AND
revokes the page's protection, defining how legacy-edited and
Tier-0-edited pages coexist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402
from model.tools.base import ToolExtension  # noqa: E402
from model.tools.manager import ProtectedPageViolation, _ProtectedPageGuard  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"


def _write_two_page_pdf(path: Path) -> None:
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Some page text", fontsize=12.0, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def _write_tier0_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (Downstream line stays) Tj ET"
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
    doc.save(str(path), garbage=0)
    doc.close()


def _open(path: Path, settings: TextCommitSettings | None = None) -> PDFModel:
    # The default engine is "tiered" since Task 16 T16-3; every caller that
    # omits ``settings`` here is asserting on the legacy redact+reinsert
    # pending/protection machinery, so the fallback pins legacy explicitly
    # rather than tracking the shipped default.
    model = PDFModel(
        text_commit_settings=settings or TextCommitSettings(engine="legacy")
    )
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _edit(model: PDFModel, probe: str, new_text: str, **kwargs) -> EditTextResult:
    block = next(
        b for b in model.block_manager.get_blocks(0) if probe in (b.text or "")
    )
    return model.edit_text(
        1, fitz.Rect(block.layout_rect), new_text, original_text=block.text, **kwargs
    )


# UI step 7 (no silent legacy): a tiered refusal reaches the legacy engine
# only with the explicit rebuild consent -- the request flag plus an accepting
# confirm callback.
_REBUILD_CONSENT = {"allow_rebuild": True, "confirm_fallback": lambda _chain: True}


def test_mark_page_content_dirty_queues_and_revokes_protection(tmp_path):
    pdf_path = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf_path)
    model = _open(pdf_path)
    try:
        model.fidelity_protected_pages.add(0)
        model.mark_page_content_dirty(0, fitz.Rect(10, 10, 100, 100))
        assert 0 not in model.fidelity_protected_pages
        assert model.pending_edits == [
            {"page_idx": 0, "rect": fitz.Rect(10, 10, 100, 100)}
        ]
    finally:
        model.close()


def test_apply_pending_redactions_skips_fidelity_protected_pages(
    tmp_path, monkeypatch
):
    pdf_path = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf_path)
    model = _open(pdf_path)
    try:
        cleaned: list[int] = []
        real_clean = fitz.Page.clean_contents

        def _spy(self, *args, **kwargs):
            cleaned.append(self.number)
            return real_clean(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "clean_contents", _spy)

        # belt-and-braces state: a protected page somehow carries a pending
        # entry — the maintenance pass must still refuse to clean it
        model.pending_edits.append({"page_idx": 0, "rect": fitz.Rect(0, 0, 5, 5)})
        model.pending_edits.append({"page_idx": 1, "rect": fitz.Rect(0, 0, 5, 5)})
        model.fidelity_protected_pages.add(0)

        model.apply_pending_redactions()

        assert cleaned == [1]
        # the protected page's entry survives; the cleaned page's is consumed
        assert [e["page_idx"] for e in model.pending_edits] == [0]
    finally:
        model.close()


def test_save_preparation_respects_protection(tmp_path, monkeypatch):
    pdf_path = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf_path)
    model = _open(pdf_path)
    try:
        cleaned: list[int] = []
        real_clean = fitz.Page.clean_contents

        def _spy(self, *args, **kwargs):
            cleaned.append(self.number)
            return real_clean(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "clean_contents", _spy)
        model.pending_edits.append({"page_idx": 0, "rect": fitz.Rect(0, 0, 5, 5)})
        model.pending_edits.append({"page_idx": 1, "rect": fitz.Rect(0, 0, 5, 5)})
        model.fidelity_protected_pages.add(1)

        model.save_as(str(tmp_path / "saved.pdf"))
        assert cleaned == [0]
    finally:
        model.close()


def test_pending_maintenance_no_longer_blocks_tier0_on_that_page(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        # a legacy rewrite is already queued for this page
        model.mark_page_content_dirty(0, fitz.Rect(0, 0, 10, 10))

        # Part 5 stage B: the fidelity-protection skip in
        # apply_pending_redactions replaces the old pending_page_maintenance
        # refusal, so the true-text engine commits with NO rebuild consent.
        result = _edit(model, TARGET, REPLACEMENT)
        assert result is EditTextResult.SUCCESS
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.fallback_chain == ()
        assert 0 in model.fidelity_protected_pages
        # the queued entry is preserved, never consumed by clean_contents
        model.apply_pending_redactions()
        assert [e["page_idx"] for e in model.pending_edits] == [0]
    finally:
        model.close()


def test_legacy_edit_on_protected_page_drops_protection(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    # The second edit must be refused by the tiered engine to reach legacy;
    # critique step 12 made Tier 1 (which admits it) the default -> Tier 0.
    model = _open(pdf_path, TextCommitSettings(engine="tiered", max_tier=0))
    try:
        assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
        assert 0 in model.fidelity_protected_pages

        # a later legacy-only edit (advance mismatch rejects Tier 0) rewrites
        # the page and must revoke its byte-fidelity protection
        assert (
            _edit(model, REPLACEMENT, "Price 2W25", **_REBUILD_CONSENT)
            is EditTextResult.SUCCESS
        )
        assert 0 not in model.fidelity_protected_pages
        assert [e["page_idx"] for e in model.pending_edits] == [0]
    finally:
        model.close()


# ----------------------------------------- part 5 / Stage C: save-hook guard
#
# ``ToolManager.prepare_doc_for_save`` is the one chokepoint through which an
# extension may touch the document at save time.  Contract: no hook may change
# the content streams of a fidelity-protected page, neither in place on the
# document it is handed (the live one) nor in the clone it returns.  A hook
# that does is refused before anything is written (fail closed), and a
# live-document rewrite is rolled back.


class _CleansPageZero(ToolExtension):
    """A hook that rewrites page 0's content (what ``clean_contents`` does)."""

    def __init__(self, *, in_place: bool) -> None:
        self.in_place = in_place
        self.produced: fitz.Document | None = None

    def prepare_doc_for_save(self, session_id, doc):
        if self.in_place:
            doc[0].clean_contents()
            return None
        clone = fitz.open("pdf", doc.tobytes(garbage=0, no_new_id=1))
        clone[0].clean_contents()
        self.produced = clone
        return clone


def _page0_streams(doc: fitz.Document) -> list[tuple[int, bytes]]:
    return [(x, doc.xref_stream(x) or b"") for x in doc[0].get_contents()]


def _protected_page_after_tier0_edit(tmp_path):
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    assert _edit(model, TARGET, REPLACEMENT) is EditTextResult.SUCCESS
    assert 0 in model.fidelity_protected_pages
    return model


def test_save_hook_rewriting_a_protected_page_in_place_is_refused_and_rolled_back(tmp_path):
    """RED before: the hook's ``clean_contents`` on the live document went
    through unchecked and ``save_as`` wrote the rewritten page."""
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        committed = _page0_streams(model.doc)
        cleaned_probe = fitz.open("pdf", model.doc.tobytes(garbage=0))
        cleaned_probe[0].clean_contents()
        assert _page0_streams(cleaned_probe) != committed, "fixture must be rewritable"
        cleaned_probe.close()

        model.tools._extensions.append(_CleansPageZero(in_place=True))
        out = tmp_path / "out.pdf"
        with pytest.raises(ProtectedPageViolation, match="已拒絕儲存.*已還原"):
            model.save_as(str(out))
        assert not out.exists(), "nothing may be written"
        assert _page0_streams(model.doc) == committed, "live page must be rolled back"
        assert 0 in model.fidelity_protected_pages
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_save_hook_returning_a_rewritten_clone_of_a_protected_page_is_refused(tmp_path):
    """RED before: the rewritten clone was written to disk."""
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        committed = _page0_streams(model.doc)
        hook = _CleansPageZero(in_place=False)
        model.tools._extensions.append(hook)
        out = tmp_path / "out.pdf"
        with pytest.raises(ProtectedPageViolation, match="已拒絕儲存"):
            model.save_as(str(out))
        assert not out.exists()
        assert hook.produced is not None and hook.produced.is_closed
        assert _page0_streams(model.doc) == committed
    finally:
        model.close()


def test_save_hook_may_rewrite_an_unprotected_page(tmp_path):
    """GUARD: the contract covers protected pages only -- a page a legacy edit
    already dirtied stays free to be cleaned by a save hook."""
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        assert 0 not in model.fidelity_protected_pages
        model.tools._extensions.append(_CleansPageZero(in_place=False))
        out = tmp_path / "out.pdf"
        model.save_as(str(out))
        assert out.exists()
    finally:
        model.close()


def test_watermark_save_on_a_protected_page_keeps_the_committed_stream_verbatim(
    tmp_path, monkeypatch
):
    """GUARD (green before and after): a real watermark hook appends to a
    protected page; the committed content stream survives byte-for-byte in
    the saved file, the page never goes through ``clean_contents``, and the
    live document is not touched."""
    cleaned: list[int] = []
    real_clean = fitz.Page.clean_contents

    def _spy(self, *args, **kwargs):
        cleaned.append(self.number)
        return real_clean(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "clean_contents", _spy)
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        committed = _page0_streams(model.doc)
        model.tools.watermark.add_watermark([1], "DRAFT")
        out = tmp_path / "wm_out.pdf"
        model.save_as(str(out))
        assert _page0_streams(model.doc) == committed
        assert 0 in model.fidelity_protected_pages
    finally:
        model.close()
    assert cleaned == []
    with fitz.open(str(out)) as saved:
        saved_streams = [saved.xref_stream(x) or b"" for x in saved[0].get_contents()]
        assert [data for _, data in committed][0] in saved_streams
        text = saved[0].get_text()
        assert "DRAFT" in text and REPLACEMENT in text and TARGET not in text


# V1 review fix-up 5: the guard's roll_back() result used to be ignored, so the
# error always claimed a clean refusal.  The text the user sees (controller
# show_error) is Chinese; the English detail stays in the log.


def test_a_clean_refusal_message_is_chinese_for_the_user(tmp_path):
    """RED before: the user-visible message was an English sentence."""
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        model.tools._extensions.append(_CleansPageZero(in_place=False))
        with pytest.raises(ProtectedPageViolation) as excinfo:
            model.save_as(str(tmp_path / "out.pdf"))
        message = str(excinfo.value)
        assert "已拒絕儲存" in message and "尚未寫入任何檔案" in message, message
        assert "還原失敗" not in message, message
        assert "fidelity" not in message and "refused before" not in message, message
    finally:
        model.close()


def test_a_failed_rollback_is_reported_not_claimed_as_a_clean_refusal(
    tmp_path, monkeypatch
):
    """RED before: with roll_back() returning False the error still said
    "refused before anything was written" and never mentioned that the live
    document could not be restored."""
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        model.tools._extensions.append(_CleansPageZero(in_place=True))
        monkeypatch.setattr(_ProtectedPageGuard, "roll_back", lambda self, doc, pages: False)
        out = tmp_path / "out.pdf"
        with pytest.raises(ProtectedPageViolation) as excinfo:
            model.save_as(str(out))
        message = str(excinfo.value)
        assert "還原失敗" in message, message
        assert "已還原" not in message and "已拒絕儲存" not in message, message
        assert not out.exists(), "nothing may be written"
    finally:
        model.close()


def test_a_failed_rollback_after_a_raising_hook_is_logged(tmp_path, monkeypatch, caplog):
    """RED before: ``_abandon`` dropped roll_back()'s result, so a hook that
    rewrote a protected page and then raised left no trace of the failed
    restore.  The hook's own exception must still propagate unchanged."""
    import logging

    class _RewritesThenRaises(ToolExtension):
        def prepare_doc_for_save(self, session_id, doc):
            doc[0].clean_contents()
            raise ValueError("hook blew up")

    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        model.tools._extensions.append(_RewritesThenRaises())
        monkeypatch.setattr(_ProtectedPageGuard, "roll_back", lambda self, doc, pages: False)
        with caplog.at_level(logging.ERROR, logger="model.tools.manager"):
            with pytest.raises(ValueError, match="hook blew up"):
                model.save_as(str(tmp_path / "out.pdf"))
        assert any("roll" in r.getMessage().lower() for r in caplog.records), caplog.records
    finally:
        model.close()


def test_a_raising_post_hook_check_rolls_back_closes_the_clone_and_propagates(
    tmp_path, monkeypatch
):
    """RED before (round-3 N7): ``_abandon`` wrapped only the hook call, so a
    non-violation exception from the post-hook check (an unreadable xref ...)
    escaped with the live protected page still rewritten and the hook's clone
    unclosed.  Required: roll back, close the clone, re-raise unchanged."""
    from model.tools.manager import ToolManager

    class _RewritesInPlaceAndClones(ToolExtension):
        def __init__(self) -> None:
            self.produced: fitz.Document | None = None

        def prepare_doc_for_save(self, session_id, doc):
            doc[0].clean_contents()
            self.produced = fitz.open("pdf", doc.tobytes(garbage=0, no_new_id=1))
            return self.produced

    def _raising_check(self, *args, **kwargs):
        raise RuntimeError("simulated MuPDF failure inside the check")

    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        committed = _page0_streams(model.doc)
        hook = _RewritesInPlaceAndClones()
        model.tools._extensions[:] = [hook]
        monkeypatch.setattr(ToolManager, "_check_hook", _raising_check)
        out = tmp_path / "out.pdf"
        with pytest.raises(RuntimeError, match="inside the check"):
            model.save_as(str(out))
        assert not out.exists()
        assert hook.produced is not None and hook.produced.is_closed
        assert _page0_streams(model.doc) == committed, "live page must be rolled back"
    finally:
        model.close()


# ----------------------------- part 5 final review: SnapshotCommand bookkeeping
#
# A whole-document SnapshotCommand restores document BYTES.  The maintenance
# bookkeeping a content rewrite changes next to them (``mark_page_content_dirty``
# revokes the page's fidelity protection and queues a ``clean_contents`` entry)
# must travel with the bytes, or undo leaves the restored, verified Tier 0 page
# unprotected and pending -- and the next save rewrites it.


def _png_bytes() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 12, 12), False)
    pix.clear_with(200)
    return pix.tobytes("png")


def _tier0_command(model: PDFModel):
    """The Tier 0 edit exactly as the controller wraps it: one undoable command."""
    from model.edit_commands import EditTextCommand

    block = next(b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or ""))
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
    assert command.result is EditTextResult.SUCCESS and command._tier0_active
    return command


def _protected_page_after_tier0_command(tmp_path):
    pdf_path = tmp_path / "tier0_cmd.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    _tier0_command(model)
    assert 0 in model.fidelity_protected_pages
    return model


def _record_image_op(model: PDFModel):
    """An object op recorded the controller's way: snapshot, op, snapshot."""
    from model.edit_commands import SnapshotCommand

    before = model._capture_doc_snapshot()
    model.add_image_object(1, fitz.Rect(300, 300, 360, 360), _png_bytes())
    after = model._capture_doc_snapshot()
    command = SnapshotCommand(
        model=model,
        command_type="add_image_object",
        affected_pages=[1],
        before_bytes=before,
        after_bytes=after,
        description="Add image object (page 1)",
    )
    model.command_manager.record(command)
    return command


def _pending_pages(model: PDFModel) -> list[int]:
    return sorted(e["page_idx"] for e in model.pending_edits)


def test_undoing_an_object_op_restores_protection_and_pending_so_save_keeps_tier0(tmp_path):
    """RED before: the op's ``mark_page_content_dirty`` unprotected page 0 and
    queued a clean_contents entry; undo restored the bytes but not those, and
    the next save ran clean_contents over the verified Tier 0 stream."""
    model = _protected_page_after_tier0_command(tmp_path)
    try:
        committed = _page0_streams(model.doc)
        pending_before = _pending_pages(model)
        _record_image_op(model)
        assert 0 not in model.fidelity_protected_pages
        assert 0 in _pending_pages(model)

        assert model.command_manager.undo() is True
        assert 0 in model.fidelity_protected_pages
        assert _pending_pages(model) == pending_before

        model.save_as(str(tmp_path / "saved.pdf"))
        assert _page0_streams(model.doc) == committed, "save must not rewrite the Tier 0 stream"
        assert model.command_manager.undo() is True, "the Tier 0 undo must still work"
        assert TARGET in model.doc[0].get_text()
    finally:
        model.close()


def test_redoing_an_object_op_reapplies_dirty_and_unprotected(tmp_path):
    """RED before: redo restored the after-bytes only, so the page stayed
    protected (and not pending) although its content was rewritten."""
    model = _protected_page_after_tier0_command(tmp_path)
    try:
        _record_image_op(model)
        assert model.command_manager.undo() is True
        assert 0 in model.fidelity_protected_pages
        assert model.command_manager.redo() is True
        assert 0 not in model.fidelity_protected_pages
        assert 0 in _pending_pages(model)
        # and a second round trip keeps the pair consistent
        assert model.command_manager.undo() is True
        assert 0 in model.fidelity_protected_pages
    finally:
        model.close()


def test_snapshot_command_without_bookkeeping_snapshots_leaves_state_alone(tmp_path):
    """GUARD (green before and after): plain-bytes snapshots (mocks, older
    callers) carry no bookkeeping, so undo/redo touch only the document."""
    from model.edit_commands import SnapshotCommand

    pdf_path = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf_path)
    model = _open(pdf_path)
    try:
        before = bytes(model._capture_doc_snapshot())
        model.fidelity_protected_pages.add(1)
        after = bytes(model._capture_doc_snapshot())
        command = SnapshotCommand(
            model=model,
            command_type="x",
            affected_pages=[1],
            before_bytes=before,
            after_bytes=after,
            description="x",
        )
        command.undo()
        command.execute()
        assert model.fidelity_protected_pages == {1}
    finally:
        model.close()


# ------------------------- part 5 final review: the protected-page guard's cost
#
# The guard decoded every protected stream before the hooks and again after each
# of the four extensions on every save (about 90 ms per protected page on the
# 50-page hvac drawing).  It now snapshots the raw bytes and the dictionary,
# decodes only a stream whose storage changed, and is not consulted for an
# extension that does not override ``prepare_doc_for_save``.


class _Overrides(ToolExtension):
    """Overrides the hook but changes nothing."""

    def prepare_doc_for_save(self, session_id, doc):
        return None


def _two_extensions(model: PDFModel, *extensions: ToolExtension) -> str:
    model.tools._extensions[:] = list(extensions)
    return model.get_active_session_id()


def test_an_extension_using_the_base_no_op_is_not_re_checked(tmp_path, monkeypatch):
    """GUARD (green before and after for correctness; RED before for cost):
    the base-class no-op cannot rewrite a page, so the guard is not asked to
    compare every protected stream again after it."""
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        sid = _two_extensions(model, ToolExtension(), ToolExtension())
        calls = {"place": 0, "clone": 0}
        real_place = _ProtectedPageGuard.violations_in_place
        real_clone = _ProtectedPageGuard.violations_in_clone

        def _place(self, doc):
            calls["place"] += 1
            return real_place(self, doc)

        def _clone(self, clone):
            calls["clone"] += 1
            return real_clone(self, clone)

        monkeypatch.setattr(_ProtectedPageGuard, "violations_in_place", _place)
        monkeypatch.setattr(_ProtectedPageGuard, "violations_in_clone", _clone)
        assert model.tools.prepare_doc_for_save(sid, model.doc) is None
        assert calls == {"place": 0, "clone": 0}
    finally:
        model.close()


def test_an_overriding_extension_is_still_checked(tmp_path, monkeypatch):
    """GUARD: an extension that DOES override the hook is checked, even when it
    returns nothing -- it may have rewritten the live document in place."""
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        sid = _two_extensions(model, _Overrides())
        calls = {"place": 0}
        real_place = _ProtectedPageGuard.violations_in_place

        def _place(self, doc):
            calls["place"] += 1
            return real_place(self, doc)

        monkeypatch.setattr(_ProtectedPageGuard, "violations_in_place", _place)
        model.tools.prepare_doc_for_save(sid, model.doc)
        assert calls["place"] == 1
    finally:
        model.close()


def test_the_guard_never_decodes_a_protected_stream_that_did_not_change(
    tmp_path, monkeypatch
):
    """RED before: ``read_page_streams`` and ``capture_stream_storage`` decoded
    every protected content stream up front, and every check decoded it again."""
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        sid = _two_extensions(model, _Overrides(), _Overrides())
        decoded: list[int] = []
        real = fitz.Document.xref_stream

        def _spy(self, xref):
            decoded.append(xref)
            return real(self, xref)

        monkeypatch.setattr(fitz.Document, "xref_stream", _spy)
        model.tools.prepare_doc_for_save(sid, model.doc)
        monkeypatch.undo()
        assert decoded == [], f"unchanged protected streams were decoded: {decoded}"
    finally:
        model.close()


def test_a_hook_that_only_re_encodes_a_protected_stream_is_not_a_violation(tmp_path):
    """GUARD (green before and after): the contract is about CONTENT.  A hook
    that rewrites a protected stream's storage (here: Flate-compressed) without
    changing a decoded byte is allowed, exactly as before the cost fix."""

    class _Reencodes(ToolExtension):
        def prepare_doc_for_save(self, session_id, doc):
            import zlib

            for xref in doc[0].get_contents():
                doc.update_stream(
                    xref, zlib.compress(doc.xref_stream(xref) or b""), compress=False
                )
                doc.xref_set_key(xref, "Filter", "/FlateDecode")
            return None

    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        committed = _page0_streams(model.doc)
        raw_before = [model.doc.xref_stream_raw(x) for x, _ in committed]
        sid = _two_extensions(model, _Reencodes())
        model.tools.prepare_doc_for_save(sid, model.doc)
        assert _page0_streams(model.doc) == committed
        assert [model.doc.xref_stream_raw(x) for x, _ in committed] != raw_before, (
            "fixture must really re-encode"
        )
    finally:
        model.close()


def test_a_hook_that_changes_a_protected_streams_content_is_still_caught(tmp_path):
    """GUARD: the lazy comparison must still see a real content change that
    keeps the stream's encoding (the decode-only-on-difference path)."""

    class _Tampers(ToolExtension):
        def prepare_doc_for_save(self, session_id, doc):
            xref = doc[0].get_contents()[0]
            doc.update_stream(xref, (doc.xref_stream(xref) or b"") + b"\n% x\n")
            return None

    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        committed = _page0_streams(model.doc)
        sid = _two_extensions(model, _Tampers())
        with pytest.raises(ProtectedPageViolation, match="已拒絕儲存.*已還原"):
            model.tools.prepare_doc_for_save(sid, model.doc)
        assert _page0_streams(model.doc) == committed
    finally:
        model.close()


# ------------------------- round 4 HIST-2: the move's rollback carries the book
#
# ``move_text_across_pages`` captures ``before = _capture_doc_snapshot()``, deletes
# the source line through a consented legacy rebuild (which unprotects the page
# and queues a clean_contents entry), and on any later failure restores
# ``before`` through ``replace_active_document_from_snapshot``.  That path put the
# BYTES back only, so the verified Tier 0 page stayed unprotected and pending: the
# next save rewrote it and the earlier Tier 0 edit's undo went STALE_UNDO.


def test_replace_active_document_from_snapshot_restores_the_book_with_the_bytes(tmp_path):
    """RED before: bytes came back, bookkeeping did not."""
    model = _protected_page_after_tier0_command(tmp_path)
    try:
        tier0 = model.command_manager._undo_stack[-1]
        committed = _page0_streams(model.doc)
        pending_before = _pending_pages(model)
        before = model._capture_doc_snapshot()

        result = _edit(model, "Downstream", "", **_REBUILD_CONSENT)
        assert result is EditTextResult.SUCCESS
        assert 0 not in model.fidelity_protected_pages, "precondition: legacy rebuild unprotects"
        assert 0 in _pending_pages(model), "precondition: legacy rebuild queues clean_contents"

        # The controller's except path.
        model.replace_active_document_from_snapshot(before, [1])

        assert _page0_streams(model.doc) == committed
        assert model.fidelity_protected_pages == {0}
        assert _pending_pages(model) == pending_before

        model.save_as(str(tmp_path / "saved.pdf"))
        assert _page0_streams(model.doc) == committed, "save must not rewrite the Tier 0 stream"
        assert model.command_manager.undo() is True, "the Tier 0 undo must still work"
        assert tier0.result is not EditTextResult.STALE_UNDO
        assert TARGET in model.doc[0].get_text()
    finally:
        model.close()


def test_replace_active_document_from_snapshot_with_plain_bytes_leaves_the_book_alone(tmp_path):
    """GUARD (green before and after): bytes without a book (the controller's
    merge, mocks) restore the document only."""
    model = _protected_page_after_tier0_command(tmp_path)
    try:
        plain = bytes(model._capture_doc_snapshot())
        model.fidelity_protected_pages.discard(0)
        model.replace_active_document_from_snapshot(plain, [1])
        assert model.fidelity_protected_pages == set()
    finally:
        model.close()


# ------------------------- round 5 SWEEP-A1: every document-snapshot restore owns the book
#
# ``delete_objects_atomic`` (a batch delete from the controller) captures
# ``before = _capture_doc_snapshot()``, mutates a protected page through the first
# request (``mark_page_content_dirty`` revokes its protection) and a later request
# fails.  ``_restore_delete_transaction`` put the BYTES and ``pending_edits`` back
# but not ``fidelity_protected_pages``, so the verified Tier 0 page was pending and
# unprotected: the next save ran clean_contents over it and the Tier 0 undo went
# STALE_UNDO.  The class is "a restore of a ``DocSnapshot`` that forgets its book";
# the one chokepoint is ``PDFModel._restore_doc_from_snapshot``.


def _failed_batch_after_tier0(tmp_path):
    from model.object_requests import DeleteObjectRequest

    pdf_path = tmp_path / "tier0_batch.pdf"
    _write_tier0_pdf(pdf_path)
    model = _open(pdf_path, TextCommitSettings(engine="tiered"))
    # An image added earlier leaves a pending entry on page 0 (kept for protected
    # pages by design), so protection is the only thing standing between a save and
    # clean_contents.
    oid = model.add_image_object(1, fitz.Rect(300, 300, 360, 360), _png_bytes())
    tier0 = _tier0_command(model)
    assert model.fidelity_protected_pages == {0}
    assert _pending_pages(model) == [0]
    committed = _page0_streams(model.doc)
    ok = model.delete_objects_atomic(
        [
            DeleteObjectRequest(object_id=oid, object_kind="image", page_num=1),
            DeleteObjectRequest(object_id="bogus-id", object_kind="rect", page_num=1),
        ]
    )
    assert ok is False
    assert _page0_streams(model.doc) == committed, "precondition: the bytes were rolled back"
    return model, tier0, committed


def test_failed_batch_delete_rollback_restores_protection_with_the_bytes(tmp_path):
    """RED before: protection {0} came back as set()."""
    model, _tier0, _committed = _failed_batch_after_tier0(tmp_path)
    try:
        assert model.fidelity_protected_pages == {0}
        assert _pending_pages(model) == [0]
    finally:
        model.close()


def test_failed_batch_delete_then_save_keeps_the_tier0_stream_and_its_undo(tmp_path):
    """RED before: the save rewrote the stream and the Tier 0 undo was STALE_UNDO."""
    model, tier0, committed = _failed_batch_after_tier0(tmp_path)
    try:
        model.save_as(str(tmp_path / "saved.pdf"))
        assert _page0_streams(model.doc) == committed, "save must not rewrite the Tier 0 stream"
        assert model.command_manager.undo() is True, "the Tier 0 undo must still work"
        assert tier0.result is not EditTextResult.STALE_UNDO
        assert TARGET in model.doc[0].get_text()
    finally:
        model.close()


def test_restore_doc_from_snapshot_restores_the_book_carried_by_the_snapshot(tmp_path):
    """RED before: the chokepoint put the bytes back and left the book alone, so
    every caller had to remember it (delete batch, delete_pages, move_page, ...)."""
    model = _protected_page_after_tier0_command(tmp_path)
    try:
        before = model._capture_doc_snapshot()
        pending_before = _pending_pages(model)
        model.mark_page_content_dirty(0, fitz.Rect(0, 0, 50, 50))
        assert 0 not in model.fidelity_protected_pages

        model._restore_doc_from_snapshot(before)

        assert model.fidelity_protected_pages == {0}
        assert _pending_pages(model) == pending_before
    finally:
        model.close()


def test_restore_doc_from_snapshot_with_plain_bytes_leaves_the_book_alone(tmp_path):
    """GUARD (green before and after): bytes without a book restore the document only."""
    model = _protected_page_after_tier0_command(tmp_path)
    try:
        plain = bytes(model._capture_doc_snapshot())
        model.fidelity_protected_pages.discard(0)
        model._restore_doc_from_snapshot(plain)
        assert model.fidelity_protected_pages == set()
    finally:
        model.close()


def test_failed_delete_pages_rollback_keeps_the_bookkeeping(tmp_path):
    """GUARD: the model's own rollback of a failed page deletion leaves a protected
    page protected and its pending entries exactly as they were."""
    pdf_path = tmp_path / "two_tier0.pdf"
    _write_tier0_pdf(pdf_path)
    doc = fitz.open(str(pdf_path))
    doc.new_page(width=595, height=842)
    two_path = tmp_path / "two_tier0_pages.pdf"
    doc.save(str(two_path), garbage=0)
    doc.close()
    model = _open(two_path, TextCommitSettings(engine="tiered"))
    try:
        _tier0_command(model)
        assert model.fidelity_protected_pages == {0}
        pending_before = _pending_pages(model)

        def _boom(_idxs):
            raise RuntimeError("index shift failed")

        model.block_manager.shift_after_delete = _boom
        with pytest.raises(RuntimeError):
            model.delete_pages([2])
        assert model.fidelity_protected_pages == {0}
        assert _pending_pages(model) == pending_before
    finally:
        model.close()


def test_a_failed_protected_page_rollback_latches_the_session_damaged(tmp_path, monkeypatch):
    """S13-DLG5-DAMAGED, same bug class: the error already says "do not overwrite
    the original", but nothing stopped the next Ctrl+S from doing exactly that."""
    from model.pdf_model import DamagedSessionSaveError

    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        original = model.original_path
        model.tools._extensions.append(_CleansPageZero(in_place=True))
        monkeypatch.setattr(_ProtectedPageGuard, "roll_back", lambda self, doc, pages: False)
        assert model.session_damaged is False
        with pytest.raises(ProtectedPageViolation, match="還原失敗"):
            model.save_as(str(tmp_path / "out.pdf"))
        assert model.session_damaged is True
        before = Path(original).read_bytes()
        with pytest.raises(DamagedSessionSaveError):
            model.save_as(original)
        assert Path(original).read_bytes() == before
    finally:
        model.close()


def test_a_failed_rollback_after_a_raising_hook_latches_the_session_damaged(tmp_path, monkeypatch):
    class _RewritesThenRaises(ToolExtension):
        def prepare_doc_for_save(self, session_id, doc):
            doc[0].clean_contents()
            raise ValueError("hook blew up")

    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        model.tools._extensions.append(_RewritesThenRaises())
        monkeypatch.setattr(_ProtectedPageGuard, "roll_back", lambda self, doc, pages: False)
        with pytest.raises(ValueError, match="hook blew up"):
            model.save_as(str(tmp_path / "out.pdf"))
        assert model.session_damaged is True
    finally:
        model.close()


def test_a_successful_protected_page_rollback_does_not_latch_damaged(tmp_path):
    model = _protected_page_after_tier0_edit(tmp_path)
    try:
        model.tools._extensions.append(_CleansPageZero(in_place=True))
        with pytest.raises(ProtectedPageViolation, match="已還原"):
            model.save_as(str(tmp_path / "out.pdf"))
        assert model.session_damaged is False
    finally:
        model.close()


# ------------------------------- F14-MM-4: the every-5th-edit pass is page-local
#
# ``edit_text`` runs the interactive ``clean_contents`` maintenance on every 5th
# edit.  An undo unit (``EditTextCommand``) snapshots and book-keeps ONE page, so
# a pass that also cleaned the OTHER queued pages rewrote bytes no command owned:
# undoing that edit left those pages in their cleaned form, and undo-all /
# redo-all ended in a different byte state than the edited one.  The interactive
# pass is therefore scoped to the edited page; every other page's queue entry
# waits for the save-time pass (which is outside the undo history by design).

_WORDS = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")


def _write_word_pdf(path: Path, pages: int = 2) -> None:
    doc = fitz.open()
    for pg in range(pages):
        page = doc.new_page(width=595, height=842)
        y = 100
        for word in _WORDS:
            page.insert_text((72, y), f"{word}{pg + 1}", fontsize=12.0, fontname="helv")
            y += 24
    doc.save(str(path))
    doc.close()


def _stream_bytes(model: PDFModel, page_idx: int) -> bytes:
    return bytes(model.doc[page_idx].read_contents())


def _rebuild_edit(model: PDFModel, page_idx: int, word: str) -> None:
    """One consented rebuild (a CJK glyph forces the legacy engine), executed
    through ``EditTextCommand`` exactly like the controller does."""
    from model.edit_commands import EditTextCommand

    model.ensure_page_index_built(page_idx + 1)
    page = model.doc[page_idx]
    rect = page.search_for(word)[0]
    point = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    hit = model.get_text_info_at_point(page_idx + 1, point)
    assert hit is not None and word in hit.target_text
    cmd = EditTextCommand(
        model=model,
        page_num=page_idx + 1,
        rect=fitz.Rect(hit.target_bbox),
        new_text=hit.target_text + "中",
        font=hit.font,
        size=hit.size,
        color=hit.color,
        original_text=hit.target_text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(page_idx),
        old_block_id=hit.target_span_id,
        old_block_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode=hit.target_mode,
        confirm_fallback=lambda _chain: True,
        source_ref=hit.source_ref,
        requires_preview_token=False,
        allow_rebuild=True,
    )
    model.command_manager.execute(cmd)
    assert cmd.result is EditTextResult.SUCCESS


# page 1 once, then page 2 four times: edit 5 is on page 2 and is the edit that
# triggers the maintenance pass while page 1 still has its queue entry.
_FIVE_EDITS = [(0, "Alpha1"), (1, "Alpha2"), (1, "Bravo2"), (1, "Charlie2"), (1, "Delta2")]


def _five_consented_edits(model: PDFModel) -> list[tuple[bytes, bytes]]:
    states = []
    for page_idx, word in _FIVE_EDITS:
        _rebuild_edit(model, page_idx, word)
        states.append((_stream_bytes(model, 0), _stream_bytes(model, 1)))
    return states


def _default_model(path: Path) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def test_the_fifth_edit_pass_cleans_only_the_edited_page(tmp_path):
    """RED before: edit 5 (on page 2) also ran ``clean_contents`` on page 1 and
    consumed its queue entry."""
    pdf_path = tmp_path / "words.pdf"
    _write_word_pdf(pdf_path)
    model = _default_model(pdf_path)
    try:
        states = _five_consented_edits(model)
        assert model.edit_count == 5
        assert states[4][0] == states[3][0], "edit 5 rewrote page 1 (not its page)"
        assert 0 in {e["page_idx"] for e in model.pending_edits}, (
            "page 1's queued clean_contents entry was consumed by another page's edit"
        )
        assert 1 not in {e["page_idx"] for e in model.pending_edits}
    finally:
        model.close()


def test_the_interactive_pass_spies_only_the_edited_page(tmp_path, monkeypatch):
    pdf_path = tmp_path / "words.pdf"
    _write_word_pdf(pdf_path)
    model = _default_model(pdf_path)
    try:
        for page_idx, word in _FIVE_EDITS[:4]:
            _rebuild_edit(model, page_idx, word)
        cleaned: list[int] = []
        real_clean = fitz.Page.clean_contents

        def _spy(self, *args, **kwargs):
            cleaned.append(self.number)
            return real_clean(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "clean_contents", _spy)
        _rebuild_edit(model, 1, "Delta2")
        assert 0 not in cleaned, f"clean_contents ran on a page the edit did not touch: {cleaned}"
    finally:
        model.close()


def test_undoing_the_fifth_edit_restores_every_page_s_bytes(tmp_path):
    """RED before: page 1 stayed in the form the maintenance pass gave it."""
    pdf_path = tmp_path / "words.pdf"
    _write_word_pdf(pdf_path)
    model = _default_model(pdf_path)
    try:
        states = _five_consented_edits(model)
        assert model.command_manager.undo()
        assert (_stream_bytes(model, 0), _stream_bytes(model, 1)) == states[3]
    finally:
        model.close()


def test_undo_all_then_redo_all_returns_to_the_edited_bytes(tmp_path):
    """RED before: page 1 ended at its un-cleaned form, never re-cleaned."""
    pdf_path = tmp_path / "words.pdf"
    _write_word_pdf(pdf_path)
    model = _default_model(pdf_path)
    try:
        states = _five_consented_edits(model)
        for _ in range(5):
            assert model.command_manager.undo()
        for _ in range(5):
            assert model.command_manager.redo()
        assert (_stream_bytes(model, 0), _stream_bytes(model, 1)) == states[4]
    finally:
        model.close()


def test_the_save_time_pass_still_cleans_the_page_the_interactive_pass_left(tmp_path, monkeypatch):
    """GUARD: scoping the interactive pass loses nothing -- page 1's queue entry
    survives to the save, which cleans every unprotected queued page."""
    pdf_path = tmp_path / "words.pdf"
    _write_word_pdf(pdf_path)
    model = _default_model(pdf_path)
    try:
        _five_consented_edits(model)
        cleaned: list[int] = []
        real_clean = fitz.Page.clean_contents

        def _spy(self, *args, **kwargs):
            cleaned.append(self.number)
            return real_clean(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "clean_contents", _spy)
        model.save_as(str(tmp_path / "saved.pdf"))
        assert 0 in cleaned
        assert model.pending_edits == []
    finally:
        model.close()


def test_undo_redo_across_a_save_requeues_the_compaction_the_save_performed(tmp_path):
    """GUARD (F14-MM-4, save-boundary half; green before and after): the
    save-time ``clean_contents`` is not an undo unit.  After save -> undo -> redo
    the page is back in its edited form WITH its queue entry restored, so the
    owed compaction is not lost: the next save writes the same stream the first
    save did."""
    pdf_path = tmp_path / "words.pdf"
    _write_word_pdf(pdf_path, pages=1)
    model = _default_model(pdf_path)
    try:
        _rebuild_edit(model, 0, "Alpha1")
        edited = _stream_bytes(model, 0)
        model.save_as(str(tmp_path / "first.pdf"))
        saved = _stream_bytes(model, 0)
        assert saved != edited, "fixture: the save must compact the page"
        assert model.pending_edits == []
        assert model.command_manager.undo()
        assert model.command_manager.redo()
        assert _stream_bytes(model, 0) == edited
        assert [e["page_idx"] for e in model.pending_edits] == [0]
        model.save_as(str(tmp_path / "second.pdf"))
        assert _stream_bytes(model, 0) == saved
    finally:
        model.close()


# ------------------------- F17-COH-3 same class: page-indexed bookkeeping follows its page
#
# ``pending_edits`` and ``fidelity_protected_pages`` name pages by 0-based INDEX.  A
# structural op left them alone: after ``delete_pages([1])`` the protection still named
# the old index (now a different page), so a save cleaned a page it should have left and
# skipped the one it should clean.  They now move with their page through the model's one
# structural chokepoint, and the ``DocSnapshot`` book brings them back exactly on undo.


def _write_labelled_pdf(path: Path, labels: list[str]) -> None:
    doc = fitz.open()
    for label in labels:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), label, fontsize=12.0, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def _bookkeeping(model: PDFModel) -> tuple[set[int], list[int]]:
    return set(model.fidelity_protected_pages), sorted(e["page_idx"] for e in model.pending_edits)


def _record_structural(model: PDFModel, command_type: str, operation):
    from model.edit_commands import SnapshotCommand

    before = model._capture_doc_snapshot()
    result = operation()
    after = model._capture_doc_snapshot()
    model.command_manager.record(SnapshotCommand(model, command_type, result, before, after, command_type))
    return result


@pytest.fixture
def four_page_model(tmp_path):
    path = tmp_path / "four.pdf"
    _write_labelled_pdf(path, ["AAAA", "BBBB", "CCCC", "DDDD"])
    model = _open(path)
    yield model
    model.close()


def _mark(model: PDFModel, protected: set[int], pending: list[int]) -> None:
    model.fidelity_protected_pages.update(protected)
    for page_idx in pending:
        model.pending_edits.append({"page_idx": page_idx, "rect": fitz.Rect(0, 0, 5, 5)})


def test_delete_pages_moves_protection_and_pending_entries_with_their_pages(four_page_model):
    model = four_page_model
    _mark(model, {1, 3}, [1, 2])  # B and D protected; B and C pending

    model.delete_pages([1])  # A goes away: B, C, D are now pages 0, 1, 2

    assert _bookkeeping(model) == ({0, 2}, [0, 1])


def test_delete_pages_drops_the_bookkeeping_of_a_deleted_page(four_page_model):
    model = four_page_model
    _mark(model, {1, 2}, [1, 2])

    model.delete_pages([2])  # B goes away

    assert _bookkeeping(model) == ({1}, [1])  # only C (now page 1) is left


def test_move_page_moves_the_bookkeeping_with_the_page(four_page_model):
    model = four_page_model
    _mark(model, {0, 2}, [2])  # A and C protected, C pending

    model.move_page(0, 3)  # B, C, D, A

    assert _bookkeeping(model) == ({1, 3}, [1])


def test_insert_blank_page_shifts_the_bookkeeping_of_later_pages(four_page_model):
    model = four_page_model
    _mark(model, {1}, [1, 3])

    model.insert_blank_page(1)  # blank, A, B, C, D

    assert _bookkeeping(model) == ({2}, [2, 4])


def test_a_pending_clean_contents_entry_follows_its_page_to_the_save(four_page_model, monkeypatch):
    """The TODOS repro: B Tier-0 protected, C queued for cleaning.  After deleting A the
    save must still clean C and leave B alone (the stale indices cleaned D and kept C)."""
    model = four_page_model
    _mark(model, {1}, [2])
    cleaned: list[int] = []
    real_clean = fitz.Page.clean_contents

    def _spy(self, *args, **kwargs):
        cleaned.append(self.number)
        return real_clean(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "clean_contents", _spy)
    model.delete_pages([1])

    model.apply_pending_redactions()

    assert cleaned == [1]  # C, now page index 1
    assert model.fidelity_protected_pages == {0}  # B stays protected


def test_undo_and_redo_of_a_structural_op_restore_the_bookkeeping_exactly(four_page_model):
    model = four_page_model
    _mark(model, {1, 3}, [1, 2])
    original = _bookkeeping(model)

    _record_structural(model, "delete_pages", lambda: model.delete_pages([1]))
    after = _bookkeeping(model)
    assert after == ({0, 2}, [0, 1])

    assert model.command_manager.undo()
    assert _bookkeeping(model) == original
    assert model.command_manager.redo()
    assert _bookkeeping(model) == after
    assert model.command_manager.undo()
    assert _bookkeeping(model) == original
