from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import fitz

from model.color_profile import safe_to_fitz_colorspace
from utils.render_limits import safe_render_scale, thumbnail_render_scale


@dataclass(frozen=True)
class RasterSamples:
    width: int
    height: int
    stride: int
    n: int
    alpha: bool
    samples: bytes


def _raster(page: fitz.Page, scale: float, color_profile: str) -> RasterSamples:
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), annots=True,
                         colorspace=safe_to_fitz_colorspace(color_profile))
    return _samples(pix)


def _samples(pix: fitz.Pixmap) -> RasterSamples:
    if not pix.alpha and pix.colorspace is not None and pix.colorspace.n in {1, 4}:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return RasterSamples(pix.width, pix.height, pix.stride, pix.n, bool(pix.alpha), pix.samples)


def rasterize_page(doc: fitz.Document, page_index: int, scale: float,
                   color_profile: str, *, watermarks_json: bytes = b'[]') -> RasterSamples:
    if watermarks_json != b'[]':
        from model.watermark_raster import rasterize_overlay
        return rasterize_overlay(doc, page_index, scale, color_profile, watermarks_json)
    page = doc[page_index]
    return _raster(page, safe_render_scale(page, scale), color_profile)


def rasterize_thumbnail(doc: fitz.Document, page_index: int,
                        color_profile: str, *, watermarks_json: bytes = b'[]') -> RasterSamples:
    if watermarks_json != b'[]':
        from model.watermark_raster import rasterize_overlay
        return rasterize_overlay(doc, page_index, 1.0, color_profile, watermarks_json, thumbnail=True)
    page = doc[page_index]
    return _raster(page, thumbnail_render_scale(page), color_profile)


class HotPageRaster:
    """Opt-in retention for one immutable worker document, not a byte budget.

    The Page wrapper itself builds a temporary DisplayList on every raster.
    Retain at most one only after repeated foreground demand. Neither scanning
    thumbnails nor the first foreground render builds an extra retained list.
    The owner must clear this object BEFORE closing/replacing its document.
    """

    def __init__(self, doc: fitz.Document) -> None:
        self._doc = doc
        self._lists: OrderedDict[int, fitz.DisplayList] = OrderedDict()
        self._seen: OrderedDict[int, str | None] = OrderedDict()
        self.last_path = 'page'

    @property
    def retained_pages(self) -> tuple[int, ...]:
        return tuple(self._lists)

    @property
    def seen_pages(self) -> tuple[int, ...]:
        return tuple(self._seen)

    def clear(self) -> None:
        self._lists.clear()
        self._seen.clear()
        self.last_path = 'page'

    def render(self, page_index: int, scale: float, color_profile: str, *,
               thumbnail: bool = False, retain: bool = False,
               intent: str | None = None, promotion_allowed: bool = True) -> RasterSamples:
        if not retain:
            self.clear()
        page = self._doc[page_index]
        actual_scale = thumbnail_render_scale(page) if thumbnail else safe_render_scale(page, scale)
        retained = self._lists.get(page_index) if retain else None
        build = (retain and promotion_allowed and retained is None
                 and not thumbnail and page_index in self._seen
                 and (intent is None or self._seen[page_index] != intent))
        self.last_path = 'page'
        try:
            if build:
                # Evict before allocating the replacement, not after it.
                if self._lists:
                    self._lists.popitem(last=False)
                retained = page.get_displaylist(annots=True)
            if retained is None:
                result = _raster(page, actual_scale, color_profile)
            else:
                result = _samples(retained.get_pixmap(
                    matrix=fitz.Matrix(actual_scale, actual_scale),
                    colorspace=safe_to_fitz_colorspace(color_profile), alpha=False))
                self._lists[page_index] = retained
                self._lists.move_to_end(page_index)
                self.last_path = 'build' if build else 'hit'
        except Exception:
            self._lists.pop(page_index, None)
            raise
        if retain and promotion_allowed and not thumbnail:
            self._seen[page_index] = intent
            self._seen.move_to_end(page_index)
            if len(self._seen) > 8:
                self._seen.popitem(last=False)
        return result
