"""Thumbnail raster width (Opus recommendation, owner-approved 2026-11-05).

380 px so thumbnails can fill the widest (400 px) sidebar cell; the per-page
time cost is x1.03-1.17 but memory doubles (~0.82 MB per portrait page as
RGB32), so documents over 400 pages keep 270 px (~330 MB cap at 400 pages).
"""
from __future__ import annotations

import fitz

from utils.render_limits import (
    LARGE_DOCUMENT_PAGES,
    THUMBNAIL_RENDER_WIDTH_PX,
    THUMBNAIL_RENDER_WIDTH_LARGE_DOC_PX,
    thumbnail_render_scale,
)


def _doc(pages: int, width: float = 595, height: float = 842) -> fitz.Document:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=width, height=height)
    return doc


def test_normal_document_thumbnails_render_380_px_wide() -> None:
    with _doc(3) as doc:
        page = doc[0]
        assert THUMBNAIL_RENDER_WIDTH_PX == 380
        assert abs(thumbnail_render_scale(page) * page.rect.width - 380) < 0.5


def test_document_over_400_pages_keeps_270_px() -> None:
    assert LARGE_DOCUMENT_PAGES == 400
    assert THUMBNAIL_RENDER_WIDTH_LARGE_DOC_PX == 270
    with _doc(LARGE_DOCUMENT_PAGES) as doc:
        page = doc[0]
        assert abs(thumbnail_render_scale(page) * page.rect.width - 380) < 0.5
    with _doc(LARGE_DOCUMENT_PAGES + 1, width=200, height=280) as doc:
        page = doc[0]
        assert abs(thumbnail_render_scale(page) * page.rect.width - 270) < 0.5


def test_large_document_height_cap_follows_the_270_px_width() -> None:
    # CF11 cap is 10x the SELECTED width: 2700 px above 400 pages, not 3800.
    with _doc(LARGE_DOCUMENT_PAGES + 1, width=10, height=14400) as doc:
        page = doc[0]
        assert abs(thumbnail_render_scale(page) * page.rect.height - 10 * 270) < 0.5


def test_oversized_page_is_still_clamped() -> None:
    with _doc(1, width=14400, height=14400) as doc:
        page = doc[0]
        scale = thumbnail_render_scale(page)
        assert page.rect.width * page.rect.height * scale * scale <= 40_000_000 * 1.0001
