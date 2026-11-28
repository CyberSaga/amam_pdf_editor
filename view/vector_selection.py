"""View side of the internal vector delete (card B7): the click, the Del key and the right-click entry in the
"vector" mode, and the highlight of what the controller reports as selected.

The view never calls the model.  It emits primitive-typed signals; the controller answers with
show_vector_selection / clear_vector_selection.  Every delete intent carries the token of the selection
that was DISPLAYED when the key was pressed or the menu was opened, so an intent built on an older selection is
recognised as stale by the controller instead of acting on whatever is selected now.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
import shiboken6
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QMenu

if TYPE_CHECKING:
    from view.pdf_view import PDFView

_CLICK_SLOP = 4.0  # scene pixels: a press and release closer than this is a click, not a drag
_HIT_TOLERANCE_PX = 3.0  # the click tolerance on screen, converted to page units with the render scale


class VectorSelectionManager:
    def __init__(self, view: PDFView) -> None:
        self._view = view
        self.token: int | None = None
        self.page_num: int = 0
        self.count: int = 0
        self.supports_delete: bool = False
        self._bbox: tuple[float, float, float, float] | None = None
        self._rect_item = None
        self._press_scene: QPointF | None = None

    # ------------------------------------------------------------------ what the controller reports

    def set_selection(self, page_num: int, token: int, bbox, count: int, supports_delete: bool) -> None:
        self.page_num, self.token, self.count = int(page_num), int(token), int(count)
        self.supports_delete = bool(supports_delete)
        self._bbox = tuple(float(v) for v in bbox) if bbox is not None else None  # type: ignore[assignment]
        self.redraw()

    def clear(self) -> None:
        self.token, self.count, self.supports_delete, self._bbox = None, 0, False, None
        self._remove_item()

    def redraw(self) -> None:
        """Draw the highlight again (a scene rebuild deletes the C++ item and leaves the wrapper dangling)."""
        self._remove_item()
        view = self._view
        if self._bbox is None or getattr(view, "scene", None) is None or self.page_num <= 0:
            return
        scene_rect = view._doc_rect_to_scene_rect(self.page_num - 1, fitz.Rect(*self._bbox))
        pen = QPen(QColor(220, 38, 38, 230), 2)
        pen.setCosmetic(True)
        item = view.scene.addRect(scene_rect, pen, QBrush(QColor(220, 38, 38, 36)))
        item.setZValue(21)
        self._rect_item = item

    def _remove_item(self) -> None:
        item, self._rect_item = self._rect_item, None
        if item is not None and shiboken6.isValid(item):
            try:
                self._view.scene.removeItem(item)
            except Exception:
                pass

    # ------------------------------------------------------------------ gestures

    def handle_press(self, event, scene_pos: QPointF) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        self._press_scene = QPointF(scene_pos)
        event.accept()
        return True

    def handle_release(self, event) -> bool:
        if event.button() != Qt.LeftButton or self._press_scene is None:
            return False
        start, self._press_scene = self._press_scene, None
        end = self._view._event_scene_pos(event)
        event.accept()
        if (end - start).manhattanLength() >= _CLICK_SLOP:
            return True  # a drag (marquee) is not part of this card
        page_idx, point = self._view._scene_pos_to_page_and_doc_point(end)
        scale = self._view._render_scale if self._view._render_scale > 0 else 1.0
        combine = "toggle" if event.modifiers() & Qt.ShiftModifier else "replace"
        self._view.sig_vector_select.emit(page_idx + 1, float(point.x), float(point.y), _HIT_TOLERANCE_PX / scale, combine)
        return True

    def delete_pressed(self) -> bool:
        """Del / Backspace in the vector mode.  True (the key is consumed) whenever a vector selection is displayed,
        even if the controller refuses the delete: it must never fall through to the object delete."""
        if self.token is None:
            return False
        self._view.sig_vector_delete.emit(int(self.token))
        return True

    # ------------------------------------------------------------------ right-click menu

    def build_menu(self) -> QMenu:
        """The menu for the selection displayed NOW; its actions keep this token."""
        token = self.token
        menu = QMenu()
        delete = menu.addAction("刪除")
        delete.setEnabled(token is not None and self.supports_delete)
        delete.triggered.connect(lambda _checked=False, t=token: self._view.sig_vector_delete.emit(int(t)) if t is not None else None)
        clear = menu.addAction("取消選取")
        clear.setEnabled(token is not None)
        clear.triggered.connect(lambda _checked=False: self._view.sig_vector_clear.emit())
        return menu

    def show_menu(self, pos) -> None:
        menu = self.build_menu()
        graphics_view = getattr(self._view, "graphics_view", None)
        menu.exec_(graphics_view.mapToGlobal(pos) if graphics_view is not None else pos)
