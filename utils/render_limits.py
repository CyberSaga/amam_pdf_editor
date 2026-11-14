from __future__ import annotations

import fitz

_MAX_PIXMAP_PX = 40_000_000  # ~40 MP per rendered page
# Matches the widest thumbnail cell (left sidebar max 400 px): thumbnails follow
# the sidebar width and a QIcon never upscales past its pixmap.  Measured
# 2026-11-05: x1.03-1.17 render time vs 270 px (content interpretation
# dominates), but ~0.82 MB per portrait page as RGB32 -- every page keeps its
# icon -- so long documents stay at 270 px (~330 MB at the 400-page limit).
THUMBNAIL_RENDER_WIDTH_PX = 380
THUMBNAIL_RENDER_WIDTH_LARGE_DOC_PX = 270
LARGE_DOCUMENT_PAGES = 400
# CF11 height cap: 10x the selected width target (a 10:1 page). Chosen so legitimate tall
# pages (corpus: up to ~8.4:1) keep the full width-based thumbnail; only extreme pages are
# reduced (a 1 x 14400 pt page was ~40 MP at width-only sizing).
MAX_THUMBNAIL_ASPECT = 10


def thumbnail_render_scale(page: fitz.Page) -> float:
    """Return a bounded scale that renders a thumbnail near the UI's max width.

    The scale is the smaller of the width-based target and the height cap
    (``MAX_THUMBNAIL_ASPECT`` x the target width), then passed through
    safe_render_scale (0.1 floor, 40 MP cap). Normal pages are unaffected: the
    height cap only binds for pages taller than 10:1."""
    doc = page.parent
    target = (
        THUMBNAIL_RENDER_WIDTH_LARGE_DOC_PX
        if doc is not None and len(doc) > LARGE_DOCUMENT_PAGES
        else THUMBNAIL_RENDER_WIDTH_PX
    )
    width = max(1.0, float(page.rect.width))
    height = max(1.0, float(page.rect.height))
    requested = min(target / width, MAX_THUMBNAIL_ASPECT * target / height)
    return min(requested, safe_render_scale(page, requested))


def safe_render_scale(page: fitz.Page, scale: float) -> float:
    """Clamp a render scale so a single page's pixmap stays under _MAX_PIXMAP_PX.

    Normal-sized pages are returned unchanged; only pathologically large pages are
    scaled down. A 0.1 floor is kept so the result is never a degenerate render —
    note this means an extreme page (millions of points per side) can still exceed
    the cap at 0.1, which is an accepted tradeoff."""
    w, h = page.rect.width, page.rect.height
    if w * h * scale * scale > _MAX_PIXMAP_PX:
        scale = (_MAX_PIXMAP_PX / max(1.0, w * h)) ** 0.5
    return max(0.1, scale)
