"""Ruled tables as page objects (docs/to_Update.md line 34, owner decision 2026-11-05).

A table found by PyMuPDF's ``Page.find_tables`` is one OBJECT for select and
delete in 操作物件 mode; its cell text stays ordinary text for the edit-text tool.
Tables are not movable or resizable (that would rewrite every cell).

* ``find_tables`` reports bboxes in the VISUAL (rotated) page frame (measured,
  PyMuPDF 1.27); deletion works in the unrotated frame through
  ``page.derotation_matrix``.
* A grid that covers most of the page (a CAD sheet frame, an ECC/HVAC title
  border) is never a table object: one click must not select, and one Delete
  must not wipe, a whole drawing.
* Detection costs 10-300 ms per page, so results are cached per page and per
  document revision (the live handle and ``edit_count``).

Qt-free (Model layer).
"""
from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)

TABLE_OBJECT_KIND = "table"
#: A detected grid larger than this share of the page is a sheet frame, not a table.
MAX_TABLE_PAGE_FRACTION = 0.6
#: Ruling strokes extend past the cell bbox by half their width; the redaction for
#: line art grows by this much so the outer border counts as "covered".
TABLE_STROKE_MARGIN_PT = 2.0
_MIN_ROWS = 2
_MIN_COLS = 2


_CACHES: weakref.WeakKeyDictionary[PDFModel, dict] = weakref.WeakKeyDictionary()


def _cache(model: PDFModel) -> dict:
    cache = _CACHES.get(model)
    if cache is None:
        cache = {}
        _CACHES[model] = cache
    return cache


def frame_key(model: PDFModel, page_num: int) -> tuple:
    """Cache key of page geometry (H3): document, page, revision and page frame."""
    doc = model.doc
    page = doc[page_num - 1]
    return (
        id(doc),
        int(page_num),
        int(model.edit_count),
        len(doc),
        page.rotation,
        tuple(page.cropbox),
        tuple(page.mediabox),
    )


def scratch_page_bytes(doc: fitz.Document, page_num: int) -> bytes:
    """One-page PDF copy of 1-based ``page_num``; the source is never touched (H1).

    ``annots``, ``links`` and ``widgets`` must all be off: with any of them on,
    ``insert_pdf`` changes objects of the source document (measured).
    """
    scratch = fitz.open()
    try:
        scratch.insert_pdf(
            doc,
            from_page=page_num - 1,
            to_page=page_num - 1,
            annots=False,
            links=False,
            widgets=False,
        )
        return scratch.tobytes()
    finally:
        scratch.close()


def find_table_rects(page: fitz.Page) -> list[tuple[float, float, float, float]]:
    """Table bboxes found on ``page`` (the caller passes a scratch page)."""
    rects: list[tuple[float, float, float, float]] = []
    try:
        page_area = max(1.0, float(page.rect.width) * float(page.rect.height))
        for table in page.find_tables().tables:
            if table.row_count < _MIN_ROWS or table.col_count < _MIN_COLS:
                continue
            rect = fitz.Rect(table.bbox)
            if rect.is_empty or rect.width * rect.height > MAX_TABLE_PAGE_FRACTION * page_area:
                continue
            rects.append(tuple(rect))
    except Exception as exc:  # detection is best-effort; no table object then
        logger.debug("table detection failed: %s", exc)
        rects = []
    return rects


def cached_table_rects(model: PDFModel, page_num: int) -> list[fitz.Rect] | None:
    """Cached rectangles for the current page frame; ``None`` on a miss (no work)."""
    doc = model.doc
    if not doc or page_num < 1 or page_num > len(doc):
        return None
    cached = _cache(model).get(frame_key(model, page_num))
    if cached is None:
        return None
    return [fitz.Rect(r) for r in cached]


def store_table_rects(model: PDFModel, key: tuple, rects) -> bool:
    """Store ``rects`` under ``key``; ``True`` only if ``key`` is still current."""
    doc = model.doc
    page_num = key[1]
    if not doc or page_num < 1 or page_num > len(doc) or key != frame_key(model, page_num):
        return False
    cache = _cache(model)
    # Only the current revision is worth keeping.
    for stale in [k for k in cache if k[0] != key[0] or k[2] != key[2]]:
        cache.pop(stale, None)
    cache[key] = [tuple(r) for r in rects]
    return True


def table_rects(model: PDFModel, page_num: int) -> list[fitz.Rect]:
    """Visual-frame bboxes of the table objects on 1-based ``page_num``."""
    doc = model.doc
    if not doc or page_num < 1 or page_num > len(doc):
        return []
    cached = cached_table_rects(model, page_num)
    if cached is not None:
        return cached
    key = frame_key(model, page_num)
    # Never on the live page: find_tables resets /Rotate and the MediaBox of a
    # rotated page while it works and does not restore a CropBox exactly
    # (measured, PyMuPDF 1.27.1), so a hit-test click would edit the document.
    # A one-page scratch copy keeps rotation and boxes, hence the same frame.
    rects: list[tuple[float, float, float, float]] = []
    try:
        with fitz.open(stream=scratch_page_bytes(doc, page_num), filetype="pdf") as scratch:
            rects = find_table_rects(scratch[0])
    except Exception as exc:
        logger.debug("table detection failed on page %s: %s", page_num, exc)
    store_table_rects(model, key, rects)
    return [fitz.Rect(r) for r in rects]


def table_object_id(page_num: int, rect: fitz.Rect) -> str:
    return f"table:{int(page_num)}:{rect.x0:.2f},{rect.y0:.2f},{rect.x1:.2f},{rect.y1:.2f}"


def parse_table_object_id(object_id: str) -> tuple[int, fitz.Rect] | None:
    try:
        prefix, page, coords = str(object_id).split(":", 2)
        if prefix != TABLE_OBJECT_KIND:
            return None
        x0, y0, x1, y1 = (float(v) for v in coords.split(","))
        return int(page), fitz.Rect(x0, y0, x1, y1)
    except (ValueError, TypeError):
        return None


def table_at_point(model: PDFModel, page_num: int, point: fitz.Point) -> fitz.Rect | None:
    """The smallest table object containing visual ``point``, if any."""
    hits = [r for r in table_rects(model, page_num) if fitz.Point(point) in r]
    if not hits:
        return None
    return min(hits, key=lambda r: r.width * r.height)


def matching_table(model: PDFModel, page_num: int, rect: fitz.Rect, tolerance: float = 1.0) -> fitz.Rect | None:
    """The table object on the page that is still where ``rect`` says, if any."""
    for found in table_rects(model, page_num):
        if all(abs(a - b) <= tolerance for a, b in zip(found, rect)):
            return found
    return None


def erase_table(page: fitz.Page, visual_rect: fitz.Rect) -> fitz.Rect:
    """Remove the text and ruling lines inside the table; returns the unrotated rect.

    Text: characters overlapping the table rect.  Line art: only paths fully
    covered by the rect grown by ``TABLE_STROKE_MARGIN_PT`` (neighbouring rules
    and drawings that merely touch it stay).  Images are kept.
    """
    unrotated = fitz.Rect(visual_rect) * page.derotation_matrix
    unrotated.normalize()
    text_rect = fitz.Rect(unrotated)
    art_rect = fitz.Rect(unrotated) + (
        -TABLE_STROKE_MARGIN_PT,
        -TABLE_STROKE_MARGIN_PT,
        TABLE_STROKE_MARGIN_PT,
        TABLE_STROKE_MARGIN_PT,
    )
    # Two passes so text and line art each get their own extent: the grown rect
    # is for strokes only and must not take characters just outside the table.
    # add_*_annot geometry is UNROTATED page space (PITFALLS, rotated annotations).
    page.add_redact_annot(text_rect, fill=False, cross_out=False)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )
    page.add_redact_annot(art_rect, fill=False, cross_out=False)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
        text=fitz.PDF_REDACT_TEXT_NONE,
    )
    return unrotated
