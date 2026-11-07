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


def test_continuous_jump_uses_existing_scene_without_gui_raster(mvc, pdf_path, monkeypatch):
    model, view, controller = mvc
    controller.open_pdf(str(pdf_path))
    _pump_events(300)
    page_num, _context, rect = model.tools.search.search_text("needle")[0]
    scheduled = []
    monkeypatch.setattr(controller, "_schedule_visible_render",
                        lambda sid, immediate_page_idx=None: scheduled.append((sid, immediate_page_idx)))

    def forbidden(*args, **kwargs):
        pytest.fail("continuous search must schedule raster, not rasterize on GUI")

    monkeypatch.setattr(model, "get_page_pixmap", forbidden)
    before = tuple(view.page_items)
    controller.jump_to_result(page_num, rect)
    assert tuple(view.page_items) == before
    assert len(_search_highlights(view)) == 1
    sid = model.get_active_session_id()
    assert scheduled[0] == (sid, page_num - 1)
    # Centering the hit can emit an additional viewport update; the scheduler
    # coalesces that update rather than rasterizing synchronously.
    assert all(entry in {(sid, page_num - 1), (sid, None)} for entry in scheduled)
    assert controller._get_ui_state(model.get_active_session_id()).current_page == page_num - 1


def test_highlight_only_preserves_pixmap_and_clears_selection(mvc, pdf_path, monkeypatch):
    model, view, controller = mvc
    controller.open_pdf(str(pdf_path))
    _pump_events(300)
    cleared = []
    monkeypatch.setattr(view, "_clear_text_selection", lambda: cleared.append(True))
    page_num, _context, rect = model.tools.search.search_text("needle")[0]
    before = [item.pixmap().cacheKey() for item in view.page_items]
    view.show_search_highlight(page_num - 1, rect)
    assert cleared == [True]
    assert [item.pixmap().cacheKey() for item in view.page_items] == before
    assert len(_search_highlights(view)) == 1
    # Rebuilding the scene before timer expiry must leave no dangling callback.
    view.scene.clear()
    view.page_items.clear()
    _pump_events(1600)


@pytest.mark.parametrize("page_num", [0, -1, 4, True, "2", None])
def test_invalid_search_target_is_ignored(mvc, pdf_path, page_num, monkeypatch):
    model, view, controller = mvc
    controller.open_pdf(str(pdf_path))
    _pump_events(300)
    monkeypatch.setattr(model, "get_page_pixmap", lambda *a, **k: pytest.fail("invalid page raster"))
    controller.jump_to_result(page_num, fitz.Rect(1, 2, 3, 4))
    assert not _search_highlights(view)
