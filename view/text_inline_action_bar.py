"""Inline action bar shown beside the live text editor (R4-2).

Apply / Cancel, the plan-preview refusal reason and the "rebuild text" consent
button used to live in the right sidebar, which the owner had dragged to 0 px,
so a refused input showed nothing.  The bar is a child of the graphics view's
viewport and is placed next to the editor by :func:`compute_inline_action_bar_pos`.

Two rows (round 6, P1): row 0 is the :class:`~view.text_live_strip.LiveTextStrip`
(a legible mirror of the hidden editor with caret, selection and preedit; visible only for a
plan-preview editor), row 1 the controls (move grip, refusal reason, rebuild consent, Apply,
Cancel).  Every control stays a direct child of the bar.

Two attributes are mandatory and pinned by tests:

* ``WA_NoMousePropagation`` -- without it a press on the bar background walks
  up to the viewport and ``_mouse_press`` treats it as a click outside the
  editor (CLICK_AWAY finalize).
* ``Qt.NoFocus`` on the bar, the move grip and the live strip, and ``Qt.TabFocus``
  (NOT ``StrongFocus``, NOT ``NoFocus``) on Apply / Cancel / rebuild -- a mouse
  press must never move focus out of the editor (FOCUS_OUTSIDE finalize,
  composition reset), but the keyboard must still reach the buttons (Tab, then
  Space); ``PDFView`` chains them after the property card's last control with
  ``QWidget.setTabOrder`` (round 7 / KBD-1).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from view.text_live_strip import LiveTextStrip

logger = logging.getLogger(__name__)

REBUILD_TOOLTIP = "以可用的字型重新寫入這段文字；字型或排版可能改變，套用前會再確認"
MOVE_GRIP_TEXT = "⠿ 移動"
MOVE_GRIP_TOOLTIP = "按住拖曳以移動文字框；移動位置後需要「改用重建文字…」才能套用"


class EditorMoveGrip(QFrame):
    """The visible handle that moves the open editor box (round 6, P2).

    A press/drag INSIDE the box places the caret and selects text, so moving needs
    an explicit grip.  It reports GLOBAL positions (the bar itself follows the box
    while it is dragged, so widget-local coordinates would drift).  Like the bar it
    sits on, it never takes focus and never lets a press fall through to the
    viewport (which would read it as a click outside the editor).
    """

    drag_started = Signal(QPoint)
    drag_moved = Signal(QPoint)
    drag_finished = Signal(QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("textEditorMoveGrip")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_NoMousePropagation, True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(MOVE_GRIP_TOOLTIP)
        self._dragging = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        self._label = QLabel(MOVE_GRIP_TEXT)
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._label.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self._label)

    def text(self) -> str:
        return self._label.text()

    def is_dragging(self) -> bool:
        return self._dragging

    def reset_drag(self) -> None:
        """Drop the press latch without emitting ``drag_finished``.

        The view ends a drag on its own (a keep-finalize completes it, teardown) and a
        modal dialog opened mid-drag can swallow the release, so the latch must never
        depend on a release this widget receives (round 7 / SEQ-1)."""
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)

    def hideEvent(self, event) -> None:
        self.reset_drag()  # a hidden grip (bar hidden, editor torn down) holds no drag
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()
        if event.button() != Qt.LeftButton:
            return
        # A left press can reach a latched grip only when the previous release was lost
        # (modal dialog, Alt+Tab): restart the drag instead of ignoring the gesture (SEQ-1).
        self._dragging = True
        self.setCursor(Qt.ClosedHandCursor)
        self.drag_started.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        event.accept()
        if self._dragging:
            self.drag_moved.emit(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
        if event.button() != Qt.LeftButton or not self._dragging:
            return
        self.reset_drag()
        self.drag_finished.emit(event.globalPosition().toPoint())


class TextInlineActionBar(QFrame):
    """Live text strip (row 0); move grip, status label, rebuild consent, Apply and
    Cancel (row 1)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("textInlineActionBar")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_NoMousePropagation, True)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)

        self.live_text_strip = LiveTextStrip(self)
        self.move_grip = EditorMoveGrip(self)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumWidth(280)
        self.status_label.setHidden(True)
        self.rebuild_btn = QPushButton("改用重建文字…")
        self.rebuild_btn.setToolTip(REBUILD_TOOLTIP)
        self.rebuild_btn.setHidden(True)
        self.apply_btn = QPushButton("套用")
        self.apply_btn.setEnabled(False)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        for button in (self.rebuild_btn, self.apply_btn, self.cancel_btn):
            button.setFocusPolicy(Qt.TabFocus)
            button.setAutoDefault(False)
        for widget in (
            self.move_grip,
            self.status_label,
            self.rebuild_btn,
            self.apply_btn,
            self.cancel_btn,
        ):
            controls.addWidget(widget)
        layout.addWidget(self.live_text_strip)
        layout.addLayout(controls)
        self.setHidden(True)


def _clamp(value: int, lo: int, hi: int) -> int:
    """Clamp ``value`` into ``[lo, hi]``; ``lo`` wins when ``hi < lo``."""
    return max(lo, min(value, hi))


def compute_inline_action_bar_pos(
    editor_rect: QRect,
    bar_size: QSize,
    viewport_rect: QRect,
    *,
    gap: int = 4,
    margin: int = 4,
) -> QPoint | None:
    """Where to put the bar (viewport coordinates), or None when the editor is
    not visible.  Preference: below, above, right, left -- none of which
    overlaps the editor (so the IME cursor rectangle stays uncovered); only the
    last-resort fallback may overlap."""
    if not editor_rect.intersects(viewport_rect):
        return None
    width, height = bar_size.width(), bar_size.height()
    vw, vh = viewport_rect.width(), viewport_rect.height()

    x = _clamp(editor_rect.right() - width + 1, margin, vw - width - margin)
    below = editor_rect.bottom() + 1 + gap
    if below + height + margin <= vh:
        return QPoint(x, below)
    above = editor_rect.top() - gap - height
    if above >= margin:
        return QPoint(x, above)

    side_y = _clamp(editor_rect.bottom() - height + 1, margin, vh - height - margin)
    right = editor_rect.right() + 1 + gap
    if right + width + margin <= vw:
        return QPoint(right, side_y)
    left = editor_rect.left() - gap - width
    if left >= margin:
        return QPoint(left, side_y)
    return QPoint(max(0, vw - width - margin), max(0, vh - height - margin))
