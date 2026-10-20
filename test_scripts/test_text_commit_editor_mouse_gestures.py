"""Round 6, P2: a mouse gesture inside the open inline editor means caret and selection.

Owner recording (2026-10-07, copy of ecc-dwg.pdf): a click with a few pixels of hand
jitter inside the open editor moved the box ~14 px and flipped an unchanged text to
``geometry_override_present`` (refused, Apply disabled), and an attempted drag-select
dragged the box instead.  The view turned EVERY press inside the box into a pending
editor drag.  Now:

* LeftButton press/drag inside the box places the caret / selects text through a
  scroll-independent hit-test of the editor's document layout; it never moves the
  box and never invalidates the plan preview;
* the box moves only through the visible ``⠿ 移動`` grip on the inline action bar
  (edit_text and add_text);
* an in-box press first commits a live composition, then places the caret;
* the viewport shows an I-beam over the box and is reset when the editor closes;
* a first click on not-yet-open text needs ``max(3, startDragDistance())`` viewport
  pixels before it counts as a drag.

The synthetic tests run the real MVC stack on a generated Helvetica page (also
/Rotate 90 and 270); the two owner-scenario tests use a COPY of the ecc-dwg corpus
file through the real-app harness of ``test_text_commit_ui_real_corpus``.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QGuiApplication,
    QImage,
    QInputMethodEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QTextCursor,
)
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsRectItem  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "test_scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "test_scripts"))

from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402
from qt_teardown import dispose_pdf_view  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402
from view.text_editing import (  # noqa: E402
    PreviewBackedInlineTextEditor,
    TextEditDragState,
    TextEditFinalizeReason,
    TextEditGeometryConstants,
    TextEditOutcome,
    _MASK_RING_THICKNESS_PX,
    _editing_position_changed,
    _ORIGIN_MASK_MAX_RING_NONUNIFORM_PCT,
    _origin_mask_margin_px,
    _qimage_ring_mean_rgb,
    _qimage_ring_nonuniform_ratio,
)
from view.text_inline_action_bar import EditorMoveGrip  # noqa: E402

LINE = "Alpha Bravo Charlie Delta"


# ------------------------------------------------------------------ harness


def _pump(ms: int = 200) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def _wait_until(predicate, timeout_s: float, step_ms: int = 50) -> None:
    """Pump events until ``predicate()`` holds or ``timeout_s`` elapse; the caller asserts."""
    end = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < end:
        _pump(step_ms)


def _editor_geometry(view) -> tuple[QPointF, fitz.Rect]:
    """The open editor's proxy position and its ``editing_rect`` (a move changes both)."""
    return QPointF(view.text_editor.pos()), fitz.Rect(view.editing_rect)


def _scene_rect_of(view, rect: fitz.Rect, page: int = 0) -> QRectF:
    """A visual page rect (pt) as a scene rect at the current render scale, computed here
    (not through the view's own mapping) so the geometry checks stay independent of it."""
    rs = view._render_scale
    return QRectF(
        view._page_scene_x(page) + rect.x0 * rs,
        view._page_scene_y(page) + rect.y0 * rs,
        rect.width * rs,
        rect.height * rs,
    )


def _write_page(
    path: Path,
    rotation: int,
    text: str = LINE,
    gray: float | None = None,
    pages: int = 1,
    neighbour: bool = False,
    stripes: bool = False,
    x: float = 72,
    y: float = 672,
) -> Path:
    """A generated Helvetica page.  ``gray`` (round 7 / F1) paints the text in that grey:
    0.57 -> rgb 145, contrast 1.92 on white, which triggers the mask tint ladder (the
    synthetic copy of the ecc-dwg trap).  ``pages`` repeats the same page.  ``neighbour``
    (round 7 / REG-1) adds a Courier run NEIGHBOUR on the same baseline, 100 pt from the left.
    ``stripes`` (round 7 / RPU-2) paints dense 1 pt black/white vertical stripes (2 pt period)
    under the run: a hatched background that no single flat colour can stand in for.  ``x``
    (round 7 / R7-INT-2) is the run's PDF x in pt (default 72), to place it near a page edge;
    ``y`` (R3-INT-1) is the baseline's PDF y in pt (default 672), to place it near the bottom."""
    doc = fitz.open()
    colour = "" if gray is None else f"{gray} g "
    for _index in range(pages):
        page = doc.new_page(width=612, height=792)
        content_xref = doc.get_new_xref()
        doc.update_object(content_xref, "<<>>")
        stream = f"BT {colour}/F1 14 Tf {x} {y} Td ({text}) Tj ET"
        if stripes:
            hatch = " ".join(f"{x} 660 1 30 re f" for x in range(60, 420, 2))
            stream = f"0 g {hatch} " + stream
        if neighbour:
            stream += " BT /F2 14 Tf 100 672 Td (NEIGHBOUR) Tj ET"
        doc.update_stream(content_xref, stream.encode("latin-1"))
        doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
        font_xref = doc.get_new_xref()
        doc.update_object(
            font_xref,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        )
        fonts = f"/F1 {font_xref} 0 R"
        if neighbour:
            courier_xref = doc.get_new_xref()
            doc.update_object(
                courier_xref,
                "<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
            )
            fonts += f" /F2 {courier_xref} 0 R"
        doc.xref_set_key(page.xref, "Resources", f"<< /Font << {fonts} >> >>")
        page.set_rotation(rotation)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


class _Gui:
    """The real model + view + controller on one generated page."""

    def __init__(self, model: PDFModel, view: PDFView, controller: PDFController, rotation: int):
        self.model = model
        self.view = view
        self.controller = controller
        self.rotation = rotation

    # ---- readers
    @property
    def viewport(self):
        return self.view.graphics_view.viewport()

    def editor(self):
        proxy = self.view.text_editor
        return proxy.widget() if proxy is not None else None

    def reason(self):
        return self.view._ensure_text_edit_manager().current_rejection_reason()

    def geometry(self):
        return _editor_geometry(self.view)

    # ---- coordinates (proxy-local pixels -> viewport pixels, rotation-proof)
    def vp_point(self, local_x: float, local_y: float) -> QPoint:
        scene = self.view.text_editor.mapToScene(QPointF(local_x, local_y))
        return self.view.graphics_view.mapFromScene(scene)

    def vp_char(self, index: int, dx: float = 1.0) -> QPoint:
        """Viewport point just right of the caret slot of character ``index``."""
        editor = self.editor()
        cursor = QTextCursor(editor.document())
        cursor.setPosition(index)
        rect = editor.cursorRect(cursor)
        return self.vp_point(rect.x() + dx, rect.y() + rect.height() / 2.0)

    # ---- real input
    def press(self, pos: QPoint, modifier=Qt.NoModifier) -> None:
        QTest.mousePress(self.viewport, Qt.LeftButton, modifier, pos)
        _pump(30)

    def move(self, pos: QPoint) -> None:
        QTest.mouseMove(self.viewport, pos)
        _pump(30)

    def release(self, pos: QPoint, modifier=Qt.NoModifier) -> None:
        QTest.mouseRelease(self.viewport, Qt.LeftButton, modifier, pos)
        _pump(60)

    def click(self, pos: QPoint, modifier=Qt.NoModifier) -> None:
        self.press(pos, modifier)
        self.release(pos, modifier)

    def open_editor(self):
        centre = _scene_rect_of(self.view, _ink_bbox(self.model.doc[0])).center()
        self.view.graphics_view.centerOn(centre)
        _pump(80)
        QTest.mouseClick(
            self.viewport, Qt.LeftButton, Qt.NoModifier, self.view.graphics_view.mapFromScene(centre)
        )
        _wait_until(lambda: self.editor() is not None, 10, step_ms=20)
        _pump(250)
        editor = self.editor()
        assert editor is not None, "the click must open the editor"
        assert isinstance(editor, PreviewBackedInlineTextEditor)
        return editor


def _ink_bbox(page: fitz.Page) -> fitz.Rect:
    from test_scripts.test_text_geometry_page_rotation import _ink_bbox as ink

    return ink(page)


def _gui_session(
    qapp, tmp_path, monkeypatch, rotation, gray=None, pages=1, preview="plan", target="run", **page_kwargs
):
    """Generator behind the ``gui`` fixtures: the real MVC stack on a generated page.  ``target`` is
    the text-target combo data (``"run"`` / ``"paragraph"``)."""
    path = _write_page(
        tmp_path / f"mouse_rot{rotation}.pdf", rotation, gray=gray, pages=pages, **page_kwargs
    )
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None)
    )
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", preview=preview, max_tier=1)
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
    index = combo.findData(target)
    if index >= 0:
        combo.setCurrentIndex(index)
    _pump(60)
    assert model.doc[0].rotation == rotation
    harness = _Gui(model, view, controller, rotation)
    try:
        yield harness
    finally:
        dispose_pdf_view(view, controller, model)
        _pump(60)


@pytest.fixture()
def gui(qapp, tmp_path, monkeypatch, request):
    yield from _gui_session(qapp, tmp_path, monkeypatch, getattr(request, "param", 0))


@pytest.fixture()
def gui_legacy(qapp, tmp_path, monkeypatch, request):
    """Round 7 / TV-1: the legacy preview (kill-switch configuration), where a keep-finalize commits."""
    yield from _gui_session(qapp, tmp_path, monkeypatch, getattr(request, "param", 0), preview="legacy")


@pytest.fixture()
def gui_grey(qapp, tmp_path, monkeypatch, request):
    """Round 7 / F1: grey 145 text, so the editor's moving mask is TINTED (202), not the page colour."""
    yield from _gui_session(qapp, tmp_path, monkeypatch, getattr(request, "param", 0), gray=0.57)


@pytest.fixture()
def gui_neighbour(qapp, tmp_path, monkeypatch, request):
    """Round 7 / REG-1: the one-word run AB with a Courier run NEIGHBOUR on the same baseline."""
    yield from _gui_session(
        qapp, tmp_path, monkeypatch, getattr(request, "param", 0), text="AB", neighbour=True
    )


@pytest.fixture()
def gui_stripes(qapp, tmp_path, monkeypatch, request):
    """Round 7 / RPU-2: the run sits on dense black/white stripes (a hatched background)."""
    # The ink-bbox helper counts stripe pixels as ink; the click must land on the text run.
    monkeypatch.setattr(sys.modules[__name__], "_ink_bbox", lambda page: page.search_for(LINE)[0])
    yield from _gui_session(qapp, tmp_path, monkeypatch, getattr(request, "param", 0), stripes=True)


@pytest.fixture()
def gui_edge(qapp, tmp_path, monkeypatch, request):
    """Round 7 / R7-INT-2: the short run ``12`` (15.6 pt wide, so the editor is padded to its 80 px
    minimum) at ``(rotation, PDF x)`` near a page edge.  The editor box hangs past the page."""
    rotation, x = request.param
    yield from _gui_session(qapp, tmp_path, monkeypatch, rotation, text="12", x=x)


@pytest.fixture()
def gui_bottom(qapp, tmp_path, monkeypatch, request):
    """R3-INT-1: PARAGRAPH mode at 50 % zoom on a run whose baseline is ``y`` pt from the page bottom
    (rotation 0) or visually at the bottom (rotation 180).  The measured paragraph box is taller than its
    7 px source span (wrap + document margin) and opens hanging past the page bottom."""
    rotation, y = request.param
    yield from _gui_session(qapp, tmp_path, monkeypatch, rotation, target="paragraph", y=y)


@pytest.fixture()
def gui_top_crossing(qapp, tmp_path, monkeypatch, request):
    """R7-DEG-1: Helvetica 14 near the visual page top (rotation 0: baseline at PDF y 787; 180: PDF y 1,
    where the upside-down glyphs' descent crosses the top).  The span's own bbox (font ascender/descender
    metrics, never clipped to the page) crosses the page top (y0 -5.95 / -2.05 pt), so the editor proxy
    opens above the page."""
    rotation, y = request.param
    # The ink helper counts only on-page pixels; the click must land on the run's own bbox.
    monkeypatch.setattr(
        sys.modules[__name__], "_ink_bbox", lambda page: page.search_for(LINE)[0] * page.rotation_matrix
    )
    yield from _gui_session(qapp, tmp_path, monkeypatch, rotation, y=y)


@pytest.fixture()
def gui_grey_two_pages(qapp, tmp_path, monkeypatch, request):
    yield from _gui_session(
        qapp, tmp_path, monkeypatch, getattr(request, "param", 0), gray=0.57, pages=2
    )


_ROTATIONS = pytest.mark.parametrize("gui", [0, 90, 270], indirect=True)
_ALL_ROTATIONS = pytest.mark.parametrize("gui", [0, 90, 180, 270], indirect=True)
_UNROTATED = pytest.mark.parametrize("gui", [0], indirect=True)
_LEGACY_ALL = pytest.mark.parametrize("gui_legacy", [0, 90, 180, 270], indirect=True)
_NEIGHBOUR_ALL = pytest.mark.parametrize("gui_neighbour", [0, 90, 180, 270], indirect=True)
_GREY_ALL = pytest.mark.parametrize("gui_grey", [0, 90, 180, 270], indirect=True)
_GREY_UNROTATED = pytest.mark.parametrize("gui_grey", [0], indirect=True)
_STRIPES_UNROTATED = pytest.mark.parametrize("gui_stripes", [0], indirect=True)
_GREY_TWO_PAGES = pytest.mark.parametrize("gui_grey_two_pages", [0], indirect=True)


# ------------------------------------------------------------------ press, jitter, drag-select


@_ROTATIONS
def test_press_and_jitter_inside_open_editor_keeps_position_and_apply(gui) -> None:
    """Owner recording 54.47 s: a click with jitter moved the box and refused an
    unchanged text.  Now it only places the caret."""
    editor = gui.open_editor()
    assert gui.view.text_apply_btn.isEnabled(), "precondition: the unchanged text is applicable"
    before = gui.geometry()
    generation = editor._plan_generation

    centre = gui.vp_point(editor.width() / 2.0, editor.height() / 2.0)
    gui.press(centre)
    jitter = gui.vp_point(editor.width() / 2.0 + 4.0, editor.height() / 2.0)
    gui.move(jitter)
    gui.release(jitter)
    _pump(300)

    assert gui.view.text_editor is not None and gui.editor() is editor
    assert gui.geometry() == before
    assert gui.view._drag_active is False and gui.view._drag_pending is False
    assert gui.view.text_apply_btn.isEnabled() is True
    assert gui.reason() is None
    assert gui.view.text_rebuild_btn.isHidden() is True
    assert editor._plan_generation == generation, "a caret gesture never supersedes the preview"
    assert gui.view._text_edit_drag_state == TextEditDragState.IDLE


@_ROTATIONS
def test_drag_inside_open_editor_selects_text_and_never_moves_it(gui) -> None:
    editor = gui.open_editor()
    before = gui.geometry()
    y = editor.height() / 2.0
    start_x = 12.0
    gui.press(gui.vp_point(start_x, y))
    for step in range(1, 12):
        gui.move(gui.vp_point(start_x + 3.0 * step, y))
    end = gui.vp_point(start_x + 33.0, y)
    gui.release(end)

    cursor = editor.textCursor()
    assert cursor.hasSelection()
    assert cursor.selectionStart() < cursor.selectionEnd()
    assert editor.toPlainText()[cursor.selectionStart() : cursor.selectionEnd()].strip()
    assert gui.geometry() == before
    assert gui.view._drag_active is False
    assert gui.view.text_apply_btn.isEnabled() is True
    assert gui.view._text_edit_drag_state == TextEditDragState.IDLE


@_ROTATIONS
def test_press_places_the_caret_at_the_clicked_character(gui) -> None:
    editor = gui.open_editor()
    before = gui.geometry()
    for index in (1, 5, 11):
        gui.click(gui.vp_char(index))
        cursor = editor.textCursor()
        assert not cursor.hasSelection()
        assert cursor.position() == index, (index, cursor.position())
    assert gui.geometry() == before


@_ROTATIONS
def test_shift_click_extends_selection_and_press_reveals_caret(gui) -> None:
    editor = gui.open_editor()
    assert editor.caret_revealed() is False
    assert editor.cursorWidth() == 0, "the box caret stays hidden until the first interaction"

    gui.click(gui.vp_char(1))
    assert editor.caret_revealed() is True
    assert editor.cursorWidth() == 1
    gui.click(gui.vp_char(4), Qt.ShiftModifier)

    cursor = editor.textCursor()
    assert (cursor.anchor(), cursor.position()) == (1, 4)
    assert cursor.selectedText() == LINE[1:4]


@_UNROTATED
def test_a_drag_never_invalidates_the_plan_preview_or_the_editing_rect(gui) -> None:
    editor = gui.open_editor()
    generation = editor._plan_generation
    rect = fitz.Rect(gui.view.editing_rect)
    y = editor.height() / 2.0
    gui.press(gui.vp_point(10.0, y))
    for step in range(1, 8):
        gui.move(gui.vp_point(10.0 + 4.0 * step, y))
    gui.release(gui.vp_point(38.0, y))
    assert editor._plan_generation == generation
    assert fitz.Rect(gui.view.editing_rect) == rect


@_UNROTATED
def test_dragging_back_past_the_box_edges_clamps_into_the_text(gui) -> None:
    editor = gui.open_editor()
    length = len(editor.toPlainText())
    y = editor.height() / 2.0
    gui.press(gui.vp_char(5))
    gui.move(gui.vp_point(editor.width() + 400.0, y + 300.0))
    assert editor.textCursor().position() == length
    gui.move(gui.vp_point(-400.0, y - 300.0))
    assert editor.textCursor().position() == 0
    assert editor.textCursor().anchor() == 5
    gui.release(gui.vp_point(-400.0, y - 300.0))
    assert gui.view.text_editor is not None


@_UNROTATED
def test_overflowing_text_hit_test_follows_the_hidden_scroll(gui) -> None:
    """The hidden layout scrolls once the text overflows the fixed box; a press must
    hit the line under the pointer, not the line at the document origin."""
    editor = gui.open_editor()
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, " " + "overflow " * 14)
    _pump(150)
    scroll = editor.verticalScrollBar().value() + editor.horizontalScrollBar().value()
    assert scroll > 0, "precondition: the hidden layout scrolled"
    length = len(editor.toPlainText())
    before = gui.geometry()

    for local_x in (1.0, editor.width() / 2.0, float(editor.width() - 1)):
        y = editor.height() / 2.0
        gui.click(gui.vp_point(local_x, y))
        position = editor.textCursor().position()
        assert 0 <= position <= length
        probe = QTextCursor(editor.document())
        probe.setPosition(position)
        caret_y = editor.cursorRect(probe).center().y()
        assert abs(caret_y - y) <= editor.cursorRect(probe).height(), (local_x, caret_y, y)
        assert position > 0, "a press on the scrolled line must not land on line 0"
    assert gui.geometry() == before


@_UNROTATED
def test_double_click_inside_the_box_selects_a_word_and_it_survives_release(gui) -> None:
    editor = gui.open_editor()
    before = gui.geometry()
    gui.press(gui.vp_char(2))
    gui.release(gui.vp_char(2))
    QTest.mouseDClick(gui.viewport, Qt.LeftButton, Qt.NoModifier, gui.vp_char(2))
    _pump(200)
    assert editor.textCursor().selectedText() == "Alpha"
    assert gui.geometry() == before
    assert gui.view.text_editor is not None


@_UNROTATED
def test_right_click_inside_the_box_changes_nothing(gui, monkeypatch) -> None:
    monkeypatch.setattr(gui.view, "_show_context_menu", lambda *_a, **_k: None)
    monkeypatch.setattr(gui.view, "_show_context_menu_manual", lambda *_a, **_k: None)
    editor = gui.open_editor()
    gui.click(gui.vp_char(3))
    before = (gui.geometry(), editor.textCursor().position(), editor.textCursor().anchor())

    pos = gui.vp_char(8)
    QTest.mousePress(gui.viewport, Qt.RightButton, Qt.NoModifier, pos)
    QTest.mouseRelease(gui.viewport, Qt.RightButton, Qt.NoModifier, pos)
    _pump(200)

    assert gui.editor() is editor
    assert gui.view._text_edit_drag_state == TextEditDragState.IDLE
    assert (gui.geometry(), editor.textCursor().position(), editor.textCursor().anchor()) == before


# ------------------------------------------------------------------ composition policy


class _SpyInputMethod:
    """Stands in for ``QGuiApplication.inputMethod()``: a real platform IME commits
    the preedit into the focus object; the offscreen platform has none."""

    def __init__(self, editor, log: list[str], real) -> None:
        self._editor = editor
        self._log = log
        self._real = real

    def commit(self) -> None:
        self._log.append("commit")
        event = QInputMethodEvent("", [])
        event.setCommitString(self._editor.preedit_text())
        QApplication.sendEvent(self._editor, event)

    def update(self, *_a, **_k) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._real, name)


class _WindowsLikeInputMethod(_SpyInputMethod):
    """Windows: ``QPlatformInputContext::commit()`` is a no-op there; only ``reset()``
    (``QWindowsInputContext::reset``) sends the pending composition as a commit string."""

    def commit(self) -> None:
        self._log.append("commit")

    def reset(self) -> None:
        self._log.append("reset")
        event = QInputMethodEvent("", [])
        event.setCommitString(self._editor.preedit_text())
        QApplication.sendEvent(self._editor, event)


def _start_composing(editor, text: str = "xyz") -> None:
    QApplication.sendEvent(editor, QInputMethodEvent(text, []))
    assert editor.is_composing()


def _spy_input_method(editor, monkeypatch, spy_cls=_SpyInputMethod) -> list[str]:
    """Install a ``spy_cls`` instance (wrapping the real input method) as
    ``QGuiApplication.inputMethod()`` for ``editor``; returns the spy's call log."""
    log: list[str] = []
    spy = spy_cls(editor, log, QGuiApplication.inputMethod())
    monkeypatch.setattr(QGuiApplication, "inputMethod", staticmethod(lambda: spy))
    return log


@_UNROTATED
def test_an_in_box_press_while_composing_commits_the_composition_then_places_the_caret(
    gui, monkeypatch
) -> None:
    editor = gui.open_editor()
    editor.setFocus()
    log = _spy_input_method(editor, monkeypatch)
    _start_composing(editor)
    focus_outs: list[bool] = []
    editor.focus_out_requested.connect(lambda: focus_outs.append(True))

    point = gui.vp_char(2)  # laid out with the preedit at the start of the line
    scene = gui.view.graphics_view.mapToScene(point)
    gui.click(point)
    _pump(300)

    assert log == ["commit"], "the composition is committed exactly once, by the input method"
    assert editor.is_composing() is False
    assert gui.editor() is editor and gui.view.text_editor is not None
    assert focus_outs == []
    assert editor.toPlainText() == "xyz" + LINE, "the committed composition is kept"
    # (Committing BEFORE the caret moves is what put the text at the start: a commit
    # after the move would have inserted it at the clicked position.)  The caret then
    # goes where the pointer is in the post-commit layout; native QTextEdit is the oracle.
    local = gui.view.text_editor.mapFromScene(scene).toPoint()
    assert editor.textCursor().position() == editor.cursorForPosition(local).position()


@_UNROTATED
def test_an_in_box_press_resets_the_input_method_when_commit_is_a_no_op(gui, monkeypatch) -> None:
    """Windows ignores ``QInputMethod.commit()``: the policy falls back to ``reset()``."""
    editor = gui.open_editor()
    editor.setFocus()
    log = _spy_input_method(editor, monkeypatch, _WindowsLikeInputMethod)
    _start_composing(editor)

    gui.click(gui.vp_char(2))
    _pump(300)

    assert log == ["commit", "reset"]
    assert editor.is_composing() is False
    assert editor.toPlainText() == "xyz" + LINE, "the composition is committed, not dropped"


@_UNROTATED
def test_a_press_on_the_bar_or_outside_the_box_keeps_the_composition(gui, monkeypatch) -> None:
    """Round-4 behaviour (TODOS 46 item 4) is unchanged for everything but the box."""
    editor = gui.open_editor()
    editor.setFocus()
    log = _spy_input_method(editor, monkeypatch)
    _start_composing(editor)
    bar = gui.view.text_action_bar
    assert bar.isVisible()

    QTest.mouseClick(bar, Qt.LeftButton, Qt.NoModifier, QPoint(2, 2))
    _pump(150)
    # (Beside the box, not below it: the two-row bar (P1 live text strip) sits below.)
    outside = gui.vp_point(-40.0, editor.height() / 2.0)
    gui.click(outside)
    _pump(250)

    assert log == []
    assert gui.editor() is editor
    assert editor.is_composing() is True


# ------------------------------------------------------------------ the move grip


def _press_and_move(widget, start: QPoint, delta: QPoint, steps: int) -> tuple[QPointF, QPointF]:
    """Press ``widget`` at ``start`` and move by ``delta`` in ``steps`` with real mouse events,
    without a release.  Returns the local and global press points (for the release)."""
    local = QPointF(start)
    global_start = QPointF(widget.mapToGlobal(start))
    press = QMouseEvent(
        QEvent.MouseButtonPress, local, global_start, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    QApplication.sendEvent(widget, press)
    for step in range(1, steps + 1):
        offset = QPointF(delta.x() * step / steps, delta.y() * step / steps)
        move = QMouseEvent(
            QEvent.MouseMove,
            local + offset,
            global_start + offset,
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(widget, move)
        _pump(20)
    return local, global_start


def _drag_widget(widget, start: QPoint, delta: QPoint, steps: int = 5) -> None:
    """Press ``widget`` at ``start`` and drag by ``delta`` with real mouse events."""
    local, global_start = _press_and_move(widget, start, delta, steps)
    final = QPointF(delta)
    release = QMouseEvent(
        QEvent.MouseButtonRelease,
        local + final,
        global_start + final,
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, release)
    _pump(250)


def _press_and_move_without_release(widget, delta: QPoint, steps: int = 5) -> None:
    """The first half of ``_drag_widget``: the release is lost (a modal dialog swallowed it)."""
    _press_and_move(widget, widget.rect().center(), delta, steps)


def _drag_grip(view, delta: QPoint, steps: int = 5) -> None:
    """Drag the inline bar's move grip from its centre by ``delta`` pixels, press to release."""
    grip = view.text_action_bar.move_grip
    _drag_widget(grip, grip.rect().center(), delta, steps)


def _grip_global_centre(view) -> QPoint:
    """The move grip's centre in global pixels: what the view's grip slots are fed."""
    grip = view.text_action_bar.move_grip
    return grip.mapToGlobal(grip.rect().center())


def _type_x_and_wait_for_token(gui, editor) -> None:
    """Type one character and wait for the plan preview to verify it: a token exists and
    nothing is refused (the precondition of every drag-after-typing test)."""
    editor.setFocus()
    _pump(100)
    QTest.keyClick(editor, Qt.Key_X)
    _pump(100)
    _wait_until(lambda: editor.current_plan_token() is not None, 10)
    assert editor.current_plan_token() is not None, "precondition: a plan token exists after typing"
    _pump(300)
    assert gui.reason() is None, "precondition: the typed edit verifies before any drag"


def _settle_reason(gui, timeout_s: float = 15.0):
    """The rejection reason once the preview has had up to ``timeout_s`` to clear it."""
    _wait_until(lambda: gui.reason() is None, timeout_s)
    _pump(300)
    return gui.reason()


def _consent_to_rebuild(gui) -> None:
    """Answer the rebuild consent with yes and click the rebuild button; waits for the
    editor to close."""
    gui.controller._confirm_legacy_fallback = lambda *_a, **_k: True
    rebuild = gui.view.text_rebuild_btn
    assert rebuild.isEnabled() and not rebuild.isHidden(), "precondition: rebuild consent is offered"
    QTest.mouseClick(rebuild, Qt.LeftButton, Qt.NoModifier, rebuild.rect().center())
    _wait_until(lambda: gui.view.text_editor is None, 15)
    _pump(250)


def _open_add_text_box(gui, page_dx: float, page_dy: float):
    """Switch to add_text and click ``(page_dx, page_dy)`` scene px from the top-left of
    page 1; returns the opened editor."""
    gui.view.set_mode("add_text")
    _pump(100)
    gui.click(
        gui.view.graphics_view.mapFromScene(
            QPointF(gui.view._page_scene_x(0) + page_dx, gui.view._page_scene_y(0) + page_dy)
        )
    )
    _pump(300)
    editor = gui.editor()
    assert editor is not None, "a click on the page in add_text mode opens an editor"
    return editor


def _scene_origin(gui) -> QPointF:
    return QPointF(gui.view._page_scene_x(0), gui.view._page_scene_y(0))


@_ALL_ROTATIONS
@pytest.mark.parametrize("axis", ["x", "y"])
def test_move_grip_drag_moves_the_editor(gui, axis) -> None:
    """Round 7 / ROT: the proxy pos and editing_rect follow the grip on every /Rotate."""
    editor = gui.open_editor()
    grip = gui.view.text_action_bar.move_grip
    assert isinstance(grip, EditorMoveGrip)
    assert grip.isVisible()
    pos_before, rect_before = gui.geometry()
    scale = gui.view._render_scale
    delta = QPoint(20, 0) if axis == "x" else QPoint(0, 20)

    _drag_widget(grip, grip.rect().center(), delta)

    pos_after, rect_after = gui.geometry()
    assert gui.editor() is editor, "moving is not an apply or a cancel"
    assert pos_after.x() == pytest.approx(pos_before.x() + delta.x(), abs=1.01)
    assert pos_after.y() == pytest.approx(pos_before.y() + delta.y(), abs=1.01)
    assert rect_after.x0 == pytest.approx(rect_before.x0 + delta.x() / scale, abs=1.2 / scale)
    assert rect_after.y0 == pytest.approx(rect_before.y0 + delta.y() / scale, abs=1.2 / scale)
    assert rect_after.width == pytest.approx(rect_before.width, abs=0.01)
    assert rect_after.height == pytest.approx(rect_before.height, abs=0.01)
    _wait_until(lambda: gui.reason() == "geometry_override_present", 15)
    assert gui.reason() == "geometry_override_present", "a moved box needs a rebuild: the feature is kept"
    assert gui.view._drag_active is False
    assert gui.view._text_edit_drag_state == TextEditDragState.IDLE


@_ALL_ROTATIONS
def test_the_proxy_box_is_at_editing_rect_at_open_and_after_a_grip_move(gui) -> None:
    """M1(ii): the rotated proxy's scene top-left equals page origin + editing_rect.tl * rs,
    checked against Qt's own transform (not against the helper that computed the position)."""
    gui.open_editor()
    scale = gui.view._render_scale

    def assert_box_at_rect() -> None:
        box = gui.view.text_editor.sceneBoundingRect()
        origin = _scene_origin(gui)
        rect = gui.view.editing_rect
        assert box.left() == pytest.approx(origin.x() + rect.x0 * scale, abs=1.0)
        assert box.top() == pytest.approx(origin.y() + rect.y0 * scale, abs=1.0)
        assert box.right() == pytest.approx(origin.x() + rect.x1 * scale, abs=1.5)
        assert box.bottom() == pytest.approx(origin.y() + rect.y1 * scale, abs=1.5)

    assert_box_at_rect()
    _drag_grip(gui.view, QPoint(37, 23))
    assert gui.view.editing_rect != gui.view._editing_original_rect, "precondition: the box moved"
    assert_box_at_rect()


@_ALL_ROTATIONS
def test_a_small_first_grip_move_never_jumps_the_box(gui) -> None:
    """The first mouse move used to clamp the rotated box as if pos were its top-left:
    a 2 px drag moved a /Rotate 90 box 52 px and a /Rotate 180 box 89 px."""
    gui.open_editor()
    pos_before, _rect = gui.geometry()

    _drag_grip(gui.view, QPoint(2, 0), steps=1)

    pos_after, _rect = gui.geometry()
    assert abs(pos_after.x() - pos_before.x() - 2.0) <= 1.0
    assert abs(pos_after.y() - pos_before.y()) <= 1.0


@_ALL_ROTATIONS
@pytest.mark.parametrize("direction", ["left", "right", "up", "down"])
def test_grip_drag_clamps_the_rotated_box_inside_the_page(gui, direction) -> None:
    """The visual box (not pos) is kept inside the page, and reaches the page edge."""
    gui.open_editor()
    far = {"left": QPoint(-3000, 0), "right": QPoint(3000, 0), "up": QPoint(0, -3000), "down": QPoint(0, 3000)}
    _drag_grip(gui.view, far[direction], steps=6)

    box = gui.view.text_editor.sceneBoundingRect()
    page = gui.view._get_page_scene_rect(0)
    assert page.adjusted(-1, -1, 1, 1).contains(box), (box, page)
    if direction == "left":
        assert box.left() == pytest.approx(page.left(), abs=1.0)
    elif direction == "right":
        assert box.right() == pytest.approx(page.right(), abs=1.0)
    elif direction == "up":
        assert box.top() == pytest.approx(page.top(), abs=1.0)
    else:
        assert box.bottom() == pytest.approx(page.bottom(), abs=1.0)


@_ALL_ROTATIONS
def test_grip_round_trip_restores_editing_rect_on_rotated_pages(gui) -> None:
    gui.open_editor()
    scale = gui.view._render_scale
    _pos, rect_open = gui.geometry()

    _drag_grip(gui.view, QPoint(30, 30))
    _drag_grip(gui.view, QPoint(-30, -30))

    _pos, rect_back = gui.geometry()
    assert rect_back.x0 == pytest.approx(rect_open.x0, abs=1.2 / scale)
    assert rect_back.y0 == pytest.approx(rect_open.y0, abs=1.2 / scale)


@_ALL_ROTATIONS
def test_grip_out_and_back_to_the_open_position_restores_the_exact_rect_and_keeps_apply(gui) -> None:
    """B1: the inverse from the rounded proxy pixel left editing_rect ~0.05 pt off the
    original, which the 0.01 pt ``_emit`` threshold turned into ``new_rect`` and the model
    refused as ``geometry_override_present``.  A box dropped back on its open position is
    not a move: the rect is the original, byte for byte, and the preview verifies again."""
    editor = gui.open_editor()
    _type_x_and_wait_for_token(gui, editor)
    open_pos, _rect = gui.geometry()
    original = fitz.Rect(gui.view._editing_original_rect)

    _drag_grip(gui.view, QPoint(30, 30))
    _drag_grip(gui.view, QPoint(-30, -30))

    back_pos, rect_back = gui.geometry()
    assert (back_pos - open_pos).manhattanLength() < 0.5, "precondition: the proxy is back on its open pixel"
    assert tuple(rect_back) == tuple(original), "back on the open position: exactly the original rect"
    assert _settle_reason(gui) is None
    assert gui.view._ensure_text_edit_manager().apply_permitted() is True
    assert gui.view.text_apply_btn.isEnabled()


@_ALL_ROTATIONS
def test_grip_out_and_a_little_back_keeps_the_inverse_rect(gui) -> None:
    """B1 guard: the exact-restore snap only applies on the open pixel; 3 px away is a move."""
    gui.open_editor()
    scale = gui.view._render_scale
    original = fitz.Rect(gui.view._editing_original_rect)
    _drag_grip(gui.view, QPoint(30, 30))
    _drag_grip(gui.view, QPoint(-27, -30))

    _pos, rect_now = gui.geometry()
    assert rect_now != original
    assert abs(rect_now.x0 - original.x0) + abs(rect_now.x1 - original.x1) + abs(rect_now.y0 - original.y0) + abs(
        rect_now.y1 - original.y1
    ) > 1.0 / scale


# R7-INT-2: (rotation, PDF x).  On a /Rotate 180 page PDF x = 20 is the visual RIGHT edge; PDF
# x = 560 there is the visual left (a no-clamp control).
_EDGE_CASES = [(0, 560), (180, 20), (0, 20), (180, 560)]
_EDGE_CASE_IDS = ["rot0_right_edge", "rot180_right_edge", "rot0_left_control", "rot180_left_control"]


@pytest.mark.parametrize("gui_edge", _EDGE_CASES, indirect=True, ids=_EDGE_CASE_IDS)
def test_a_vertical_first_grip_move_near_the_right_edge_never_jumps_x(gui_edge) -> None:
    """R7-INT-2: the 80 px minimum-width editor of a short run near the right page edge opens
    hanging past the page.  The clamp measured that whole box, so the first 1 px (even purely
    vertical) move shoved it 28 px left and ``editing_rect`` followed.  Only the source span has
    to stay on the page; the minimum-width padding may hang over the edge."""
    gui_edge.open_editor()
    pos_before, rect_before = gui_edge.geometry()

    _drag_grip(gui_edge.view, QPoint(0, 5), steps=1)

    pos_after, rect_after = gui_edge.geometry()
    assert abs(pos_after.x() - pos_before.x()) <= 1.0, (
        f"x jumped {pos_after.x() - pos_before.x():+.1f} px (rect.x0 {rect_before.x0:.2f} -> {rect_after.x0:.2f})"
    )
    assert abs(rect_after.x0 - rect_before.x0) <= 1.0 / gui_edge.view._render_scale


@pytest.mark.parametrize("gui_edge", _EDGE_CASES, indirect=True, ids=_EDGE_CASE_IDS)
def test_out_and_back_to_the_open_spot_near_the_right_edge_restores_the_rect_and_apply(gui_edge) -> None:
    """R7-INT-2: the clamp held the box 28 px short of its open spot, so the B1 restore could never
    fire and ``geometry_override_present`` kept Apply disabled until Escape (losing the text)."""
    editor = gui_edge.open_editor()
    view = gui_edge.view
    _type_x_and_wait_for_token(gui_edge, editor)
    original = fitz.Rect(view._editing_original_rect)

    _drag_grip(view, QPoint(0, 30))
    _drag_grip(view, QPoint(0, -30))

    _pos, rect_back = gui_edge.geometry()
    assert tuple(rect_back) == tuple(original), f"x0 {rect_back.x0:.3f} vs the open {original.x0:.3f}"
    assert _settle_reason(gui_edge) is None
    assert view._ensure_text_edit_manager().apply_permitted() is True
    assert view.text_apply_btn.isEnabled()


@pytest.mark.parametrize("gui_edge", [(0, 560), (180, 20)], indirect=True, ids=["rot0", "rot180"])
def test_dragging_to_the_right_edge_keeps_the_source_span_on_the_page(gui_edge) -> None:
    """R7-INT-2 guard: the clamp still bites, at the SOURCE SPAN.  A far-right drag lands the span's
    right edge on the page edge (the padding hangs over) and never past it."""
    gui_edge.open_editor()
    view = gui_edge.view
    _drag_grip(view, QPoint(3000, 0), steps=6)

    _pos, rect = gui_edge.geometry()
    page_w = view.controller.get_page_rect(0).width
    assert rect.x1 <= page_w + 0.5 / view._render_scale
    assert rect.x1 == pytest.approx(page_w, abs=1.5 / view._render_scale)
    assert view.text_editor.sceneBoundingRect().right() > view._get_page_scene_rect(0).right(), (
        "the padded box hangs over the page edge; only the span is held inside"
    )


_BOTTOM_CASES = [(0, 8), (180, 776)]


@pytest.mark.parametrize("gui_bottom", _BOTTOM_CASES, indirect=True, ids=["rot0", "rot180"])
def test_out_and_back_to_the_open_spot_near_the_bottom_edge_restores_the_rect_and_apply(gui_bottom) -> None:
    """R3-INT-1: a paragraph editor at 0/180 is taller than its source span (the measuring document
    adds margin and wraps at the span width).  Near the page bottom it opens hanging past the page.
    The clamp subtracted the horizontal padding only (R7-INT-2), so the first grip move, even a
    1 px horizontal one, shoved the box up by the whole hang and its open spot became unreachable:
    ``editing_rect.y0`` drifted, ``geometry_override_present`` kept Apply disabled.  Only the SOURCE
    SPAN has to stay on the page; the excess height may hang over the bottom edge."""
    view = gui_bottom.view
    view.zoom_combo.setCurrentText("50%")
    _pump(1500)
    rs = view._render_scale
    editor = gui_bottom.open_editor()
    _type_x_and_wait_for_token(gui_bottom, editor)
    original = fitz.Rect(view._editing_original_rect)
    pos_open = QPointF(view.text_editor.pos())
    hang_px = view.text_editor.sceneBoundingRect().bottom() - view._get_page_scene_rect(0).bottom()
    assert hang_px > 0.5, f"precondition: the open box hangs {hang_px:.2f} scene px past the page bottom"

    _drag_grip(view, QPoint(1, 0), steps=1)
    _drag_grip(view, QPoint(-1, 0), steps=1)

    pos_back, rect_back = gui_bottom.geometry()
    assert abs(pos_back.y() - pos_open.y()) <= 1.0, (
        f"the box did not return to its open spot: dy {pos_back.y() - pos_open.y():+.2f} px"
    )
    assert abs(rect_back.y0 - original.y0) <= 0.5 / rs
    assert tuple(rect_back) == tuple(original), f"y0 {rect_back.y0:.3f} vs the open {original.y0:.3f}"
    assert _settle_reason(gui_bottom) is None
    assert view._ensure_text_edit_manager().apply_permitted() is True
    assert view.text_apply_btn.isEnabled()


@pytest.mark.parametrize("gui_bottom", _BOTTOM_CASES, indirect=True, ids=["rot0", "rot180"])
def test_dragging_a_paragraph_to_the_bottom_edge_keeps_the_source_span_on_the_page(gui_bottom) -> None:
    """R3-INT-1 guard: the vertical clamp still bites, at the SOURCE SPAN.  A far-down drag lands the
    span's bottom on the page bottom (the excess height hangs over) and never past it."""
    view = gui_bottom.view
    view.zoom_combo.setCurrentText("50%")
    _pump(1500)
    gui_bottom.open_editor()
    _drag_grip(view, QPoint(0, 3000), steps=6)

    _pos, rect = gui_bottom.geometry()
    page_h = view.controller.get_page_rect(0).height
    assert rect.y1 <= page_h + 0.5 / view._render_scale
    assert rect.y1 == pytest.approx(page_h, abs=1.5 / view._render_scale)


_TOP_CROSSING_CASES = [(0, 787), (180, 1)]
_TOP_CROSSING_IDS = ["rot0", "rot180"]


@pytest.mark.parametrize("gui_top_crossing", _TOP_CROSSING_CASES, indirect=True, ids=_TOP_CROSSING_IDS)
def test_a_horizontal_first_grip_move_of_a_span_crossing_the_page_top_never_jumps_y(gui_top_crossing) -> None:
    """R7-DEG-1: the span's own bbox crosses the page top (it is built from font metrics and never
    clipped), so the proxy opens above the page.  The clamp pulled the whole box down to the page
    top on the first move, even a purely horizontal one (about 6 px at baseline 5).  The open
    position is part of the allowed region: a move may never be forced off it by the clamp."""
    gui = gui_top_crossing
    view = gui.view
    gui.open_editor()
    original = fitz.Rect(view._editing_original_rect)
    assert original.y0 < -1.0, f"precondition: the span bbox crosses the page top (y0 {original.y0:.3f})"
    pos_before, rect_before = gui.geometry()

    _drag_grip(view, QPoint(5, 0), steps=1)

    pos_after, rect_after = gui.geometry()
    assert abs(pos_after.y() - pos_before.y()) <= 1.0, (
        f"y jumped {pos_after.y() - pos_before.y():+.1f} px (rect.y0 {rect_before.y0:.2f} -> {rect_after.y0:.2f})"
    )
    assert abs(rect_after.y0 - rect_before.y0) <= 1.0 / view._render_scale


@pytest.mark.parametrize("gui_top_crossing", _TOP_CROSSING_CASES, indirect=True, ids=_TOP_CROSSING_IDS)
def test_out_and_back_to_the_open_spot_of_a_span_crossing_the_page_top_restores_the_rect_and_apply(
    gui_top_crossing,
) -> None:
    """R7-DEG-1: an out-and-back grip gesture is harmless (B1 / R7-INT-1) only when the open spot is
    reachable.  For a span whose bbox crosses the page top the clamp held the page top, so the drop
    stayed ~6 px off the open spot: ``editing_rect != _editing_original_rect``, the settled reason
    was ``geometry_override_present`` and Apply was disabled."""
    gui = gui_top_crossing
    view = gui.view
    gui.open_editor()
    original = fitz.Rect(view._editing_original_rect)
    assert original.y0 < -1.0, f"precondition: the span bbox crosses the page top (y0 {original.y0:.3f})"
    assert gui.reason() is None, "precondition: the untouched editor verifies"
    open_pos, _rect = gui.geometry()

    _drag_grip(view, QPoint(5, 0), steps=1)
    _drag_grip(view, QPoint(-5, -20))

    back_pos, rect_back = gui.geometry()
    assert (back_pos - open_pos).manhattanLength() < 0.5, f"the box is {back_pos - open_pos} off its open spot"
    assert tuple(rect_back) == tuple(original), f"y0 {rect_back.y0:.3f} vs the open {original.y0:.3f}"
    assert not _editing_position_changed(view)
    assert _settle_reason(gui) != "geometry_override_present"
    assert gui.reason() is None
    assert view._ensure_text_edit_manager().apply_permitted() is True
    assert view.text_apply_btn.isEnabled()


@pytest.mark.parametrize("gui_top_crossing", [(0, 787)], indirect=True, ids=["rot0"])
def test_dragging_a_page_top_crossing_span_up_stops_at_its_open_spot_and_down_at_the_page_bottom(
    gui_top_crossing,
) -> None:
    """R7-DEG-1 guard: the allowed region is the page UNION the open spot, no more.  A far-up drag
    stops on the open spot (never further above the page); a far-down drag still lands the box on
    the page bottom."""
    gui = gui_top_crossing
    view = gui.view
    gui.open_editor()
    original = fitz.Rect(view._editing_original_rect)
    rs = view._render_scale
    assert original.y0 < -1.0, f"precondition: the span bbox crosses the page top (y0 {original.y0:.3f})"

    _drag_grip(view, QPoint(0, -3000), steps=6)
    _pos, rect_up = gui.geometry()
    assert rect_up.y0 >= original.y0 - 0.5 / rs, f"went above the open spot: {rect_up.y0:.3f} < {original.y0:.3f}"

    _drag_grip(view, QPoint(0, 3000), steps=6)
    _pos, rect_down = gui.geometry()
    page_h = view.controller.get_page_rect(0).height
    assert rect_down.y1 <= page_h + 0.5 / rs
    assert rect_down.y1 == pytest.approx(page_h, abs=1.5 / rs)


def test_grip_one_px_off_the_open_spot_at_214_percent_is_not_a_move_and_keeps_apply(gui) -> None:
    """R7-INT-1: grip drags move in whole scene pixels, so at 214 % one pixel is 0.467 pt.  That
    is inside the 0.5 pt ``POSITION_CHANGE_TOLERANCE_PT`` that finalize / ``apply_permitted`` use
    (NOT a move), yet above the 0.5 px B1 snap and the 0.01 pt ``_emit`` threshold, so the preview
    was refused (geometry_override_present), Apply was disabled and the consented rebuild then
    dropped the move.  One chokepoint: a drop inside the point tolerance restores the open rect AND
    the open proxy position (box and commit agree), so the exact preview verifies again."""
    view = gui.view
    view.zoom_combo.setCurrentText("214%")
    _pump(1500)
    assert view._render_scale == pytest.approx(2.14, abs=1e-6), "precondition: 214 % zoom applied"

    editor = gui.open_editor()
    _type_x_and_wait_for_token(gui, editor)
    assert view._ensure_text_edit_manager().apply_permitted() is True
    open_pos, _rect = gui.geometry()
    original = fitz.Rect(view._editing_original_rect)

    _drag_grip(view, QPoint(30, 30))
    _drag_grip(view, QPoint(-29, -30))  # one pixel short of the open spot

    assert not _editing_position_changed(view), "precondition: inside the 0.5 pt move tolerance"
    back_pos, rect_back = gui.geometry()
    assert tuple(rect_back) == tuple(original), "a sub-tolerance drop is the open rect, byte for byte"
    assert (back_pos - open_pos).manhattanLength() < 0.5, "the box sits on the open spot: box here = commit here"
    assert _settle_reason(gui) != "geometry_override_present"
    assert gui.reason() is None
    assert view._ensure_text_edit_manager().apply_permitted() is True
    assert view.text_apply_btn.isEnabled()


@_ALL_ROTATIONS
@pytest.mark.parametrize("net_px", [1, 2])
def test_grip_one_or_two_px_off_the_open_spot_is_a_move_not_a_snap(gui, net_px) -> None:
    """TV-2: the B1 snap tolerance (0.5 px) is pinned from both sides.  A box left 1-2 px
    from its open spot (above the tolerance, below the old 3 px guard) is a deliberate nudge:
    ``editing_rect`` keeps the displaced inverse (so Apply sees ``new_rect`` and asks for the
    rebuild) and the origin patch stays visible over the source glyphs.  A tolerance raised
    to ~2.5 px snaps these back to the original: box here, commit there.  (Render scale 1.0 here:
    1 px = 1 pt > 0.5 pt.  At >= 200 % one pixel is inside the point tolerance and IS snapped:
    R7-INT-1.)"""
    gui.open_editor()
    original = fitz.Rect(gui.view._editing_original_rect)
    open_pos, _rect = gui.geometry()
    _drag_grip(gui.view, QPoint(30, 30))
    _drag_grip(gui.view, QPoint(-(30 - net_px), -30))

    pos_now, rect_now = gui.geometry()
    assert (pos_now - open_pos).manhattanLength() >= net_px - 0.5, "precondition: the proxy is displaced"
    assert rect_now != original, "editing_rect snapped back to the open rect although the box was nudged"
    patch = getattr(gui.view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.isVisible(), "origin patch hidden although the box left its spot"


@_ALL_ROTATIONS
def test_a_rotated_grip_move_lands_where_the_box_was_dropped_and_survives_save_reopen(gui, tmp_path) -> None:
    """M2: not only "the maths inverts itself": the rebuilt text's anchor (the first-line
    top-left of its ink, in the unrotated frame) really moves by the drag on a /Rotate page,
    in memory and after save + reopen of a COPY.  This does NOT claim the rebuilt run looks
    unchanged: the rebuild re-wraps the synthetic one-line run onto two lines (rotation 0
    too; a TODOS item tracks it), so only the anchor is compared."""
    gui.open_editor()
    scale = gui.view._render_scale
    delta = QPoint(40, 30)

    def unrotated_ink(page: fitz.Page) -> fitz.Rect:
        # The rebuild re-wraps the line in the page's UNROTATED frame (the synthetic
        # Helvetica run comes back narrower and two lines tall, at rotation 0 as well), so
        # the size of the ink is not comparable; its first-line top-left corner is.
        return _ink_bbox(page) * page.derotation_matrix

    derot = gui.model.doc[0].derotation_matrix
    expected = fitz.Point(delta.x() / scale, delta.y() / scale) * fitz.Matrix(derot.a, derot.b, derot.c, derot.d, 0, 0)
    origin_before = unrotated_ink(gui.model.doc[0])

    _drag_grip(gui.view, delta)

    _wait_until(lambda: gui.reason() == "geometry_override_present", 15)
    assert gui.reason() == "geometry_override_present", "precondition: a moved box needs the rebuild"
    _consent_to_rebuild(gui)
    assert gui.view.text_editor is None, "the rebuild apply closed the editor"

    def assert_shifted(page: fitz.Page) -> None:
        origin_after = unrotated_ink(page)
        assert origin_after.x0 - origin_before.x0 == pytest.approx(expected.x, abs=1.5)
        assert origin_after.y0 - origin_before.y0 == pytest.approx(expected.y, abs=1.5)

    assert_shifted(gui.model.doc[0])
    copy = tmp_path / "moved_copy.pdf"
    gui.model.save_as(str(copy))
    reopened = fitz.open(str(copy))
    try:
        assert reopened[0].rotation == gui.rotation
        assert_shifted(reopened[0])
    finally:
        reopened.close()


# ------------------------------------------------------------------ round 7 / F1: the origin patch

_ORIGIN_PATCH_Z = 10.5
_RING_PX = 3


def _patch_items(view) -> list:
    """Scene items at the origin patch z value."""
    return [item for item in view.scene.items() if abs(item.zValue() - _ORIGIN_PATCH_Z) < 1e-9]


def _scene_pixels(view, scene_rect: QRectF) -> QImage:
    """Render ONLY the scene (no viewport children such as the inline bar) 1:1."""
    width = max(1, int(round(scene_rect.width())))
    height = max(1, int(round(scene_rect.height())))
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    view.scene.render(painter, QRectF(0, 0, width, height), scene_rect)
    painter.end()
    return image


def _deviating(image: QImage, rgb, tolerance: int = 2, skip: QRectF | None = None, origin=None) -> int:
    """Pixels whose channels differ from ``rgb`` by more than ``tolerance``.  ``skip`` (in the
    scene coordinates of ``origin`` = the image's top-left) is not counted."""
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if skip is not None and skip.contains(origin.x() + x + 0.5, origin.y() + y + 0.5):
                continue
            c = image.pixelColor(x, y)
            if (
                abs(c.red() - rgb[0]) > tolerance
                or abs(c.green() - rgb[1]) > tolerance
                or abs(c.blue() - rgb[2]) > tolerance
            ):
                count += 1
    return count


def _origin_page_colour(view, open_rect: QRectF):
    """The untinted ring mean of the page around ``open_rect``, sampled BEFORE any move
    (an independent computation of the colour the patch must have)."""
    sampled = view._ensure_text_edit_manager()._resolve_mask_sampling_context(open_rect)
    assert sampled is not None, "precondition: the page pixmap can be sampled at the editor"
    ring = _qimage_ring_mean_rgb(sampled[0], sampled[1], _MASK_RING_THICKNESS_PX)
    assert ring is not None
    return tuple(int(round(v)) for v in ring)


def _expected_origin_cover(view) -> QRectF:
    """The origin patch rect, computed from the SOURCE span (REG-1): the span's scene rect from
    ``_editing_original_rect`` + the glyph-overhang margin, snapped outward to whole pixels."""
    scene = _scene_rect_of(view, fitz.Rect(view._editing_original_rect), view._editing_origin_page_idx)
    margin = _origin_mask_margin_px(view)
    return QRectF(scene.adjusted(-margin, -margin, margin, margin).toAlignedRect())


def _grip_move_off_the_spot(view, rect: QRectF) -> None:
    """Drag the grip clear of the box's open spot, on both axes."""
    _drag_grip(view, QPoint(int(rect.width()) + 24, int(rect.height()) + 24))


@_GREY_ALL
def test_grip_move_hides_the_source_text_at_its_old_spot(gui_grey) -> None:
    """S17a: after a grip move the original glyphs stayed visible beside the moved box
    ("備備為C標新設。").  The spot must show the UNTINTED page colour (255), not the tinted
    mask (202), and no glyph sliver may remain in a 3 px ring around it (M3/M4)."""
    gui = gui_grey
    gui.open_editor()
    view = gui.view
    metrics = gui.editor().property("mask_debug_metrics")
    assert metrics["tint_strength"] > 0, "precondition: grey text makes the moving mask a tinted grey"
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    page_rgb = _origin_page_colour(view, open_rect)
    assert min(page_rgb) >= 250, "precondition: the synthetic page is white"
    inner = open_rect.adjusted(1, 1, -1, -1)
    assert _deviating(_scene_pixels(view, inner), page_rgb) > 0, "precondition: the frozen frame shows glyphs"

    _grip_move_off_the_spot(view, open_rect)

    moved = QRectF(view.text_editor.sceneBoundingRect()).adjusted(-3, -3, 3, 3)
    assert not moved.intersects(open_rect.adjusted(-_RING_PX, -_RING_PX, _RING_PX, _RING_PX)), (
        "precondition: the box left its spot",
        moved,
        open_rect,
    )
    assert _deviating(_scene_pixels(view, inner), page_rgb) == 0, "the source glyphs show through"
    centre = _scene_pixels(view, open_rect).pixelColor(int(open_rect.width() / 2), int(open_rect.height() / 2))
    assert (centre.red(), centre.green(), centre.blue()) == pytest.approx(page_rgb, abs=2), "not the tinted 202"
    outer = open_rect.adjusted(-_RING_PX, -_RING_PX, _RING_PX, _RING_PX)
    ring_ink = _deviating(_scene_pixels(view, outer), page_rgb, skip=open_rect, origin=outer.topLeft())
    assert ring_ink == 0, "glyph slivers remain outside the open rect"


def _luma_stddev(image: QImage) -> float:
    """Population stddev of the luminance (r+g+b)/3 over every pixel of ``image``."""
    values = []
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            values.append((c.red() + c.green() + c.blue()) / 3.0)
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


@_STRIPES_UNROTATED
def test_origin_patch_is_not_painted_over_a_striped_background(gui_stripes) -> None:
    """RPU-2: the patch is one flat ring-mean colour, a grey block (131) across the stripes
    (std 0 inside vs ~80 around it).  A fake block is worse than the visible source text, so on
    a non-uniform ring no patch is drawn and the page raster (stripes + source glyphs) shows."""
    gui = gui_stripes
    gui.open_editor()
    view = gui.view
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    surround = open_rect.adjusted(-16, -16, 16, 16)
    surround_img = _scene_pixels(view, surround)
    assert _luma_stddev(surround_img) > 50.0, "precondition: the spot sits on a real stripe pattern"

    _grip_move_off_the_spot(view, open_rect)

    moved = QRectF(view.text_editor.sceneBoundingRect()).adjusted(-3, -3, 3, 3)
    assert not moved.intersects(open_rect), "precondition: the box left its spot"
    assert getattr(view, "_text_editor_origin_mask_item", None) is None, "no flat patch on a hatched ring"
    assert not _patch_items(view)
    inner = open_rect.adjusted(1, 1, -1, -1)
    assert _luma_stddev(_scene_pixels(view, inner)) > 50.0, "the stripes must show through, not a flat block"

    # A further grip move keeps it that way (the verdict is cached per page + span).
    _drag_grip(view, QPoint(10, 10))
    assert getattr(view, "_text_editor_origin_mask_item", None) is None


def test_ring_nonuniform_ratio_separates_flat_rings_from_hatching() -> None:
    """RPU-2: the ring measure behind the gate: 0 on a flat ring, ~1 on dense stripes, tiny when
    only a few glyph-overhang pixels poke into an otherwise flat ring (the ecc-dwg case)."""
    inner = QRect(10, 10, 20, 8)
    flat = QImage(40, 28, QImage.Format_RGBA8888)
    flat.fill(QColor(255, 255, 255))
    ring_mean = (255.0, 255.0, 255.0)
    assert _qimage_ring_nonuniform_ratio(flat, inner, _MASK_RING_THICKNESS_PX, ring_mean) == 0.0

    striped = QImage(flat)
    for x in range(striped.width()):
        if x % 2 == 0:
            for y in range(striped.height()):
                striped.setPixelColor(x, y, QColor(0, 0, 0))
    assert _qimage_ring_nonuniform_ratio(striped, inner, _MASK_RING_THICKNESS_PX, (127.5,) * 3) > 0.9

    sliver = QImage(flat)
    for x in range(12, 20):
        sliver.setPixelColor(x, 9, QColor(0, 0, 0))  # one overhang row of 8 px in a ~290 px ring
    ratio = _qimage_ring_nonuniform_ratio(sliver, inner, _MASK_RING_THICKNESS_PX, ring_mean)
    assert 0.0 < ratio < _ORIGIN_MASK_MAX_RING_NONUNIFORM_PCT

    assert _qimage_ring_nonuniform_ratio(flat, QRect(), _MASK_RING_THICKNESS_PX, ring_mean) == 0.0
    assert _qimage_ring_nonuniform_ratio(flat, inner, 0, ring_mean) == 0.0


def _reference_ring_nonuniform_ratio(image: QImage, inner_rect: QRect, ring_px: int, mean_rgb) -> float:
    """The original per-pixel definition (pixelColor loop) the vectorised version must match."""
    outer = inner_rect.adjusted(-ring_px, -ring_px, ring_px, ring_px).intersected(image.rect())
    inner = inner_rect.intersected(outer)
    total = outliers = 0
    for y in range(outer.top(), outer.bottom() + 1):
        for x in range(outer.left(), outer.right() + 1):
            if inner.contains(x, y):
                continue
            c = image.pixelColor(x, y)
            total += 1
            if abs(c.red() - mean_rgb[0]) + abs(c.green() - mean_rgb[1]) + abs(c.blue() - mean_rgb[2]) > 48.0:
                outliers += 1
    return outliers / total if total else 0.0


@pytest.mark.parametrize(
    "fmt, inner",
    [
        (QImage.Format_RGBA8888, QRect(10, 10, 20, 8)),
        (QImage.Format_RGBA8888, QRect(-2, 3, 14, 40)),  # ring clipped by the image edge
        (QImage.Format_ARGB32_Premultiplied, QRect(5, 5, 30, 12)),  # non-RGBA8888 source
    ],
)
def test_ring_nonuniform_ratio_matches_the_per_pixel_definition(fmt, inner) -> None:
    """PERF-1: the vectorised ring measure returns exactly what the pixelColor loop returned."""
    from view.text_editing import _MASK_RING_OUTLIER_L1

    assert _MASK_RING_OUTLIER_L1 == 48.0, "reference helper hard-codes the production threshold"
    img = QImage(40, 28, fmt)
    img.fill(QColor(250, 250, 250))
    for i, (x, y) in enumerate([(2, 2), (9, 9), (31, 10), (20, 19), (0, 27), (39, 0), (12, 9), (4, 20)]):
        img.setPixelColor(x, y, QColor(0, 10 * i, 255 - 20 * i))
    mean = (200.0, 190.0, 180.0)
    got = _qimage_ring_nonuniform_ratio(img, inner, _MASK_RING_THICKNESS_PX, mean)
    assert got == pytest.approx(_reference_ring_nonuniform_ratio(img, inner, _MASK_RING_THICKNESS_PX, mean))
    assert got > 0.0


@pytest.mark.parametrize("w, h", [(1500, 72), (4000, 192), (3600, 2000)])
def test_ring_nonuniform_ratio_cost_follows_the_ring_not_the_span_area(w: int, h: int) -> None:
    """PERF-1: it runs on the UI thread on the first grip-drag frame and on every re-render of
    the origin page.  A paragraph at zoom 4 / DPR 2 is millions of pixels but only a ~3 px ring
    matters: it must stay far under the 50 ms frame budget (the pixelColor loop took 0.5-0.9 s)."""
    img = QImage(w, h, QImage.Format_RGBA8888)
    img.fill(QColor(255, 255, 255))
    inner = QRect(3, 3, w - 6, h - 6)
    _qimage_ring_nonuniform_ratio(img, inner, _MASK_RING_THICKNESS_PX, (255.0, 255.0, 255.0))  # warm-up
    t0 = time.perf_counter()
    ratio = _qimage_ring_nonuniform_ratio(img, inner, _MASK_RING_THICKNESS_PX, (255.0, 255.0, 255.0))
    dt = time.perf_counter() - t0
    assert ratio == 0.0
    assert dt < 0.05, f"{w}x{h} ring measure took {dt * 1000:.1f} ms"


@_NEIGHBOUR_ALL
def test_origin_patch_covers_the_source_span_not_the_editor_widget(gui_neighbour) -> None:
    """REG-1: the editor widget is at least 80 px wide, the one-word run AB only ~19 px.  The
    origin patch must cover the SOURCE SPAN (plus the glyph-overhang margin), otherwise the
    neighbouring run on the same baseline disappears while the box is displaced."""
    gui = gui_neighbour
    view = gui.view
    page = gui.model.doc[0]

    def scene_rect(word: str) -> QRectF:
        return _scene_rect_of(view, page.search_for(word)[0] * page.rotation_matrix)

    span, neighbour = scene_rect("AB"), scene_rect("NEIGHBOUR")
    view.graphics_view.centerOn(span.center())
    _pump(80)
    neighbour_before = _scene_pixels(view, neighbour)
    assert _deviating(neighbour_before, (255, 255, 255), tolerance=60) > 0, "precondition: NEIGHBOUR has ink"
    QTest.mouseClick(
        gui.viewport, Qt.LeftButton, Qt.NoModifier, view.graphics_view.mapFromScene(span.center())
    )
    _wait_until(lambda: gui.editor() is not None, 10, step_ms=20)
    _pump(250)
    editor = gui.editor()
    assert isinstance(editor, PreviewBackedInlineTextEditor), "the click on AB must open the editor"
    widget_rect = QRectF(view.text_editor.sceneBoundingRect())
    if gui.rotation == 0:
        # Only the unrotated box has the min-width widget (80 px) that overlaps NEIGHBOUR; the
        # rotated rows are the regression guard that the span-sized cover also fits there.
        assert widget_rect.width() * widget_rect.height() > 2.0 * span.width() * span.height(), (
            "precondition: the widget is much larger than the source span",
            widget_rect,
            span,
        )
        assert widget_rect.intersects(neighbour), "precondition: the widget rect overlaps NEIGHBOUR"

    # Move perpendicular to the text direction: clear of NEIGHBOUR on every rotation.
    delta = QPoint(60, 0) if gui.rotation in (90, 270) else QPoint(0, 60)
    _drag_grip(view, delta)
    _pump(300)
    assert gui.editor() is editor
    moved = QRectF(view.text_editor.sceneBoundingRect())
    assert not moved.intersects(neighbour), "precondition: the moved box is clear of NEIGHBOUR"
    assert not moved.intersects(widget_rect), "precondition: the box left its spot"

    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.isVisible(), "precondition: a displaced box shows the patch"
    margin = _origin_mask_margin_px(view)
    cover = QRectF(patch.rect())
    assert cover.contains(span), "the patch must still cover the whole source span"
    assert cover.width() <= span.width() + 2 * margin + 2, (cover, span)
    assert cover.height() <= span.height() + 2 * margin + 2, (cover, span)
    assert _scene_pixels(view, neighbour) == neighbour_before, "NEIGHBOUR ink changed at its old spot"


def test_origin_mask_margin_scales_with_the_render_scale_literal() -> None:
    """Round 7 / TV-3: the margin is the 1.0 pt glyph overhang in SCENE pixels.  Literal
    expectations (no reuse of the production constant) so dropping the scale factor fails here."""

    class _View:
        def __init__(self, scale) -> None:
            self._render_scale = scale

    assert _origin_mask_margin_px(_View(1.0)) == pytest.approx(1.0)
    assert _origin_mask_margin_px(_View(2.14)) == pytest.approx(2.14)
    assert _origin_mask_margin_px(_View(4.0)) == pytest.approx(4.0)
    assert _origin_mask_margin_px(_View(0.5)) == pytest.approx(1.0), "never below one whole pixel"
    assert _origin_mask_margin_px(_View(None)) == pytest.approx(1.0), "no scale: 1 pixel"
    assert _origin_mask_margin_px(object()) == pytest.approx(1.0), "no scale attribute: 1 pixel"


def test_origin_patch_docs_state_the_real_overhang_not_a_flat_1_pt() -> None:
    """Round 7 round 2 / DOC-1: the cover is the span plus ``max(1 px, 1 pt * zoom)`` snapped OUTWARD
    to whole pixels, so each side overhangs by 1 to 2 SCENE pixels (1-2 pt at 100 %, 2-4 pt at 50 %).
    Four docs promised "up to 1 pt".  The snap and the 1 px floor are load-bearing (glyph ink and the
    span's edge pixel), so the docs, not the code, were wrong; this pins the docs to the real bound."""
    root = Path(__file__).resolve().parents[1]
    stale = {
        "docs/FEATURES.md": r"thin margin of up to 1 pt",
        "docs/PITFALLS.md": r"paints over up to 1 pt of neighbouring content",
        "TODOS.md": r"within 1 pt of\s+the span bbox",
        "docs/ARCHITECTURE.md": r"hide up to 1 pt of\s+neighbouring vector content",
    }
    for rel, pattern in stale.items():
        text = (root / rel).read_bytes().decode("utf-8", errors="replace")
        assert not re.search(pattern, text), f"{rel} still promises a flat 1 pt origin-patch margin"
    features = (root / "docs/FEATURES.md").read_text(encoding="utf-8-sig")
    assert re.search(r"1 to 2 (screen|scene) pixels|1 to 2 pt at 100 ?%", features), (
        "FEATURES.md must state the real per-side overhang of the origin patch"
    )


def test_origin_patch_comments_describe_the_source_span_not_the_open_rect() -> None:
    """Round 7 round 2 / DOC-4: after REG-1 the origin patch covers the SOURCE SPAN (plus the margin);
    the widget rect captured at open (``_editing_origin_scene_rect``) only drives the displacement test.
    Five comments/docstrings in view/text_editing.py kept saying the patch covers the OPEN rect, the
    design that erased a neighbouring run.  This pins them to the shipped behaviour."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "view/text_editing.py").read_bytes().decode("utf-8")
    stale = [line for line in source.splitlines() if re.search(r"(?:OPEN|open) rect", line)]
    assert not stale, "view/text_editing.py still describes the origin patch via the open rect: " + repr(stale)

    from view.text_editing import TextEditManager  # noqa: PLC0415

    sync_doc = TextEditManager.sync_text_editor_origin_mask.__doc__ or ""
    assert "source span" in sync_doc.lower(), "sync_text_editor_origin_mask docstring must name the source span"
    assert "displace" in sync_doc.lower()
    margin_doc = _origin_mask_margin_px.__doc__ or ""
    assert "source span" in margin_doc.lower()
    # The widget-rect comment must say it is NOT what gets covered.
    assert "NOT covered" in source


def test_rotated_move_docs_no_longer_list_the_fixed_limits_as_open() -> None:
    """Round 7 round 2 / DOC-2: ROT fixed the ``/Rotate`` clamp (``_proxy_visual_extent``) and the
    ``editing_rect`` derivation (``_proxy_corner_offset``), but three docs kept listing both as open
    known limitations (the round 6 bullet in the structure doc, the round 6 PITFALLS entry, and the
    task 13 follow-ups (a)/(b) in TODOS).  This pins the docs to the fix."""
    root = Path(__file__).resolve().parents[1]
    arch = (root / "docs/架構.txt").read_bytes().decode("utf-8", errors="replace")
    assert "已知限制：/Rotate" not in arch, "structure doc still lists the /Rotate limit as open"
    assert "_proxy_corner_offset" in arch and "_proxy_visual_extent" in arch

    pitfalls = (root / "docs/PITFALLS.md").read_bytes().decode("utf-8", errors="replace")
    assert "**Known limits (not fixed):** on `/Rotate` pages the grip" not in pitfalls, (
        "PITFALLS round 6 entry still lists the rotated clamp / editing_rect bugs as unfixed"
    )

    todos = (root / "TODOS.md").read_bytes().decode("utf-8", errors="replace")
    match = re.search(r"\(a\)\s+drag-end rect derivation.*?\(b\)\s+`_clamp_editor_pos_to_page`[^;]*;", todos, re.S)
    assert match, "TODOS task 13 follow-ups (a)/(b) not found"
    assert re.search(r"fixed (in )?round 7", match.group(0), re.I), (
        "TODOS follow-ups (a)/(b) must say the rotated move was fixed in round 7"
    )


def test_origin_patch_grows_the_span_by_the_scaled_overhang_at_214_percent(gui_grey) -> None:
    """Round 7 / TV-3: every other MVC fixture runs at render scale 1.0 and the 214 % ecc-dwg owner
    run is ``needs_fixtures`` (deselected in CI), so nothing CI-collected pinned the scale factor of
    the glyph-overhang margin.  The expectation is a LITERAL 1.0 pt * 2.14 = 2.14 px per side."""
    gui = gui_grey
    view = gui.view
    view.zoom_combo.setCurrentText("214%")
    _pump(1500)
    assert view._render_scale == pytest.approx(2.14, abs=1e-6), "precondition: 214 % zoom applied"

    gui.open_editor()
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    _grip_move_off_the_spot(view, open_rect)
    _pump(300)

    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.isVisible(), "precondition: a displaced box shows the patch"
    scene = _scene_rect_of(view, fitz.Rect(view._editing_original_rect), view._editing_origin_page_idx)
    grown = scene.adjusted(-2.14, -2.14, 2.14, 2.14)
    cover = QRectF(patch.rect())
    assert cover.contains(grown), ("the patch must cover the span grown by 2.14 px per side", cover, grown)
    assert cover == QRectF(grown.toAlignedRect()), "snapped outward to whole pixels, nothing more"


def test_origin_patch_overhang_is_one_to_two_scene_pixels_per_side_at_50_percent(gui_grey) -> None:
    """Round 7 round 2 / DOC-1: below 100 % the 1 scene px floor beats 1 pt (0.5 px) and the outward
    snap adds up to one more pixel, so a side overhangs by [1, 2) px = [2, 4) pt at 50 %.  Literal
    bounds: the documented contract; a tighter or looser cover must be a conscious change."""
    gui = gui_grey
    view = gui.view
    view.zoom_combo.setCurrentText("50%")
    _pump(1500)
    assert view._render_scale == pytest.approx(0.5, abs=1e-6), "precondition: 50 % zoom applied"

    gui.open_editor()
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    _grip_move_off_the_spot(view, open_rect)
    _pump(300)

    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.isVisible(), "precondition: a displaced box shows the patch"
    span = QRectF(view._editing_origin_span_scene_rect)
    cover = QRectF(patch.rect())
    sides = {
        "left": span.left() - cover.left(),
        "top": span.top() - cover.top(),
        "right": cover.right() - span.right(),
        "bottom": cover.bottom() - span.bottom(),
    }
    for name, overhang_px in sides.items():
        assert 1.0 - 1e-6 <= overhang_px < 2.0, (name, overhang_px, cover, span)
        assert 2.0 - 1e-6 <= overhang_px / view._render_scale < 4.0, (name, overhang_px)


@_GREY_UNROTATED
def test_grip_move_back_hides_the_origin_patch(gui_grey) -> None:
    gui = gui_grey
    gui.open_editor()
    view = gui.view
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    before = _scene_pixels(view, open_rect)
    _drag_grip(view, QPoint(0, 40))
    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.isVisible(), "a displaced box leaves the patch behind"
    _drag_grip(view, QPoint(0, -40))
    assert view.text_editor.sceneBoundingRect().topLeft() == open_rect.topLeft(), "precondition: back at the spot"

    assert view._text_editor_origin_mask_item is patch, "the item is kept, only hidden"
    assert not patch.isVisible()
    assert _scene_pixels(view, open_rect) == before


@_UNROTATED
def test_add_text_grip_move_leaves_no_origin_patch(gui) -> None:
    """GUARD (green before and after): add_text has nothing to hide at its old spot."""
    _open_add_text_box(gui, 200.0, 400.0)
    assert gui.view.editing_intent == "add_new"
    before = QPointF(gui.view.text_editor.pos())
    _drag_grip(gui.view, QPoint(0, 60))
    assert gui.view.text_editor.pos().y() > before.y() + 50, "precondition: the box moved"
    assert getattr(gui.view, "_text_editor_origin_mask_item", None) is None
    assert _patch_items(gui.view) == []


@_GREY_UNROTATED
def test_escape_after_a_grip_move_removes_the_origin_patch(gui_grey) -> None:
    gui = gui_grey
    gui.open_editor()
    view = gui.view
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    _grip_move_off_the_spot(view, open_rect)
    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.scene() is view.scene, "precondition: the patch is in the scene"
    manager = view._ensure_text_edit_manager()

    QTest.keyClick(gui.editor(), Qt.Key_Escape)
    _pump(300)

    assert view.text_editor is None
    assert view._text_editor_origin_mask_item is None
    assert patch.scene() is None
    assert [i for i in view.scene.items() if i.zValue() in (_ORIGIN_PATCH_Z, 11, 13)] == []
    assert manager._last_origin_mask_signature is None
    assert not hasattr(view, "_editing_origin_scene_rect")


@_GREY_UNROTATED
def test_scene_detach_takes_the_origin_patch_out_of_the_scene(gui_grey) -> None:
    gui = gui_grey
    gui.open_editor()
    view = gui.view
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    _grip_move_off_the_spot(view, open_rect)
    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.scene() is view.scene, "precondition: the patch is in the scene"
    items = [view.text_editor, view._text_editor_mask_item, view._text_editor_focus_border_item, patch]

    view._detach_text_editor_before_scene_clear()

    assert [item.scene() for item in items] == [None, None, None, None]
    view._ensure_text_edit_manager()._teardown_editor()
    assert view._text_editor_origin_mask_item is None


@_GREY_TWO_PAGES
def test_cross_page_grip_move_keeps_the_origin_page_covered(gui_grey_two_pages) -> None:
    gui = gui_grey_two_pages
    view = gui.view
    assert view.continuous_pages and len(view.page_y_positions) == 2, "precondition: continuous, 2 pages"
    gui.open_editor()
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    page_rgb = _origin_page_colour(view, open_rect)
    rs = view._render_scale
    dest_y = view.page_y_positions[1] + 72 * rs
    _drag_grip(view, QPoint(0, int(dest_y - open_rect.center().y())), steps=6)

    assert view._editing_page_idx == 1 and view._editing_origin_page_idx == 0
    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.isVisible()
    cover = _expected_origin_cover(view)
    assert cover.contains(open_rect.adjusted(1, 1, -1, -1)), "precondition: the span is the open rect here"
    assert (patch.rect().x(), patch.rect().y(), patch.rect().width(), patch.rect().height()) == pytest.approx(
        (cover.x(), cover.y(), cover.width(), cover.height()), abs=0.01
    )
    assert view._text_editor_mask_item.rect().top() >= view.page_y_positions[1], "the moving mask is on page 2"
    inner = open_rect.adjusted(1, 1, -1, -1)
    assert _deviating(_scene_pixels(view, inner), page_rgb) == 0

    # M5: a re-render of the ORIGIN page resamples the patch from the new page pixmap.
    page_pixmap = view.page_items[0].pixmap()
    yellow = QPixmap(page_pixmap.size())
    yellow.fill(QColor(255, 250, 200))
    view.update_page_in_scene(0, yellow)
    colour = patch.brush().texture().toImage().pixelColor(0, 0)
    assert (colour.red(), colour.green(), colour.blue()) == pytest.approx((255, 250, 200), abs=2)


@_GREY_UNROTATED
def test_a_refused_zoom_keeps_the_origin_patch(gui_grey) -> None:
    """M7: a moved box refuses VIEW_RESCALE (editor kept, scene not rebuilt): the patch stays."""
    gui = gui_grey
    gui.open_editor()
    view = gui.view
    open_rect = QRectF(view.text_editor.sceneBoundingRect())
    _grip_move_off_the_spot(view, open_rect)
    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.scene() is view.scene, "precondition: the patch is in the scene"
    rect_before = QRectF(patch.rect())

    assert view.release_text_editor_for_rescale() is False

    assert view.text_editor is not None
    assert view._text_editor_origin_mask_item is patch and patch.scene() is view.scene
    assert patch.isVisible() and patch.rect() == rect_before


@_GREY_UNROTATED
def test_a_committed_move_removes_the_origin_patch(gui_grey) -> None:
    """M6(i): the rebuild-consent apply re-renders the page and tears the patch down."""
    gui = gui_grey
    gui.open_editor()
    view = gui.view
    _drag_grip(view, QPoint(40, 30))
    patch = getattr(view, "_text_editor_origin_mask_item", None)
    assert patch is not None and patch.scene() is view.scene, "precondition: the patch is in the scene"
    _wait_until(lambda: gui.reason() == "geometry_override_present", 15)
    _consent_to_rebuild(gui)

    assert view.text_editor is None
    assert view._text_editor_origin_mask_item is None
    assert _patch_items(view) == []


@_UNROTATED
def test_move_grip_contract(gui) -> None:
    editor = gui.open_editor()
    bar = gui.view.text_action_bar
    grip = bar.move_grip
    assert grip.testAttribute(Qt.WA_NoMousePropagation)
    assert grip.focusPolicy() == Qt.NoFocus
    assert "移動" in grip.text()
    assert "重建" in grip.toolTip()
    assert grip.cursor().shape() == Qt.OpenHandCursor
    assert grip.parent() is bar
    assert grip.geometry().left() < bar.apply_btn.geometry().left(), "the grip leads the controls"
    # A press on the grip is not a click-away: it neither finalizes nor steals focus.
    editor.setFocus()
    assert editor.hasFocus(), "precondition: the editor holds the focus"
    generation = editor._plan_generation
    _drag_widget(grip, grip.rect().center(), QPoint(0, 0), steps=1)
    assert gui.editor() is editor
    assert editor.hasFocus()
    assert editor._plan_generation == generation, "a grip click without movement is not a move"
    assert gui.view._text_edit_drag_state == TextEditDragState.IDLE


@_UNROTATED
def test_move_grip_is_hidden_when_no_editor_is_live(gui) -> None:
    gui.open_editor()
    grip = gui.view.text_action_bar.move_grip
    assert grip.isVisible()
    QTest.keyClick(gui.editor(), Qt.Key_Escape)
    _pump(300)
    assert gui.view.text_editor is None
    assert not grip.isVisible()


def test_a_grip_press_with_a_stale_latch_starts_a_new_drag(qapp) -> None:
    """SEQ-1: a left press can only reach the grip while its latch is set when the previous
    release was lost, so the press must restart the drag instead of being ignored."""
    grip = EditorMoveGrip()
    grip.resize(60, 20)
    grip.show()
    started: list[QPoint] = []
    grip.drag_started.connect(started.append)
    _press_and_move_without_release(grip, QPoint(10, 0))
    assert grip.is_dragging() is True and len(started) == 1
    _press_and_move_without_release(grip, QPoint(10, 0))
    assert len(started) == 2, "the second press (the first release was lost) must start a drag"
    assert grip.is_dragging() is True
    grip.hide()
    assert grip.is_dragging() is False, "a hidden grip never holds a drag"
    assert grip.cursor().shape() == Qt.OpenHandCursor


@_ALL_ROTATIONS
@pytest.mark.parametrize(
    "reason",
    [TextEditFinalizeReason.SAVE_SHORTCUT, TextEditFinalizeReason.CANCEL_BUTTON],
)
def test_a_finalize_that_swallows_the_grip_release_leaves_the_next_grip_drag_working(gui, reason) -> None:
    """SEQ-1: Ctrl+Shift+S mid-drag finalizes (CS1 completes the drag) and opens a modal dialog
    that swallows the release.  The grip's own latch stayed set, so the next press was ignored
    and the user's whole first move did nothing."""
    gui.open_editor()
    view = gui.view
    grip = view.text_action_bar.move_grip
    _press_and_move_without_release(grip, QPoint(30, 0))
    assert view._drag_active and grip.is_dragging(), "precondition: a live grip drag, no release"

    view._finalize_text_edit(reason)
    _pump(200)

    assert view._drag_active is False
    assert grip.is_dragging() is False, "the view ended the drag: the grip must not stay latched"
    assert grip.cursor().shape() == Qt.OpenHandCursor
    if gui.editor() is None:
        gui.open_editor()
    pos_before, _ = gui.geometry()
    _drag_widget(grip, grip.rect().center(), QPoint(20, 0))
    pos_after, _ = gui.geometry()
    assert pos_after.x() == pytest.approx(pos_before.x() + 20, abs=1.01), "the next drag must move the box"


@_ALL_ROTATIONS
def test_an_ended_grip_drag_clears_the_grip_latch_in_every_view_path(gui) -> None:
    """SEQ-1: ``_on_move_grip_finished`` (the view's end of a drag) clears the latch on both the
    moved and the unmoved branch, even when the grip never saw the release."""
    gui.open_editor()
    view = gui.view
    grip = view.text_action_bar.move_grip
    for delta in (QPoint(30, 0), QPoint(0, 0)):
        _press_and_move_without_release(grip, delta)
        assert grip.is_dragging() is True
        view._on_move_grip_finished(QPoint())
        _pump(100)
        assert grip.is_dragging() is False
        assert grip.cursor().shape() == Qt.OpenHandCursor


@_ALL_ROTATIONS
def test_grip_moves_an_add_text_box_on_a_rotated_page_by_the_drag(gui) -> None:
    """S5: add_new editors open through the same rotated corner path as edit_existing, so the
    move inverse and the clamp apply to them too: the box follows the drag on screen, its
    document rect shifts by the derotated drag, and it stays on the page."""
    gui.view.set_mode("add_text")
    _pump(100)
    page_scene = _scene_rect_of(gui.view, gui.model.doc[0].rect)
    gui.view.graphics_view.centerOn(page_scene.center())
    _pump(80)
    click = gui.view.graphics_view.mapFromScene(
        QPointF(page_scene.x() + page_scene.width() * 0.4, page_scene.y() + page_scene.height() * 0.4)
    )
    gui.click(click)
    _pump(300)
    editor = gui.editor()
    assert editor is not None, "a click on the page in add_text mode opens an editor"
    editor.insertPlainText("hello world")
    _pump(100)

    scale = gui.view._render_scale
    delta = QPoint(40, 30)
    scene_before = QRectF(gui.view.text_editor.sceneBoundingRect())
    rect_before = fitz.Rect(gui.view.editing_rect)
    grip = gui.view.text_action_bar.move_grip
    assert grip.isVisible(), "add_text editors get the grip too"
    _drag_widget(grip, grip.rect().center(), delta)
    _pump(200)

    assert gui.editor() is editor and editor.toPlainText() == "hello world"
    scene_after = QRectF(gui.view.text_editor.sceneBoundingRect())
    assert scene_after.x() - scene_before.x() == pytest.approx(delta.x(), abs=1.5)
    assert scene_after.y() - scene_before.y() == pytest.approx(delta.y(), abs=1.5)
    assert page_scene.contains(scene_after), "the moved box stays on the page"

    # ``editing_rect`` of an add_text box is the VISUAL (as displayed) rect, so it shifts by
    # the drag itself, not by its derotation.
    rect_after = fitz.Rect(gui.view.editing_rect)
    assert rect_after.x0 - rect_before.x0 == pytest.approx(delta.x() / scale, abs=1.5 / scale)
    assert rect_after.y0 - rect_before.y0 == pytest.approx(delta.y() / scale, abs=1.5 / scale)


@_UNROTATED
def test_grip_moves_an_add_text_box_and_an_in_box_press_places_its_caret(gui) -> None:
    editor = _open_add_text_box(gui, 200.0, 400.0)
    editor.insertPlainText("hello world")
    editor.setFocus()
    _pump(100)
    gui.click(gui.vp_char(5))
    assert gui.editor() is editor and editor.textCursor().position() == 5
    assert gui.view._text_edit_drag_state == TextEditDragState.IDLE

    grip = gui.view.text_action_bar.move_grip
    assert grip.isVisible(), "add_text editors get the grip too"
    before = QPointF(gui.view.text_editor.pos())
    _drag_widget(grip, grip.rect().center(), QPoint(0, 24))
    after = gui.view.text_editor.pos()
    assert gui.editor() is editor
    assert after.y() == pytest.approx(before.y() + 24.0, abs=1.01)
    assert after.x() == pytest.approx(before.x(), abs=0.01)
    assert editor.toPlainText() == "hello world"

    # add_text owns an I-beam mode cursor: it must survive hovering away and closing.
    gui.move(gui.vp_point(editor.width() / 2.0, editor.height() + 60.0))
    assert gui.viewport.cursor().shape() == Qt.IBeamCursor
    QTest.keyClick(editor, Qt.Key_Escape)
    _pump(300)
    assert gui.view.text_editor is None
    assert gui.viewport.cursor().shape() == Qt.IBeamCursor


# ------------------------------------------------------------------ cursor


def _hover_into_the_box(gui, editor) -> None:
    outside = gui.vp_point(editor.width() / 2.0, editor.height() + 60.0)
    gui.move(outside)
    gui.move(gui.vp_point(editor.width() / 2.0, editor.height() / 2.0))


@_UNROTATED
def test_hover_inside_open_editor_shows_ibeam(gui) -> None:
    editor = gui.open_editor()
    _hover_into_the_box(gui, editor)
    assert gui.viewport.cursor().shape() == Qt.IBeamCursor
    # QGraphicsView resets a scroll-hand viewport to an open hand after a click; a move
    # that stays inside the box must bring the I-beam back.
    gui.viewport.setCursor(Qt.OpenHandCursor)
    gui.move(gui.vp_point(editor.width() / 2.0 + 3.0, editor.height() / 2.0))
    assert gui.viewport.cursor().shape() == Qt.IBeamCursor
    # (Beside the box, not below it: the two-row bar (P1 live text strip) sits below.)
    outside = gui.vp_point(-40.0, editor.height() / 2.0)
    gui.move(outside)
    expected = (
        Qt.OpenHandCursor
        if gui.view.graphics_view.dragMode() == gui.view.graphics_view.DragMode.ScrollHandDrag
        else Qt.ArrowCursor
    )
    assert gui.viewport.cursor().shape() == expected


@_UNROTATED
def test_the_ibeam_does_not_outlive_the_editor(gui) -> None:
    editor = gui.open_editor()
    _hover_into_the_box(gui, editor)
    assert gui.viewport.cursor().shape() == Qt.IBeamCursor
    QTest.keyClick(editor, Qt.Key_Escape)
    _pump(300)
    assert gui.view.text_editor is None
    assert gui.viewport.cursor().shape() != Qt.IBeamCursor


@_UNROTATED
def test_the_ibeam_does_not_survive_a_mode_switch(gui) -> None:
    editor = gui.open_editor()
    _hover_into_the_box(gui, editor)
    assert gui.viewport.cursor().shape() == Qt.IBeamCursor
    gui.view.set_mode("objects")
    _pump(200)
    assert gui.viewport.cursor().shape() != Qt.IBeamCursor


def test_hover_over_the_open_box_sets_the_ibeam_and_leaving_restores_the_drag_cursor(
    monkeypatch,
) -> None:
    """Deterministic pin on the fake view: offscreen Qt gives an I-beam over a proxy by
    itself, but the corpus window and the owner's Windows session kept the open hand
    (recording 54.47 s), so the view must set the cursor itself on every move."""
    from PySide6.QtWidgets import QGraphicsView

    import test_text_editing_gui_regressions as fakes

    class _BoxProxy(fakes._FakeProxy):
        def boundingRect(self) -> QRectF:
            return QRectF(0, 0, 100, 20)

        def mapRectToScene(self, rect: QRectF) -> QRectF:
            return rect.translated(self._pos)

    monkeypatch.setattr(fakes.pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **k: None)
    view = fakes._make_view()
    view.current_mode = "edit_text"
    view.text_editor = _BoxProxy(fakes._FakeEditorWidget("text", "text"), pos=QPointF(10, 10))
    modes = {"mode": QGraphicsView.ScrollHandDrag}
    view.graphics_view.dragMode = lambda: modes["mode"]
    viewport = view.graphics_view.viewport()

    view._mouse_move(fakes._FakeMouseEvent(50, 20))
    assert viewport.cursor == Qt.IBeamCursor

    view._mouse_move(fakes._FakeMouseEvent(300, 300))
    assert viewport.cursor == Qt.OpenHandCursor

    view._mouse_move(fakes._FakeMouseEvent(50, 20))
    modes["mode"] = QGraphicsView.NoDrag
    view._mouse_move(fakes._FakeMouseEvent(300, 300))
    assert viewport.cursor == Qt.ArrowCursor


# ------------------------------------------------------------------ reveal_caret API


@_UNROTATED
def test_reveal_caret_is_idempotent_and_signals_once(gui) -> None:
    editor = gui.open_editor()
    seen: list[bool] = []
    editor.caret_revealed_changed.connect(lambda: seen.append(True))
    assert editor.caret_revealed() is False
    editor.reveal_caret()
    editor.reveal_caret()
    assert editor.caret_revealed() is True
    assert editor.cursorWidth() == 1
    assert seen == [True]


@_UNROTATED
def test_a_key_press_reveals_the_caret_through_reveal_caret(gui) -> None:
    editor = gui.open_editor()
    seen: list[bool] = []
    editor.caret_revealed_changed.connect(lambda: seen.append(True))
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_Right)
    assert editor.caret_revealed() is True and seen == [True]


# ------------------------------------------------------------------ first click threshold


def _fake_pending_view(monkeypatch):
    """The no-editor 'pending text block' path on the fake view of the regression suite."""
    import test_text_editing_gui_regressions as fakes

    monkeypatch.setattr(fakes.pdf_view.QGraphicsView, "mouseMoveEvent", lambda *a, **k: None)
    view = fakes._make_view()
    view.current_mode = "edit_text"
    view.text_editor = None
    view._drag_pending = True
    view._drag_active = False
    view._drag_start_scene_pos = QPointF(0, 0)
    view._drag_editor_start_pos = None
    view._pending_text_info = ("block",)
    view._editing_page_idx = 0
    created: list[tuple] = []

    def _create(*info):
        created.append(info)
        view.text_editor = fakes._FakeProxy(fakes._FakeEditorWidget("t", "t"), pos=QPointF(10, 10))

    view._create_text_editor = _create
    view._clamp_editor_pos_to_page = lambda x, y, page_idx: (x, y)
    view._position_text_action_bar = lambda: None
    return fakes, view, created


def test_first_click_threshold_is_the_larger_of_3_and_the_platform_drag_distance(monkeypatch) -> None:
    fakes, view, created = _fake_pending_view(monkeypatch)
    threshold = max(TextEditGeometryConstants.DRAG_START_DISTANCE_PX, QApplication.startDragDistance())
    assert threshold >= 3.0

    view._mouse_move(fakes._FakeMouseEvent(threshold - 1.0, 0))
    assert view._drag_active is False and created == []
    assert view._drag_pending is True

    view._mouse_move(fakes._FakeMouseEvent(threshold + 1.0, 0))
    assert view._drag_active is True
    assert created == [("block",)], "the pending block opens only past the threshold"


def test_first_click_threshold_follows_the_platform_drag_distance(monkeypatch) -> None:
    fakes, view, created = _fake_pending_view(monkeypatch)
    monkeypatch.setattr(QApplication, "startDragDistance", staticmethod(lambda: 20))
    view._mouse_move(fakes._FakeMouseEvent(15.0, 0))
    assert view._drag_active is False and created == []
    view._mouse_move(fakes._FakeMouseEvent(21.0, 0))
    assert view._drag_active is True and len(created) == 1


@_UNROTATED
def test_first_click_with_jitter_on_unopened_text_opens_the_editor_unmoved(gui) -> None:
    ink_scene = _scene_rect_of(gui.view, _ink_bbox(gui.model.doc[0]))
    centre = ink_scene.center()
    gui.view.graphics_view.centerOn(centre)
    _pump(80)
    start = gui.view.graphics_view.mapFromScene(centre)
    gui.press(start)
    gui.move(QPoint(start.x() + 4, start.y()))
    gui.release(QPoint(start.x() + 4, start.y()))
    _wait_until(lambda: gui.editor() is not None, 10, step_ms=20)
    _pump(300)
    assert gui.editor() is not None
    assert gui.view.text_editor.pos().x() == pytest.approx(ink_scene.left(), abs=3.0)
    assert gui.view.text_apply_btn.isEnabled() is True
    assert gui.reason() is None


# ------------------------------------------------------------------ owner scenario (corpus copy)

_ECC = REPO_ROOT / "test_files" / "ecc-dwg.pdf"
_ECC_RUN = "備為C標新設。"


def _open_ecc_run(monkeypatch, tmp_path, zoom: str | None = None):
    """Open the owner's run on a COPY of ecc-dwg; ``zoom`` (e.g. ``"214%"``) scales the glyph overhang."""
    if not _ECC.is_file():
        pytest.skip("test_files/ecc-dwg.pdf is not available")
    import test_text_commit_ui_real_corpus as ui

    work = tmp_path / "ecc-dwg - copy.pdf"
    shutil.copyfile(_ECC, work)
    app = ui._App(monkeypatch, work, shipped=True)
    app.ensure_edit_text_run_mode()
    if zoom is not None:
        app.view.zoom_combo.setCurrentText(zoom)
        app.pump(3000)
    with app.snapshot() as doc:
        hits = doc[0].search_for(_ECC_RUN)
    assert hits, "the owner's run must be on page 1"
    if zoom is not None:
        app.view.graphics_view.centerOn(app.view._doc_rect_to_scene_rect(0, hits[0]).center())
        app.pump(500)
    editor = app.click_glyph(0, hits[0])
    app.pump(600)
    assert editor is not None
    return app, editor


@pytest.mark.needs_fixtures
def test_press_and_jitter_inside_open_editor_on_the_owner_run(tmp_path, monkeypatch) -> None:
    app, editor = _open_ecc_run(monkeypatch, tmp_path)
    try:
        view = app.view
        manager = view._ensure_text_edit_manager()
        before = _editor_geometry(app.view)
        proxy = view.text_editor
        scene_rect = proxy.mapRectToScene(proxy.boundingRect())
        centre = view.graphics_view.mapFromScene(scene_rect.center())
        viewport = view.graphics_view.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, centre)
        app.pump(60)
        QTest.mouseMove(viewport, QPoint(centre.x() + 4, centre.y()))
        app.pump(60)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(centre.x() + 4, centre.y()))
        app.pump(1200)
        assert _editor_geometry(app.view) == before
        assert view.text_apply_btn.isEnabled() is True
        assert manager.current_rejection_reason() is None
        assert view.text_rebuild_btn.isHidden() is True
    finally:
        app.close()


@pytest.mark.needs_fixtures
def test_drag_inside_open_editor_on_the_owner_run_selects_and_never_moves(tmp_path, monkeypatch) -> None:
    app, editor = _open_ecc_run(monkeypatch, tmp_path)
    try:
        view = app.view
        before = _editor_geometry(app.view)
        proxy = view.text_editor
        scene_rect = proxy.mapRectToScene(proxy.boundingRect())
        y = scene_rect.y() + scene_rect.height() / 2.0
        start = view.graphics_view.mapFromScene(QPointF(scene_rect.x() + 12.0, y))
        viewport = view.graphics_view.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
        for step in range(1, 12):
            QTest.mouseMove(viewport, QPoint(start.x() + 3 * step, start.y()))
            app.pump(20)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(start.x() + 33, start.y()))
        app.pump(1200)
        cursor = editor.textCursor()
        assert cursor.hasSelection() and cursor.selectionStart() < cursor.selectionEnd()
        assert _editor_geometry(app.view) == before
        assert view.text_apply_btn.isEnabled() is True
    finally:
        app.close()


@pytest.mark.needs_fixtures
@pytest.mark.parametrize("zoom", ["100%", "214%"])
def test_grip_move_leaves_no_source_glyph_or_sliver_on_the_owner_run(tmp_path, monkeypatch, zoom) -> None:
    """S17a on a COPY of ecc-dwg (CJK, grey text): the open spot is blank after a grip move, and
    the glyph ink that overhangs the span bbox (measured: 1 px at 100 %, 2 px at 214 %) is covered
    too (M3).  The ring is checked 4 px out (the next text line starts 7 px away)."""
    app, _editor = _open_ecc_run(monkeypatch, tmp_path, zoom)
    try:
        view = app.view
        open_rect = QRectF(view.text_editor.sceneBoundingRect())
        page_rgb = _origin_page_colour(view, open_rect)
        inner = open_rect.adjusted(1, 1, -1, -1)
        assert _deviating(_scene_pixels(view, inner), page_rgb) > 0, "precondition: the frozen frame shows glyphs"
        _grip_move_off_the_spot(view, open_rect)
        app.pump(300)

        patch = view._text_editor_origin_mask_item
        assert patch is not None and patch.isVisible()
        assert patch.rect() == _expected_origin_cover(view)
        assert _deviating(_scene_pixels(view, inner), page_rgb) == 0, "the source glyphs show through"
        outer = open_rect.adjusted(-4, -4, 4, 4)
        ring = _deviating(_scene_pixels(view, outer), page_rgb, tolerance=8, skip=open_rect, origin=outer.topLeft())
        assert ring == 0, "glyph slivers remain outside the open rect"
    finally:
        app.close()


def _shift_px(view, original_rect: fitz.Rect) -> float:
    """How far ``editing_rect`` moved from ``original_rect`` (top-left), in scene pixels."""
    rect = fitz.Rect(view.editing_rect)
    return max(abs(rect.x0 - original_rect.x0), abs(rect.y0 - original_rect.y0)) * view._render_scale


@_ALL_ROTATIONS
@pytest.mark.parametrize(
    "reason",
    [TextEditFinalizeReason.SAVE_SHORTCUT, TextEditFinalizeReason.VIEW_RESCALE],
)
def test_a_keep_finalize_mid_grip_drag_completes_the_drag(gui, reason) -> None:
    """CS1: a keep-finalize (Ctrl+S, zoom) while the grip is still pressed used to clear the
    drag state without finishing the drag: the box stayed displaced and the origin patch
    visible, but ``editing_rect`` never followed, so Apply committed at the original spot.
    The drag is completed first; later grip moves / the release are ignored."""
    editor = gui.open_editor()
    editor.insertPlainText("X")
    _pump(200)
    view = gui.view
    original_rect = fitz.Rect(view._editing_original_rect)
    g0 = _grip_global_centre(view)

    view._on_move_grip_started(g0)
    view._on_move_grip_moved(g0 + QPoint(40, 0))
    _pump(60)
    moved_pos = QPointF(view.text_editor.pos())
    assert fitz.Rect(view.editing_rect) == original_rect, "precondition: mid-drag editing_rect has not followed yet"
    assert view._drag_active, "precondition: the grip drag is live"

    result = view._finalize_text_edit(reason)
    _pump(200)

    # The drag must be completed BEFORE the finalize reads the geometry (TV-1): the result's delta
    # (and, under the legacy preview, the committed request) has to see the displaced box.
    assert result is not None and result.delta.text_changed is True
    assert result.delta.position_changed is True, "the finalize delta must report the drag"
    assert gui.editor() is editor, "precondition: a keep reason keeps the editor"
    assert view._drag_active is False
    assert view._text_edit_drag_state == TextEditDragState.IDLE
    assert gui.viewport.cursor().shape() != Qt.ClosedHandCursor
    rect = fitz.Rect(view.editing_rect)
    assert _shift_px(view, original_rect) == pytest.approx(40.0, abs=1.5), (
        "editing_rect must follow the displaced box"
    )

    view._on_move_grip_moved(g0 + QPoint(60, 0))
    view._on_move_grip_finished(g0 + QPoint(60, 0))
    _pump(100)
    assert QPointF(view.text_editor.pos()) == moved_pos, "the drag is over: later grip events are ignored"
    assert fitz.Rect(view.editing_rect) == rect


@_ALL_ROTATIONS
def test_a_keep_finalize_after_a_grip_press_that_never_moved_still_commits(gui) -> None:
    """CS1, unmoved branch: Ctrl+S while the grip is pressed but the box has not moved must
    close the press like a release (reset the drag state and cursor) and KEEP the verified plan
    token.  Finishing it through ``_finish_editor_drag`` instead would regenerate the preview
    (dropping the token) and the commit would be refused."""
    editor = gui.open_editor()
    _type_x_and_wait_for_token(gui, editor)
    view = gui.view
    manager = view._ensure_text_edit_manager()
    original_rect = fitz.Rect(view._editing_original_rect)
    g0 = _grip_global_centre(view)

    view._on_move_grip_started(g0)
    _pump(60)
    assert view._drag_active, "precondition: the grip is pressed"
    assert editor.current_plan_token() is not None, "precondition: the press alone keeps the token"
    assert manager.apply_permitted() is True, "precondition: Apply is still permitted"
    assert fitz.Rect(view.editing_rect) == original_rect, "precondition: the box never moved"

    result = view._finalize_text_edit(TextEditFinalizeReason.SAVE_SHORTCUT)
    _pump(300)

    assert result is not None
    assert result.outcome == TextEditOutcome.COMMITTED, f"a press without a move must not refuse the commit: {result}"
    assert result.delta.position_changed is False
    assert view._drag_active is False
    assert view._text_edit_drag_state == TextEditDragState.IDLE
    assert gui.viewport.cursor().shape() != Qt.ClosedHandCursor


@_LEGACY_ALL
def test_legacy_keep_finalize_mid_grip_drag_commits_the_displaced_box(gui_legacy) -> None:
    """TV-1: under the legacy preview Ctrl+S mid-drag commits (apply is permitted).  The request
    must carry the displaced rect, not ``new_rect=None`` (text committed at the original spot
    while the box sits displaced)."""
    gui = gui_legacy
    editor = gui.open_editor()
    editor.insertPlainText("X")
    _pump(200)
    view = gui.view
    original_rect = fitz.Rect(view._editing_original_rect)
    g0 = _grip_global_centre(view)
    view._on_move_grip_started(g0)
    view._on_move_grip_moved(g0 + QPoint(40, 0))
    _pump(60)
    assert view._drag_active, "precondition: the grip drag is live"
    emitted: list = []
    view.sig_edit_text.connect(emitted.append)

    view._finalize_text_edit(TextEditFinalizeReason.SAVE_SHORTCUT)
    _pump(200)

    assert len(emitted) == 1, f"expected one sig_edit_text emission, got {len(emitted)}"
    new_rect = emitted[0].new_rect
    assert new_rect is not None, "new_rect=None: committed at the original spot"
    new_rect = fitz.Rect(new_rect)
    shift_pt = max(abs(new_rect.x0 - original_rect.x0), abs(new_rect.y0 - original_rect.y0))
    assert shift_pt * view._render_scale == pytest.approx(40.0, abs=1.5)
    assert new_rect == fitz.Rect(view.editing_rect)


# ------------------------------------------------ SEQ-2: a grip drag whose release was swallowed


def _lost_release_drag(gui, dx: int = 40):
    """A grip press + ``dx`` px of moves whose release never arrives (a modal such as Ctrl+O's
    file dialog swallowed it, or the focus net did not finalize).  Returns ``(editor, open rect)``."""
    editor = gui.open_editor()
    view = gui.view
    original_rect = fitz.Rect(view._editing_original_rect)
    _press_and_move_without_release(view.text_action_bar.move_grip, QPoint(dx, 0))
    _pump(60)
    assert view._drag_active is True, "precondition: the lost-release drag is live"
    assert fitz.Rect(view.editing_rect) == original_rect, "precondition: editing_rect has not followed yet"
    return editor, original_rect


@_ALL_ROTATIONS
def test_an_in_box_click_after_a_lost_grip_release_completes_the_drag_and_commits_the_move(gui) -> None:
    """SEQ-2 (a): the in-box press cleared ``_drag_active`` without ``_finish_editor_drag``, so the
    box (and the origin patch) sat displaced while ``editing_rect`` stayed at the open spot and
    the commit landed there with ``position_changed`` False."""
    editor, original_rect = _lost_release_drag(gui)
    view = gui.view
    centre = view.graphics_view.mapFromScene(view.text_editor.sceneBoundingRect().center())

    QTest.mouseClick(gui.viewport, Qt.LeftButton, Qt.NoModifier, centre)
    _pump(200)

    assert view._drag_active is False
    assert view._text_edit_drag_state != TextEditDragState.ACTIVE
    assert _shift_px(view, original_rect) == pytest.approx(40.0, abs=1.5), (
        "editing_rect must follow the displaced box"
    )
    assert _editing_position_changed(view) is True
    assert view.text_action_bar.move_grip.is_dragging() is False, "the ended drag clears the grip latch"

    # Same state a released drag leaves: a moved box needs the rebuild consent, so Apply is
    # refused -- it must never commit at the old spot (position_changed False) while the box
    # sits displaced.
    editor.insertPlainText("X")
    _wait_until(lambda: gui.reason() == "geometry_override_present", 15)
    assert gui.reason() == "geometry_override_present", "the displaced box is a move, as after a real release"
    assert editor.current_plan_token() is None
    result = view._finalize_text_edit(TextEditFinalizeReason.APPLY)
    _pump(300)
    assert result is None or result.outcome != TextEditOutcome.COMMITTED, result


@_ALL_ROTATIONS
def test_a_button_less_move_after_a_lost_grip_release_ends_the_drag_instead_of_moving_the_box(gui) -> None:
    """SEQ-2 (b): the ACTIVE branch of ``_mouse_move`` had no ``buttons() & LeftButton`` check (the
    SELECTING branch does), so the box followed the hovering pointer with no button held."""
    _editor, original_rect = _lost_release_drag(gui)
    view = gui.view
    grip = view.text_action_bar.move_grip
    pos_before = QPointF(view.text_editor.pos())
    target = gui.viewport.rect().center() + QPoint(100, 50)

    QApplication.sendEvent(
        gui.viewport,
        QMouseEvent(
            QEvent.MouseMove,
            QPointF(target),
            QPointF(gui.viewport.mapToGlobal(target)),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        ),
    )
    _pump(120)

    assert view._drag_active is False
    assert view._text_edit_drag_state != TextEditDragState.ACTIVE
    assert QPointF(view.text_editor.pos()) == pos_before, "no button held: the box must not follow the pointer"
    assert _shift_px(view, original_rect) == pytest.approx(40.0, abs=1.5), "the drag was completed where it stood"
    assert grip.is_dragging() is False
    assert gui.viewport.cursor().shape() != Qt.ClosedHandCursor


@_ALL_ROTATIONS
def test_a_left_button_move_still_drives_a_live_viewport_drag(gui) -> None:
    """SEQ-2 control: the new guard keys on the button, not on the drag state."""
    _editor, _original = _lost_release_drag(gui)
    view = gui.view
    pos_before = QPointF(view.text_editor.pos())
    target = gui.viewport.rect().center() + QPoint(100, 50)

    QApplication.sendEvent(
        gui.viewport,
        QMouseEvent(
            QEvent.MouseMove,
            QPointF(target),
            QPointF(gui.viewport.mapToGlobal(target)),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    _pump(120)

    assert view._drag_active is True
    assert QPointF(view.text_editor.pos()) != pos_before


@_ALL_ROTATIONS
def test_a_second_grip_press_after_a_lost_release_completes_the_first_drag_and_keeps_its_own_latch(gui) -> None:
    """SEQ-2 / SEQ-1: the next grip press (the release was lost) must not silently re-base the drag
    on the displaced box and forget the first move; and finishing the stale drag must not clear the
    latch of the press that is starting right now."""
    _editor, original_rect = _lost_release_drag(gui)
    view = gui.view
    grip = view.text_action_bar.move_grip

    _press_and_move_without_release(grip, QPoint(0, 0))
    _pump(60)

    assert _shift_px(view, original_rect) == pytest.approx(40.0, abs=1.5), "the first drag was completed"
    assert view._drag_active is True, "the new press owns a fresh drag"
    assert grip.is_dragging() is True, "the new press keeps its latch"


def _red_search_hit_items(view) -> list:
    """The 2 px red search-hit rectangles display_page adds to the scene."""
    return [
        item
        for item in view.scene.items()
        if isinstance(item, QGraphicsRectItem) and item.pen().color() == QColor("red")
    ]


def _red_pixel_count(image: QImage) -> int:
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.red() > 200 and c.green() < 80 and c.blue() < 80:
                count += 1
    return count


def test_search_jump_highlight_is_drawn_above_the_origin_patch_while_the_box_is_moved(gui) -> None:
    """SCN-1: a search jump keeps the editor open and the highlight lands on the source span,
    which the origin patch (z 10.5) covers while the box is displaced.  The 2 px red rect was
    added at z 0, so the spot looked blank at exactly the place the search pointed to."""
    view = gui.view
    gui.open_editor()
    _grip_move_off_the_spot(view, QRectF(view.text_editor.sceneBoundingRect()))
    patch = view._text_editor_origin_mask_item
    assert patch is not None and patch.isVisible(), "precondition: the origin patch is shown"
    span = fitz.Rect(view._editing_original_rect)
    span_scene = _scene_rect_of(view, span)
    window = span_scene.adjusted(-20, -20, 20, 20)
    assert _red_pixel_count(_scene_pixels(view, window)) == 0, "precondition: no highlight yet"

    gui.controller.jump_to_result(1, span)
    _pump(200)

    assert view.text_editor is not None and view.text_editor.widget() is not None, "the jump keeps the editor"
    hits = _red_search_hit_items(view)
    assert hits, "the jump draws a search-hit rectangle"
    z = hits[-1].zValue()
    assert patch.zValue() < z < 11, ("above the origin patch, below the moving mask / proxy", z)
    assert view.scene.items(span_scene.center())[0] is hits[-1], "the highlight is the topmost item at the span"
    assert _red_pixel_count(_scene_pixels(view, window)) > 0, "the highlight is visible at the source span"


# ------------------------------------------------ round 7 / ISO-2: the harness tears its widgets down


def test_gui_session_teardown_leaves_no_live_view_or_visible_editor(qapp, tmp_path, monkeypatch) -> None:
    """ISO-2.  RED before: the ``_gui_session`` teardown closed the view but never cancelled the open inline
    editor and never ``deleteLater()``-ed the view, so every test that left an editor open kept one live
    ``PDFView`` plus one VISIBLE top-level ``PreviewBackedInlineTextEditor`` (via view -> action bar ->
    live_text_strip -> editor) for the rest of the process: 161 visible editors, ~45k widgets and ~2 GB
    after this module alone, which every later ``processEvents`` then had to service."""
    import gc

    import shiboken6

    def visible_editors() -> list:
        return [
            w
            for w in QApplication.topLevelWidgets()
            if isinstance(w, PreviewBackedInlineTextEditor) and w.isVisible()
        ]

    before = len(visible_editors())
    session = _gui_session(qapp, tmp_path, monkeypatch, 0)
    harness = next(session)
    editor = harness.open_editor()
    view = harness.view
    assert editor.isVisible() and len(visible_editors()) == before + 1, "the test leaves an editor open"
    assert next(session, None) is None, "the fixture teardown ran to its end"
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
    assert len(visible_editors()) == before, "no visible editor outlives the fixture"
    assert not shiboken6.isValid(view), "the PDFView is destroyed, not merely hidden"


# ------------------------------------------------ S17-PASTE-NOTICE: the status bar says what a paste cleaned


def test_pasting_controls_and_an_image_into_the_open_editor_shows_a_zh_tw_status_notice(gui) -> None:
    """The owner chose a status-bar notice (not a toast) for what a paste removed; a clean paste is silent."""
    from PySide6.QtCore import QMimeData

    editor = gui.open_editor()
    status = gui.view.status_bar
    status.clearMessage()
    clean = QMimeData()
    clean.setText("ok")
    editor.insertFromMimeData(clean)
    assert status.currentMessage() == "", "a clean paste says nothing"
    dirty = QMimeData()
    dirty.setText("x\x07y")
    dirty.setHtml('<p>x<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">y</p>')
    editor.insertFromMimeData(dirty)
    message = status.currentMessage()
    assert message and any("\u4e00" <= ch <= "\u9fff" for ch in message), message
    assert "1" in message
