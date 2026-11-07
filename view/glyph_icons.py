"""Vector replacements for symbol glyphs the UI font does not contain.

Microsoft JhengHei UI has no curved arrows or Braille dots. The first startup text
measurement that contains one makes Qt search every system font (about 0.6 s of GUI
freeze on the reference machine), so the ribbon undo/redo arrows and the editor
move grip are drawn instead of typed. Colours come from the active theme tokens so a
theme switch needs no icon rebuild; the disabled state uses the subtle token.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from utils.theme_ids import DEFAULT_THEME_ID
from view.theme import THEME_REGISTRY

_theme_id = DEFAULT_THEME_ID


def set_glyph_theme(theme_id: str) -> None:
    global _theme_id
    if theme_id in THEME_REGISTRY:
        _theme_id = theme_id


def _token(name: str) -> QColor:
    return QColor(THEME_REGISTRY[_theme_id].tokens[name])


class _CurvedArrowEngine(QIconEngine):
    """An open circle with an arrowhead: anticlockwise (undo) or its mirror (redo)."""

    def __init__(self, clockwise: bool) -> None:
        super().__init__()
        self._clockwise = clockwise

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        color = _token("fg_subtle" if mode == QIcon.Mode.Disabled else "fg")
        side = float(min(rect.width(), rect.height()))
        box = QRectF(rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._clockwise:
            painter.translate(box.center())
            painter.scale(-1.0, 1.0)
            painter.translate(-box.center())
        radius = side * 0.30
        center = box.center()
        circle = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        start_deg, span_deg = 125.0, 290.0
        path = QPainterPath()
        path.arcMoveTo(circle, start_deg)
        path.arcTo(circle, start_deg, span_deg)
        pen = painter.pen()
        pen.setColor(color)
        pen.setWidthF(max(1.0, side * 0.10))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        end = math.radians(start_deg + span_deg)
        tip_base = QPointF(center.x() + radius * math.cos(end), center.y() - radius * math.sin(end))
        tangent = QPointF(-math.sin(end), -math.cos(end))
        normal = QPointF(-tangent.y(), tangent.x())
        head = side * 0.22
        tip = QPointF(tip_base.x() + tangent.x() * head * 0.9, tip_base.y() + tangent.y() * head * 0.9)
        left = QPointF(tip_base.x() + normal.x() * head * 0.65, tip_base.y() + normal.y() * head * 0.65)
        right = QPointF(tip_base.x() - normal.x() * head * 0.65, tip_base.y() - normal.y() * head * 0.65)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([tip, left, right]))
        painter.restore()

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(QPoint(0, 0), size), mode, state)
        painter.end()
        return pixmap

    def clone(self) -> _CurvedArrowEngine:
        return _CurvedArrowEngine(self._clockwise)


def curved_arrow_icon(clockwise: bool) -> QIcon:
    return QIcon(_CurvedArrowEngine(clockwise))


class GripDots(QWidget):
    """Two columns of three dots, in the widget's text colour."""

    _DIAMETER = 3.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self) -> QSize:
        return QSize(10, 14)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.WindowText))
        radius = self._DIAMETER / 2
        top = (self.height() - 14) / 2
        left = (self.width() - 10) / 2
        for column in (2.5, 7.5):
            for row in (2.5, 7.0, 11.5):
                painter.drawEllipse(QPointF(left + column, top + row), radius, radius)
        painter.end()
