"""No CSS/HTML interim preview in plan mode (UI critique step 11).

With ``TextCommitSettings.preview == "plan"`` the inline editor must never
paint the CSS/HTML system-font frame while the user types: that frame is
rendered from fonts the PDF does not use, so it would claim a fidelity it
cannot have.  Until the verified plan raster for the current text arrives the
editor shows the original (or the last verified) frame and a "預覽更新中" badge;
the typed text is shown in the live text strip above the box (round 7: no
in-box chip in plan mode).  Legacy preview mode is unchanged.

Every fixture is synthetic (plan section 10 data policy).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import TextCommitSettings  # noqa: E402
from view.text_editing import PreviewBackedInlineTextEditor  # noqa: E402

from test_scripts.type0_fixture_builder import build_identity_h_fixture  # noqa: E402

_W, _H = 240, 60
_BLUE = 0xFF0000FF
_GREEN = 0xFF00FF00
_RED = 0xFFFF0000


class _SpyCssRenderer:
    """Stand-in for the CSS PreviewRenderer that records every render."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def render(self, **kwargs):
        self.calls.append(kwargs)
        image = QImage(_W, _H, QImage.Format_ARGB32)
        image.fill(_RED)  # a CSS frame is recognisable by its red fill
        return image


def _solid(rgba: int) -> QImage:
    image = QImage(_W, _H, QImage.Format_ARGB32)
    image.fill(rgba)
    return image


def _editor(qapp, *, plan_mode: bool) -> tuple[PreviewBackedInlineTextEditor, _SpyCssRenderer, list]:
    spy = _SpyCssRenderer()
    editor = PreviewBackedInlineTextEditor("Buffer Tank", spy)
    editor.setFixedSize(_W, _H)
    if plan_mode:
        editor.set_plan_preview_mode(True)
    requests: list[tuple[str, int]] = []
    editor.set_plan_preview_hook(lambda text, generation: requests.append((text, generation)))
    editor.configure_render_context(
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        rect_pt=(70.0, 130.0, 200.0, 150.0),
        rotation=0,
        render_scale=1.0,
        line_height=0.0,
    )
    editor.freeze_first_frame(_solid(_BLUE))
    return editor, spy, requests


def _grab(editor: PreviewBackedInlineTextEditor) -> QImage:
    return editor.viewport().grab().toImage().convertToFormat(QImage.Format_ARGB32)


def _px(image: QImage, x: int, y: int) -> int:
    return image.pixel(x, y) & 0xFFFFFFFF


def _same(a: QImage, b: QImage) -> bool:
    return a.convertToFormat(QImage.Format_ARGB32) == b.convertToFormat(QImage.Format_ARGB32)


# ------------------------------------------------------------ editor level


def test_plan_mode_never_calls_the_css_renderer(qapp) -> None:
    editor, spy, requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()  # synchronous stand-in for the debounce
    editor.configure_render_context(font_size=14.0)  # a style change too
    editor.setPlainText("")  # emptied: used to regenerate synchronously
    assert spy.calls == [], "plan mode must not render the CSS interim frame"
    # The plan request still goes out for every regenerate.
    assert requests and requests[-1][1] == editor._plan_generation


def test_legacy_mode_still_renders_css(qapp) -> None:
    """Guard: preview='legacy' (the default editor) keeps the CSS frame."""
    editor, spy, _requests = _editor(qapp, plan_mode=False)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    assert spy.calls, "legacy mode must still render the CSS preview"
    assert editor.plan_preview_pending() is False
    assert _px(_grab(editor), _W // 2, _H // 2) == _RED


def test_pending_paints_frozen_frame_and_badge(qapp) -> None:
    editor, spy, _requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()

    assert editor.plan_preview_pending() is True
    assert editor.plan_preview_badge_text() == "預覽更新中"
    painted = _grab(editor)
    assert _px(painted, _W // 2, _H // 2) == _BLUE, "base is the frozen frame"
    assert not _same(painted, _solid(_BLUE)), "the badge is painted on top"
    assert spy.calls == []


def test_verified_raster_paints_without_badge_then_stays_as_last_frame(qapp) -> None:
    editor, _spy, requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    verified = _solid(_GREEN)
    assert editor.apply_plan_preview(requests[-1][1], verified, "tok") is True

    assert editor.plan_preview_pending() is False
    assert _same(_grab(editor), verified), "a current verified frame has no overlay"

    # The next keystroke: the verified frame stays as the base, badge returns.
    editor.setPlainText("Buffer Tnka")
    editor._regenerate_preview()
    assert editor.plan_preview_pending() is True
    painted = _grab(editor)
    assert _px(painted, _W // 2, _H // 2) == _GREEN, "last verified frame is the base"
    assert not _same(painted, verified)


def test_unchanged_text_paints_only_the_frozen_frame(qapp) -> None:
    """Type-then-delete returns to the original: no badge, pure frozen frame."""
    editor, _spy, _requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    editor.setPlainText("Buffer Tank")
    editor._regenerate_preview()
    assert editor.plan_preview_pending() is False
    assert _same(_grab(editor), _solid(_BLUE))


def test_rejection_replaces_the_updating_badge(qapp) -> None:
    """A refused preview is not 'still updating'; step 10 owns that message."""
    editor, _spy, requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    assert editor.plan_preview_pending() is True
    assert editor.set_plan_preview_state(requests[-1][1], "type0_unicode_unmapped")
    assert editor.plan_preview_pending() is False


def test_emptied_text_in_plan_mode_keeps_the_frame_not_a_blank_css_image(qapp) -> None:
    editor, spy, _requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("")
    painted = _grab(editor)
    assert spy.calls == []
    assert _px(painted, _W // 2, _H // 2) == _BLUE
    assert editor.plan_preview_pending() is True


# ------------------------------------------------------------ real UI path


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
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    preview = getattr(request, "param", "plan")
    fixture = build_identity_h_fixture("Buffer Tank")
    path = tmp_path / "gui.pdf"
    fixture.doc.save(str(path))
    fixture.doc.close()
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None)
    )
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel(
        text_commit_settings=TextCommitSettings(
            engine="tiered", strict=True, max_tier=1, preview=preview
        )
    )
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    monkeypatch.setattr(controller, "_confirm_legacy_fallback", lambda *a, **k: False)
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
        yield model, view, controller
    finally:
        try:
            controller._end_text_edit_plan_preview_session()
        except Exception:
            pass
        model.close()
        view.close()
        _pump(60)


def _open_editor(model, view):
    import fitz
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    from model.geometry import unrotated_to_visual_rect

    # Critique step 12: "run" is the combo's shipped default now, so no mode
    # change builds the index before this pre-click geometry lookup.
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
    click_pos = view.graphics_view.mapFromScene(centre)
    QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, click_pos)
    _pump(260)
    assert view.text_editor is not None, "click must open the editor"
    editor = view.text_editor.widget()
    assert editor.toPlainText() == "Buffer Tank"
    return editor


@pytest.fixture
def css_spy(monkeypatch):
    from view import text_editing

    calls: list[str] = []
    original = text_editing.PreviewRenderer.render

    def spy(self, **kwargs):
        calls.append(str(kwargs.get("text")))
        return original(self, **kwargs)

    monkeypatch.setattr(text_editing.PreviewRenderer, "render", spy)
    return calls


def test_real_editor_in_plan_mode_never_renders_css_while_typing(gui, css_spy) -> None:
    model, view, _controller = gui
    editor = _open_editor(model, view)
    assert editor.plan_preview_mode() is True

    editor.setPlainText("Buffer Tnak")
    assert editor.plan_preview_pending() is True
    assert _wait_for(lambda: editor.current_plan_token() is not None)
    editor.setPlainText("Buffer Tnka")
    editor.setPlainText("")
    _pump(400)  # let every debounce and plan result settle

    assert css_spy == [], f"CSS renderer was called in plan mode: {css_spy!r}"


@pytest.mark.parametrize("gui", ["legacy"], indirect=True)
def test_real_editor_in_legacy_mode_still_renders_css(gui, css_spy) -> None:
    """Guard: preview='legacy' keeps the CSS interim frame."""
    model, view, _controller = gui
    editor = _open_editor(model, view)
    assert editor.plan_preview_mode() is False
    editor.setPlainText("Buffer Tnak")
    _pump(400)
    assert css_spy, "legacy mode must still call the CSS renderer"
    assert editor.plan_preview_pending() is False


# ------------------------------- part 5 final review: composing paint and chip


def _send_preedit(editor, text: str) -> None:
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(editor, QInputMethodEvent(text, []))


def test_composing_in_legacy_mode_never_paints_the_frozen_original_under_deleted_text(
    qapp,
) -> None:
    """RED before: the composing branch ran before the mutated-state fail-safe
    and painted the frozen ORIGINAL frame under the chip although the original
    word had been deleted and the CSS renderer produced no frame."""
    editor, spy, _requests = _editor(qapp, plan_mode=False)
    spy.render = lambda **_kwargs: None  # the renderer failed: no CSS frame
    editor.setPlainText("")  # the original word deleted
    assert editor._preview_image is None and not editor._text_matches_initial
    _send_preedit(editor, "mo")
    painted = _grab(editor)
    assert _px(painted, _W // 2, _H // 2) != _BLUE, "the frozen original was painted"


def test_composing_in_legacy_mode_never_paints_a_rejected_preview(qapp) -> None:
    """RED before: a preview ``_mutated_preview_is_valid`` rejected (no visible
    ink) was still painted as the base under the chip."""
    editor, _spy, _requests = _editor(qapp, plan_mode=False)
    editor.setPlainText("Buffer Tnak")
    editor._preview_image = _solid(_RED)
    editor._mutated_preview_is_valid = False
    _send_preedit(editor, "mo")
    painted = _grab(editor)
    center = _px(painted, _W // 2, _H // 2)
    assert center not in (_RED, _BLUE), hex(center)


def test_composing_over_unchanged_text_paints_the_frozen_frame_in_both_modes(qapp) -> None:
    """RED before in legacy mode (the CSS frame was the base for UNCHANGED text,
    the permanent-delta the frozen-frame contract forbids); GUARD in plan mode."""
    for plan_mode in (False, True):
        editor, _spy, _requests = _editor(qapp, plan_mode=plan_mode)
        _send_preedit(editor, "mo")
        painted = _grab(editor)
        assert _px(painted, _W // 2, _H // 2) == _BLUE, f"plan_mode={plan_mode}"
        assert editor.plan_preview_badge_text() == "組字中"


def test_composing_over_a_valid_legacy_preview_keeps_it_as_the_base(qapp) -> None:
    """GUARD (green before and after): mutated text with a valid CSS preview
    still paints that preview under the chip."""
    editor, _spy, _requests = _editor(qapp, plan_mode=False)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    assert editor._mutated_preview_is_valid
    _send_preedit(editor, "mo")
    assert _px(_grab(editor), _W // 2, _H // 2) == _RED


def _chip_band_pixels(image: QImage) -> list[int]:
    """The pixels of the chip's bottom-left band (rows ``_H - 16 .. _H`` x
    columns ``0 .. _W // 2``); the badge sits top-right, 16 px tall here."""
    return [_px(image, x, y) for y in range(_H - 16, _H) for x in range(0, _W // 2)]


@pytest.mark.parametrize("state", ["pending", "refused", "composing_unchanged", "composing_typed"])
def test_plan_mode_paints_the_badge_and_no_chip(qapp, state: str) -> None:
    """Round 7 / F2: plan mode paints the base frame and the badge only; the
    typed text and the preedit are shown by the live text strip.  RED before:
    the white chip with the typed text sat in the bottom-left band."""
    editor, _spy, requests = _editor(qapp, plan_mode=True)
    if state in ("pending", "refused", "composing_typed"):
        editor.setPlainText("Buffer Tnak")
        editor._regenerate_preview()
    if state == "refused":
        assert editor.set_plan_preview_state(requests[-1][1], "type0_unicode_unmapped")
        assert editor.plan_preview_refused() is True
    if state.startswith("composing"):
        _send_preedit(editor, "mo")
        assert editor.preedit_text() == "mo"
    painted = _grab(editor)
    band = _chip_band_pixels(painted)
    assert band and set(band) == {_BLUE}, f"{state}: chip pixels in the bottom-left band"
    assert _px(painted, _W - 4, 4) != _BLUE, f"{state}: the badge must still be painted"
    assert not hasattr(editor, "plan_preview_chip_text"), "dead chip text API must be gone"


def test_non_plan_composing_still_paints_the_preedit_chip(qapp) -> None:
    """GUARD (green before and after): outside plan mode the composing chip is
    the only preedit echo (no live strip for add_text / legacy editors)."""
    editor, _spy, _requests = _editor(qapp, plan_mode=False)
    _send_preedit(editor, "mo")
    assert editor.preedit_text() == "mo"
    band = _chip_band_pixels(_grab(editor))
    assert any(pixel != _BLUE for pixel in band), "the composing chip disappeared"


def test_elide_composing_parts_keeps_the_preedit_whole_and_elides_committed_text_first() -> None:
    """RED before (no such helper; the whole elided string became the preedit
    slot and was fully underlined)."""
    from view.text_editing import elide_composing_parts

    parts = elide_composing_parts("A" * 40, "mo", "B" * 40, 20, len)
    before, preedit, after = parts
    assert preedit == "mo"
    assert before.startswith("\u2026") and before.endswith("A") and set(before[1:]) == {"A"}
    assert after.endswith("\u2026") and after.startswith("B") and set(after[:-1]) == {"B"}
    assert sum(len(part) for part in parts) <= 20

    # fits: untouched
    assert elide_composing_parts("ab", "mo", "cd", 20, len) == ("ab", "mo", "cd")
    # cursor at the end of the text: only the left side is elided
    left_only = elide_composing_parts("A" * 40, "mo", "", 20, len)
    assert left_only[1] == "mo" and left_only[2] == "" and left_only[0].startswith("\u2026")
    assert sum(len(part) for part in left_only) <= 20
    # one short side donates its unused room to the long side
    lopsided = elide_composing_parts("A" * 40, "mo", "BB", 20, len)
    assert lopsided[2] == "BB" and lopsided[1] == "mo"
    assert sum(len(part) for part in lopsided) <= 20
    assert len(lopsided[0]) > 20 // 2 - 1, "the short side's spare room must go to the long side"
    # a preedit that alone overflows is elided on its own, committed text dropped
    only = elide_composing_parts("x" * 5, "m" * 30, "y" * 5, 10, len)
    assert only[0] == "" and only[2] == "" and len(only[1]) <= 10 and only[1].startswith("\u2026")


def test_composing_chip_paints_the_elided_parts_with_the_preedit_alone_underlined(
    qapp, monkeypatch
) -> None:
    """RED before (no helper to wrap).  A long committed text with a short
    preedit in the middle: the legacy/add_text composing chip (round 7: the
    only preedit echo outside plan mode) is built from the helper's parts."""
    import view.text_editing as text_editing

    real = text_editing.elide_composing_parts
    seen: list[tuple[str, str, str]] = []

    def _spy(*args, **kwargs):
        parts = real(*args, **kwargs)
        seen.append(parts)
        return parts

    monkeypatch.setattr(text_editing, "elide_composing_parts", _spy)
    editor, _spy_css, _requests = _editor(qapp, plan_mode=False)
    editor.setPlainText("A" * 60 + "B" * 60)
    editor._regenerate_preview()
    assert editor._mutated_preview_is_valid, "a valid CSS preview keeps the chip path"
    cursor = editor.textCursor()
    cursor.setPosition(60)
    editor.setTextCursor(cursor)
    _send_preedit(editor, "mo")
    _grab(editor)
    assert seen, "the overflowing chip never went through the elision helper"
    before, preedit, after = seen[-1]
    assert preedit == "mo", seen[-1]
    assert before.startswith("\u2026") and after.endswith("\u2026"), seen[-1]


# ------------------------------------- round 4 / R4-1: paint a refused input


def test_refused_preview_paints_the_refusal_badge_over_the_base(qapp) -> None:
    """RED before: a refusal painted only the bare base frame (no badge), so
    the refusal was invisible.  Round 7: the typed text is in the live strip."""
    editor, spy, requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    assert editor.set_plan_preview_state(requests[-1][1], "type0_unicode_unmapped")
    painted = _grab(editor)

    assert editor.plan_preview_pending() is False
    assert editor.plan_preview_refused() is True
    assert editor.plan_preview_badge_text() == "無法套用"
    assert _px(painted, _W // 2, _H // 2) == _BLUE, "base is still the frozen frame"
    assert not _same(painted, _solid(_BLUE)), "the refusal badge is painted"
    assert spy.calls == []


def test_refusal_state_change_schedules_a_full_repaint(qapp) -> None:
    """RED before: set_plan_preview_state never called viewport().update(), so
    a stale 預覽更新中 badge stayed until an unrelated full repaint."""
    from PySide6.QtCore import QEvent, QObject

    editor, _spy, requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    editor.show()
    for _ in range(4):
        qapp.processEvents()

    regions: list = []

    class _Recorder(QObject):
        def eventFilter(self, obj, ev):  # noqa: N802 - Qt override
            if ev.type() == QEvent.Paint:
                regions.append(ev.region().boundingRect())
            return False

    recorder = _Recorder()
    editor.viewport().installEventFilter(recorder)
    try:
        # A superseded generation neither changes state nor repaints.
        assert editor.set_plan_preview_state(editor._plan_generation - 1, "x") is False
        for _ in range(3):
            qapp.processEvents()
        assert regions == []

        assert editor.set_plan_preview_state(requests[-1][1], "type0_unicode_unmapped")
        for _ in range(3):
            qapp.processEvents()
        full = editor.viewport().rect()
        assert any(r.contains(full) for r in regions), regions
    finally:
        editor.viewport().removeEventFilter(recorder)
        editor.close()


def test_no_change_refusal_paints_no_refusal_badge(qapp) -> None:
    """GUARD (green before and after): ``no_change`` means Apply is a no-op
    close, so '無法套用' would be false."""
    editor, _spy, requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()
    assert editor.set_plan_preview_state(requests[-1][1], "no_change")
    assert editor.plan_preview_refused() is False
