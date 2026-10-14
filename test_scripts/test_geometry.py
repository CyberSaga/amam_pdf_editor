from __future__ import annotations

import fitz
import pytest

from model.geometry import (
    clamp_rect_to_page,
    rect_from_points,
    rect_overlap_ratio,
    rect_union,
    unrotated_page_rect,
    unrotated_to_visual_point,
    unrotated_to_visual_rect,
    visual_to_unrotated_point,
    visual_to_unrotated_rect,
)
from model.text_commit.transforms import page_visual_frame, page_visual_frame_or_none


def test_clamp_inside_page_unchanged():
    r = fitz.Rect(10, 10, 100, 100)
    assert clamp_rect_to_page(r, fitz.Rect(0, 0, 595, 842)) == r


def test_clamp_overflow_right():
    r = fitz.Rect(500, 10, 700, 100)
    assert clamp_rect_to_page(r, fitz.Rect(0, 0, 595, 842)).x1 <= 595


def test_clamp_overflow_bottom():
    r = fitz.Rect(10, 800, 100, 900)
    assert clamp_rect_to_page(r, fitz.Rect(0, 0, 595, 842)).y1 <= 842


def test_clamp_degenerate_is_nonempty():
    r = clamp_rect_to_page(fitz.Rect(700, 700, 800, 800), fitz.Rect(0, 0, 595, 842))
    assert r.width >= 1 and r.height >= 1


def test_rect_from_points_basic():
    r = rect_from_points([fitz.Point(0, 0), fitz.Point(100, 200)])
    assert r == fitz.Rect(0, 0, 100, 200)


def test_rect_from_points_multiple():
    pts = [fitz.Point(50, 10), fitz.Point(10, 50), fitz.Point(30, 30)]
    r = rect_from_points(pts)
    assert r.x0 == 10 and r.y0 == 10 and r.x1 == 50 and r.y1 == 50


def test_rect_union_empty():
    assert rect_union([]) == fitz.Rect()


def test_rect_union_single():
    r = fitz.Rect(10, 10, 50, 50)
    assert rect_union([r]) == r


def test_rect_union_two():
    u = rect_union([fitz.Rect(0, 0, 50, 50), fitz.Rect(25, 25, 100, 100)])
    assert u == fitz.Rect(0, 0, 100, 100)


def test_rect_union_three():
    u = rect_union([fitz.Rect(0, 0, 10, 10), fitz.Rect(20, 20, 30, 30), fitz.Rect(5, 5, 25, 25)])
    assert u.x0 == 0 and u.y0 == 0 and u.x1 == 30 and u.y1 == 30


def test_overlap_ratio_no_overlap():
    assert rect_overlap_ratio(fitz.Rect(0, 0, 50, 50), fitz.Rect(100, 100, 200, 200)) == 0.0


def test_overlap_ratio_full_contain():
    ratio = rect_overlap_ratio(fitz.Rect(0, 0, 100, 100), fitz.Rect(25, 25, 75, 75))
    assert ratio == pytest.approx(1.0)


def test_overlap_ratio_partial():
    # Two 50x50 rects overlapping by 25x50 = 1250 area; smaller is 2500; ratio = 0.5
    ratio = rect_overlap_ratio(fitz.Rect(0, 0, 50, 50), fitz.Rect(25, 0, 75, 50))
    assert ratio == pytest.approx(0.5)


def test_overlap_ratio_empty_rect():
    assert rect_overlap_ratio(fitz.Rect(), fitz.Rect(0, 0, 10, 10)) == 0.0


# --- F15-G1-UU-ROT: the page-space chokepoints on a ROTATED /UserUnit page ---
#
# ``page.rotation_matrix`` / ``derotation_matrix`` drop ``/UserUnit`` (they size
# the quarter turn from the unscaled box), while ``get_text`` geometry is
# multiplied by it.  The chokepoints must agree with the page's own frame.


def _geometry_page(
    rotation: int,
    user_unit: float,
    *,
    cropbox: tuple[float, ...] | None = None,
    mediabox: tuple[float, ...] = (0, 0, 300, 400),
):
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox is not None:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % cropbox)
    doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
    doc.xref_set_key(page.xref, "Rotate", str(rotation))
    return doc, doc.reload_page(page)


@pytest.mark.parametrize(
    ("mediabox", "cropbox"),
    [
        ((0, 0, 300, 400), None),
        ((0, 0, 300, 400), (15.0, 20.0, 250.0, 350.0)),
        # CropBox past the MediaBox: PyMuPDF sizes the quarter turn from the UNCLIPPED box.
        ((-100, -100, 495, 742), (50.0, 60.0, 545.0, 782.0)),
    ],
    ids=["plain", "crop", "crop_past_mediabox"],
)
@pytest.mark.parametrize("user_unit", [1.0, 2.0, 0.5])
@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_visual_unrotated_conversions_follow_the_frame_on_a_rotated_page(
    rotation: int, user_unit: float, mediabox, cropbox
) -> None:
    doc, page = _geometry_page(rotation, user_unit, cropbox=cropbox, mediabox=mediabox)
    try:
        frame = page_visual_frame(page)
        page_box = fitz.Rect(0, 0, frame.width0, frame.height0)
        assert tuple(unrotated_page_rect(page)) == pytest.approx(tuple(page_box), abs=1e-3)
        assert tuple(visual_to_unrotated_rect(page, page.rect)) == pytest.approx(tuple(page_box), abs=1e-3)
        assert tuple(unrotated_to_visual_rect(page, page_box)) == pytest.approx(tuple(page.rect), abs=1e-3)
        probe = fitz.Point(page.rect.width * 0.25, page.rect.height * 0.8)
        want = probe * ~frame.quarter_turn
        got = visual_to_unrotated_point(page, probe)
        assert (got.x, got.y) == pytest.approx((want.x, want.y), abs=1e-3)
        back = unrotated_to_visual_point(page, got)
        assert (back.x, back.y) == pytest.approx((probe.x, probe.y), abs=1e-3)
    finally:
        doc.close()


def test_visual_unrotated_conversions_fall_back_when_the_frame_cannot_be_proven() -> None:
    doc, page = _geometry_page(90, 1.0)
    try:
        # A CropBox outside the MediaBox: MuPDF falls back to a letter page, no frame.
        doc.xref_set_key(page.xref, "CropBox", "[500 500 600 600]")
        page = doc.reload_page(page)
        assert page.rotation == 90 and page_visual_frame_or_none(page) is None
        r = fitz.Rect(10, 10, 60, 40)
        assert visual_to_unrotated_rect(page, r) == (r * page.derotation_matrix).normalize()
        assert unrotated_to_visual_rect(page, r) == (r * page.rotation_matrix).normalize()
    finally:
        doc.close()
