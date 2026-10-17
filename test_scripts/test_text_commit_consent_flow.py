"""Red-light tests for Task 12 P0-C Phase 2 -- pre-commit consent for a
legacy-fidelity fallback.

Phase 1 (``test_text_commit_degrade_visibility.py``) made a
DEGRADED_COMMITTED outcome visible after the fact. Phase 2 pauses BEFORE the
legacy mutation happens: a real tiered->legacy fallback must get explicit
per-edit user consent, and a decline must leave the document, undo stack,
and edit_count byte-for-byte untouched.

Architecture (plan §8 has the full pivot record): a Qt-free callback
(``confirm_fallback: Callable[[tuple[str, ...]], bool] | None``) injected
into ``model.edit_text()``, invoked synchronously at the exact point
today's code already falls through to the legacy engine. A two-pass
Controller-side preflight was considered and rejected: it cannot see a
commit-stage-only failure (prepare succeeds on the scratch copy, live
verification then fails) in time to pause before it, because that
information does not exist until ``engine.commit()`` actually runs, and
running it during a preflight is unsafe on the success branch (double-edit
corruption).

Only ``engine="tiered"``, non-strict, cross-page-move, and the module-level
"redo must not re-prompt" tests need a real, unpatched confirm call site;
every test here supplies its own ``_confirm_legacy_fallback`` stand-in
(never a real Qt modal), so nothing hangs offscreen.

UI step 7 (owner decision 2026-09-30, "no silent legacy") moved the gate
from the retired ``TextCommitSettings.confirm_degrade`` opt-in onto the
REQUEST: only ``EditTextRequest.allow_rebuild`` / ``MoveTextRequest.
allow_rebuild`` (the explicit "改用重建文字…" consent) reaches the confirm
callback; without it a tiered refusal is final (``EditTextResult.REJECTED``,
pinned in ``test_text_commit_no_silent_legacy.py``). Every request in this
file therefore sets ``allow_rebuild=True`` explicitly -- including the
"never requests consent" cases and the ``engine="legacy"`` one, where an
unarmed gate would make the assertion pass vacuously.

All fixtures are synthetic (data policy, plan §10).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import controller.pdf_controller as controller_module  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from model.edit_commands import EditTextCommand  # noqa: E402
from model.edit_requests import (  # noqa: E402
    EditTextRequest,
    MoveTextRequest,
    RebuildConsent,
    UnkeepableGlyph,
)
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica (Tier 0 fixture pair)
DOWNSTREAM = "Downstream line stays"

# Privacy sentinels (user-frozen): none of these may reach the confirm
# payload, its rendered message, or any INFO+ log record.
SENTINEL_TARGET = "SECRET_TARGET_TEXT"
SENTINEL_REPLACEMENT = "SECRET_REPLACEMENT_TEXT"
SENTINEL_BASENAME = "SECRET-customer-project"


# ---------------------------------------------------------------- fixtures


def _add_raw_page(doc: fitz.Document, stream: bytes) -> fitz.Page:
    """Append a page whose content stream is exactly ``stream`` (xref surgery)."""
    page = doc.new_page(width=595, height=842)
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


def _tier0_stream() -> bytes:
    """Single-literal-``Tj`` page: commits losslessly at Tier 0."""
    return (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )


def _tj_array_stream(target: str) -> bytes:
    """Array-``TJ`` page: structurally ineligible for Tier 0, so a non-strict
    tiered edit falls back to the legacy engine (needs consent, Phase 2).

    The ineligible shape is a MULTI-item array (T16-4X S1 admitted the
    single-item one, which this helper used to emit -- every test here then
    committed at Tier 0 and never reached the fallback it exists to test).
    The target's bytes, the page and the geometry are unchanged: the items
    concatenate to exactly ``target``.
    """
    head, tail = target[: len(target) // 2], target[len(target) // 2 :]
    return (
        b"BT /F1 12 Tf 72 700 Td [("
        + head.encode()
        + b") ("
        + tail.encode()
        + b")] TJ ET"
    )


def _write_pdf(path: Path, stream: bytes) -> Path:
    doc = fitz.open()
    _add_raw_page(doc, stream)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


class _ConfirmSpy:
    """Records every fallback-consent call and answers configurably.

    ``probe``, when set, runs at call time before the answer is returned --
    lets a test assert on document/model state AT THE MOMENT OF THE ASK,
    proving the callback fires before any mutation.
    """

    def __init__(self, answer: bool = True) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.answer = answer
        self.probe = None

    def __call__(self, chain: tuple[str, ...]) -> bool:
        self.calls.append(chain)
        if self.probe is not None:
            self.probe(chain)
        return self.answer


def _launch(
    path: Path, settings: TextCommitSettings, monkeypatch: pytest.MonkeyPatch
) -> tuple[PDFModel, PDFView, PDFController]:
    model = PDFModel(text_commit_settings=settings)
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    # Keep the harness light: rendering and tooltip refresh are not under test.
    monkeypatch.setattr(controller, "show_page", lambda _page: None)
    monkeypatch.setattr(
        controller,
        "_invalidate_active_render_state",
        lambda *args, **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)
    monkeypatch.setattr(view, "capture_viewport_anchor", lambda: None)
    return model, view, controller


def _teardown(model: PDFModel, view: PDFView, qapp) -> None:
    model.close()
    view.close()
    qapp.processEvents()


def _edit_via_signal(
    model: PDFModel,
    view: PDFView,
    probe: str,
    new_text: str,
    page_num: int = 1,
    *,
    allow_rebuild: bool = True,
) -> None:
    """Drive the edit through the production wiring: the View's
    ``sig_edit_text`` signal into ``PDFController.edit_text``.  Every
    request here carries the explicit rebuild consent (UI step 7) so the
    confirm gate is armed."""
    page_idx = page_num - 1
    model.ensure_page_index_built(page_num)
    block = next(
        b for b in model.block_manager.get_blocks(page_idx) if probe in (b.text or "")
    )
    request = EditTextRequest(
        page=page_num,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        allow_rebuild=allow_rebuild,
    )
    view.sig_edit_text.emit(request)


# ---------------------------------------------------------------- tests


def test_real_tier_fallback_pauses_before_legacy_mutation(
    qapp, tmp_path, monkeypatch
):
    """RED: the confirm callback must fire BEFORE any legacy mutation -- the
    document, edit_count and last_commit_outcome are still exactly as they
    were pre-edit at the moment the callback is invoked."""
    pdf_path = _write_pdf(tmp_path / "pause.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        edit_count_before = model.edit_count

        spy = _ConfirmSpy(answer=True)

        def _probe(_chain: tuple[str, ...]) -> None:
            assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
            assert model.edit_count == edit_count_before
            assert model.last_commit_outcome is None

        spy.probe = _probe
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(spy.calls) == 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert model.edit_count == edit_count_before + 1
    finally:
        _teardown(model, view, qapp)


def test_cancelled_fallback_leaves_document_and_history_byte_unchanged(
    qapp, tmp_path, monkeypatch
):
    """RED: declining the confirm dialog must produce zero mutation -- no
    document bytes changed, no undo entry, no edit_count bump, no outcome."""
    pdf_path = _write_pdf(tmp_path / "cancel.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        edit_count_before = model.edit_count
        undo_count_before = model.command_manager.undo_count

        monkeypatch.setattr(
            controller, "_confirm_legacy_fallback", _ConfirmSpy(answer=False)
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert model.edit_count == edit_count_before
        assert model.command_manager.undo_count == undo_count_before
        assert model.command_manager.has_pending_changes() is False
        assert model.last_commit_outcome is None
    finally:
        _teardown(model, view, qapp)


def test_confirmed_fallback_commits_once_and_notifies_once(
    qapp, tmp_path, monkeypatch
):
    """RED: confirming commits the legacy fallback exactly once, records
    exactly one undo entry, and surfaces exactly one Phase 1 degrade notice
    (the two phases must compose, not double up)."""
    pdf_path = _write_pdf(tmp_path / "confirm.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        degrade_notices: list[str] = []
        monkeypatch.setattr(
            view,
            "notify_degraded_commit",
            lambda message: degrade_notices.append(str(message)),
            raising=False,
        )
        undo_count_before = model.command_manager.undo_count

        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(spy.calls) == 1
        assert len(degrade_notices) == 1
        assert model.command_manager.undo_count == undo_count_before + 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
    finally:
        _teardown(model, view, qapp)


def test_explicit_legacy_engine_never_requests_consent(qapp, tmp_path, monkeypatch):
    """PIN: under the kill switch (``engine="legacy"``, no longer the
    default since Task 16 T16-3) the confirm callback is never called --
    a legacy-engine edit proceeds exactly as before Phase 2 existed,
    because there is no higher-fidelity attempt to fall back FROM."""
    pdf_path = _write_pdf(tmp_path / "default.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="legacy"),
        monkeypatch,
    )
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == []
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert outcome.fallback_chain == ("legacy",)
    finally:
        _teardown(model, view, qapp)


def test_normal_high_fidelity_commit_never_requests_consent(
    qapp, tmp_path, monkeypatch
):
    """PIN: a lossless Tier 0 commit never asks for consent."""
    pdf_path = _write_pdf(tmp_path / "tier0.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == []
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.COMMITTED
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    finally:
        _teardown(model, view, qapp)


def test_strict_rejection_never_requests_consent(qapp, tmp_path, monkeypatch):
    """PIN: strict mode fails closed without ever asking -- REJECTED_STRICT,
    zero mutation, same as Phase 1."""
    pdf_path = _write_pdf(tmp_path / "strict.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered", strict=True),
        monkeypatch,
    )
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == []
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.REJECTED
    finally:
        _teardown(model, view, qapp)


def test_redo_does_not_reprompt_or_repeat_notice(qapp, tmp_path, monkeypatch):
    """RED: the user consented to THIS command's low-fidelity execution
    once; undo/redo replays that same decision, it does not ask again or
    repeat the Phase 1 degrade notice."""
    pdf_path = _write_pdf(tmp_path / "redo.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        degrade_notices: list[str] = []
        monkeypatch.setattr(
            view,
            "notify_degraded_commit",
            lambda message: degrade_notices.append(str(message)),
            raising=False,
        )
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        assert len(spy.calls) == 1
        assert len(degrade_notices) == 1

        controller.undo()
        controller.redo()

        assert len(spy.calls) == 1
        assert len(degrade_notices) == 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
    finally:
        _teardown(model, view, qapp)


def test_cross_page_move_cancel_is_atomic_on_both_pages(qapp, tmp_path, monkeypatch):
    """RED: a cross-page move always rebuilds (source deletion AND the
    destination add_textbox, UI step 7 / critique B3); its single consent is
    asked before either -- a decline must leave BOTH pages, the undo stack,
    and edit_count untouched, and must not raise into the generic error
    handler (no restore needed; nothing changed)."""
    move_target = "PriceToken"
    doc = fitz.open()
    _add_raw_page(doc, _tj_array_stream(move_target))
    _add_raw_page(doc, _tier0_stream())
    pdf_path = tmp_path / "cross_cancel.pdf"
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        import controller.pdf_controller as controller_module

        monkeypatch.setattr(
            controller_module,
            "show_error",
            lambda parent, message: (_ for _ in ()).throw(
                AssertionError(f"unexpected show_error: {message!r}")
            ),
        )
        monkeypatch.setattr(
            controller, "_confirm_legacy_fallback", _ConfirmSpy(answer=False)
        )

        model.ensure_page_index_built(1)
        source_span = next(
            s
            for s in model.block_manager.get_spans(0)
            if move_target in (s.text or "")
        )

        fp_source_before = page_fingerprint(model.doc, model.doc[0])
        fp_dest_before = page_fingerprint(model.doc, model.doc[1])
        undo_count_before = model.command_manager.undo_count
        edit_count_before = model.edit_count

        request = MoveTextRequest(
            source_page=1,
            source_rect=fitz.Rect(source_span.bbox),
            destination_page=2,
            destination_rect=fitz.Rect(72, 500, 300, 540),
            new_text=move_target,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=source_span.text,
            target_span_id=source_span.span_id,
            allow_rebuild=True,
        )
        view.sig_move_text_across_pages.emit(request)

        assert page_fingerprint(model.doc, model.doc[0]) == fp_source_before
        assert page_fingerprint(model.doc, model.doc[1]) == fp_dest_before
        assert model.command_manager.undo_count == undo_count_before
        assert model.edit_count == edit_count_before
    finally:
        _teardown(model, view, qapp)


def test_consent_payload_contains_codes_only_no_text_filename_or_path(
    qapp, tmp_path, monkeypatch, caplog
):
    """RED: the chain handed to the confirm callback, and the message built
    from it, must carry reason codes only -- no document text, replacement
    text, filename, or path -- and neither may the surrounding INFO+ logs."""
    pdf_path = _write_pdf(
        tmp_path / f"{SENTINEL_BASENAME}.pdf", _tj_array_stream(SENTINEL_TARGET)
    )
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        with caplog.at_level(logging.INFO):
            _edit_via_signal(model, view, SENTINEL_TARGET, SENTINEL_REPLACEMENT)

        assert len(spy.calls) == 1
        chain = spy.calls[0]
        message = controller._fallback_confirmation_message(chain)

        sentinels = (
            SENTINEL_TARGET,
            SENTINEL_REPLACEMENT,
            SENTINEL_BASENAME,
            str(pdf_path),
        )
        chain_text = " ".join(chain)
        for sentinel in sentinels:
            assert sentinel not in chain_text, (
                f"sentinel {sentinel!r} leaked into consent chain {chain!r}"
            )
            assert sentinel not in message, (
                f"sentinel {sentinel!r} leaked into confirm message {message!r}"
            )
        for record in caplog.records:
            record_message = record.getMessage()
            for sentinel in sentinels:
                assert sentinel not in record_message, (
                    f"sentinel {sentinel!r} leaked into log record from "
                    f"{record.name}: {record_message!r}"
                )
    finally:
        _teardown(model, view, qapp)


def test_commit_stage_fallback_confirmation_uses_coded_chain_only(
    qapp, tmp_path, monkeypatch, caplog
):
    """RED: a COMMIT-stage failure (prepare succeeds on the scratch copy,
    live verification then fails) is exactly the case a Controller-side
    preflight cannot see -- it must still reach the confirm callback, with
    the stable reason code only, never the free-form ``detail`` string."""
    pdf_path = _write_pdf(tmp_path / "commit_fail.pdf", _tier0_stream())
    model, view, controller = _launch(
        pdf_path,
        TextCommitSettings(engine="tiered"),
        monkeypatch,
    )
    try:
        import model.text_commit.engine as engine_module
        from model.text_commit.verify import VerificationFailure

        detail_sentinel = "document no longer opens: SECRET_MUPDF_DETAIL"
        real_verify = engine_module.verify_tier0_commit

        def _fail_live_only(doc, page, prepared, pre_state, **kwargs):
            # prepare() proves the candidate on a SCRATCH copy with the same
            # verify function -- let that succeed so the failure genuinely
            # happens at the live COMMIT stage.
            if doc is model.doc:
                return VerificationFailure(
                    reason=RejectReason.VERIFICATION_FAILED,
                    detail=detail_sentinel,
                )
            return real_verify(doc, page, prepared, pre_state, **kwargs)

        monkeypatch.setattr(engine_module, "verify_tier0_commit", _fail_live_only)

        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        with caplog.at_level(logging.INFO):
            _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(spy.calls) == 1
        chain = spy.calls[0]
        assert chain == (f"tier0:{RejectReason.VERIFICATION_FAILED}", "legacy")
        assert "SECRET_MUPDF_DETAIL" not in " ".join(chain)
        # The engine's own diagnostic warning is allowed to keep the
        # free-form detail (Phase 1 precedent) -- only controller-level
        # (confirm-chain-facing) logs must be reason-codes-only.
        for record in caplog.records:
            if record.name.startswith("controller."):
                assert "SECRET_MUPDF_DETAIL" not in record.getMessage()

        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
    finally:
        _teardown(model, view, qapp)


def test_real_confirm_degraded_fallback_dialog_returns_user_choice(qapp, monkeypatch):
    """RED: every other test in this file replaces
    ``controller._confirm_legacy_fallback`` before asserting -- the real,
    unmodified View-layer ``confirm_degraded_fallback`` (backed by
    ``QMessageBox.question``) never executes under test, so a mutation that
    inverts Yes/No, drops the message text, or silently no-ops would leave
    the whole suite green. This test exercises the unmodified function
    directly, with only the Qt call itself replaced (never a real modal)."""
    from PySide6.QtWidgets import QMessageBox

    from view.message_boxes import confirm_degraded_fallback

    captured: dict[str, object] = {}

    def _fake_question_yes(parent, title, text, buttons, default):
        captured["text"] = text
        captured["buttons"] = buttons
        captured["default"] = default
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fake_question_yes))
    assert confirm_degraded_fallback(None, "tier0:advance_mismatch → legacy") is True
    assert captured["text"] == "tier0:advance_mismatch → legacy"
    assert captured["default"] == QMessageBox.StandardButton.No

    def _fake_question_no(parent, title, text, buttons, default):
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fake_question_no))
    assert confirm_degraded_fallback(None, "tier0:advance_mismatch → legacy") is False


def test_high_fidelity_commit_does_not_arm_fallback_bypass_for_a_later_execute(
    tmp_path, monkeypatch
):
    """RED (adversarial verification finding, high): a command that commits
    cleanly at Tier 0 -- no fallback ever attempted, confirm_fallback never
    called -- must NOT silently disable asking on a LATER re-execution of
    the SAME command that genuinely needs a fallback. The prior flag design
    set ``_fallback_ever_confirmed = True`` on ANY successful execute(),
    conflating "this command has run once" with "the user was actually
    asked about a fallback and agreed" -- those are different things
    whenever a Tier 0/1 commit has no retained reversal patchset
    (``build_reversal_patchset`` returns ``None`` for any commit touching
    more than one content stream -- documented, not hypothetical) and a
    later redo must re-run the full pipeline from scratch against a page
    whose Tier 0 eligibility may have changed since (e.g. an out-of-band
    mutation like OCR, which bypasses command_manager entirely and so
    never clears a stale redo entry)."""
    pdf_path = _write_pdf(tmp_path / "reprompt.pdf", _tier0_stream())
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        block = next(
            b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or "")
        )
        snapshot = model._capture_page_snapshot(0)

        spy = _ConfirmSpy(answer=True)
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=snapshot,
            old_block_id=None,
            old_block_text=block.text,
            confirm_fallback=spy,
            allow_rebuild=True,
        )

        assert cmd.execute() is True
        assert cmd.outcome is not None
        assert cmd.outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert spy.calls == [], "a clean Tier 0 win must never ask"
        assert cmd._after_page_snapshot_bytes is None, (
            "nothing was ever asked or agreed for this command -- no rebuild "
            "replay may be recorded for it"
        )

        # Simulate the reachable "no retained patchset" redo landing on a
        # page that is no longer Tier 0-eligible for this exact edit (e.g.
        # an out-of-band mutation changed the stream shape).  Force the
        # classification to fail deterministically (the engine binds
        # ``prepare_plan`` by name at import).
        #
        # UI step 8 (deliberate policy change): this redo used to re-run the
        # whole pipeline and ASK for the fallback (the old pin: "a later
        # execute must still ask").  A Tier 0/1 command without a recorded
        # reversal now refuses redo with STALE_PLAN and zero mutation -- it
        # never re-prepares, never asks and never reaches legacy.  The
        # "never bypass the consent" property this test guards still holds:
        # nothing is committed without asking.
        assert cmd.undo() is True
        cmd._tier0_forward_patchset = None
        cmd._tier0_active = False
        import model.text_commit.engine as engine_module
        from model.text_commit.plan import PlanRejection

        monkeypatch.setattr(
            engine_module,
            "prepare_plan",
            lambda *args, **kwargs: PlanRejection(
                RejectReason.ADVANCE_MISMATCH, "forced for test"
            ),
        )
        fingerprint = page_fingerprint(model.doc, model.doc[0])

        assert cmd.execute() is False
        assert cmd.result.value == "stale_plan"
        assert model.last_commit_outcome.status is CommitStatus.STALE_PLAN
        assert spy.calls == [], "a refused redo never asks"
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint
        assert TARGET in model.doc[0].get_text()
    finally:
        model.close()


def test_redo_of_an_actually_confirmed_fallback_still_does_not_reprompt(
    tmp_path, monkeypatch
):
    """PIN: the fix above must not regress the original guarantee -- once a
    real fallback WAS asked and agreed to for this command, a later
    re-execution of the identical command (the common redo case, page
    unchanged) still does not ask again."""
    pdf_path = _write_pdf(tmp_path / "repin.pdf", _tj_array_stream(TARGET))
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        block = next(
            b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or "")
        )
        snapshot = model._capture_page_snapshot(0)

        spy = _ConfirmSpy(answer=True)
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=snapshot,
            old_block_id=None,
            old_block_text=block.text,
            confirm_fallback=spy,
            allow_rebuild=True,
        )

        assert cmd.execute() is True
        assert cmd.outcome is not None
        assert cmd.outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert len(spy.calls) == 1
        # UI step 8: the consented rebuild recorded its after-snapshot.
        assert cmd._after_page_snapshot_bytes is not None

        # No retained patchset for a legacy-tier commit.  UI step 7: a real
        # redo follows an undo.  UI step 8: that redo restores the
        # after-snapshot instead of re-running the pipeline (the old replay
        # re-ran legacy with a pre-approved callback).
        assert cmd._tier0_forward_patchset is None
        assert cmd.undo() is True
        assert cmd.execute() is True
        assert cmd.outcome is not None
        assert cmd.outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert len(spy.calls) == 1, "must not re-ask for the same confirmed decision"
    finally:
        model.close()


# ---------------------------------------------------------------------------
# F11-UNI-1 (owner decision C): the rebuild consent dialog names the
# untouched glyphs the rebuild cannot keep; consenting acknowledges exactly
# those glyphs, and only then does the model commit the rebuild.
# ---------------------------------------------------------------------------

_GLYPH_LOSS_LINE = "無法保留"


def _unkeepable_glyph_pdf(path: Path) -> Path:
    """``Price <glyph> today``: Helvetica WinAnsi whose 0x80 glyph's
    ToUnicode is U+FFFD -- a glyph with no Unicode identity."""
    tounicode = (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        b"1 beginbfchar\n<80> <FFFD>\nendbfchar\n"
        b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    )
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(
        content_xref,
        b"BT /F1 12 Tf 72 700 Td (Price \x80 today) Tj 0 -40 Td ("
        + DOWNSTREAM.encode()
        + b") Tj ET",
    )
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    tx = doc.get_new_xref()
    doc.update_object(tx, "<<>>")
    doc.update_stream(tx, tounicode)
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        f"/Encoding /WinAnsiEncoding /ToUnicode {tx} 0 R >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _capture_rebuild_dialog(monkeypatch, answer: bool) -> list[str]:
    """Replace only the View's Qt modal; the controller's real
    ``_confirm_legacy_fallback`` and message builder run."""
    messages: list[str] = []

    def _fake_confirm(_parent, message: str) -> bool:
        messages.append(message)
        return answer

    monkeypatch.setattr(controller_module, "confirm_degraded_fallback", _fake_confirm)
    return messages


def _edit_today_to_tomorrow(model: PDFModel, view: PDFView) -> None:
    """Edit the ``today`` line of the unkeepable-glyph fixture through the view's signal."""
    model.ensure_page_index_built(1)
    block = next(b for b in model.block_manager.get_blocks(0) if "today" in (b.text or ""))
    _edit_via_signal(model, view, "today", block.text.replace("today", "tomorrow"))


def test_rebuild_dialog_names_unkeepable_glyphs_and_consent_commits(
    qapp, tmp_path, monkeypatch
):
    pdf_path = _unkeepable_glyph_pdf(tmp_path / "glyph_loss.pdf")
    model, view, controller = _launch(pdf_path, TextCommitSettings(engine="tiered"), monkeypatch)
    try:
        errors: list[str] = []
        monkeypatch.setattr(
            controller_module, "show_error", lambda _p, msg: errors.append(str(msg))
        )
        messages = _capture_rebuild_dialog(monkeypatch, answer=True)
        undo_before = model.command_manager.undo_count
        _edit_today_to_tomorrow(model, view)

        assert len(messages) == 1
        assert _GLYPH_LOSS_LINE in messages[0]
        assert "1 個符號" in messages[0]
        assert "變成其他符號或消失" in messages[0]
        assert "U+FFFD" not in messages[0], "codes and code points stay out of the dialog"
        assert errors == [], errors
        page_text = model.doc[0].get_text()
        assert "tomorrow" in page_text and DOWNSTREAM in page_text
        assert model.command_manager.undo_count == undo_before + 1
    finally:
        _teardown(model, view, qapp)


def test_declining_the_glyph_loss_dialog_leaves_the_page_untouched(
    qapp, tmp_path, monkeypatch
):
    pdf_path = _unkeepable_glyph_pdf(tmp_path / "glyph_loss_no.pdf")
    model, view, controller = _launch(pdf_path, TextCommitSettings(engine="tiered"), monkeypatch)
    try:
        messages = _capture_rebuild_dialog(monkeypatch, answer=False)
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        undo_before = model.command_manager.undo_count
        _edit_today_to_tomorrow(model, view)

        assert len(messages) == 1 and _GLYPH_LOSS_LINE in messages[0]
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert model.command_manager.undo_count == undo_before
    finally:
        _teardown(model, view, qapp)


def test_rebuild_dialog_without_unkeepable_glyphs_has_no_glyph_line(
    qapp, tmp_path, monkeypatch
):
    pdf_path = _write_pdf(tmp_path / "plain.pdf", _tj_array_stream(TARGET))
    model, view, controller = _launch(pdf_path, TextCommitSettings(engine="tiered"), monkeypatch)
    try:
        messages = _capture_rebuild_dialog(monkeypatch, answer=True)
        _edit_via_signal(model, view, TARGET, REPLACEMENT)
        assert len(messages) == 1
        assert _GLYPH_LOSS_LINE not in messages[0]
    finally:
        _teardown(model, view, qapp)


def test_confirm_returns_an_acknowledgement_of_exactly_the_reported_glyphs(monkeypatch):
    """Unit pin of the consent answer: a bare True without a report, a
    ``RebuildConsent`` carrying the model's report verbatim with one, and
    a plain False on decline either way."""
    report = (
        UnkeepableGlyph(span_id=None, index=6, codepoint="U+FFFD", fate="replaced"),
        UnkeepableGlyph(span_id="p0_b0_l1_s0", index=0, codepoint="U+F0B7", fate="removed"),
    )
    controller = PDFController.__new__(PDFController)
    controller.view = object()
    controller.model = SimpleNamespace(pending_rebuild_glyph_loss=report)
    answers = iter([True, False])
    shown: list[str] = []

    def _fake_confirm(_parent, message):
        shown.append(message)
        return next(answers)

    monkeypatch.setattr(controller_module, "confirm_degraded_fallback", _fake_confirm)
    consent = controller._confirm_legacy_fallback(("tier0:advance_mismatch", "legacy"))
    assert isinstance(consent, RebuildConsent)
    assert consent.acknowledged_glyph_loss == report
    assert bool(consent) is True
    assert "2 個符號" in shown[0] and "1 個會變成其他符號" in shown[0] and "1 個會消失" in shown[0]
    assert controller._confirm_legacy_fallback(("tier0:advance_mismatch", "legacy")) is False

    controller.model = SimpleNamespace(pending_rebuild_glyph_loss=())
    monkeypatch.setattr(controller_module, "confirm_degraded_fallback", lambda _p, _m: True)
    assert controller._confirm_legacy_fallback(("tier0:advance_mismatch", "legacy")) is True
