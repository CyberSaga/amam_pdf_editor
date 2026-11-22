"""The one chokepoint of the view's interaction epoch (A6.5).

A pending text-edit press may replay only for the exact moment of the press.  Instead of listing
every interaction that ends that moment, one application-level event filter, scoped to the
view's window, bumps the epoch on ANY user input that is not part of the pressing gesture itself.
``view.bump_interaction_epoch()`` is the only thing it calls.

Bumps: any mouse press / double click (any button, any widget of the window), key press, context
menu, shortcut, a wheel WITHOUT Ctrl, and focus moving to or from any widget other than the graphics
view.  Does not bump: mouse move / hover, the release of the same press, paint, timers, Ctrl+wheel
(zoom), a bare modifier key press (Ctrl/Shift/Alt/Meta).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from view.pdf_view import PDFView

logger = logging.getLogger(__name__)

_ALWAYS_BUMP = frozenset(
    {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.KeyPress,
        QEvent.Type.ContextMenu,
        QEvent.Type.Shortcut,
        QEvent.Type.ShortcutOverride,
    }
)
_OBJECT_CLICK_ENDERS = frozenset({QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress})
_KEYS = frozenset({QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride})
_MODIFIER_KEYS = frozenset({Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr})
_FOCUS = frozenset({QEvent.Type.FocusIn, QEvent.Type.FocusOut})


class InteractionEpochFilter(QObject):
    def __init__(self, view: PDFView) -> None:
        super().__init__(view)
        self._view = view

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        kind = event.type()
        if kind not in _ALWAYS_BUMP and kind not in _FOCUS and kind != QEvent.Type.Wheel:
            return False
        view = self._view
        if not isinstance(obj, QWidget) or obj.window() is not view:
            return False
        if kind in _KEYS and event.key() in _MODIFIER_KEYS:
            return False  # a bare modifier (Ctrl before a zoom wheel) is not an interaction
        if kind == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return False
        elif kind in _FOCUS:
            graphics_view = getattr(view, "graphics_view", None)
            if graphics_view is not None and (obj is graphics_view or obj is graphics_view.viewport()):
                return False
        view.bump_interaction_epoch()
        if kind in _OBJECT_CLICK_ENDERS:
            # H23 finding 2, class closure: a pending object lookup is stale after ANY newer press or
            # key press of the window, not only a press on the viewport.  Wheel, scroll and zoom keep it.
            view._ensure_object_selection_manager().bump_object_click_generation()
        return False
