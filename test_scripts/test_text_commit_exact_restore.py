"""Red-light tests for exact stream-storage restore (plan Task 15 P4-B2
slice 1, ``plans/task15-p4b2-exact-painter-geometry-admission.md`` section
1.3).

``AppliedPatch.revert`` and undo/redo used to rewrite a reverted stream with
``update_stream(xref, decoded, compress=True)``: decoded content came back
exact, but the stream's own storage encoding (compression, ``/Filter``,
``/DecodeParms``) did not -- a FAILED live verification, an undo, or a redo
left an originally-uncompressed or multi-filter content stream re-encoded
as a single ``/FlateDecode`` object with different raw bytes (Codex
adversarial review, 2026-09-02; TODOS). This module pins the fix: exact raw
bytes + object dict restore (``model.text_commit.inspect.
capture_stream_storage`` / ``restore_stream_storage``), never just decoded
content, across every storage encoding in
``test_scripts/stream_storage_fixtures.py``.
"""
from __future__ import annotations

import hashlib
import logging
import sys
import zlib
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.engine as engine_module  # noqa: E402
from model.edit_commands import EditTextCommand  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    StreamReplacement,
    TextCommitSettings,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    capture_stream_storage,
    page_fingerprint,
    restore_stream_storage,
)
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.verify import VerificationFailure  # noqa: E402
from test_scripts.stream_storage_fixtures import (  # noqa: E402
    CASES,
    REPLACEMENT,
    TARGET,
    open_case,
    write_case_pdf,
)

TIER0_CASES = ("a", "b", "c", "d")  # cases with a real bindable TARGET show


# --------------------------------------------------------------- helpers


def _full_stream_patchset(doc: fitz.Document, page: fitz.Page) -> PatchSet:
    """A full-stream, harmlessly-mutating PatchSet over every content
    stream on ``page`` -- exercises apply_patchset/revert's storage
    machinery independent of any real text binding."""
    fingerprint = page_fingerprint(doc, page)
    replacements = []
    for xref in page.get_contents():
        current = doc.xref_stream(xref) or b""
        digest = hashlib.sha256(current).hexdigest()
        replacements.append(
            StreamReplacement(
                stream_xref=xref,
                start=0,
                end=len(current),
                expected_bytes=current,
                replacement_bytes=current + b" ",
                expected_stream_digest=digest,
            )
        )
    return PatchSet(
        page_xref=page.xref,
        replacements=tuple(replacements),
        expected_page_fingerprint=fingerprint,
    )


def _capture_all(doc: fitz.Document, page: fitz.Page) -> dict:
    return {xref: capture_stream_storage(doc, xref) for xref in page.get_contents()}


def _prepare_plan_for_case(doc: fitz.Document, page: fitz.Page, registry) -> PreparedEdit:
    span = None
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for sp in line["spans"]:
                text = "".join(ch["c"] for ch in sp["chars"])
                if TARGET in text:
                    span = sp
    assert span is not None, "fixture TARGET not found in rawdict"
    plan = prepare_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=tuple(span["origin"]),
        target_bbox=None,
        registry=registry,
    )
    assert isinstance(plan, PreparedEdit), getattr(plan, "reason", plan)
    return plan


def _open_model(path: Path, settings: TextCommitSettings) -> PDFModel:
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _make_command(model: PDFModel, probe: str, new_text: str) -> EditTextCommand:
    block = next(
        b for b in model.block_manager.get_blocks(0) if probe in (b.text or "")
    )
    return EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(0),
        old_block_id=None,
        old_block_text=block.text,
    )


# ------------------------------------------------------- 1. apply + revert


@pytest.mark.parametrize("case", CASES)
def test_apply_then_revert_restores_exact_storage_for_every_encoding(case):
    doc = open_case(case)
    page = doc[0]
    before = _capture_all(doc, page)
    patchset = _full_stream_patchset(doc, page)
    applied = apply_patchset(doc, page, patchset)
    # the mutation actually happened -- revert has something to undo
    assert _capture_all(doc, page) != before
    assert applied.revert(doc) is True
    after = _capture_all(doc, page)
    assert after == before
    doc.close()


# ------------------------------------------------ 2. real engine.commit


@pytest.mark.parametrize("case", TIER0_CASES)
def test_engine_commit_failed_verify_reverts_exact_storage(case, monkeypatch):
    doc = open_case(case)
    page = doc[0]
    engine = TieredCommitEngine(doc)
    xref = page.get_contents()[0]
    original = capture_stream_storage(doc, xref)
    plan = _prepare_plan_for_case(doc, page, engine.registry)

    def failing_verify(*args, **kwargs):
        return VerificationFailure(RejectReason.VERIFICATION_FAILED, "injected by test")

    monkeypatch.setattr(engine_module, "verify_tier0_commit", failing_verify)

    outcome = engine.commit(plan)

    assert outcome.status == CommitStatus.FAILED, outcome
    assert capture_stream_storage(doc, xref) == original
    doc.close()


@pytest.mark.parametrize("case", TIER0_CASES)
def test_engine_commit_raising_verifier_reverts_exact_storage_and_reraises(case, monkeypatch):
    doc = open_case(case)
    page = doc[0]
    engine = TieredCommitEngine(doc)
    xref = page.get_contents()[0]
    original = capture_stream_storage(doc, xref)
    plan = _prepare_plan_for_case(doc, page, engine.registry)

    def raising_verify(*args, **kwargs):
        raise RuntimeError("injected verifier crash")

    monkeypatch.setattr(engine_module, "verify_tier0_commit", raising_verify)

    with pytest.raises(RuntimeError, match="injected verifier crash"):
        engine.commit(plan)

    assert capture_stream_storage(doc, xref) == original
    doc.close()


# --------------------------------------------------- 3. undo/redo replay


@pytest.mark.parametrize("case", TIER0_CASES)
def test_undo_restores_exact_pre_commit_storage(case, tmp_path):
    pdf_path = tmp_path / f"case_{case}.pdf"
    write_case_pdf(case, pdf_path)
    model = _open_model(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        content_xref = model.doc[0].get_contents()[0]
        pre_commit_storage = capture_stream_storage(model.doc, content_xref)

        cmd = _make_command(model, TARGET, REPLACEMENT)
        model.command_manager.execute(cmd)
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

        assert model.command_manager.undo() is True

        assert capture_stream_storage(model.doc, content_xref) == pre_commit_storage
    finally:
        model.close()


@pytest.mark.parametrize("case", TIER0_CASES)
def test_redo_restores_exact_post_commit_storage(case, tmp_path):
    pdf_path = tmp_path / f"case_{case}.pdf"
    write_case_pdf(case, pdf_path)
    model = _open_model(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        content_xref = model.doc[0].get_contents()[0]
        cmd = _make_command(model, TARGET, REPLACEMENT)
        model.command_manager.execute(cmd)
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        post_commit_storage = capture_stream_storage(model.doc, content_xref)

        assert model.command_manager.undo() is True
        assert model.command_manager.redo() is True

        assert capture_stream_storage(model.doc, content_xref) == post_commit_storage
    finally:
        model.close()


# -------------------------------------------------- 4. corruption negative


def test_restore_stream_storage_corruption_negative_falls_back_with_one_warning(
    monkeypatch, caplog
):
    """``update_object`` neutered -> the self-check mismatch fallback fires:
    decoded bytes still restore exactly, ``restore_stream_storage`` returns
    ``False``, nothing raises, and exactly one WARNING is logged."""
    doc = open_case("b")
    xref = doc[0].get_contents()[0]
    storage = capture_stream_storage(doc, xref)
    # Drift the live stream away from the captured storage so a restore is
    # actually attempted (not the short-circuit no-op).
    doc.update_stream(xref, storage.decoded + b" drift", compress=True)
    assert doc.xref_stream(xref) != storage.decoded

    def noop_update_object(self, *args, **kwargs):
        return None

    monkeypatch.setattr(fitz.Document, "update_object", noop_update_object)

    with caplog.at_level(logging.WARNING, logger="model.text_commit.inspect"):
        result = restore_stream_storage(doc, storage)

    assert result is False
    assert doc.xref_stream(xref) == storage.decoded  # decoded bytes still exact
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, [r.message for r in caplog.records]
    doc.close()


# ------------------------------------------------------ 5. save + reopen


def test_save_reopen_preserves_exact_restore_case_c(tmp_path):
    doc = open_case("c")
    page = doc[0]
    xref = page.get_contents()[0]
    original = capture_stream_storage(doc, xref)

    patchset = _full_stream_patchset(doc, page)
    applied = apply_patchset(doc, page, patchset)
    assert applied.revert(doc) is True

    path = tmp_path / "case_c_reverted.pdf"
    doc.save(str(path), garbage=0)
    doc.close()

    reopened = fitz.open(str(path))
    reopened_xref = reopened[0].get_contents()[0]
    assert reopened.xref_stream_raw(reopened_xref) == original.raw
    assert reopened.xref_object(reopened_xref) == original.obj
    assert reopened.xref_stream(reopened_xref) == original.decoded
    reopened.close()


# -------------------------------------------------------- 6. premise pins


def test_premise_update_stream_compress_true_adds_flate_to_57kb_uncompressed_stream():
    """A PyMuPDF-bump canary: if this ever stops adding /FlateDecode, the
    exact-restore short-circuit (raw/obj comparison) is still correct, but
    the DESIGN RATIONALE (why exact restore matters -- compress=True keeps
    whichever of flate/raw is smaller, no size threshold) needs review."""
    doc = fitz.open()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    big = b"q Q " * 14250  # 57,000 bytes, well over MuPDF's flate-skip floor
    assert len(big) >= 57_000
    doc.update_stream(xref, big, compress=False)
    assert "/Filter" not in doc.xref_object(xref)
    doc.update_stream(xref, big, compress=True)
    assert "/FlateDecode" in doc.xref_object(xref)
    doc.close()


def test_premise_update_object_then_update_stream_loses_the_dict():
    """PITFALLS "Restore stream bytes before restoring the stream
    dictionary": a canary for the load-bearing write order in
    restore_stream_storage (stream first, object second -- never
    reversed)."""
    doc = fitz.open()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    original = zlib.compress(b"BT ET")
    doc.update_stream(xref, original, compress=False)
    doc.update_object(xref, f"<< /Length {len(original)} /Filter /FlateDecode >>")
    assert "/Filter" in doc.xref_object(xref)
    # A stream write AFTER the object restore silently rewrites the dict.
    doc.update_stream(xref, b"BT ET", compress=False)
    assert "/Filter" not in doc.xref_object(xref)
    doc.close()


def test_capture_tier0_reversal_post_storage_capture_never_raises(tmp_path, monkeypatch):
    """A successful commit must stay successful even if the post-commit
    storage capture itself blows up (e.g. a doc swapped out from under a
    mocked/minimal model). Unlike the sibling pre-commit capture in
    execute() (which has always been best-effort), the post-commit capture
    in _capture_tier0_reversal used to have no guard at all -- a raise
    there would escape a SUCCESSFUL execute() and turn a committed edit
    into an exception. This pins the fix: degrade to no post-commit
    storage tracked, never propagate."""
    import model.edit_commands as edit_commands_module

    pdf_path = tmp_path / "case_a.pdf"
    write_case_pdf("a", pdf_path)
    model = _open_model(pdf_path, TextCommitSettings(engine="tiered"))
    try:
        cmd = _make_command(model, TARGET, REPLACEMENT)

        # Case "a" has exactly one content stream, so the pre-commit
        # capture loop in execute() makes exactly one real call -- let
        # THAT one through (so pre_fingerprint/pre_page still get set and
        # _capture_tier0_reversal actually runs), then blow up on every
        # call after it, which is where the post-commit capture this test
        # targets happens.
        call_count = 0

        def flaky_capture(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return capture_stream_storage(*args, **kwargs)
            raise RuntimeError("injected: post-commit capture blew up")

        monkeypatch.setattr(edit_commands_module, "capture_stream_storage", flaky_capture)

        # Must not raise -- the commit itself still succeeds.
        model.command_manager.execute(cmd)
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert call_count >= 2, "test setup did not reach the post-commit capture"
        assert len(cmd._pre_storage) == 1  # the one real (pre-commit) call
        assert cmd._post_storage == ()  # degraded, not raised

        # Undo/redo still function (just without exact-storage tracking on
        # the post-commit side).
        monkeypatch.setattr(
            edit_commands_module, "capture_stream_storage", capture_stream_storage
        )
        assert model.command_manager.undo() is True
        assert model.command_manager.redo() is True
    finally:
        model.close()


def test_premise_wrong_filter_silently_empties_decoded_stream_without_raising():
    """The self-check in restore_stream_storage exists BECAUSE this is
    silent: a wrong /Filter is validated nowhere in PyMuPDF -- xref_stream()
    returns b"" (MuPDF logs to stderr, never raises), so a mis-restore
    would otherwise save cleanly as an empty page."""
    doc = fitz.open()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    raw = b"this is not valid flate-compressed data at all"
    doc.update_stream(xref, raw, compress=False)
    doc.update_object(xref, f"<< /Length {len(raw)} /Filter /FlateDecode >>")
    assert doc.xref_stream_raw(xref) == raw
    decoded = doc.xref_stream(xref)
    assert decoded == b""
    doc.close()
