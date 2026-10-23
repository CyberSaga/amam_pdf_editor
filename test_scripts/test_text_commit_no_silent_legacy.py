"""No silent legacy (UI critique step 7; owner decision 2026-09-30).

The tiered engine's refusal is FINAL unless the request carries the explicit
rebuild consent (``EditTextRequest.allow_rebuild``, set only by the future
"改用重建文字…" action):

* tiered refusal and ``allow_rebuild`` False -> ``EditTextResult.REJECTED``
  with the real reason code and zero mutation -- never legacy, whether or
  not ``strict`` is set (strict keeps ``REJECTED_STRICT``);
* ``allow_rebuild`` True but no confirm callback -> ``FALLBACK_DECLINED``
  (a missing callback is not consent), zero mutation;
* ``allow_rebuild`` True with a callback -> the existing confirm (default
  No), then legacy.

The same consent covers same-page drag, cross-page move (the source
deletion AND the destination ``add_textbox``, critique B3), emptying the
text, font/size changes and paragraph-mode edits.  The Controller passes the
confirm callback only when ``allow_rebuild`` is set; the old
``TextCommitSettings.confirm_degrade`` opt-in is retired.

Every fixture is synthetic (plan section 10 data policy).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.edit_requests import (  # noqa: E402
    EditTextRequest,
    MoveTextRequest,
    StyleOverrides,
)
from model.geometry import unrotated_to_visual_rect  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from test_scripts.qt_teardown import dispose_pdf_view  # noqa: E402

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica -> Tier 0 commits
MISSING_GLYPH = "Price 路"  # not encodable in WinAnsi Helvetica
DOWNSTREAM = "Downstream line stays"
MOVE_TOKEN = "PriceToken"  # one token -> exactly one span (move tests)

SHIPPED = TextCommitSettings()


# ---------------------------------------------------------------- fixtures


def _add_raw_page(doc: fitz.Document, stream: bytes) -> fitz.Page:
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
    return (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )


def _tj_array_stream() -> bytes:
    """Multi-item array ``TJ``: structurally refused by Tier 0."""
    head, tail = TARGET[:5], TARGET[5:]
    return (
        b"BT /F1 12 Tf 72 700 Td [(" + head.encode() + b") (" + tail.encode()
        + b")] TJ ET"
    )


def _write_pdf(path: Path, *streams: bytes) -> Path:
    doc = fitz.open()
    for stream in streams:
        _add_raw_page(doc, stream)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _open_model(path: Path, settings: TextCommitSettings = SHIPPED) -> PDFModel:
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _block(model: PDFModel, probe: str, page_num: int = 1):
    model.ensure_page_index_built(page_num)
    return next(
        b
        for b in model.block_manager.get_blocks(page_num - 1)
        if probe in (b.text or "")
    )


class _State:
    """Everything a zero-mutation claim covers, for every page."""

    def __init__(self, model: PDFModel) -> None:
        doc = model.doc
        self.fingerprints = [page_fingerprint(doc, doc[i]) for i in range(len(doc))]
        self.streams = [
            [doc.xref_stream(x) for x in doc[i].get_contents()] for i in range(len(doc))
        ]
        self.edit_count = model.edit_count
        self.undo_count = model.command_manager.undo_count
        self.protected = set(model.fidelity_protected_pages)

    def assert_unchanged(self, model: PDFModel) -> None:
        after = _State(model)
        assert after.fingerprints == self.fingerprints
        assert after.streams == self.streams
        assert after.edit_count == self.edit_count
        assert after.undo_count == self.undo_count
        assert after.protected == self.protected


class _NoLegacy:
    def __init__(self, model: PDFModel, monkeypatch) -> None:
        self.calls: list[int] = []

        def _legacy(*a, **k):
            self.calls.append(1)
            raise AssertionError("legacy redact+reinsert engine reached")

        monkeypatch.setattr(model, "_apply_redact_insert", _legacy)


def _model_edit(model: PDFModel, new_text: str, **extra) -> EditTextResult:
    block = _block(model, TARGET)
    return model.edit_text(
        1,
        fitz.Rect(block.layout_rect),
        new_text,
        "helv",
        12.0,
        (0.0, 0.0, 0.0),
        original_text=block.text,
        **extra,
    )


def _assert_rejected(model: PDFModel, reason: str) -> None:
    outcome = model.last_commit_outcome
    assert outcome is not None
    assert outcome.status is CommitStatus.REJECTED, outcome
    assert outcome.degraded_reason == reason, outcome
    assert "legacy" not in outcome.fallback_chain, outcome.fallback_chain
    assert outcome.fallback_chain == (f"tier0:{reason}",)


# ---------------------------------------------------------------- model level


def test_shipped_defaults_are_non_strict() -> None:
    """Guard (true before and after): the red tests below run under the
    SHIPPED defaults, where ``strict`` is False."""
    assert SHIPPED.engine == "tiered"
    assert SHIPPED.strict is False


def test_missing_glyph_under_shipped_defaults_refuses_with_zero_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    model = _open_model(_write_pdf(tmp_path / "glyph.pdf", _tier0_stream()))
    try:
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        result = _model_edit(model, MISSING_GLYPH)
        assert result is EditTextResult.REJECTED
        assert legacy.calls == []
        _assert_rejected(model, RejectReason.ENCODING_FAILED)
        state.assert_unchanged(model)
    finally:
        model.close()


def test_structural_refusal_without_rebuild_never_reaches_legacy(
    tmp_path: Path, monkeypatch
) -> None:
    model = _open_model(_write_pdf(tmp_path / "tj.pdf", _tj_array_stream()))
    try:
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        consent: list[tuple[str, ...]] = []
        # A callback WITHOUT allow_rebuild is not consent either.
        result = _model_edit(
            model, REPLACEMENT, confirm_fallback=lambda c: consent.append(c) or True
        )
        assert result is EditTextResult.REJECTED
        assert legacy.calls == [] and consent == []
        outcome = model.last_commit_outcome
        assert outcome is not None and outcome.status is CommitStatus.REJECTED
        assert outcome.degraded_reason and outcome.degraded_reason != "legacy"
        state.assert_unchanged(model)
    finally:
        model.close()


def test_unknown_settings_fail_closed_like_the_cross_page_gate(
    tmp_path: Path, monkeypatch
) -> None:
    """RED before (part-3 VERIFY defect 7): with ``text_commit_settings``
    None, ``edit_text`` skipped the tiered branch and rebuilt through legacy
    without consent (fail-open), while the cross-page gate treats unknown
    settings as gated (fail-closed).  Unknown settings now mean the shipped
    tiered defaults: the refusal is final without the explicit consent."""
    model = _open_model(_write_pdf(tmp_path / "none.pdf", _tier0_stream()))
    try:
        model.text_commit_settings = None
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        result = _model_edit(model, MISSING_GLYPH)
        assert result is EditTextResult.REJECTED
        assert legacy.calls == []
        _assert_rejected(model, RejectReason.ENCODING_FAILED)
        state.assert_unchanged(model)
    finally:
        model.close()


def test_allow_rebuild_without_a_callback_is_declined(tmp_path: Path, monkeypatch) -> None:
    model = _open_model(_write_pdf(tmp_path / "nocb.pdf", _tj_array_stream()))
    try:
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        result = _model_edit(model, REPLACEMENT, allow_rebuild=True)
        assert result is EditTextResult.FALLBACK_DECLINED
        assert legacy.calls == []
        state.assert_unchanged(model)
    finally:
        model.close()


def test_allow_rebuild_with_a_declining_callback_is_declined(
    tmp_path: Path, monkeypatch
) -> None:
    """Guard for the confirm leg (the pre-existing decline path)."""
    model = _open_model(_write_pdf(tmp_path / "decline.pdf", _tj_array_stream()))
    try:
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        asked: list[tuple[str, ...]] = []
        result = _model_edit(
            model,
            REPLACEMENT,
            allow_rebuild=True,
            confirm_fallback=lambda c: asked.append(c) or False,
        )
        assert result is EditTextResult.FALLBACK_DECLINED
        assert len(asked) == 1 and asked[0][-1] == "legacy"
        assert legacy.calls == []
        state.assert_unchanged(model)
    finally:
        model.close()


def test_allow_rebuild_with_consent_rebuilds_through_legacy(tmp_path: Path) -> None:
    """Guard (true before and after): consent still rebuilds."""
    model = _open_model(_write_pdf(tmp_path / "accept.pdf", _tj_array_stream()))
    try:
        asked: list[tuple[str, ...]] = []
        result = _model_edit(
            model,
            REPLACEMENT,
            allow_rebuild=True,
            confirm_fallback=lambda c: asked.append(c) or True,
        )
        assert result is EditTextResult.SUCCESS
        assert len(asked) == 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert outcome.fallback_chain == asked[0]
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_strict_still_rejects_strict_even_with_rebuild_consent(
    tmp_path: Path, monkeypatch
) -> None:
    """Guard (true before and after): strict forbids the legacy engine
    outright, consent or not."""
    model = _open_model(
        _write_pdf(tmp_path / "strict.pdf", _tj_array_stream()),
        TextCommitSettings(engine="tiered", strict=True),
    )
    try:
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        asked: list[tuple[str, ...]] = []
        result = _model_edit(
            model,
            REPLACEMENT,
            allow_rebuild=True,
            confirm_fallback=lambda c: asked.append(c) or True,
        )
        assert result is EditTextResult.REJECTED_STRICT
        assert asked == [] and legacy.calls == []
        state.assert_unchanged(model)
    finally:
        model.close()


@pytest.mark.parametrize(
    ("label", "new_text", "extra", "reason"),
    [
        ("empty", "", {}, RejectReason.EMPTY_REPLACEMENT),
        (
            "font_size",
            REPLACEMENT,
            {"style_overrides": StyleOverrides(font_size=14.0)},
            RejectReason.STYLE_OVERRIDE_PRESENT,
        ),
        (
            "drag",
            REPLACEMENT,
            {"new_rect": fitz.Rect(200, 300, 300, 320)},
            RejectReason.GEOMETRY_OVERRIDE_PRESENT,
        ),
    ],
)
def test_rebuild_only_operations_refuse_without_consent(
    tmp_path: Path, monkeypatch, label, new_text, extra, reason
) -> None:
    """Owner decision 2026-09-30: emptying the text, font/size changes and
    drags are rebuild-only; the drag or the restyle by itself is NOT
    consent."""
    model = _open_model(_write_pdf(tmp_path / f"{label}.pdf", _tier0_stream()))
    try:
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        result = _model_edit(model, new_text, **extra)
        assert result is EditTextResult.REJECTED
        assert legacy.calls == []
        _assert_rejected(model, reason)
        state.assert_unchanged(model)
    finally:
        model.close()


@pytest.mark.parametrize(
    ("label", "extra", "reason"),
    [
        (
            "font_only",
            {"style_overrides": StyleOverrides(font_family="cour")},
            RejectReason.STYLE_OVERRIDE_PRESENT,
        ),
        (
            "size_only",
            {"style_overrides": StyleOverrides(font_size=14.0)},
            RejectReason.STYLE_OVERRIDE_PRESENT,
        ),
        (
            "drag_only",
            {"new_rect": fitz.Rect(200, 300, 300, 320)},
            RejectReason.GEOMETRY_OVERRIDE_PRESENT,
        ),
    ],
)
def test_override_only_refusal_reports_the_override_not_no_change(
    tmp_path: Path, monkeypatch, label, extra, reason
) -> None:
    """The text is unchanged but the user restyled or dragged: the real
    reason is the override.  (The plan gate checks ``no_change`` first; its
    order is pinned, so ``edit_text`` must report the override.)"""
    model = _open_model(_write_pdf(tmp_path / f"{label}.pdf", _tier0_stream()))
    try:
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        result = _model_edit(model, TARGET, **extra)
        assert result is EditTextResult.REJECTED
        assert legacy.calls == []
        _assert_rejected(model, reason)
        state.assert_unchanged(model)
    finally:
        model.close()


def test_unchanged_edit_is_no_change_not_a_refusal(app) -> None:
    """Same text, no override: nothing to do -- ``NO_CHANGE``, zero
    mutation, and no refusal notice (it is not a rejection)."""
    model, view, controller, rec = app
    state = _State(model)
    view.sig_edit_text.emit(_request(model, 2, new_text=TARGET))
    assert controller.consume_last_edit_result() is EditTextResult.NO_CHANGE
    state.assert_unchanged(model)
    assert rec["toast"] == [] and rec["show_error"] == [] and rec["confirm"] == []


def test_paragraph_mode_edit_refuses_without_consent(tmp_path: Path, monkeypatch) -> None:
    """A paragraph target spans several shows: rebuild-only."""
    two_line = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
        b"0 -14 Td (Second line here) Tj ET"
    )
    model = _open_model(_write_pdf(tmp_path / "para.pdf", two_line))
    try:
        model.set_text_target_mode("paragraph")
        state = _State(model)
        legacy = _NoLegacy(model, monkeypatch)
        block = _block(model, TARGET)
        result = model.edit_text(
            1,
            fitz.Rect(block.layout_rect),
            (block.text or "").replace("2024", "2025"),
            "helv",
            12.0,
            (0.0, 0.0, 0.0),
            original_text=block.text,
            target_mode="paragraph",
        )
        assert "Second line here" in (block.text or "")
        assert result is EditTextResult.REJECTED
        assert legacy.calls == []
        _assert_rejected(model, RejectReason.MULTI_SPAN_TARGET)
        state.assert_unchanged(model)
    finally:
        model.close()


def test_redo_of_a_consented_rebuild_replays_without_reprompting(tmp_path: Path) -> None:
    """Guard (true before; the replay path must keep it true after the
    no-callback rule): a consented rebuild's redo replays the decision already made (no
    second prompt, never ``FALLBACK_DECLINED``)."""
    model = _open_model(_write_pdf(tmp_path / "redo.pdf", _tj_array_stream()))
    try:
        block = _block(model, TARGET)
        asked: list[tuple[str, ...]] = []
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
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=block.text,
            confirm_fallback=lambda c: asked.append(c) or True,
            allow_rebuild=True,
        )
        model.command_manager.execute(cmd)
        assert cmd.result is EditTextResult.SUCCESS and len(asked) == 1
        assert model.command_manager.undo() is True
        assert TARGET in model.doc[0].get_text()
        assert model.command_manager.redo() is True
        assert cmd.result is EditTextResult.SUCCESS
        assert len(asked) == 1
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_confirm_degrade_setting_is_retired() -> None:
    assert not hasattr(SHIPPED, "confirm_degrade")
    parsed = TextCommitSettings.from_env({"TEXT_COMMIT_CONFIRM_DEGRADE": "1"})
    assert not hasattr(parsed, "confirm_degrade")


def test_headless_confirm_defaults_to_no() -> None:
    """With no View to ask, the consent is NOT given (the confirm's default
    is No) -- a missing prompt surface is not consent."""
    from controller.pdf_controller import PDFController

    controller = PDFController.__new__(PDFController)
    controller.view = None
    assert controller._confirm_legacy_fallback(("tier0:advance_mismatch", "legacy")) is False


def test_move_request_carries_allow_rebuild_default_off() -> None:
    request = MoveTextRequest(
        source_page=1,
        source_rect=fitz.Rect(0, 0, 1, 1),
        destination_page=2,
        destination_rect=fitz.Rect(0, 0, 1, 1),
        new_text="x",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
    )
    assert request.allow_rebuild is False


# ---------------------------------------------------------------- controller


@pytest.fixture
def app(qapp, tmp_path: Path, monkeypatch, request):
    """Model + View + Controller over a three-page synthetic document.  Modals
    are recorded and return a safe default (never a real dialog).  Indirect
    param: the ``TextCommitSettings`` (default: shipped)."""
    from controller.pdf_controller import PDFController
    from view.pdf_view import PDFView

    settings = getattr(request, "param", SHIPPED)
    path = _write_pdf(
        tmp_path / "ctl.pdf",
        _tj_array_stream(),
        _tier0_stream(),
        b"BT /F1 12 Tf 72 650 Td (" + MOVE_TOKEN.encode() + b") Tj ET",
    )
    model = PDFModel(text_commit_settings=settings)
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    monkeypatch.setattr(controller, "show_page", lambda _page: None)
    monkeypatch.setattr(
        controller, "_invalidate_active_render_state", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)
    monkeypatch.setattr(view, "capture_viewport_anchor", lambda: None)
    rec: dict[str, list] = {
        "show_error": [],
        "confirm": [],
        "toast": [],
        "degrade": [],
        "add_textbox": [],
        "doc_snapshot": [],
        "replace_doc": [],
        "model_edit": [],
    }
    monkeypatch.setattr(
        "controller.pdf_controller.show_error", lambda *a, **k: rec["show_error"].append(a)
    )
    monkeypatch.setattr(
        controller, "_confirm_legacy_fallback", lambda chain: rec["confirm"].append(chain) or False
    )
    monkeypatch.setattr(
        view, "_show_toast", lambda msg, **k: rec["toast"].append((msg, k)), raising=False
    )
    monkeypatch.setattr(
        controller, "_notify_degraded_commit", lambda o: rec["degrade"].append(o)
    )
    monkeypatch.setattr(
        controller, "_notify_legacy_baseline_degrade", lambda o: rec["degrade"].append(o)
    )

    def _spy(name: str, target, attr: str) -> None:
        real = getattr(target, attr)

        def _wrapped(*a, **k):
            rec[name].append((a, k))
            return real(*a, **k)

        monkeypatch.setattr(target, attr, _wrapped)

    _spy("add_textbox", model, "add_textbox")
    _spy("doc_snapshot", model, "_capture_doc_snapshot")
    _spy("replace_doc", model, "replace_active_document_from_snapshot")
    _spy("model_edit", model, "edit_text")
    try:
        yield model, view, controller, rec
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def _request(model: PDFModel, page_num: int, **extra) -> EditTextRequest:
    block = _block(model, TARGET, page_num)
    return EditTextRequest(
        page=page_num,
        rect=fitz.Rect(block.layout_rect),
        new_text=extra.pop("new_text", REPLACEMENT),
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        **extra,
    )


def _move(model: PDFModel, source_page: int, destination_page: int, **extra) -> MoveTextRequest:
    """Move the single-token ``MOVE_TOKEN`` span (page 3 of the ``app``
    document).  A single token lands in exactly one span, so its id is
    supplied directly -- as in test_text_commit_degrade_visibility, which
    documents the pre-existing gap in the ambiguous-candidate ranking of
    ``_resolve_cross_page_move_source_span_id``."""
    model.ensure_page_index_built(source_page)
    span = next(
        s
        for s in model.block_manager.get_spans(source_page - 1)
        if MOVE_TOKEN in (s.text or "")
    )
    return MoveTextRequest(
        source_page=source_page,
        source_rect=fitz.Rect(span.bbox),
        destination_page=destination_page,
        destination_rect=fitz.Rect(100, 400, 260, 420),
        new_text=MOVE_TOKEN,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=span.text,
        target_span_id=span.span_id,
        **extra,
    )


def test_tokenless_commit_without_rebuild_is_refused_with_a_notice(app) -> None:
    """The verify report's blank-canvas click-away: a tokenless request that
    Tier 0 refuses used to commit through legacy DEGRADED."""
    model, view, controller, rec = app
    state = _State(model)
    view.sig_edit_text.emit(_request(model, 1))
    assert controller.consume_last_edit_result() is EditTextResult.REJECTED
    state.assert_unchanged(model)
    assert rec["confirm"] == [] and rec["degrade"] == []
    assert rec["show_error"] == []
    assert len(rec["toast"]) == 1
    message, kwargs = rec["toast"][0]
    assert "文件未變更" in message
    # UI step 10 (deliberate change): the notice says the reason in plain
    # text from the shared mapping, not the bare code.
    from view.text_edit_reasons import rejection_reason_text

    assert rejection_reason_text(model.last_commit_outcome.degraded_reason) in message
    assert kwargs.get("tone") == "warning"


def test_controller_asks_only_for_an_explicit_rebuild(app) -> None:
    model, view, controller, rec = app
    state = _State(model)
    view.sig_edit_text.emit(_request(model, 1, allow_rebuild=True))
    assert len(rec["confirm"]) == 1 and rec["confirm"][0][-1] == "legacy"
    assert controller.consume_last_edit_result() is EditTextResult.FALLBACK_DECLINED
    state.assert_unchanged(model)
    assert rec["show_error"] == []


def test_drag_without_consent_is_refused(app) -> None:
    model, view, controller, rec = app
    state = _State(model)
    view.sig_edit_text.emit(_request(model, 2, new_rect=fitz.Rect(200, 300, 330, 320)))
    assert controller.consume_last_edit_result() is EditTextResult.REJECTED
    assert model.last_commit_outcome.degraded_reason == RejectReason.GEOMETRY_OVERRIDE_PRESENT
    state.assert_unchanged(model)
    assert rec["confirm"] == [] and rec["show_error"] == []


def test_same_page_move_request_without_consent_is_refused(app) -> None:
    model, _view, controller, rec = app
    state = _State(model)
    controller.move_text_across_pages(_move(model, 3, 3))
    assert controller.consume_last_edit_result() is EditTextResult.REJECTED
    assert model.last_commit_outcome.degraded_reason == RejectReason.GEOMETRY_OVERRIDE_PRESENT
    state.assert_unchanged(model)
    assert rec["confirm"] == [] and rec["show_error"] == []


def test_same_page_move_request_forwards_rebuild_consent(app) -> None:
    model, _view, controller, rec = app
    state = _State(model)
    controller.move_text_across_pages(_move(model, 3, 3, allow_rebuild=True))
    assert len(rec["confirm"]) == 1
    assert controller.consume_last_edit_result() is EditTextResult.FALLBACK_DECLINED
    state.assert_unchanged(model)


def _check_move_without_consent_touches_nothing(app) -> None:
    model, _view, controller, rec = app
    state = _State(model)
    controller.move_text_across_pages(_move(model, 3, 1))
    assert controller.consume_last_edit_result() is EditTextResult.REJECTED
    state.assert_unchanged(model)
    for key in ("model_edit", "add_textbox", "doc_snapshot", "replace_doc", "confirm", "show_error"):
        assert rec[key] == [], (key, rec[key])
    assert len(rec["toast"]) == 1 and "文件未變更" in rec["toast"][0][0]


def _check_move_decline_is_asked_once_before_any_deletion(app) -> None:
    model, _view, controller, rec = app
    state = _State(model)
    controller.move_text_across_pages(_move(model, 3, 1, allow_rebuild=True))
    assert len(rec["confirm"]) == 1
    assert controller.consume_last_edit_result() is EditTextResult.FALLBACK_DECLINED
    state.assert_unchanged(model)
    for key in ("model_edit", "add_textbox", "doc_snapshot", "replace_doc", "show_error"):
        assert rec[key] == [], (key, rec[key])


def _check_move_with_consent_asks_once_and_moves(app, monkeypatch) -> None:
    model, _view, controller, rec = app
    monkeypatch.setattr(
        controller, "_confirm_legacy_fallback", lambda chain: rec["confirm"].append(chain) or True
    )
    undo_before = model.command_manager.undo_count
    controller.move_text_across_pages(_move(model, 3, 1, allow_rebuild=True))
    assert rec["show_error"] == []
    assert controller.consume_last_edit_result() is EditTextResult.SUCCESS
    assert len(rec["confirm"]) == 1, rec["confirm"]
    assert len(rec["add_textbox"]) == 1
    assert MOVE_TOKEN not in model.doc[2].get_text()
    assert MOVE_TOKEN in model.doc[0].get_text()
    assert model.command_manager.undo_count == undo_before + 1


def test_cross_page_move_without_consent_touches_nothing(app) -> None:
    _check_move_without_consent_touches_nothing(app)


def test_cross_page_move_decline_is_asked_once_before_any_deletion(app) -> None:
    _check_move_decline_is_asked_once_before_any_deletion(app)


def test_cross_page_move_with_consent_asks_once_and_moves(app, monkeypatch) -> None:
    _check_move_with_consent_asks_once_and_moves(app, monkeypatch)


_LEGACY = [TextCommitSettings(engine="legacy")]


@pytest.mark.parametrize("app", _LEGACY, indirect=True)
def test_legacy_engine_cross_page_move_without_consent_touches_nothing(app) -> None:
    """Part 5 / A4 (owner decision Q2): the single legacy exemption of the
    cross-page consent gate is gone -- ``engine="legacy"`` needs the same
    explicit consent as every other engine.  Before: the legacy engine moved
    the text without asking."""
    _check_move_without_consent_touches_nothing(app)


@pytest.mark.parametrize("app", _LEGACY, indirect=True)
def test_legacy_engine_cross_page_move_declined_consent_makes_zero_model_calls(app) -> None:
    _check_move_decline_is_asked_once_before_any_deletion(app)


@pytest.mark.parametrize("app", _LEGACY, indirect=True)
def test_legacy_engine_cross_page_move_with_consent_asks_once_and_moves(
    app, monkeypatch
) -> None:
    _check_move_with_consent_asks_once_and_moves(app, monkeypatch)


# ---------------------------------------------------------------- real view


def _pump(ms: int = 200) -> None:
    from PySide6.QtWidgets import QApplication

    qt_app = QApplication.instance()
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.01)


def test_blank_canvas_click_away_never_reaches_legacy(qapp, tmp_path: Path, monkeypatch) -> None:
    """Real View: type text the font cannot show, click blank canvas (the
    tokenless CLICK_AWAY finalize).  The PDF must stay byte-identical and the
    legacy engine must never run."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    from controller.pdf_controller import PDFController
    from test_scripts.type0_fixture_builder import build_identity_h_fixture
    from view.pdf_view import PDFView

    fixture = build_identity_h_fixture("Buffer Tank", subset=True)
    path = tmp_path / "canvas.pdf"
    fixture.doc.save(str(path))
    fixture.doc.close()
    modal: list[str] = []
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information",
        staticmethod(lambda *a, **k: modal.append("information")),
    )
    monkeypatch.setattr(
        "controller.pdf_controller.show_error", lambda *a, **k: modal.append("show_error")
    )
    model = PDFModel(
        text_commit_settings=TextCommitSettings(
            engine="tiered", strict=False, max_tier=1, preview="plan"
        )
    )
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    monkeypatch.setattr(
        controller, "_confirm_legacy_fallback", lambda *a, **k: modal.append("fallback") or False
    )
    legacy = _NoLegacy(model, monkeypatch)
    requests: list = []
    try:
        view.resize(1200, 900)
        view.show()
        _pump(120)
        controller.open_pdf(str(path))
        _pump(400)
        view.set_mode("edit_text")
        combo = view.text_target_mode_combo
        combo.setCurrentIndex(combo.findData("run"))
        _pump(60)
        view.sig_edit_text.connect(requests.append)
        state = _State(model)

        # Critique step 12: "run" is the combo's shipped default now, so no
        # mode change builds the index before this pre-click lookup.
        model.ensure_page_index_built(1)
        run = [r for r in model.block_manager.get_runs(0) if r.text == "Tank"][0]
        page = model.doc[0]
        visual = unrotated_to_visual_rect(page, fitz.Rect(run.bbox))
        rs = view._render_scale if view._render_scale > 0 else 1.0
        centre = QPointF(
            view._page_scene_x(0) + (visual.x0 + visual.x1) / 2.0 * rs,
            view._page_scene_y(0) + (visual.y0 + visual.y1) / 2.0 * rs,
        )
        view.graphics_view.centerOn(centre)
        _pump(60)
        QTest.mouseClick(
            view.graphics_view.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            view.graphics_view.mapFromScene(centre),
        )
        _pump(260)
        assert view.text_editor is not None, "click must open the editor"
        editor = view.text_editor.widget()
        editor.setPlainText("Buffer 路")
        _pump(400)
        assert editor.current_plan_token() is None

        blank = QPointF(
            view._page_scene_x(0) + (page.rect.width - 40.0) * rs,
            view._page_scene_y(0) + (page.rect.height - 40.0) * rs,
        )
        QTest.mouseClick(
            view.graphics_view.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            view.graphics_view.mapFromScene(blank),
        )
        _pump(400)

        # UI step 9 (owner decision 2026-09-30): a click-away with no
        # verified preview sends NOTHING and keeps the editor and its input
        # (S7 pinned the model-side REJECTED of the tokenless request it used
        # to send; the tokenless-request refusal itself stays pinned by
        # ``test_tokenless_commit_without_rebuild_is_refused_with_a_notice`` above).
        assert requests == [], [(r.new_text, r.plan_token) for r in requests]
        assert view.text_editor is not None and view.text_editor.widget() is editor
        assert editor.toPlainText() == "Buffer 路"
        assert legacy.calls == []
        state.assert_unchanged(model)
        assert "fallback" not in modal and "show_error" not in modal
    finally:
        dispose_pdf_view(view, controller, model)


# ------------------------------------------- F10-UNI-2: block-level no-change gate


def _view_shape_edit(model: PDFModel, probe: str, new_text: str) -> EditTextResult:
    """The view's request shape: the block's own PyMuPDF font name and size."""
    block = _block(model, probe)
    return model.edit_text(
        1,
        fitz.Rect(block.layout_rect),
        new_text,
        block.font or "helv",
        float(block.size),
        tuple(block.color or (0.0, 0.0, 0.0)),
        original_text=block.text,
    )


@pytest.mark.parametrize(
    ("label", "replacement"),
    [
        ("case_only", "PRICE 2024"),
        ("double_space", "Price  2024"),
        ("trailing_space", "Price 2024 "),
        ("space_removed", "Price2024"),
    ],
)
def test_visible_or_textual_edit_the_engine_commits_is_never_dropped_as_no_change(
    tmp_path: Path, label: str, replacement: str
) -> None:
    """RED before (F10-UNI-2): the block-level gate compared
    ``normalize_text`` (lowercase, ALL whitespace stripped) of both sides and
    returned ``NO_CHANGE`` before the tiered branch ran, so the plan preview
    verified the edit and Apply silently did nothing.  Only an equal text
    (modulo extraction ligatures) is a no-op."""
    model = _open_model(_write_pdf(tmp_path / f"{label}.pdf", _tier0_stream()))
    try:
        result = _view_shape_edit(model, TARGET, replacement)
        assert result is not EditTextResult.NO_CHANGE
        assert result is EditTextResult.SUCCESS
        out = tmp_path / f"{label}_saved.pdf"
        model.save_as(str(out))
    finally:
        model.close()
    saved = fitz.open(str(out))
    try:
        assert replacement.strip() in saved[0].get_text()
    finally:
        saved.close()


def test_curly_quote_and_zero_width_edits_are_not_silently_dropped(tmp_path: Path) -> None:
    """Curly quotes and a zero-width space are different characters: the
    request is either committed or REFUSED with a real reason, never a
    silent ``NO_CHANGE``."""
    def _stream(text: bytes) -> bytes:
        return b"BT /F1 12 Tf 72 700 Td (" + text + b") Tj ET"

    quote = _write_pdf(tmp_path / "quote.pdf", _stream(b"it's fine"))
    model = _open_model(quote)
    try:
        result = _view_shape_edit(model, "fine", "it\u2019s fine")
        assert result is not EditTextResult.NO_CHANGE
    finally:
        model.close()
    zwsp = _write_pdf(tmp_path / "zwsp.pdf", _stream(TARGET.encode()))
    model = _open_model(zwsp)
    try:
        result = _view_shape_edit(model, TARGET, "Price\u200b2024")
        assert result is not EditTextResult.NO_CHANGE
    finally:
        model.close()


def test_identical_text_is_still_no_change_with_the_view_request_shape(
    tmp_path: Path,
) -> None:
    model = _open_model(_write_pdf(tmp_path / "same.pdf", _tier0_stream()))
    try:
        state = _State(model)
        assert _view_shape_edit(model, TARGET, TARGET) is EditTextResult.NO_CHANGE
        state.assert_unchanged(model)
    finally:
        model.close()


def test_unchanged_text_comparison_only_forgives_extraction_artifacts() -> None:
    from model.text_normalization import is_unchanged_text

    assert is_unchanged_text("Price 2024", "Price 2024")
    assert is_unchanged_text("of\ufb01ce", "office")  # ligature extraction
    assert is_unchanged_text("a\ufffdb", "ab")  # replacement-char extraction
    assert is_unchanged_text("", "")
    for requested in (
        "PRICE 2024",
        "Price  2024",
        "Price 2024 ",
        "Price2024",
        "Price\u200b2024",
        "Price 2025",
    ):
        assert not is_unchanged_text("Price 2024", requested), requested
    assert not is_unchanged_text("it's", "it\u2019s")
