"""RED: the page→visual chain must survive rotated CROPPED and /UserUnit pages.

Production geometry maps text-space quads to VISUAL (pixmap) space through
``page.transformation_matrix × page.rotation_matrix``.  Both factors are
wrong on a rotated page whose ``/CropBox`` is offset or whose ``/UserUnit``
is not 1: PyMuPDF rebuilds ``transformation_matrix`` from the page size
alone when ``/Rotate != 0`` (dropping the CropBox origin AND ``/UserUnit``),
and ``rotation_matrix``/``derotation_matrix`` always drop ``/UserUnit`` and
use the UNCLIPPED CropBox dims.

Every assertion here is anchored to 72-dpi pixmap INK bounds (one device
pixel == one visual point at that dpi), never to ``rotation_matrix``
arithmetic — the thing under test must not be its own oracle.  The eight
shapes cross every axis that can go wrong (offset CropBox, CropBox
extending past the MediaBox, negative MediaBox origin, ``/UserUnit`` above
and below 1) with all four ``/Rotate`` values; ``E@180`` is the cell no
wrong formula passes.

Ground truth for the tables below was measured on PyMuPDF 1.27.1.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.pdf_text_edit import _dict_space_to_visual  # noqa: E402
from model.text_commit.inspect import _origin_in_page_space  # noqa: E402
from model.text_commit.plan import _grown_verify_bbox  # noqa: E402
from model.text_commit.transforms import (  # noqa: E402
    UnsupportedPageGeometryError,
    admission_verdict,
    combined_linear,
    map_text_quad_to_visual,
    page_visual_frame,
    read_user_unit,
    visual_baseline_direction,
)
from model.text_commit.verify import _visual_bbox_to_dict_space  # noqa: E402
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    first_show,
    set_page_boxes,
    set_user_unit,
)
from test_scripts.type0_fixture_builder import CJK_TEXT, Type0Fixture  # noqa: E402
from test_scripts.type0_fixture_builder import build_identity_h_fixture  # noqa: E402

ROTATIONS = (0, 90, 180, 270)

# shape -> (mediabox literal, cropbox literal, /UserUnit, authored origin).
# ``None`` means "leave the builder's own 595x842 MediaBox / no CropBox /
# no /UserUnit".  G's origin is inside its small CropBox so its glyphs
# still render; every other shape keeps the builder's (72, 700).
SHAPES: dict[str, tuple[tuple[float, ...] | None, tuple[float, ...] | None, float | None, tuple[float, float]]] = {
    "A": (None, None, None, (72.0, 700.0)),
    "B": ((0, 0, 595, 842), (50, 60, 545, 782), None, (72.0, 700.0)),
    "C": (None, None, 2, (72.0, 700.0)),
    "D": (None, (50, 60, 545, 782), 2, (72.0, 700.0)),
    "E": ((-100, -100, 495, 742), (50, 60, 545, 782), None, (72.0, 700.0)),
    "F": ((-100, -100, 495, 742), (50, 60, 545, 782), 2, (72.0, 700.0)),
    "G": (None, (100, 100, 300, 400), 0.5, (120.0, 200.0)),
    "H": ((0, 0, 595, 842), (-20, -30, 400, 900), 3, (72.0, 700.0)),
}

CELLS = [(shape, rotation) for shape in SHAPES for rotation in ROTATIONS]

FONT_SIZE = 12.0
GLYPH_COUNT = 4  # the builder's four full-width CJK chars, 1 em each


@pytest.fixture(autouse=True)
def _font_metric_bboxes():
    """Pin PyMuPDF's process-global ``small_glyph_heights`` to OFF.

    ``PDFModel.__init__`` flips that flag to ``True`` for the rest of a
    single-process suite (see PITFALLS, "PDFModel.__init__ flips PyMuPDF's
    process-global small_glyph_heights"), and with it on MuPDF reports a
    *tight* fontsize-tall span bbox that deliberately sits INSIDE the
    rendered ink — on shape H (``/UserUnit 3``) the sub-point difference is
    magnified to 1.3 visual pt and breaks the ink-containment oracle these
    cells are anchored on.  The flag never touches the frame arithmetic
    under test; ``test_dict_visual_round_trip_is_flag_independent`` covers
    the app's own (flag-on) configuration.
    """
    prior = bool(fitz.TOOLS.set_small_glyph_heights())
    fitz.TOOLS.set_small_glyph_heights(False)
    try:
        yield
    finally:
        fitz.TOOLS.set_small_glyph_heights(prior)


def build_shape(shape: str, rotation: int) -> Type0Fixture:
    """One fixture page in the named shape at ``rotation``.

    ``/Rotate`` is written with ``xref_set_key`` rather than
    ``Page.set_rotation`` so nothing here depends on the rotation-0 window
    that permanently dirties a document.
    """
    mediabox, cropbox, user_unit, origin = SHAPES[shape]
    fixture = build_identity_h_fixture(origin=origin)
    if mediabox is not None or cropbox is not None:
        set_page_boxes(fixture, mediabox=mediabox, cropbox=cropbox)
    if user_unit is not None:
        set_user_unit(fixture, user_unit)
    if rotation:
        fixture.doc.xref_set_key(fixture.page.xref, "Rotate", str(rotation))
    assert fixture.page.rotation == rotation, "fixture: /Rotate did not take"
    return fixture


def ink_bbox(page: fitz.Page) -> tuple[int, int, int, int]:
    """Dark-pixel bounds of the whole page at 72 dpi == visual points."""
    pix = page.get_pixmap(dpi=72, colorspace=fitz.csGRAY, alpha=False)
    table = bytes(1 if value < 200 else 0 for value in range(256))
    packed = bytes(pix.samples).translate(table)
    width, height = pix.width, pix.height
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        row = packed[y * width : (y + 1) * width]
        if 1 not in row:
            continue
        ys.append(y)
        xs.append(row.index(1))
        xs.append(width - 1 - row[::-1].index(1))
    assert xs, "fixture rendered no ink"
    irect = tuple(pix.irect)
    return (
        irect[0] + min(xs),
        irect[1] + min(ys),
        irect[0] + max(xs) + 1,
        irect[1] + max(ys) + 1,
    )


_INK_CACHE: dict[tuple[str, int], tuple[int, int, int, int]] = {}


def cell_ink(shape: str, rotation: int) -> tuple[int, int, int, int]:
    """Cached ink bounds for one cell (rendering 32 pages twice is slow)."""
    key = (shape, rotation)
    cached = _INK_CACHE.get(key)
    if cached is None:
        fixture = build_shape(shape, rotation)
        try:
            cached = ink_bbox(fixture.doc[0])
        finally:
            fixture.doc.close()
        _INK_CACHE[key] = cached
    return cached


def metric_quad() -> tuple[float, float, float, float]:
    """The planner's own text-space metric quad for the fixture show."""
    return (0.0, -0.35 * FONT_SIZE, GLYPH_COUNT * FONT_SIZE, FONT_SIZE)


# --------------------------------------------------------- /UserUnit


USER_UNIT_CASES = [
    # (label, literal or None for absent, expected user_unit)
    ("absent", None, 1.0),
    ("int", "2", 2.0),
    ("real", "2.0", 2.0),
    ("indirect", "INDIRECT", 2.0),
    ("zero", "0", 0.0),
    ("negative", "-2", -2.0),
    ("negative real", "-2.5", -2.5),
    ("sub unit", "0.5", 0.5),
    ("name", "/Foo", 1.0),
    ("string", "(2)", 1.0),
    ("bool", "true", 1.0),
    ("array", "[2]", 1.0),
    # Exponent notation is NOT PDF number syntax: MuPDF's lexer refuses the
    # whole key, so the page reads as if /UserUnit were absent.
    ("exponent", "1e30", 1.0),
]


@pytest.mark.parametrize(
    ("label", "literal", "expected"),
    USER_UNIT_CASES,
    ids=[case[0] for case in USER_UNIT_CASES],
)
def test_user_unit_semantics_mirror_mupdf(label, literal, expected):
    """``read_user_unit`` is exactly the factor MuPDF applies.

    MEASURED (1.27.1): any PDF *number* — including ``0`` and negatives —
    is applied verbatim; every non-number value (name, string, boolean,
    array, absent, unlexable) reads as 1.  ``page.transformation_matrix``
    at rotation 0 is the definition of the base matrix, so it is also the
    self-check: a reader that clamps, rejects or coerces differently from
    MuPDF fails here rather than silently misplacing a halo.

    The READER mirrors MuPDF including the pathological values; the FRAME
    refuses them (a zero or mirrored page has no usable visual geometry) —
    ``test_text_commit_page_geometry_gate.py`` owns that half.
    """
    fixture = build_identity_h_fixture()
    try:
        doc = fixture.doc
        if literal == "INDIRECT":
            xref = doc.get_new_xref()
            doc.update_object(xref, "2")
            doc.xref_set_key(fixture.page.xref, "UserUnit", f"{xref} 0 R")
        elif literal is not None:
            doc.xref_set_key(fixture.page.xref, "UserUnit", literal)
        page = doc[0]
        assert read_user_unit(doc, page.xref) == pytest.approx(expected), label
        if expected <= 0.0:
            with pytest.raises(UnsupportedPageGeometryError):
                page_visual_frame(page)
            return
        frame = page_visual_frame(page)
        assert frame.user_unit == pytest.approx(expected), label
        assert tuple(frame.base) == tuple(page.transformation_matrix), label
        assert tuple(frame.visual) == tuple(frame.base), "rotation 0 is base"
    finally:
        fixture.doc.close()


def test_indirect_user_unit_pointing_at_a_non_number_reads_as_one():
    """An indirect reference is resolved, then judged as a number or not."""
    for literal, expected in (("(2)", 1.0), ("/Foo", 1.0), ("2.5", 2.5)):
        fixture = build_identity_h_fixture()
        try:
            doc = fixture.doc
            xref = doc.get_new_xref()
            doc.update_object(xref, literal)
            doc.xref_set_key(fixture.page.xref, "UserUnit", f"{xref} 0 R")
            page = doc[0]
            frame = page_visual_frame(page)
            assert frame.user_unit == pytest.approx(expected), literal
            assert tuple(frame.base) == tuple(page.transformation_matrix), literal
        finally:
            fixture.doc.close()


# ------------------------------------------------- base == MuPDF at rot 0


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_base_is_mupdfs_rotation_zero_transformation_matrix(shape):
    """The self-check: at ``/Rotate 0`` MuPDF's own matrix IS the base."""
    fixture = build_shape(shape, 0)
    try:
        page = fixture.doc[0]
        frame = page_visual_frame(page)
        assert tuple(frame.base) == tuple(page.transformation_matrix), shape
        assert frame.rotation == 0
        assert (frame.width0, frame.height0) == (
            pytest.approx(page.rect.width),
            pytest.approx(page.rect.height),
        )
    finally:
        fixture.doc.close()


def _edge_shape_docs():
    """Four page shapes whose box DICTIONARIES are off-nominal."""
    # 1. Reversed box literals (legal: a rectangle is two opposite corners).
    fixture = build_identity_h_fixture()
    set_page_boxes(fixture, mediabox=(595, 842, 0, 0), cropbox=(545, 782, 50, 60))
    yield "reversed literals", fixture

    # 2. Boxes inherited from /Pages with the page's own keys nulled.
    fixture = build_identity_h_fixture()
    doc = fixture.doc
    page_xref = fixture.page.xref
    _, parent = doc.xref_get_key(page_xref, "Parent")
    parent_xref = int(parent.split()[0])
    doc.xref_set_key(parent_xref, "MediaBox", "[0 0 595 842]")
    doc.xref_set_key(parent_xref, "CropBox", "[50 60 545 782]")
    doc.xref_set_key(page_xref, "MediaBox", "null")
    doc.xref_set_key(page_xref, "CropBox", "null")
    yield "inherited boxes", fixture

    # 3. Indirect /UserUnit on an offset CropBox.
    fixture = build_identity_h_fixture()
    set_page_boxes(fixture, cropbox=(50, 60, 545, 782))
    xref = fixture.doc.get_new_xref()
    fixture.doc.update_object(xref, "2")
    fixture.doc.xref_set_key(fixture.page.xref, "UserUnit", f"{xref} 0 R")
    yield "indirect user unit", fixture

    # 4. No /CropBox at all, non-zero MediaBox origin.
    fixture = build_identity_h_fixture()
    set_page_boxes(fixture, mediabox=(-100, -100, 495, 742))
    yield "no cropbox", fixture


def test_edge_page_shapes_still_reproduce_mupdfs_base_matrix():
    """Reversed literals, inheritance, indirect /UserUnit, absent CropBox."""
    for label, fixture in _edge_shape_docs():
        try:
            page = fixture.doc[0]
            frame = page_visual_frame(page)
            assert tuple(frame.base) == tuple(page.transformation_matrix), label
        finally:
            fixture.doc.close()


def test_cropbox_is_reported_y_flipped_against_the_mediabox_and_unclipped():
    """The premise the base matrix is reconstructed from.

    MEASURED: with MediaBox ``[-100 -100 495 742]`` and CropBox
    ``[50 60 545 782]``, ``page.cropbox`` reads ``(50, -40, 545, 682)`` —
    y flipped against ``mediabox.y1`` and NOT clipped to the MediaBox
    (``x1 == 545 > 495``).  Un-flipping and intersecting is what
    :func:`page_visual_frame` must do.
    """
    fixture = build_shape("E", 0)
    try:
        page = fixture.doc[0]
        assert tuple(page.mediabox) == (-100.0, -100.0, 495.0, 742.0)
        assert tuple(page.cropbox) == (50.0, -40.0, 545.0, 682.0)
        assert tuple(page.rect) == (0.0, 0.0, 445.0, 682.0)
    finally:
        fixture.doc.close()
    fixture = build_shape("H", 0)
    try:
        page = fixture.doc[0]
        assert tuple(page.cropbox) == (-20.0, -58.0, 400.0, 872.0)
        assert tuple(page.rect) == (0.0, 0.0, 1200.0, 2526.0)
    finally:
        fixture.doc.close()


# ------------------------------------------------------- the 32-cell table


@pytest.mark.parametrize(
    ("shape", "rotation"), CELLS, ids=[f"{s}@{r}" for s, r in CELLS]
)
def test_visual_quad_covers_the_rendered_ink(shape, rotation):
    """``map_text_quad_to_visual`` of the show's metric quad must land on
    the ink — covering it, and not by more than the metric heuristic's own
    margin (scaled by ``/UserUnit``, since visual points are)."""
    fixture = build_shape(shape, rotation)
    try:
        page = fixture.doc[0]
        show = first_show(fixture)
        bounds = map_text_quad_to_visual(page, show.tm, show.ctm, metric_quad())
        ink = cell_ink(shape, rotation)
        scale = abs(page_visual_frame(page).user_unit)
        slack = 4.0 * scale
        assert bounds[0] <= ink[0] + 1.0, (bounds, ink)
        assert bounds[1] <= ink[1] + 1.0, (bounds, ink)
        assert bounds[2] >= ink[2] - 1.0, (bounds, ink)
        assert bounds[3] >= ink[3] - 1.0, (bounds, ink)
        assert bounds[0] >= ink[0] - slack, (bounds, ink)
        assert bounds[1] >= ink[1] - slack, (bounds, ink)
        assert bounds[2] <= ink[2] + slack, (bounds, ink)
        assert bounds[3] <= ink[3] + slack, (bounds, ink)
    finally:
        fixture.doc.close()


@pytest.mark.parametrize(
    ("shape", "rotation"), CELLS, ids=[f"{s}@{r}" for s, r in CELLS]
)
def test_origin_in_page_space_lands_on_the_ink(shape, rotation):
    """``inspect._origin_in_page_space`` maps the show's user-space origin
    to the baseline corner of the rendered ink."""
    fixture = build_shape(shape, rotation)
    try:
        page = fixture.doc[0]
        show = first_show(fixture)
        x, y = _origin_in_page_space(page, show)
        ink = cell_ink(shape, rotation)
        slack = 2.0 * abs(page_visual_frame(page).user_unit)
        assert ink[0] - slack <= x <= ink[2] + slack, ((x, y), ink)
        assert ink[1] - slack <= y <= ink[3] + slack, ((x, y), ink)
    finally:
        fixture.doc.close()


def test_shape_e_at_180_is_the_discriminating_cell():
    """MediaBox ``[-100 -100 495 742]`` + CropBox ``[50 60 545 782]`` at
    ``/Rotate 180``: the legacy ``transformation_matrix × rotation_matrix``
    chain misses the ink by 56 pt vertically, the frame lands on it.

    MEASURED ink ``(376, 639, 423, 650)``; legacy chain
    ``(375.0, 695.8, 423.0, 712.0)``.
    """
    fixture = build_shape("E", 180)
    try:
        page = fixture.doc[0]
        show = first_show(fixture)
        ink = cell_ink("E", 180)
        assert ink == (376, 639, 423, 650)
        bounds = map_text_quad_to_visual(page, show.tm, show.ctm, metric_quad())
        assert bounds[1] <= ink[1] + 1.0 and bounds[3] >= ink[3] - 1.0, bounds
        legacy = page.transformation_matrix * page.rotation_matrix
        legacy_bounds = (
            fitz.Rect(72.0, 700.0 - 0.35 * FONT_SIZE, 72.0 + 48.0, 700.0 + FONT_SIZE)
            * legacy
        ).normalize()
        assert legacy_bounds.y0 > ink[3], (
            "premise: the legacy chain must MISS this cell",
            tuple(legacy_bounds),
            ink,
        )
    finally:
        fixture.doc.close()


# --------------------------------------------------- dict <-> visual pair


@pytest.mark.parametrize(
    ("shape", "rotation"), CELLS, ids=[f"{s}@{r}" for s, r in CELLS]
)
def test_dict_visual_round_trip_is_identity_and_lands_on_the_ink(shape, rotation):
    """``get_text`` geometry is BASE space on every rotation (MEASURED: the
    span origin is constant across /Rotate).  The write-side
    ``_dict_space_to_visual`` and the read-side ``_visual_bbox_to_dict_space``
    must be exact inverses, and the visual half must hit the ink."""
    fixture = build_shape(shape, rotation)
    try:
        page = fixture.doc[0]
        span = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        dict_bbox = fitz.Rect(*span["bbox"])
        dict_origin = fitz.Point(*span["origin"])
        origin_visual, bbox_visual = _dict_space_to_visual(
            page, dict_origin, dict_bbox
        )
        ink = cell_ink(shape, rotation)
        assert bbox_visual.x0 <= ink[0] + 1.0, (tuple(bbox_visual), ink)
        assert bbox_visual.y0 <= ink[1] + 1.0, (tuple(bbox_visual), ink)
        assert bbox_visual.x1 >= ink[2] - 1.0, (tuple(bbox_visual), ink)
        assert bbox_visual.y1 >= ink[3] - 1.0, (tuple(bbox_visual), ink)
        slack = 2.0 * abs(page_visual_frame(page).user_unit)
        assert ink[0] - slack <= origin_visual.x <= ink[2] + slack
        assert ink[1] - slack <= origin_visual.y <= ink[3] + slack
        back = _visual_bbox_to_dict_space(page, tuple(bbox_visual))
        # fitz.Matrix arithmetic is float32: 1e-3 pt is its round-trip floor.
        assert back == pytest.approx(tuple(dict_bbox), abs=1e-3)
    finally:
        fixture.doc.close()


def test_dict_visual_round_trip_is_flag_independent():
    """The dict<->visual pair is pure geometry: it must round-trip in the
    app's own configuration too, where ``PDFModel`` has flipped the
    process-global ``small_glyph_heights``.  Only the ink-containment
    oracle of the cell above depends on that flag (MuPDF then reports a
    tight box inside the ink); the mapping itself must not."""
    prior = bool(fitz.TOOLS.set_small_glyph_heights())
    fitz.TOOLS.set_small_glyph_heights(True)
    try:
        for shape, rotation in CELLS:
            fixture = build_shape(shape, rotation)
            try:
                page = fixture.doc[0]
                span = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
                dict_bbox = fitz.Rect(*span["bbox"])
                _, bbox_visual = _dict_space_to_visual(
                    page, fitz.Point(*span["origin"]), dict_bbox
                )
                back = _visual_bbox_to_dict_space(page, tuple(bbox_visual))
                assert back == pytest.approx(tuple(dict_bbox), abs=1e-3), (
                    shape,
                    rotation,
                )
            finally:
                fixture.doc.close()
    finally:
        fitz.TOOLS.set_small_glyph_heights(prior)


# --------------------------------------------------- grown verify band


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_grown_verify_band_carries_the_user_unit(rotation):
    """Shape F (offset CropBox past the MediaBox, ``/UserUnit 2``): the
    growth band is ``growth_advance × |Tm×CTM linear| × /UserUnit`` visual
    points wide, whatever the rotation.  Under the legacy chain the band
    loses the ``/UserUnit`` factor on a rotated page — a HALF-WIDTH growth
    zone, the false-ACCEPT direction."""
    fixture = build_shape("F", rotation)
    try:
        page = fixture.doc[0]
        show = first_show(fixture)
        frame = page_visual_frame(page)
        target = map_text_quad_to_visual(page, show.tm, show.ctm, metric_quad())
        growth = 10.0
        grown = _grown_verify_bbox(page, show, target, growth)
        norm = math.hypot(*combined_linear(show.tm, show.ctm)[:2])
        expected = growth * norm * abs(frame.user_unit)
        assert expected == pytest.approx(20.0), "fixture: unit Tm at /UserUnit 2"
        band_x = (grown[2] - grown[0]) - (target[2] - target[0])
        band_y = (grown[3] - grown[1]) - (target[3] - target[1])
        assert band_x + band_y == pytest.approx(expected, abs=1e-3)
        assert min(band_x, band_y) == pytest.approx(0.0, abs=1e-3)
        assert _grown_verify_bbox(page, show, target, 0.0) == target
    finally:
        fixture.doc.close()


# ------------------------------------------------------------- premises


def test_rotated_page_matrices_disagree_with_the_frame():
    """Premise pins for shape F at 90: BOTH PyMuPDF factors are wrong.

    ``transformation_matrix`` collapses to the unclipped page size and
    ``rotation_matrix`` uses the UNCLIPPED CropBox dims without
    ``/UserUnit`` — so neither may be used to derive the other half.
    """
    fixture = build_shape("F", 90)
    try:
        page = fixture.doc[0]
        frame = page_visual_frame(page)
        assert tuple(page.transformation_matrix) != tuple(frame.base)
        assert tuple(page.rotation_matrix) != tuple(frame.quarter_turn)
        assert tuple(page.transformation_matrix * page.rotation_matrix) != tuple(
            frame.visual
        )
    finally:
        fixture.doc.close()


def test_unrotated_and_uncropped_pages_keep_the_legacy_chain_bit_identical():
    """Compatibility: the frame must not move geometry on the shapes the
    engine has always handled — every shape at rotation 0, and the plain
    page at every rotation."""
    for shape in sorted(SHAPES):
        fixture = build_shape(shape, 0)
        try:
            page = fixture.doc[0]
            legacy = page.transformation_matrix * page.rotation_matrix
            assert tuple(page_visual_frame(page).visual) == tuple(legacy), shape
        finally:
            fixture.doc.close()
    for rotation in ROTATIONS:
        fixture = build_shape("A", rotation)
        try:
            page = fixture.doc[0]
            legacy = page.transformation_matrix * page.rotation_matrix
            assert tuple(page_visual_frame(page).visual) == tuple(legacy), rotation
        finally:
            fixture.doc.close()


def test_page_visual_frame_never_dirties_the_document():
    """The frame is COMPUTED, never captured: no ``set_rotation(0)`` window
    (which permanently flips ``doc.is_dirty`` on a clean document)."""
    fixture = build_identity_h_fixture()
    try:
        doc = fixture.doc
        assert doc.is_dirty is False, "fixture: fresh document is not clean"
        page = doc[0]
        frame = page_visual_frame(page)
        assert doc.is_dirty is False
        show = first_show(fixture)
        map_text_quad_to_visual(page, show.tm, show.ctm, metric_quad(), frame=frame)
        _origin_in_page_space(page, show)
        assert doc.is_dirty is False
    finally:
        fixture.doc.close()


def test_map_text_quad_to_visual_accepts_a_precomputed_frame():
    """The per-prepare frame kwarg must be an optimisation, not a variant:
    the default (page-derived) and the passed frame agree bit for bit."""
    fixture = build_shape("F", 270)
    try:
        page = fixture.doc[0]
        show = first_show(fixture)
        frame = page_visual_frame(page)
        assert map_text_quad_to_visual(
            page, show.tm, show.ctm, metric_quad(), frame=frame
        ) == map_text_quad_to_visual(page, show.tm, show.ctm, metric_quad())
    finally:
        fixture.doc.close()


# -------------------------------------------- visual baseline direction


def _ink_growth_direction(shape: str, rotation: int) -> str:
    """The direction the run GROWS on screen, from the RENDERER alone.

    One glyph vs four at the same authored origin: the edge of the ink box
    that moved is the visual baseline direction.  Never consults a page
    matrix, so it is a valid oracle for the classifier under test.
    """
    inks = []
    for text in (CJK_TEXT[:1], CJK_TEXT):
        mediabox, cropbox, user_unit, origin = SHAPES[shape]
        fixture = build_identity_h_fixture(text=text, origin=origin)
        try:
            if mediabox is not None or cropbox is not None:
                set_page_boxes(fixture, mediabox=mediabox, cropbox=cropbox)
            if user_unit is not None:
                set_user_unit(fixture, user_unit)
            if rotation:
                fixture.doc.xref_set_key(fixture.page.xref, "Rotate", str(rotation))
            inks.append(ink_bbox(fixture.doc[0]))
        finally:
            fixture.doc.close()
    one, four = inks
    moved = (
        ("right", four[2] - one[2]),
        ("left", one[0] - four[0]),
        ("down", four[3] - one[3]),
        ("up", one[1] - four[1]),
    )
    best = max(moved, key=lambda pair: pair[1])
    assert best[1] > 0, (shape, rotation, moved)
    return best[0]


@pytest.mark.parametrize(
    ("shape", "rotation"), CELLS, ids=[f"{s}@{r}" for s, r in CELLS]
)
def test_visual_baseline_direction_matches_the_rendered_run(shape, rotation):
    """PREMISE PIN, not new red coverage: for a positive ``/UserUnit`` the
    legacy ``transformation_matrix x rotation_matrix`` chain and the frame
    differ only by a positive uniform scale, so the classified direction was
    already right on all 32 cells (MEASURED 32/32 both ways).  Routing the
    classifier through the frame must PRESERVE that -- this cell is the
    renderer-anchored proof it did."""
    fixture = build_shape(shape, rotation)
    try:
        page = fixture.doc[0]
        show = first_show(fixture)
        linear = combined_linear(show.tm, show.ctm)
        assert visual_baseline_direction(page, linear) == _ink_growth_direction(
            shape, rotation
        )
    finally:
        fixture.doc.close()


def test_visual_baseline_direction_follows_the_passed_frame_not_the_page():
    """RED: the classifier must read the FRAME, never the page's own
    matrices.

    A page at ``/Rotate 0`` classified against a frame built from the SAME
    boxes at ``/Rotate 90`` must answer ``down`` -- the frame's rotation.
    Under the legacy chain the page's own (unrotated) matrices win and the
    answer stays ``right``, so this cell dies the moment anyone reintroduces
    ``page.transformation_matrix * page.rotation_matrix`` here.
    """
    flat = build_shape("F", 0)
    turned = build_shape("F", 90)
    try:
        page = flat.doc[0]
        show = first_show(flat)
        linear = combined_linear(show.tm, show.ctm)
        rotated_frame = page_visual_frame(turned.doc[0])
        assert visual_baseline_direction(page, linear) == "right"
        assert (
            visual_baseline_direction(page, linear, frame=rotated_frame) == "down"
        )
    finally:
        flat.doc.close()
        turned.doc.close()


def test_admission_verdict_threads_the_frame_through():
    """``admission_verdict`` is the production entry point; it must accept
    the per-prepare frame and hand it to the direction classifier rather
    than re-deriving (or worse, re-deriving from the page matrices)."""
    flat = build_shape("F", 0)
    turned = build_shape("F", 90)
    try:
        page = flat.doc[0]
        show = first_show(flat)
        rotated_frame = page_visual_frame(turned.doc[0])
        assert admission_verdict(page, show.tm, show.ctm).direction == "right"
        assert (
            admission_verdict(
                page, show.tm, show.ctm, frame=rotated_frame
            ).direction
            == "down"
        )
    finally:
        flat.doc.close()
        turned.doc.close()


@pytest.mark.parametrize(
    ("shape", "rotation"), CELLS, ids=[f"{s}@{r}" for s, r in CELLS]
)
def test_admission_direction_is_bit_identical_with_and_without_the_frame(
    shape, rotation
):
    """The frame kwarg is an optimisation, not a variant (shapes A-H)."""
    fixture = build_shape(shape, rotation)
    try:
        page = fixture.doc[0]
        show = first_show(fixture)
        frame = page_visual_frame(page)
        assert (
            admission_verdict(page, show.tm, show.ctm, frame=frame)
            == admission_verdict(page, show.tm, show.ctm)
        )
    finally:
        fixture.doc.close()


def test_frame_inverse_round_trips_user_space():
    """``frame.inverse`` is the visual→user inverse ``_grown_verify_bbox``
    rides; ``quarter_turn`` is the dict→visual half."""
    fixture = build_shape("H", 90)
    try:
        page = fixture.doc[0]
        frame = page_visual_frame(page)
        point = fitz.Point(72.0, 700.0)
        assert tuple(point * frame.visual * frame.inverse) == pytest.approx(
            tuple(point), abs=1e-3
        )
        assert tuple(frame.base * frame.quarter_turn) == pytest.approx(
            tuple(frame.visual), abs=1e-9
        )
    finally:
        fixture.doc.close()
