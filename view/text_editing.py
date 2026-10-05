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
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTextCursor,
    QTextDocument,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import QTextEdit
from shiboken6 import isValid as _qt_object_alive

from model.edit_commands import EditTextResult  # re-exported for view/controller (pure DTO enum, no mutation surface)
from model.edit_requests import EditTextRequest, MoveTextRequest, StyleOverrides  # re-exported for view/controller
from utils.render_limits import safe_render_scale as _safe_render_scale
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
_MASK_TINT_LADDER: tuple[float, ...] = (0.04, 0.08, 0.12, 0.16, _MASK_MAX_TINT_STRENGTH)

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
_NOT_APPLIED_KEPT_NOTICE = "文字編輯尚未套用：預覽仍在更新，編輯框已保留（文件未變更）"
# Defect 6: the input was already refused and is not re-sent -- say so.
_ALREADY_REFUSED_KEPT_NOTICE = (
    "文字編輯尚未套用：這段輸入已被拒絕{detail}，請修改內容或取消；編輯框已保留（文件未變更）"
)
_CLOSE_KEPT_NOTICE = "文字編輯尚未套用{detail}，已取消關閉並保留編輯框（文件未變更）"
_RESCALE_KEPT_NOTICE = (
    "文字編輯尚未套用{detail}，已取消縮放並保留編輯框；請先套用或取消編輯（文件未變更）"
)


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


class InlineTextEditor(QTextEdit):
    focus_out_requested = Signal()

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
            def build_preview_html(*, text, font_size, color, font_name, line_height):
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
    ) -> QImage:
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
        )
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
            temp_page.insert_htmlbox(target_rect, html, css=css, scale_low=1)

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

        self._cache_key = key
        self._cache_image = image
        return image


class PreviewBackedInlineTextEditor(InlineTextEditor):
    # UI step 5: fired whenever current_plan_token() may have changed (a new
    # generation, an interim CSS frame, an accepted plan raster) so the View
    # can re-gate its Apply button.  Carries nothing; listeners re-query.
    plan_token_state_changed = Signal()
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

    def keyPressEvent(self, event) -> None:
        if not self._cursor_revealed:
            self.setCursorWidth(1)
            self._cursor_revealed = True
        super().keyPressEvent(event)

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

    def invalidate_plan_preview(self, *, regenerate: bool = True) -> None:
        """Supersede every plan request issued so far (UI step 6).

        For inputs the editor cannot see itself -- a drag moves the proxy and
        the View's ``editing_rect``.  ``regenerate=False`` only bumps the
        generation (cheap; per mouse-move); ``True`` also re-requests the
        preview so the editor is not left without a token.
        """
        self._plan_generation += 1
        self._plan_preview_active = False
        self.plan_token_state_changed.emit()
        if regenerate:
            self._debounce.stop()
            self._regenerate_preview()

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
            )
            self._mutated_preview_is_valid = (
                not self._text_is_nonempty
                or self._mutated_preview_has_visible_ink(self._preview_image)
            )
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

    def paintEvent(self, event) -> None:
        # CRITICAL — visual fidelity contract. While text == initial (incl.
        # after a type-then-delete round-trip) paint the frozen MuPDF capture;
        # CSS preview never pixel-matches MuPDF hinting, so using it for
        # unchanged text introduces a permanent delta. _text_matches_initial is
        # cached (see _schedule_preview); never recompute it per paint.
        # Gates: test_click_to_edit_qtest_integration,
        #        test_click_to_edit_then_insert_then_delete_stays_stable.
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
            viewport = self.viewport()
            old_auto_fill = viewport.autoFillBackground()
            viewport.setAutoFillBackground(False)
            super().paintEvent(event)
            viewport.setAutoFillBackground(old_auto_fill)
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
            viewport = self.viewport()
            old_auto_fill = viewport.autoFillBackground()
            viewport.setAutoFillBackground(False)
            super().paintEvent(event)
            viewport.setAutoFillBackground(old_auto_fill)
            return
        elif self._frozen_first_frame_image is not None:
            painter.drawImage(0, 0, self._frozen_first_frame_image)
        else:
            painter.end()
            super().paintEvent(event)
            return
        painter.end()

    # ---- plan-mode frame (UI step 11) ----------------------------------

    PLAN_PENDING_BADGE_TEXT = "預覽更新中"

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
        return (
            self._plan_mode
            and not self._text_matches_initial
            and not self._plan_frame_is_verified()
            and self.plan_rejection_reason() is None
        )

    def _plan_frame_is_verified(self) -> bool:
        return bool(
            self._plan_preview_active
            and self._applied_plan_generation == self._plan_generation
        )

    def plan_preview_badge_text(self) -> str:
        return self.PLAN_PENDING_BADGE_TEXT

    def plan_preview_chip_text(self) -> str:
        """The typed text, shown in UI chrome (not in the PDF font)."""
        return self.toPlainText()

    def _paint_plan_mode_frame(self) -> None:
        """Last verified frame (else the frozen original) plus, while the
        preview is pending, the badge and a typed-text chip.  Never the CSS
        frame and never the editor's native glyphs."""
        painter = QPainter(self.viewport())
        base = self._preview_image
        if base is None:
            base = self._frozen_first_frame_image
        if base is not None:
            painter.drawImage(0, 0, base)
        if self.plan_preview_pending():
            self._paint_plan_overlay(painter)
        painter.end()

    def _paint_plan_overlay(self, painter: QPainter) -> None:
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
        painter.setBrush(QColor(40, 40, 40, 215))
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, int(Qt.AlignCenter), badge)

        chip = " ".join(self.plan_preview_chip_text().split()) or "（空白）"
        chip = metrics.elidedText(chip, Qt.ElideRight, max(10, rect.width() - 4 * pad))
        chip_w = min(rect.width(), metrics.horizontalAdvance(chip) + 2 * pad)
        chip_rect = QRect(rect.left(), rect.bottom() - height + 1, chip_w, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRoundedRect(chip_rect, 3, 3)
        painter.setPen(QColor(30, 30, 30))
        painter.drawText(chip_rect, int(Qt.AlignCenter), chip)

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
        """The applied plan's token, only while it matches the live text."""
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

    def _resolve_mask_sampling_context(self, scene_rect: QRectF) -> tuple[QImage, QRect] | None:
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
        return image, image_rect

    def _build_background_matched_mask(
        self,
        scene_rect: QRectF,
        text_rgb: tuple[int, int, int],
    ) -> tuple[QBrush, QColor, dict[str, object]]:
        text_rgb_f: tuple[float, float, float] = tuple(float(v) for v in text_rgb)  # type: ignore[assignment]

        sampled = self._resolve_mask_sampling_context(scene_rect)
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

        mask_mean_rgb = _qimage_mean_rgb(patch, patch.rect()) or ring_rgb
        contrast_ratio = _contrast_ratio_rgb(text_rgb_f, mask_mean_rgb)
        tint_strength = 0.0
        if contrast_ratio < _MASK_MIN_CONTRAST_RATIO:
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
        page_items = getattr(self._view, "page_items", None)
        pixmap_key: int | None = None
        if isinstance(page_items, list) and 0 <= page_idx < len(page_items):
            page_item = page_items[page_idx]
            if page_item is not None and hasattr(page_item, "pixmap"):
                pixmap = page_item.pixmap()
                if pixmap is not None and not pixmap.isNull():
                    cache_key_fn = getattr(pixmap, "cacheKey", None)
                    pixmap_key = int(cache_key_fn()) if callable(cache_key_fn) else id(pixmap)
        aligned = scene_rect.toAlignedRect()
        signature = (
            pixmap_key,
            page_idx,
            (aligned.x(), aligned.y(), aligned.width(), aligned.height()),
            text_rgb,
        )
        if signature == self._last_mask_signature and getattr(self._view, "_text_editor_mask_item", None) is not None:
            self._sync_text_editor_focus_border_item(scene_rect)
            return

        mask_brush, mask_color, mask_debug = self._build_background_matched_mask(scene_rect, text_rgb)
        self._sync_text_editor_mask_item(scene_rect, mask_brush)
        self._sync_text_editor_focus_border_item(scene_rect)
        editor.setStyleSheet(self._view._build_text_editor_stylesheet(text_rgb, mask_color))
        editor.setProperty("mask_rgb", (mask_color.red(), mask_color.green(), mask_color.blue()))
        editor.setProperty("mask_debug_metrics", mask_debug)
        self._last_mask_signature = signature

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
        view.text_editor.setPos(round(pos_x), round(pos_y))
        if hasattr(view.text_editor, "setTransformOriginPoint"):
            view.text_editor.setTransformOriginPoint(0.0, 0.0)
        if hasattr(view.text_editor, "setRotation"):
            view.text_editor.setRotation(float(normalized_rotation))
        if initial_frame is not None:
            editor.freeze_first_frame(initial_frame)
        self.refresh_text_editor_mask_color()
        view._editor_shortcut_forwarder = _EditorShortcutForwarder(view)
        if isinstance(view._editor_shortcut_forwarder, QObject):
            editor.installEventFilter(view._editor_shortcut_forwarder)
        editor.focus_out_requested.connect(view._schedule_finalize_on_focus_change)
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
        if normalized_rotation == 90:
            editor_width_px = max(int(round(scaled_rect.height)), 1)
            editor_height_px = max(int(round(scaled_rect.width)), 1)
            pos_x = float(x0 + scaled_rect.x1)
            pos_y = float(y0 + scaled_rect.y0)
        elif normalized_rotation == 270:
            editor_width_px = max(int(round(scaled_rect.height)), 1)
            editor_height_px = max(int(round(scaled_rect.width)), 1)
            pos_x = float(x0 + scaled_rect.x0)
            pos_y = float(y0 + scaled_rect.y1)

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
        QTimer.singleShot(
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
        QTimer.singleShot(
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
                reason, emitted=emitted, already_refused=already_refused
            )
            if notice:
                show = getattr(view, "_show_toast", None)
                if callable(show):
                    show(notice, duration_ms=3000, tone="warning")
            self._sync_view_apply_enabled()
            if reason is TextEditFinalizeReason.APPLY and editor.isVisible():
                # S10 concern, fixed at the root: the re-arm above disabled the
                # FOCUSED Apply (or rebuild) button; give focus back to the
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
                QTimer.singleShot(
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

    def _kept_notice(
        self, reason: TextEditFinalizeReason, *, emitted: bool, already_refused: bool
    ) -> str | None:
        """The warning for an edit kept un-applied, or None (the Controller's
        own refusal toast already said it, or the action needs no word)."""
        detail = rejection_reason_text(self.current_rejection_reason())
        detail = f"（{detail}）" if detail else ""
        if reason is TextEditFinalizeReason.CLOSE_DOCUMENT:
            return _CLOSE_KEPT_NOTICE.format(detail=detail)
        if reason is TextEditFinalizeReason.VIEW_RESCALE:
            return _RESCALE_KEPT_NOTICE.format(detail=detail)
        if reason is TextEditFinalizeReason.SAVE_SHORTCUT and not emitted:
            if already_refused:
                return _ALREADY_REFUSED_KEPT_NOTICE.format(detail=detail)
            return _NOT_APPLIED_KEPT_NOTICE
        return None

    def has_unapplied_input(self) -> bool:
        """Finalize policy completion: does the live editor hold input that
        is not in the PDF (a text, style, position or page change, or a new
        text box with text)?  Such input counts as unsaved when a document
        or the window closes."""
        view = self._view
        editor = self._live_editor()
        if editor is None:
            return False
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
        proxy_to_remove = view.text_editor
        view.text_editor = None
        if proxy_to_remove is not None and _qt_object_alive(proxy_to_remove):
            try:
                if proxy_to_remove.scene():
                    view.scene.removeItem(proxy_to_remove)
            except RuntimeError:
                logger.debug("text editor proxy already deleted")
        self._clear_text_editor_mask_item()
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
