"""A thumbnail pass stays linear in the page count (perf pass 2026-11-04).

The thumbnail workers hand the view one page per batch.  ``update_thumbnail_batch``
re-ran the whole-list layout pass (size hint + alignment of EVERY row) after
each batch, so one pass over an n-page document cost O(n^2) on the GUI thread.
Only the first rows feed the icon aspect ratio the layout depends on.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap

from test_scripts.qt_teardown import dispose_pdf_view
from view.pdf_view import PDFView

#: 4x the rows may take at most this many times as long (linear ~4, quadratic ~16).
LINEAR_GROWTH_LIMIT = 8.0
#: Below this the full-size pass is too short for a ratio to mean anything; the
#: quadratic pass over this many rows takes well over a second.
LINEAR_GROWTH_FLOOR_S = 0.05
FULL_ROWS = 800


@pytest.fixture
def view(qapp):
    pdf_view = PDFView()
    yield pdf_view
    dispose_pdf_view(pdf_view)


def _landscape_pixmap() -> QPixmap:
    pix = QPixmap(120, 80)
    pix.fill(QColor("white"))
    return pix


def _timed_pass(view: PDFView, rows: int, pix: QPixmap) -> float:
    view.set_thumbnail_placeholders(rows)
    started = time.perf_counter()
    for row in range(rows):
        view.update_thumbnail_batch(row, [pix])
    return time.perf_counter() - started


def _assert_linear_pass(view: PDFView) -> None:
    pix = _landscape_pixmap()
    quarter_s = _timed_pass(view, FULL_ROWS // 4, pix)
    full_s = _timed_pass(view, FULL_ROWS, pix)
    if full_s >= LINEAR_GROWTH_FLOOR_S:
        growth = full_s / max(quarter_s, 1e-6)
        assert growth < LINEAR_GROWTH_LIMIT, (
            f"4x the rows took {growth:.1f}x the time ({quarter_s:.3f} s -> {full_s:.3f} s): not linear"
        )


def test_one_page_batches_keep_a_thumbnail_pass_linear(view) -> None:
    _assert_linear_pass(view)


def test_the_linear_guard_trips_on_a_per_batch_full_layout_pass(view, monkeypatch) -> None:
    """GUARD of the guard: re-laying every row after each batch (the old
    behaviour) must fail :func:`_assert_linear_pass`."""
    original = view.update_thumbnail_batch

    def relayout_every_batch(start_index, pixmaps):
        original(start_index, pixmaps)
        view._update_thumbnail_layout_metrics()

    monkeypatch.setattr(view, "update_thumbnail_batch", relayout_every_batch)
    with pytest.raises(AssertionError, match="not linear"):
        _assert_linear_pass(view)


def test_layout_follows_the_first_icons_and_every_row_keeps_the_grid(view) -> None:
    """Regression guard: the aspect ratio still comes from the first icons, and
    every row (including those whose icon arrived after the probe rows) keeps
    the grid size hint and centred text."""
    rows = 40
    # Wide sidebar: narrow ones clamp the icon height, hiding the aspect ratio.
    view.thumbnail_list.resize(300, 600)
    view.set_thumbnail_placeholders(rows)
    portrait_grid = view.thumbnail_list.gridSize()
    pix = _landscape_pixmap()
    for row in range(rows):
        view.update_thumbnail_batch(row, [pix])

    grid = view.thumbnail_list.gridSize()
    icon = view.thumbnail_list.iconSize()
    assert grid.height() < portrait_grid.height()  # landscape icons shrank the cells
    assert icon.height() <= int(icon.width() * 0.9)
    for row in range(rows):
        item = view.thumbnail_list.item(row)
        assert not item.icon().isNull()
        assert item.sizeHint() == grid
        assert item.textAlignment() & Qt.AlignHorizontal_Mask == Qt.AlignHCenter
