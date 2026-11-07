from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem
from PySide6.QtTest import QTest

from controller.pdf_controller import PDFController
from view.canvas_view import CanvasView


def test_canvas_notification_follows_actual_scene_paint(qapp):
    order = []

    class Scene(QGraphicsScene):
        def drawForeground(self, painter, rect):
            super().drawForeground(painter, rect)
            order.append('paint')

    scene = Scene()
    view = CanvasView()
    view.setScene(scene)
    view.painted.connect(lambda: order.append('notified'))
    try:
        view.show()
        QTest.qWait(30)
        assert 'notified' in order
        assert order.index('paint') < order.index('notified')
    finally:
        view.close()


def test_only_present_high_quality_pixels_authorize_expansion(qapp, tmp_path):
    import fitz
    from model.pdf_model import PDFModel

    path = tmp_path / 'presentation.pdf'
    with fitz.open() as document:
        document.new_page()
        document.save(path)
    model = PDFModel()
    model.open_pdf(str(path))
    # Keep a real document; only the presentation/backend endpoints are spies.
    calls = []
    image = QImage(4, 4, QImage.Format_RGB888)
    item = QGraphicsPixmapItem(QPixmap.fromImage(image))
    quality = {0: 'low'}
    controller = SimpleNamespace(
        model=model, _render_owner='owner',
        _render_client=SimpleNamespace(foreground_presented=lambda *args: calls.append(args)),
        view=SimpleNamespace(page_items=[item]),
        _visible_render_targets=lambda: ([0], [0]),
        _page_quality_map=lambda *args: quality,
        _color_profile_for_session=lambda session: 'srgb',
        _render_revision=lambda session: 3,
    )
    try:
        PDFController._on_canvas_painted(controller)
        assert calls == []
        quality[0] = 'high'
        PDFController._on_canvas_painted(controller)
        assert calls == [('owner', f'{model.get_active_session_id()}@3')]
        item.setPixmap(QPixmap())
        PDFController._on_canvas_painted(controller)
        assert len(calls) == 1
    finally:
        model.close()
