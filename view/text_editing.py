from __future__ import annotations
import logging
import math
import unicodedata
import uuid
from dataclasses import dataclass
from enum import Enum

import fitz
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QInputMethodEvent,
    QPainter,
    QPen,
    QPixmap,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import QApplication, QTextEdit
from shiboken6 import isValid as _qt_object_alive

from model.edit_commands import EditTextResult  # re-exported for view/controller (pure DTO enum, no mutation surface)
from model.edit_requests import EditTextRequest, MoveTextRequest, StyleOverrides  # re-exported for view/controller
from utils.cjk_ext_b_font import ExtBSubsetNotReady, htmlbox_args_with_ext_b
from utils.qt_deferred import call_later
from utils.render_limits import safe_render_scale as _safe_render_scale
from utils.text_chars import OBJECT_REPLACEMENT_CHARACTER, split_unrenderable
from view.ext_b_subset_worker import ExtBSubsetService
from view.text_edit_reasons import (
    effective_rejection_reason,
    rebuild_offered_for,
    rejection_reason_text,
)

logger = logging.getLogger(__name__)

# Counter-rotation (degrees, Qt clockwise-positive) that maps a displayed-space
# raster of the editor's bbox into the proxy-local paint frame of an editor
# proxy rotated by ``setRotation(rotation)`` about its origin corner
# (``_compute_editor_proxy_layout``: 90 -> top-right, 180 -> bottom-right,
# 270 -> bottom-left). Shared by the frozen first frame and the plan preview
# so the two paint paths can never disagree.
PROXY_COUNTER_ROTATION: dict[int, float] = {90: -90.0, 180: 180.0, 270: 90.0}


def _parse_font_size_str(text: str) -> float | None:
    """Parse combo-box font-size text as float; return None on malformed input."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _validated_font_size_input(text: str) -> float | None:
    """Validate a manually-entered font size with at most one decimal place."""
    candidate = str(text).strip()
    parts = candidate.split(".")
    if not candidate or len(parts) > 2:
        return None
    if not parts[0].isascii() or not parts[0].isdigit():
        return None
    if len(parts) == 2 and (
        len(parts[1]) != 1 or not parts[1].isascii() or not parts[1].isdigit()
    ):
        return None
    size = float(candidate)
    if not 1.0 <= size <= 999.9:
        return None
    return size


def _format_font_size(size: float) -> str:
    """Render a font size for the combo box: ``9`` / ``9.5`` — no trailing ``.0``."""
    value = float(size)
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:g}"

_LIGATURE_EXPAND = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

_DEFAULT_EDITOR_MASK_COLOR = QColor("#FFFFFF")
_DARK_EDITOR_MASK_COLOR = QColor("#18181B")
_LIGHT_TEXT_LUMA_THRESHOLD = 180.0
_MASK_RING_THICKNESS_PX = 3
_MASK_MIN_CONTRAST_RATIO = 3.2
_MASK_MAX_TINT_STRENGTH = 0.20
_MASK_TEXTURE_MAX_LEAK_PCT = 0.01
# Round 7 (RPU-2): the origin patch is ONE flat colour, so it is only drawn where the ring around
# the source span is (nearly) uniform: at most this fraction of the ring pixels may differ from
# the ring mean by more than ``_MASK_RING_OUTLIER_L1`` (summed over r, g, b).
_ORIGIN_MASK_MAX_RING_NONUNIFORM_PCT = 0.05
_MASK_RING_OUTLIER_L1 = 48.0
_MASK_TINT_LADDER: tuple[float, ...] = (0.04, 0.08, 0.12, 0.16, _MASK_MAX_TINT_STRENGTH)
# Round 7 (F1): the patch that keeps an edit_existing box's SOURCE SPAN covered while the box
# is displaced.  z 10.5: above page items (0), block outlines (6) and the hover highlight
# (10); below the moving mask (11), the proxy (12) and the focus border (13).
_ORIGIN_MASK_Z = 10.5
# SCN-1: the red search-hit rect display_page draws is above the origin patch (a search jump keeps
# the editor open and lands on the source span the patch covers) but below the moving mask (11).
_SEARCH_HIGHLIGHT_Z = 10.75
_ORIGIN_MASK_MIN_DISPLACEMENT_PX = 0.5
# Glyphs overhang the span bbox a little (CJK ink 1 px outside at 100 %, 2 px at 214 % on the
# ecc-dwg corpus, measured round 7): the patch is the source span plus this many PDF points,
# in scene pixels at least 1.  The cover is then snapped OUTWARD to whole pixels, so each side
# overhangs the span by [max(1, scale), max(1, scale) + 1) scene px: 1-2 pt at 100 %, 2-4 pt at
# 50 % (DOC-1; the docs state this, not a flat 1 pt).
_ORIGIN_MASK_MARGIN_PT = 1.0

MASK_MODE_BACKGROUND_MATCH = "background_match"
MASK_MODE_FALLBACK = "fallback"


def _readable_editor_mask_color(text_rgb: tuple[int, int, int] | None = None) -> QColor:
    """Pick an editor underlay that keeps the text legible: a dark mask under
    light text, the default light mask otherwise. Derived purely from the text
    color (no page sampling) so the underlay is deterministic and never bleeds
    the old glyphs through."""
    if text_rgb is not None:
        r, g, b = [max(0, min(255, int(value))) for value in text_rgb]
        luma = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
        if luma >= _LIGHT_TEXT_LUMA_THRESHOLD:
            return QColor(_DARK_EDITOR_MASK_COLOR)
    return QColor(_DEFAULT_EDITOR_MASK_COLOR)


class TextEditUIConstants:
    MIN_EDITOR_WIDTH_PX = 80
    MIN_EDITOR_HEIGHT_PX = 40
    FOCUS_RESTORE_DELAY_MS = 0
    MASK_SAMPLE_INSET_RATIO = 0.15
    MASK_SAMPLE_INSET_MAX_PX = 6.0
    # QTextEdit has a few px of internal frame/viewport margin; pad so measured
    # natural content height doesn't clip the last line visually.
    EDITOR_CONTENT_PADDING_PX = 8
    MAX_EDITOR_VIEWPORT_HEIGHT_RATIO = 0.6


class TextEditGeometryConstants:
    POSITION_CHANGE_TOLERANCE_PT = 0.5
    DRAG_START_DISTANCE_PX = 3.0


class TextEditFinalizeReason(str, Enum):
    APPLY = "apply"
    CLICK_AWAY = "click_away"
    CANCEL_BUTTON = "cancel_button"
    ESCAPE = "escape"
    SAVE_SHORTCUT = "save_shortcut"
    MODE_SWITCH = "mode_switch"
    FOCUS_OUTSIDE = "focus_outside"
    # Finalize policy completion (part-3 VERIFY defect 3): the user ANSWERED
    # a close prompt with save -- commit a verified edit; anything else keeps
    # the editor and the input and the close is aborted (never silently lost).
    CLOSE_DOCUMENT = "close_document"
    # ... and answered it with discard: the explicit, prompted discard.
    CLOSE_DISCARD = "close_discard"
    # Defect 1: a zoom is about to rebuild the whole scene.  A verified edit
    # commits; un-applied input keeps the editor and the zoom is refused.
    VIEW_RESCALE = "view_rescale"
    # UI step 9: the active document session is about to change (open,
    # tab switch, tab close, detach).  Commits a verified edit against the
    # ORIGINAL session, otherwise discards with a visible warning.
    SESSION_SWITCH = "session_switch"
    # UI step 9: the scene is about to be cleared/rebuilt (``scene.clear()``
    # would delete a kept editor proxy).  Same close-always policy.
    SCENE_REBUILD = "scene_rebuild"
    # Part 5 / A2 (owner decision Q4): F5 is about to enter fullscreen.  Same
    # policy as a zoom: a verified edit commits first; un-applied input keeps
    # the editor and fullscreen is refused.
    FULLSCREEN = "fullscreen"


class TextEditOutcome(str, Enum):
    DISCARDED = "discarded"
    NO_OP = "no_op"
    COMMITTED = "committed"
    FAILED = "failed"
    # UI step 9: the edit was not applied (the Controller refused it, or no
    # verified preview exists yet) and the editor stays open with the input.
    REFUSED = "refused"


class TextEditReason(str, Enum):
    USER_COMMIT = "user_commit"


class TextEditDragState(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    ACTIVE = "active"
    # Round 6 (P2): a LeftButton press inside the open editor is a caret/selection
    # gesture, never a box drag; the box moves only through the action bar's grip.
    SELECTING = "selecting"


@dataclass(frozen=True)
class TextEditDelta:
    text_changed: bool
    style_changed: bool
    position_changed: bool
    page_changed: bool

    @property
    def any_change(self) -> bool:
        return self.text_changed or self.style_changed or self.position_changed or self.page_changed


@dataclass(frozen=True)
class TextEditFinalizeResult:
    reason: TextEditFinalizeReason
    outcome: TextEditOutcome
    intent: str
    edit_page: int
    origin_page: int
    delta: TextEditDelta
    # UI step 9: the Controller's REAL result for this finalize (pulled right
    # after the emit), or None when nothing was emitted / no pull API exists.
    edit_result: EditTextResult | None = None


@dataclass(frozen=True)
class TextEditSession:
    original_rect: fitz.Rect | None
    current_rect: fitz.Rect | None
    current_font: str
    initial_font: str
    original_color: tuple
    current_size: float
    initial_size: float
    edit_page: int
    origin_page: int
    intent: str
    target_span_id: str | None
    target_mode: str
    original_text: str | None
    # UI step 4: the hit's proven source show (opaque DTO), carried verbatim
    # into the preview payload and the EditTextRequest.
    source_ref: object | None = None
    # UI step 9: the document session the editor was opened in.
    session_id: str | None = None


# UI step 9 finalize policy (plan section 3; ui_spec section 8 table; owner
# decision 2026-09-30 "click-away with no verified preview keeps the editor").
# When the edit is NOT applied -- the Controller refused it, or plan preview
# has no current token yet -- these reasons keep the editor and its input:
_KEEP_EDITOR_REASONS = frozenset(
    {
        TextEditFinalizeReason.APPLY,
        TextEditFinalizeReason.SAVE_SHORTCUT,
        TextEditFinalizeReason.CLICK_AWAY,
        TextEditFinalizeReason.FOCUS_OUTSIDE,
        # Finalize policy completion: a cancellable close (answered "save")
        # and a zoom keep un-applied input; the caller aborts its action.
        TextEditFinalizeReason.CLOSE_DOCUMENT,
        TextEditFinalizeReason.VIEW_RESCALE,
        TextEditFinalizeReason.FULLSCREEN,
    }
)
# ... these always discard (an explicit user discard):
_DISCARD_REASONS = frozenset(
    {
        TextEditFinalizeReason.CANCEL_BUTTON,
        TextEditFinalizeReason.ESCAPE,
        TextEditFinalizeReason.CLOSE_DISCARD,
    }
)
# ... and these cannot keep the editor (the scene really is cleared, or the
# mode/session really changes): they commit a verified edit, otherwise
# discard with a visible "not applied" warning -- never silently.  Callers
# must use them only where the editor truly cannot survive (whether a scene
# is cleared depends on the branch taken, not on the caller).
_CLOSE_ALWAYS_REASONS = frozenset(
    {
        TextEditFinalizeReason.MODE_SWITCH,
        TextEditFinalizeReason.SESSION_SWITCH,
        TextEditFinalizeReason.SCENE_REBUILD,
    }
)
_NOT_APPLIED_DISCARD_NOTICE = "文字編輯未套用，輸入已捨棄（文件未變更）"
# Part 5 / A1: an input-method composition (preedit) is un-applied input that
# the plan token (and the text) do not contain.
_COMPOSING_KEPT_NOTICE = "正在組字（輸入法尚未確認）：請先確認或取消組字，編輯框與輸入已保留（文件未變更）"
# The WHOLE edit is discarded (the verified text too), so the notice says so.
_COMPOSING_DISCARD_NOTICE = "輸入已捨棄（含組字中的內容），文件未變更"
# V1 review fix-up 4: Ctrl+S / Save As with an editor that is not applied still
# SAVES the document as it is, so these must not say "文件未變更" (the modal that
# follows says the file was saved).  The toast is shown before the save (and a
# Save As dialog can still be cancelled), hence "the saved file lacks this edit".
_SAVE_NOT_INCLUDED = "（此段編輯未套用，儲存的檔案不含這段編輯）"
_SAVE_NOT_APPLIED_KEPT_NOTICE = (
    "文字編輯尚未套用：預覽仍在更新，編輯框已保留" + _SAVE_NOT_INCLUDED
)
_SAVE_ALREADY_REFUSED_KEPT_NOTICE = (
    "文字編輯尚未套用：這段輸入已被拒絕{detail}，請修改內容或取消；編輯框與輸入已保留"
    + _SAVE_NOT_INCLUDED
)
_SAVE_COMPOSING_KEPT_NOTICE = (
    "正在組字（輸入法尚未確認）：請先確認或取消組字，編輯框與輸入已保留" + _SAVE_NOT_INCLUDED
)
_FULLSCREEN_KEPT_NOTICE = (
    "文字編輯尚未套用{detail}，已取消進入全螢幕並保留編輯框；請先套用或取消編輯（文件未變更）"
)
_CLOSE_KEPT_NOTICE = "文字編輯尚未套用{detail}，已取消關閉並保留編輯框（文件未變更）"
# Part 5 round 4 / R4-3: a click or a focus change that the kept editor
# ignored says why (it used to say nothing for a plan refusal or a preview
# that is still updating), and a composition names the cancelled action.
_CLICK_AWAY_KEPT_NOTICE = (
    "文字編輯尚未套用{detail}，已忽略這次點擊並保留編輯框；請先套用或取消編輯（文件未變更）"
)
_FOCUS_OUTSIDE_KEPT_NOTICE = (
    "文字編輯尚未套用{detail}，編輯框與輸入已保留；請先套用或取消編輯（文件未變更）"
)
_PREVIEW_STILL_UPDATING_DETAIL = "預覽仍在更新"
_COMPOSING_ACTION_KEPT_NOTICE = (
    "正在組字（輸入法尚未確認），已取消{action}；請先確認或取消組字，編輯框與輸入已保留（文件未變更）"
)
# The action each keep reason cancelled (FOCUS_OUTSIDE and SAVE_SHORTCUT
# cancel nothing / have their own wording).
_COMPOSING_ACTION_WORDS = {
    TextEditFinalizeReason.APPLY: "套用",
    TextEditFinalizeReason.CLICK_AWAY: "這次點擊頁面",
    TextEditFinalizeReason.CLOSE_DOCUMENT: "關閉",
    TextEditFinalizeReason.VIEW_RESCALE: "縮放",
    TextEditFinalizeReason.FULLSCREEN: "進入全螢幕",
}
# Pointer-driven keep reasons say it once per (text, preedit) state.
_POINTER_NOTICE_REASONS = frozenset(
    {TextEditFinalizeReason.CLICK_AWAY, TextEditFinalizeReason.FOCUS_OUTSIDE}
)
# Escape on changed text discards without a prompt: say so (view side, so a
# stub view without a graphics view never toasts).
ESCAPE_DISCARD_NOTICE = "文字編輯已捨棄（按下 Esc），文件未變更"
_RESCALE_KEPT_NOTICE = (
    "文字編輯尚未套用{detail}，已取消縮放並保留編輯框；請先套用或取消編輯（文件未變更）"
)
# Part 5 round 5: F2 / a ribbon re-click / the context menu on the open
# editor's own run is not a mode switch (R4-4) but used to say nothing.
_MODE_REENTRY_KEPT_NOTICE = (
    "文字編輯尚未套用{detail}，仍在編輯模式並保留編輯框；請先套用或取消編輯（文件未變更）"
)
_MODE_REENTRY_ACTION = "切換模式"
# S17-PASTE-NOTICE: how long the status bar shows what a paste cleaned out.
_PASTE_NOTICE_DURATION_MS = 4000


class _EditorShortcutForwarder(QObject):
    """Forward common window shortcuts while the embedded editor has focus."""

    def __init__(self, view) -> None:
        super().__init__(view if isinstance(view, QObject) else None)
        self._view = view

    def _trigger(self, action_name: str, fallback_name: str | None = None) -> bool:
        action = getattr(self._view, action_name, None)
        if action is not None and hasattr(action, "trigger"):
            action.trigger()
            return True
        if fallback_name:
            fallback = getattr(self._view, fallback_name, None)
            if callable(fallback):
                fallback()
                return True
        return False

    def _editor_widget(self):
        editor = getattr(self._view, "text_editor", None)
        if editor is None or not hasattr(editor, "widget"):
            return None
        return editor.widget()

    def _handle_editor_undo(self) -> bool:
        widget = self._editor_widget()
        if widget is None:
            return True
        document = widget.document() if hasattr(widget, "document") else None
        if document is not None and document.isUndoAvailable():
            widget.undo()
        return True

    def _handle_editor_redo(self) -> bool:
        widget = self._editor_widget()
        if widget is None:
            return True
        document = widget.document() if hasattr(widget, "document") else None
        if document is not None and document.isRedoAvailable():
            widget.redo()
        return True

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return False
        if event.key() == Qt.Key_Escape:
            if _editor_is_composing(obj):
                # A real IME takes Escape to cancel the composition; the edit
                # itself must survive it.
                return False
            handler = getattr(self._view, "_handle_escape", None)
            return bool(handler()) if callable(handler) else False
        modifiers = event.modifiers()
        if not (modifiers & Qt.ControlModifier):
            return False
        if event.key() == Qt.Key_S and (modifiers & Qt.ShiftModifier):
            return self._trigger("_action_save_as", "_save_as")
        if event.key() == Qt.Key_S and not (modifiers & Qt.ShiftModifier):
            return self._trigger("_action_save", "_save")
        if event.key() == Qt.Key_Z and not (modifiers & Qt.ShiftModifier):
            return self._handle_editor_undo()
        if event.key() == Qt.Key_Y:
            return self._handle_editor_redo()
        if event.key() == Qt.Key_Z and (modifiers & Qt.ShiftModifier):
            return self._handle_editor_redo()
        return False


def _fit_edge(text: str, budget: int, measure, *, keep_tail: bool) -> str:
    """``text`` cut to fit ``budget`` with an ellipsis on the cut side.

    ``keep_tail`` keeps the END of the text (the part next to a cursor that
    follows it); otherwise the start is kept.  Binary search on the kept
    length: ``measure`` is monotonic in it, and a chip can hold thousands of
    characters.  Returns ``""`` when not even the ellipsis fits."""
    if measure(text) <= budget:
        return text
    ellipsis = "\u2026"

    def build(count: int) -> str:
        if keep_tail:
            return ellipsis + (text[len(text) - count :] if count else "")
        return (text[:count] if count else "") + ellipsis

    low, high = 0, len(text) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if measure(build(mid)) <= budget:
            low = mid
        else:
            high = mid - 1
    candidate = build(low)
    return candidate if measure(candidate) <= budget else ""


def elide_composing_parts(
    before: str, preedit: str, after: str, room: int, measure
) -> tuple[str, str, str]:
    """The ``(before, preedit, after)`` display parts of the composing chip.

    The chip underlines the preedit and nothing else, so an overflowing chip
    must keep that split: the committed text on either side is elided first
    (``before`` keeps its tail, ``after`` its head, a side that needs less than
    its half donates the rest to the other) and the preedit stays whole.  Only
    a preedit that alone overflows ``room`` is elided (on its left, keeping
    what was typed last) and then stands alone.  ``measure`` is the width of a
    string in the same unit as ``room``."""
    if measure(before + preedit + after) <= room:
        return before, preedit, after
    preedit_width = measure(preedit)
    if preedit_width >= room:
        return "", _fit_edge(preedit, room, measure, keep_tail=True), ""
    budget = room - preedit_width
    before_width, after_width = measure(before), measure(after)
    before_budget = min(budget, max(budget // 2, budget - after_width))
    after_budget = budget - min(before_width, before_budget)
    return (
        _fit_edge(before, before_budget, measure, keep_tail=True),
        preedit,
        _fit_edge(after, after_budget, measure, keep_tail=False),
    )


def paste_cleaned_notice(controls_removed: int, images_dropped: int) -> str | None:
    """The zh-TW status-bar notice for what a paste cleaned out, or None for a clean paste.

    S17-PASTE-NOTICE (owner decision 2026-10-12): the editor keeps stripping control
    characters and dropping pasted images, and says so.
    """
    parts: list[str] = []
    if controls_removed > 0:
        parts.append(f"移除 {controls_removed} 個控制字元")
    if images_dropped > 0:
        parts.append(f"略過 {images_dropped} 張圖片")
    if not parts:
        return None
    return "貼上時已" + "並".join(parts)


def _editor_is_composing(editor) -> bool:
    """Whether ``editor`` holds a live input-method composition; False for an
    editor without the hook (a stub, a plain QTextEdit)."""
    checker = getattr(editor, "is_composing", None)
    return bool(checker()) if callable(checker) else False


def _editor_preedit_text(editor) -> str:
    """The editor's composition (preedit) text; ``""`` without the hook."""
    reader = getattr(editor, "preedit_text", None)
    return reader() if callable(reader) else ""


def _widen_ime_anchor(rect):
    """An ``ImCursorRectangle`` answer at least 1 px wide, so the input method's
    candidate window gets a non-empty anchor while the caret is hidden (width 0).
    Qt6 reports a QRectF and PySide6 has no ``QRect(QRectF)``: widen it directly
    instead of converting.  Anything but a QRectF passes through unchanged."""
    if isinstance(rect, QRectF) and rect.width() < 1.0:
        widened = QRectF(rect)
        widened.setWidth(1.0)
        return widened
    return rect


class InlineTextEditor(QTextEdit):
    focus_out_requested = Signal()
    # S17-PASTE-NOTICE: ``(control characters removed, images dropped)`` by one paste that
    # cleaned something out; never emitted for a clean paste.  The View shows the notice.
    paste_cleaned = Signal(int, int)
    # Round 6 (P1): the composition changed -- preedit text or the cursor offset inside it.
    # Emitted from every ``_preedit_state_changed``, so listeners (the live text strip)
    # see both editors alike.
    composition_changed = Signal()

    # Part 5 / A1: an input-method composition (preedit) lives in the text
    # layout, not in toPlainText().  Tracked here so every finalize path can
    # treat it as un-applied input instead of committing the text without it.
    _preedit_text: str = ""
    # The IME's cursor offset inside the preedit (the ``Cursor`` attribute); None until
    # an event carries one -- then the end of the preedit.
    _preedit_cursor: int | None = None

    @staticmethod
    def _event_preedit_cursor(event, preedit: str) -> int:
        for attribute in event.attributes():
            if attribute.type == QInputMethodEvent.Cursor:
                return max(0, min(len(preedit), int(attribute.start)))
        return len(preedit)

    def inputMethodEvent(self, event) -> None:
        super().inputMethodEvent(event)
        preedit = str(event.preeditString() or "")
        cursor = self._event_preedit_cursor(event, preedit)
        if preedit != self._preedit_text:
            self._preedit_text = preedit
            self._preedit_cursor = cursor
            self._preedit_state_changed()
        elif preedit and cursor != self.preedit_cursor():
            self._preedit_cursor = cursor
            self.composition_changed.emit()

    def _preedit_state_changed(self) -> None:
        self.viewport().update()
        self.composition_changed.emit()

    def preedit_text(self) -> str:
        return self._preedit_text

    def preedit_cursor(self) -> int:
        """The cursor offset inside the preedit (the end of it when the IME sent none)."""
        if self._preedit_cursor is None:
            return len(self._preedit_text)
        return max(0, min(len(self._preedit_text), self._preedit_cursor))

    def is_composing(self) -> bool:
        return bool(self._preedit_text)

    def inputMethodQuery(self, query):
        value = super().inputMethodQuery(query)
        if query == Qt.ImCursorRectangle:
            # The cursor is hidden (width 0) until the first key press; give
            # the candidate window a non-empty anchor all the same.
            return _widen_ime_anchor(value)
        return value

    def keyPressEvent(self, event) -> None:
        # For single-paragraph inline edits, treat End as "move to document end"
        # instead of visual-line end so keyboard workflows stay deterministic.
        if event.key() == Qt.Key_End and self.document().blockCount() <= 1:
            cursor = self.textCursor()
            move_mode = (
                QTextCursor.KeepAnchor
                if event.modifiers() & Qt.ShiftModifier
                else QTextCursor.MoveAnchor
            )
            cursor.movePosition(QTextCursor.End, move_mode)
            self.setTextCursor(cursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        """Paste PLAIN text only, without control characters or U+FFFC (F16-PASTE-1/2).

        The default ``QTextEdit`` paste keeps rich text: an ``<img>`` inside HTML
        copied from a browser or Word becomes an image object that
        ``toPlainText()`` reads as U+FFFC, and the commit then drew a dashed "OBJ"
        box in the PDF.  A PDF text edit takes characters only (the formatting of a
        paste never reached the commit either), so the clipboard is flattened here,
        the object anchors and the control characters the page cannot draw are
        dropped, and ``paste_cleaned`` says how many of each (S17-PASTE-NOTICE: the
        View turns that into a status-bar notice).  The model strips/refuses them
        again (``strip_unrenderable_controls``, ``_verify_rebuild_edit``) for text that
        arrives some other way.
        """
        text = source.text() if source.hasText() else ""
        html_images = 0
        if source.hasHtml() and (not text or "<img" in source.html().lower()):
            # A browser copy carries text/plain (no trace of the image) next to text/html.
            html_text = QTextDocumentFragment.fromHtml(source.html()).toPlainText()
            html_images = html_text.count(OBJECT_REPLACEMENT_CHARACTER)
            if not text:
                text = html_text
        clean, controls, images = split_unrenderable(text)
        images = max(images, html_images)
        if clean:
            self.insertPlainText(clean)
        if controls or images:
            self.paste_cleaned.emit(controls, images)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.focus_out_requested.emit()


@dataclass(frozen=True)
class ViewportAnchor:
    page_idx: int
    horizontal_value: int
    vertical_value: int


def _normalize_for_edit_compare(text: str) -> str:
    if not text:
        return ""
    for ligature, expanded in _LIGATURE_EXPAND.items():
        text = text.replace(ligature, expanded)
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split()).strip()


def _average_image_rect_color(image, rect: QRect) -> QColor:
    mean = _qimage_mean_rgb(image, rect)
    if mean is None:
        return QColor(_DEFAULT_EDITOR_MASK_COLOR)
    return QColor(int(round(mean[0])), int(round(mean[1])), int(round(mean[2])))


def _contrast_ratio_rgb(foreground: tuple[float, float, float], background: tuple[float, float, float]) -> float:
    def _channel(v: float) -> float:
        value = max(0.0, min(255.0, float(v))) / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    fr, fg, fb = foreground
    br, bg, bb = background
    lum_f = 0.2126 * _channel(fr) + 0.7152 * _channel(fg) + 0.0722 * _channel(fb)
    lum_b = 0.2126 * _channel(br) + 0.7152 * _channel(bg) + 0.0722 * _channel(bb)
    light = max(lum_f, lum_b)
    dark = min(lum_f, lum_b)
    return (light + 0.05) / (dark + 0.05)


def _qimage_mean_rgb(image: QImage, rect: QRect) -> tuple[float, float, float] | None:
    try:
        import numpy as np
    except Exception:
        np = None
    bounded = rect.intersected(image.rect())
    if bounded.isEmpty():
        return None
    if image.format() != QImage.Format_RGBA8888:
        image = image.convertToFormat(QImage.Format_RGBA8888)
    stride = int(image.bytesPerLine())
    size_bytes = int(image.sizeInBytes())
    buf = memoryview(image.constBits())[:size_bytes]
    left = bounded.left()
    right = bounded.right()
    width = right - left + 1
    height = bounded.bottom() - bounded.top() + 1
    count = width * height
    if count <= 0:
        return None
    if np is not None:
        img_height = int(image.height())
        img_width = int(image.width())
        arr = np.frombuffer(buf, dtype=np.uint8, count=stride * img_height).reshape((img_height, stride))
        rgba = arr[:, : img_width * 4].reshape((img_height, img_width, 4))
        crop = rgba[bounded.top() : bounded.bottom() + 1, left : right + 1, :3]
        mean_rgb = crop.reshape(-1, 3).mean(axis=0, dtype=np.float64)
        return (float(mean_rgb[0]), float(mean_rgb[1]), float(mean_rgb[2]))
    total_r = 0
    total_g = 0
    total_b = 0
    for y in range(bounded.top(), bounded.bottom() + 1):
        base = y * stride + left * 4
        end = base + width * 4
        row = bytes(buf[base:end])
        total_r += sum(row[0::4])
        total_g += sum(row[1::4])
        total_b += sum(row[2::4])
    return (
        total_r / count,
        total_g / count,
        total_b / count,
    )


def _qimage_ring_mean_rgb(image: QImage, inner_rect: QRect, ring_px: int) -> tuple[float, float, float] | None:
    if ring_px <= 0:
        return _qimage_mean_rgb(image, inner_rect)
    try:
        import numpy as np
    except Exception:
        np = None
    outer = inner_rect.adjusted(-ring_px, -ring_px, ring_px, ring_px).intersected(image.rect())
    inner = inner_rect.intersected(outer)
    if outer.isEmpty():
        return None
    if image.format() != QImage.Format_RGBA8888:
        image = image.convertToFormat(QImage.Format_RGBA8888)
    stride = int(image.bytesPerLine())
    size_bytes = int(image.sizeInBytes())
    buf = memoryview(image.constBits())[:size_bytes]
    total_r = 0
    total_g = 0
    total_b = 0
    count = 0
    if np is not None:
        height = int(image.height())
        width = int(image.width())
        arr = np.frombuffer(buf, dtype=np.uint8, count=stride * height).reshape((height, stride))
        rgba = arr[:, : width * 4].reshape((height, width, 4))

        ys, xs = np.ogrid[outer.top() : outer.bottom() + 1, outer.left() : outer.right() + 1]
        ring_mask = (
            (xs < inner.left())
            | (xs > inner.right())
            | (ys < inner.top())
            | (ys > inner.bottom())
        )
        ring_pixels = rgba[outer.top() : outer.bottom() + 1, outer.left() : outer.right() + 1][ring_mask]
        if ring_pixels.size == 0:
            return _qimage_mean_rgb(image, inner_rect)
        mean_rgb = ring_pixels[:, :3].mean(axis=0, dtype=np.float64)
        return (float(mean_rgb[0]), float(mean_rgb[1]), float(mean_rgb[2]))

    for y in range(outer.top(), outer.bottom() + 1):
        for x in range(outer.left(), outer.right() + 1):
            if inner.contains(x, y):
                continue
            offset = y * stride + x * 4
            total_r += buf[offset]
            total_g += buf[offset + 1]
            total_b += buf[offset + 2]
            count += 1
    if count <= 0:
        return _qimage_mean_rgb(image, inner_rect)
    return (
        total_r / count,
        total_g / count,
        total_b / count,
    )


def _qimage_ring_nonuniform_ratio(
    image: QImage,
    inner_rect: QRect,
    ring_px: int,
    mean_rgb: tuple[float, float, float],
) -> float:
    """Fraction of the ring pixels around ``inner_rect`` (the same ring as
    ``_qimage_ring_mean_rgb``) whose |r|+|g|+|b| distance to ``mean_rgb`` exceeds
    ``_MASK_RING_OUTLIER_L1``.  0.0 = a flat background; ~0.5 = hatching / rules / a photo.
    An empty ring counts as flat."""
    if ring_px <= 0 or image.isNull():
        return 0.0
    outer = inner_rect.adjusted(-ring_px, -ring_px, ring_px, ring_px).intersected(image.rect())
    inner = inner_rect.intersected(outer)
    if outer.isEmpty():
        return 0.0
    mr, mg_, mb = (float(c) for c in mean_rgb)
    # Only the ring bands are visited (cost ~ perimeter, not span area): PERF-1, this runs on the
    # UI thread on the first grip-drag frame and on every re-render of the origin page.
    bands: list[QRect] = []
    if inner.isEmpty():
        bands.append(outer)
    else:
        if inner.top() > outer.top():
            bands.append(QRect(outer.left(), outer.top(), outer.width(), inner.top() - outer.top()))
        if inner.bottom() < outer.bottom():
            bands.append(QRect(outer.left(), inner.bottom() + 1, outer.width(), outer.bottom() - inner.bottom()))
        if inner.left() > outer.left():
            bands.append(QRect(outer.left(), inner.top(), inner.left() - outer.left(), inner.height()))
        if inner.right() < outer.right():
            bands.append(QRect(inner.right() + 1, inner.top(), outer.right() - inner.right(), inner.height()))
    total = 0
    outliers = 0
    try:
        import numpy as np
    except Exception:
        np = None
    if np is not None:
        if image.format() != QImage.Format_RGBA8888:
            image = image.convertToFormat(QImage.Format_RGBA8888)
        stride = int(image.bytesPerLine())
        height = int(image.height())
        width = int(image.width())
        buf = memoryview(image.constBits())[: int(image.sizeInBytes())]
        arr = np.frombuffer(buf, dtype=np.uint8, count=stride * height).reshape((height, stride))
        rgba = arr[:, : width * 4].reshape((height, width, 4))
        for band in bands:
            region = rgba[band.top() : band.bottom() + 1, band.left() : band.right() + 1, :3]
            delta = np.abs(region[:, :, 0].astype(np.float64) - mr)
            delta += np.abs(region[:, :, 1].astype(np.float64) - mg_)
            delta += np.abs(region[:, :, 2].astype(np.float64) - mb)
            total += int(delta.size)
            outliers += int(np.count_nonzero(delta > _MASK_RING_OUTLIER_L1))
        return outliers / total if total else 0.0
    for band in bands:
        for y in range(band.top(), band.bottom() + 1):
            for x in range(band.left(), band.right() + 1):
                c = image.pixelColor(x, y)
                total += 1
                if abs(c.red() - mr) + abs(c.green() - mg_) + abs(c.blue() - mb) > _MASK_RING_OUTLIER_L1:
                    outliers += 1
    return outliers / total if total else 0.0


def _blend_patch_towards_rgb(
    patch: QImage,
    target_rgb: tuple[float, float, float],
    blend_strength: float,
) -> None:
    try:
        import numpy as np
    except Exception:
        np = None
    strength = max(0.0, min(1.0, float(blend_strength)))
    if patch.isNull() or strength <= 0.0:
        return
    if patch.format() != QImage.Format_RGBA8888:
        return
    tr, tg, tb = [max(0.0, min(255.0, float(c))) for c in target_rgb]
    stride = int(patch.bytesPerLine())
    height = int(patch.height())
    width = int(patch.width())
    bits = patch.bits()
    size_bytes = int(patch.sizeInBytes())
    if hasattr(bits, "setsize"):
        bits.setsize(size_bytes)
    data = bits if isinstance(bits, memoryview) else memoryview(bits)
    data = data[:size_bytes]
    if np is not None:
        arr = np.frombuffer(data, dtype=np.uint8).reshape((height, stride))
        rgb = arr[:, : width * 4].reshape((height, width, 4))
        rgb[:, :, 0] = np.clip(rgb[:, :, 0] * (1.0 - strength) + tr * strength, 0, 255).astype(np.uint8)
        rgb[:, :, 1] = np.clip(rgb[:, :, 1] * (1.0 - strength) + tg * strength, 0, 255).astype(np.uint8)
        rgb[:, :, 2] = np.clip(rgb[:, :, 2] * (1.0 - strength) + tb * strength, 0, 255).astype(np.uint8)
        rgb[:, :, 3] = 255
        return
    for y in range(height):
        row = y * stride
        for x in range(width):
            idx = row + x * 4
            data[idx] = int(data[idx] * (1.0 - strength) + tr * strength)
            data[idx + 1] = int(data[idx + 1] * (1.0 - strength) + tg * strength)
            data[idx + 2] = int(data[idx + 2] * (1.0 - strength) + tb * strength)
            data[idx + 3] = 255


def _mask_leak_ratio(patch: QImage, reference_rgb: tuple[float, float, float], threshold: float = 16.0) -> float:
    try:
        import numpy as np
    except Exception:
        np = None
    if patch.isNull():
        return 1.0
    if patch.format() != QImage.Format_RGBA8888:
        patch = patch.convertToFormat(QImage.Format_RGBA8888)
    rr, rg, rb = [float(c) for c in reference_rgb]
    stride = int(patch.bytesPerLine())
    height = int(patch.height())
    width = int(patch.width())
    total = max(1, width * height)
    leaking = 0
    buf = memoryview(patch.constBits())[: int(patch.sizeInBytes())]
    if np is not None:
        arr = np.frombuffer(buf, dtype=np.uint8).reshape((height, stride))
        rgb = arr[:, : width * 4].reshape((height, width, 4))
        delta = np.abs(rgb[:, :, 0].astype(np.float32) - rr)
        delta += np.abs(rgb[:, :, 1].astype(np.float32) - rg)
        delta += np.abs(rgb[:, :, 2].astype(np.float32) - rb)
        leaking = int(np.count_nonzero(delta > threshold * 3.0))
        return leaking / total
    for y in range(height):
        row = y * stride
        for x in range(width):
            idx = row + x * 4
            delta = (
                abs(float(buf[idx]) - rr)
                + abs(float(buf[idx + 1]) - rg)
                + abs(float(buf[idx + 2]) - rb)
            )
            if delta > threshold * 3.0:
                leaking += 1
    return leaking / total


def _origin_mask_margin_px(view) -> float:
    """How far the origin patch extends beyond the source span, in scene pixels."""
    scale = float(getattr(view, "_render_scale", 1.0) or 1.0)
    return max(1.0, _ORIGIN_MASK_MARGIN_PT * scale)


def _make_fallback_mask_result(
    text_rgb_f: tuple[float, float, float],
) -> tuple[QBrush, QColor, dict[str, object]]:
    fallback_color = _readable_editor_mask_color(tuple(int(round(v)) for v in text_rgb_f))
    fallback_rgb = (
        float(fallback_color.red()),
        float(fallback_color.green()),
        float(fallback_color.blue()),
    )
    return (
        QBrush(fallback_color),
        QColor(fallback_color),
        {
            "mask_mode": MASK_MODE_FALLBACK,
            "ring_delta": None,
            "leak_pct": None,
            "contrast_ratio": _contrast_ratio_rgb(text_rgb_f, fallback_rgb),
            "tint_strength": 0.0,
            "ring_nonuniform_pct": None,
        },
    )


def _widget_logical_dpi() -> float:
    """Logical DPI Qt uses for font rendering; 96 on typical Windows."""
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is not None:
        dpi = float(screen.logicalDotsPerInch())
        if dpi > 0:
            return dpi
    return 96.0


def _display_font_pt(pdf_font_size: float, render_scale: float) -> float:
    """Qt point size that makes the editor's glyphs match the rendered PDF's
    glyphs in physical pixels.

    PyMuPDF rasterizes at ``72 × render_scale`` DPI, so a ``S`` pt glyph is
    ``S × render_scale`` physical px tall. Qt renders ``setPointSizeF(P)`` at
    ``P × logical_dpi/72`` px. Equating gives
    ``P = S × render_scale × 72/logical_dpi`` — the only point size at which
    "what you see while editing" equals "what you get after commit".
    """
    return float(pdf_font_size) * float(render_scale) * (72.0 / _widget_logical_dpi())


def _measure_text_content_height_px(
    *,
    text: str,
    qt_font_family: str,
    display_font_pt: float,
    wrap_width_px: int,
) -> int:
    """Natural laid-out height of ``text`` at the given (already display-scaled)
    font and wrap width. Used for paragraph-mode editors whose region box is
    larger than the actual ink."""
    import math

    measure_font = QFont(qt_font_family)
    measure_font.setPointSizeF(float(display_font_pt))
    doc = QTextDocument()
    doc.setDefaultFont(measure_font)
    doc.setTextWidth(float(max(wrap_width_px, 1)))
    doc.setPlainText(text or "")
    return int(math.ceil(doc.size().height()))


def _compute_editor_proxy_layout(
    *,
    scaled_rect: fitz.Rect,
    scaled_width: int,
    page_y_offset: float,
    rotation: int,
    content_height_px: int | None = None,
) -> tuple[int, int, float, float, int]:
    normalized_rotation = int(rotation) % 360
    width_px = max(int(round(scaled_width)), TextEditUIConstants.MIN_EDITOR_WIDTH_PX)
    raw_height = (
        content_height_px
        if content_height_px is not None
        else int(round(scaled_rect.height))
    )
    # First-frame height tracks the PDF span bbox / measured content height.
    # A large fixed minimum (e.g. 40px) is exactly what produced the visible
    # click-to-edit size jump, so it is deliberately NOT applied here.
    height_px = max(int(round(raw_height)), 1)
    pos_x = float(scaled_rect.x0)
    pos_y = float(page_y_offset + scaled_rect.y0)

    if normalized_rotation == 180:
        pos_x += width_px
        pos_y += height_px

    return width_px, height_px, pos_x, pos_y, normalized_rotation


def _proxy_corner_offset(
    rotation: int,
    *,
    rect_w_px: float,
    rect_h_px: float,
    widget_w: float,
    widget_h: float,
) -> tuple[float, float]:
    """Proxy ``pos`` minus the box's visual top-left (page origin + editing_rect.tl * rs).

    The open path rotates the proxy about (0, 0) and puts ``pos`` at a rotation-dependent
    CORNER of the box (90: x1, 180: x0 + W / y0 + H, 270: y1).  The drag-finish path
    subtracts this offset: it is the inverse of the open path (pinned against the literal
    open formulas in ``test_text_editor_rotated_move``)."""
    r = int(rotation) % 360
    if r == 90:
        return float(rect_w_px), 0.0
    if r == 180:
        return float(widget_w), float(widget_h)
    if r == 270:
        return 0.0, float(rect_h_px)
    return 0.0, 0.0


def _proxy_visual_extent(
    rotation: int, widget_w: float, widget_h: float
) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) of the rotated proxy's visual box relative to ``pos``
    (transform origin (0, 0), ``setRotation(rotation)``)."""
    r = int(rotation) % 360
    w, h = float(widget_w), float(widget_h)
    if r == 90:
        return -h, 0.0, 0.0, w
    if r == 180:
        return -w, -h, 0.0, 0.0
    if r == 270:
        return 0.0, -w, h, 0.0
    return 0.0, 0.0, w, h


def _quarter_turn_proxy_layout(
    *,
    scaled_rect: fitz.Rect,
    page_x: float,
    page_y: float,
    rotation: int,
    width_px: int,
    height_px: int,
    pos_x: float,
    pos_y: float,
) -> tuple[int, int, float, float]:
    """90/270: swap the widget size and put ``pos`` at the rotated corner of the box.

    Other rotations pass through unchanged.  The expressions are deliberately the literal
    open-path ones (``x0 + sr.x1`` at 90, ``y0 + sr.y1`` at 270): ``setPos(round(...))``
    follows, so an algebraically equal but float-different form could flip a pixel."""
    r = int(rotation) % 360
    if r == 90:
        return (
            max(int(round(scaled_rect.height)), 1),
            max(int(round(scaled_rect.width)), 1),
            float(page_x + scaled_rect.x1),
            float(page_y + scaled_rect.y0),
        )
    if r == 270:
        return (
            max(int(round(scaled_rect.height)), 1),
            max(int(round(scaled_rect.width)), 1),
            float(page_x + scaled_rect.x0),
            float(page_y + scaled_rect.y1),
        )
    return width_px, height_px, pos_x, pos_y


def _viewport_editor_height_cap_px(view) -> int | None:
    """Cap the editor height to a fraction of the viewport so a huge paragraph
    box never fills the screen. Returns None when no viewport is available."""
    graphics_view = getattr(view, "graphics_view", None)
    if graphics_view is None or not hasattr(graphics_view, "viewport"):
        return None
    viewport = graphics_view.viewport()
    if viewport is None or not hasattr(viewport, "height"):
        return None
    try:
        viewport_height = int(viewport.height())
    except (TypeError, ValueError):
        return None
    if viewport_height <= 0:
        return None
    return max(
        TextEditUIConstants.MIN_EDITOR_HEIGHT_PX,
        int(viewport_height * TextEditUIConstants.MAX_EDITOR_VIEWPORT_HEIGHT_RATIO),
    )


def _alias_font_family(font_name: str) -> str:
    """Normalize PDF font hints to a CSS family MuPDF resolves consistently.

    ``helv`` / ``helvetica`` (and bold variants without an explicit family)
    map to ``Helvetica`` so the preview's fallback CSS resolves to the same
    base-14 face the commit path and a direct ``insert_htmlbox`` would use —
    a prerequisite for pixel-height parity.
    """
    family = str(font_name or "Helvetica").strip()
    low = family.lower()
    if low in {"helv", "helvetica", ""}:
        return "Helvetica"
    if "bold" in low and "helvetica" not in low:
        return "Helvetica"
    return family


class PreviewRenderer:
    """Rasterizes proposed edit content through the *same* MuPDF
    ``insert_htmlbox`` engine the commit path uses, so the glyphs an opened
    editor shows are pixel-identical to what lands in the PDF.

    A model may be supplied so the preview borrows the model's exact CSS /
    HTML builders; with ``model=None`` (unit isolation) a minimal but
    metrics-equivalent CSS/HTML is used instead.
    """

    def __init__(self, build_preview_html=None, model=None) -> None:
        # R2.6: the preview borrows the commit path's CSS/HTML through a public
        # callable (controller.build_insert_preview_html), so render() no longer
        # reaches the model's private dunders. The legacy ``model=`` argument is a
        # backward-compat shim (tests construct PreviewRenderer with a model):
        # when no callable is supplied, derive one from the model's builders so
        # the rendered pixels are identical either way.
        if build_preview_html is None and model is not None and hasattr(model, "_build_insert_css"):
            def build_preview_html(*, text, font_size, color, font_name, line_height, member_spans=None):
                builder = getattr(model, "build_preview_insert_css", None)
                if builder is not None:
                    css = builder(
                        size=font_size, color=color, font_hint=font_name,
                        line_height=line_height, member_spans=member_spans,
                        new_text=text,
                    )
                else:
                    css = model._build_insert_css(
                        size=font_size, color=color, font_hint=font_name, line_height=line_height
                    )
                html = model._convert_text_to_html(
                    text=text, font_size=font_size, color=color, latin_font=font_name
                )
                return css, html
        self._build_preview_html = build_preview_html
        self._model = model
        self._cache_key: tuple | None = None
        self._cache_image: QImage | None = None
        # S14-EXTB-PREVIEW-WORKER: the markup whose Ext-B subsets were not cached when the
        # last ``render(defer_ext_b=True)`` ran (that frame drew .notdef for them), else None.
        self.pending_ext_b_html: str | None = None

    @staticmethod
    def _pixel_dims(rect: fitz.Rect, render_scale: float, rotation: int) -> tuple[int, int]:
        width = max(1, int(round(float(rect.width) * float(render_scale))))
        height = max(1, int(round(float(rect.height) * float(render_scale))))
        if int(rotation) % 360 in (90, 270):
            width, height = height, width
        return width, height

    def _to_qimage_dimensions(self, *, rect: fitz.Rect, render_scale: float, rotation: int) -> QImage:
        width, height = self._pixel_dims(rect, render_scale, rotation)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        return image

    def render(
        self,
        *,
        text: str,
        font_name: str,
        font_size: float,
        color: tuple[float, float, float],
        member_spans: list[object] | None,
        rect_pt: fitz.Rect,
        rotation: int,
        render_scale: float,
        line_height: float = 0.0,
        defer_ext_b: bool = False,
    ) -> QImage:
        """Rasterize ``text`` through the commit path's htmlbox engine.

        ``defer_ext_b=False`` (direct callers, tests) computes any missing CJK Ext-B
        subset right here, on the calling thread.  The GUI passes ``True``: only cached
        subsets are used, an uncached set draws ``.notdef`` for this frame and
        ``pending_ext_b_html`` names the markup whose subsets a worker must build
        (``view/ext_b_subset_worker.py``) before the next render; such a frame is
        never cached."""
        key = (
            text,
            font_name,
            float(font_size),
            tuple(float(c) for c in color),
            int(rotation),
            float(render_scale),
            float(line_height),
            int(round(float(rect_pt.width) * 100)),
            int(round(float(rect_pt.height) * 100)),
            # D-RTL-PREVIEW: the frame's layout direction follows the edited runs
            # (and the typed text, which is already part of the key).
            tuple(getattr(s, "span_id", None) for s in (member_spans or ())),
        )
        # A cache hit is a complete frame: nothing pending.  Any other render re-derives it below.
        self.pending_ext_b_html = None
        if key == self._cache_key and self._cache_image is not None:
            return self._cache_image

        normalized_rotation = int(rotation) % 360
        # The preview is painted inside the inline editor proxy, which the view
        # rotates via setRotation(rotation). The frozen first frame is likewise
        # counter-rotated into upright local space. So the live preview glyphs
        # must stay UPRIGHT here — the proxy applies the visual rotation. We only
        # swap the page (wrap) dimensions for 90/270 so the upright text wraps
        # along the rotated run's reading-direction length and the image fills
        # the swapped editor frame. Rendering with rotate=normalized_rotation
        # would double-rotate the content the moment the user types.
        if normalized_rotation in (90, 270):
            page_w_pt = max(float(rect_pt.height), 1.0)
            page_h_pt = max(float(rect_pt.width), 1.0)
        else:
            page_w_pt = max(float(rect_pt.width), 1.0)
            page_h_pt = max(float(rect_pt.height), 1.0)

        temp_doc = fitz.open()
        try:
            temp_page = temp_doc.new_page(width=page_w_pt, height=page_h_pt)

            if self._build_preview_html is not None:
                # Borrow the commit path's exact CSS/HTML so preview and committed
                # pixels come from one engine configuration (the builder forwards
                # to the model's _build_insert_css / _convert_text_to_html).
                css, html = self._build_preview_html(
                    text=text or "",
                    font_size=float(font_size),
                    color=tuple(float(c) for c in color),
                    font_name=str(font_name),
                    line_height=float(line_height),
                    member_spans=member_spans,
                )
            else:
                import html as _html_mod

                r, g, b = (int(c * 255) for c in color)
                family = _alias_font_family(font_name)
                lh_css = f" line-height: {line_height}pt;" if line_height > 0 else ""
                css = (
                    f"span {{ font-family: {family}; font-size: {font_size}pt;{lh_css} "
                    f"color: rgb({r},{g},{b}); white-space: pre-wrap; }}"
                )
                html = f"<span>{_html_mod.escape(text or '')}</span>"

            target_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
            # rotate=0: glyphs stay upright; the editor proxy rotation supplies
            # the on-screen rotation (see the page-dimension note above).
            # S12-EXTB-PREVIEW: the same Ext-B subset @font-face/archive the commit
            # chokepoint (model.font_stream_compaction.insert_htmlbox_tracked) adds,
            # so a typed U+20B9F previews as its glyph, not .notdef.  The view may
            # not import model, hence the shared utils helper.
            box_kwargs: dict = {"css": css, "scale_low": 1}
            try:
                html, box_kwargs = htmlbox_args_with_ext_b(
                    html, box_kwargs, cached_only=defer_ext_b
                )
            except ExtBSubsetNotReady:
                # S14-EXTB-PREVIEW-WORKER: never subset on the GUI thread; this frame draws
                # .notdef for the Ext-B characters and the editor re-renders once the worker
                # has filled the cache.
                self.pending_ext_b_html = html
            temp_page.insert_htmlbox(target_rect, html, **box_kwargs)

            clamped = _safe_render_scale(temp_page, float(render_scale))
            pixmap = temp_page.get_pixmap(
                matrix=fitz.Matrix(clamped, clamped),
                alpha=True,
            )
            fmt = QImage.Format_RGBA8888 if pixmap.alpha else QImage.Format_RGB888
            image = QImage(
                pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, fmt
            ).copy()
        finally:
            temp_doc.close()

        if self.pending_ext_b_html is None:
            self._cache_key = key
            self._cache_image = image
        return image


class PreviewBackedInlineTextEditor(InlineTextEditor):
    # UI step 5: fired whenever current_plan_token() may have changed (a new
    # generation, an interim CSS frame, an accepted plan raster) so the View
    # can re-gate its Apply button.  Carries nothing; listeners re-query.
    plan_token_state_changed = Signal()
    # Round 6 (P2): fired once, when the hidden QTextEdit caret is first revealed
    # (a key press or an in-box mouse press); see reveal_caret().
    caret_revealed_changed = Signal()
    """Inline editor that paints a MuPDF-rasterized preview instead of Qt's
    native glyphs, so the on-screen text is pixel-faithful to the committed
    PDF. While the text is unchanged it paints a *frozen* capture of the real
    PDF span (the only thing that is truly pixel-perfect); once mutated it
    paints the live CSS preview from the shared engine.
    """

    # Treat an effectively-transparent mutated preview as invalid and fall
    # back to native QTextEdit painting so typed text stays readable.
    _MUTATED_PREVIEW_MIN_NONTRANSPARENT_COVERAGE = 0.0001
    _VISIBLE_ALPHA_THRESHOLD = 8
    _ime_anchor_provider = None

    def __init__(self, text: str, renderer: PreviewRenderer | None = None, **legacy_kwargs) -> None:
        super().__init__()
        self.setFrameStyle(0)
        self.setViewportMargins(0, 0, 0, 0)
        self.setContentsMargins(0, 0, 0, 0)
        # Override any QApplication-level QSS that adds padding or borders to
        # QTextEdit (e.g. the theme stylesheet from view/theme.py). The inline
        # editor must always render flush to the PDF page.
        self.setStyleSheet("QTextEdit { padding: 0px; border: 0px; margin: 0px; }")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCursorWidth(0)
        self._cursor_revealed = False
        self._ime_anchor_provider = None
        try:
            self.document().setDocumentMargin(0.0)
        except Exception:
            logger.debug("document margin reset skipped")
        self._renderer = renderer or PreviewRenderer(model=legacy_kwargs.get("model"))
        self._preview_image: QImage | None = None
        self._frozen_first_frame_image: QImage | None = None
        self._initial_text = text or ""
        # Cached (toPlainText() == _initial_text); refreshed only on
        # textChanged. paintEvent reads it but must never recompute it (it
        # fires on cursor blink/scroll and would walk the whole document).
        self._text_matches_initial: bool = True
        self._text_is_nonempty: bool = bool(self._initial_text)
        self._mutated_preview_is_valid: bool = True
        self._legacy_standalone_mode = bool(legacy_kwargs) and renderer is None
        self._render_args: dict[str, object] = {}
        # Plan-backed exact preview (V2 Task 8). The hook only *emits* a
        # request — the editor never opens a PDF or touches the Model; the
        # raster comes back through apply_plan_preview() with a generation
        # guard so stale keystrokes can never paint.
        self._plan_preview_hook = None
        self._plan_generation = 1
        self._plan_preview_active = False
        # UI step 11: with preview='plan' the CSS/HTML system-font frame is
        # never rendered or painted (it claims a fidelity it cannot have).
        self._plan_mode = False
        self._applied_plan_generation: int | None = None
        self._applied_plan_token: str | None = None
        # UI step 10: the refusal (reason code) recorded for one generation
        # -- a rejected plan preview or a refused commit.  Valid only while
        # that generation is current, so any input change drops it.
        self._plan_rejection: tuple[int, str] | None = None
        # S14-EXTB-PREVIEW-WORKER: the markup an Ext-B subset worker is building now (the
        # latest render's), the one already tried (never asked twice: a subset that cannot
        # be built keeps the .notdef frame instead of looping), and the lazily made service.
        self._ext_b_pending: str | None = None
        self._ext_b_tried: str | None = None
        self._ext_b_service: ExtBSubsetService | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._regenerate_preview)
        self.setPlainText(text)
        self.textChanged.connect(self._schedule_preview)
        if legacy_kwargs:
            rgb = legacy_kwargs.get("color", (0.0, 0.0, 0.0))
            text_rgb = tuple(max(0, min(255, int(float(c) * 255))) for c in rgb)
            legacy_kwargs["text_rgb"] = text_rgb
            legacy_kwargs.setdefault("legacy_bg_rgb", (70, 70, 70))
            initial_frame_image = legacy_kwargs.pop("initial_frame_image", None)
            self.configure_render_context(**legacy_kwargs)
            if isinstance(initial_frame_image, QImage) and not initial_frame_image.isNull():
                self.setFixedSize(initial_frame_image.width(), initial_frame_image.height())
                self.freeze_first_frame(initial_frame_image)
            if self._preview_image is not None and not self._legacy_standalone_mode:
                self.freeze_first_frame(self._preview_image)

    def reveal_caret(self) -> None:
        """The one chokepoint that turns the native caret on (width 0 at open, so
        an untouched session paints pixel-identically).  Idempotent; signals once."""
        if self._cursor_revealed:
            return
        self.setCursorWidth(1)
        self._cursor_revealed = True
        self.caret_revealed_changed.emit()

    def caret_revealed(self) -> bool:
        return self._cursor_revealed

    def keyPressEvent(self, event) -> None:
        self.reveal_caret()
        super().keyPressEvent(event)

    def inputMethodEvent(self, event) -> None:
        # The base first: it keeps the preedit tracking.  An IME-only user never presses
        # a key, so a non-empty commit or preedit is what reveals the caret.
        super().inputMethodEvent(event)
        if event.commitString() or event.preeditString():
            self.reveal_caret()

    def set_ime_anchor_provider(self, provider) -> None:
        """``provider() -> QRectF | None`` (this editor's coordinates): where the input
        method's candidate window anchors.  The view installs one that points at the live
        text strip caret, which is the only place the typed text is legible."""
        self._ime_anchor_provider = provider

    def inputMethodQuery(self, query):
        if query == Qt.ImCursorRectangle and self._ime_anchor_provider is not None:
            try:
                rect = self._ime_anchor_provider()
            except Exception:
                logger.debug("IME anchor provider failed", exc_info=True)
                rect = None
            if isinstance(rect, QRectF) and rect.height() > 0:
                return _widen_ime_anchor(rect)
        return super().inputMethodQuery(query)

    def configure_render_context(self, **kwargs) -> None:
        # UI step 6: every change of a render input after the first call
        # (font, size, colour, geometry) supersedes any plan raster still in
        # flight for the old inputs.  Bump here -- the chokepoint -- so no
        # caller can forget: a same-generation result would otherwise set the
        # token for a preview the user no longer sees.
        if self._render_args and any(
            key not in self._render_args or self._render_args[key] != value
            for key, value in kwargs.items()
        ):
            self._plan_generation += 1
        self._render_args.update(kwargs)
        rect_val = self._render_args.get("rect_pt")
        scale_val = float(self._render_args.get("render_scale", 1.0) or 1.0)
        if rect_val is not None:
            rect = fitz.Rect(rect_val)
            width_px = max(1, int(round(float(rect.width) * scale_val)))
            height_px = max(1, int(round(float(rect.height) * scale_val)))
            rotation = int(self._render_args.get("rotation", 0)) % 360
            if rotation in (90, 270):
                width_px, height_px = height_px, width_px
            # create_text_editor() owns the no-jump geometry; only fall back to
            # rect-derived sizing when no explicit frame was set (or legacy
            # standalone mode where rect sizing is the sole input).
            if self._legacy_standalone_mode or self.width() <= 1 or self.height() <= 1:
                self.setFixedSize(width_px, height_px)
        self._regenerate_preview()

    def invalidate_plan_preview(
        self, *, regenerate: bool = True, keep_refusal: bool = False
    ) -> None:
        """Supersede every plan request issued so far (UI step 6).

        For inputs the editor cannot see itself -- a drag moves the proxy and
        the View's ``editing_rect``.  ``regenerate=False`` only bumps the
        generation (cheap; per mouse-move); ``True`` also re-requests the
        preview so the editor is not left without a token.

        ``keep_refusal`` (a document-change invalidate such as a save: the
        INPUT is unchanged): a refusal the input already has is re-recorded
        for the new generation when no plan request will follow to record it
        again (legacy preview mode).  In plan mode the pending re-preview reports
        the refusal itself, so nothing stale is shown meanwhile.
        """
        kept = self.plan_rejection_reason() if keep_refusal else None
        self._plan_generation += 1
        self._plan_preview_active = False
        self.plan_token_state_changed.emit()
        if regenerate:
            self._debounce.stop()
            self._regenerate_preview()
        if kept is not None and not self._plan_mode:
            self.set_plan_preview_state(self._plan_generation, kept)

    def _schedule_preview(self) -> None:
        # CRITICAL — do NOT clear _frozen_first_frame_image here. It is the
        # real MuPDF pixmap of the span as the user saw it pre-click. Releasing
        # it on first mutation makes type-then-delete a one-way trip: the
        # editor never returns to PDF-faithful appearance even when content is
        # byte-identical to the original, leaving a permanent restore delta.
        # Gates: test_click_to_edit_qtest_integration,
        #        test_click_to_edit_then_insert_then_delete_stays_stable.
        #
        # textChanged is the ONLY event that can flip these flags; refresh them
        # here so paintEvent can read cached values instead of walking the
        # QTextDocument 60+ times/second.
        self._text_matches_initial = self.toPlainText() == self._initial_text
        self._text_is_nonempty = bool(self.toPlainText())
        # Bump synchronously on every text change (not in the debounced
        # regenerate) so the generation always reflects the latest text and
        # rasters for superseded keystrokes fail the guard.
        self._plan_generation += 1
        self.plan_token_state_changed.emit()
        if not self._text_is_nonempty:
            # Box just emptied: regenerate synchronously so the editor does not
            # linger on the stale preview of the previous text (which would flash
            # the old glyphs over the mask until the debounce fires). Ongoing
            # typing stays debounced for performance.
            self._debounce.stop()
            self._regenerate_preview()
        else:
            self._debounce.start()
        self.viewport().update()

    def _mutated_preview_has_visible_ink(self, image: QImage | None) -> bool:
        try:
            import numpy as np
        except Exception:
            np = None
        # The only consumer compares coverage against a tiny fraction, so we
        # just need "are there at least N visible alpha bytes?" — scan and stop
        # as soon as the count crosses the threshold instead of summing every
        # pixel of the preview on every debounced regenerate.
        if (
            image is None
            or image.isNull()
            or self._frozen_first_frame_image is None
        ):
            return False
        width = int(image.width())
        height = int(image.height())
        if width <= 0 or height <= 0:
            return False
        if image.format() != QImage.Format_RGBA8888:
            image = image.convertToFormat(QImage.Format_RGBA8888)
        threshold = int(self._VISIBLE_ALPHA_THRESHOLD)
        stride = int(image.bytesPerLine())
        size_bytes = int(image.sizeInBytes())
        buf = memoryview(image.constBits())[:size_bytes]
        needed = self._MUTATED_PREVIEW_MIN_NONTRANSPARENT_COVERAGE * width * height
        if np is not None:
            pixels = np.frombuffer(buf, dtype=np.uint8, count=stride * height)
            rows = pixels.reshape((height, stride))
            visible = int(np.count_nonzero(rows[:, 3 : 4 * width : 4] > threshold))
            return visible > needed
        visible = 0
        for y in range(height):
            row_start = y * stride
            row_alpha = buf[row_start + 3 : row_start + 4 * width : 4]
            visible += sum(1 for a in row_alpha if a > threshold)
            if visible > needed:
                return True
        return visible > needed

    def _regenerate_preview(self) -> None:
        if not self._render_args:
            return
        text = self.toPlainText()
        self._text_is_nonempty = bool(text)
        if self._plan_mode:
            # UI step 11: no CSS interim frame.  _preview_image keeps the last
            # verified plan raster (or None -> the frozen original frame).
            self._mutated_preview_is_valid = True
        else:
            self._render_css_frame(text)
        # The CSS interim frame is now current; any previously applied plan
        # raster belongs to older text until a fresh one arrives.
        self._plan_preview_active = False
        self.plan_token_state_changed.emit()
        if self._plan_preview_hook is not None:
            try:
                self._plan_preview_hook(text, self._plan_generation)
            except Exception:
                logger.warning("plan preview hook failed", exc_info=True)
        self.viewport().update()

    def _render_css_frame(self, text: str) -> None:
        """Rasterize the CSS interim frame for ``text`` and refresh its validity flag.

        S14-EXTB-PREVIEW-WORKER: ``defer_ext_b=True`` keeps the fontTools subset of a
        new CJK Ext-B character set off this (GUI) thread.  A set that is not cached
        yet draws .notdef for this frame; the markup goes to the editor's worker
        (``_sync_ext_b_worker``) and ``_on_ext_b_subsets_ready`` re-renders."""
        self._preview_image = self._renderer.render(
            text=text,
            font_name=str(self._render_args.get("font_name", "helv")),
            font_size=float(self._render_args.get("font_size", 12.0)),
            color=tuple(self._render_args.get("color", (0.0, 0.0, 0.0))),
            member_spans=self._render_args.get("member_spans"),
            rect_pt=fitz.Rect(self._render_args.get("rect_pt")),
            rotation=int(self._render_args.get("rotation", 0)),
            render_scale=float(self._render_args.get("render_scale", 1.0)),
            line_height=float(self._render_args.get("line_height", 0.0)),
            defer_ext_b=True,
        )
        self._mutated_preview_is_valid = (
            not self._text_is_nonempty
            or self._mutated_preview_has_visible_ink(self._preview_image)
        )
        self._sync_ext_b_worker()

    def _sync_ext_b_worker(self) -> None:
        """After a render: ask the worker for the subsets the frame lacked, or note that
        the frame is complete.  The markup is compared on arrival, so a result for text
        the user has since changed is dropped (``_on_ext_b_subsets_ready``)."""
        pending = getattr(self._renderer, "pending_ext_b_html", None)
        if not isinstance(pending, str):
            self._ext_b_pending = None
            self._ext_b_tried = None
            return
        if pending == self._ext_b_pending or pending == self._ext_b_tried:
            # Already building it, or built it and still not cached (a font that cannot
            # be subset, an evicted entry): keep the .notdef frame instead of looping.
            return
        self._ext_b_pending = pending
        service = self._ext_b_service
        if service is None:
            service = ExtBSubsetService(self)
            service.subsets_ready.connect(self._on_ext_b_subsets_ready)
            self._ext_b_service = service
        service.request(pending)

    def _on_ext_b_subsets_ready(self, html: str, ok: bool) -> None:
        if html != self._ext_b_pending:
            return  # superseded by newer text: its own request is (or was) in flight
        self._ext_b_pending = None
        self._ext_b_tried = html
        if not ok or not self._render_args or self._plan_mode:
            return
        self._render_css_frame(self.toPlainText())
        self.viewport().update()

    def release_background_work(self) -> None:
        """Editor closing (``TextEditManager._teardown_editor``): drop the queued Ext-B
        request and ignore any result still in flight.  A running worker finishes on its
        own (it only fills the cache) and is reaped by ``view.ext_b_subset_worker``."""
        self._ext_b_pending = None
        self._ext_b_tried = None
        service, self._ext_b_service = self._ext_b_service, None
        if service is not None:
            service.close()

    def paintEvent(self, event) -> None:
        # CRITICAL — visual fidelity contract. While text == initial (incl.
        # after a type-then-delete round-trip) paint the frozen MuPDF capture;
        # CSS preview never pixel-matches MuPDF hinting, so using it for
        # unchanged text introduces a permanent delta. _text_matches_initial is
        # cached (see _schedule_preview); never recompute it per paint.
        # Gates: test_click_to_edit_qtest_integration,
        #        test_click_to_edit_then_insert_then_delete_stays_stable.
        if self._preedit_text:
            # Part 5 / A1: the frame never contains the composition (QTextEdit's
            # native paint is bypassed), so draw it as UI chrome -- before the
            # frozen-frame short-circuit below, which would hide it entirely.
            use_frame, base = self._composing_paint_plan()
            if use_frame:
                self._paint_composing_frame(base)
            else:
                # Part 5 final review: the mutated-state fail-safe below must
                # hold while composing too -- never the frozen source glyphs or
                # a preview ``_mutated_preview_is_valid`` rejected.  The native
                # paint draws the live text and the preedit itself.
                self._paint_native_text(event)
            return
        if self._frozen_first_frame_image is not None and self._text_matches_initial:
            painter = QPainter(self.viewport())
            painter.drawImage(0, 0, self._frozen_first_frame_image)
            painter.end()
            return
        if self._plan_mode:
            self._paint_plan_mode_frame()
            return
        if (
            self._preview_image is not None
            and self._text_is_nonempty
            and not self._text_matches_initial
            and not self._mutated_preview_is_valid
        ):
            # Mutated-state fail-safe: never repaint the frozen source glyphs
            # while editing. The opaque mask item below this transparent
            # editor suppresses the PDF underlay; native QTextEdit paint adds
            # only the current live text.
            self._paint_native_text(event)
            return
        painter = QPainter(self.viewport())
        if self._preview_image is not None:
            if self._legacy_standalone_mode:
                bg_rgb = self._render_args.get("legacy_bg_rgb", (184, 184, 184))
                painter.fillRect(self.viewport().rect(), QColor(*bg_rgb))
            painter.drawImage(0, 0, self._preview_image)
        elif self._text_is_nonempty and not self._text_matches_initial:
            # Debounce window before the live preview arrives: paint only the
            # current QTextEdit contents over the underlay mask. Drawing the
            # frozen first frame here would overlap old and new glyphs.
            painter.end()
            self._paint_native_text(event)
            return
        elif self._frozen_first_frame_image is not None:
            painter.drawImage(0, 0, self._frozen_first_frame_image)
        else:
            painter.end()
            super().paintEvent(event)
            return
        painter.end()

    def _paint_native_text(self, event) -> None:
        """QTextEdit's own paint, transparent over the opaque mask item: only
        the live text (and any preedit) is drawn, never a PDF frame."""
        viewport = self.viewport()
        old_auto_fill = viewport.autoFillBackground()
        viewport.setAutoFillBackground(False)
        super().paintEvent(event)
        viewport.setAutoFillBackground(old_auto_fill)

    def _composing_paint_plan(self) -> tuple[bool, QImage | None]:
        """``(use_frame, base)`` for a paint while an input method composes.

        Unchanged text paints the frozen capture (the fidelity contract);
        plan mode keeps its last verified raster (UI step 11); in the legacy
        CSS preview mode a mutated text may only sit on a preview that
        ``_mutated_preview_is_valid`` accepts -- otherwise ``use_frame`` is
        False and the caller falls back to the native paint."""
        frozen = self._frozen_first_frame_image
        if frozen is not None and self._text_matches_initial:
            return True, frozen
        if self._plan_mode:
            return True, self._preview_image if self._preview_image is not None else frozen
        if self._preview_image is not None and self._mutated_preview_is_valid:
            return True, self._preview_image
        return False, None

    # ---- plan-mode frame (UI step 11) ----------------------------------

    PLAN_PENDING_BADGE_TEXT = "預覽更新中"
    PLAN_REFUSED_BADGE_TEXT = "無法套用"

    def set_plan_preview_mode(self, enabled: bool) -> None:
        """Plan mode: never render or paint the CSS interim frame."""
        self._plan_mode = bool(enabled)
        self.viewport().update()

    def plan_preview_mode(self) -> bool:
        return self._plan_mode

    def plan_preview_pending(self) -> bool:
        """True while the shown frame does not yet reflect the typed text:
        plan mode, text differs from the original, and the current generation
        has neither a verified raster nor a recorded refusal."""
        if self._preedit_text:
            return True
        return (
            self._plan_mode
            and not self._text_matches_initial
            and not self._plan_frame_is_verified()
            and self.plan_rejection_reason() is None
        )

    def plan_preview_refused(self) -> bool:
        """True while the shown frame is stale because the current text was
        refused (R4-1): plan mode, text differs from the original, no
        composition, no verified raster, and a recorded refusal.  ``no_change``
        is excluded: Apply is then a no-op close, so "無法套用" would be false.
        Kept separate from :meth:`plan_preview_pending`, which is False here."""
        reason = self.plan_rejection_reason()
        return bool(
            self._plan_mode
            and not self._preedit_text
            and not self._text_matches_initial
            and reason is not None
            and reason != "no_change"
            and not self._plan_frame_is_verified()
        )

    def _plan_frame_is_verified(self) -> bool:
        return bool(
            self._plan_preview_active
            and self._applied_plan_generation == self._plan_generation
        )

    COMPOSING_BADGE_TEXT = "組字中"

    def plan_preview_badge_text(self) -> str:
        if self._preedit_text:
            return self.COMPOSING_BADGE_TEXT
        if self.plan_preview_refused():
            return self.PLAN_REFUSED_BADGE_TEXT
        return self.PLAN_PENDING_BADGE_TEXT

    def _composing_chip_parts(self) -> tuple[str, str, str]:
        text = self.toPlainText()
        position = max(0, min(len(text), self.textCursor().position()))
        return text[:position], self._preedit_text, text[position:]

    def _preedit_state_changed(self) -> None:
        # The token text excludes the preedit, so the token (and Apply) go
        # away while composing and come back when the composition ends.  The
        # token signal goes first, before the base repaints and notifies the strip.
        self.plan_token_state_changed.emit()
        super()._preedit_state_changed()

    def _paint_composing_frame(self, base: QImage | None) -> None:
        """``base`` (chosen by :meth:`_composing_paint_plan`) plus the
        composing badge; outside plan mode also a chip showing the text with
        the preedit underlined (in plan mode the live text strip shows it).
        UI chrome only: the PDF-fidelity contract (never native glyphs over
        the page) holds."""
        painter = QPainter(self.viewport())
        if base is not None:
            painter.drawImage(0, 0, base)
        self._paint_editor_overlay(painter)
        painter.end()

    def _paint_plan_mode_frame(self) -> None:
        """Last verified frame (else the frozen original) plus, while the
        preview is pending or refused, the badge (round 7: no in-box chip;
        the live text strip shows the typed text).  Never the CSS frame and
        never the editor's native glyphs."""
        painter = QPainter(self.viewport())
        base = self._preview_image
        if base is None:
            base = self._frozen_first_frame_image
        if base is not None:
            painter.drawImage(0, 0, base)
        if self.plan_preview_pending() or self.plan_preview_refused():
            self._paint_editor_overlay(painter)
        painter.end()

    def _paint_editor_overlay(self, painter: QPainter) -> None:
        rect = self.viewport().rect()
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont()
        font.setPixelSize(max(9, min(12, rect.height() // 3)))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        pad = 3
        height = metrics.height() + 2
        painter.setPen(Qt.NoPen)

        badge = self.plan_preview_badge_text()
        badge_w = min(rect.width(), metrics.horizontalAdvance(badge) + 2 * pad)
        badge_rect = QRect(rect.right() - badge_w + 1, rect.top(), badge_w, height)
        # Refusal: the warning-toast colour, so it reads differently from the
        # neutral "still updating" badge.
        if self.plan_preview_refused():
            painter.setBrush(QColor(170, 110, 20, 230))
        else:
            painter.setBrush(QColor(40, 40, 40, 215))
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, int(Qt.AlignCenter), badge)

        if self._plan_mode or not self._preedit_text:
            # Round 7 (F2): plan mode draws no chip -- the live text strip above
            # the box shows the typed text, caret, selection and preedit.  Outside
            # plan mode this method is only reached while composing, and the chip
            # is the only preedit echo there (the strip is plan-only).
            return
        room = max(10, rect.width() - 4 * pad)
        before, preedit, after = self._composing_chip_parts()
        before, preedit, after = elide_composing_parts(
            before, preedit, after, room, metrics.horizontalAdvance
        )
        chip_w = min(rect.width(), metrics.horizontalAdvance(before + preedit + after) + 2 * pad)
        chip_rect = QRect(rect.left(), rect.bottom() - height + 1, chip_w, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRoundedRect(chip_rect, 3, 3)
        painter.setPen(QColor(30, 30, 30))
        x = chip_rect.left() + pad
        baseline = chip_rect.top() + (height + metrics.ascent() - metrics.descent()) // 2
        for segment, underlined in ((before, False), (preedit, True), (after, False)):
            if not segment:
                continue
            segment_font = QFont(font)
            segment_font.setUnderline(underlined)
            painter.setFont(segment_font)
            painter.drawText(x, baseline, segment)
            x += QFontMetrics(segment_font).horizontalAdvance(segment)
        painter.setFont(font)

    def freeze_first_frame(self, image: QImage | None) -> None:
        self._frozen_first_frame_image = image.copy() if image is not None else None
        self.viewport().update()

    # ---- plan-backed exact preview (V2 Task 8) -------------------------

    def set_plan_preview_hook(self, hook) -> None:
        """Install the request emitter: ``hook(text, generation)``.

        The hook must only emit a View signal — the editor stays free of
        any PDF or Model access.
        """
        self._plan_preview_hook = hook

    def apply_plan_preview(
        self, generation: int, image: QImage | None, plan_token: str | None = None
    ) -> bool:
        """Accept an exact plan raster only for the current generation."""
        if generation != self._plan_generation:
            return False  # stale keystroke: the CSS interim frame stays
        if image is None or image.isNull():
            return False
        self._preview_image = self._counter_rotate_for_proxy(image)
        self._mutated_preview_is_valid = True
        self._plan_preview_active = True
        self._applied_plan_generation = generation
        self._applied_plan_token = plan_token
        self._plan_rejection = None
        self.viewport().update()
        self.plan_token_state_changed.emit()
        return True

    def set_plan_preview_state(self, generation: int, reason: str | None) -> bool:
        """UI step 10: record why ``generation`` cannot be applied as is.

        ``reason`` is a refusal code (a rejected plan preview, or the
        Controller's refusal of the commit); ``None`` clears it.  Ignored for
        any generation but the current one (a superseded keystroke never
        paints a refusal).  Listeners re-query through
        ``plan_token_state_changed``."""
        if generation != self._plan_generation:
            return False
        self._plan_rejection = (generation, str(reason)) if reason else None
        # R4-1: the badge depends on the refusal; without a full repaint a
        # stale "預覽更新中" stays until an unrelated paint.
        self.viewport().update()
        self.plan_token_state_changed.emit()
        return True

    def plan_rejection_reason(self) -> str | None:
        """The refusal code recorded for the CURRENT generation, else None."""
        rejection = self._plan_rejection
        if rejection is not None and rejection[0] == self._plan_generation:
            return rejection[1]
        return None

    def _counter_rotate_for_proxy(self, image: QImage) -> QImage:
        """Displayed-space raster -> this editor's local paint frame.

        The scene rotates the proxy by the configured ``rotation`` at display
        time, so a raster of the displayed-space clip must be counter-rotated
        before it is painted at local (0, 0) -- exactly what
        ``TextEditManager._capture_frozen_first_frame`` does for the frozen
        first frame. Identity for unrotated editors.
        """
        rotation = int(self._render_args.get("rotation", 0) or 0) % 360
        counter = PROXY_COUNTER_ROTATION.get(rotation)
        if counter is None:
            return image
        return image.transformed(QTransform().rotate(counter))

    def current_plan_token(self) -> str | None:
        """The applied plan's token, only while it matches the live text (and
        no input-method composition is pending: the token text excludes it)."""
        if self._preedit_text:
            return None
        if (
            self._plan_preview_active
            and self._applied_plan_generation == self._plan_generation
        ):
            return self._applied_plan_token
        return None


class TextEditManager:
    def __init__(self, view) -> None:
        self._view = view
        self._preview_renderer: PreviewRenderer | None = None
        self._last_mask_signature: tuple | None = None
        self._last_origin_mask_signature: tuple | None = None
        self._origin_mask_skip_signature: tuple | None = None

    def _clear_text_editor_mask_item(self) -> None:
        self._last_mask_signature = None
        mask_item = getattr(self._view, "_text_editor_mask_item", None)
        if mask_item is None:
            return
        try:
            if mask_item.scene():
                self._view.scene.removeItem(mask_item)
        except Exception:
            logger.debug("text editor mask removal skipped")
        self._view._text_editor_mask_item = None

    def _clear_text_editor_origin_mask_item(self) -> None:
        self._last_origin_mask_signature = None
        self._origin_mask_skip_signature = None
        origin_item = getattr(self._view, "_text_editor_origin_mask_item", None)
        if origin_item is None:
            return
        try:
            if origin_item.scene():
                self._view.scene.removeItem(origin_item)
        except Exception:
            logger.debug("text editor origin mask removal skipped")
        self._view._text_editor_origin_mask_item = None

    def _clear_text_editor_focus_border_item(self) -> None:
        border_item = getattr(self._view, "_text_editor_focus_border_item", None)
        if border_item is None:
            return
        try:
            if border_item.scene():
                self._view.scene.removeItem(border_item)
        except Exception:
            logger.debug("text editor focus border removal skipped")
        self._view._text_editor_focus_border_item = None

    def _sync_text_editor_focus_border_item(self, scene_rect: QRectF) -> None:
        if scene_rect.isEmpty() or not hasattr(self._view, "scene"):
            self._clear_text_editor_focus_border_item()
            return
        if not hasattr(self._view.scene, "addRect"):
            return
        border_rect = scene_rect.adjusted(-2.0, -2.0, 2.0, 2.0)
        pen = QPen(QColor(30, 120, 255, 230), 2)
        brush = QBrush(Qt.NoBrush)
        border_item = getattr(self._view, "_text_editor_focus_border_item", None)
        if border_item is None:
            border_item = self._view.scene.addRect(border_rect, pen, brush)
            self._view._text_editor_focus_border_item = border_item
        else:
            if hasattr(border_item, "setRect"):
                border_item.setRect(border_rect)
            if hasattr(border_item, "setPen"):
                border_item.setPen(pen)
            if hasattr(border_item, "setBrush"):
                border_item.setBrush(brush)
        if hasattr(border_item, "setZValue"):
            border_item.setZValue(13)

    def _sync_text_editor_mask_item(self, scene_rect: QRectF, mask_brush: QBrush) -> None:
        if scene_rect.isEmpty() or not hasattr(self._view, "scene"):
            self._clear_text_editor_mask_item()
            self._clear_text_editor_origin_mask_item()
            self._clear_text_editor_focus_border_item()
            return
        if not hasattr(self._view.scene, "addRect"):
            return
        pen = QPen(Qt.NoPen)
        mask_item = getattr(self._view, "_text_editor_mask_item", None)
        if mask_item is None:
            mask_item = self._view.scene.addRect(scene_rect, pen, mask_brush)
            self._view._text_editor_mask_item = mask_item
        else:
            if hasattr(mask_item, "setRect"):
                mask_item.setRect(scene_rect)
            if hasattr(mask_item, "setBrush"):
                mask_item.setBrush(mask_brush)
            if hasattr(mask_item, "setPen"):
                mask_item.setPen(pen)
        if hasattr(mask_item, "setZValue"):
            mask_item.setZValue(11)
        editor_proxy = getattr(self._view, "text_editor", None)
        if editor_proxy is not None and hasattr(editor_proxy, "setZValue"):
            editor_proxy.setZValue(12)

    def _resolve_mask_sampling(
        self, scene_rect: QRectF, page_idx: int | None = None
    ) -> tuple[QImage, QRect, float] | None:
        """``(image, image_rect, image px per scene px)``: the last is the pixmap's device pixel
        ratio for a high-quality render, so a width in IMAGE px is ``1 / k`` scene px."""
        if page_idx is None:
            page_idx = int(getattr(self._view, "_editing_page_idx", getattr(self._view, "current_page", -1)))
        page_items = getattr(self._view, "page_items", None)
        if not isinstance(page_items, list) or page_idx < 0 or page_idx >= len(page_items):
            return None
        page_item = page_items[page_idx]
        if page_item is None or not hasattr(page_item, "pixmap"):
            return None
        pixmap = page_item.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        item_rect = page_item.sceneBoundingRect() if hasattr(page_item, "sceneBoundingRect") else QRectF()
        if item_rect.isEmpty():
            return None
        local_rect = scene_rect.intersected(item_rect)
        if local_rect.isEmpty():
            return None
        image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        if image.isNull():
            return None
        scale_x = float(image.width()) / max(1.0, float(item_rect.width()))
        scale_y = float(image.height()) / max(1.0, float(item_rect.height()))
        img_x = int(math.floor((float(local_rect.left()) - float(item_rect.left())) * scale_x))
        img_y = int(math.floor((float(local_rect.top()) - float(item_rect.top())) * scale_y))
        img_w = max(1, int(math.ceil(float(local_rect.width()) * scale_x)))
        img_h = max(1, int(math.ceil(float(local_rect.height()) * scale_y)))
        image_rect = QRect(img_x, img_y, img_w, img_h).intersected(image.rect())
        if image_rect.isEmpty():
            return None
        return image, image_rect, max(scale_x, scale_y)

    def _build_background_matched_mask(
        self,
        scene_rect: QRectF,
        text_rgb: tuple[int, int, int],
        *,
        page_idx: int | None = None,
        tint: bool = True,
        measure_ring: bool = False,
        reach_scene_px: float = 0.0,
    ) -> tuple[QBrush, QColor, dict[str, object]]:
        """``page_idx`` samples another page than the one being edited and ``tint=False``
        keeps the plain ring-mean page colour (the round 7 origin patch).  ``measure_ring``
        adds ``ring_nonuniform_pct`` (RPU-2) to the debug dict: how much of the ring differs
        from its mean, i.e. how fake a flat patch of that colour would look.  ``reach_scene_px``
        (HDZ-1) is how far beyond ``scene_rect`` the caller will paint: the measured ring is at
        least that thick in SCENE px (it is a fixed 3 IMAGE px otherwise, which at device pixel
        ratio 2 or a high zoom is thinner than the cover and lets a rule in the gap read as flat)."""
        text_rgb_f: tuple[float, float, float] = tuple(float(v) for v in text_rgb)  # type: ignore[assignment]

        sampled = self._resolve_mask_sampling(scene_rect, page_idx)
        ring_rgb = (
            _qimage_ring_mean_rgb(sampled[0], sampled[1], _MASK_RING_THICKNESS_PX)
            if sampled is not None
            else None
        )
        if ring_rgb is None:
            return _make_fallback_mask_result(text_rgb_f)

        image_rect = sampled[1]
        # The editor rectangle itself can contain source glyph pixels. Build
        # a fail-closed opaque patch from the local perimeter color instead of
        # reusing interior texture that could ghost old glyphs during editing.
        patch = QImage(
            max(1, int(image_rect.width())),
            max(1, int(image_rect.height())),
            QImage.Format_RGBA8888,
        )
        patch.fill(
            QColor(
                int(round(ring_rgb[0])),
                int(round(ring_rgb[1])),
                int(round(ring_rgb[2])),
                255,
            )
        )
        leak_pct = _mask_leak_ratio(patch, ring_rgb)
        ring_nonuniform_pct = None
        if measure_ring:
            # +1 image px: ``image_rect`` itself is snapped outward from the exact span edge.
            measure_ring_px = max(_MASK_RING_THICKNESS_PX, int(math.ceil(float(reach_scene_px) * sampled[2])) + 1)
            raw_ratio = _qimage_ring_nonuniform_ratio(sampled[0], image_rect, measure_ring_px, ring_rgb)
            # A rule on one side is diluted 1/T by a T px ring (4.4 % at T=7 where the 3 px ring
            # reads 10 %), so normalise to the 3 px ring: the RPU-2 threshold then means the same
            # at every device pixel ratio and zoom.  Identical when no reach is requested.
            ring_nonuniform_pct = min(1.0, raw_ratio * measure_ring_px / _MASK_RING_THICKNESS_PX)

        mask_mean_rgb = _qimage_mean_rgb(patch, patch.rect()) or ring_rgb
        contrast_ratio = _contrast_ratio_rgb(text_rgb_f, mask_mean_rgb)
        tint_strength = 0.0
        if tint and contrast_ratio < _MASK_MIN_CONTRAST_RATIO:
            dark_contrast = _contrast_ratio_rgb(text_rgb_f, (0.0, 0.0, 0.0))
            light_contrast = _contrast_ratio_rgb(text_rgb_f, (255.0, 255.0, 255.0))
            tint_target = (0.0, 0.0, 0.0) if dark_contrast >= light_contrast else (255.0, 255.0, 255.0)
            base_patch = patch.copy()
            for candidate in _MASK_TINT_LADDER:
                patch = base_patch.copy()
                _blend_patch_towards_rgb(patch, tint_target, candidate)
                candidate_mean = _qimage_mean_rgb(patch, patch.rect()) or mask_mean_rgb
                candidate_contrast = _contrast_ratio_rgb(text_rgb_f, candidate_mean)
                tint_strength = float(candidate)
                contrast_ratio = candidate_contrast
                if candidate_contrast >= _MASK_MIN_CONTRAST_RATIO:
                    break

        mask_mean_rgb = _qimage_mean_rgb(patch, patch.rect()) or ring_rgb
        ring_delta = (
            abs(mask_mean_rgb[0] - ring_rgb[0])
            + abs(mask_mean_rgb[1] - ring_rgb[1])
            + abs(mask_mean_rgb[2] - ring_rgb[2])
        ) / 3.0
        mask_color = QColor(
            int(round(mask_mean_rgb[0])),
            int(round(mask_mean_rgb[1])),
            int(round(mask_mean_rgb[2])),
        )
        brush = QBrush(QPixmap.fromImage(patch))
        return (
            brush,
            mask_color,
            {
                "mask_mode": MASK_MODE_BACKGROUND_MATCH,
                "ring_delta": float(ring_delta),
                "leak_pct": float(leak_pct),
                "contrast_ratio": float(contrast_ratio),
                "tint_strength": float(tint_strength),
                "ring_nonuniform_pct": ring_nonuniform_pct,
            },
        )

    def current_text_editor_scene_rect(self) -> QRectF | None:
        editor = getattr(self._view, "text_editor", None)
        if not editor or not editor.widget():
            return None
        if hasattr(editor, "sceneBoundingRect"):
            return editor.sceneBoundingRect()
        pos = editor.pos() if hasattr(editor, "pos") else QPointF(0, 0)
        widget = editor.widget()
        return QRectF(pos.x(), pos.y(), float(widget.width()), float(widget.height()))

    def _page_pixmap_key(self, page_idx: int) -> int | None:
        """Identity of the page pixmap currently shown for ``page_idx`` (mask cache key)."""
        page_items = getattr(self._view, "page_items", None)
        if not isinstance(page_items, list) or not 0 <= page_idx < len(page_items):
            return None
        page_item = page_items[page_idx]
        if page_item is None or not hasattr(page_item, "pixmap"):
            return None
        pixmap = page_item.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        cache_key_fn = getattr(pixmap, "cacheKey", None)
        return int(cache_key_fn()) if callable(cache_key_fn) else id(pixmap)

    def sync_text_editor_origin_mask(self) -> None:
        """Round 7 (F1): while an edit_existing box is displaced, keep its SOURCE SPAN
        (``_editing_origin_span_scene_rect`` plus the glyph-overhang margin) covered with the
        untinted page colour of the origin page, so the source glyphs do not show beside the
        moved box (which paints the frozen original frame).  The editor widget rect at open
        (``_editing_origin_scene_rect``) is NOT covered: it can be far wider than the span and
        would erase a neighbouring run; it only drives the displacement test.  add_new never
        gets a patch: the page text under an add_text spot is real content."""
        view = self._view
        origin = getattr(view, "_editing_origin_scene_rect", None)
        # REG-1: what is COVERED is the source span; ``origin`` (the widget rect at open, which
        # can be much larger: >= 80 px min width) only drives the displacement test.
        span = getattr(view, "_editing_origin_span_scene_rect", None)
        scene = getattr(view, "scene", None)
        if (
            getattr(view, "editing_intent", None) != "edit_existing"
            or origin is None
            or origin.isEmpty()
            or span is None
            or span.isEmpty()
            or scene is None
            or not hasattr(scene, "addRect")
        ):
            self._clear_text_editor_origin_mask_item()
            return
        current = self.current_text_editor_scene_rect()
        item = getattr(view, "_text_editor_origin_mask_item", None)
        displaced = current is None or (
            abs(current.x() - origin.x()) > _ORIGIN_MASK_MIN_DISPLACEMENT_PX
            or abs(current.y() - origin.y()) > _ORIGIN_MASK_MIN_DISPLACEMENT_PX
        )
        if not displaced:
            if item is not None and hasattr(item, "setVisible"):
                item.setVisible(False)
            return
        origin_page = int(getattr(view, "_editing_origin_page_idx", getattr(view, "_editing_page_idx", -1)))
        aligned = span.toAlignedRect()
        margin = _origin_mask_margin_px(view)
        # Snapped outward to whole scene pixels: a fractional edge would blend the span's own
        # edge pixel and leave a faint sliver of the source glyph.
        cover = QRectF(span.adjusted(-margin, -margin, margin, margin).toAlignedRect())
        signature = (
            self._page_pixmap_key(origin_page),
            origin_page,
            (aligned.x(), aligned.y(), aligned.width(), aligned.height()),
            margin,
        )
        if signature == self._origin_mask_skip_signature:
            return  # measured non-uniform already; nothing to draw until the inputs change
        if item is None or signature != self._last_origin_mask_signature:
            # HDZ-1: gate the whole painted band (margin + the <1 px outward snap), not a fixed
            # 3 image px ring that is thinner than the cover at DPR 2 / high zoom.
            brush, _color, debug = self._build_background_matched_mask(
                span,
                (0, 0, 0),
                page_idx=origin_page,
                tint=False,
                measure_ring=True,
                reach_scene_px=margin + 1.0,
            )
            if debug.get("mask_mode") != MASK_MODE_BACKGROUND_MATCH:
                # A fallback contrast colour would be a visible block, worse than the bug.
                logger.debug("origin mask skipped: no page sample for page %s", origin_page)
                self._clear_text_editor_origin_mask_item()
                return
            nonuniform = debug.get("ring_nonuniform_pct")
            if isinstance(nonuniform, float) and nonuniform > _ORIGIN_MASK_MAX_RING_NONUNIFORM_PCT:
                # RPU-2: one flat colour over hatching / rules / an image is a fake block, worse
                # than the visible source text.  Keep the signature so a repaint does not re-measure.
                logger.debug(
                    "origin mask skipped: page %s background is not uniform (%.2f of the ring)",
                    origin_page,
                    nonuniform,
                )
                self._clear_text_editor_origin_mask_item()
                self._origin_mask_skip_signature = signature
                return
            if item is None:
                item = scene.addRect(cover, QPen(Qt.NoPen), brush)
                view._text_editor_origin_mask_item = item
            else:
                if hasattr(item, "setRect"):
                    item.setRect(cover)
                if hasattr(item, "setBrush"):
                    item.setBrush(brush)
            if hasattr(item, "setZValue"):
                item.setZValue(_ORIGIN_MASK_Z)
            self._last_origin_mask_signature = signature
        if hasattr(item, "setVisible"):
            item.setVisible(True)

    def refresh_text_editor_mask_color(self) -> None:
        editor_proxy = getattr(self._view, "text_editor", None)
        if not editor_proxy or not editor_proxy.widget():
            self._last_mask_signature = None
            return
        scene_rect = self.current_text_editor_scene_rect()
        if scene_rect is None:
            self._last_mask_signature = None
            return
        editor = editor_proxy.widget()
        text_rgb = tuple(editor.property("text_rgb") or (0, 0, 0))

        # Short-circuit when the inputs that drive mask appearance haven't
        # changed: same page pixmap, same editor footprint, same text color.
        page_idx = int(getattr(self._view, "_editing_page_idx", -1))
        pixmap_key = self._page_pixmap_key(page_idx)
        aligned = scene_rect.toAlignedRect()
        signature = (
            pixmap_key,
            page_idx,
            (aligned.x(), aligned.y(), aligned.width(), aligned.height()),
            text_rgb,
        )
        if signature == self._last_mask_signature and getattr(self._view, "_text_editor_mask_item", None) is not None:
            self._sync_text_editor_focus_border_item(scene_rect)
            self.sync_text_editor_origin_mask()
            return

        mask_brush, mask_color, mask_debug = self._build_background_matched_mask(scene_rect, text_rgb)
        self._sync_text_editor_mask_item(scene_rect, mask_brush)
        self._sync_text_editor_focus_border_item(scene_rect)
        editor.setStyleSheet(self._view._build_text_editor_stylesheet(text_rgb, mask_color))
        editor.setProperty("mask_rgb", (mask_color.red(), mask_color.green(), mask_color.blue()))
        editor.setProperty("mask_debug_metrics", mask_debug)
        self._last_mask_signature = signature
        self.sync_text_editor_origin_mask()

    def _capture_frozen_first_frame(
        self,
        *,
        scaled_rect: fitz.Rect,
        y0: float,
        pos_x: float,
        pos_y: float,
        editor_width_px: int,
        editor_height_px: int,
        normalized_rotation: int,
        x0: float = 0.0,
    ) -> QImage | None:
        graphics_view = getattr(self._view, "graphics_view", None)
        if graphics_view is None or not hasattr(graphics_view, "viewport"):
            return None
        try:
            # rotation 0/180: the editor's pre-rotation rect IS the PDF
            # bbox; grab it directly.
            #
            # rotation 90/180/270: the proxy is rotated about its origin
            # corner at display time (90/270 additionally swap the local
            # paint extents), so ``pos`` is NOT the bbox's top-left. Grab
            # the axis-aligned PDF bbox and COUNTER-rotate the bytes so
            # that, after the proxy's setRotation, the widget's local paint
            # lands back on the correct PDF pixels. Without this the grab
            # samples the empty page margin and the editor opens blank.
            # Gates: test_click_to_edit_qtest_integration[
            #          test-vertical-texts.pdf-vertical],
            #        test_text_edit_rotated_page_gui (90/180/270 pages).
            counter = PROXY_COUNTER_ROTATION.get(normalized_rotation)
            if counter is not None:
                bbox_tl = graphics_view.mapFromScene(QPointF(
                    float(x0 + scaled_rect.x0),
                    float(y0 + scaled_rect.y0),
                ))
                bbox_grab = QRect(
                    int(bbox_tl.x()),
                    int(bbox_tl.y()),
                    max(1, int(round(scaled_rect.width))),
                    max(1, int(round(scaled_rect.height))),
                )
                raw_img = (
                    graphics_view.viewport().grab(bbox_grab)
                    .toImage()
                    .convertToFormat(QImage.Format_RGBA8888)
                )
                return raw_img.transformed(QTransform().rotate(counter))
            else:
                vp_top_left = graphics_view.mapFromScene(QPointF(float(pos_x), float(pos_y)))
                grab_rect = QRect(
                    int(vp_top_left.x()),
                    int(vp_top_left.y()),
                    max(1, int(editor_width_px)),
                    max(1, int(editor_height_px)),
                )
                return (
                    graphics_view.viewport().grab(grab_rect)
                    .toImage()
                    .convertToFormat(QImage.Format_RGBA8888)
                )
        except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
            logger.debug("frozen-frame grab failed: %s", exc)
            return None

    def _compute_preview_line_height(
        self,
        page_idx: int,
        cluster_span_ids: list[str] | None,
    ) -> tuple[float, list | None]:
        line_ht = 0.0
        member_spans = None
        if not cluster_span_ids:
            return line_ht, member_spans
        try:
            model_ref = getattr(getattr(self._view, "controller", None), "model", None)
            if model_ref is None:
                return line_ht, member_spans
            bm = model_ref.block_manager
            spans = [bm.find_span_by_id(page_idx, sid) for sid in cluster_span_ids]
            spans = [s for s in spans if s is not None]
            if spans:
                member_spans = spans
                ordered = sorted(spans, key=lambda s: float(s.bbox.y0))
                if len(ordered) >= 2:
                    advances = [
                        abs(float(ordered[i + 1].bbox.y0) - float(ordered[i].bbox.y0))
                        for i in range(len(ordered) - 1)
                        if abs(float(ordered[i + 1].bbox.y0) - float(ordered[i].bbox.y0)) > 0.5
                    ]
                    if advances:
                        line_ht = sorted(advances)[len(advances) // 2]
                if line_ht <= 0:
                    heights = [float(s.bbox.height) for s in spans if s.bbox.height > 0]
                    if heights:
                        line_ht = max(heights)
        except Exception:
            line_ht = 0.0
        return line_ht, member_spans

    def _sync_font_combo_state(self, font_name: str, font_size: float) -> None:
        view = self._view
        size_str = _format_font_size(font_size)
        if view.text_size.findText(size_str) == -1:
            view.text_size.addItem(size_str)
            items = sorted(
                (view.text_size.itemText(i) for i in range(view.text_size.count())),
                key=lambda item: _parse_font_size_str(item) or 0.0,
            )
            view.text_size.clear()
            view.text_size.addItems(items)
        view.text_size.setCurrentText(size_str)
        view._last_valid_text_size_text = size_str
        view._text_size_input_dirty = False
        normalized_font = view._qt_font_to_pdf(font_name)
        view._set_text_font_by_pdf(normalized_font)
        view._editing_initial_size = float(font_size)
        view._editing_current_pdf_size = float(font_size)
        if not hasattr(view, "editing_font_name"):
            view.editing_font_name = normalized_font
        # Style-override baseline: the raw font name the session opened with
        # (``editing_font_name`` holds the PyMuPDF name, "Helvetica", on an
        # existing span; the combo later writes UI aliases such as "helv").
        # Every comparison against this baseline goes through
        # ``_font_alias`` so that an untouched session and a
        # pick-another-font-then-pick-it-back session both read as "no
        # override" -- a spurious override refuses the Tier 0 plan and falls
        # back to the legacy engine.
        view._editing_initial_font_name = str(view.editing_font_name)
        if not getattr(view, "_edit_font_size_connected", False):
            view.text_size.currentTextChanged.connect(view._on_edit_font_size_changed)
            view._edit_font_size_connected = True
        if not getattr(view, "_edit_font_family_connected", False):
            view.text_font.currentIndexChanged.connect(view._on_edit_font_family_changed)
            view._edit_font_family_connected = True

    def _install_editor_in_scene(
        self,
        editor: PreviewBackedInlineTextEditor,
        pos_x: float,
        pos_y: float,
        normalized_rotation: int,
        initial_frame: QImage | None,
    ) -> None:
        view = self._view
        view.text_editor = view.scene.addWidget(editor)
        # Round 6 (P1): the live text strip mirrors this editor from the moment it exists;
        # the matching unbind is in _teardown_editor (every close path funnels through it).
        bind_strip = getattr(view, "_bind_live_text_strip", None)
        if callable(bind_strip):
            bind_strip(editor)
        view.text_editor.setPos(round(pos_x), round(pos_y))
        # R4-2: the inline action bar follows the editor proxy.
        reposition_bar = getattr(view, "_position_text_action_bar", None)
        if callable(reposition_bar):
            for signal_name in ("xChanged", "yChanged", "geometryChanged"):
                signal = getattr(view.text_editor, signal_name, None)
                if signal is not None:
                    signal.connect(reposition_bar)
        if hasattr(view.text_editor, "setTransformOriginPoint"):
            view.text_editor.setTransformOriginPoint(0.0, 0.0)
        if hasattr(view.text_editor, "setRotation"):
            view.text_editor.setRotation(float(normalized_rotation))
        if initial_frame is not None:
            editor.freeze_first_frame(initial_frame)
        # Round 7 (F1): the editor widget rect at open, taken right before the first mask sync
        # so the two are identical by construction.  It is NOT covered by the origin patch (see
        # REG-1 below); it is only the reference for "has the box been displaced?".
        open_rect = self.current_text_editor_scene_rect()
        view._editing_origin_scene_rect = QRectF(open_rect) if open_rect is not None else None
        # R7-DEG-1: the open proxy position, so the grip-drag page clamp can keep it reachable (a
        # span's own bbox is built from font metrics and may cross the page edge).
        view._editing_open_proxy_pos = QPointF(view.text_editor.pos())
        # REG-1: the origin patch covers the SOURCE SPAN, not the (>= 80 px wide) widget rect, so
        # a neighbouring run on the same baseline stays visible.  ``editing_rect`` is in visual
        # page space, so the scene rect needs no rotation handling.
        span_rect = getattr(view, "_editing_original_rect", None)
        view._editing_origin_span_scene_rect = None
        if span_rect is not None:  # add_new is excluded in sync_text_editor_origin_mask
            span_rs = view._render_scale if view._render_scale > 0 else 1.0
            span_page_idx = getattr(view, "_editing_origin_page_idx", getattr(view, "_editing_page_idx", 0))
            view._editing_origin_span_scene_rect = QRectF(
                view._page_scene_x(span_page_idx) + span_rect.x0 * span_rs,
                view._page_scene_y(span_page_idx) + span_rect.y0 * span_rs,
                span_rect.width * span_rs,
                span_rect.height * span_rs,
            )
        self.refresh_text_editor_mask_color()
        view._editor_shortcut_forwarder = _EditorShortcutForwarder(view)
        if isinstance(view._editor_shortcut_forwarder, QObject):
            editor.installEventFilter(view._editor_shortcut_forwarder)
        editor.focus_out_requested.connect(view._schedule_finalize_on_focus_change)
        paste_cleaned = getattr(editor, "paste_cleaned", None)
        if paste_cleaned is not None:
            paste_cleaned.connect(self._on_editor_paste_cleaned)
        token_state = getattr(editor, "plan_token_state_changed", None)
        sync_apply = getattr(view, "_sync_text_apply_enabled", None)
        if token_state is not None and callable(sync_apply):
            token_state.connect(sync_apply)
        document = editor.document() if hasattr(editor, "document") else None
        refresh_undo_redo = getattr(view, "_refresh_undo_redo_action_state", None)
        if document is not None and callable(refresh_undo_redo):
            try:
                document.undoAvailable.connect(refresh_undo_redo)
                document.redoAvailable.connect(refresh_undo_redo)
            except (TypeError, RuntimeError):
                logger.debug("editor undo/redo signal hookup skipped")
        if callable(refresh_undo_redo):
            refresh_undo_redo()
        else:
            view._set_document_undo_redo_enabled(False)
        view._set_edit_focus_guard(True)
        sync_panel = getattr(view, "_sync_text_property_panel_state", None)
        if callable(sync_panel):
            sync_panel()
        editor.setFocus()

    def create_text_editor(
        self,
        rect: fitz.Rect,
        text: str,
        font_name: str,
        font_size: float,
        color: tuple = (0, 0, 0),
        rotation: int = 0,
        target_span_id: str | None = None,
        target_mode: str = "run",
        editor_intent: str = "edit_existing",
        cluster_span_ids: list[str] | None = None,
        source_ref: object | None = None,
    ) -> None:
        view = self._view
        if view.text_editor:
            view._finalize_text_edit()
            if self._editor_is_open():
                # UI step 9: the open editor's edit was not applied and it
                # stays open with its input; never stack a second editor.
                logger.warning("text editor kept open; new editor not created")
                return

        page_idx = getattr(view, "_editing_page_idx", view.current_page)
        rs = view._render_scale if view._render_scale > 0 else 1.0
        # edit_existing: wrap width is the exact source bbox width (no Qt
        # margin) so the editor wraps where the PDF wraps. add_new has no
        # source span, so fall back to the model's render-width helper.
        if editor_intent == "edit_existing":
            scaled_width = int(round(rect.width * rs))
        else:
            render_width_pt = view.controller.get_render_width_for_edit(page_idx + 1, rect)
            scaled_width = int(render_width_pt * rs)
        scaled_rect = rect * rs

        view.editing_rect = fitz.Rect(rect)
        view._editing_original_rect = fitz.Rect(rect)
        view._editing_origin_page_idx = page_idx
        x0 = view._page_scene_x(page_idx)
        y0 = view._page_scene_y(page_idx)
        display_font_pt = _display_font_pt(font_size, rs)
        qt_font_family = view._pdf_font_to_qt(font_name)
        # Run-level edits: first frame matches the clicked span bbox exactly.
        # Paragraph edits can target an oversized region box, so use the real
        # wrapped-text layout height instead.
        content_height_px = max(int(round(scaled_rect.height)), 1)
        if target_mode == "paragraph":
            measured_height_px = _measure_text_content_height_px(
                text=text,
                qt_font_family=qt_font_family,
                display_font_pt=display_font_pt,
                wrap_width_px=max(int(round(scaled_width)), 1),
            )
            content_height_px = max(measured_height_px, 1)
        if rotation not in (90, 270):
            height_cap_px = _viewport_editor_height_cap_px(view)
            if height_cap_px is not None:
                content_height_px = min(content_height_px, height_cap_px)
        editor_width_px, editor_height_px, pos_x, pos_y, normalized_rotation = _compute_editor_proxy_layout(
            scaled_rect=scaled_rect,
            scaled_width=scaled_width,
            page_y_offset=y0,
            rotation=rotation,
            content_height_px=content_height_px,
        )
        pos_x += x0
        editor_width_px, editor_height_px, pos_x, pos_y = _quarter_turn_proxy_layout(
            scaled_rect=scaled_rect,
            page_x=x0,
            page_y=y0,
            rotation=normalized_rotation,
            width_px=editor_width_px,
            height_px=editor_height_px,
            pos_x=pos_x,
            pos_y=pos_y,
        )

        initial_frame = self._capture_frozen_first_frame(
            scaled_rect=scaled_rect,
            y0=y0,
            x0=x0,
            pos_x=pos_x,
            pos_y=pos_y,
            editor_width_px=editor_width_px,
            editor_height_px=editor_height_px,
            normalized_rotation=normalized_rotation,
        )

        if self._preview_renderer is None:
            controller = getattr(view, "controller", None)
            builder = getattr(controller, "build_insert_preview_html", None)
            self._preview_renderer = PreviewRenderer(build_preview_html=builder)
        editor = PreviewBackedInlineTextEditor(text, self._preview_renderer)
        intent = editor_intent if editor_intent in ("edit_existing", "add_new") else "edit_existing"
        # UI step 11: set BEFORE the first configure_render_context so not even
        # the initial pass renders the CSS interim frame.  Plan mode needs the
        # request signal too: without it no verified raster could ever arrive.
        # Task B: keyed on THIS editor's intent (the argument -- the view's
        # ``editing_intent`` still holds the previous editor's value here).
        if self._plan_preview_applies(intent) and hasattr(
            view, "sig_text_edit_plan_preview"
        ):
            editor.set_plan_preview_mode(True)
        editor.setProperty("original_text", text)
        view._editing_rotation = normalized_rotation
        # R7-INT-2: the minimum-width floor (``MIN_EDITOR_WIDTH_PX``) pads a short source span's
        # box on its trailing (visual right) side at 0/180; the page clamp must hold the SOURCE
        # SPAN inside the page, not that padding.  edit_existing only: add_new's width is the
        # real wrap width.  90/270 have no floor (``_quarter_turn_proxy_layout``).
        span_pads_apply = editor_intent == "edit_existing" and normalized_rotation in (0, 180)
        view._editing_min_width_pad_px = (
            max(0, int(editor_width_px) - int(round(scaled_width))) if span_pads_apply else 0
        )
        # R3-INT-1: the same for the vertical axis.  A paragraph editor at 0/180 is measured taller
        # than its source span (wrap at the span width + the measuring document's margin) and the
        # excess hangs BELOW the span at both rotations (180 puts ``pos`` at the visual bottom).  The
        # clamp must hold the span, not the excess, on the page or a bottom-edge paragraph shoves up
        # on the first move and its open spot is unreachable.  Run mode: widget height == span, 0.
        view._editing_height_pad_px = (
            max(0, int(editor_height_px) - max(int(round(scaled_rect.height)), 1))
            if span_pads_apply
            else 0
        )
        view.editing_target_span_id = target_span_id
        view.editing_source_ref = source_ref
        # UI step 9: bind the edit to the document session it was opened in
        # (stamped NOW -- at finalize the active session may already differ).
        # (The same active-tab lookup the floating-note popup binds to.)
        active_session_of = getattr(view, "_active_document_session_id", None)
        view.editing_session_id = (
            active_session_of() if callable(active_session_of) else None
        )
        view.editing_target_mode = target_mode if target_mode in ("run", "paragraph") else "run"
        view.editing_intent = intent

        qt_font_obj = QFont(qt_font_family)
        qt_font_obj.setPointSizeF(display_font_pt)
        editor.setFont(qt_font_obj)

        r, g, b = [int(c * 255) for c in color]
        text_rgb = (r, g, b)
        mask_color = _readable_editor_mask_color(text_rgb)
        editor.setProperty("text_rgb", text_rgb)
        editor.setAutoFillBackground(False)
        editor.viewport().setAutoFillBackground(False)
        editor.setStyleSheet(view._build_text_editor_stylesheet(text_rgb, mask_color))

        editor.setFixedWidth(editor_width_px)
        setattr(editor, "_width", editor_width_px)
        editor.setFixedHeight(editor_height_px)
        setattr(editor, "_height", editor_height_px)
        editor.setLineWrapMode(QTextEdit.WidgetWidth)
        editor.setWordWrapMode(QTextOption.WrapAnywhere)
        plan_mode = getattr(editor, "plan_preview_mode", None)
        if callable(plan_mode) and plan_mode() and view.editing_target_mode == "run":
            # Round 6 (P1): the plan-mode box never paints native glyphs, and Qt's advances
            # (1.0 em for CJK) exceed the PDF's, so wrapping split even the ORIGINAL line
            # into an invisible second row (Home/Up/Down jumped across hidden lines).  A run
            # is one line; the live strip shows the wrapped view.  Paragraph editors hold
            # real multi-line text and keep wrapping.
            editor.setLineWrapMode(QTextEdit.NoWrap)

        line_ht_for_preview, member_spans_for_preview = self._compute_preview_line_height(
            page_idx, cluster_span_ids,
        )

        editor.configure_render_context(
            font_name=font_name,
            font_size=float(font_size),
            color=tuple(float(c) for c in color),
            member_spans=member_spans_for_preview,
            rect_pt=fitz.Rect(rect),
            rotation=normalized_rotation,
            render_scale=float(rs),
            line_height=line_ht_for_preview,
        )

        # Installed AFTER the initial configure so the unchanged first frame
        # (already pixel-exact via the frozen capture) emits no request.
        # Task B: only a true-text edit has a source run to plan against.  An
        # add box is a NEW text box: a plan preview would resolve whatever
        # existing run lies under it and verify a token for an edit the user
        # is not making (preview != Apply).
        if intent == "edit_existing":
            self._install_plan_preview_hook(
                editor,
                page_idx=page_idx,
                rect=fitz.Rect(rect),
                original_text=text,
                target_span_id=target_span_id,
                target_mode=view.editing_target_mode,
                source_ref=source_ref,
                rotation=normalized_rotation,
                render_scale=float(rs),
                initial_font=font_name,
                initial_size=float(font_size),
                document_session_id=view.editing_session_id,
            )

        self._sync_font_combo_state(font_name, font_size)

        self._install_editor_in_scene(editor, pos_x, pos_y, normalized_rotation, initial_frame)

    def _install_plan_preview_hook(
        self,
        editor,
        *,
        page_idx: int,
        rect: fitz.Rect,
        original_text: str,
        target_span_id: str | None,
        target_mode: str | None,
        rotation: int,
        render_scale: float,
        initial_font: str,
        initial_size: float,
        source_ref: object | None = None,
        document_session_id: str | None = None,
    ) -> None:
        """Emit-only wiring for the exact plan-backed preview (V2 Task 8).

        The hook packages primitives and emits ``sig_text_edit_plan_preview``
        — the View never opens a PDF and never calls the Model.  ``rect`` /
        ``clip_rect`` are displayed-space; the raster that comes back is a
        displayed-space clip, and rotated editors (``rotation`` 90/180/270,
        the on-screen glyph rotation) counter-rotate it into their proxy-local
        frame in ``apply_plan_preview`` -- the same transform the frozen first
        frame uses -- so the exact preview stays available on ``/Rotate``
        pages and for rotated text alike.
        """
        view = self._view
        del rotation  # orientation is handled by the editor at paint time
        if not hasattr(view, "sig_text_edit_plan_preview"):
            return
        session_key = str(uuid.uuid4())
        editor.plan_preview_session_key = session_key
        rect_tuple = (
            float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1),
        )

        def _emit(text: str, generation: int) -> None:
            current_font = getattr(view, "editing_font_name", initial_font)
            session_initial_font = getattr(
                view, "_editing_initial_font_name", initial_font
            )
            current_size = float(
                getattr(view, "_editing_current_pdf_size", initial_size)
            )
            session_initial_size = float(
                getattr(view, "_editing_initial_size", initial_size)
            )
            style_overrides = build_style_overrides(
                current_font=current_font,
                initial_font=session_initial_font,
                font_key=lambda name: _font_alias(view, name),
                current_size=current_size,
                initial_size=session_initial_size,
            )
            current_rect = getattr(view, "editing_rect", None)
            original_rect = getattr(view, "_editing_original_rect", rect)
            new_rect = None
            if current_rect is not None and original_rect is not None:
                if (
                    abs(float(current_rect.x0) - float(original_rect.x0)) > 0.01
                    or abs(float(current_rect.y0) - float(original_rect.y0)) > 0.01
                    or abs(float(current_rect.x1) - float(original_rect.x1)) > 0.01
                    or abs(float(current_rect.y1) - float(original_rect.y1)) > 0.01
                ):
                    new_rect = tuple(float(value) for value in current_rect)
            view.sig_text_edit_plan_preview.emit(
                {
                    "session_key": session_key,
                    "page_idx": int(page_idx),
                    "rect": rect_tuple,
                    "original_text": original_text,
                    "target_span_id": target_span_id,
                    "target_mode": target_mode,
                    "source_ref": source_ref,
                    "replacement_text": text,
                    "generation": int(generation),
                    "clip_rect": rect_tuple,
                    "render_scale": float(render_scale),
                    "style_overrides": style_overrides,
                    "new_rect": new_rect,
                    # UI step 9: the Controller refuses a preview for any
                    # document session but the one the editor was opened in.
                    "document_session_id": document_session_id,
                }
            )

        if hasattr(editor, "set_plan_preview_hook"):
            editor.set_plan_preview_hook(_emit)

    def on_edit_font_family_changed(self, *_) -> None:
        view = self._view
        if not view.text_editor or not view.text_editor.widget():
            return
        editor = view.text_editor.widget()
        selected_pdf_font = view._qt_font_to_pdf(
            str(view.text_font.currentData() or view.text_font.currentText())
        )
        font = editor.font()
        font.setFamily(view._pdf_font_to_qt(selected_pdf_font))
        editor.setFont(font)
        if hasattr(editor, "configure_render_context"):
            editor.configure_render_context(font_name=selected_pdf_font)
        view.editing_font_name = selected_pdf_font
        self.refresh_text_editor_mask_color()
        self._sync_view_apply_enabled()
        call_later(
            view,
            TextEditUIConstants.FOCUS_RESTORE_DELAY_MS,
            lambda: editor.setFocus(Qt.OtherFocusReason)
            if (view.text_editor and view.text_editor.widget() is editor)
            else None,
        )

    def on_edit_font_size_changed(self, size_str: str) -> None:
        view = self._view
        if not view.text_editor or not view.text_editor.widget():
            return
        size = _parse_font_size_str(size_str)
        if size is None or size <= 0:
            return
        view._editing_current_pdf_size = float(size)
        editor = view.text_editor.widget()
        font = editor.font()
        # Combo values stay in PDF points; the widget font is display-scaled.
        rs = view._render_scale if getattr(view, "_render_scale", 0) > 0 else 1.0
        font.setPointSizeF(_display_font_pt(size, rs))
        editor.setFont(font)
        if hasattr(editor, "configure_render_context"):
            editor.configure_render_context(font_size=float(size))
        self.refresh_text_editor_mask_color()
        self._sync_view_apply_enabled()
        call_later(
            view,
            TextEditUIConstants.FOCUS_RESTORE_DELAY_MS,
            lambda: editor.setFocus(Qt.OtherFocusReason)
            if (view.text_editor and view.text_editor.widget() is editor)
            else None,
        )

    def finalize_text_edit(
        self,
        reason: TextEditFinalizeReason = TextEditFinalizeReason.CLICK_AWAY,
        *,
        allow_rebuild: bool = False,
    ) -> TextEditFinalizeResult | None:
        view = self._view
        if view._finalizing_text_edit:
            return view._last_text_edit_finalize_result
        if not view.text_editor or not view.text_editor.widget():
            view._set_edit_focus_guard(False)
            view._edit_focus_check_pending = False
            return None
        view._finalizing_text_edit = True
        try:
            result = self.finalize_text_edit_impl(reason, allow_rebuild=allow_rebuild)
            view._last_text_edit_finalize_result = result
            logger.debug(
                "text edit finalize: reason=%s intent=%s outcome=%s delta=%s",
                result.reason.value,
                result.intent,
                result.outcome.value,
                result.delta,
            )
            return result
        finally:
            # UI step 9: an editor kept open (edit not applied) keeps its
            # app-level focus-out net; only a torn-down editor drops it.
            view._set_edit_focus_guard(self._editor_is_open())
            view._edit_focus_check_pending = False
            view._finalizing_text_edit = False

    def _editor_is_open(self) -> bool:
        proxy = getattr(self._view, "text_editor", None)
        if proxy is None:
            return False
        try:
            return proxy.widget() is not None
        except RuntimeError:  # the proxy was deleted under us (scene.clear)
            return False

    def _sync_view_apply_enabled(self) -> None:
        sync_apply = getattr(self._view, "_sync_text_apply_enabled", None)
        if callable(sync_apply):
            sync_apply()

    def _plan_preview_applies(self, intent: str | None = None) -> bool:
        """Task B chokepoint: does the true-text plan preview (and with it the
        Apply token gate, the refusal state and the rebuild offer) govern an
        editor of ``intent`` (default: the live editor's)?

        Only a true-text edit of existing text (``edit_existing``).  An add
        box (``add_new``) is a new text box committed by ``add_textbox``: it
        has no source run to plan against and cannot change existing text.
        This is the ONLY read of the plan-preview mode flag in this module
        (guarded by test), so a new mode flag is decided per intent here."""
        view = self._view
        if intent is None:
            intent = getattr(view, "editing_intent", "edit_existing")
        return intent == "edit_existing" and bool(
            getattr(view, "_text_plan_preview_required", False)
        )

    def apply_permitted(self) -> bool:
        """UI step 5 (apply by token): may the inline Apply commit right now?

        With plan preview on (see ``_plan_preview_applies``), a text edit
        commits only the candidate whose verified preview the
        editor currently shows, so Apply waits for a current-generation
        token; the editor stays open meanwhile (click-away decision).
        Exempt: only an untouched session (Apply is a no-op close), and an
        add box (Task B: never token-gated).  UI step
        10: a drag, a cross-page move or a restyle has no verified preview
        (the preview refuses overrides), so Apply stays disabled for them
        and the explicit "改用重建文字…" action is their way forward (it
        bypasses this gate on purpose; see ``request_rebuild``).
        """
        view = self._view
        proxy = getattr(view, "text_editor", None)
        editor = proxy.widget() if proxy else None
        if editor is None:
            return False
        if _editor_is_composing(editor):
            # Before the add-box exemption below: a composition is un-applied
            # input for every intent.
            return False
        if not self._plan_preview_applies():
            return True
        text_changed = _normalize_for_edit_compare(
            editor.toPlainText()
        ) != _normalize_for_edit_compare(editor.property("original_text") or "")
        if not (
            text_changed
            or _editing_style_changed(view)
            or _editing_position_changed(view)
            or _editing_page_changed(view)
        ):
            return True
        token_of = getattr(editor, "current_plan_token", None)
        return callable(token_of) and token_of() is not None

    def _live_editor(self):
        proxy = getattr(self._view, "text_editor", None)
        try:
            return proxy.widget() if proxy is not None else None
        except RuntimeError:  # the proxy was deleted under us (scene.clear)
            return None

    def current_rejection_reason(self) -> str | None:
        """UI step 10: the refusal the live editor should show, as a code.

        The editor's recorded refusal for its current generation, mapped to
        what the user actually did (a restyle or drag previews as
        ``no_change``; see ``effective_rejection_reason``)."""
        editor = self._live_editor()
        reason_of = getattr(editor, "plan_rejection_reason", None)
        if not callable(reason_of):
            return None
        view = self._view
        if getattr(view, "editing_intent", "edit_existing") == "add_new":
            # Task B: an add box never previews, so its only refusal is the
            # Controller's refusal of the add itself (e.g. another document
            # session) -- shown as is, never rewritten as a true-text reason.
            return reason_of()
        return effective_rejection_reason(
            reason_of(),
            page_changed=_editing_page_changed(view),
            position_changed=_editing_position_changed(view),
            style_changed=_editing_style_changed(view),
            paragraph_mode=getattr(view, "editing_target_mode", None) == "paragraph",
        )

    def refused_input_reason(self) -> str | None:
        """CLOSE-PROMPT-1: the refusal code when the live editor holds input
        that was refused and so can never be applied as typed; else ``None``.

        ``None`` for: no editor, nothing un-applied, a composition (the input
        method still owns the text), a verified preview (the plan token commits
        it), and input whose preview is still updating (no refusal yet).  A
        close prompt uses this to stop offering a save that cannot include the
        input."""
        editor = self._live_editor()
        if editor is None or _editor_is_composing(editor):
            return None
        if not self.has_unapplied_input():
            return None
        token_of = getattr(editor, "current_plan_token", None)
        if callable(token_of) and token_of() is not None:
            return None
        return self.current_rejection_reason() or None

    def rebuild_offered(self) -> bool:
        """Whether "改用重建文字…" is offered for the current input.

        Task B: never for an add box -- there is no existing text to rebuild,
        and its "rebuild" would be an unconsented ``add_textbox``."""
        if getattr(self._view, "editing_intent", "edit_existing") != "edit_existing":
            return False
        return rebuild_offered_for(self.current_rejection_reason())

    def request_rebuild(self) -> TextEditFinalizeResult | None:
        """UI step 10 (critique B4): the explicit rebuild consent.

        Sends the SAME target and text as Apply would, with
        ``allow_rebuild=True`` and no token, through the Controller's consent
        path (its confirm dialog, default No).  Only while a rebuildable
        refusal is current -- a stale or queued click does nothing.  The
        consent belongs to this one request; nothing is remembered."""
        if not self.rebuild_offered():
            return None
        return self.finalize_text_edit(
            TextEditFinalizeReason.APPLY, allow_rebuild=True
        )

    def finalize_text_edit_impl(
        self,
        reason: TextEditFinalizeReason = TextEditFinalizeReason.CLICK_AWAY,
        *,
        allow_rebuild: bool = False,
    ) -> TextEditFinalizeResult:
        """``allow_rebuild`` is the explicit "改用重建文字…" consent (UI step
        10): an argument of THIS call only, never stored, so it cannot leak
        into a later finalize (consent is per request)."""
        view = self._view
        if not view.text_editor or not view.text_editor.widget():
            raise RuntimeError("Cannot finalize text edit without an active editor")

        if reason not in _DISCARD_REASONS:
            # CS1: a keep/commit finalize while the grip is still pressed
            # (Ctrl+S, zoom) must not abandon the drag half-way -- the box
            # stays at the displaced spot, so ``editing_rect`` has to follow it
            # before the delta is read.  Complete the drag as the release it
            # stands in for (a press that never moved the box just resets the
            # cursor); later grip moved/finished events are then ignored.
            settle = getattr(view, "_settle_lost_grip_drag", None)
            if callable(settle):
                settle()
        editor = view.text_editor.widget()
        new_text = editor.toPlainText()
        original_text_prop = editor.property("original_text")
        text_changed = (
            _normalize_for_edit_compare(new_text)
            != _normalize_for_edit_compare(original_text_prop or "")
        )

        original_rect = view._editing_original_rect
        current_rect = view.editing_rect
        position_changed = (
            original_rect is not None and current_rect is not None and
            (
                abs(current_rect.x0 - original_rect.x0) > TextEditGeometryConstants.POSITION_CHANGE_TOLERANCE_PT
                or abs(current_rect.y0 - original_rect.y0) > TextEditGeometryConstants.POSITION_CHANGE_TOLERANCE_PT
            )
        )

        combo_size = _parse_font_size_str(view.text_size.currentText())
        current_size_attr = getattr(view, "_editing_current_pdf_size", combo_size)
        initial_size_attr = getattr(view, "_editing_initial_size", current_size_attr)
        try:
            current_size = float(current_size_attr) if current_size_attr is not None else (combo_size or 0.0)
        except (TypeError, ValueError):
            current_size = combo_size or 0.0
        try:
            initial_size = float(initial_size_attr) if initial_size_attr is not None else current_size
        except (TypeError, ValueError):
            initial_size = current_size
        session = TextEditSession(
            original_rect=fitz.Rect(original_rect) if original_rect else None,
            current_rect=fitz.Rect(current_rect) if current_rect else None,
            current_font=getattr(view, "editing_font_name", "helv"),
            initial_font=getattr(view, "_editing_initial_font_name", getattr(view, "editing_font_name", "helv")),
            original_color=getattr(view, "editing_color", (0, 0, 0)),
            current_size=float(current_size),
            initial_size=float(initial_size),
            edit_page=getattr(view, "_editing_page_idx", view.current_page),
            origin_page=getattr(view, "_editing_origin_page_idx", getattr(view, "_editing_page_idx", view.current_page)),
            intent=getattr(view, "editing_intent", "edit_existing"),
            target_span_id=getattr(view, "editing_target_span_id", None),
            target_mode=getattr(view, "editing_target_mode", "run"),
            original_text=getattr(view, "editing_original_text", None),
            source_ref=getattr(view, "editing_source_ref", None),
            session_id=getattr(view, "editing_session_id", None),
        )
        font_changed = _font_alias(view, session.current_font) != _font_alias(
            view, session.initial_font
        )
        size_changed = abs(float(session.current_size) - float(session.initial_size)) > 1e-3
        delta = TextEditDelta(
            text_changed=text_changed,
            style_changed=(font_changed or size_changed),
            position_changed=position_changed,
            page_changed=(session.origin_page != session.edit_page),
        )

        view._drag_pending = False
        view._drag_active = False
        view._drag_start_scene_pos = None
        view._drag_editor_start_pos = None
        view._pending_text_info = None
        if hasattr(view, "_text_edit_drag_state"):
            view._text_edit_drag_state = TextEditDragState.IDLE
        reset_grip = getattr(view, "_reset_move_grip_latch", None)
        if callable(reset_grip):
            reset_grip()  # SEQ-1: a swallowed release must not leave the grip latched

        def _result(
            outcome: TextEditOutcome, edit_result: EditTextResult | None = None
        ) -> TextEditFinalizeResult:
            return TextEditFinalizeResult(
                reason=reason,
                outcome=outcome,
                intent=session.intent,
                edit_page=session.edit_page,
                origin_page=session.origin_page,
                delta=delta,
                edit_result=edit_result,
            )

        if reason in _DISCARD_REASONS:
            self._teardown_editor()
            return _result(TextEditOutcome.DISCARDED)

        if _editor_is_composing(editor):
            # Part 5 / A1: an input-method composition is un-applied input the
            # text and the token do NOT contain.  Never commit the text
            # without it (token or not), never treat the box as a no-op:
            # keep-reasons keep the editor and the preedit; close-always
            # reasons discard visibly.
            if reason in _KEEP_EDITOR_REASONS:
                return self._not_applied(
                    reason, _result, None, emitted=False, composing=True
                )
            self._teardown_editor()
            show = getattr(view, "_show_toast", None)
            if callable(show):
                show(_COMPOSING_DISCARD_NOTICE, duration_ms=3500, tone="warning")
            return _result(TextEditOutcome.DISCARDED)

        # UI step 9: build the commit, EMIT it while the editor still exists,
        # pull the Controller's REAL result, and tear the editor down only on
        # SUCCESS.  (Before step 9 the editor was torn down first and the
        # emit counted as COMMITTED, so a refusal lost the typed input.)
        if session.intent == "add_new":
            if not (new_text.strip() and session.current_rect is not None):
                self._teardown_editor()
                return _result(TextEditOutcome.NO_OP)

            def _emit() -> None:
                # Task B: bound to the document session the box was opened
                # in -- the Controller refuses it for any other document
                # (before, only the finalize ordering protected it).
                view.sig_add_textbox.emit(
                    session.edit_page + 1,
                    session.current_rect,
                    new_text,
                    session.current_font or view._add_text_default_pdf_font,
                    session.current_size,
                    session.original_color,
                    session.session_id,
                )
        elif not delta.any_change or not session.original_rect:
            self._teardown_editor()
            return _result(TextEditOutcome.NO_OP)
        else:
            if not allow_rebuild and not self.apply_permitted():
                # Plan preview is on and the typed input has no verified
                # preview yet: nothing may be committed.  (The explicit
                # rebuild consent bypasses the token gate by design,
                # critique B2: it can never have a token.)
                return self._not_applied(reason, _result, None, emitted=False)
            vertical_shift_left = getattr(view, "vertical_shift_left_cb", None)
            vertical_shift_left_value = vertical_shift_left.isChecked() if vertical_shift_left else True
            new_rect_arg = session.current_rect if position_changed else None
            if delta.page_changed and session.current_rect is not None:
                move_request = MoveTextRequest(
                    source_page=session.origin_page + 1,
                    source_rect=session.original_rect,
                    destination_page=session.edit_page + 1,
                    destination_rect=session.current_rect,
                    new_text=new_text,
                    font=session.current_font,
                    size=session.current_size,
                    color=session.original_color,
                    original_text=session.original_text,
                    target_span_id=session.target_span_id,
                    target_mode=session.target_mode,
                    session_id=session.session_id,
                    allow_rebuild=allow_rebuild,
                )

                def _emit() -> None:
                    view.sig_move_text_across_pages.emit(move_request)
            else:
                plan_token = (
                    editor.current_plan_token()
                    if hasattr(editor, "current_plan_token") and not allow_rebuild
                    else None
                )
                request = EditTextRequest(
                    page=session.edit_page + 1,
                    rect=session.original_rect,
                    new_text=new_text,
                    font=session.current_font,
                    size=session.current_size,
                    color=session.original_color,
                    original_text=session.original_text,
                    vertical_shift_left=vertical_shift_left_value,
                    new_rect=new_rect_arg,
                    target_span_id=session.target_span_id,
                    target_mode=session.target_mode,
                    style_overrides=build_style_overrides(
                        current_font=session.current_font,
                        initial_font=session.initial_font,
                        font_key=lambda name: _font_alias(view, name),
                        current_size=session.current_size,
                        initial_size=session.initial_size,
                    ),
                    plan_token=plan_token,
                    source_ref=session.source_ref,
                    # UI step 5/9: with plan preview on, EVERY commit of an
                    # in-place text edit (Apply, click-away, mode/session
                    # change, save) is bound to the verified preview's
                    # token -- not only Apply.  A drag stays tokenless (it
                    # is rebuild-only; the model refuses it, step 7).
                    requires_preview_token=(
                        self._plan_preview_applies(session.intent)
                        and not position_changed
                        and not allow_rebuild
                    ),
                    session_id=session.session_id,
                    # UI step 10: only "改用重建文字…" sets it, for this
                    # request alone (tokenless; the Controller asks).
                    allow_rebuild=allow_rebuild,
                )

                def _emit() -> None:
                    view.sig_edit_text.emit(request)

        # The token is part of the key: a fresh verified preview (another
        # document state) may be retried by a click-away; the same one may not.
        token_of = getattr(editor, "current_plan_token", None)
        input_key = self._input_key(new_text, session) + (
            token_of() if callable(token_of) else None,
        )
        if (
            reason is not TextEditFinalizeReason.APPLY
            and input_key == getattr(editor, "_refused_input_key", None)
        ):
            # The Controller already refused exactly this input: a click-away
            # or focus change must not re-send it (and re-toast) in a loop.
            return self._not_applied(
                reason, _result, None, emitted=False, already_refused=True
            )
        try:
            _emit()
        except Exception as exc:
            logger.error("發送編輯信號時出錯: %s", exc)
            if reason not in _KEEP_EDITOR_REASONS:
                self._teardown_editor()
            return _result(TextEditOutcome.FAILED)
        # UI step 10: the refusal shown before this attempt -- a declined
        # rebuild leaves the same refusal standing.
        refusal_before = (
            editor.plan_rejection_reason()
            if hasattr(editor, "plan_rejection_reason")
            else None
        )
        known, edit_result = self._pull_edit_result()
        refusal_reason = self._pull_refusal_reason() if known else None
        if not known or edit_result is EditTextResult.SUCCESS:
            # ``known`` is False only for a View without the Controller's
            # pull API (unit harnesses): the pre-step-9 emit-means-committed
            # contract.  The real app always pulls.
            self._teardown_editor()
            return _result(TextEditOutcome.COMMITTED, edit_result)
        if self._editor_is_open() and view.text_editor.widget() is editor:
            editor._refused_input_key = input_key
        if refusal_reason is None and edit_result is EditTextResult.FALLBACK_DECLINED:
            refusal_reason = refusal_before
        return self._not_applied(
            reason, _result, edit_result, emitted=True, refusal_reason=refusal_reason
        )

    @staticmethod
    def _input_key(new_text: str, session: TextEditSession) -> tuple:
        rect = session.current_rect
        return (
            new_text,
            str(session.current_font),
            round(float(session.current_size), 3),
            tuple(round(float(v), 2) for v in rect) if rect is not None else None,
            session.edit_page,
        )

    def _pull_edit_result(self) -> tuple[bool, EditTextResult | None]:
        """The Controller's REAL result of the edit just emitted (pull-and-clear).

        ``(False, None)`` when the View has no Controller pull API; an
        unknown value counts as "not SUCCESS" (never assume success)."""
        controller = getattr(self._view, "controller", None)
        pull = getattr(controller, "consume_last_edit_result", None)
        if not callable(pull):
            return False, None
        value = pull()
        return True, value if isinstance(value, EditTextResult) else None

    def _pull_refusal_reason(self) -> str | None:
        """UI step 10: the reason code of the refusal just pulled (REJECTED
        only; pull-and-clear), or ``None``."""
        controller = getattr(self._view, "controller", None)
        pull = getattr(controller, "consume_last_edit_refusal_reason", None)
        if not callable(pull):
            return None
        value = pull()
        return str(value) if value else None

    def _not_applied(
        self,
        reason: TextEditFinalizeReason,
        make_result,
        edit_result: EditTextResult | None,
        *,
        emitted: bool,
        refusal_reason: str | None = None,
        already_refused: bool = False,
        composing: bool = False,
    ) -> TextEditFinalizeResult:
        """Policy for an edit that was not applied (refused, or no token yet)."""
        view = self._view
        if reason in _KEEP_EDITOR_REASONS and self._editor_is_open():
            editor = view.text_editor.widget()
            if emitted and hasattr(editor, "invalidate_plan_preview"):
                # ``controller.edit_text`` ended the preview session on the
                # attempt, so the in-flight result would be dropped: re-arm a
                # fresh preview or Apply could never become available again.
                editor.invalidate_plan_preview(regenerate=True)
            if refusal_reason and hasattr(editor, "set_plan_preview_state"):
                # UI step 10: AFTER the re-arm (it bumps the generation): the
                # refusal stands for the kept input until the input changes or
                # a newer preview result replaces it.  In legacy preview mode
                # this is the only source of the reason.
                editor.set_plan_preview_state(editor._plan_generation, refusal_reason)
            notice = self._kept_notice(
                reason, emitted=emitted, already_refused=already_refused, composing=composing
            )
            pointer_key = (editor.toPlainText(), _editor_preedit_text(editor))
            if reason is TextEditFinalizeReason.FOCUS_OUTSIDE and not self._focus_outside_notice_allowed():
                # A dialog / menu took the focus, or the app lost it: no
                # notice, and nothing is recorded as said.
                notice = None
            elif reason in _POINTER_NOTICE_REASONS and notice:
                # R4-3: the same state never says it twice (a Ctrl+S notice
                # followed by the save modal's focus change, a repeated click).
                if getattr(editor, "_pointer_notice_stamp", None) == pointer_key:
                    notice = None
            if emitted or notice:
                editor._pointer_notice_stamp = pointer_key
            if notice and reason is TextEditFinalizeReason.VIEW_RESCALE:
                # Part 5 / D (defect 5): a Ctrl+wheel gesture refused many times in a row says it once while the editor is kept and its text is unchanged.
                shown_key = (reason, notice, editor.toPlainText())
                if getattr(editor, "_kept_notice_shown", None) == shown_key:
                    notice = None
                else:
                    editor._kept_notice_shown = shown_key
            if notice:
                show = getattr(view, "_show_toast", None)
                if callable(show):
                    show(notice, duration_ms=3000, tone="warning")
            self._sync_view_apply_enabled()
            if reason is TextEditFinalizeReason.APPLY and editor.isVisible():
                # S10 concern, fixed at the root: the re-arm above disabled the
                # Tab-focused Apply (or rebuild) button (keyboard path, KBD-1); give focus back to the
                # editor NOW, before the focus net's delayed FOCUS_OUTSIDE
                # finalize can run and overwrite this result.  The view must
                # hold the keyboard focus too: the editor lives in a proxy, so
                # its own setFocus only moves the scene's focus item.
                graphics_view = getattr(view, "graphics_view", None)
                if graphics_view is not None:
                    graphics_view.setFocus(Qt.OtherFocusReason)
                editor.setFocus(Qt.OtherFocusReason)
            if reason is TextEditFinalizeReason.CLICK_AWAY:
                # Ignore the click: keep typing where the user was.
                call_later(
                    view,
                    0,
                    lambda: editor.setFocus(Qt.OtherFocusReason)
                    if (view.text_editor and view.text_editor.widget() is editor)
                    else None,
                )
            return make_result(TextEditOutcome.REFUSED, edit_result)
        self._teardown_editor()
        show = getattr(view, "_show_toast", None)
        if callable(show):
            show(_NOT_APPLIED_DISCARD_NOTICE, duration_ms=3500, tone="warning")
        return make_result(TextEditOutcome.DISCARDED, edit_result)

    def _on_editor_paste_cleaned(self, controls_removed: int, images_dropped: int) -> None:
        """S17-PASTE-NOTICE: say in the status bar what the last paste removed."""
        message = paste_cleaned_notice(controls_removed, images_dropped)
        status_bar = getattr(self._view, "status_bar", None)
        if message and status_bar is not None:
            status_bar.showMessage(message, _PASTE_NOTICE_DURATION_MS)

    def notify_same_mode_reentry(self) -> str | None:
        """Part 5 round 5: say why a kept editor is still there when the
        current mode is re-entered (F2, ribbon re-click, context menu on the
        editor's own run).  Notifies only: it never finalizes (that would be
        click-away semantics and contradict R4-4).  Returns the notice shown,
        or None.  Has its own de-dup stamp: the click-away stamp must not
        silence it (the owner clicked away before pressing F2)."""
        editor = self._live_editor()
        if editor is None:
            return None
        preedit = _editor_preedit_text(editor)
        if _editor_is_composing(editor):
            notice = _COMPOSING_ACTION_KEPT_NOTICE.format(action=_MODE_REENTRY_ACTION)
        elif not self.has_unapplied_input():
            return None  # nothing pending; focus returning is the visible effect
        elif self.apply_permitted():
            return None  # Apply is lit and nothing blocks the user
        else:
            reason_text = rejection_reason_text(self.current_rejection_reason())
            notice = _MODE_REENTRY_KEPT_NOTICE.format(
                detail=f"（{reason_text or _PREVIEW_STILL_UPDATING_DETAIL}）"
            )
        key = (notice, editor.toPlainText(), preedit)
        if getattr(editor, "_reentry_notice_stamp", None) == key:
            return None
        editor._reentry_notice_stamp = key
        show = getattr(self._view, "_show_toast", None)
        if callable(show):
            show(notice, duration_ms=3000, tone="warning")
        return notice

    def _kept_notice(
        self,
        reason: TextEditFinalizeReason,
        *,
        emitted: bool,
        already_refused: bool,
        composing: bool = False,
    ) -> str | None:
        """The warning for an edit kept un-applied, or None (the Controller's
        own refusal toast already said it, or the action needs no word)."""
        if composing:
            if reason is TextEditFinalizeReason.SAVE_SHORTCUT:
                return _SAVE_COMPOSING_KEPT_NOTICE
            action = _COMPOSING_ACTION_WORDS.get(reason)
            if action is None:
                return _COMPOSING_KEPT_NOTICE
            return _COMPOSING_ACTION_KEPT_NOTICE.format(action=action)
        reason_text = rejection_reason_text(self.current_rejection_reason())
        detail = f"（{reason_text}）" if reason_text else ""
        if reason is TextEditFinalizeReason.CLOSE_DOCUMENT:
            return _CLOSE_KEPT_NOTICE.format(detail=detail)
        if reason is TextEditFinalizeReason.VIEW_RESCALE:
            return _RESCALE_KEPT_NOTICE.format(detail=detail)
        if reason is TextEditFinalizeReason.FULLSCREEN:
            return _FULLSCREEN_KEPT_NOTICE.format(detail=detail)
        if (
            reason in _POINTER_NOTICE_REASONS
            and not emitted
            and not already_refused
        ):
            # Not sent (the plan token gate): the Controller said nothing, so
            # name the refusal, or the pending preview, here.
            pointer_detail = f"（{reason_text or _PREVIEW_STILL_UPDATING_DETAIL}）"
            template = (
                _CLICK_AWAY_KEPT_NOTICE
                if reason is TextEditFinalizeReason.CLICK_AWAY
                else _FOCUS_OUTSIDE_KEPT_NOTICE
            )
            return template.format(detail=pointer_detail)
        if reason is TextEditFinalizeReason.SAVE_SHORTCUT and not emitted:
            if already_refused or self.current_rejection_reason():
                # Defect 3: a plan-mode refusal (no token will ever come) is
                # not "preview still updating" -- name the refusal.
                return _SAVE_ALREADY_REFUSED_KEPT_NOTICE.format(detail=detail)
            return _SAVE_NOT_APPLIED_KEPT_NOTICE
        return None

    @staticmethod
    def _focus_outside_notice_allowed() -> bool:
        """False when the focus left for a dialog or a menu, or the whole app
        is inactive (alt-tab): the user did not click anything here."""
        app = QApplication.instance()
        if app is None:
            return True
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return False
        return app.applicationState() == Qt.ApplicationActive

    def has_unapplied_input(self) -> bool:
        """Finalize policy completion: does the live editor hold input that
        is not in the PDF (a text, style, position or page change, or a new
        text box with text)?  Such input counts as unsaved when a document
        or the window closes."""
        view = self._view
        editor = self._live_editor()
        if editor is None:
            return False
        # MT-2: ``editing_rect`` follows the box only when its drag finishes, so a close asked
        # while the grip is still held (Ctrl+W, Alt+F4) would read the old spot and skip the
        # prompt.  Finish the drag where the box stands, like the release it stands in for.
        settle = getattr(view, "_settle_lost_grip_drag", None)
        if callable(settle):
            settle()
        if _editor_is_composing(editor):
            return True
        text = editor.toPlainText()
        if getattr(view, "editing_intent", "edit_existing") == "add_new":
            return bool(text.strip())
        return bool(
            _normalize_for_edit_compare(text)
            != _normalize_for_edit_compare(editor.property("original_text") or "")
            or _editing_style_changed(view)
            or _editing_position_changed(view)
            or _editing_page_changed(view)
        )

    def _teardown_editor(self) -> None:
        """Remove the inline editor and clear every per-session attribute.

        Deleted-proxy-proof: a synchronous ``show_page`` in single-page mode
        (``display_page`` -> ``scene.clear()``) may have deleted the proxy
        while the commit was being applied."""
        view = self._view
        # S14-EXTB-PREVIEW-WORKER: no Ext-B subset result may reach a closing editor.
        release_background = getattr(self._live_editor(), "release_background_work", None)
        if callable(release_background):
            release_background()
        proxy_to_remove = view.text_editor
        view.text_editor = None
        unbind_strip = getattr(view, "_unbind_live_text_strip", None)
        if callable(unbind_strip):
            unbind_strip(proxy_to_remove)
        # The I-beam the view set while hovering the box must not outlive it.
        reset_hover_cursor = getattr(view, "_reset_editor_hover_cursor", None)
        if callable(reset_hover_cursor):
            reset_hover_cursor()
        if proxy_to_remove is not None and _qt_object_alive(proxy_to_remove):
            try:
                if proxy_to_remove.scene():
                    view.scene.removeItem(proxy_to_remove)
            except RuntimeError:
                logger.debug("text editor proxy already deleted")
        self._clear_text_editor_mask_item()
        self._clear_text_editor_origin_mask_item()
        self._clear_text_editor_focus_border_item()
        # Restore dim outline for the block that was just edited
        try:
            active_key = getattr(view, '_active_outline_key', None)
            if active_key is not None:
                outline = view._block_outline_items.get(active_key)
                if outline is not None:
                    outline.setVisible(True)
                view._active_outline_key = None
        except Exception:
            pass
        view.editing_rect = None
        view._editing_original_rect = None
        if getattr(view, "_edit_font_size_connected", False):
            try:
                view.text_size.currentTextChanged.disconnect(view._on_edit_font_size_changed)
            except (TypeError, RuntimeError):
                logger.debug("text size disconnect skipped during finalize")
            view._edit_font_size_connected = False
        if getattr(view, "_edit_font_family_connected", False):
            try:
                view.text_font.currentIndexChanged.disconnect(view._on_edit_font_family_changed)
            except (TypeError, RuntimeError):
                logger.debug("text font disconnect skipped during finalize")
            view._edit_font_family_connected = False
        refresh_undo_redo = getattr(view, "_refresh_undo_redo_action_state", None)
        if callable(refresh_undo_redo):
            refresh_undo_redo()
        else:
            view._set_document_undo_redo_enabled(True)
        for name in (
            "editing_font_name",
            "_editing_initial_font_name",
            "_editing_initial_size",
            "_editing_current_pdf_size",
            "editing_color",
            "_editing_page_idx",
            "_editing_origin_page_idx",
            "_editing_origin_scene_rect",
            "_editing_open_proxy_pos",
            "_editing_origin_span_scene_rect",
            "_editing_rotation",
            "editing_target_span_id",
            "editing_source_ref",
            "editing_session_id",
            "editing_target_mode",
            "editing_intent",
        ):
            if hasattr(view, name):
                delattr(view, name)
        sync_panel = getattr(view, "_sync_text_property_panel_state", None)
        if callable(sync_panel):
            sync_panel()


def _editing_position_changed(view) -> bool:
    """The live editor was dragged away from its source rect (same formula
    as ``finalize_text_edit_impl``)."""
    original_rect = getattr(view, "_editing_original_rect", None)
    current_rect = getattr(view, "editing_rect", None)
    if original_rect is None or current_rect is None:
        return False
    tol = TextEditGeometryConstants.POSITION_CHANGE_TOLERANCE_PT
    return (
        abs(current_rect.x0 - original_rect.x0) > tol
        or abs(current_rect.y0 - original_rect.y0) > tol
    )


def _editing_page_changed(view) -> bool:
    edit_page = getattr(view, "_editing_page_idx", None)
    origin_page = getattr(view, "_editing_origin_page_idx", edit_page)
    return edit_page is not None and origin_page != edit_page


def _editing_style_changed(view) -> bool:
    """The user picked another font or size for the live editor."""
    current_font = getattr(view, "editing_font_name", "helv")
    initial_font = getattr(view, "_editing_initial_font_name", current_font)
    if _font_alias(view, current_font) != _font_alias(view, initial_font):
        return True
    current_size = getattr(view, "_editing_current_pdf_size", None)
    initial_size = getattr(view, "_editing_initial_size", current_size)
    try:
        return (
            current_size is not None
            and initial_size is not None
            and abs(float(current_size) - float(initial_size)) > 1e-3
        )
    except (TypeError, ValueError):
        return False


def _font_alias(view, font_name: object) -> str:
    """Comparison key for a session font name.

    The session baseline is the raw PyMuPDF name ("Helvetica") while the
    font combo writes UI aliases ("helv"); both sides of every
    changed-font comparison go through the view's alias mapping so the two
    alphabets never compare unequal for the same face.
    """
    name = str(font_name or "")
    mapper = getattr(view, "_qt_font_to_pdf", None)
    if callable(mapper):
        try:
            return str(mapper(name)).lower()
        except (AttributeError, TypeError, ValueError):
            pass
    return name.lower()


def build_style_overrides(
    *,
    current_font: str,
    initial_font: str,
    current_size: float,
    initial_size: float,
    font_key=None,
) -> StyleOverrides:
    """Overrides for the fields the user actually changed this session.

    Uses the same change detection as TextEditDelta: a case-insensitive
    font-name comparison (through ``font_key`` when given, so a raw source
    name and its UI alias compare equal) and a 1e-3 size tolerance.  Merely
    opening the editor (which maps the source font to a UI alias) never
    counts as a user override — with no change, style truth stays with the
    source spans (V2 plan Task 5).
    """
    key = font_key if callable(font_key) else (lambda name: str(name).lower())
    font_changed = key(current_font) != key(initial_font)
    size_changed = abs(float(current_size) - float(initial_size)) > 1e-3
    return StyleOverrides(
        font_family=str(current_font) if font_changed else None,
        font_size=float(current_size) if size_changed else None,
        color=None,  # no in-session color control yet
    )


def _map_legacy_reason(reason: TextEditReason | TextEditFinalizeReason) -> TextEditFinalizeReason:
    if isinstance(reason, TextEditFinalizeReason):
        return reason
    return TextEditFinalizeReason.CLICK_AWAY


def finalize_text_edit_impl(
    *,
    view,
    session,
    delta,
    reason: TextEditReason | TextEditFinalizeReason = TextEditReason.USER_COMMIT,
) -> TextEditFinalizeResult:
    """Module-level compatibility helper for finalize-outcome tests.

    Preserves the legacy function-level contract that a failed signal emit
    reports FAILED rather than COMMITTED.
    """
    mapped_reason = _map_legacy_reason(reason)
    try:
        view.sig_edit_text.emit(object())
    except Exception:
        return TextEditFinalizeResult(
            reason=mapped_reason,
            outcome=TextEditOutcome.FAILED,
            intent=getattr(session, "intent", "edit_existing"),
            edit_page=int(getattr(session, "edit_page", 0)),
            origin_page=int(getattr(session, "origin_page", 0)),
            delta=delta,
        )
    return TextEditFinalizeResult(
        reason=mapped_reason,
        outcome=TextEditOutcome.COMMITTED,
        intent=getattr(session, "intent", "edit_existing"),
        edit_page=int(getattr(session, "edit_page", 0)),
        origin_page=int(getattr(session, "origin_page", 0)),
        delta=delta,
    )
