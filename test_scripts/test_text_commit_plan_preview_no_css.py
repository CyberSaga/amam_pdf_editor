"""No CSS/HTML interim preview in plan mode (UI critique step 11).

With ``TextCommitSettings.preview == "plan"`` the inline editor must never
paint the CSS/HTML system-font frame while the user types: that frame is
rendered from fonts the PDF does not use, so it would claim a fidelity it
cannot have.  Until the verified plan raster for the current text arrives the
editor shows the original (or the last verified) frame, a "預覽更新中" badge and
a small chip with the typed text.  Legacy preview mode is unchanged.

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


def test_pending_paints_frozen_frame_badge_and_chip(qapp) -> None:
    editor, spy, _requests = _editor(qapp, plan_mode=True)
    editor.setPlainText("Buffer Tnak")
    editor._regenerate_preview()

    assert editor.plan_preview_pending() is True
    assert editor.plan_preview_badge_text() == "預覽更新中"
    assert editor.plan_preview_chip_text() == "Buffer Tnak"
    painted = _grab(editor)
    assert _px(painted, _W // 2, _H // 2) == _BLUE, "base is the frozen frame"
    assert not _same(painted, _solid(_BLUE)), "badge and chip are painted on top"
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
    assert editor.plan_preview_chip_text() == "Buffer Tnka"


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
