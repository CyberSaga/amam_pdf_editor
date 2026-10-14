"""Live text strip: a legible mirror of the hidden inline editor (round 6, P1).

With the shipped plan preview the inline ``QTextEdit`` never paints its own glyphs
(the box shows the PDF-faithful raster), so the owner saw no caret, no selection and
only a tiny elided chip of what was typed.  The strip is UI chrome OUTSIDE the box, the
first row of the inline action bar: it lays the editor's plain text out in a screen font
(>= 14 px) and draws the caret, the selection band and the IME preedit on it.  Clicking
or dragging in the strip moves the editor's caret / selection, so the caret can be placed
exactly even though the hidden layout's advances differ from the PDF's.

Contract (pinned by ``test_text_commit_live_text_strip.py``):

* ``Qt.NoFocus``; the editor keeps the keyboard focus.  A press never finalizes.
* it mirrors the editor synchronously (no debounce) through the editor's signals;
* ``text()`` is the editor's plain text unchanged; ``"\\n"`` is laid out as U+2028 so
  every position stays 1:1 with the editor's;
* while an input method composes, the preedit is part of the layout (positions after the
  cursor are shifted by its length) and underlined; a press first COMMITS it (native
  text-field behaviour), then places the caret;
* the strip caret is visible whenever the editor has the keyboard focus, independent of
  the box's own (hidden-until-interaction) caret;
* it is shown only for a plan-preview editor: legacy editors paint native text in the box.

Bound / unbound by the view at the two editor-lifecycle chokepoints
(``_install_editor_in_scene`` / ``_teardown_editor`` in ``view/text_editing.py``).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

logger = logging.getLogger(__name__)

STRIP_MIN_PX = 14
STRIP_MAX_PX = 24
STRIP_MIN_WIDTH = 240
STRIP_MAX_LINES = 6
_PAD_X = 6
_PAD_Y = 3
_CARET_WIDTH = 2
_LINE_SEPARATOR = "\u2028"
# The editor signals the strip mirrors (each triggers a synchronous ``refresh``).
_MIRRORED_SIGNALS = (
    "textChanged",
    "cursorPositionChanged",
    "selectionChanged",
    "composition_changed",
    "caret_revealed_changed",
)


def commit_ime_composition(editor) -> bool:
    """Commit a live IME composition before a press moves the caret.

    ``QInputMethod.commit()`` is a no-op in several platform input contexts (Windows:
    ``QPlatformInputContext::commit`` is empty; ``QWindowsInputContext::reset`` is what
    sends the preedit as a commit string), so fall back to ``reset()`` when the editor
    is still composing.  Returns True when a composition was live on entry.
    """
    is_composing = getattr(editor, "is_composing", None)
    if not (callable(is_composing) and is_composing()):
        return False
    method = QGuiApplication.inputMethod()
    method.commit()
    if is_composing():
        method.reset()
    return True


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


class LiveTextStrip(QWidget):
    """Read-only mirror of a bound editor with caret, selection and preedit."""

    #: The strip's size hint (width or height) changed: the bar must be re-sized/placed.
    geometry_changed = Signal()
    #: Anything that moves the strip caret changed: the IME anchor must be refreshed.
    anchor_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("textLiveStrip")
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_NoMousePropagation, True)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.IBeamCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._editor = None
        self._available_width: int | None = None
        self._layout: QTextLayout | None = None
        self._full_text = ""
        self._text = ""
        self._position = 0
        self._anchor = 0
        self._preedit = ""
        self._preedit_at = 0
        self._preedit_cursor = 0
        self._scroll_y = 0.0
        self._content_height = 0.0
        self._line_height = 16
        self._pixel_size = STRIP_MIN_PX
        self._width_hint = STRIP_MIN_WIDTH
        self._height_hint = self._line_height + 2 * _PAD_Y
        self._selecting = False
        self.setFixedHeight(self._height_hint)
        self.setHidden(True)

    # ------------------------------------------------------------ binding

    def bind(self, editor) -> None:
        """Mirror ``editor``; any previously bound editor is released first."""
        self.unbind()
        self._editor = editor
        for name in _MIRRORED_SIGNALS:
            signal = getattr(editor, name, None)
            if signal is not None:
                signal.connect(self.refresh)
        editor.installEventFilter(self)
        self.refresh()

    def unbind(self) -> None:
        editor = self._editor
        self._editor = None
        self._selecting = False
        if editor is not None:
            for name in _MIRRORED_SIGNALS:
                try:
                    getattr(editor, name).disconnect(self.refresh)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            try:
                editor.removeEventFilter(self)
            except RuntimeError:
                pass
        self._layout = None
        self._full_text = self._text = ""
        self._position = self._anchor = 0
        self._preedit = ""
        self._preedit_at = self._preedit_cursor = 0
        self._scroll_y = 0.0
        self.setHidden(True)

    def is_bound(self) -> bool:
        return self._editor is not None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if obj is self._editor and event.type() in (
            QEvent.FocusIn,
            QEvent.FocusOut,
            QEvent.FontChange,
        ):
            if event.type() == QEvent.FontChange:
                self.refresh()
            else:
                self.update()
        return False

    def set_available_width(self, width: int | None) -> None:
        """Upper bound for the strip width (the view passes the viewport width minus the
        bar chrome); a change re-lays the strip out."""
        if width is not None:
            width = max(120, int(width))
        if width == self._available_width:
            return
        self._available_width = width
        if self._editor is not None:
            self.refresh()

    # ------------------------------------------------------------ mirror

    def refresh(self, *_args) -> None:
        """Re-read the editor and relayout (synchronous; connected to its signals)."""
        editor = self._editor
        if editor is None:
            return
        try:
            text = editor.toPlainText()
            cursor = editor.textCursor()
            position, anchor = int(cursor.position()), int(cursor.anchor())
            font = editor.font()
            plan = bool(editor.plan_preview_mode()) if hasattr(editor, "plan_preview_mode") else False
            preedit = str(editor.preedit_text()) if hasattr(editor, "preedit_text") else ""
            preedit_cursor = (
                int(editor.preedit_cursor()) if hasattr(editor, "preedit_cursor") else len(preedit)
            )
            editor_width = int(editor.width())
        except RuntimeError:
            # The editor's C++ object is gone (scene cleared under us).
            self.unbind()
            return
        self.setHidden(not plan)
        if not plan:
            self._layout = None
            return
        old_hint = (self._width_hint, self._height_hint)
        self._text = text
        self._position = _clamp(position, 0, len(text))
        self._anchor = _clamp(anchor, 0, len(text))
        self._preedit = preedit
        self._preedit_at = self._position
        self._preedit_cursor = _clamp(preedit_cursor, 0, len(preedit))
        self._relayout(font, editor_width)
        self.update()
        if (self._width_hint, self._height_hint) != old_hint:
            self.updateGeometry()
            self.geometry_changed.emit()
        self.anchor_changed.emit()

    @staticmethod
    def _editor_pixel_height(font: QFont) -> float:
        if font.pixelSize() > 0:
            return float(font.pixelSize())
        return float(QFontMetricsF(font).height())

    def _relayout(self, editor_font: QFont, editor_width: int) -> None:
        pixel = _clamp(
            int(round(self._editor_pixel_height(editor_font))), STRIP_MIN_PX, STRIP_MAX_PX
        )
        self._pixel_size = pixel
        font = QFont(editor_font.family())
        font.setPixelSize(pixel)
        width = max(editor_width, STRIP_MIN_WIDTH)
        if self._available_width is not None:
            width = min(width, self._available_width)
        self._width_hint = int(width)

        at = self._preedit_at
        self._full_text = self._text[:at] + self._preedit + self._text[at:]
        layout = QTextLayout(self._text.replace("\n", _LINE_SEPARATOR), font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        if self._preedit:
            layout.setPreeditArea(at, self._preedit)
            underline = QTextCharFormat()
            underline.setUnderlineStyle(QTextCharFormat.SingleUnderline)
            fmt_range = QTextLayout.FormatRange()
            fmt_range.start, fmt_range.length = self.preedit_underline_ranges()[0]
            fmt_range.format = underline
            layout.setFormats([fmt_range])
        line_width = max(40, self._width_hint - 2 * _PAD_X)
        y = 0.0
        first_height = 0.0
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(line_width)
            line.setPosition(QPointF(0.0, y))
            if first_height == 0.0:
                first_height = float(line.height())
            y += line.height()
        layout.endLayout()
        self._layout = layout
        self._content_height = y
        self._line_height = max(1, int(round(first_height or QFontMetricsF(font).height())))

        visible = min(self._content_height, STRIP_MAX_LINES * self._line_height)
        visible = max(float(self._line_height), visible)
        self._height_hint = int(round(visible)) + 2 * _PAD_Y
        self._scroll_to_caret(visible)
        if self.height() != self._height_hint:
            self.setFixedHeight(self._height_hint)

    def _scroll_to_caret(self, visible_height: float) -> None:
        layout = self._layout
        if layout is None or self._content_height <= visible_height:
            self._scroll_y = 0.0
            return
        line = layout.lineForTextPosition(self._caret_layout_position())
        top = float(line.y()) if line.isValid() else 0.0
        bottom = top + (float(line.height()) if line.isValid() else float(self._line_height))
        scroll = self._scroll_y
        if top < scroll:
            scroll = top
        elif bottom > scroll + visible_height:
            scroll = bottom - visible_height
        self._scroll_y = max(0.0, min(scroll, self._content_height - visible_height))

    # ------------------------------------------------------------ accessors

    def text(self) -> str:
        return self._text

    def font_pixel_size(self) -> int:
        return self._pixel_size

    def line_count(self) -> int:
        return int(self._layout.lineCount()) if self._layout is not None else 1

    def line_height(self) -> int:
        return self._line_height

    def preedit_area(self) -> tuple[int, str]:
        return self._preedit_at, self._preedit

    def preedit_underline_ranges(self) -> list[tuple[int, int]]:
        """``[(start, length)]`` of the underlined preedit in layout positions; empty
        when nothing is composed."""
        if not self._preedit:
            return []
        return [(self._preedit_at, len(self._preedit))]

    def caret_visible(self) -> bool:
        """The strip caret is shown whenever the bound editor has the focus."""
        editor = self._editor
        if editor is None or self.isHidden():
            return False
        try:
            return bool(editor.hasFocus())
        except RuntimeError:
            return False

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self._width_hint, self._height_hint)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(min(self._width_hint, 120), self._height_hint)

    # ------------------------------------------------------------ position mapping

    def _to_layout(self, position: int) -> int:
        """Editor position -> layout position (the preedit sits at the cursor)."""
        position = _clamp(int(position), 0, len(self._text))
        if self._preedit and position > self._preedit_at:
            return position + len(self._preedit)
        return position

    def _from_layout(self, layout_position: int) -> int:
        """Layout position -> editor position; the preedit itself collapses to its start."""
        plen = len(self._preedit)
        at = self._preedit_at
        if plen and layout_position > at:
            if layout_position >= at + plen:
                layout_position -= plen
            else:
                layout_position = at
        return _clamp(layout_position, 0, len(self._text))

    def _caret_layout_position(self) -> int:
        if self._preedit:
            return self._preedit_at + self._preedit_cursor
        return self._position

    def _x_at(self, layout_position: int) -> tuple[float, float, float]:
        """``(x, y, height)`` of a layout position in layout coordinates."""
        layout = self._layout
        if layout is None:
            return 0.0, 0.0, float(self._line_height)
        line = layout.lineForTextPosition(layout_position)
        if not line.isValid():
            return 0.0, 0.0, float(self._line_height)
        result = line.cursorToX(layout_position)
        x = float(result[0] if isinstance(result, tuple) else result)
        return x, float(line.y()), float(line.height())

    def _rect_at(self, layout_position: int) -> QRect:
        x, y, height = self._x_at(layout_position)
        return QRect(
            int(round(x)) + _PAD_X,
            int(round(y - self._scroll_y)) + _PAD_Y,
            _CARET_WIDTH,
            int(round(height)),
        )

    def cursor_rect_for(self, position: int) -> QRect:
        """The caret slot of editor ``position`` in strip coordinates (the preedit, if
        any, pushes later positions right).  Positions clamp to the text."""
        return self._rect_at(self._to_layout(position))

    def caret_rect(self) -> QRect:
        """Where the caret is drawn: the preedit cursor while composing."""
        return self._rect_at(self._caret_layout_position())

    def position_at(self, point: QPoint) -> int:
        """Editor position under ``point`` (strip coordinates)."""
        layout = self._layout
        if layout is None or layout.lineCount() == 0:
            return 0
        ly = point.y() - _PAD_Y + self._scroll_y
        chosen = layout.lineAt(layout.lineCount() - 1)
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            if ly < line.y() + line.height():
                chosen = line
                break
        layout_position = int(chosen.xToCursor(float(point.x() - _PAD_X)))
        end = int(chosen.textStart() + chosen.textLength())
        # A hard line break ends the line; the position AFTER it belongs to the next line.
        if (
            chosen.lineNumber() < layout.lineCount() - 1
            and 0 < end <= len(self._full_text)
            and self._full_text[end - 1] == "\n"
        ):
            layout_position = min(layout_position, end - 1)
        return self._from_layout(layout_position)

    # ------------------------------------------------------------ paint

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        palette = self.palette()
        painter = QPainter(self)
        painter.fillRect(self.rect(), palette.color(QPalette.Base))
        painter.setPen(palette.color(QPalette.Mid))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        layout = self._layout
        if layout is None:
            painter.end()
            return
        painter.setClipRect(self.rect().adjusted(1, 1, -1, -1))
        painter.setPen(palette.color(QPalette.Text))
        selections = []
        start, end = sorted((self._position, self._anchor))
        if start != end:
            fmt = QTextCharFormat()
            fmt.setBackground(palette.brush(QPalette.Highlight))
            fmt.setForeground(palette.brush(QPalette.HighlightedText))
            selection = QTextLayout.FormatRange()
            plen = len(self._preedit)
            at = self._preedit_at
            # The selection never swallows the preedit: starts at/after it shift, ends
            # strictly after it shift.
            selection.start = start + plen if (plen and start >= at) else start
            shifted_end = end + plen if (plen and end > at) else end
            selection.length = max(0, shifted_end - selection.start)
            selection.format = fmt
            selections.append(selection)
        layout.draw(painter, QPointF(float(_PAD_X), float(_PAD_Y) - self._scroll_y), selections)
        if self.caret_visible():
            painter.fillRect(self.caret_rect(), palette.color(QPalette.Text))
        painter.end()

    # ------------------------------------------------------------ mouse

    def _commit_composition(self) -> None:
        """A press that moves the caret first commits a live composition (native
        behaviour); ``setTextCursor`` under a live preedit would leave the IME composing
        at a stale position."""
        if commit_ime_composition(self._editor):
            self.refresh()

    def _move_editor_caret(self, point: QPoint, *, extend: bool) -> None:
        editor = self._editor
        if editor is None:
            return
        cursor = editor.textCursor()
        cursor.setPosition(
            self.position_at(point),
            QTextCursor.KeepAnchor if extend else QTextCursor.MoveAnchor,
        )
        editor.setTextCursor(cursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        event.accept()
        editor = self._editor
        if editor is None or event.button() != Qt.LeftButton:
            return
        self._commit_composition()
        self._move_editor_caret(
            event.position().toPoint(), extend=bool(event.modifiers() & Qt.ShiftModifier)
        )
        try:
            editor.setFocus(Qt.MouseFocusReason)
            reveal = getattr(editor, "reveal_caret", None)
            if callable(reveal):
                reveal()
        except RuntimeError:
            self.unbind()
            return
        self._selecting = True

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        event.accept()
        if self._selecting and self._editor is not None and event.buttons() & Qt.LeftButton:
            self._move_editor_caret(event.position().toPoint(), extend=True)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        event.accept()
        if event.button() == Qt.LeftButton:
            self._selecting = False

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt override
        # A double click is a second press: caret placement only, no word selection.
        self.mousePressEvent(event)


__all__ = [
    "STRIP_MAX_LINES",
    "STRIP_MAX_PX",
    "STRIP_MIN_PX",
    "STRIP_MIN_WIDTH",
    "LiveTextStrip",
]
