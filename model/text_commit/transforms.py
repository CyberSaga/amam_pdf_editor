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

Shared by replay/inspect/plan/verify; the census tooling
(``scripts/trm_taxonomy.py``) delegates to this module — this module must
never import ``scripts/`` (pinned by tests).  Contract pinned verbatim by
``test_scripts/test_text_commit_trm_admission.py``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

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

_IDENTITY_MATRIX = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def read_user_unit(doc: fitz.Document, page_xref: int) -> float:
    """The ``/UserUnit`` factor MuPDF applies to this page's geometry.

    MEASURED (PyMuPDF 1.27.1): every PDF *number* is applied verbatim —
    including ``0`` (which collapses the page to a point) and negatives
    (which mirror it); every value that is not a number (absent, name,
    string, boolean, array, or unlexable) reads as ``1``.  One indirect
    hop is resolved, and the resolved object is judged as a number in the
    same way.  ``/UserUnit`` is NOT inheritable, so the page dict is the
    only place to look.

    Deliberately NOT shared with ``inspect._update_page_geometry``: that
    reader folds the raw ``kind:value`` pair for non-numeric values
    (identity, not geometry) and ``inspect`` imports this module, so the
    dependency could only run the other way.
    """
    try:
        kind, value = doc.xref_get_key(page_xref, "UserUnit")
        if kind == "xref":
            value = doc.xref_object(int(value.split()[0]))
        elif kind not in _NUMERIC_KEY_KINDS:
            return 1.0
    except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
        return 1.0
    text = value.strip()
    if not _PDF_NUMBER_RE.match(text):
        return 1.0
    try:
        return float(text)
    except (ValueError, OverflowError):  # pragma: no cover - regex-guarded
        return 1.0


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
    """
    document = page.parent
    user_unit = 1.0 if document is None else read_user_unit(document, page.xref)
    mediabox = page.mediabox
    cropbox = page.cropbox
    raw_cropbox = fitz.Rect(
        cropbox.x0,
        mediabox.y1 - cropbox.y1,
        cropbox.x1,
        mediabox.y1 - cropbox.y0,
    )
    clip = raw_cropbox & mediabox
    # The translation puts the mapped clip's minimum corner at the origin —
    # which is ``(-uu·clip.x0, uu·clip.y1)`` for the ordinary positive
    # ``/UserUnit`` and stays MuPDF-exact for zero and negative ones.
    xs = (user_unit * clip.x0, user_unit * clip.x1)
    ys = (-user_unit * clip.y0, -user_unit * clip.y1)
    return PageVisualFrame(
        base=fitz.Matrix(user_unit, 0.0, 0.0, -user_unit, -min(xs), -min(ys)),
        rotation=int(page.rotation) % 360,
        width0=abs(user_unit) * clip.width,
        height0=abs(user_unit) * clip.height,
        user_unit=user_unit,
    )


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
    linear: Linear, *, rel_tol: float = REL_TOL, abs_floor: float = ABS_SCALE_FLOOR
) -> str | None:
    """First failing shape gate's stable code, or ``None`` when the linear
    map is a positive-orientation uniform rotation+scale.

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
    if det < 0.0:
        return RejectReason.TRM_REFLECTED
    if abs(a * c + b * d) > rel_tol * scale_sq:
        return RejectReason.TRM_SHEARED
    if abs(row_x - row_y) > rel_tol * max(row_x, row_y):
        return RejectReason.TRM_NON_UNIFORM_SCALE
    return None


def visual_baseline_direction(
    page: fitz.Page, linear: Linear, *, rel_tol: float = REL_TOL
) -> str:
    """Cardinal slug for where the text baseline points ON SCREEN.

    Pushes text-space ``(1, 0)`` through the combined linear map and then
    ``page.transformation_matrix × page.rotation_matrix`` — the exact
    chain the raster verifier's pixmaps use (``transformation_matrix``
    alone omits ``/Rotate``, the known pitfall) — and classifies against
    visual axes (y grows DOWNWARD in visual space).
    """
    ux, uy = linear[0], linear[1]
    if not (math.isfinite(ux) and math.isfinite(uy)):
        return DIRECTION_DEGENERATE
    visual = page.transformation_matrix * page.rotation_matrix
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
    """

    reject_reason: str | None
    direction: str | None
    scale: float | None


def admission_verdict(
    page: fitz.Page, tm: Matrix, ctm: Matrix, *, rel_tol: float = REL_TOL
) -> TrmVerdict:
    """Prove (or refuse) one show's combined transform for the v1 scope."""
    linear = combined_linear(tm, ctm)
    reason = shape_reject_reason(linear, rel_tol=rel_tol)
    if reason is not None:
        return TrmVerdict(reject_reason=reason, direction=None, scale=None)
    direction = visual_baseline_direction(page, linear, rel_tol=rel_tol)
    if direction not in CARDINAL_DIRECTIONS:
        return TrmVerdict(
            reject_reason=RejectReason.TRM_ROTATION_NOT_QUARTER_TURN,
            direction=None,
            scale=None,
        )
    return TrmVerdict(
        reject_reason=None,
        direction=direction,
        scale=math.hypot(linear[0], linear[1]),
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
