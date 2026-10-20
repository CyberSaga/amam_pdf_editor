from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import controller.pdf_controller as controller_module  # noqa: E402
import view.pdf_view as pdf_view  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from model.object_op_refusal import ObjectOpRefusal  # noqa: E402
from model.object_requests import ObjectHitInfo  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self.emitted = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


class _FakeViewport:
    def __init__(self, offset: QPoint | None = None) -> None:
        self.cursor = None
        self._offset = offset or QPoint(0, 0)

    def setCursor(self, cursor) -> None:
        self.cursor = cursor

    def mapFrom(self, _parent, pos):
        return QPoint(pos.x() + self._offset.x(), pos.y() + self._offset.y())


class _FakeGraphicsView:
    def __init__(self, viewport_offset: QPoint | None = None) -> None:
        self._viewport = _FakeViewport(viewport_offset)
        self._scene_offset = viewport_offset or QPoint(0, 0)

    def viewport(self):
        return self._viewport

    def mapToGlobal(self, pos):
        return pos

    def mapToScene(self, pos):
        if isinstance(pos, QPointF):
            return QPointF(float(pos.x() - self._scene_offset.x()), float(pos.y() - self._scene_offset.y()))
        return QPointF(float(pos.x() - self._scene_offset.x()), float(pos.y() - self._scene_offset.y()))


class _FakeEvent:
    def __init__(
        self,
        x: float,
        y: float,
        button=Qt.LeftButton,
        modifiers: Qt.KeyboardModifiers = Qt.NoModifier,
    ) -> None:
        self._point = QPointF(x, y)
        self._button = button
        self._modifiers = modifiers
        self.accepted = False

    def position(self):
        return self._point

    def pos(self):
        return self._point.toPoint()

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


class _FakeKeyEvent:
    def __init__(self, key: int, modifiers: Qt.KeyboardModifiers = Qt.NoModifier) -> None:
        self._key = key
        self._modifiers = modifiers
        self.accepted = False

    def key(self):
        return self._key

    def modifiers(self):
        return self._modifiers

    def matches(self, sequence):
        return False

    def accept(self):
        self.accepted = True


def _make_object_hit(kind: str = "textbox", supports_rotate: bool = True) -> ObjectHitInfo:
    return ObjectHitInfo(
        object_kind=kind,
        object_id="obj-1",
        page_num=1,
        bbox=fitz.Rect(20, 20, 120, 80),
        rotation=0,
        supports_move=True,
        supports_delete=True,
        supports_rotate=supports_rotate,
    )


def _make_view(viewport_offset: QPoint | None = None) -> pdf_view.PDFView:
    view = pdf_view.PDFView.__new__(pdf_view.PDFView)
    view.graphics_view = _FakeGraphicsView(viewport_offset)
    view.current_mode = "browse"
    view.current_page = 0
    view.total_pages = 1
    view.scale = 1.0
    view._fullscreen_active = False
    view._selected_text_cached = ""
    view._selected_text_rect_doc = None
    view._selected_object_info = None
    view._object_selection_rect_item = None
    view._object_rotate_handle_item = None
    view._object_drag_pending = False
    view._object_drag_active = False
    view._object_rotate_pending = False
    view._object_drag_start_scene_pos = None
    view._object_drag_start_doc_rect = None
    view._object_drag_page_idx = None
    view._object_drag_current_scene_pos = None
    view._render_scale = 1.0
    view.page_y_positions = [0.0]
    view.continuous_pages = True
    view.scene = None
    view.controller = SimpleNamespace(
        get_object_info_at_point=lambda page_num, point: None,
        get_text_info_at_point=lambda page_num, point, allow_fallback=False: None,
    )
    view._clear_text_selection = lambda: None
    view._start_text_selection = lambda scene_pos, page_idx: setattr(view, "_text_selection_started", True)
    view._text_selection_started = False
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(scene_pos.x(), scene_pos.y()))
    view._select_object = lambda info: setattr(view, "_selected_object_info", info)
    view._clear_object_selection = lambda: setattr(view, "_selected_object_info", None)
    view._update_browse_hover_cursor = lambda scene_pos: None
    view._reset_browse_hover_cursor = lambda: None
    view._point_hits_object_rotate_handle = lambda scene_pos: False
    view.sig_delete_object = _FakeSignal()
    view.sig_rotate_object = _FakeSignal()
    return view


def test_objects_mouse_press_selects_object_and_blocks_text_selection(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    hit = _make_object_hit(kind="rect", supports_rotate=False)
    view.controller.get_object_info_at_point = lambda page_num, point: hit

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_press(view, _FakeEvent(40, 40))

    assert view._selected_object_info == hit
    assert view._text_selection_started is False


def test_objects_mouse_press_selects_native_image(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    hit = _make_object_hit(kind="native_image", supports_rotate=True)
    view.controller.get_object_info_at_point = lambda page_num, point: hit

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    event = _FakeEvent(40, 40)
    pdf_view.PDFView._mouse_press(view, event)

    assert view._selected_object_info == hit
    assert event.accepted is True


def test_event_scene_pos_normalizes_viewport_offset() -> None:
    view = _make_view(QPoint(97, 186))
    scene_pos = pdf_view.PDFView._event_scene_pos(view, _FakeEvent(166, 37))
    assert scene_pos == QPointF(166.0, 37.0)


def test_delete_selected_object_emits_request() -> None:
    view = _make_view()
    view._selected_object_info = _make_object_hit(kind="rect", supports_rotate=False)

    assert pdf_view.PDFView._delete_selected_object(view) is True
    assert view.sig_delete_object.emitted


def test_rotate_selected_object_emits_request() -> None:
    view = _make_view()
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)

    assert pdf_view.PDFView._rotate_selected_object(view, 90) is True
    assert view.sig_rotate_object.emitted


def test_rotate_selected_object_absolute_emits_exact_request() -> None:
    view = _make_view()
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)
    view._update_object_selection_visuals = lambda *args, **kwargs: None

    assert pdf_view.PDFView._rotate_selected_object_absolute(view, 180) is True
    req = view.sig_rotate_object.emitted[-1][0]
    assert req.rotation_delta == 0
    assert req.absolute_rotation == 180.0
    assert view._selected_object_info.rotation == 180.0

    assert pdf_view.PDFView._rotate_selected_object_absolute(view, 360) is True
    req = view.sig_rotate_object.emitted[-1][0]
    assert req.rotation_delta == 0
    assert req.absolute_rotation == 0.0
    assert view._selected_object_info.rotation == 0.0


def test_delete_shortcut_works_in_objects_mode() -> None:
    view = _make_view()
    view.current_mode = "objects"
    view._selected_object_info = _make_object_hit(kind="rect", supports_rotate=False)

    event = _FakeKeyEvent(Qt.Key_Delete)
    pdf_view.PDFView.keyPressEvent(view, event)

    assert event.accepted is True
    assert view.sig_delete_object.emitted


def test_delete_shortcut_works_in_text_edit_mode() -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)

    event = _FakeKeyEvent(Qt.Key_Backspace)
    pdf_view.PDFView.keyPressEvent(view, event)

    assert event.accepted is True
    assert view.sig_delete_object.emitted


def test_browse_object_drag_threshold_starts_drag(monkeypatch) -> None:
    view = _make_view()
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)
    view._object_drag_pending = True
    view._object_drag_start_scene_pos = QPointF(10, 10)
    view._object_drag_start_doc_rect = fitz.Rect(20, 20, 120, 80)
    view._object_drag_page_idx = 0
    view.controller.model = SimpleNamespace(doc=[SimpleNamespace(rect=fitz.Rect(0, 0, 500, 500))])
    view._object_drag_preview_rect = None
    view._update_object_selection_visuals = lambda rect=None: None

    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseMoveEvent", lambda *args, **kwargs: None)

    pdf_view.PDFView._mouse_move(view, _FakeEvent(40, 40))

    assert view._object_drag_active is True


def test_text_edit_mouse_press_on_rotate_handle_does_not_arm_free_rotation(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    hit = _make_object_hit(kind="textbox", supports_rotate=True)
    view._selected_object_info = hit
    view._point_hits_object_rotate_handle = lambda scene_pos: True
    view.controller.get_object_info_at_point = lambda page_num, point: None

    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *args, **kwargs: None)

    event = _FakeEvent(40, 40)
    pdf_view.PDFView._mouse_press(view, event)

    assert view._object_rotate_pending is False
    assert event.accepted is False


def test_textbox_rotate_pending_release_steps_to_next_right_angle(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "text_edit"
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)
    view._object_rotate_pending = True
    view._object_rotate_active = False
    view._object_drag_pending = False

    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *args, **kwargs: None)

    event = _FakeEvent(40, 40)
    pdf_view.PDFView._mouse_release(view, event)

    assert event.accepted is True
    assert len(view.sig_rotate_object.emitted) == 1
    req = view.sig_rotate_object.emitted[0][0]
    assert req.rotation_delta == 0
    assert req.absolute_rotation == 90.0


def test_scene_context_menu_includes_object_actions(monkeypatch) -> None:
    view = _make_view()
    labels = []
    view._selected_object_info = _make_object_hit(kind="textbox", supports_rotate=True)
    view._resolve_text_info_for_context_menu_pos = lambda pos: None

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class _FakeMenu:
        def __init__(self) -> None:
            self._actions = []
            self._children = []

        def addAction(self, text: str, callback=None):
            self._actions.append(_FakeAction(text))
            return self._actions[-1]

        def addMenu(self, text: str):
            self._actions.append(_FakeAction(text))
            child = _FakeMenu()
            self._children.append(child)
            return child

        def addSeparator(self):
            return None

        def exec_(self, *args, **kwargs):
            labels.extend(action.text() for action in self._actions)
            for child in self._children:
                labels.extend(action.text() for action in child._actions)
            return None

    monkeypatch.setattr(pdf_view, "QMenu", _FakeMenu)

    pdf_view.PDFView._show_context_menu(view, QPoint(0, 0))

    assert "Delete Object" in labels
    assert "Rotate Object" in labels
    assert "90°" not in labels
    assert "180°" not in labels
    assert "270°" not in labels
    assert "360°" not in labels


def test_objects_context_menu_exposes_image_insert_actions(monkeypatch) -> None:
    view = _make_view()
    view.current_mode = "objects"
    labels = []
    view._selected_object_info = None
    view._resolve_text_info_for_context_menu_pos = lambda pos: None
    view._resolve_default_image_insert_target = lambda pos: (1, fitz.Rect(10, 10, 110, 85))

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class _FakeMenu:
        def __init__(self) -> None:
            self._actions = []

        def addAction(self, text: str, callback=None):
            self._actions.append(_FakeAction(text))
            return self._actions[-1]

        def addSeparator(self):
            return None

        def exec_(self, *args, **kwargs):
            labels.extend(action.text() for action in self._actions)
            return None

    monkeypatch.setattr(pdf_view, "QMenu", _FakeMenu)

    pdf_view.PDFView._show_context_menu(view, QPoint(0, 0))

    assert any("插入圖片" in label for label in labels)
    assert any("剪貼簿" in label for label in labels)


def test_objects_mode_move_release_rebases_selected_object_info_immediately(monkeypatch) -> None:
    """After drag-release in objects mode, _selected_object_info.bbox must update to the
    preview rect immediately — without requiring another click."""
    view = _make_view()
    view.current_mode = "objects"

    original_bbox = fitz.Rect(20, 20, 120, 80)
    new_bbox = fitz.Rect(50, 50, 150, 110)

    hit = _make_object_hit(kind="rect", supports_rotate=False)
    view._selected_object_info = hit
    view._selected_object_infos = {hit.object_id: hit}
    view._selected_object_page_idx = 0

    # Simulate mid-drag state
    view._object_drag_active = True
    view._object_drag_pending = False
    view._object_drag_preview_rect = fitz.Rect(new_bbox)
    view._object_drag_start_doc_rect = fitz.Rect(original_bbox)
    view._object_drag_preview_rects = None  # single-select path

    # Wire up required signals and helpers
    move_signal = _FakeSignal()
    view.sig_move_object = move_signal
    visuals_calls: list[object] = []
    view._update_object_selection_visuals = lambda rect=None: visuals_calls.append(rect)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    # Signal must have been emitted with the new rect
    assert len(move_signal.emitted) == 1

    # _selected_object_info.bbox must reflect the preview rect immediately
    updated = view._selected_object_info
    assert updated is not None, "_selected_object_info was cleared after move"
    assert abs(updated.bbox.x0 - new_bbox.x0) < 0.5, (
        f"bbox.x0 not updated: expected {new_bbox.x0}, got {updated.bbox.x0}"
    )
    assert abs(updated.bbox.y0 - new_bbox.y0) < 0.5, (
        f"bbox.y0 not updated: expected {new_bbox.y0}, got {updated.bbox.y0}"
    )

    # Selection visuals must have been refreshed
    assert len(visuals_calls) >= 1, "_update_object_selection_visuals was not called after move"


def test_objects_mode_move_release_rebases_when_preview_rects_populated(monkeypatch) -> None:
    """Real production path: press populates _object_drag_start_doc_rects as a dict,
    so drag-release takes the multi-branch even for a single selection.
    That branch must still rebase _selected_object_info, _selected_object_infos,
    _object_drag_start_doc_rects, and refresh visuals."""
    view = _make_view()
    view.current_mode = "objects"

    original_bbox = fitz.Rect(20, 20, 120, 80)
    new_bbox = fitz.Rect(50, 50, 150, 110)

    hit = _make_object_hit(kind="image", supports_rotate=False)
    view._selected_object_info = hit
    view._selected_object_infos = {hit.object_id: hit}
    view._selected_object_page_idx = 0

    # Mid-drag state as produced by the real press + move code paths:
    view._object_drag_active = True
    view._object_drag_pending = False
    view._object_drag_start_doc_rect = fitz.Rect(original_bbox)
    view._object_drag_preview_rect = fitz.Rect(new_bbox)
    view._object_drag_start_doc_rects = {hit.object_id: fitz.Rect(original_bbox)}
    view._object_drag_preview_rects = {hit.object_id: fitz.Rect(new_bbox)}

    move_signal = _FakeSignal()
    view.sig_move_object = move_signal
    visuals_calls: list[object] = []
    view._update_object_selection_visuals = lambda rect=None: visuals_calls.append(rect)

    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    # A BatchMoveObjectsRequest must have been emitted once.
    assert len(move_signal.emitted) == 1

    # _selected_object_info must reflect the new rect immediately.
    updated = view._selected_object_info
    assert updated is not None, "_selected_object_info was cleared after move"
    assert abs(updated.bbox.x0 - new_bbox.x0) < 0.5
    assert abs(updated.bbox.y0 - new_bbox.y0) < 0.5
    assert abs(updated.bbox.x1 - new_bbox.x1) < 0.5
    assert abs(updated.bbox.y1 - new_bbox.y1) < 0.5

    # _selected_object_infos entry rebased too.
    infos_entry = view._selected_object_infos[hit.object_id]
    assert abs(infos_entry.bbox.x0 - new_bbox.x0) < 0.5
    assert abs(infos_entry.bbox.y1 - new_bbox.y1) < 0.5

    # Drag-start rects rebased so the next drag starts from the new position.
    rebased = view._object_drag_start_doc_rects[hit.object_id]
    assert abs(rebased.x0 - new_bbox.x0) < 0.5
    assert abs(rebased.y1 - new_bbox.y1) < 0.5

    # Visuals were refreshed on the new rect.
    assert len(visuals_calls) >= 1, "_update_object_selection_visuals not called after multi-branch move"

    # Preview-rects dict cleared so stale data doesn't leak into the next drag.
    assert getattr(view, "_object_drag_preview_rects", None) is None


def test_add_image_object_clears_stale_object_selection_in_view() -> None:
    """Inserting an image must clear any stale object selection in the view, so the user's
    next click on the freshly-inserted image is not consumed by lingering resize handles
    from a previously-selected object.

    Regression: after Image-Manipulation-Behavior-Fixes, users reported that newly-inserted
    images "rarely react" to clicks in objects mode — caused by stale handle items in the
    scene from a prior selection intercepting the press.
    """
    import importlib

    pdf_controller = importlib.import_module("controller.pdf_controller")

    # Build a minimal fake view exposing only what add_image_object touches.
    cleared = {"called": False}

    class _FakeView:
        continuous_pages = True
        page_items: list = []
        scale = 1.0

        def _clear_object_selection(self) -> None:
            cleared["called"] = True

        def scroll_to_page(self, idx, emit_viewport_changed=False):
            pass

    class _FakeModel:
        def __init__(self) -> None:
            self.doc = [object()]  # len(doc) == 1
            self.command_manager = SimpleNamespace(
                record=lambda cmd: None,
                can_undo=lambda: False,
                can_redo=lambda: False,
                _undo_stack=[],
                _redo_stack=[],
            )

        def _capture_doc_snapshot(self) -> bytes:
            return b""

        def add_image_object(self, page_num, rect, image_bytes, *, rotation=0):
            return "obj-new"

        def get_active_session_id(self):
            return None

    controller = pdf_controller.PDFController.__new__(pdf_controller.PDFController)
    controller.model = _FakeModel()
    controller.view = _FakeView()
    controller._invalidate_active_render_state = lambda clear_page_sizes=False: None
    controller._update_undo_redo_tooltips = lambda: None
    controller.show_page = lambda idx: None

    from model.object_requests import InsertImageObjectRequest

    controller.add_image_object(
        InsertImageObjectRequest(
            page_num=1,
            visual_rect=fitz.Rect(100, 100, 200, 200),
            image_bytes=b"\x89PNG\r\n",
            rotation=0,
        )
    )

    assert cleared["called"], (
        "controller.add_image_object must call view._clear_object_selection() to drop "
        "stale resize handles before the user clicks the freshly-inserted image"
    )


# --- F15-1: an object selection never outlives the document state it was made on ---
#
# Native image ids are positional (``native_image:<page>:<occurrence>``) and app
# objects resolve through the page number, so a selection kept across a page
# delete / insert / reorder / rotate, a tab switch or an undo made Delete act on
# whatever object now sits at those coordinates (a native image on a DIFFERENT
# page), or silently do nothing.  Real model + view + controller, no stubs on
# the paths the fix runs through.

_RED = (255, 0, 0)
_BLUE = (0, 0, 255)
_GREEN = (0, 160, 0)


def _solid_png(rgb: tuple[int, int, int], size: tuple[int, int] = (8, 8)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, *size), False)
    pix.set_rect(pix.irect, rgb)
    return pix.tobytes("png")


def _blank_pdf(path: Path) -> Path:
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def _make_image_pdf(path: Path, pages: list[tuple[str, list[tuple[tuple[int, int, int], fitz.Rect]]]]) -> Path:
    doc = fitz.open()
    try:
        for label, images in pages:
            page = doc.new_page()
            page.insert_text((72, 72), label, fontsize=12)
            for rgb, rect in images:
                page.insert_image(rect, stream=_solid_png(rgb))
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _four_page_image_pdf(path: Path) -> Path:
    box = fitz.Rect(100, 100, 200, 200)
    return _make_image_pdf(
        path,
        [
            ("page one", []),
            ("page two", [(_RED, box)]),
            ("page three", [(_BLUE, box)]),
            ("page four", [(_GREEN, box)]),
        ],
    )


def _page_images(doc) -> list[tuple[str, list[tuple[int, int, int]]]]:
    out = []
    for page in doc:
        colors = []
        for info in page.get_image_info(xrefs=True):
            pix = fitz.Pixmap(doc, info["xref"])
            colors.append(tuple(pix.pixel(0, 0)[:3]))
        out.append((page.get_text().strip(), sorted(colors)))
    return out


def _undo_types(model) -> list[str]:
    return [getattr(c, "_command_type", type(c).__name__) for c in model.command_manager._undo_stack]


@pytest.fixture
def _real_mvc(qapp, monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: errors.append(text))
    monkeypatch.setattr(controller_module.QMessageBox, "information", lambda *a, **k: None)
    model = PDFModel()
    view = pdf_view.PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    try:
        yield model, view, controller, errors
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def _select_like_press(view, controller, page_num: int, point: fitz.Point):
    """Build the selection state the objects-mode press handler builds."""
    info = controller.get_object_info_at_point(page_num, point)
    assert info is not None
    view._selected_object_infos = {str(info.object_id): info}
    view._selected_object_page_idx = page_num - 1
    view._select_object(info)
    assert view._selected_object_info is info
    return info


def _press_delete(view, qapp) -> None:
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
    qapp.processEvents()


def _assert_selection_dropped(view) -> None:
    assert view._selected_object_info is None
    assert view._selected_object_infos == {}
    assert view._selected_object_page_idx is None


def _open_four_pages_in_objects_mode(controller, view, qapp, tmp_path) -> None:
    controller.open_pdf(str(_four_page_image_pdf(tmp_path / "four.pdf")))
    qapp.processEvents()
    view.set_mode("objects")


def test_page_delete_drops_object_selection_so_delete_cannot_hit_shifted_image(_real_mvc, qapp, tmp_path) -> None:
    model, view, controller, errors = _real_mvc
    _open_four_pages_in_objects_mode(controller, view, qapp, tmp_path)
    info = _select_like_press(view, controller, 3, fitz.Point(150, 150))
    assert info.object_id == "native_image:3:0"

    view._delete_specific_pages([1])  # the thumbnail context menu's delete-this-page action
    qapp.processEvents()
    after_page_delete = _page_images(model.doc)
    assert after_page_delete == [("page two", [_RED]), ("page three", [_BLUE]), ("page four", [_GREEN])]

    _press_delete(view, qapp)

    # Before the fix: GREEN (old p4, now p3) was deleted and BLUE stayed.
    assert _page_images(model.doc) == after_page_delete
    assert _undo_types(model) == ["delete_pages"]
    assert errors == []
    _assert_selection_dropped(view)


def _op_delete_first_page(model, view, controller, tmp_path) -> None:
    controller.delete_pages([1])


def _op_insert_blank_before(model, view, controller, tmp_path) -> None:
    controller.insert_blank_page(1)


def _op_reorder(model, view, controller, tmp_path) -> None:
    controller.reorder_page(3, 0)


def _op_rotate_page(model, view, controller, tmp_path) -> None:
    controller.rotate_pages([3], 90)


def _op_open_other_tab(model, view, controller, tmp_path) -> None:
    controller.open_pdf(str(_four_page_image_pdf(tmp_path / "other.pdf")))


def _op_zoom(model, view, controller, tmp_path) -> None:
    controller.change_scale(view.current_page, 1.5)


@pytest.mark.parametrize(
    ("op", "expected_last"),
    [
        (_op_delete_first_page, "delete_pages"),
        (_op_insert_blank_before, "insert_blank_page"),
        (_op_reorder, "move_page"),
        (_op_rotate_page, "rotate_pages"),
        (_op_open_other_tab, None),
        (_op_zoom, None),
    ],
    ids=["delete_pages", "insert_blank_page", "reorder_page", "rotate_pages", "tab_switch", "zoom_rebuild"],
)
def test_scene_rebuild_drops_object_selection_and_delete_is_a_no_op(
    _real_mvc, qapp, tmp_path, op, expected_last
) -> None:
    model, view, controller, errors = _real_mvc
    _open_four_pages_in_objects_mode(controller, view, qapp, tmp_path)
    _select_like_press(view, controller, 3, fitz.Point(150, 150))

    op(model, view, controller, tmp_path)
    qapp.processEvents()
    _assert_selection_dropped(view)
    images_before_delete = _page_images(model.doc)
    undo_before_delete = _undo_types(model)
    if expected_last is not None:
        assert undo_before_delete[-1] == expected_last

    _press_delete(view, qapp)

    assert _page_images(model.doc) == images_before_delete
    assert _undo_types(model) == undo_before_delete
    assert errors == []


def test_structural_undo_drops_object_selection(_real_mvc, qapp, tmp_path) -> None:
    model, view, controller, errors = _real_mvc
    _open_four_pages_in_objects_mode(controller, view, qapp, tmp_path)
    controller.delete_pages([1])
    qapp.processEvents()
    info = _select_like_press(view, controller, 2, fitz.Point(150, 150))  # BLUE, now on p2
    assert info.object_id == "native_image:2:0"

    controller.undo()  # page one comes back: BLUE is on p3 again, RED on p2
    qapp.processEvents()
    _assert_selection_dropped(view)

    _press_delete(view, qapp)

    assert _page_images(model.doc) == [
        ("page one", []),
        ("page two", [_RED]),
        ("page three", [_BLUE]),
        ("page four", [_GREEN]),
    ]
    assert errors == []


def test_same_page_undo_drops_object_selection_of_renumbered_native_image(_real_mvc, qapp, tmp_path) -> None:
    """Undo restores an image on the selected image's page and renumbers occurrences."""
    model, view, controller, errors = _real_mvc
    path = _make_image_pdf(
        tmp_path / "two-images.pdf",
        [("only page", [(_RED, fitz.Rect(100, 100, 200, 200)), (_BLUE, fitz.Rect(300, 300, 400, 400))])],
    )
    controller.open_pdf(str(path))
    qapp.processEvents()
    view.set_mode("objects")

    red = _select_like_press(view, controller, 1, fitz.Point(150, 150))
    assert red.object_id == "native_image:1:0"
    _press_delete(view, qapp)
    assert _page_images(model.doc) == [("only page", [_BLUE])]

    blue = _select_like_press(view, controller, 1, fitz.Point(350, 350))
    assert blue.object_id == "native_image:1:0"  # BLUE moved up to occurrence 0

    controller.undo()  # RED is back as occurrence 0
    qapp.processEvents()
    assert _page_images(model.doc) == [("only page", sorted([_RED, _BLUE]))]

    _press_delete(view, qapp)

    # Before the fix: the stale native_image:1:0 deleted RED, not the selected BLUE.
    assert _page_images(model.doc) == [("only page", sorted([_RED, _BLUE]))]
    assert _undo_types(model) == []
    assert errors == []
    _assert_selection_dropped(view)


def test_app_object_selection_dropped_after_page_delete(_real_mvc, qapp, tmp_path) -> None:
    """A UUID app object moved to another page number: Delete used to be a silent no-op."""
    model, view, controller, errors = _real_mvc
    controller.open_pdf(str(_four_page_image_pdf(tmp_path / "four.pdf")))
    qapp.processEvents()
    controller.add_rect(3, fitz.Rect(100, 300, 200, 400), (1, 0, 0, 1), None, 2.0)
    qapp.processEvents()
    view.set_mode("objects")
    info = _select_like_press(view, controller, 3, fitz.Point(150, 350))
    assert info.object_kind == "rect"

    controller.delete_pages([1])
    qapp.processEvents()

    _assert_selection_dropped(view)
    assert _undo_types(model) == ["add_rect", "delete_pages"]
    assert errors == []


def _mouse_drag(view, qapp, p0, p1) -> None:
    vp = view.graphics_view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p0)
    steps = 6
    for i in range(1, steps + 1):
        QTest.mouseMove(vp, QPoint(p0.x() + (p1.x() - p0.x()) * i // steps, p0.y() + (p1.y() - p0.y()) * i // steps))
        qapp.processEvents()
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p1)
    for _ in range(5):
        qapp.processEvents()


def _doc_to_viewport(view, x: float, y: float) -> QPoint:
    rs = view._render_scale if view._render_scale > 0 else 1.0
    return view.graphics_view.mapFromScene(view._page_scene_x(0) + x * rs, view._page_scene_y(0) + y * rs)


def _object_rects(model) -> list[list[float]]:
    rects = []
    for annot in model.doc[0].annots():
        info = annot.info
        if info.get("subject", "").startswith("pdf_editor_"):
            rects.append([round(v, 1) for v in json.loads(info["content"])["rect"]])
    return rects


@pytest.mark.parametrize("kind", ["rect", "image"])
@pytest.mark.parametrize("step", ["undo", "redo"])
def test_history_step_of_object_move_drops_frame_and_handles_so_handle_drag_cannot_relocate(
    _real_mvc, qapp, tmp_path, kind, step
) -> None:
    """F15-5: Ctrl+Z / Ctrl+Y of a mouse move used to keep the selection frame and its 8
    resize handles at the old position; dragging the stale BR handle then moved the object
    there (a 'resize_object' step) because the press reads its start rect from the stale
    selection.  After the step nothing may be selected and no handle may remain in the scene."""
    model, view, controller, errors = _real_mvc
    controller.open_pdf(str(_blank_pdf(tmp_path / "blank.pdf")))
    view.resize(1200, 900)
    view.show()
    qapp.processEvents()
    if kind == "rect":
        controller.add_rect(1, fitz.Rect(100, 100, 200, 160), (1, 0, 0, 1), (1, 0, 0, 1), 1.0)
    else:
        model.add_image_object(1, fitz.Rect(100, 100, 200, 160), _solid_png(_RED))
        controller._invalidate_active_render_state()
        controller.show_page(0)
    for _ in range(10):
        qapp.processEvents()
    view.set_mode("objects")
    qapp.processEvents()
    assert _object_rects(model) == [[100.0, 100.0, 200.0, 160.0]]

    centre = _doc_to_viewport(view, 150, 130)
    _mouse_drag(view, qapp, centre, QPoint(centre.x() + 100, centre.y() + 100))
    assert _object_rects(model) == [[200.0, 200.0, 300.0, 260.0]]
    assert view._selected_object_info is not None
    assert len(view._object_resize_handle_items) == 8
    steps_before = _undo_types(model)

    if step == "undo":
        controller.undo()
        expected = [[100.0, 100.0, 200.0, 160.0]]
    else:
        controller.undo()
        qapp.processEvents()
        # Re-select the object at its restored position the way a click does, then redo.
        _select_like_press(view, controller, 1, fitz.Point(150, 130))
        assert len(view._object_resize_handle_items) == 8
        controller.redo()
        expected = [[200.0, 200.0, 300.0, 260.0]]
    for _ in range(10):
        qapp.processEvents()

    assert _object_rects(model) == expected
    _assert_selection_dropped(view)
    assert view._object_selection_rect_item is None
    assert view._object_resize_handle_items == []
    assert view._object_rotate_handle_item is None

    # A press where the stale BR handle used to be must not resize/move anything.
    stale_br = _doc_to_viewport(view, 300, 260) if step == "undo" else _doc_to_viewport(view, 200, 160)
    _mouse_drag(view, qapp, stale_br, QPoint(stale_br.x() + 20, stale_br.y() + 20))
    assert _object_rects(model) == expected
    assert "resize_object" not in _undo_types(model)
    assert errors == []
    assert steps_before  # the move itself was recorded


# --- D-OBJ-FRAME: a refused object op must not move the selection frame --------------------
#
# The View used to rebase / rotate its selection frame right after emitting the request,
# whatever the Controller then did.  A refused move / resize / rotate (D-OLD-MARKERS) left
# the frame at the requested place while the object stayed, so the next press hit-tested the
# wrong area.  The Controller now names the refused object ids back to the View
# (``note_object_op_refused``) during the synchronous emit; the View follows only the ops
# that were not refused.


def _age_twin_marker(model, object_id: str, rect: fitz.Rect) -> None:
    """Age the marker of ``object_id`` so its xref/digest no longer locates it (the stale
    marker fixture of the D-OLD-MARKERS tests): a move of it refuses IMAGE_NOT_LOCATED."""
    for annot in model.doc[0].annots() or []:
        payload = json.loads(annot.info.get("content") or "{}")
        if payload.get("object_id") == object_id:
            payload["rect"] = [rect.x0, rect.y0, rect.x1, rect.y1]
            annot.set_rect(rect)
            annot.set_info(content=json.dumps(payload), subject="pdf_editor_image_object")
            annot.update()
            return
    raise AssertionError(f"no marker {object_id}")


def test_real_refused_mouse_move_leaves_frame_on_the_object(_real_mvc, qapp, tmp_path) -> None:
    """Real model + controller + view, real mouse drag: two same-digest placements, the
    second marker aged, so the drag refuses.  The frame stays on the object, and the next
    drag starts from the real place."""
    model, view, controller, errors = _real_mvc
    controller.open_pdf(str(_blank_pdf(tmp_path / "twins.pdf")))
    view.resize(1200, 900)
    view.show()
    qapp.processEvents()
    wide = _solid_png((0, 160, 0), (20, 10))
    placed = fitz.Rect(100, 100, 200, 175)
    model.add_image_object(1, placed, wide, rotation=0)
    second = model.add_image_object(1, placed, wide, rotation=0)
    _age_twin_marker(model, second, placed)
    controller._invalidate_active_render_state()
    controller.show_page(0)
    for _ in range(10):
        qapp.processEvents()
    view.set_mode("objects")
    qapp.processEvents()

    centre = _doc_to_viewport(view, 150, 137)
    _mouse_drag(view, qapp, centre, QPoint(centre.x() + 100, centre.y() + 100))

    assert len(errors) == 1, errors  # the refusal is reported once (D-OLD-MARKERS)
    assert model.last_object_op_refusal is not None
    assert view._selected_object_info is not None
    frame = view._selected_object_info.bbox
    hit = controller.get_object_info_at_point(1, fitz.Point(150, 137))
    assert hit is not None
    assert list(frame) == pytest.approx(list(hit.bbox), abs=1.5), (frame, hit.bbox)
    assert list(frame) == pytest.approx(list(placed), abs=1.5)
    assert list(view._object_drag_start_doc_rect) == pytest.approx(list(placed), abs=1.5)


class _ControllerWiredSignal(_FakeSignal):
    """Stands in for the Qt connection ``view.sig_* -> controller.<slot>`` (direct, so the
    slot runs inside ``emit``, as in the app)."""

    def __init__(self, slot) -> None:
        super().__init__()
        self._slot = slot

    def emit(self, *args) -> None:
        super().emit(*args)
        self._slot(*args)


def _wired_view(monkeypatch, refused: set[str], mode: str = "objects"):
    """A fake-geometry view whose move / resize / rotate signals run the REAL controller
    slots over a model that refuses the object ids in ``refused``."""
    from test_object_controller_flow import _refusing_controller

    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _p, _t, text, *a, **k: shown.append(str(text)) or QMessageBox.StandardButton.Ok),
    )
    view = _make_view()
    view.current_mode = mode
    view._update_object_selection_visuals = lambda rect=None: None
    controller = _refusing_controller(refused, ObjectOpRefusal.IMAGE_NOT_LOCATED)
    controller.view = view
    view.sig_move_object = _ControllerWiredSignal(controller.move_object)
    view.sig_resize_object = _ControllerWiredSignal(controller.resize_object)
    view.sig_rotate_object = _ControllerWiredSignal(controller.rotate_object)
    monkeypatch.setattr(pdf_view.QGraphicsView, "mouseReleaseEvent", lambda *a, **kw: None)
    return view, controller, shown


def _hit(object_id: str, bbox: fitz.Rect, kind: str = "image", rotation: float = 0) -> ObjectHitInfo:
    return ObjectHitInfo(
        object_kind=kind,
        object_id=object_id,
        page_num=1,
        bbox=fitz.Rect(bbox),
        rotation=rotation,
        supports_move=True,
        supports_delete=True,
        supports_rotate=True,
    )


_START = fitz.Rect(20, 20, 120, 80)
_REQUESTED = fitz.Rect(50, 50, 150, 110)


def _arm_single_drag(view, hit, *, with_preview_rects: bool) -> None:
    view._selected_object_info = hit
    view._selected_object_infos = {hit.object_id: hit}
    view._selected_object_page_idx = 0
    view._object_drag_active = True
    view._object_drag_pending = False
    view._object_drag_start_doc_rect = fitz.Rect(_START)
    view._object_drag_preview_rect = fitz.Rect(_REQUESTED)
    view._object_drag_start_doc_rects = {hit.object_id: fitz.Rect(_START)}
    view._object_drag_preview_rects = {hit.object_id: fitz.Rect(_REQUESTED)} if with_preview_rects else None


@pytest.mark.parametrize(
    ("mode", "with_preview_rects"),
    [("objects", False), ("objects", True), ("browse", False)],
)
def test_refused_single_move_keeps_frame_at_object(monkeypatch, mode, with_preview_rects) -> None:
    view, controller, shown = _wired_view(monkeypatch, {"obj-1"}, mode=mode)
    hit = _hit("obj-1", _START)
    _arm_single_drag(view, hit, with_preview_rects=with_preview_rects)

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    assert len(shown) == 1, shown
    assert list(view._selected_object_info.bbox) == list(_START)
    assert list(view._selected_object_infos["obj-1"].bbox) == list(_START)
    assert list(view._object_drag_start_doc_rect) == list(_START)
    assert list(view._object_drag_preview_rect) == list(_START)
    assert controller.model.command_manager.recorded == []


@pytest.mark.parametrize(("mode", "with_preview_rects"), [("objects", False), ("objects", True), ("browse", False)])
def test_successful_single_move_still_rebases_frame(monkeypatch, mode, with_preview_rects) -> None:
    view, controller, shown = _wired_view(monkeypatch, set(), mode=mode)
    hit = _hit("obj-1", _START)
    _arm_single_drag(view, hit, with_preview_rects=with_preview_rects)

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    assert shown == []
    assert list(view._selected_object_info.bbox) == list(_REQUESTED)
    assert len(controller.model.command_manager.recorded) == 1


def test_partly_refused_batch_move_rebases_only_the_moved_objects(monkeypatch) -> None:
    view, controller, shown = _wired_view(monkeypatch, {"obj-2"})
    one, two = _hit("obj-1", _START), _hit("obj-2", fitz.Rect(200, 20, 300, 80))
    view._selected_object_info = None  # multi-select keeps no single selection
    view._selected_object_infos = {"obj-1": one, "obj-2": two}
    view._selected_object_page_idx = 0
    view._object_drag_active = True
    view._object_drag_pending = False
    view._object_drag_start_doc_rect = fitz.Rect(_START)
    view._object_drag_preview_rect = fitz.Rect(_REQUESTED)
    view._object_drag_start_doc_rects = {k: fitz.Rect(v.bbox) for k, v in view._selected_object_infos.items()}
    view._object_drag_preview_rects = {
        "obj-1": fitz.Rect(_REQUESTED),
        "obj-2": fitz.Rect(230, 50, 330, 110),
    }

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    assert len(shown) == 1, shown
    assert list(view._selected_object_infos["obj-1"].bbox) == list(_REQUESTED)
    assert list(view._selected_object_infos["obj-2"].bbox) == [200.0, 20.0, 300.0, 80.0]
    assert list(view._object_drag_start_doc_rects["obj-2"]) == [200.0, 20.0, 300.0, 80.0]
    assert list(view._object_drag_start_doc_rects["obj-1"]) == list(_REQUESTED)


@pytest.mark.parametrize("refused", [True, False])
def test_resize_release_follows_only_an_accepted_resize(monkeypatch, refused) -> None:
    view, controller, shown = _wired_view(monkeypatch, {"obj-1"} if refused else set())
    hit = _hit("obj-1", _START)
    view._selected_object_info = hit
    view._selected_object_infos = {"obj-1": hit}
    view._object_resize_pending = True
    view._object_resize_active = True
    view._object_resize_start_doc_rect = fitz.Rect(_START)
    view._object_resize_preview_rect = fitz.Rect(20, 20, 160, 100)

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    assert len(shown) == (1 if refused else 0), shown
    expected = list(_START) if refused else [20.0, 20.0, 160.0, 100.0]
    assert list(view._selected_object_info.bbox) == expected


@pytest.mark.parametrize("refused", [True, False])
def test_absolute_and_stepped_rotation_follow_only_an_accepted_rotate(monkeypatch, refused) -> None:
    view, controller, shown = _wired_view(monkeypatch, {"obj-1"} if refused else set())
    view._selected_object_info = _hit("obj-1", _START, rotation=0.0)

    result = view._rotate_selected_object_absolute(90.0)

    assert result is (not refused)
    assert len(shown) == (1 if refused else 0), shown
    assert view._selected_object_info.rotation == (0.0 if refused else 90.0)

    view._rotate_selected_object(90)

    assert view._selected_object_info.rotation == (0.0 if refused else 180.0)


@pytest.mark.parametrize("refused", [True, False])
def test_free_rotation_commit_follows_only_an_accepted_rotate(monkeypatch, refused) -> None:
    view, controller, shown = _wired_view(monkeypatch, {"obj-1"} if refused else set())
    view._selected_object_info = _hit("obj-1", _START, rotation=0.0)
    view._object_rotate_start_rotation = 0.0
    view._object_rotate_start_angle = 0.0
    view._object_rotate_preview_angle = 90.0  # clockwise quarter turn -> stored 270

    view._commit_free_rotation()

    assert len(shown) == (1 if refused else 0), shown
    assert view._selected_object_info.rotation == (0.0 if refused else 270.0)
    assert view._object_rotate_preview_angle == 0.0


def test_a_refusal_outside_an_emit_does_not_poison_the_next_successful_move(monkeypatch) -> None:
    """The refused-id set lives only for one synchronous emit: a refusal reported while no
    op is in flight (a direct controller call) must not suppress a later rebase."""
    view, controller, shown = _wired_view(monkeypatch, set())
    view.note_object_op_refused(["obj-1"])
    hit = _hit("obj-1", _START)
    _arm_single_drag(view, hit, with_preview_rects=False)

    pdf_view.PDFView._mouse_release(view, _FakeEvent(150, 110))

    assert list(view._selected_object_info.bbox) == list(_REQUESTED)
