"""Thumbnails fill the left sidebar and follow its width (docs/to_Update.md line 10).

Owner feedback 2026-11: the gap between a thumbnail and the sidebar edge was too
large and the thumbnail did not grow with the sidebar.  Root cause: portrait rows
were height-capped at 120 px in sidebars up to 260 px (an ~85 px wide page in a
~230 px box), the cell width was capped at 280 px, the cell was computed from the
list width rather than the viewport (a horizontal scrollbar appeared), and the
thumbnail raster was only 270 px wide.
"""
from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view, leaked_gui_since, snapshot_visible_gui
from view.pdf_view import PDFView

#: Allowed horizontal slack between the page image and the viewport edges.
EDGE_SLACK_PX = 24


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
def portrait_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "portrait-6p.pdf"
    with fitz.open() as doc:
        for number in range(6):
            page = doc.new_page(width=595, height=842)
            page.insert_text((72, 72), f"Page {number + 1}", fontsize=24, fontname="helv")
        doc.save(path)
    return path


def _open_wide(mvc, path: Path) -> PDFView:
    _, view, controller = mvc
    view.resize(1600, 900)
    view.show()
    controller.open_pdf(str(path))
    _pump_events(1500)
    return view


def _icon_width_at(view: PDFView, left_width: int) -> tuple[int, int]:
    view._apply_sidebar_sizes(left_width=left_width, right_width=280)
    _pump_events(300)
    tl = view.thumbnail_list
    item = tl.item(0)
    assert item is not None and not item.icon().isNull()
    return item.icon().actualSize(tl.iconSize()).width(), tl.viewport().width()


@pytest.mark.parametrize("left_width", [200, 260, 380])
def test_portrait_thumbnail_fills_the_sidebar_width(mvc, portrait_pdf, left_width):
    view = _open_wide(mvc, portrait_pdf)
    shown_w, viewport_w = _icon_width_at(view, left_width)
    assert shown_w >= viewport_w - EDGE_SLACK_PX, (shown_w, viewport_w)
    assert view.thumbnail_list.horizontalScrollBar().maximum() == 0


def test_cell_width_does_not_depend_on_the_scrollbar_appearing(mvc, tmp_path):
    """Cell height follows cell width; if the width shrank when the vertical bar
    appeared, crossing that height would toggle the bar back and forth."""
    path = tmp_path / "two.pdf"
    with fitz.open() as doc:
        for _ in range(2):
            doc.new_page(width=595, height=842)
        doc.save(path)
    view = _open_wide(mvc, path)
    view._apply_sidebar_sizes(left_width=260, right_width=280)
    widths = set()
    for height in (1400, 900, 600, 420):
        view.resize(1600, height)
        _pump_events(250)
        widths.add(view.thumbnail_list.gridSize().width())
    assert len(widths) == 1, widths


def test_thumbnail_grows_with_the_sidebar(mvc, portrait_pdf):
    view = _open_wide(mvc, portrait_pdf)
    narrow, _ = _icon_width_at(view, 220)
    wide, _ = _icon_width_at(view, 380)
    assert wide >= narrow + 120, (narrow, wide)
