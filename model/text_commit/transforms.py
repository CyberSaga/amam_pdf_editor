"""Production TRM classifier — the single source for rotated-text geometry.

Task 13 Priority 2: classifies the combined ``Tm × CTM`` linear map of a
show operator into a fail-closed admission verdict, and maps text-space
geometry into visual space along the SAME chain the raster verifier's
pixmaps use (row vectors, visual y down).  Task 15 P4-B2 slice 2 made that
chain :class:`PageVisualFrame` — computed arithmetic, correct on rotated
CROPPED and ``/UserUnit`` pages where BOTH of PyMuPDF's own page matrices
are wrong — and this module is its single source.

The v1 scope is the census-locked quarter-turn family: positive-orientation
uniform rotation+scale whose visual baseline direction is cardinal.  Every
other shape keeps its own stable :class:`~model.text_commit.dto.RejectReason`
code, attributed by a FIXED gate precedence so telemetry can never drift:

    finite → non-singular determinant → absolute scale floor →
    positive orientation → orthogonal axes → equal axis norms →
    cardinal visual direction

Plan section 2.C (2026-09-29) separates "reflected" from "degenerate": a
negative-orientation matrix that passes every OTHER gate (the same
finite / ``|det|`` / floor / orthogonality / equal-norm proofs, see
``shape_reject_reason(allow_reflection=True)``) and has a cardinal visual
baseline is admitted by :func:`admission_verdict` with ``reflected=True``
-- but only when the caller PROVES a fill-only render mode.  The code a
refused mirror carries is still ``trm_reflected`` (the precedence above is
unchanged); the planner additionally holds an admitted mirror to Tier 0's
exact equal-advance splice (``trm_reflected_advance_change`` otherwise).
The original matrix signs are never rewritten: the splice replaces one
string operand, so ``Tm``/``cm`` bytes survive untouched.

Shared by replay/inspect/plan/verify; the census tooling
(``scripts/trm_taxonomy.py``) delegates to this module — this module must
never import ``scripts/`` (pinned by tests).  Contract pinned verbatim by
``test_scripts/test_text_commit_trm_admission.py``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import fitz

from model.text_commit.dto import RejectReason

Matrix = tuple[float, float, float, float, float, float]
Linear = tuple[float, float, float, float]

# Relative, not absolute: a rotation reconstructed through float math at
# scale 1000 carries proportionally larger component noise than one at
# scale 0.01, and both must classify identically.
REL_TOL = 1e-6
# Absolute, not relative: mirrors replay._uniform_scale's ``a <= _EPS``
# floor — a degenerate baseline scale has no defensible advance geometry
# no matter how "relatively clean" the matrix is.  Closed boundary
# (exactly the floor rejects).
ABS_SCALE_FLOOR = 1e-6

DIRECTION_RIGHT = "right"
DIRECTION_LEFT = "left"
DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_OBLIQUE = "oblique"
DIRECTION_DEGENERATE = "degenerate"

CARDINAL_DIRECTIONS = frozenset(
    {DIRECTION_RIGHT, DIRECTION_LEFT, DIRECTION_UP, DIRECTION_DOWN}
)


# PDF number syntax (ISO 32000-1 7.3.3): an optional sign, digits and at
# most one decimal point.  Exponent notation is NOT a PDF number, and
# MuPDF's lexer refuses the whole key rather than reading a prefix —
# ``/UserUnit 1e30`` therefore behaves exactly like an absent key
# (MEASURED, 1.27.1).
_PDF_NUMBER_RE = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$")
_NUMERIC_KEY_KINDS = frozenset({"int", "float"})

# Bound on the /Pages chain walked for an inherited key — a malformed
# document can point /Parent at itself, and a geometry reader must not hang.
_MAX_PAGE_TREE_DEPTH = 32

_IDENTITY_MATRIX = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Relative agreement required between the frame's own page box and the one
# MuPDF renders.  Both are built from the same box literals, so anything
# beyond float32 matrix noise means the reconstruction lost the page.
_FRAME_DIMS_REL_TOL = 1e-6


class UnsupportedPageGeometryError(ValueError):
    """The page's visual frame cannot be PROVEN against what MuPDF renders.

    Raised by :func:`page_visual_frame` when the arithmetic reconstruction
    and ``page.rect`` disagree (a ``/CropBox`` that does not intersect the
    ``/MediaBox`` leaves an empty clip while MuPDF substitutes a 612x792
    fallback page — MEASURED), when ``/UserUnit`` is not a usable positive
    finite scale (``0`` collapses the page to a point, a negative one
    mirrors it), or when the ``/Rotate`` in force is not an exact quarter
    turn (MuPDF renders those at the NEAREST quarter turn while
    ``page.rotation`` reports 0).  Every consumer converts this into its own layer's
    fail-closed refusal — ``PlanRejection`` /
    :data:`~model.text_commit.dto.RejectReason.PAGE_GEOMETRY_UNSUPPORTED`,
    ``BindingFailure``, ``VerificationFailure``, or ``None`` — so it never
    reaches the UI as an exception.
    """


def _pdf_number_key(doc: fitz.Document, xref: int, key: str) -> float | None:
    """``key``'s value on object ``xref`` when it is a PDF *number*.

    ``None`` for every value that is not one: absent, name, string,
    boolean, array, or unlexable.  One indirect hop is resolved and the
    resolved object is judged the same way.
    """
    try:
        kind, value = doc.xref_get_key(xref, key)
        if kind == "xref":
            value = doc.xref_object(int(value.split()[0]))
        elif kind not in _NUMERIC_KEY_KINDS:
            return None
    except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
        return None
    text = value.strip()
    if not _PDF_NUMBER_RE.match(text):
        return None
    try:
        return float(text)
    except (ValueError, OverflowError):  # pragma: no cover - regex-guarded
        return None


def read_user_unit(doc: fitz.Document, page_xref: int) -> float:
    """The ``/UserUnit`` factor MuPDF applies to this page's geometry.

    MEASURED (PyMuPDF 1.27.1): every PDF *number* is applied verbatim —
    including ``0`` (which collapses the page to a point) and negatives
    (which mirror it); every value that is not a number (absent, name,
    string, boolean, array, or unlexable) reads as ``1``.  One indirect
    hop is resolved, and the resolved object is judged as a number in the
    same way.  ``/UserUnit`` is NOT inheritable, so the page dict is the
    only place to look.

    This mirrors MuPDF including the pathological values; refusing them is
    :func:`page_visual_frame`'s job, not the reader's.

    Deliberately NOT shared with ``inspect._update_page_geometry``: that
    reader folds the raw ``kind:value`` pair for non-numeric values
    (identity, not geometry) and ``inspect`` imports this module, so the
    dependency could only run the other way.
    """
    value = _pdf_number_key(doc, page_xref, "UserUnit")
    return 1.0 if value is None else value


def read_rotate_literal(doc: fitz.Document, page_xref: int) -> float:
    """The ``/Rotate`` NUMBER in force for this page, inheritance included.

    ``page.rotation`` cannot be used for this: MEASURED (1.27.1), MuPDF
    rounds a non-quarter-turn ``/Rotate`` to the nearest quarter turn when
    it RENDERS (``/Rotate 45`` and ``/Rotate 135`` place ink exactly where
    ``90`` and ``180`` do) while ``page.rotation`` and
    ``page.rotation_matrix`` both report ``0`` for every such value — so a
    page can render rotated 180 degrees while every Python-level rotation
    accessor says it is upright.  ``/Rotate`` IS inheritable (an inherited
    ``135`` reproduces the same trap), so the ``/Parent`` chain is walked
    until a number is found.  ``0.0`` when the chain ends without one (the
    PDF default); ``nan`` when the chain is longer than
    :data:`_MAX_PAGE_TREE_DEPTH` — a cycle or an absurd page tree, where
    "no ``/Rotate`` found" would be a guess, and ``nan`` refuses.
    """
    xref = page_xref
    for _ in range(_MAX_PAGE_TREE_DEPTH):
        value = _pdf_number_key(doc, xref, "Rotate")
        if value is not None:
            return value
        try:
            kind, parent = doc.xref_get_key(xref, "Parent")
            if kind != "xref":
                return 0.0
            xref = int(parent.split()[0])
        except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
            return 0.0
    return math.nan


@dataclass(frozen=True)
class PageVisualFrame:
    """One page's user-space → VISUAL (pixmap) space transform, computed.

    ``base`` is the rotation-0 half — the ``/UserUnit`` scale, the y flip
    and the clipped CropBox origin — and is by definition what
    ``page.transformation_matrix`` returns on an UNROTATED page (pinned by
    ``test_text_commit_visual_frame.py``).  ``quarter_turn`` is the plain
    ``/Rotate`` term over the base-space page box ``(width0, height0)``.

    Neither PyMuPDF factor may be used on a rotated page: MEASURED (1.27.1)
    ``page.transformation_matrix`` collapses to ``(1, 0, 0, -1, 0, H)`` when
    ``/Rotate != 0`` (dropping the CropBox origin AND ``/UserUnit``), and
    ``page.rotation_matrix`` / ``page.derotation_matrix`` always drop
    ``/UserUnit`` and size themselves from the UNCLIPPED CropBox.  The frame
    is arithmetic, never captured through a ``set_rotation(0)`` window: that
    window permanently flips ``doc.is_dirty`` on a clean document.
    """

    base: fitz.Matrix
    rotation: int
    width0: float
    height0: float
    user_unit: float

    @property
    def quarter_turn(self) -> fitz.Matrix:
        """The ``/Rotate`` term alone — the dict-space → visual-space map.

        ``page.get_text('dict'/'rawdict')`` geometry IS base space on every
        rotation (MEASURED: a span's ``origin`` is identical at 0/90/180/270
        and carries the CropBox flip and ``/UserUnit``), so this matrix and
        its inverse are the whole dict↔visual conversion.
        """
        if self.rotation == 90:
            return fitz.Matrix(0.0, 1.0, -1.0, 0.0, self.height0, 0.0)
        if self.rotation == 180:
            return fitz.Matrix(-1.0, 0.0, 0.0, -1.0, self.width0, self.height0)
        if self.rotation == 270:
            return fitz.Matrix(0.0, -1.0, 1.0, 0.0, 0.0, self.width0)
        return fitz.Matrix(*_IDENTITY_MATRIX)

    @property
    def visual(self) -> fitz.Matrix:
        """User space → visual space: ``base × quarter_turn``."""
        return self.base * self.quarter_turn

    @property
    def inverse(self) -> fitz.Matrix:
        """Visual space → user space."""
        return ~self.visual


def page_visual_frame(page: fitz.Page) -> PageVisualFrame:
    """Derive :class:`PageVisualFrame` from the page's own dictionaries.

    ``page.cropbox`` is reported y-flipped against ``mediabox.y1`` and
    UNCLIPPED (MEASURED), so it is un-flipped back into PDF user space and
    intersected with the MediaBox — that intersection is the box MuPDF
    actually renders, and the box every visual coordinate is relative to.

    Raises :class:`UnsupportedPageGeometryError` when the reconstruction
    cannot be PROVEN: the ``/Rotate`` in force must be an exact quarter
    turn, the ``/UserUnit`` must be a finite positive scale, and the
    reconstructed page box must equal ``page.rect`` (swapped for the
    quarter turns) — the one independent witness of the box MuPDF actually
    renders.  On the shapes that fail that box check (an empty clipped
    CropBox, a zero ``/UserUnit``) MuPDF renders NO INK AT ALL (MEASURED),
    so its fallback page cannot be mirrored against any ink oracle either;
    a refusal is the only provable answer.
    """
    document = page.parent
    user_unit = 1.0 if document is None else read_user_unit(document, page.xref)
    rotate_literal = 0.0 if document is None else read_rotate_literal(
        document, page.xref
    )
    if not math.isfinite(rotate_literal) or rotate_literal % 90.0 != 0.0:
        # MEASURED: MuPDF RENDERS such a page at the nearest quarter turn
        # while page.rotation reports 0, so neither the accessor nor the
        # page-box check below (which cannot tell 0 from 180) can be
        # trusted here.  Refuse rather than place ink upside down.
        raise UnsupportedPageGeometryError(
            f"/Rotate {rotate_literal!r} is not an exact quarter turn"
        )
    mediabox = page.mediabox
    cropbox = page.cropbox
    raw_cropbox = fitz.Rect(
        cropbox.x0,
        mediabox.y1 - cropbox.y1,
        cropbox.x1,
        mediabox.y1 - cropbox.y0,
    )
    clip = raw_cropbox & mediabox
    if not (math.isfinite(user_unit) and user_unit > 0.0):
        raise UnsupportedPageGeometryError(
            f"/UserUnit is not a usable positive scale ({user_unit!r})"
        )
    # The translation puts the mapped clip's minimum corner at the origin —
    # for a positive ``/UserUnit`` that is exactly ``(-uu·clip.x0, uu·clip.y1)``.
    xs = (user_unit * clip.x0, user_unit * clip.x1)
    ys = (-user_unit * clip.y0, -user_unit * clip.y1)
    width0 = user_unit * clip.width
    height0 = user_unit * clip.height
    _require_frame_matches_rendered_page(page, width0, height0)
    return PageVisualFrame(
        base=fitz.Matrix(user_unit, 0.0, 0.0, -user_unit, -min(xs), -min(ys)),
        rotation=int(page.rotation) % 360,
        width0=width0,
        height0=height0,
        user_unit=user_unit,
    )


def _require_frame_matches_rendered_page(
    page: fitz.Page, width0: float, height0: float
) -> None:
    """Prove the reconstructed page box against ``page.rect``.

    ``page.rect`` is MuPDF's own clipped, ``/UserUnit``-scaled, rotated page
    box — the ONE fact about the rendered page the frame does not compute
    itself, and therefore the only usable witness.  It is compared swapped
    on the quarter turns, relatively (a 1,000,000 pt MediaBox is legal and
    is NOT clamped — MEASURED — so an absolute tolerance would scale wrong).
    """
    if not (math.isfinite(width0) and math.isfinite(height0)):
        raise UnsupportedPageGeometryError(
            "reconstructed page box is not finite"
        )
    if width0 <= 0.0 or height0 <= 0.0:
        raise UnsupportedPageGeometryError(
            "the /CropBox does not intersect the /MediaBox in a positive area"
        )
    rect = page.rect
    rotation = int(page.rotation) % 360
    expected = (
        (float(rect.height), float(rect.width))
        if rotation in (90, 270)
        else (float(rect.width), float(rect.height))
    )
    for got, want in ((width0, expected[0]), (height0, expected[1])):
        if abs(got - want) > _FRAME_DIMS_REL_TOL * max(abs(got), abs(want), 1.0):
            raise UnsupportedPageGeometryError(
                "reconstructed page box does not match the rendered page "
                f"({width0}x{height0} vs {expected[0]}x{expected[1]})"
            )


def page_visual_frame_or_none(page: fitz.Page) -> PageVisualFrame | None:
    """``page``'s visual frame, or ``None`` when it cannot be proven.

    The fail-closed adapter every geometry consumer goes through:
    :func:`page_visual_frame` refuses a page whose reconstruction it cannot
    prove against what MuPDF renders (review "sol" F2), and a caller that
    only wants best-effort geometry must turn that refusal into ``None``,
    never let the exception reach it. The single chokepoint for this
    adapter -- callers used to duplicate it (``inspect.py``,
    ``scripts/audit_tier_coverage.py``, an inline try/except in
    ``scripts/measure_tier_funnel.py``; docs/PITFALLS.md: "an audit that
    mirrors a gate goes stale the day the gate moves").
    """
    try:
        return page_visual_frame(page)
    except UnsupportedPageGeometryError:
        return None


def pymupdf_writer_matrix(page: fitz.Page) -> fitz.Matrix | None:
    """The map from a TRUE unrotated-page-space point to the point to hand a
    PyMuPDF page writer (``insert_htmlbox``, ``insert_image``), or ``None`` when
    the identity already lands the ink (F15-G4, F15-G1-UU-ROT).

    Those writers convert page space to PDF user space with
    ``~page.transformation_matrix``.  MEASURED (1.27.1): once ``/Rotate != 0``
    that matrix collapses to ``(1, 0, 0, -1, 0, H)`` and drops BOTH the CropBox /
    MediaBox origin and the ``/UserUnit`` scale, so on a rotated page everything
    such a writer draws is displaced by the dropped origin (a ``/Rotate 90`` page
    with CropBox ``[30 40 500 700]`` drew 40/30 pt off its box) and, at
    ``/UserUnit u``, ``u`` times too large and too far from the origin (a
    ``/Rotate 90`` + ``/UserUnit 2`` page drew a 20 pt box's ink at 40 pt).  The
    true map is :attr:`PageVisualFrame.base`; the correction is
    ``~base x tm``: a pure translation at ``/UserUnit 1`` and a translation plus
    the scale ``1 / u`` otherwise (the writer then scales that rect back up by
    ``u`` through the page's own display scale, so the ink keeps its size).
    ``insert_text`` does not go through that matrix and needs none of this (it
    ignores ``/UserUnit`` instead: :func:`insert_text_page_space`, F15-G6).

    ``None`` when nothing needs cancelling: an unrotated page (where
    ``transformation_matrix`` is already right, ``/UserUnit`` included) or a
    frame that cannot be proven.
    """
    if int(page.rotation) % 360 == 0:
        return None
    frame = page_visual_frame_or_none(page)
    if frame is None:
        return None
    base = frame.base
    tm = page.transformation_matrix
    try:
        return fitz.Matrix(~base * tm)
    except (ZeroDivisionError, ValueError):
        return None


def pymupdf_writer_shift(page: fitz.Page) -> tuple[float, float]:
    """The TRANSLATION ``(dx, dy)`` of :func:`pymupdf_writer_matrix` (F15-G4).

    ``(0.0, 0.0)`` when nothing needs cancelling (unrotated page, unprovable
    frame) and when the correction also carries a SCALE (a ``/UserUnit != 1``
    rotated page: the rect must be rescaled, not only moved, so a bare shift
    would be wrong; use :func:`shift_rect_for_pymupdf_writers`).
    """
    matrix = pymupdf_writer_matrix(page)
    if matrix is None:
        return (0.0, 0.0)
    # Not a pure translation (a scale or a skew in the linear part): no bare shift.
    if max(abs(matrix.a - 1.0), abs(matrix.d - 1.0), abs(matrix.b), abs(matrix.c)) > 1e-6:
        return (0.0, 0.0)
    return (float(matrix.e), float(matrix.f))


def shape_writer_scale(page: fitz.Page) -> float:
    """``1 / UserUnit``: the factor from PAGE units to what ``insert_text`` takes.

    ``Page.insert_text`` / ``insert_textbox`` / ``draw_*`` (the ``Shape``
    writers) take coordinates AND font sizes in UNSCALED PDF user units, while
    ``page.rect``, ``get_text`` geometry and every model coordinate are
    already multiplied by ``/UserUnit`` (MEASURED, 1.27.1: on a MediaBox
    ``[0 0 300 400]`` + ``/UserUnit 2`` page ``insert_text((100, 300),
    fontsize=12)`` draws its baseline at (200, 600) with 24 pt glyphs, at every
    ``/Rotate``).  Multiply a page-space point and size by this to land the ink
    where it was asked (F15-G6).  ``insert_htmlbox`` is NOT affected.

    ``1.0`` for ``/UserUnit`` absent, not a number, zero, negative or not
    finite: there is no scale to undo (``page_visual_frame`` refuses such
    pages, and a zero-scale page has no geometry at all).
    """
    document = page.parent
    if document is None:
        return 1.0
    user_unit = read_user_unit(document, page.xref)
    if not (math.isfinite(user_unit) and user_unit > 0.0):
        return 1.0
    return 1.0 / user_unit


def insert_text_page_space(
    page: fitz.Page,
    point: fitz.Point,
    text: str,
    *,
    fontsize: float,
    morph: tuple[fitz.Point, fitz.Matrix] | None = None,
    **kwargs: Any,
) -> int:
    """``page.insert_text`` taking PAGE units: the one ``insert_text`` call site.

    ``point`` (the baseline origin, in the unrotated frame ``get_text`` reports),
    ``fontsize`` and the ``morph`` pivot are page units; they are multiplied by
    :func:`shape_writer_scale` so the ink lands there and keeps its size on a
    ``/UserUnit != 1`` page.  The scale is exactly ``1.0`` otherwise, so a unit
    page takes the same call as before.  Everything else (``rotate``,
    ``fontname``, ``color``, ``render_mode``, opacity, ...) passes through.
    A test pins that no other module calls ``insert_text`` /
    ``insert_textbox`` directly.
    """
    scale = shape_writer_scale(page)
    if scale != 1.0:
        point = fitz.Point(point) * scale
        fontsize = float(fontsize) * scale
        if morph is not None:
            morph = (fitz.Point(morph[0]) * scale, morph[1])
    return page.insert_text(point, text, fontsize=fontsize, morph=morph, **kwargs)


def shift_rect_for_pymupdf_writers(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    """``rect`` (true unrotated page space) mapped by :func:`pymupdf_writer_matrix`.

    The rect to PLACE a writer's output in: moved by the dropped CropBox /
    MediaBox origin and, on a rotated ``/UserUnit != 1`` page, scaled by
    ``1 / UserUnit`` (F15-G1-UU-ROT).  Right for ``insert_image``; ``insert_htmlbox``
    lays its text out in the rect it is given, so it needs the unscaled rect for
    layout and this one for placement (``font_stream_compaction``).
    Returns a new :class:`fitz.Rect`; the input is never mutated.
    """
    matrix = pymupdf_writer_matrix(page)
    r = fitz.Rect(rect)
    if matrix is None:
        return r
    return fitz.Rect(r * matrix)


def combined_linear(tm: Matrix, ctm: Matrix) -> Linear:
    """Linear part of ``tm × ctm`` (row-vector convention, as replay's)."""
    a1, b1, c1, d1, _, _ = tm
    a2, b2, c2, d2, _, _ = ctm
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
    )


def sigma_max(linear: Linear) -> float:
    """The largest singular value of the 2x2 linear map ``(a, b, c, d)``.

    ``E=(a+d)/2, F=(a-d)/2, G=(b+c)/2, H=(b-c)/2``,
    ``sigma_max = hypot(E, H) + hypot(F, G)`` — the closed form for a 2x2
    matrix's largest singular value (the SVD via the Kabsch/2D-rotation
    decomposition), exact rather than an estimate.

    T16-4 D5: a round stroke pen of radius ``r`` maps to an ellipse whose
    largest semi-axis is exactly ``sigma_max · r`` — tight, not merely an
    upper bound.  This is used ONLY as a bound's building block, deliberately
    diverging from ``scripts/painter_geometry.stroke_expansion``'s
    ``max(|a|, |b|, |c|, |d|)`` (MuPDF's ``fz_matrix_max_expansion``, pinned
    unchanged by ``test_p4b2_oracles.py`` and reconciled by test, not by
    import — see ``model.text_commit.plan._stroke_outset_visual``), which
    ``docs/PITFALLS.md`` (around line 2917) records as UNDER-bounding the
    true stretch: by sqrt(2) under a 45-degree rotation, by up to 2 under a
    shear.

    Pure. Non-finite input is not guarded against — the result may be
    ``nan`` or ``inf`` in that case (e.g. an ``inf`` component propagates
    through the arithmetic); every caller in this codebase checks
    ``math.isfinite`` on the result before trusting it, so this function
    does not duplicate that check.
    """
    a, b, c, d = linear
    e = (a + d) / 2.0
    f = (a - d) / 2.0
    g = (b + c) / 2.0
    h = (b - c) / 2.0
    return math.hypot(e, h) + math.hypot(f, g)


def _combined_matrix(tm: Matrix, ctm: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = tm
    a2, b2, c2, d2, e2, f2 = ctm
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def shape_reject_reason(
    linear: Linear,
    *,
    rel_tol: float = REL_TOL,
    abs_floor: float = ABS_SCALE_FLOOR,
    allow_reflection: bool = False,
) -> str | None:
    """First failing shape gate's stable code, or ``None`` when the linear
    map is a positive-orientation uniform rotation+scale.

    ``allow_reflection=True`` (plan section 2.C) skips the ORIENTATION gate
    alone, so ``None`` then means "orthogonal uniform rotation+scale, of
    either orientation".  Nothing else moves: the singular gate already
    reads ``|det|``, and orthogonality (``a·c + b·d``) and equal norms are
    orientation-blind by construction, so a sheared or non-uniform mirror
    keeps its own code with the same relative boundaries.  The default
    stays ``False`` -- the census taxonomy and every caller that has not
    proven the rest of the mirror admission keep the historical verdict.

    Angle-blind on purpose: quarter-turn vs arbitrary angle is the visual
    DIRECTION dimension's job (:func:`visual_baseline_direction` /
    :func:`admission_verdict`), because a rotated ``Tm`` compensating a
    page ``/Rotate`` is only classifiable against the page's visual
    matrix, never in user space alone.  ``abs_floor=0.0`` disables the
    floor gate — the census taxonomy delegates that way because its shape
    dimension predates the floor (which it applies in its predicted chain
    instead); production callers keep the default.
    """
    a, b, c, d = linear[0], linear[1], linear[2], linear[3]
    if not all(math.isfinite(v) for v in (a, b, c, d)):
        return RejectReason.TRM_NON_FINITE
    row_x = math.hypot(a, b)
    row_y = math.hypot(c, d)
    scale_sq = max(row_x * row_x, row_y * row_y)
    det = a * d - b * c
    if scale_sq == 0.0 or abs(det) <= rel_tol * scale_sq:
        return RejectReason.TRM_SINGULAR
    if row_x <= abs_floor:
        # The baseline scale (text-space (1, 0)'s image) is what every
        # advance/kern computation divides by — the absolute floor guards
        # it; a degenerate CROSS axis is caught by the norms gate below.
        return RejectReason.TRM_SCALE_BELOW_FLOOR
    if det < 0.0 and not allow_reflection:
        return RejectReason.TRM_REFLECTED
    if abs(a * c + b * d) > rel_tol * scale_sq:
        return RejectReason.TRM_SHEARED
    if abs(row_x - row_y) > rel_tol * max(row_x, row_y):
        return RejectReason.TRM_NON_UNIFORM_SCALE
    return None


def visual_baseline_direction(
    page: fitz.Page,
    linear: Linear,
    *,
    rel_tol: float = REL_TOL,
    frame: PageVisualFrame | None = None,
) -> str:
    """Cardinal slug for where the text baseline points ON SCREEN.

    Pushes text-space ``(1, 0)`` through the combined linear map and then
    the page's :class:`PageVisualFrame` — the exact chain the raster
    verifier's pixmaps use — and classifies against visual axes (y grows
    DOWNWARD in visual space).  ``page.transformation_matrix ×
    page.rotation_matrix`` is NOT that chain on a rotated cropped or
    ``/UserUnit`` page (review "sol" F3); for a positive ``/UserUnit`` the
    two agree up to a positive uniform scale, so every direction this
    classifier has ever returned is preserved bit-identically.

    ``frame`` is a pure optimisation for callers that already hold the
    page's frame; omitting it derives the same frame from the page.  A page
    whose frame cannot be proven classifies as
    :data:`DIRECTION_DEGENERATE` — fail-closed, since a non-cardinal
    direction refuses the show.
    """
    ux, uy = linear[0], linear[1]
    if not (math.isfinite(ux) and math.isfinite(uy)):
        return DIRECTION_DEGENERATE
    try:
        visual = (page_visual_frame(page) if frame is None else frame).visual
    except UnsupportedPageGeometryError:
        return DIRECTION_DEGENERATE
    vx = ux * visual.a + uy * visual.c
    vy = ux * visual.b + uy * visual.d
    norm = math.hypot(vx, vy)
    if norm == 0.0 or not math.isfinite(norm):
        return DIRECTION_DEGENERATE
    if abs(vy) <= rel_tol * norm:
        return DIRECTION_RIGHT if vx > 0.0 else DIRECTION_LEFT
    if abs(vx) <= rel_tol * norm:
        return DIRECTION_DOWN if vy > 0.0 else DIRECTION_UP
    return DIRECTION_OBLIQUE


@dataclass(frozen=True)
class TrmVerdict:
    """One show's fail-closed TRM admission verdict.

    ``reject_reason`` is one of the seven ``trm_*`` codes, or ``None``
    when admitted; ``direction`` (a cardinal slug) and ``scale`` (the
    uniform baseline scale factor) are set exactly when admitted.
    ``reflected`` is ``True`` only on an ADMITTED negative-orientation
    matrix (plan section 2.C): the planner reads it to hold the show to
    Tier 0's exact equal-advance splice.  Defaulted so every positional
    construction stays valid.
    """

    reject_reason: str | None
    direction: str | None
    scale: float | None
    reflected: bool = False


def admission_verdict(
    page: fitz.Page,
    tm: Matrix,
    ctm: Matrix,
    *,
    rel_tol: float = REL_TOL,
    frame: PageVisualFrame | None = None,
    render_mode: int | None = None,
) -> TrmVerdict:
    """Prove (or refuse) one show's combined transform for the v1 scope.

    ``frame`` threads the caller's per-prepare :class:`PageVisualFrame`
    into the direction gate; omitting it derives the same frame.

    ``render_mode`` is the show's ``Tr`` and matters only for a REFLECTED
    matrix (plan section 2.C): a mirror is admitted exactly when it is
    otherwise orthogonal and uniform (``allow_reflection=True`` shape
    proof), its visual baseline is cardinal, AND the caller proves the
    fill-only mode ``0``.  ``None`` -- the caller did not say -- refuses
    the mirror as ``trm_reflected``, so an instrument that never learned
    about the mirror admission stays fail-closed rather than over-admitting.
    Every refused mirror keeps ``trm_reflected`` whatever its second defect
    (the fixed precedence puts orientation ahead of shear, norms and
    direction, and the census attributes the same way).
    """
    linear = combined_linear(tm, ctm)
    reason = shape_reject_reason(linear, rel_tol=rel_tol)
    reflected = False
    if reason == RejectReason.TRM_REFLECTED:
        if render_mode != 0 or shape_reject_reason(
            linear, rel_tol=rel_tol, allow_reflection=True
        ) is not None:
            return TrmVerdict(reject_reason=reason, direction=None, scale=None)
        reflected = True
    elif reason is not None:
        return TrmVerdict(reject_reason=reason, direction=None, scale=None)
    direction = visual_baseline_direction(page, linear, rel_tol=rel_tol, frame=frame)
    if direction not in CARDINAL_DIRECTIONS:
        return TrmVerdict(
            reject_reason=(
                RejectReason.TRM_REFLECTED
                if reflected
                else RejectReason.TRM_ROTATION_NOT_QUARTER_TURN
            ),
            direction=None,
            scale=None,
        )
    return TrmVerdict(
        reject_reason=None,
        direction=direction,
        scale=math.hypot(linear[0], linear[1]),
        reflected=reflected,
    )


def map_text_quad_to_visual(
    page: fitz.Page,
    tm: Matrix,
    ctm: Matrix,
    quad: tuple[float, float, float, float],
    *,
    frame: PageVisualFrame | None = None,
) -> tuple[float, float, float, float]:
    """Visual-space bounds of a TEXT-space rectangle under one show's
    full transform chain.

    ``quad`` is ``(x0, y0, x1, y1)`` in text space (points; x along the
    baseline, y toward the ascender).  Each corner rides
    ``tm × ctm`` (translations included) and then the page's
    :class:`PageVisualFrame`; the result is the axis-aligned bounds of the
    mapped quad — the ONE way every fallback target box and growth strip
    becomes visual geometry, so no caller can reintroduce a ``+x``
    assumption.

    ``frame`` is a pure optimisation for callers that already hold the
    page's frame (one prepare maps many quads); omitting it derives the
    same frame from the page and yields bit-identical bounds.
    """
    trm = _combined_matrix(tm, ctm)
    visual = (page_visual_frame(page) if frame is None else frame).visual
    xs: list[float] = []
    ys: list[float] = []
    for tx, ty in (
        (quad[0], quad[1]),
        (quad[2], quad[1]),
        (quad[0], quad[3]),
        (quad[2], quad[3]),
    ):
        ux = trm[0] * tx + trm[2] * ty + trm[4]
        uy = trm[1] * tx + trm[3] * ty + trm[5]
        vx = ux * visual.a + uy * visual.c + visual.e
        vy = ux * visual.b + uy * visual.d + visual.f
        xs.append(vx)
        ys.append(vy)
    return (min(xs), min(ys), max(xs), max(ys))
