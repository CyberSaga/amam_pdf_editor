from __future__ import annotations

import subprocess
import sys

import fitz
import pytest

from model.page_raster import rasterize_page, rasterize_thumbnail
from model.color_profile import safe_to_fitz_colorspace
from utils.render_limits import thumbnail_render_scale


@pytest.mark.parametrize("profile", ["srgb", "gray", "cmyk"])
def test_raster_matches_direct_pixels_with_annotation(profile):
    with fitz.open() as doc:
        page = doc.new_page(width=120, height=160)
        page.insert_text((20, 30), "Raster")
        page.add_rect_annot(fitz.Rect(10, 40, 50, 80)).update()
        actual = rasterize_page(doc, 0, 1.25, profile)
        expected = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), annots=True,
                                   colorspace=safe_to_fitz_colorspace(profile))
        if expected.colorspace.n in {1, 4}:
            expected = fitz.Pixmap(fitz.csRGB, expected)
        assert (actual.width, actual.height, actual.stride, actual.n, actual.alpha,
                actual.samples) == (expected.width, expected.height, expected.stride,
                                    expected.n, bool(expected.alpha), expected.samples)
        thumb = rasterize_thumbnail(doc, 0, profile)
        direct = page.get_pixmap(matrix=fitz.Matrix(thumbnail_render_scale(page),
                                                  thumbnail_render_scale(page)))
        assert (thumb.width, thumb.height) == (direct.width, direct.height)


def test_page_raster_is_qt_free():
    result = subprocess.run([sys.executable, "-c",
        "import model.page_raster, sys; assert 'PySide6' not in sys.modules; "
        "assert 'model.pdf_model' not in sys.modules"], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_raster_test_is_classified_pure():
    from pathlib import Path
    from scripts.run_suite import classify
    assert classify(Path(__file__).read_text(encoding="utf-8"),
                    "test_scripts/test_page_raster.py") == "pure"


def test_large_page_preserves_existing_scale_clamp_without_allocating_40mp(monkeypatch):
    import math
    import model.page_raster as module
    from utils.render_limits import safe_render_scale
    calls = []
    sentinel = object()

    def capture(page, scale, profile):
        calls.append((scale, profile))
        return sentinel

    monkeypatch.setattr(module, "_raster", capture)
    with fitz.open() as doc:
        page = doc.new_page(width=20000, height=20000)
        assert module.rasterize_page(doc, 0, 2, "srgb") is sentinel
        scale = calls[0][0]
        assert scale == safe_render_scale(page, 2)
        assert scale < 2
        # Raster integer rounding may add a boundary row/column, unchanged.
        assert math.ceil(20000 * scale) ** 2 <= 40_000_000 + 2 * 6325 + 1
