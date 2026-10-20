"""F15-G5 -- watermark placement on ``/Rotate`` pages.

``apply_watermarks_to_page`` is the single renderer behind both the live
overlay (``WatermarkTool.apply_page_overlay``) and the save path
(``prepare_doc_for_save`` -> ``apply_watermarks_to_document``).  The dialog
promises DISPLAYED-page semantics: the watermark is centred on the page as
shown, a positive ``offset_x`` moves it right and a positive ``offset_y`` moves
it down.

``Page.insert_text`` works in the UNROTATED page space and draws glyphs in
that frame, so on ``/Rotate 90/270`` the centre, the offsets and the angle all
have to be mapped through the page rotation.  The oracle is INK on a rendered
pixmap: a rotated page must look exactly like the same watermark on an upright
page of the displayed size (this pins the placement without freezing the
renderer's upright-page geometry), plus absolute checks of the reported
symptoms (horizontal text, centred, offsets right/down).
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.tools.watermark_rendering import (  # noqa: E402
    apply_watermarks_to_document,
    apply_watermarks_to_page,
)

_GEOMETRIES = {
    "plain": {"mb": (0, 0, 600, 800)},
    "crop": {"mb": (0, 0, 600, 800), "cb": (30, 40, 500, 700)},
    "negmb": {"mb": (-100, -200, 500, 600)},
}
_ROTATIONS = (90, 180, 270)
_TOL = 3.0
# (angle, offset_x, offset_y): flat, offset, diagonal+offset, vertical.
_PLACEMENTS = ((0, 0, 0), (0, 100, 40), (30, 0, 0), (45, 60, -30), (90, 0, 0))


def _page_doc(
    mb: tuple, cb: tuple | None = None, rot: int = 0, pages: int = 1, uu: float | None = None
) -> fitz.Document:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=200, height=200)
        doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mb)
        if cb:
            doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % cb)
        if uu is not None:
            doc.xref_set_key(page.xref, "UserUnit", str(uu))
        if rot:
            doc.xref_set_key(page.xref, "Rotate", str(rot))
    reopened = fitz.open("pdf", doc.tobytes())
    doc.close()
    return reopened


def _upright_twin(page: fitz.Page) -> fitz.Page:
    """An upright, origin-at-zero page with the same displayed size as *page*."""
    return _page_doc(mb=(0, 0, page.rect.width, page.rect.height))[0]


def _wm(**overrides) -> dict:
    wm = {
        "text": "WMARK TEST",
        "angle": 0,
        "opacity": 1.0,
        "font_size": 48,
        "color": (0, 0, 0),
        "font": "helv",
        "pages": [1],
    }
    wm.update(overrides)
    return wm


def _ink(page: fitz.Page) -> np.ndarray:
    """Boolean mask of dark pixels in the page's displayed raster."""
    pm = page.get_pixmap(alpha=False)
    arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)
    return arr[:, :, 0] < 128


def _ink_centre(page: fitz.Page) -> tuple[float, float, float, float]:
    """(centre_x, centre_y, bbox_width, bbox_height) of the page's ink."""
    ys, xs = np.nonzero(_ink(page))
    assert xs.size, "no ink drawn"
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return (x0 + x1) / 2, (y0 + y1) / 2, float(x1 - x0), float(y1 - y0)


def _assert_same_ink(page: fitz.Page, twin: fitz.Page, label: str = "") -> None:
    """``page`` carries the ink ``twin`` carries (at most 3 % of the twin's pixels differ)."""
    got, want = _ink(page), _ink(twin)
    assert got.shape == want.shape, label
    assert want.sum() > 0, label
    assert np.count_nonzero(got ^ want) <= 0.03 * want.sum(), label


@pytest.mark.parametrize("angle,offset_x,offset_y", _PLACEMENTS)
@pytest.mark.parametrize("rot", _ROTATIONS)
@pytest.mark.parametrize("geo", sorted(_GEOMETRIES))
def test_rotated_page_gets_the_watermark_an_upright_page_of_the_same_size_gets(
    geo: str, rot: int, angle: int, offset_x: int, offset_y: int
) -> None:
    page = _page_doc(rot=rot, **_GEOMETRIES[geo])[0]
    twin = _upright_twin(page)
    wm = _wm(angle=angle, offset_x=offset_x, offset_y=offset_y)
    apply_watermarks_to_page(page, [wm])
    apply_watermarks_to_page(twin, [wm])
    _assert_same_ink(page, twin)


@pytest.mark.parametrize("rot", _ROTATIONS)
@pytest.mark.parametrize("geo", sorted(_GEOMETRIES))
def test_angle_zero_watermark_reads_horizontally_and_is_centred_across(geo: str, rot: int) -> None:
    page = _page_doc(rot=rot, **_GEOMETRIES[geo])[0]
    apply_watermarks_to_page(page, [_wm(text="WMARK")])
    cx, _, width, height = _ink_centre(page)
    assert width > height, f"{geo}/Rotate {rot}: angle 0 must read horizontally on screen"
    assert cx == pytest.approx(page.rect.width / 2, abs=_TOL)


@pytest.mark.parametrize("rot", _ROTATIONS)
@pytest.mark.parametrize("geo", sorted(_GEOMETRIES))
def test_offsets_move_the_watermark_right_and_down_on_the_screen(geo: str, rot: int) -> None:
    base = _page_doc(rot=rot, **_GEOMETRIES[geo])[0]
    moved = _page_doc(rot=rot, **_GEOMETRIES[geo])[0]
    # A short word: the shifted ink must stay inside the narrowest (470 pt) page.
    apply_watermarks_to_page(base, [_wm(text="WMARK")])
    apply_watermarks_to_page(moved, [_wm(text="WMARK", offset_x=100, offset_y=40)])
    bx, by, _, _ = _ink_centre(base)
    mx, my, _, _ = _ink_centre(moved)
    assert mx - bx == pytest.approx(100, abs=2)
    assert my - by == pytest.approx(40, abs=2)


def test_save_path_places_a_rotated_page_watermark_like_the_overlay_path() -> None:
    """``apply_watermarks_to_document`` (the save clone) and the overlay share the geometry."""
    overlay_doc = _page_doc(rot=90, **_GEOMETRIES["plain"])
    apply_watermarks_to_page(overlay_doc[0], [_wm(offset_x=100, angle=30)])
    save_doc = _page_doc(rot=90, **_GEOMETRIES["plain"])
    apply_watermarks_to_document(save_doc, [_wm(offset_x=100, angle=30)])
    assert np.array_equal(_ink(save_doc[0]), _ink(overlay_doc[0]))
    assert _ink(save_doc[0]).any()


def test_mixed_portrait_and_rotated_pages_get_the_same_on_screen_watermark() -> None:
    doc = _page_doc(mb=(0, 0, 600, 800))
    rotated = _page_doc(mb=(0, 0, 600, 800), rot=90)
    doc.insert_pdf(rotated)
    rotated.close()
    wm = _wm(pages=[1, 2], text="DRAFT", angle=45, offset_x=20)
    apply_watermarks_to_document(doc, [wm])
    for index in (0, 1):
        twin = _upright_twin(doc[index])
        apply_watermarks_to_page(twin, [wm])
        _assert_same_ink(doc[index], twin, f"page {index + 1}")


def test_no_watermarks_or_blank_text_draws_nothing_on_a_rotated_page() -> None:
    page = _page_doc(rot=90, **_GEOMETRIES["plain"])[0]
    apply_watermarks_to_page(page, [])
    apply_watermarks_to_page(page, [_wm(text="  \n ")])
    assert not _ink(page).any()


# --- F15-G6: /UserUnit pages ------------------------------------------------
# ``Page.insert_text`` takes UNSCALED user units while ``page.rect`` (the frame
# the centre, the font size and every offset live in) is already multiplied by
# ``/UserUnit``.  The ink oracle again: a ``/UserUnit`` page must carry exactly
# the watermark a unit-scale page of the same displayed size carries.
_UU_GEOMETRIES = {
    "uu2": {"mb": (0, 0, 300, 400), "uu": 2},
    "uu0.5": {"mb": (0, 0, 1200, 1600), "uu": 0.5},
    "uu2_crop": {"mb": (0, 0, 300, 400), "cb": (15, 20, 250, 350), "uu": 2},
    "uu2_negmb": {"mb": (-50, -100, 250, 300), "uu": 2},
}


def _uu_page(mb: tuple, uu: float, cb: tuple | None = None, rot: int = 0) -> fitz.Page:
    return _page_doc(mb, cb, rot, uu=uu)[0]


@pytest.mark.parametrize("angle,offset_x,offset_y", _PLACEMENTS)
@pytest.mark.parametrize("geo", sorted(_UU_GEOMETRIES))
def test_user_unit_page_gets_the_watermark_a_unit_page_of_the_same_size_gets(
    geo: str, angle: int, offset_x: int, offset_y: int
) -> None:
    page = _uu_page(**_UU_GEOMETRIES[geo])
    twin = _upright_twin(page)
    wm = _wm(angle=angle, offset_x=offset_x, offset_y=offset_y)
    apply_watermarks_to_page(page, [wm])
    apply_watermarks_to_page(twin, [wm])
    _assert_same_ink(page, twin)


@pytest.mark.parametrize("geo", sorted(_UU_GEOMETRIES))
def test_user_unit_watermark_keeps_its_font_size_in_page_units_and_all_its_text(geo: str) -> None:
    page = _uu_page(**_UU_GEOMETRIES[geo])
    apply_watermarks_to_page(page, [_wm(text="WMARK")])
    cx, cy, width, height = _ink_centre(page)
    assert cx == pytest.approx(page.rect.width / 2, abs=_TOL)
    # A 48 pt "WMARK" is about 180 x 36 pt; doubled it would be 2x that and cut.
    assert 150 <= width <= 200 and 30 <= height <= 45, (width, height)
    assert page.get_text().strip() == "WMARK"


# F15-G1-UU-ROT (was a strict xfail pinning the TODOS "model/geometry.py shares
# the rotated-page defect" item): ``visual_to_unrotated_point`` used
# ``page.derotation_matrix``, which drops ``/UserUnit``, so the centre of a ROTATED
# ``/UserUnit`` page was mapped by the unscaled page size. The geometry
# chokepoints now go through ``page_visual_frame().quarter_turn``.
@pytest.mark.parametrize("rot", _ROTATIONS)
def test_user_unit_rotated_page_gets_the_watermark_an_upright_twin_gets(rot: int) -> None:
    page = _uu_page(rot=rot, **_UU_GEOMETRIES["uu2"])
    twin = _upright_twin(page)
    wm = _wm(angle=30, offset_x=40, offset_y=-20)
    apply_watermarks_to_page(page, [wm])
    apply_watermarks_to_page(twin, [wm])
    _assert_same_ink(page, twin)


# --- F15-G5-GEOM: the upright geometry itself ---------------------------------
# Owner decision (round 16): the watermark's INK is centred on the DISPLAYED page
# centre plus the requested offsets, at every angle.  The renderer used to pre-turn
# each line's origin by ``angle`` and let ``insert_text``'s morph turn it again
# (rotated by twice the angle) and stacked the lines from the block's top edge
# instead of centring them.  The oracle is the bounding-box centre of the rendered
# ink against ``page.rect``'s centre; no arithmetic of the renderer is frozen.
# Files saved by older builds show a second (old-geometry) copy on reopen; that is
# owner-accepted (no migration), see PITFALLS F15-G5-GEOM.
_GEOM_TOL = 2.0
_CAPS = {
    # Square-cornered caps, no descenders: a turned line's ink box is then symmetric about
    # its centre (the corners of W / A / K are not inked and skew the box by 3-4 pt at 45).
    "single": "HEHEH",
    "multi": "MMMM\nHHHH\nMMMM",
    "multi_mixed_widths": "HEHEH\nHE\nHEHEH",
}
_GEOM_ROTATIONS = (0, 90, 180, 270)


def _geom_page(rot: int) -> fitz.Page:
    return _page_doc(mb=(0, 0, 600, 800), rot=rot)[0]


def _assert_ink_centred(page: fitz.Page, offset_x: float = 0, offset_y: float = 0, tol: float = _GEOM_TOL) -> None:
    cx, cy, _, _ = _ink_centre(page)
    want_x = page.rect.width / 2 + offset_x
    want_y = page.rect.height / 2 + offset_y
    assert (cx, cy) == (pytest.approx(want_x, abs=tol), pytest.approx(want_y, abs=tol))


@pytest.mark.parametrize("name", sorted(_CAPS))
@pytest.mark.parametrize("angle", (0, 45, 90))
@pytest.mark.parametrize("rot", _GEOM_ROTATIONS)
def test_ink_is_centred_on_the_displayed_page_centre_at_every_angle(rot: int, angle: int, name: str) -> None:
    page = _geom_page(rot)
    apply_watermarks_to_page(page, [_wm(text=_CAPS[name], angle=angle)])
    _assert_ink_centred(page)


@pytest.mark.parametrize("angle,offset_x,offset_y", ((0, 60, -40), (45, 60, -40), (90, -50, 70)))
@pytest.mark.parametrize("rot", _GEOM_ROTATIONS)
def test_ink_centre_follows_the_requested_offsets_at_every_angle(
    rot: int, angle: int, offset_x: int, offset_y: int
) -> None:
    page = _geom_page(rot)
    apply_watermarks_to_page(page, [_wm(text=_CAPS["multi"], angle=angle, offset_x=offset_x, offset_y=offset_y)])
    _assert_ink_centred(page, offset_x, offset_y)


def test_dialog_default_angle_45_no_longer_lands_far_from_the_centre() -> None:
    """The reported symptom: 45 degrees put the ink about 80 pt from the page centre."""
    page = _geom_page(0)
    apply_watermarks_to_page(page, [_wm(text="WMARK TEST", angle=45)])
    # Round glyph corners skew the ink box by a few points; the defect was ~80 pt.
    _assert_ink_centred(page, tol=6)


def test_a_multi_line_block_is_centred_not_hanging_from_its_centre() -> None:
    """Three lines straddle the centre: the middle line's ink is centred on it."""
    page = _geom_page(0)
    apply_watermarks_to_page(page, [_wm(text="WMARK\nWMARK\nWMARK")])
    ys, xs = np.nonzero(_ink(page))
    rows = np.unique(ys)
    cy = page.rect.height / 2
    # Ink rows exist on both sides of the centre and the middle line covers it.
    assert rows.min() < cy - 30 and rows.max() > cy + 30
    assert (ys == int(cy)).any()
    _assert_ink_centred(page)


def test_overlay_save_and_print_paths_agree_on_the_corrected_geometry() -> None:
    """Live overlay (``WatermarkTool``), save clone and print helper draw the same ink."""
    from model.tools.watermark_tool import WatermarkTool
    from src.printing.helper_main import _build_snapshot_bytes

    wm = _wm(text=_CAPS["multi"], angle=45, offset_x=30, offset_y=20)
    direct = _geom_page(90)
    apply_watermarks_to_page(direct, [wm])

    overlay_doc = _page_doc(mb=(0, 0, 600, 800), rot=90)
    tool = WatermarkTool(model=None)  # type: ignore[arg-type]
    tool._watermarks_by_session["s"] = [wm]
    tool.apply_page_overlay("s", 1, overlay_doc[0], "view")

    save_doc = _page_doc(mb=(0, 0, 600, 800), rot=90)
    WatermarkTool.apply_watermarks_to_document(save_doc, [wm])

    src = _page_doc(mb=(0, 0, 600, 800), rot=90)
    printed = fitz.open("pdf", _build_snapshot_bytes(src.tobytes(), [wm]))

    want = _ink(direct)
    for label, page in (("overlay", overlay_doc[0]), ("save", save_doc[0]), ("print", printed[0])):
        assert np.array_equal(_ink(page), want), label
    _assert_ink_centred(direct, 30, 20)
