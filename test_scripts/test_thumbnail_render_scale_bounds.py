from __future__ import annotations

import fitz
import pytest

from utils.render_limits import THUMBNAIL_RENDER_WIDTH_PX, thumbnail_render_scale

MAX_THUMBNAIL_HEIGHT_PX = 10 * THUMBNAIL_RENDER_WIDTH_PX  # 10:1 max aspect for sidebar thumbnails
_SCALE_FLOOR = 0.1  # safe_render_scale never returns less than this


def _page(width: float, height: float) -> fitz.Page:
    doc = fitz.open()
    return doc.new_page(width=width, height=height)


def test_tall_narrow_page_thumbnail_height_is_capped():
    page = _page(1, 14400)
    scale = thumbnail_render_scale(page)
    height_px = page.rect.height * scale
    assert height_px <= MAX_THUMBNAIL_HEIGHT_PX
    assert scale == pytest.approx(MAX_THUMBNAIL_HEIGHT_PX / page.rect.height)
    assert scale > 0


def test_tall_narrow_page_rendered_pixel_count_is_small():
    page = _page(1, 14400)
    scale = thumbnail_render_scale(page)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    assert pix.width * pix.height <= THUMBNAIL_RENDER_WIDTH_PX * 1440


def test_moderately_tall_page_is_capped_at_max_height():
    page = _page(1, 4000)
    scale = thumbnail_render_scale(page)
    assert page.rect.height * scale == pytest.approx(MAX_THUMBNAIL_HEIGHT_PX)


@pytest.mark.parametrize(
    ("width", "height"),
    [(595, 842), (612, 792), (842, 595)],  # A4 portrait, Letter portrait, A4 landscape
)
def test_normal_pages_keep_width_based_scale(width, height):
    page = _page(width, height)
    expected = THUMBNAIL_RENDER_WIDTH_PX / width
    assert thumbnail_render_scale(page) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("width", "height"),
    [(595, 5021), (800, 5424)],  # corpus pages issue14724 p0 / issue14982 p0 (~8.4:1, 6.8:1)
)
def test_legitimate_tall_pages_keep_width_based_scale(width, height):
    page = _page(width, height)
    assert thumbnail_render_scale(page) == pytest.approx(THUMBNAIL_RENDER_WIDTH_PX / width)
