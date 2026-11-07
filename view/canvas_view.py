from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QGraphicsView


class CanvasView(QGraphicsView):
    """Notify controllers only after the scene's paint call has returned."""

    painted = Signal()
    pixel_ratio_changed = Signal()

    def event(self, event):
        result = super().event(event)
        if event.type() == getattr(QEvent.Type, 'DevicePixelRatioChange', None):
            self.pixel_ratio_changed.emit()
        return result

    def paintEvent(self, event):
        super().paintEvent(event)
        self.painted.emit()
