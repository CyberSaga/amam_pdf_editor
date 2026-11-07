from __future__ import annotations

import json
import math

import fitz

from model.page_raster import RasterSamples, _raster
from utils.render_limits import safe_render_scale, thumbnail_render_scale

MAX_WATERMARK_BYTES = 48 * 1024


def decode_watermark_recipe(data: bytes) -> tuple[dict, ...]:
    """Accept bounded frozen, already-sanitized Model descriptors, without repair.

    Reject instead of truncating or sanitizing again: omitted/changed overlay
    ink must never be mistaken for a successful render of the frozen source.
    """
    if type(data) is not bytes or len(data) > MAX_WATERMARK_BYTES:
        raise ValueError('invalid watermark recipe')
    try:
        values = json.loads(data)
        if not isinstance(values, list) or len(values) > 128:
            raise ValueError()
        if not values:
            return ()
        # Lazy imports keep ordinary-page startup independent of overlay code.
        from model.tools.watermark_tool import _coerce_wm

        for value in values:
            if not isinstance(value, dict):
                raise ValueError()
            if (not isinstance(value.get('pages'), list)
                    or any(type(page) is not int or page < 1 for page in value['pages'])):
                raise ValueError()
            for key in ('angle', 'opacity', 'font_size', 'offset_x', 'offset_y', 'line_spacing'):
                if key in value and (type(value[key]) not in (int, float)
                                     or not math.isfinite(value[key])):
                    raise ValueError()
            color = value.get('color')
            if (not isinstance(color, list) or len(color) != 3
                    or any(type(c) not in (int, float) or not math.isfinite(c) for c in color)):
                raise ValueError()
            sanitized = _coerce_wm(value)
            if sanitized is None or json.loads(json.dumps(sanitized)) != value:
                raise ValueError()
        return tuple(values)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ValueError('invalid watermark recipe') from None


def rasterize_overlay(doc: fitz.Document, page_index: int, scale: float,
                      color_profile: str, recipe: bytes, *, thumbnail: bool = False) -> RasterSamples:
    watermarks = decode_watermark_recipe(recipe)
    page = doc[page_index]
    actual_scale = thumbnail_render_scale(page) if thumbnail else safe_render_scale(page, scale)
    covered = [wm for wm in watermarks if page_index + 1 in wm['pages']]
    if not covered:
        return _raster(page, actual_scale, color_profile)
    from model.tools.watermark_rendering import apply_watermarks_to_page

    # Same view oracle as ToolManager: copy exactly one original page, stamp
    # once, and rasterize at the scale clamped on the original page.
    # insert_pdf can remove /P from SOURCE annotation dictionaries. Never graft
    # from the retained worker document. Immutable stream-backed workers reuse
    # their original bytes; edited/file-backed callers serialize their live state.
    source = doc.stream if not doc.is_dirty and isinstance(doc.stream, bytes) else doc.tobytes(
        garbage=0, no_new_id=True, encryption=fitz.PDF_ENCRYPT_NONE)
    with fitz.open(stream=source, filetype='pdf') as isolated, fitz.open() as temporary:
        temporary.insert_pdf(isolated, from_page=page_index, to_page=page_index)
        target = temporary[0]
        apply_watermarks_to_page(target, covered)
        return _raster(target, actual_scale, color_profile)
