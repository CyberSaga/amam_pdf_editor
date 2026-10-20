"""Round 6, P1: the live text strip -- caret, selection and legible typed text while a
plan-preview editor is open.

Owner recording (2026-10-07, copy of ecc-dwg.pdf): with the shipped plan preview the
hidden ``QTextEdit`` paints nothing natively (the box shows the PDF-faithful raster),
so the owner could see no caret, no selection and only a 9-12 px elided chip of what
was typed.  The fix is UI chrome OUTSIDE the box: a ``LiveTextStrip`` on the first row
of the inline action bar that mirrors the editor (text, caret, selection, IME preedit)
in a screen font.  Pinned here:

* the strip mirrors the editor synchronously (no debounce) and is legible (>= 14 px);
* its caret is visible whenever the editor has focus, while the BOX keeps
  ``cursorWidth() == 0`` until the first interaction;
* an IME commit/preedit alone reveals the native caret (``reveal_caret`` chokepoint);
* the selection is an opaque palette-Highlight band; the preedit is underlined;
* a press/drag in the strip moves the caret/selection without finalizing; a press
  while composing commits the composition first (the P2 policy);
* the hidden layout never wraps in plan + run mode (paragraph mode keeps wrapping);
* the IME candidate window is anchored at the strip caret (box fallback otherwise);
* the strip is bound/unbound at the two editor-lifecycle chokepoints and never
  overlaps the box.

The synthetic tests run the real MVC stack on a generated Helvetica page (also
/Rotate 90 and 270 where the geometry matters); ``needs_fixtures`` tests use a COPY of
the gitignored ecc-dwg drawing through the real-app harness.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QFont,
    QGuiApplication,
    QImage,
    QInputMethodEvent,
    QPalette,
    QTextCursor,
)
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextEdit  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "test_scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "test_scripts"))

from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402
from test_text_commit_editor_mouse_gestures import (  # noqa: E402
    LINE,
    _Gui,
    _open_ecc_run,
    _pump,
    _SpyInputMethod,
    _WindowsLikeInputMethod,
    _write_page,
)
from qt_teardown import dispose_pdf_view  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402
from view.text_editing import PreviewBackedInlineTextEditor  # noqa: E402
from view.text_inline_action_bar import compute_inline_action_bar_pos  # noqa: E402
from view.text_live_strip import STRIP_MAX_PX, STRIP_MIN_PX, LiveTextStrip  # noqa: E402


# ------------------------------------------------------------------ harness


@pytest.fixture()
def gui(qapp, tmp_path, monkeypatch, request):
    rotation = getattr(request, "param", 0)
    path = _write_page(tmp_path / f"strip_rot{rotation}.pdf", rotation)
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None)
    )
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", preview="plan", max_tier=1)
    )
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    monkeypatch.setattr(controller, "_confirm_legacy_fallback", lambda *_a, **_k: False)
    view.resize(1400, 1000)
    view.show()
    view.activateWindow()
    _pump(120)
    controller.open_pdf(str(path))
    _pump(400)
    view.set_mode("edit_text")
    _pump(60)
    combo = view.text_target_mode_combo
    index = combo.findData("run")
    if index >= 0:
        combo.setCurrentIndex(index)
    _pump(60)
    harness = _Gui(model, view, controller, rotation)
    try:
        yield harness
    finally:
        dispose_pdf_view(view, controller, model)
        _pump(60)


_ROTATIONS = pytest.mark.parametrize("gui", [0, 90, 270], indirect=True)
_UNROTATED = pytest.mark.parametrize("gui", [0], indirect=True)


def _strip(gui):
    return gui.view.text_action_bar.live_text_strip


def _global_rect(widget) -> QRect:
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


def _editor_global_point(gui, rect: QRectF) -> QPoint:
    """Centre of an editor-local rectangle, as a global point (rotation-proof)."""
    polygon = gui.view.text_editor.mapToScene(rect)
    viewport_rect = gui.view.graphics_view.mapFromScene(polygon).boundingRect()
    return gui.viewport.mapToGlobal(viewport_rect.center())


def _ime(editor, *, commit: str = "", preedit: str = "", cursor: int | None = None) -> None:
    attributes = []
    if preedit and cursor is not None:
        attributes.append(
            QInputMethodEvent.Attribute(QInputMethodEvent.Cursor, cursor, 1)
        )
    event = QInputMethodEvent(preedit, attributes)
    if commit:
        event.setCommitString(commit)
    QApplication.sendEvent(editor, event)


# ------------------------------------------------------------------ open: mirror + legible


@_UNROTATED
def test_strip_mirrors_text_at_open_and_is_legible(gui) -> None:
    editor = gui.open_editor()
    bar = gui.view.text_action_bar
    strip = _strip(gui)
    assert strip.isVisible(), "plan mode: the strip is the first row of the bar"
    assert strip.parent() is bar
    assert strip.focusPolicy() == Qt.NoFocus
    assert strip.text() == editor.toPlainText() == LINE
    assert strip.font_pixel_size() >= 14, "legible even when the box is a few px tall"
    assert strip.font_pixel_size() <= 24
    # The box invariant stays: the native caret is hidden until the first interaction ...
    assert editor.cursorWidth() == 0
    assert editor.caret_revealed() is False
    # ... but the strip is chrome outside the box: its caret shows whenever the editor
    # has the focus (critic 8) -- the owner could not see the cursor before a key press.
    assert editor.hasFocus(), "precondition: the freshly opened editor holds the focus"
    assert strip.caret_visible() is True


@_UNROTATED
def test_strip_is_a_two_row_bar_with_the_controls_below(gui) -> None:
    gui.open_editor()
    bar = gui.view.text_action_bar
    strip = _strip(gui)
    assert strip.geometry().bottom() < bar.apply_btn.geometry().top()
    assert strip.geometry().bottom() < bar.move_grip.geometry().top()
    assert bar.move_grip.parent() is bar and bar.apply_btn.parent() is bar
    # The clicks that must stay inert for the composition (P2) keep landing on the margin.
    assert not strip.geometry().contains(QPoint(2, 2))


@_UNROTATED
def test_strip_is_hidden_without_a_live_editor(gui) -> None:
    gui.open_editor()
    assert _strip(gui).isVisible()
    QTest.keyClick(gui.editor(), Qt.Key_Escape)
    _pump(300)
    assert gui.view.text_editor is None
    assert not _strip(gui).isVisible()
    assert _strip(gui).is_bound() is False


# ------------------------------------------------------------------ typing, IME, caret reveal


@_UNROTATED
def test_strip_updates_synchronously_when_typing(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    QTest.keyClicks(editor, "X")  # no pump: the 150 ms preview debounce must not matter
    assert "X" in editor.toPlainText()
    assert strip.text() == editor.toPlainText()
    assert strip.caret_visible() is True
    # the caret rectangle follows the cursor (one position to the right of the old one)
    assert strip.cursor_rect_for(editor.textCursor().position()).x() > strip.cursor_rect_for(0).x()


@_UNROTATED
def test_ime_commit_alone_reveals_the_caret(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    assert editor.cursorWidth() == 0 and editor.caret_revealed() is False
    seen: list[bool] = []
    editor.caret_revealed_changed.connect(lambda: seen.append(True))
    _ime(editor, commit="點")  # no key press: exactly what an IME-only user sends
    assert editor.caret_revealed() is True
    assert editor.cursorWidth() == 1
    assert seen == [True]
    assert "點" in editor.toPlainText() and strip.text() == editor.toPlainText()
    assert strip.caret_visible() is True


@_UNROTATED
def test_ime_preedit_alone_reveals_the_caret(gui) -> None:
    editor = gui.open_editor()
    assert editor.caret_revealed() is False
    _ime(editor, preedit="ㄉ")
    assert editor.caret_revealed() is True and editor.cursorWidth() == 1
    _ime(editor)  # leave no composition behind


@_UNROTATED
def test_an_empty_input_method_event_does_not_reveal_the_caret(gui) -> None:
    editor = gui.open_editor()
    _ime(editor)  # no commit, no preedit
    assert editor.caret_revealed() is False and editor.cursorWidth() == 0


# ------------------------------------------------------------------ selection and preedit paint


def _pixels_equal_to(image: QImage, rgb: int) -> list[tuple[int, int]]:
    hits = []
    for y in range(image.height()):
        for x in range(image.width()):
            if (image.pixel(x, y) & 0xFFFFFF) == rgb:
                hits.append((x, y))
    return hits


@_UNROTATED
def test_strip_paints_the_selection_band(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    highlight = strip.palette().color(QPalette.Highlight).rgb() & 0xFFFFFF
    assert _pixels_equal_to(strip.grab().toImage(), highlight) == [], "no selection, no band"
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClick(editor, Qt.Key_Left, Qt.ShiftModifier)
    QTest.keyClick(editor, Qt.Key_Left, Qt.ShiftModifier)
    total = len(editor.toPlainText())
    cursor = editor.textCursor()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (total - 2, total)
    left = strip.cursor_rect_for(total - 2)
    right = strip.cursor_rect_for(total)
    hits = _pixels_equal_to(strip.grab().toImage(), highlight)
    assert len(hits) > 20, "the selection is an opaque palette Highlight band"
    xs = [x for x, _ in hits]
    ys = [y for _, y in hits]
    assert min(xs) >= left.x() - 1 and max(xs) <= right.x() + 1
    assert min(ys) >= left.y() - 1 and max(ys) <= left.y() + left.height() + 1


@_UNROTATED
def test_strip_shows_the_preedit_underlined_at_the_cursor(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    editor.moveCursor(QTextCursor.Start)
    editor.moveCursor(QTextCursor.NextCharacter)
    editor.moveCursor(QTextCursor.NextCharacter)
    position = editor.textCursor().position()
    assert position == 2
    plain_before = strip.grab().toImage()
    _ime(editor, preedit="ㄉㄧㄢ", cursor=2)
    assert editor.is_composing() and editor.preedit_text() == "ㄉㄧㄢ"
    assert strip.text() == editor.toPlainText(), "the preedit is not part of the document text"
    assert strip.preedit_area() == (2, "ㄉㄧㄢ")
    assert (2, 3) in strip.preedit_underline_ranges()
    assert strip.grab().toImage() != plain_before, "the composition is drawn in the strip"
    # characters AFTER the cursor are pushed right by the preedit
    assert strip.cursor_rect_for(3).x() > strip.cursor_rect_for(2).x() + 10
    # ... and the box paint is untouched by the strip (badge, not native glyphs)
    box_with_strip = editor.viewport().grab().toImage()
    strip.hide()
    _pump(30)
    assert editor.viewport().grab().toImage() == box_with_strip
    _ime(editor)


@_UNROTATED
def test_composition_changed_fires_in_plan_mode_and_the_strip_repaints_synchronously(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    areas: list[tuple[int, str]] = []
    editor.composition_changed.connect(lambda: areas.append(strip.preedit_area()))
    _ime(editor, preedit="ㄉ")
    _ime(editor, preedit="ㄉㄧ")
    _ime(editor)
    pos = editor.textCursor().position()
    assert areas == [(pos, "ㄉ"), (pos, "ㄉㄧ"), (pos, "")]


@_UNROTATED
def test_the_preedit_cursor_offset_moves_the_strip_caret(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    editor.moveCursor(QTextCursor.Start)
    _ime(editor, preedit="ㄉㄧㄢ", cursor=1)
    first = strip.caret_rect()
    _ime(editor, preedit="ㄉㄧㄢ", cursor=3)
    second = strip.caret_rect()
    assert second.x() > first.x(), "same preedit, new cursor offset: the caret moves"
    _ime(editor)


# ------------------------------------------------------------------ strip mouse


@_UNROTATED
def test_click_in_strip_moves_caret_without_finalizing(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    proxy = gui.view.text_editor
    undo_depth = len(gui.model.command_manager._undo_stack)
    generation = editor._plan_generation
    rect = strip.cursor_rect_for(3)
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, QPoint(rect.x(), rect.center().y()))
    _pump(250)
    assert editor.textCursor().position() == 3
    assert editor.hasFocus(), "the strip never takes the focus"
    assert gui.view.text_editor is proxy and gui.editor() is editor
    assert len(gui.model.command_manager._undo_stack) == undo_depth
    assert editor._plan_generation == generation, "moving a caret supersedes no preview"
    assert editor.caret_revealed() is True
    assert strip.caret_visible() is True


@_UNROTATED
def test_drag_in_strip_selects_and_shift_click_extends(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    y = strip.cursor_rect_for(0).center().y()
    start = QPoint(strip.cursor_rect_for(2).x(), y)
    end = QPoint(strip.cursor_rect_for(6).x(), y)
    QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(strip, QPoint((start.x() + end.x()) // 2, y))
    QTest.mouseMove(strip, end)
    QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, end)
    cursor = editor.textCursor()
    assert (cursor.anchor(), cursor.position()) == (2, 6)
    # Shift+click extends from the anchor
    far = QPoint(strip.cursor_rect_for(9).x(), y)
    QTest.mouseClick(strip, Qt.LeftButton, Qt.ShiftModifier, far)
    cursor = editor.textCursor()
    assert (cursor.anchor(), cursor.position()) == (2, 9)
    assert gui.editor() is editor


@_UNROTATED
def test_a_right_click_in_the_strip_changes_nothing(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    before = (editor.textCursor().position(), editor.textCursor().anchor())
    rect = strip.cursor_rect_for(5)
    QTest.mouseClick(strip, Qt.RightButton, Qt.NoModifier, QPoint(rect.x(), rect.center().y()))
    _pump(100)
    assert (editor.textCursor().position(), editor.textCursor().anchor()) == before
    assert gui.editor() is editor


@_UNROTATED
def test_a_strip_press_while_composing_commits_first_then_places_the_caret(
    gui, monkeypatch
) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    editor.moveCursor(QTextCursor.Start)
    log: list[str] = []
    spy = _SpyInputMethod(editor, log, QGuiApplication.inputMethod())
    monkeypatch.setattr(QGuiApplication, "inputMethod", staticmethod(lambda: spy))
    _ime(editor, preedit="xyz")
    assert editor.is_composing()
    focus_outs: list[bool] = []
    editor.focus_out_requested.connect(lambda: focus_outs.append(True))
    rect = strip.cursor_rect_for(3)  # laid out with the preedit at the start of the line
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, QPoint(rect.x(), rect.center().y()))
    _pump(250)
    assert log == ["commit"], "committed exactly once, by the input method"
    assert editor.is_composing() is False
    assert focus_outs == [] and gui.editor() is editor and gui.view.text_editor is not None
    assert editor.toPlainText() == "xyz" + LINE, "the composition is kept"
    # the caret goes where the pointer is in the post-commit layout: after 'xyzAlp'
    assert editor.textCursor().position() == 6


@_UNROTATED
def test_a_strip_press_resets_the_input_method_when_commit_is_a_no_op(gui, monkeypatch) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    editor.moveCursor(QTextCursor.Start)
    log: list[str] = []
    spy = _WindowsLikeInputMethod(editor, log, QGuiApplication.inputMethod())
    monkeypatch.setattr(QGuiApplication, "inputMethod", staticmethod(lambda: spy))
    _ime(editor, preedit="xyz")
    rect = strip.cursor_rect_for(3)
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, QPoint(rect.x(), rect.center().y()))
    _pump(250)
    assert log == ["commit", "reset"]
    assert editor.is_composing() is False
    assert editor.toPlainText() == "xyz" + LINE


@_UNROTATED
def test_a_press_on_the_bar_margin_keeps_the_composition(gui, monkeypatch) -> None:
    editor = gui.open_editor()
    editor.setFocus()
    log: list[str] = []
    spy = _SpyInputMethod(editor, log, QGuiApplication.inputMethod())
    monkeypatch.setattr(QGuiApplication, "inputMethod", staticmethod(lambda: spy))
    _ime(editor, preedit="xyz")
    QTest.mouseClick(gui.view.text_action_bar, Qt.LeftButton, Qt.NoModifier, QPoint(2, 2))
    _pump(150)
    assert log == [] and editor.is_composing() is True and gui.editor() is editor
    _ime(editor)


# ------------------------------------------------------------------ IME anchor


@_ROTATIONS
def test_ime_cursor_rectangle_points_at_the_strip_caret(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End)
    rect = editor.inputMethodQuery(Qt.ImCursorRectangle)
    assert isinstance(rect, QRectF) and rect.width() >= 1.0 and rect.height() > 0
    point = _editor_global_point(gui, rect)
    assert _global_rect(strip).contains(point), (point, _global_rect(strip))
    # ... and it follows the caret
    QTest.keyClick(editor, Qt.Key_Home)
    left = _editor_global_point(gui, editor.inputMethodQuery(Qt.ImCursorRectangle))
    assert left.x() < point.x()


@_UNROTATED
def test_ime_anchor_falls_back_to_the_box_when_the_bar_is_not_placed(gui) -> None:
    editor = gui.open_editor()
    gui.view.text_action_bar.hide()
    rect = editor.inputMethodQuery(Qt.ImCursorRectangle)
    assert isinstance(rect, QRectF) and rect.width() >= 1.0 and rect.height() > 0
    assert QRectF(editor.rect()).intersects(rect), "the fallback anchors inside the box"


@_UNROTATED
def test_ime_anchor_updates_after_the_bar_moves_or_the_caret_moves(gui, monkeypatch) -> None:
    editor = gui.open_editor()
    calls: list[object] = []

    class _Spy:
        def update(self, queries):
            calls.append(queries)

        def __getattr__(self, name):
            return getattr(real, name)

    real = QGuiApplication.inputMethod()
    monkeypatch.setattr(QGuiApplication, "inputMethod", staticmethod(lambda: _Spy()))
    editor.setFocus()
    calls.clear()
    QTest.keyClick(editor, Qt.Key_End)
    assert Qt.ImCursorRectangle in calls, "a caret move re-anchors the candidate window"
    calls.clear()
    gui.view._position_text_action_bar()
    assert Qt.ImCursorRectangle in calls, "a bar move re-anchors the candidate window"


# ------------------------------------------------------------------ hidden layout wrap


@_UNROTATED
def test_hidden_layout_does_not_wrap_in_plan_run_mode(gui) -> None:
    editor = gui.open_editor()
    assert gui.view.editing_target_mode == "run"
    assert editor.plan_preview_mode() is True
    assert editor.lineWrapMode() == QTextEdit.NoWrap
    one_line = editor.document().size().height()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClicks(editor, "x" * 90)
    assert editor.document().size().height() == pytest.approx(one_line), "never wraps into a hidden line"
    assert editor.horizontalScrollBar().maximum() > 0, "the hidden layout scrolled horizontally"
    QTest.keyClick(editor, Qt.Key_Home)
    assert editor.textCursor().position() == 0, "Home reaches the start although it scrolled"
    QTest.keyClick(editor, Qt.Key_End)
    assert editor.textCursor().position() == len(editor.toPlainText())


@_UNROTATED
def test_paragraph_mode_keeps_the_wrapping_hidden_layout_and_the_strip(gui) -> None:
    gui.view.text_target_mode_combo.setCurrentIndex(
        gui.view.text_target_mode_combo.findData("paragraph")
    )
    _pump(80)
    editor = gui.open_editor()
    assert gui.view.editing_target_mode == "paragraph"
    assert editor.lineWrapMode() == QTextEdit.WidgetWidth, "Up/Down/Home/End need real lines"
    strip = _strip(gui)
    assert strip.isVisible() and strip.text() == editor.toPlainText()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClicks(editor, " word" * 40)
    total = len(editor.toPlainText())
    QTest.keyClick(editor, Qt.Key_Up)
    assert 0 < editor.textCursor().position() < total, "Up moves between wrapped lines"


@_UNROTATED
def test_newlines_lay_out_on_separate_strip_lines_with_one_to_one_indices(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setPlainText("alpha\nbeta\ngamma")
    assert strip.text() == editor.toPlainText() == "alpha\nbeta\ngamma"
    assert strip.line_count() == 3
    first = strip.cursor_rect_for(0)
    second = strip.cursor_rect_for(6)  # start of "beta"
    third = strip.cursor_rect_for(11)  # start of "gamma"
    assert second.y() > first.y() and third.y() > second.y()
    assert second.x() == first.x() == third.x()
    # the end of "alpha" and the start of "beta" are different positions on different lines
    assert strip.cursor_rect_for(5).x() > first.x() and strip.cursor_rect_for(5).y() == first.y()


# ------------------------------------------------------------------ geometry


@_ROTATIONS
def test_strip_never_overlaps_the_box_and_the_bar_follows_its_growth(gui) -> None:
    editor = gui.open_editor()
    bar = gui.view.text_action_bar
    strip = _strip(gui)
    viewport_rect = gui.viewport.rect()

    def _box() -> QRect:
        scene = gui.view.text_editor.mapRectToScene(gui.view.text_editor.boundingRect())
        return gui.view.graphics_view.mapFromScene(scene).boundingRect()

    assert bar.isVisible() and not bar.geometry().intersects(_box())
    height_before = bar.height()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClicks(editor, " lorem ipsum dolor sit amet" * 8)
    assert strip.line_count() >= 2
    assert bar.height() > height_before, "the bar grows with the strip, synchronously"
    assert not bar.geometry().intersects(_box()), "no overlap on the same event turn"
    assert viewport_rect.contains(bar.geometry())
    # the strip is a visible row inside the bar
    assert bar.rect().contains(strip.geometry())


@_UNROTATED
def test_the_strip_caps_its_height_and_keeps_the_caret_line_visible(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClicks(editor, " lorem ipsum dolor sit amet" * 30)
    assert strip.line_count() > 6
    line_height = strip.line_height()
    assert strip.height() <= 6 * line_height + 12
    caret = strip.caret_rect()
    assert strip.rect().contains(caret), "the layout scrolls so the caret line stays visible"
    QTest.keyClick(editor, Qt.Key_Home)
    caret = strip.caret_rect()
    assert strip.rect().contains(caret)


def test_a_tall_bar_prefers_the_side_before_overlapping_the_box() -> None:
    viewport = QRect(0, 0, 1000, 600)
    editor = QRect(300, 330, 120, 20)
    bar = QSize(300, 180)
    pos = compute_inline_action_bar_pos(editor, bar, viewport)
    assert pos is not None
    placed = QRect(pos, bar)
    assert not placed.intersects(editor), "side placement is chosen before the overlapping fallback"
    assert viewport.contains(placed)


# ------------------------------------------------------------------ lifecycle


@_UNROTATED
def test_the_strip_is_unbound_on_close_and_rebinds_for_the_next_editor(gui) -> None:
    editor = gui.open_editor()
    strip = _strip(gui)
    assert strip.is_bound() is True
    QTest.keyClick(editor, Qt.Key_Escape)
    _pump(300)
    assert gui.view.text_editor is None
    assert strip.is_bound() is False and strip.isHidden()
    assert strip.text() == ""
    editor2 = gui.open_editor()
    assert strip.is_bound() is True and strip.isVisible()
    assert strip.text() == editor2.toPlainText() == LINE


def test_binding_a_second_editor_never_leaves_the_first_connected(qapp) -> None:
    strip = LiveTextStrip()
    first = PreviewBackedInlineTextEditor("first")
    second = PreviewBackedInlineTextEditor("second")
    first.set_plan_preview_mode(True)
    second.set_plan_preview_mode(True)
    strip.bind(first)
    strip.bind(second)
    first.setPlainText("changed")
    assert strip.text() == "second"
    second.setPlainText("again")
    assert strip.text() == "again"
    strip.unbind()
    second.setPlainText("late")
    assert strip.text() == "" and strip.is_bound() is False


def test_a_deleted_editor_does_not_crash_a_bound_strip(qapp) -> None:
    strip = LiveTextStrip()
    editor = PreviewBackedInlineTextEditor("gone")
    strip.bind(editor)
    editor.deleteLater()
    QApplication.sendPostedEvents(None, 0)
    _pump(30)
    strip.refresh()  # must not raise
    strip.unbind()
    strip.unbind()  # idempotent


def test_legacy_editor_keeps_the_strip_hidden(qapp) -> None:
    strip = LiveTextStrip()
    editor = PreviewBackedInlineTextEditor("legacy")  # not in plan mode
    strip.bind(editor)
    assert strip.isHidden(), "legacy mode paints the native text in the box already"
    editor.set_plan_preview_mode(True)
    strip.refresh()
    assert not strip.isHidden()


def test_the_font_is_clamped_to_the_legible_range(qapp) -> None:
    strip = LiveTextStrip()
    editor = PreviewBackedInlineTextEditor("size")
    editor.set_plan_preview_mode(True)
    strip.bind(editor)
    small = QFont("Arial")
    small.setPixelSize(6)
    editor.setFont(small)
    strip.refresh()
    assert strip.font_pixel_size() == STRIP_MIN_PX
    big = QFont("Arial")
    big.setPixelSize(80)
    editor.setFont(big)
    strip.refresh()
    assert strip.font_pixel_size() == STRIP_MAX_PX


def test_strip_survives_empty_text_and_reports_a_sane_caret(qapp) -> None:
    strip = LiveTextStrip()
    editor = PreviewBackedInlineTextEditor("")
    editor.set_plan_preview_mode(True)
    strip.bind(editor)
    strip.resize(300, strip.sizeHint().height())
    assert strip.text() == "" and strip.line_count() == 1
    rect = strip.caret_rect()
    assert rect.height() > 0 and rect.width() >= 1
    assert strip.cursor_rect_for(0) == strip.cursor_rect_for(99), "positions clamp to the text"


# ------------------------------------------------------------------ owner scenario (corpus copy)


@pytest.mark.needs_fixtures
def test_strip_on_the_owner_run_mirrors_types_and_reveals_on_ime_commit(tmp_path, monkeypatch) -> None:
    app, editor = _open_ecc_run(monkeypatch, tmp_path)
    try:
        view = app.view
        strip = view.text_action_bar.live_text_strip
        assert strip.isVisible()
        assert strip.text() == editor.toPlainText() == "備為C標新設。"
        assert strip.font_pixel_size() >= 14
        assert editor.height() <= 40
        assert editor.cursorWidth() == 0 and strip.caret_visible() is True
        # the hidden layout is one line at the real zoom (it wrapped before: Home gave 15)
        assert editor.lineWrapMode() == QTextEdit.NoWrap
        one_line = editor.document().size().height()
        editor.setFocus()
        _ime(editor, commit="點擊頁面")
        assert editor.caret_revealed() is True and editor.cursorWidth() == 1
        assert strip.text() == editor.toPlainText() and "點擊頁面" in strip.text()
        QTest.keyClicks(editor, "x" * 40)
        assert editor.document().size().height() == pytest.approx(one_line)
        QTest.keyClick(editor, Qt.Key_Home)
        assert editor.textCursor().position() == 0
        assert strip.text() == editor.toPlainText()
    finally:
        app.close()


@pytest.mark.needs_fixtures
def test_strip_after_a_refused_commit_still_shows_the_typed_text(tmp_path, monkeypatch) -> None:
    app, editor = _open_ecc_run(monkeypatch, tmp_path)
    try:
        strip = app.view.text_action_bar.live_text_strip
        editor.setFocus()
        _ime(editor, commit="點擊頁面")
        assert app.wait(lambda: editor.plan_rejection_reason() is not None, 20)
        app.pump(200)
        assert editor.plan_preview_refused() is True
        assert strip.isVisible() and "點擊頁面" in strip.text()
        assert strip.font_pixel_size() >= 14
        assert app.view.text_action_bar.isVisible()
    finally:
        app.close()
