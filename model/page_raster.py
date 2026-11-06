from __future__ import annotations

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
    if not pix.alpha and pix.colorspace is not None and pix.colorspace.n in {1, 4}:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return RasterSamples(pix.width, pix.height, pix.stride, pix.n, bool(pix.alpha), pix.samples)


def rasterize_page(doc: fitz.Document, page_index: int, scale: float,
                   color_profile: str) -> RasterSamples:
    page = doc[page_index]
    return _raster(page, safe_render_scale(page, scale), color_profile)


def rasterize_thumbnail(doc: fitz.Document, page_index: int,
                        color_profile: str) -> RasterSamples:
    page = doc[page_index]
    return _raster(page, thumbnail_render_scale(page), color_profile)
