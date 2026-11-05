from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication, QGraphicsRectItem

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view, leaked_gui_since, snapshot_visible_gui
from view.pdf_view import PDFView
from view.text_editing import _SEARCH_HIGHLIGHT_Z


def _pump_events(ms: int = 100) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _no_stray_gui_state():
    before = snapshot_visible_gui()
    yield
    leaked = leaked_gui_since(before)
    assert not leaked, "this test left GUI state behind for the next test: " + "; ".join(leaked)


@pytest.fixture
def mvc(monkeypatch, qapp):
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    try:
        yield model, view, controller
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "search-3p.pdf"
    with fitz.open() as doc:
        for number in range(3):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {number + 1}", fontsize=12, fontname="helv")
        doc[1].insert_text((300, 500), "needle", fontsize=14, fontname="helv")
        doc.save(path)
    return path


def _search_highlights(view) -> list[QGraphicsRectItem]:
    return [
        item
        for item in view.scene.items()
        if isinstance(item, QGraphicsRectItem) and item.zValue() == _SEARCH_HIGHLIGHT_Z
    ]


@pytest.mark.parametrize("zoom", [1.0, 2.36])
def test_continuous_search_jump_draws_box_on_the_hit(mvc, pdf_path, zoom):
    model, view, controller = mvc
    controller.open_pdf(str(pdf_path))
    view.show()
    _pump_events(300)
    assert view.continuous_pages
    controller.change_scale(0, zoom)
    _pump_events(300)

    hits = model.tools.search.search_text("needle")
    assert len(hits) == 1
    page_num, _context, rect = hits[0]
    assert page_num == 2

    controller.jump_to_result(page_num, rect)
    _pump_events(50)

    boxes = _search_highlights(view)
    assert len(boxes) == 1
    box = boxes[0].sceneBoundingRect()
    expected = view._doc_rect_to_scene_rect(page_num - 1, fitz.Rect(rect))
    assert abs(box.center().x() - expected.center().x()) < 3
    assert abs(box.center().y() - expected.center().y()) < 3
    assert abs(box.width() - expected.width()) < 4
    # The hit sits inside page 2's band, not further down the scroll.
    page_top = view._page_scene_y(1)
    assert page_top <= box.top() <= page_top + view.page_heights[1]


def test_single_page_search_jump_scales_box_once(mvc, pdf_path):
    model, view, controller = mvc
    controller.open_pdf(str(pdf_path))
    view.show()
    _pump_events(300)
    view.continuous_pages = False
    view.scale = 2.0
    page_num, _context, rect = model.tools.search.search_text("needle")[0]

    controller.jump_to_result(page_num, rect)
    _pump_events(50)

    boxes = _search_highlights(view)
    assert len(boxes) == 1
    box = boxes[0].sceneBoundingRect()
    hit = fitz.Rect(rect)
    assert abs(box.center().x() - (hit.x0 + hit.x1)) < 3
    assert abs(box.center().y() - (hit.y0 + hit.y1)) < 3
