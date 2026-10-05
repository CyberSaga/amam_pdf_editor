"""Apply by token (UI critique step 5; fixes critique defect B2).

The preview <-> commit identity contract: the inline Apply commits the SAME
``PreparedEdit`` the user saw verified, or nothing.

* A cache hit is re-bound on the LIVE page before it is committed: the page
  xref, the page fingerprint, the stream xref and the show's
  ``op_start``/``op_end``/``string_start``/``string_end`` range must all
  equal the cached candidate's (``seq`` is only an ordinal).  A mismatch
  refuses ``PREVIEW_STALE`` with zero mutation -- never a legacy fallback.
* A cache miss re-prepares and commits only when the new token equals the
  request's ``plan_token``; any other outcome is ``PREVIEW_STALE``.
* ``EditTextRequest.requires_preview_token`` (set only by the inline Apply)
  without a token refuses ``PREVIEW_PENDING``.  ``allow_rebuild=True`` and
  tokenless internal callers (cross-page delete, same-page drag, redo) are
  not gated.
* The controller toasts both codes (never ``show_error``); the View keeps
  Apply disabled while the editor has no current-generation token.

Every fixture is synthetic (plan section 10 data policy).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.edit_requests import EditTextRequest  # noqa: E402
from model.geometry import unrotated_to_visual_rect  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import derive_tier0_preview_target  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, TextCommitSettings  # noqa: E402
from model.text_commit.plan import PreparedEdit  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from model.text_commit.replay import replay_page_streams  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    append_page_content,
    build_identity_h_fixture,
    encode_cids,
)

_NON_STRICT = TextCommitSettings(engine="tiered", strict=False, max_tier=1)
_REPLACEMENT = "Buffer Tnak"  # same glyphs, same advance -> Tier 0


# ---------------------------------------------------------------- helpers


def _twins(tmp_path: Path, settings: TextCommitSettings = _NON_STRICT) -> PDFModel:
    """Two identical ``Buffer Tank`` shows (72,700) and (72,600), one stream."""
    fixture = build_identity_h_fixture("Buffer Tank")
    hex_operand = encode_cids("Buffer Tank").hex().upper()
    append_page_content(
        fixture,
        f"BT /{fixture.resource_name} {fixture.fontsize:g} Tf "
        f"1 0 0 1 72 600 Tm <{hex_operand}> Tj ET",
    )
    path = tmp_path / "twins.pdf"
    fixture.doc.save(str(path))
    fixture.doc.close()
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path))
    model.set_text_target_mode("run")
    model.ensure_page_index_built(1)
    return model


def _runs(model: PDFModel) -> list:
    return list(model.block_manager.get_runs(0))


def _hit(model: PDFModel, nth: int):
    """Run-mode hit on the ``nth`` 'Tank' run (0 = the y=700 twin)."""
    runs = [r for r in _runs(model) if r.text == "Tank"]
    assert len(runs) > nth, [r.text for r in _runs(model)]
    page = model.doc[0]
    rect = unrotated_to_visual_rect(page, fitz.Rect(runs[nth].bbox))
    hit = model.get_text_info_at_point(
        1, fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)
    )
    assert hit is not None and hit.source_ref is not None
    assert hit.target_text == "Buffer Tank"
    return hit


def _shows(model: PDFModel):
    page = model.doc[0]
    return replay_page_streams(
        [(x, model.doc.xref_stream(x)) for x in page.get_contents()]
    ).shows


def _content_bytes(model: PDFModel) -> list[bytes]:
    page = model.doc[0]
    return [model.doc.xref_stream(x) for x in page.get_contents()]


def _preview_token(model: PDFModel, hit, replacement: str = _REPLACEMENT) -> PreparedEdit:
    """The production preview path: derive the target from the hit's ref,
    prepare on the session snapshot, cache the verified candidate exactly as
    ``PDFController._consume_plan_preview`` does."""
    target = derive_tier0_preview_target(
        model,
        page_num=1,
        rect=hit.target_bbox,
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
        source_ref=hit.source_ref,
    )
    assert target is not None and target.source_kind == "source_show"
    session = open_preview_session(model.doc, 0, "apply-by-token", max_tier=1)
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    try:
        result = renderer.render(
            PlanPreviewRequest(
                session_key="apply-by-token",
                generation=1,
                target_text=target.text,
                replacement_text=target.replacement_for(replacement),
                expected_origin=target.origin,
                target_bbox=target.bbox,
                clip_rect=target.bbox,
                render_scale=1.0,
            )
        )
    finally:
        renderer.close()
    assert result.plan_token is not None, result.reject_reason
    assert isinstance(result.prepared, PreparedEdit)
    model.cache_verified_candidate(result.plan_token, result.prepared)
    return result.prepared


def _edit(model: PDFModel, hit, new_text: str = _REPLACEMENT, **extra) -> EditTextResult:
    return model.edit_text(
        page_num=1,
        rect=hit.target_bbox,
        new_text=new_text,
        font=hit.font,
        size=hit.size,
        color=hit.color,
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
        source_ref=hit.source_ref,
        **extra,
    )


class _Spies:
    """Record (and pass through) every mutation-capable entry point."""

    def __init__(self, model: PDFModel, monkeypatch) -> None:
        self.prepare: list[int] = []
        self.commit: list[int] = []
        self.legacy: list[int] = []
        engine = model.get_tiered_commit_engine()
        real_prepare = engine.prepare
        real_commit = engine.commit

        def _prepare(*a, **k):
            self.prepare.append(1)
            return real_prepare(*a, **k)

        def _commit(*a, **k):
            self.commit.append(1)
            return real_commit(*a, **k)

        monkeypatch.setattr(engine, "prepare", _prepare)
        monkeypatch.setattr(engine, "commit", _commit)

        def _legacy(*a, **k):
            self.legacy.append(1)
            raise AssertionError("legacy redact+reinsert engine reached")

        monkeypatch.setattr(model, "_apply_redact_insert", _legacy)


def _assert_lossless(model: PDFModel) -> None:
    outcome = model.last_commit_outcome
    assert outcome is not None and outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier in (
        CommitTier.TIER0_LOSSLESS_STREAM_PATCH,
        CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE,
    ), outcome
    assert tuple(outcome.fallback_chain or ()) == (), outcome.fallback_chain


# ------------------------------------------------ cache hit: identity re-bind


def test_twin_token_never_commits_the_other_twin(tmp_path: Path, monkeypatch) -> None:
    """The token was verified for twin A (y=700); the request targets twin B
    (y=600) with B's own, valid ``source_ref`` and the SAME replacement, so
    the cached candidate passes the text/replacement check.  Before the
    re-bind, the cache hit committed A's candidate: the user edited B and A
    changed."""
    model = _twins(tmp_path)
    try:
        hit_a, hit_b = _hit(model, 0), _hit(model, 1)
        assert hit_a.source_ref != hit_b.source_ref
        prepared_a = _preview_token(model, hit_a)
        assert prepared_a.binding.show.op_start == hit_a.source_ref.op_start
        before = _content_bytes(model)
        xref_count = model.doc.xref_length()
        spies = _Spies(model, monkeypatch)

        result = _edit(model, hit_b, plan_token=prepared_a.token)

        assert [s.decoded_bytes for s in _shows(model)] == [
            encode_cids("Buffer Tank"),
            encode_cids("Buffer Tank"),
        ], "a token for twin A must never rewrite either twin on B's request"
        assert _content_bytes(model) == before
        assert model.doc.xref_length() == xref_count
        assert result is EditTextResult.PREVIEW_STALE
        assert spies.commit == [] and spies.prepare == [] and spies.legacy == []
        outcome = model.last_commit_outcome
        assert outcome is not None and outcome.status is CommitStatus.REJECTED
        assert "legacy" not in tuple(outcome.fallback_chain or ())
    finally:
        model.close()


def test_twin_positive_control_own_token_commits(tmp_path: Path, monkeypatch) -> None:
    """Guard (passes before and after): A's token on A's request commits A,
    straight from the cache (no re-prepare)."""
    model = _twins(tmp_path)
    try:
        hit_a = _hit(model, 0)
        prepared_a = _preview_token(model, hit_a)
        spies = _Spies(model, monkeypatch)

        result = _edit(model, hit_a, plan_token=prepared_a.token)

        assert result is EditTextResult.SUCCESS
        _assert_lossless(model)
        assert spies.prepare == [] and spies.legacy == []
        assert [s.decoded_bytes for s in _shows(model)] == [
            encode_cids(_REPLACEMENT),
            encode_cids("Buffer Tank"),
        ]
    finally:
        model.close()


def test_tier1_cached_candidate_rebinds_and_commits(tmp_path: Path, monkeypatch) -> None:
    """A Tier 1 candidate splices the whole operator (``op_start..op_end``),
    not just the string operand; the re-bind must accept that range (found
    by the real-corpus umbrella: hvac p4/show26 and ecc show60)."""
    model = _twins(tmp_path)
    try:
        hit_a = _hit(model, 0)
        prepared_a = _preview_token(model, hit_a, "Buffer Tanks")
        assert prepared_a.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
        spies = _Spies(model, monkeypatch)

        result = _edit(model, hit_a, "Buffer Tanks", plan_token=prepared_a.token)

        assert result is EditTextResult.SUCCESS, model.last_commit_outcome
        assert spies.prepare == [] and spies.legacy == []
        assert model.last_commit_outcome.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    finally:
        model.close()


# --------------------------------------------- stale after a document change


def _commit_twin_b_first(model: PDFModel) -> None:
    """A tokenless internal edit of twin B changes page 1 (fingerprint)."""
    hit_b = _hit(model, 1)
    assert _edit(model, hit_b, "Buffer Tnka") is EditTextResult.SUCCESS
    _assert_lossless(model)


@pytest.mark.parametrize("cache", ["hit", "cleared"])
def test_token_after_a_document_change_refuses_without_mutation(
    tmp_path: Path, monkeypatch, cache: str
) -> None:
    """The token was verified before another edit rewrote the page.  A cache
    hit used to reach ``apply_patchset``'s STALE_PLAN and then fall to the
    legacy engine; a cleared cache used to re-prepare silently and commit a
    candidate the user never saw."""
    model = _twins(tmp_path)
    try:
        prepared_a = _preview_token(model, _hit(model, 0))
        _commit_twin_b_first(model)
        if cache == "cleared":
            model.clear_verified_candidates()
        hit_a = _hit(model, 0)  # a fresh, valid ref on the changed page
        before = _content_bytes(model)
        xref_count = model.doc.xref_length()
        spies = _Spies(model, monkeypatch)

        result = _edit(model, hit_a, plan_token=prepared_a.token)

        assert _content_bytes(model) == before, "a stale token must not mutate"
        assert model.doc.xref_length() == xref_count
        assert result is EditTextResult.PREVIEW_STALE
        assert spies.legacy == []
        assert spies.commit == [], "nothing may be committed for a stale token"
        assert [s.decoded_bytes for s in _shows(model)] == [
            encode_cids("Buffer Tank"),
            encode_cids("Buffer Tnka"),
        ]
    finally:
        model.close()


def test_cleared_cache_with_matching_token_commits(tmp_path: Path, monkeypatch) -> None:
    """Guard (passes before the change via the silent re-prepare; after it,
    via the token-equality check): a cache miss whose re-prepared token
    equals the request's commits exactly that candidate."""
    model = _twins(tmp_path)
    try:
        hit_a = _hit(model, 0)
        prepared_a = _preview_token(model, hit_a)
        model.clear_verified_candidates()
        spies = _Spies(model, monkeypatch)

        result = _edit(model, hit_a, plan_token=prepared_a.token)

        assert result is EditTextResult.SUCCESS
        _assert_lossless(model)
        assert spies.prepare == [1] and spies.legacy == []
        assert [s.decoded_bytes for s in _shows(model)] == [
            encode_cids(_REPLACEMENT),
            encode_cids("Buffer Tank"),
        ]
    finally:
        model.close()


def test_cache_miss_with_a_different_replacement_is_stale(tmp_path: Path, monkeypatch) -> None:
    """The token was verified for 'Buffer Tnak'; the request now says
    'Buffer Tnka' (a keystroke the preview never verified).  The re-prepare
    succeeds with a different token -- it must not be committed."""
    model = _twins(tmp_path)
    try:
        hit_a = _hit(model, 0)
        prepared_a = _preview_token(model, hit_a)
        before = _content_bytes(model)
        spies = _Spies(model, monkeypatch)

        result = _edit(model, hit_a, "Buffer Tnka", plan_token=prepared_a.token)

        assert _content_bytes(model) == before
        assert result is EditTextResult.PREVIEW_STALE
        assert spies.commit == [] and spies.legacy == []
    finally:
        model.close()


# ------------------------------------------------------ pending (no token)


def test_request_fields_default_off() -> None:
    request = EditTextRequest(
        page=1, rect=fitz.Rect(0, 0, 1, 1), new_text="x", font="helv", size=12.0,
        color=(0.0, 0.0, 0.0),
    )
    assert request.requires_preview_token is False
    assert request.allow_rebuild is False


def test_required_token_missing_refuses_pending(tmp_path: Path, monkeypatch) -> None:
    model = _twins(tmp_path)
    try:
        hit_a = _hit(model, 0)
        before = _content_bytes(model)
        spies = _Spies(model, monkeypatch)

        result = _edit(model, hit_a, requires_preview_token=True)

        assert result is EditTextResult.PREVIEW_PENDING
        assert _content_bytes(model) == before
        assert spies.prepare == [] and spies.commit == [] and spies.legacy == []
    finally:
        model.close()


def test_allow_rebuild_is_not_gated_by_the_token_requirement(tmp_path: Path) -> None:
    model = _twins(tmp_path)
    try:
        result = _edit(
            model, _hit(model, 0), requires_preview_token=True, allow_rebuild=True
        )
        assert result is EditTextResult.SUCCESS
        _assert_lossless(model)
    finally:
        model.close()


def test_tokenless_internal_caller_is_not_gated(tmp_path: Path) -> None:
    """Guard: a caller that does not require a token (cross-page delete,
    same-page drag, redo) keeps committing without one."""
    model = _twins(tmp_path)
    try:
        assert _edit(model, _hit(model, 0)) is EditTextResult.SUCCESS
        _assert_lossless(model)
    finally:
        model.close()


def test_redo_replays_without_the_token_gate() -> None:
    """Redo re-runs ``model.edit_text`` for a command with no retained forward
    patch; it replays a decision already made, so it must not carry the
    first execute's token requirement (or its now-stale token)."""
    calls: list[dict] = []

    class _Model:
        fidelity_protected_pages: set = set()
        doc = None
        last_commit_outcome = None

        def edit_text(self, *args, **kwargs):
            calls.append(kwargs)
            return EditTextResult.SUCCESS

    cmd = EditTextCommand(
        model=_Model(),
        page_num=1,
        rect=fitz.Rect(0, 0, 10, 10),
        new_text="x",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text="y",
        vertical_shift_left=True,
        page_snapshot_bytes=b"",
        old_block_id=None,
        old_block_text=None,
        plan_token="tok-1",
        requires_preview_token=True,
    )
    assert cmd.execute() is True
    assert calls[0]["plan_token"] == "tok-1"
    assert calls[0]["requires_preview_token"] is True
    assert cmd.execute() is True  # redo of a non-patch command
    assert calls[1]["plan_token"] is None
    assert calls[1]["requires_preview_token"] is False
    assert cmd.plan_token == "tok-1"


# -------------------------------------------------- controller: toast route


@pytest.mark.parametrize(
    "code", ["PREVIEW_PENDING", "PREVIEW_STALE"]
)
def test_preview_codes_toast_and_never_show_error(monkeypatch, code: str) -> None:
    from controller import pdf_controller
    from controller.pdf_controller import PDFController

    result = getattr(EditTextResult, code)
    message = PDFController._edit_result_to_message(None, result)
    assert message and "文件未變更" in message

    errors: list = []
    monkeypatch.setattr(pdf_controller, "show_error", lambda *a, **k: errors.append(a))
    toasts: list = []
    controller = PDFController.__new__(PDFController)
    controller.view = SimpleNamespace(
        _show_toast=lambda msg, duration_ms=0, tone="": toasts.append((msg, tone))
    )
    controller._show_edit_result_feedback(result)
    assert toasts == [(message, "warning")]
    assert errors == []

    # A view without a toast surface logs; it never escalates to a modal.
    controller.view = SimpleNamespace()
    controller._show_edit_result_feedback(result)
    assert errors == []


# ------------------------------------------------ View: Apply needs a token


def _pump(ms: int = 200) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def _wait_for(predicate, timeout_ms: int = 15000) -> bool:
    end = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < end:
        if predicate():
            return True
        _pump(40)
    return predicate()


@pytest.fixture
def gui(qapp, tmp_path: Path, monkeypatch, request):
    from controller.pdf_controller import PDFController
    from view.pdf_view import PDFView

    preview = getattr(request, "param", "plan")
    fixture = build_identity_h_fixture("Buffer Tank")
    path = tmp_path / "gui.pdf"
    fixture.doc.save(str(path))
    fixture.doc.close()
    modal_calls: list[str] = []
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information",
        staticmethod(lambda *a, **k: modal_calls.append("information")),
    )
    monkeypatch.setattr(
        "controller.pdf_controller.show_error",
        lambda *a, **k: modal_calls.append("show_error"),
    )
    model = PDFModel(
        text_commit_settings=TextCommitSettings(
            engine="tiered", strict=True, max_tier=1, preview=preview
        )
    )
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    monkeypatch.setattr(
        controller,
        "_confirm_legacy_fallback",
        lambda *a, **k: modal_calls.append("fallback") or False,
    )
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
        yield model, view, controller, modal_calls
    finally:
        try:
            controller._end_text_edit_plan_preview_session()
        except Exception:
            pass
        model.close()
        view.close()
        _pump(60)


def _open_editor(model: PDFModel, view):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    # Critique step 12: "run" is now the combo's shipped default, so the
    # fixture's setCurrentIndex no longer fires a mode change that built the
    # index as a side effect; the helper reads run geometry before the click.
    model.ensure_page_index_built(1)
    run = [r for r in _runs(model) if r.text == "Tank"][0]
    page = model.doc[0]
    visual = unrotated_to_visual_rect(page, fitz.Rect(run.bbox))
    rs = view._render_scale if view._render_scale > 0 else 1.0
    centre = QPointF(
        view._page_scene_x(0) + (visual.x0 + visual.x1) / 2.0 * rs,
        view._page_scene_y(0) + (visual.y0 + visual.y1) / 2.0 * rs,
    )
    view.graphics_view.centerOn(centre)
    _pump(60)
    click_pos = view.graphics_view.mapFromScene(centre)
    QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump(260)
    assert view.text_editor is not None, "click must open the editor"
    editor = view.text_editor.widget()
    assert editor.toPlainText() == "Buffer Tank"
    return editor


def test_apply_waits_for_a_current_token_and_carries_it(gui) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    model, view, _controller, modal_calls = gui
    requests: list = []
    view.sig_edit_text.connect(requests.append)
    editor = _open_editor(model, view)

    editor.setPlainText("Buffer Tnak")
    assert editor.current_plan_token() is None
    assert view.text_apply_btn.isEnabled() is False, (
        "Apply must stay disabled until the typed text has a verified preview"
    )
    assert view.text_cancel_btn.isEnabled() is True
    assert _wait_for(lambda: editor.current_plan_token() is not None)
    _pump(40)
    assert view.text_apply_btn.isEnabled() is True

    # A new keystroke invalidates the token -> Apply disabled again, and a
    # programmatic Apply keeps the editor (click-away decision) and sends nothing.
    editor.setPlainText("Buffer Tnka")
    assert view.text_apply_btn.isEnabled() is False
    view._on_text_apply_clicked()
    _pump(80)
    assert view.text_editor is not None and requests == []

    assert _wait_for(lambda: editor.current_plan_token() is not None)
    token = editor.current_plan_token()
    _pump(40)
    assert view.text_apply_btn.isEnabled() is True
    QTest.mouseClick(
        view.text_apply_btn, Qt.LeftButton, Qt.NoModifier, view.text_apply_btn.rect().center()
    )
    _pump(300)

    assert len(requests) == 1
    assert requests[0].requires_preview_token is True
    assert requests[0].plan_token == token
    assert requests[0].allow_rebuild is False
    assert [s.decoded_bytes for s in _shows(model)] == [encode_cids("Buffer Tnka")]
    _assert_lossless(model)
    assert modal_calls == []


def test_clicking_the_disabled_apply_keeps_the_editor(gui) -> None:
    """A press on the disabled Apply is delivered to the first ClickFocus
    ancestor; that used to be ``rightPanel`` -- outside the edit context --
    so the focus-out finalize committed the unverified text tokenless and
    closed the editor.  The click must leave editor, input and PDF alone."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    model, view, _controller, modal_calls = gui
    requests: list = []
    view.sig_edit_text.connect(requests.append)
    editor = _open_editor(model, view)
    editor.setPlainText("Buffer Tnak")
    assert view.text_apply_btn.isEnabled() is False

    QTest.mouseClick(
        view.text_apply_btn, Qt.LeftButton, Qt.NoModifier, view.text_apply_btn.rect().center()
    )
    _pump(300)

    assert requests == [], [(r.requires_preview_token, r.plan_token) for r in requests]
    assert view.text_editor is not None and view.text_editor.widget() is editor
    assert editor.toPlainText() == "Buffer Tnak"
    assert [s.decoded_bytes for s in _shows(model)] == [encode_cids("Buffer Tank")]
    assert modal_calls == []


@pytest.mark.parametrize("gui", ["legacy"], indirect=True)
def test_legacy_preview_mode_keeps_apply_enabled(gui) -> None:
    """Guard: without plan preview no token can ever arrive, so Apply stays
    usable and the request does not require one."""
    model, view, _controller, _modal_calls = gui
    requests: list = []
    view.sig_edit_text.connect(requests.append)
    editor = _open_editor(model, view)
    editor.setPlainText("Buffer Tnak")
    _pump(60)
    assert view.text_apply_btn.isEnabled() is True
    view._on_text_apply_clicked()
    _pump(200)
    assert len(requests) == 1 and requests[0].requires_preview_token is False


@pytest.mark.parametrize("change", ["size", "font"])
def test_style_change_rejects_an_in_flight_result_so_apply_stays_disabled(
    gui, change: str
) -> None:
    """UI critique step 6.  A verified preview result for the current text is
    still in flight when the user changes the font or size.  It must not set
    the token afterwards: the restyle has no verified preview, so Apply stays
    disabled and nothing is committed."""
    from PySide6.QtGui import QImage

    model, view, _controller, modal_calls = gui
    requests: list = []
    view.sig_edit_text.connect(requests.append)
    editor = _open_editor(model, view)
    editor.setPlainText("Buffer Tnak")
    assert _wait_for(lambda: editor.current_plan_token() is not None)
    in_flight_generation = editor._plan_generation
    in_flight_token = editor.current_plan_token()

    if change == "size":
        view.text_size.setCurrentText("13")
    else:
        view.text_font.setCurrentIndex(view.text_font.findData("tiro"))
    assert editor._plan_generation > in_flight_generation

    # The old result arrives now, before the restyle's own request returns.
    raster = QImage(4, 4, QImage.Format_RGBA8888)
    raster.fill(0xFF00FF00)
    assert editor.apply_plan_preview(in_flight_generation, raster, in_flight_token) is False
    assert editor.current_plan_token() is None
    assert view.text_apply_btn.isEnabled() is False

    view._on_text_apply_clicked()
    _pump(150)
    assert requests == []
    assert view.text_editor is not None and view.text_editor.widget() is editor
    assert [s.decoded_bytes for s in _shows(model)] == [encode_cids("Buffer Tank")]
    assert modal_calls == []
