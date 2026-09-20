"""Tier 0/1 capability classification: narrow by design, never guessing.

Tier 0: one unambiguous run bound to one complete single-string ``Tj``
(literal or hex) on the direct page stream, simple Latin encoding with a
verified reverse encoder, fill render mode, no rise, a positive finite
horizontal scale, no marked-content dependency, a text matrix that is at most a uniform positive
scale, no style or geometry override, and a replacement whose consumed
advance equals the source advance exactly.

Tier 1 Slice 1 (``prepare_plan``, escalation only): the SAME classified
candidate, reached only when Tier 0 refuses with ``ADVANCE_MISMATCH`` and
the caller allows ``max_tier >= 1``. Composes ``patch.
build_kern_compensated_transplant`` -- a whole-op ``"[(new) K] TJ"`` splice
whose kern term absorbs an arbitrary advance delta, so ink may grow past the
source bbox under a verified blank-growth-zone proof (``verify.
verify_tier1_commit``).

Every failed gate returns a stable :class:`RejectReason` code.
"""
from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import fitz

from model.edit_requests import StyleOverrides
from model.text_commit.cid_fonts import (
    CidCapabilityFailure,
    IdentityHCidCapability,
    PdfRef,
    parse_pdf_value,
)
from model.text_commit.dto import (
    SPLICE_KIND_STRING_TOKEN,
    SPLICE_KIND_WHOLE_OPERATOR,
    CommitTier,
    RejectReason,
    StreamReplacement,
)
from model.text_commit.evidence import ReplayEvidenceCache, resolve_replay
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.glyph_boxes import (
    GlyphBoxCache,
    TjItem,
    TjSpan,
    predict_glyphs,
    rect_union,
    scale_units_to_text,
    tj_item_spans,
    tj_items,
)
from model.text_commit.inspect import (
    BindingFailure,
    SourceSpanBinding,
    bind_source_text,
    capture_page_streams,
    find_pages_sharing_content_stream,
    page_fingerprint,
    page_has_widgets_or_signatures,
)
from model.text_commit.marked_content import admit_show_wrappers
from model.text_commit.patch import build_kern_compensated_transplant, kern_for_displacement
from model.text_commit.pdf_lexer import (
    TokenKind,
    encode_hex_string,
    encode_literal_string,
)
from model.text_commit.replay import McWrapper, ShowOp
from model.text_commit.transforms import (
    PageVisualFrame,
    UnsupportedPageGeometryError,
    admission_verdict,
    combined_linear,
    map_text_quad_to_visual,
    page_visual_frame,
    page_visual_frame_or_none,
    sigma_max,
)

logger = logging.getLogger(__name__)

# Advance equality tolerance, relative to font size.  Both sides are measured
# from the same source, so genuinely width-neutral replacements agree to float
# precision and this only absorbs rounding.
#
# The two sources need different tolerances, and the difference is not
# cosmetic.  A /Widths advance is exact rational arithmetic — integer table
# units scaled by the font size — and one table unit is *exactly*
# ``_ADVANCE_TOL_PER_PT * size``.  Reusing the face tolerance there would put
# the smallest representable width difference precisely on the ``>`` boundary,
# leaving float representation to decide accept/reject: measured
# non-monotonic (size 12 accepted a 0.012pt shift, size 72 refused 0.072pt,
# size 600 accepted 0.600pt).  Absorbing a whole unit of the document's own
# width table is not "rounding", so widths get a float-noise tolerance.
_ADVANCE_TOL_PER_PT = 1e-3  # face-derived: absorbs the face's own float error
_ADVANCE_TOL_PER_PT_EXACT = 1e-9  # /Widths: exact arithmetic, noise only
_GROWTH_OUTSIDE_PAGE_REASON = RejectReason.GROWTH_OUTSIDE_PAGE
# Finiteness is NOT the raster sampler's real precondition: ``verify.py``'s
# ``_bbox_pixels`` does ``int(x * 96 / 72)``, which raises ``OverflowError``
# for finite coordinates above ~1.348e308.  The bound below is that
# precondition with headroom, deliberately NOT a tighter policy cut: a
# smaller limit would reject geometry the sampler handles correctly today
# (a probe at 1.5e305 reaches it and returns an ordinary rejection), and
# rejecting what still renders is an admission regression, not a safety
# gain.
_RENDERABLE_COORD_LIMIT = 1.0e308
_PAGE_CONTAINMENT_TOL_PT = 1e-3


def _renderable_bbox(
    values: Sequence[float | int | str] | None,
) -> tuple[float, float, float, float] | None:
    """Return one sampler-safe four-coordinate bbox, else ``None``."""
    if values is None or len(values) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in values)
    except (OverflowError, TypeError, ValueError):
        return None
    bbox = (x0, y0, x1, y1)
    if not all(
        math.isfinite(value) and abs(value) <= _RENDERABLE_COORD_LIMIT
        for value in bbox
    ):
        return None
    return bbox


@dataclass(frozen=True)
class PreparedEdit:
    """An immutable, verified-on-scratch Tier 0 or Tier 1 candidate."""

    token: str
    page_xref: int
    stream_xref: int
    replacement: StreamReplacement
    binding: SourceSpanBinding
    original_text: str
    replacement_text: str
    font_resource: str
    font_xref: int
    font_size: float
    target_bbox_page: tuple[float, float, float, float]
    page_fingerprint: str
    # Task 11 Slice 1 additions -- all defaulted so the single Tier 0
    # construction site and every existing test/script stays valid.
    tier: CommitTier = CommitTier.TIER0_LOSSLESS_STREAM_PATCH
    # None for Tier 0 (which never grows the target box); the ink-growth-
    # widened box for Tier 1, or exactly ``target_bbox_page`` when a Tier 1
    # candidate has no growth.
    verify_bbox_page: tuple[float, float, float, float] | None = None
    # Tier 1 background-majority sampling uses this flag-immune metric quad.
    # It is a pure derivation of token-bound inputs (the fingerprint determines
    # the show transform; source_advance is already in the token), so folding
    # it into the token would add no candidate identity.
    background_bbox_page: tuple[float, float, float, float] | None = None
    source_advance: float = 0.0
    replacement_advance: float = 0.0
    kern_adjustment: float = 0.0
    style_overrides: StyleOverrides | None = None
    geometry_intent: tuple[float, float, float, float] | None = None
    # Task 13 P2: the admitted show's cardinal visual baseline direction
    # ("right"/"left"/"up"/"down"), bound into the plan token (review F5:
    # verify does NOT read this field — it re-derives the grown edge from
    # target/verify bbox geometry, which agrees by construction because
    # ``_grown_verify_bbox`` extends exactly the edge this slug names).
    # Defaulted so pre-P2 hand-built PreparedEdits stay valid; None also
    # marks the axis path (replay-uniform shows, including admitted
    # boundary residuals the shape checks would refuse).
    growth_direction: str | None = None
    # T16-4X S1 (X3, "one splice primitive, three grammars, one proof
    # dispatch"): the grammar the spliced byte range obeys, which V0c's
    # ``_target_operator_failure`` dispatches on.  ``"string_token"`` is a
    # whole string operand (``Tj``) or the single inner item of a
    # single-item ``TJ``.  Defaulted so every hand-built PreparedEdit stays
    # valid.  The label alone never selects a weaker proof: each arm first
    # re-derives the range it expects from the recorded show, because a
    # PreparedEdit is cached at prepare and reused at commit.
    splice_kind: str = SPLICE_KIND_STRING_TOKEN

    @property
    def effective_verify_bbox(self) -> tuple[float, float, float, float]:
        """``verify_bbox_page`` when set, else ``target_bbox_page``."""
        if self.verify_bbox_page is not None:
            return self.verify_bbox_page
        return self.target_bbox_page

    @property
    def has_ink_growth(self) -> bool:
        """True when the verified region is wider than the target box."""
        return (
            self.verify_bbox_page is not None
            and self.verify_bbox_page != self.target_bbox_page
        )


@dataclass(frozen=True)
class PlanRejection:
    reason: str  # a RejectReason constant
    detail: str


@dataclass(frozen=True)
class ShowGateAdmission:
    """What :func:`tier0_show_gate` proves about ONE show operator.

    PUBLIC: the instruments (``scripts/audit_tier_coverage.py``) admit shows
    through the same object the planner does, so an audit can never lag a
    slice that moves a gate (docs/PITFALLS.md, "an audit that mirrors a gate
    goes stale the day the gate moves").

    Later T16-4X S1 stages APPEND fields here as the gates that derive them
    land (the render-mode ladder's proven mode) -- construct it by keyword
    and read it by name, never by position or unpacking.

    ``item_span`` is the admitted single-item ``TJ``'s INNER string item,
    with absolute offsets into its own stream; ``None`` for a ``Tj``, whose
    splice covers the whole string operand.  It is carried here so
    :func:`_build_tier0` reads the proven range instead of re-lexing the
    array and possibly disagreeing with the gate that admitted it.

    ``pen`` is the PROVEN stroke pen of an admitted ``render_mode == 2``
    show (tandem plan D8) and ``None`` for the fill mode, which strokes
    nothing.  Carried for the same reason as ``item_span``: the pen is
    resolved ONCE, here, against the page's ``/Resources /ExtGState``, and
    every consumer (the honest fallback ``target_bbox`` outset today; the
    duplicate-painter gate's conservative core outset next) reads that one
    answer rather than re-deriving a possibly different one.
    """

    capability: FontCapability
    item_span: TjSpan | None = None
    pen: StrokePen | None = None


@dataclass(frozen=True)
class _ClassifiedTarget:
    """Everything the shared classifier proves before either tier decides.

    Not a public contract: an internal handoff between :func:`_classify_common`
    and :func:`_build_tier0`/:func:`_build_tier1`, both of which reuse it
    without re-parsing or re-binding.
    """

    binding: SourceSpanBinding
    show: ShowOp
    capability: FontCapability
    stream_bytes: bytes
    target_text: str
    replacement_text: str
    source_encoded: bytes
    replacement_encoded: bytes
    source_advance: float
    replacement_advance: float
    advance_tolerance: float
    target_bbox_page: tuple[float, float, float, float]
    fingerprint: str
    style_overrides: StyleOverrides | None
    geometry_intent: tuple[float, float, float, float] | None
    # "literal" (simple fonts) or "hex" (Identity-H CID operands): decides
    # how ``replacement_encoded`` is serialized into the spliced operator.
    operand_kind: str
    # T16-4X S1: the admitted single-item ``TJ``'s inner string item, with
    # absolute offsets into ``stream_bytes``; ``None`` for a ``Tj``, whose
    # splice covers the whole string operand.  Proven ONCE, by
    # ``tier0_show_gate``, and carried rather than re-lexed.
    show_item_span: TjSpan | None = None
    # Task 13 P2: the admitted show's cardinal visual baseline direction
    # (transforms.admission_verdict) — the ONE direction every growth
    # probe shares.
    trm_direction: str | None = None
    # Task 15 P4-B2 slice 2: the page's visual frame, derived ONCE per
    # prepare (its /UserUnit read costs an xref lookup) and threaded into
    # every geometry call downstream.  ``None`` only if a caller builds a
    # target by hand — every mapper then derives the same frame itself.
    frame: PageVisualFrame | None = None


def _advance(
    capability: FontCapability, text: str, size: float, tc: float, tw: float
) -> float:
    """Advance ``text`` consumes, in points, including Tc/Tw contributions.

    The string width comes from the font's own /Widths table when it
    declares one — that, not the font program, is what a viewer advances by
    for a simple font — and from the resolved face otherwise.  Callers must
    have established that the advance is provable; an unprovable code has no
    defensible width and Tier 0 refuses rather than invent one.
    """
    width = capability.string_width(text, size)
    if width is None:
        raise ValueError("advance is not provable for this font and text")
    return width + tc * len(text) + tw * text.count(" ")


# The former ``_page_visual_matrix`` (``transformation_matrix ×
# rotation_matrix``) is gone: ``transforms.page_visual_frame`` is the single
# source for the user-space → pixmap/visual-space matrix.  PyMuPDF's own
# ``transformation_matrix`` drops the CropBox origin AND ``/UserUnit`` once
# ``/Rotate != 0``, and its ``rotation_matrix`` drops ``/UserUnit`` and sizes
# itself from the UNCLIPPED CropBox, so their product is wrong on every
# rotated cropped page (docs/PITFALLS.md).


def _strict_overlap_depths(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float]:
    return (
        min(first[2], second[2]) - max(first[0], second[0]),
        min(first[3], second[3]) - max(first[1], second[1]),
    )


def _glyph_identity(capability: FontCapability) -> tuple:
    """Conservative glyph-program identity, excluding layout metrics.

    A producer that clones a font dictionary — new xref, new ``/BaseFont``
    subset tag, same glyph program — paints the same outlines even if its
    width tables differ.  Widths, defaults, first-char offsets, and advance
    provenance affect placement only and must never prove different glyphs.
    """
    cid = capability.cid
    return (
        capability.subtype,
        capability.encoding,
        capability.embedded,
        capability.supports_simple_encoding,
        cid.cidtogid_table if cid is not None else None,
    )


def _same_font_object(
    first: FontCapability | None, second: FontCapability
) -> Literal[True] | None:
    """Whether two resolved capabilities paint the SAME glyphs.

    ``None`` means "not provable"; this helper never claims two fonts paint
    different glyphs.  Resource names are aliases. Identity is established
    by xref, equal same-document evidence, or equal conservative glyph
    identity (:func:`_glyph_identity`). A degraded capability proves nothing.
    """
    if (
        first is None
        or first.advance_source == "none"
        or second.advance_source == "none"
    ):
        return None
    if (
        first.font_xref == second.font_xref
        or first.evidence_digest == second.evidence_digest
        or _glyph_identity(first) == _glyph_identity(second)
    ):
        return True
    return None


def _painter_advance(
    capability: FontCapability, show: ShowOp, text: str
) -> float | None:
    """One show's own raw (Tz-free) advance for ``text``, or ``None`` when
    the document does not prove it.

    Mirrors the two advance branches ``_classify_common`` uses for the
    target — the Identity-H codec's ``/W``-driven arithmetic (where Tw never
    applies, PDF 32000-1 §9.3.3) and the simple-font ``_advance`` — so a
    twin is measured exactly the way the target is, under its OWN
    ``font_size``/``Tc``/``Tw``.
    """
    if capability.cid is not None:
        raw = show.decoded_bytes
        if not raw or len(raw) % 2:
            return None
        cids = tuple(
            int.from_bytes(raw[index : index + 2], "big")
            for index in range(0, len(raw), 2)
        )
        return capability.cid.advance_points(cids, show.font_size, show.char_spacing)
    try:
        return _advance(
            capability, text, show.font_size, show.char_spacing, show.word_spacing
        )
    except ValueError:
        return None


# T16-4 D5/D4: the pen lives in USER space, never text space — the
# combined linear map used below is ``IDENTITY × show.ctm``, so a caller
# that instead threads ``show.tm`` in would under-state the pen whenever
# the text-matrix scale is < 1 (the false-safe direction at the duplicate
# gate, E5).
_IDENTITY_TM: tuple[float, float, float, float, float, float] = (
    1.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
)
# T16-4 S1 review H2.  Only 1 (round) and 2 (bevel) have no miter to
# overshoot: they were MEASURED collapsing to half the pen (E6).  Every
# OTHER value — 0, a negative operand, anything above 2 — takes the miter
# factor at the conservative bound, because a negative join operand
# ('-1 j') renders as MITER in MuPDF and an out-of-range one is
# renderer-defined.  The complement is the fail-closed spelling: a new
# undefined value cannot slip through as "not 0, so not a miter".
_NON_MITER_LINE_JOINS = (1, 2)
_DEFINED_LINE_JOINS = (0, 1, 2)
# ISO 32000-1 8.5.2: a conforming miter limit is >= 1.  Below that the
# factor would drop under the geometric half-pen a stroke always reaches,
# so 1.0 is the conservative floor (and ``_prove_stroke_pen`` refuses the
# spec-illegal value outright rather than floor it into an admission).
_MIN_MITER_LIMIT = 1.0
# The initial graphics state (ISO 32000-1 8.4.1 Table 52), which is what a
# page's pen is before any w/j/M/gs runs.  The ordered pen replay in
# ``_resolve_stroke_pen`` starts here rather than from ``ShowOp``'s
# scalars, which a malformed operand parks on a sentinel and a later
# ExtGState can overwrite.
_PDF_DEFAULT_LINE_WIDTH = 1.0
_PDF_DEFAULT_LINE_JOIN = 0
_PDF_DEFAULT_MITER_LIMIT = 10.0


@dataclass(frozen=True)
class StrokePen:
    """One show's stroke-pen evidence, resolved independently of
    :class:`~model.text_commit.replay.ShowOp`.

    Decoupled on purpose (T16-4 D8): the stream-recorded
    ``line_width``/``line_join``/``miter_limit`` on ``ShowOp`` is what
    replay captured, but the planner may need to resolve (or refuse) an
    ExtGState override against the page ``/Resources /ExtGState`` before
    the pen is provable — a concern that does not belong on the replay
    evidence type.

    ``line_join`` carries whatever the stream (or an ExtGState ``/LJ``)
    said, including a value outside ``{0, 1, 2}``: this type records
    evidence and does not validate it.  The two consumers disagree on
    purpose (T16-4 S1 review H2) — :func:`_stroke_outset_visual` treats
    every join outside ``{1, 2}`` as a miter (the fail-closed BOUND), while
    :func:`_prove_stroke_pen` refuses an undefined join outright, because
    what such an operand paints is renderer-defined and admission needs a
    pen it can PROVE, not merely bound.
    """

    width: float
    line_join: int
    miter_limit: float


def _stroke_outset_visual(
    show: ShowOp,
    *,
    frame: PageVisualFrame,
    pen: StrokePen,
    conservative: bool,
) -> float | None:
    """One show's stroke outset, in VISUAL points, or ``None`` if unprovable.

    ``(abs(pen.width) / 2) * factor * sigma_max(L)``, where ``L`` is the
    linear part of ``combined_linear(_IDENTITY_TM, show.ctm)`` composed
    with ``frame.visual``.  ``show.tm`` is NEVER read here: the stroke pen
    is defined in USER space (measured, E5 — ``cm 2 0 0 2`` doubles the
    stroked outset; neither ``Tm 2 0 0 2`` nor ``200 Tz`` moves it at all),
    so folding the text matrix or the horizontal scale in would under-state
    the pen whenever either shrinks it below 1 — the false-safe direction
    at the duplicate-painter gate this bound feeds (D4).  ``frame.visual``
    carries the page's own ``/UserUnit`` and ``/Rotate`` (E5 continued —
    ``/UserUnit 2`` doubles the outset the same way a ``2 0 0 2 cm`` does;
    an exact quarter-turn ``/Rotate`` leaves it unchanged, since
    ``frame.visual``'s rotation term is orthogonal).

    ``factor`` is ``max(pen.miter_limit, 1.0)`` when ``conservative`` is
    true AND ``pen.line_join`` is NOT one of ``{1, 2}`` (round, bevel);
    every other combination — ``conservative=False`` (the HONEST bound), or
    a round/bevel join under either mode — uses ``1.0``.  D4 keeps two
    different bounds at two sites, in the SAME direction of error each site
    cannot tolerate:

    - the honest bound (``target_bbox_page`` / the V0d halo): an
      under-bound false-REJECTS (revert, zero mutation) — cheap.  An
      over-bound erodes how much of the page V0d's diff-margin exempts, so
      the miter factor must stay OUT of it — E7 measured the fixture's own
      miter bound (``0.40114/2 × 10 = 2.0057``) exceeding
      ``verify._HALO_MARGIN_PT`` (``2.0``), which would roughly double the
      exempt region if adopted here.
    - the conservative bound (``target_core`` / the duplicate-painter
      gate): an under-bound false-SAFEs — an overlapping same-bytes twin
      is admitted and silently damaged.  E6 measured a miter join
      overshooting half-pen by up to 4.54x on an acute vertex (round/bevel
      joins collapse to half-pen, no overshoot), so the miter factor is
      MANDATORY here whenever the join is actually a miter join.

    Deliberately diverges from ``scripts/painter_geometry.stroke_expansion``
    (MuPDF's reverse-measured ``fz_matrix_max_expansion`` —
    ``max(|a|,|b|,|c|,|d|)`` on the combined ctm, which
    ``docs/PITFALLS.md`` (around line 2917) records as UNDER-bounding the
    true stretch — by sqrt(2) under a 45-degree rotation, by up to 2 under
    a shear).  ``sigma_max`` is the exact largest singular value instead of
    that estimate.  The divergence is deliberate (D5) and reconciled by
    TEST, not by import:
    ``test_p4b2_oracles.py::test_bboxlog_stroke_text_rect_is_o1_union_plus_stroke_expansion``
    stays pinned to the MuPDF-measured (under-bounding) formula unchanged,
    on purpose, so nobody "fixes" one formula toward the other.

    Two details of ``factor`` are load-bearing, not cosmetic, and both are
    T16-4 S1 review H2 corrections to the first spelling
    (``max(pen.miter_limit, 0.5) if pen.line_join == 0``):

    * the floor is ``1.0``, not ``0.5``.  A compliant ``M`` operand is
      always ``>= 1`` (ISO 32000-1 8.5.2), but a malformed stream can carry
      ``0`` or a negative value, and a factor BELOW 1.0 under-states the
      geometry itself: a stroke reaches ``w/2`` per side whatever the join
      does, so ``1 w 0 M`` produced an outset of 0.25 pt against a measured
      expansion of 0.5 pt — the false-safe direction D4 forbids at the
      duplicate gate.  (``_prove_stroke_pen`` refuses ``M < 1`` before
      admission, so on that path the floor is defence in depth; the
      instrument call sites — the census, the funnel — reach it.)
    * the miter test is ``line_join not in {1, 2}``, not ``== 0``.  Only
      round and bevel provably collapse to half the pen; MuPDF renders a
      NEGATIVE join operand (``-1 j``) as MITER, so "not 0 ⇒ no miter"
      collapsed the bound 10x on a stream that paints a miter vertex.
      ``5 j`` and an ExtGState ``/LJ 5`` were measured rendering
      bevel/round in MuPDF, but that is renderer behaviour on an undefined
      operand: the fail-closed answer is to treat every join outside
      ``{1, 2}`` as a miter.

    Returns ``None`` — the caller turns this into
    :data:`~model.text_commit.dto.RejectReason.STROKE_BOUND_UNPROVEN` —
    when ``pen.width`` is non-finite or exactly ``0.0`` (a hairline pen
    reads as device-thinnest, which a half-pen bound would understate, not
    the PDF-default-width fallback MuPDF's own renderer applies), when
    ``pen.miter_limit`` is non-finite, or when ``sigma_max`` is non-finite
    or ``<= 0.0`` (only the ZERO combined map: ``sigma_max`` is strictly
    positive for every non-zero linear map, including a rank-deficient
    one — a merely SINGULAR (rank-1) combined map still returns a positive
    bound here.  Refusing on rank-deficiency itself is a separate, caller-
    side concern — e.g. ``_painter_reach``'s determinant test,
    ``docs/PITFALLS.md:2952-2954`` — not this bound's).
    """
    if not math.isfinite(pen.width) or pen.width == 0.0:
        return None
    if not math.isfinite(pen.miter_limit):
        return None
    ctm_linear = combined_linear(_IDENTITY_TM, show.ctm)
    visual = frame.visual
    linear = combined_linear(
        (ctm_linear[0], ctm_linear[1], ctm_linear[2], ctm_linear[3], 0.0, 0.0),
        (visual.a, visual.b, visual.c, visual.d, 0.0, 0.0),
    )
    scale = sigma_max(linear)
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    factor = 1.0
    if conservative and pen.line_join not in _NON_MITER_LINE_JOINS:
        factor = max(pen.miter_limit, _MIN_MITER_LIMIT)
    return (abs(pen.width) / 2.0) * factor * scale


def _painter_core_quad(
    show: ShowOp, advance: float
) -> tuple[float, float, float, float] | None:
    """The baseline/rise core envelope in the show's own text space.

    ``_classify_common`` refuses non-zero rise on the target, but a candidate
    may have either sign.  Enveloping both its baseline core and its
    rise-shifted core is monotone fail-closed: it detects a rise that cancels
    a baseline offset without reopening the old high-rise false-admit band.
    """
    if (
        not show.origin_reliable
        or not math.isfinite(show.font_size)
        or show.font_size <= 0.0
        or not math.isfinite(show.hscale)
        or show.hscale <= 0.0
        or not math.isfinite(show.rise)
        or not math.isfinite(advance)
    ):
        return None
    width = advance * (show.hscale / 100.0)
    if not math.isfinite(width):
        return None
    y0 = min(0.0, show.rise)
    y1 = max(0.0, show.rise) + 0.6 * show.font_size
    return (0.0, y0, width, y1)


def _painter_reach(
    page: fitz.Page, show: ShowOp, *, frame: PageVisualFrame | None = None
) -> tuple[float, float] | None:
    """Text-space extent beyond which a show's ink cannot mark this page.

    Used when the exact advance is unavailable (unresolvable font resource)
    or when the recorded origin cannot be trusted to be where the ink
    starts (``TJ`` may carry a leading kern that :class:`ShowOp` does not
    preserve).  Any point of the ink that lands inside the page is within
    ``half-diagonal + |origin − centre|`` of the origin, so dividing that
    by the mapped length of one text-space unit bounds the only extent that
    can ever be visible; ink past it is off-page and cannot survive as a
    ghost.  Returns that reach plus ``|v| / |u|``, the mapped y/x unit ratio
    needed to cover the cross-term under shear.  ``None`` when even that
    bound is not derivable.

    The bound presumes the text-space → visual map is INVERTIBLE: a band of
    text space has to arrive as a band.  Under a rank-deficient ``Tm``
    (``1 0 0 0``, or any pair of parallel mapped unit vectors) it arrives as
    a SEGMENT instead, every strict overlap against it measures zero on one
    axis, and a stroked collapsed outline — which paints a CTM-scaled pen
    bar straight across the target — reads as "provably disjoint".  That was
    a false safe in this arm from the start, in the reach and advance paths
    alike; the determinant test below closes it (matrix rows
    ``collapsed-tm-stroke-tr1``/``-tr2``).
    """
    origin = map_text_quad_to_visual(
        page, show.tm, show.ctm, (0.0, 0.0, 0.0, 0.0), frame=frame
    )
    unit = map_text_quad_to_visual(
        page, show.tm, show.ctm, (1.0, 0.0, 1.0, 0.0), frame=frame
    )
    vertical = map_text_quad_to_visual(
        page, show.tm, show.ctm, (0.0, 1.0, 0.0, 1.0), frame=frame
    )
    if not all(math.isfinite(value) for value in (*origin, *unit, *vertical)):
        return None
    ux, uy = unit[0] - origin[0], unit[1] - origin[1]
    vx, vy = vertical[0] - origin[0], vertical[1] - origin[1]
    scale = math.hypot(ux, uy)
    vertical_scale = math.hypot(vx, vy)
    determinant = ux * vy - uy * vx
    if (
        not math.isfinite(scale)
        or scale <= 0.0
        or not math.isfinite(vertical_scale)
        or not math.isfinite(determinant)
        # Rank-deficient: the mapped unit vectors are parallel (or one of
        # them is zero), so the reach quad collapses to a segment and proves
        # nothing on the axis it lost.
        or determinant == 0.0
    ):
        return None
    rect = page.rect
    span = math.hypot(rect.x1 - rect.x0, rect.y1 - rect.y0) / 2.0 + math.hypot(
        origin[0] - (rect.x0 + rect.x1) / 2.0,
        origin[1] - (rect.y0 + rect.y1) / 2.0,
    )
    reach = span / scale
    y_cross_ratio = vertical_scale / scale
    if not math.isfinite(reach) or not math.isfinite(y_cross_ratio):
        return None
    return reach, y_cross_ratio


# ------------------------------- exact painter geometry (P4-B2 slice 3b)
#
# A DECLARED ADVANCE IS NOT AN INK BOUND.  ``/W 0`` over a full-width glyph
# under-states the ink by a whole em; ``/W 1500`` over a 1000-unit glyph
# over-states it by half.  Both were false verdicts at the frozen P4-B1 tip
# (the 16 ``/W`` rows of ``test_p4b2_production_pins.py``), and neither is
# fixable by widening the quad, because the error has both signs.  For the
# CID population the document proves the real answer: the embedded outline.
#
# The arm below bounds BOTH painters from their own glyph programs and
# compares glyph against glyph.  Simple fonts keep the advance/reach path
# unchanged -- a stated residual, not an oversight: a simple-font glyph
# route needs ``cmap``/``Encoding`` -> gid, no measurement backs refusing
# every Latin document whose target word appears twice, and this arm is a
# net tightening only where it can see the outlines.

_Rect = tuple[float, float, float, float]


def _show_items(
    show: ShowOp, streams: Mapping[int, bytes] | None
) -> tuple[TjItem, ...] | None:
    """One show's operand as ordered string/kern items, or ``None``.

    ``Tj`` needs no stream: its whole operand is the recorded bytes.  ``TJ``
    does — :class:`ShowOp` drops the array's kern numbers, and a cursor
    replay without them places every glyph after the first in the wrong
    place.  ``'`` and ``"`` are refused outright: their recorded range folds
    a line break or a ``Tw``/``Tc`` assignment whose effect on the origin
    this arm does not prove.
    """
    if show.operator == "Tj":
        return (TjItem("string", show.decoded_bytes),)
    if show.operator != "TJ" or streams is None:
        return None
    stream = streams.get(show.stream_xref)
    if stream is None:
        return None
    return tj_items(stream, show)


def _painter_glyph_ink(
    page: fitz.Page,
    show: ShowOp,
    capability: IdentityHCidCapability,
    *,
    glyph_boxes: GlyphBoxCache,
    streams: Mapping[int, bytes] | None,
    frame: PageVisualFrame | None,
    cids: tuple[int, ...] | None = None,
) -> list[_Rect] | None:
    """Per-glyph ink boxes for one show, in visual space.

    ``None`` is AMBIGUOUS — the caller must fall back to a bound it can
    prove, never admit.  An empty list is the opposite kind of answer: the
    show is proven to paint nothing at all.

    ``cids`` replaces the shown string with an arbitrary CID sequence placed
    by THIS show's own cursor — how the target's replacement ink is bounded
    before it exists on the page.
    """
    if (
        not show.origin_reliable
        # A stroke or a clip adds ink the outline box does not carry (the
        # pen is CTM-scaled, and a clip's effect on later ink is invisible
        # here), so a non-fill mode is not boundable by this arm.
        or show.render_mode != 0
        or not math.isfinite(show.font_size)
        or show.font_size <= 0.0
        or not math.isfinite(show.hscale)
        or show.hscale == 0.0
        or not math.isfinite(show.rise)
    ):
        return None
    doc = page.parent
    if doc is None:
        return None
    units_per_em = glyph_boxes.units_per_em(doc, capability)
    if units_per_em is None:
        return None
    items = (
        _show_items(show, streams)
        if cids is None
        else (TjItem("string", capability.encode_cids(cids)),)
    )
    predicted = predict_glyphs(show, capability, items)
    if predicted.slug is not None:
        return None
    hscale = show.hscale / 100.0
    boxes: list[_Rect] = []
    for glyph in predicted.glyphs:
        unit_box = glyph_boxes.box(doc, capability, glyph.gid)
        units = unit_box.units
        if unit_box.reason is not None or units is None:
            return None
        if units[2] <= units[0] or units[3] <= units[1]:
            # A blank ``loca`` span: proven to paint nothing, so it widens
            # no union.  Distinct from a refusal, which returns None above.
            continue
        text = scale_units_to_text(units, units_per_em, show.font_size, hscale)
        quad = (
            text[0] + glyph.cursor_x,
            text[1] + show.rise,
            text[2] + glyph.cursor_x,
            text[3] + show.rise,
        )
        visual = map_text_quad_to_visual(
            page, show.tm, show.ctm, quad, frame=frame
        )
        if not all(math.isfinite(value) for value in visual):
            return None
        boxes.append(visual)
    return boxes


def _glyph_ink_overlap(
    target_boxes: list[_Rect], twin_boxes: list[_Rect]
) -> tuple[float, float] | None:
    """Depths of the first strictly overlapping (target, twin) glyph pair.

    STRICTLY POSITIVE on both axes IS the overlap test here — no epsilon.
    In an EXACT ink test a tolerance runs the wrong way: it subtracts from a
    bound that is already the conservative one, so every fraction of a point
    it forgives is real ink the arm admits blind.  The margin this arm needs
    is already spent, outward, in the box itself: one font unit of pad on
    every side (:mod:`model.text_commit.glyph_boxes`), which absorbs the lsb
    shift and the control-box/outline gap.  Padding outward and then
    forgiving inward would cancel the only safety the pad buys.

    The advance/reach path in :func:`duplicate_source_painter_detail` and
    the simple-font advance path keep their 0.05 pt tolerance, and that is
    not an inconsistency: those bound ink by a DECLARED ADVANCE plus a
    baseline band, a bound whose residual is a fraction of an em in BOTH
    directions, so 0.05 pt there only forgives quantization inside a bound
    that is already loose by orders of magnitude more.  Here it would be
    carving ink out of a bound that is tight by construction.  Different
    bounds, different residuals — do not unify the two numbers.

    The aggregate AABBs are tested first: two words on the same baseline
    that merely share a bounding box (a positive ``Tc`` gap straddling the
    target, say) are dismissed in one comparison instead of ``n x m``.  The
    prefilter can only ADMIT — every pair it skips is inside an aggregate
    pair that was already disjoint — so it never hides an overlap.
    """
    if not target_boxes or not twin_boxes:
        return None  # one of the two painters paints nothing
    aggregate = _strict_overlap_depths(
        rect_union(target_boxes), rect_union(twin_boxes)
    )
    if aggregate[0] <= 0.0 or aggregate[1] <= 0.0:
        return None  # touching (depth 0) is not overlapping
    for target_box in target_boxes:
        for twin_box in twin_boxes:
            depths = _strict_overlap_depths(target_box, twin_box)
            if depths[0] > 0.0 and depths[1] > 0.0:
                return depths
    return None


def _twin_stroke_outset(
    page: fitz.Page, twin: ShowOp, *, frame: PageVisualFrame | None
) -> float | None:
    """The conservative visual outset for a NON-FILL twin, or ``None``.

    T16-4X S1 review M2.  Step 9 grew the TARGET's core by the pen the show
    gate proved for it and left every twin on its bare advance core, so a
    same-bytes twin painting at ``2 Tr 5 w 10 M`` was called disjoint 0.1 pt
    clear of a fill-mode target while its rendered stroke ink reached
    0.208 pt INTO that target's core (measured; the gate's tolerance is
    0.05 pt).  Nothing about the target was wrong -- the ink that lands on
    the edit is the TWIN's, and the twin's pen was simply never read.

    ``None`` means "no bound this function can compute", and every caller
    turns that into a refusal, never into "no outset":

    * a mode this tier's ladder does not admit -- 1 (stroke-only ink, which
      an advance core does not bound at all) and 4-7 (glyphs added to the
      CLIPPING PATH, a persistent effect on everything painted afterwards).
      Mode 3 paints nothing today, but it is refused with them rather than
      treated as a fill: S7 is the slice that decides what an invisible show
      means, and a gate that silently admitted mode 3 now would have to be
      re-derived then.
    * a pen ``_resolve_stroke_pen`` cannot replay -- the SAME ordered proof
      the target's pen goes through (ExtGState included), so a twin whose
      ``gs`` sets ``/LW`` after its ``w`` is bounded by what it actually
      renders.  Not ``_prove_stroke_pen``: that adds the
      ``STROKE_BOUND_TOO_LARGE`` ceiling, which exists to keep V0d's halo
      meaningful for the show being EDITED and has nothing to say about how
      far a neighbour's ink reaches.
    * an outset that is not provable in visual space (a ``0 w`` hairline
      renders device-thinnest, which a half-pen bound understates; a
      non-finite pen or a degenerate frame).
    """
    if twin.render_mode == 0:
        return None  # a fill-mode twin strokes nothing; caller skips the outset
    if twin.render_mode != 2:
        return None
    page_frame = frame if frame is not None else page_visual_frame_or_none(page)
    if page_frame is None:
        return None
    pen = _resolve_stroke_pen(page.parent, page, twin)
    if isinstance(pen, PlanRejection):
        return None
    return _stroke_outset_visual(twin, frame=page_frame, pen=pen, conservative=True)


def duplicate_source_painter_detail(
    page: fitz.Page,
    target: ShowOp,
    *,
    target_text: str,
    target_capability: FontCapability,
    source_advance: float,
    registry: DocumentFontRegistry,
    shows: tuple[ShowOp, ...],
    capabilities: dict[str, FontCapability] | None = None,
    streams: Mapping[int, bytes] | None = None,
    replacement_cids: tuple[int, ...] | None = None,
    glyph_boxes: GlyphBoxCache | None = None,
    frame: PageVisualFrame | None = None,
    pen: StrokePen | None = None,
) -> str | None:
    """Describe an indistinguishable overlapping source painter, if any.

    Candidacy is SEMANTIC: the same encoding bytes shown from a font that
    paints the same glyphs, whatever resource name each show reached it
    through.  A candidate whose identity AND placement are both provable is
    measured from its OWN text state — its capability's width for
    ``target_text`` at its own size, its own ``Tc``/``Tw``/``Tz`` — never
    from the target's advance scaled by a ratio.  Anything less than proven
    is not rejected outright: its ink is bounded by :func:`_painter_reach`,
    so a twin that provably cannot reach the target core (a different line,
    the far side of the page) stays admissible and only a twin that could
    overlap fails closed.

    P4-B2 slice 3b adds an EXACT-FIRST arm for the CID population, taken
    whenever the caller supplies ``glyph_boxes`` (a
    :class:`~model.text_commit.glyph_boxes.GlyphBoxCache`) AND
    ``replacement_cids``: both painters are then bounded by their own
    embedded outlines rather than by a declared advance, and only a twin
    whose GLYPH INK meets the target's -- the source ink and the
    replacement's alike -- is refused.  A caller that supplies neither (the
    census, the funnel diagnostics) keeps the pre-slice behaviour verbatim,
    string for string.  Within the arm, anything the outline cannot prove
    -- a non-fill render mode, an unresolvable gid, a ``TJ`` whose kerns do
    not re-lex -- falls to the SAME reach bound as before, never to the
    declared advance.

    ``pen`` (T16-4 Step 9) is the target's PROVEN stroke pen, and its
    presence IS the mode-2 signal: ``tier0_show_gate`` produces a
    :class:`StrokePen` only for a ``render_mode == 2`` show it admitted,
    and ``None`` for the fill mode, which strokes nothing.  When it is
    supplied, ``target_core`` grows on every side by the CONSERVATIVE
    outset (``_stroke_outset_visual(conservative=True)``) BEFORE any twin
    is compared against it, because the advance core bounds the FILL leg
    only and the stroke leg paints past it -- by half the pen on a plain
    join and, on an acute miter vertex, by up to 4.54x that (E6).  D4's
    direction of error at this site is the false-SAFE one: a twin admitted
    over stroked ink is silently damaged, so the miter factor is mandatory
    here and must stay out of the honest ``target_bbox`` bound.  A caller
    that supplies no pen (``scripts/measure_type0_funnel.py``, the census)
    keeps today's un-outset comparison verbatim -- correct for the fill
    mode it measures, and an UNDER-bound for a mode-2 target, which is why
    the production call site passes ``ShowGateAdmission.pen``.

    The TWIN side of that outset is symmetric and needs no parameter
    (T16-4X S1 review M2): every candidate whose ``render_mode`` is not 0
    grows its own core by its OWN conservative bound, resolved through
    :func:`_twin_stroke_outset` from the pen the twin's stream actually
    replays.  A twin in a mode the ladder does not admit (1, 3, 4-7), or one
    whose pen cannot be replayed, has no bound at all, and is refused with
    the same "cannot prove target placement" string the target's own
    unprovable bound returns -- UNLESS the un-outset comparison already
    refuses it, in which case the older, more specific verdict (the measured
    core overlap, or the reach string) stands.  Growing a box is monotone on
    the overlap predicate, so that ordering changes which sentence a refusal
    carries and never which pages are admitted: the outset moves where the
    boundary is, it never adds a verdict.  Applying
    it to a FILL-mode twin would be wrong in the other direction: a
    ``0 Tr`` show strokes nothing however wide the ``w`` before it, and
    outsetting it would refuse every page that sets a line width ahead of
    its text.
    """
    twins = tuple(
        candidate
        for candidate in shows
        if candidate.seq != target.seq
        and candidate.decoded_bytes == target.decoded_bytes
    )
    if not twins:
        return None
    target_quad = _painter_core_quad(target, source_advance)
    if target_quad is None:
        return "identical source painter cannot prove target placement"
    target_core = map_text_quad_to_visual(
        page, target.tm, target.ctm, target_quad, frame=frame
    )
    if not all(math.isfinite(value) for value in target_core):
        return "identical source painter cannot prove target placement"
    if pen is not None:
        # The stroked target's ink escapes its advance core by the pen, so
        # the core is grown before -- never after -- the twin comparison
        # below.  Placed after the ``if not twins`` early-out so a page with
        # no same-bytes painter pays nothing for it.
        page_frame = frame if frame is not None else page_visual_frame_or_none(page)
        outset = (
            None
            if page_frame is None
            else _stroke_outset_visual(
                target, frame=page_frame, pen=pen, conservative=True
            )
        )
        if outset is None:
            # Unreachable from the production caller (``tier0_show_gate``
            # proved this exact bound before it handed the pen over), but a
            # bound that cannot be computed is not a bound: reuse the
            # target-placement string rather than compare against a core
            # known to be too small.
            return "identical source painter cannot prove target placement"
        target_core = (
            target_core[0] - outset,
            target_core[1] - outset,
            target_core[2] + outset,
            target_core[3] + outset,
        )
    # One resolve per DISTINCT candidate resource, not one per candidate:
    # ``registry.capability`` re-digests the whole font entry on every call
    # (~0.9 ms warm), which a dense same-string bucket would otherwise turn
    # into a quarter-second per prepare.  A caller that already holds the
    # page's capabilities (the census, which runs this per show) passes them
    # in and pays nothing here at all.
    # The exact arm's precondition: a CID target, a cache to read outlines
    # through, and the replacement CIDs, because the ink this edit is about
    # to PAINT counts as much as the ink it replaces.  Missing any of the
    # three leaves every twin on the pre-slice path.
    target_cid = target_capability.cid
    exact_enabled = (
        glyph_boxes is not None
        and replacement_cids is not None
        and target_cid is not None
    )
    target_ink: list[_Rect] | None = None
    target_ink_measured = False

    resolved: dict[str, FontCapability | None] = {}
    for candidate in twins:
        resource = candidate.font_resource or ""
        if capabilities is not None:
            capability = capabilities.get(resource)
        elif resource in resolved:
            capability = resolved[resource]
        else:
            capability = registry.capability(page, resource) if resource else None
            resolved[resource] = capability
        same_font = _same_font_object(capability, target_capability)
        candidate_quad: tuple[float, float, float, float] | None = None
        unproven = "" if same_font is True else "font identity"
        # An ambiguous exact verdict must NOT fall back to the declared
        # advance -- that is the bound this arm exists to distrust -- so it
        # forces the reach branch, with the pre-slice "exact extent"
        # semantics intact.
        force_reach = False
        candidate_cid = capability.cid if capability is not None else None
        if exact_enabled and candidate_cid is not None:
            assert glyph_boxes is not None and target_cid is not None
            assert replacement_cids is not None
            if not target_ink_measured:
                target_ink_measured = True
                source_ink = _painter_glyph_ink(
                    page,
                    target,
                    target_cid,
                    glyph_boxes=glyph_boxes,
                    streams=streams,
                    frame=frame,
                )
                after_ink = _painter_glyph_ink(
                    page,
                    target,
                    target_cid,
                    glyph_boxes=glyph_boxes,
                    streams=streams,
                    frame=frame,
                    cids=replacement_cids,
                )
                if source_ink is not None and after_ink is not None:
                    target_ink = source_ink + after_ink
            if target_ink is None:
                # Same string the advance quad emits for the same failure:
                # nothing about THIS target's placement is provable, and no
                # twin can change that.
                return "identical source painter cannot prove target placement"
            candidate_ink = _painter_glyph_ink(
                page,
                candidate,
                candidate_cid,
                glyph_boxes=glyph_boxes,
                streams=streams,
                frame=frame,
            )
            if candidate_ink is not None:
                depths = _glyph_ink_overlap(target_ink, candidate_ink)
                if depths is None:
                    continue  # proven disjoint outlines; next twin
                # ``.4g``, not ``.3f``: with the strict-positive rule a
                # refusal can now be a hundredth of a point deep, and
                # "overlaps ... by 0.000pt x 0.000pt" would read as a bug
                # in the gate rather than as the measurement it is.
                return (
                    "identical source painter's glyph ink overlaps the "
                    f"target ink by {depths[0]:.4g}pt x {depths[1]:.4g}pt"
                )
            force_reach = True
        simple_round_trip = (
            capability is not None
            and capability.cid is None
            and capability.advance_source == "widths"
            and capability.encode_simple(target_text) == candidate.decoded_bytes
        )
        exact_extent = (
            not force_reach
            and capability is not None
            and candidate.operator == "Tj"
            and (
                same_font is True
                or capability.cid is not None
                or simple_round_trip
            )
        )
        if exact_extent:
            assert capability is not None
            candidate_advance = _painter_advance(capability, candidate, target_text)
            if candidate_advance is not None:
                candidate_quad = _painter_core_quad(candidate, candidate_advance)
        if candidate_quad is None:
            if same_font is True:
                unproven = "exact extent"
            reach_proof = _painter_reach(page, candidate, frame=frame)
            baseline = _painter_core_quad(candidate, 0.0)
            if reach_proof is None or baseline is None:
                return "identical source painter cannot prove disjoint placement"
            reach, y_cross_ratio = reach_proof
            x_pad = max(abs(baseline[1]), abs(baseline[3])) * y_cross_ratio
            if not math.isfinite(x_pad):
                return "identical source painter cannot prove disjoint placement"
            # ``TJ`` is bounded in BOTH directions: replay drops the array's
            # numeric items, so a leading kern may have displaced the ink
            # either way from the recorded origin.
            candidate_quad = (
                (0.0 if candidate.operator == "Tj" else -reach) - x_pad,
                baseline[1],
                reach + x_pad,
                baseline[3],
            )
        candidate_core = map_text_quad_to_visual(
            page, candidate.tm, candidate.ctm, candidate_quad, frame=frame
        )
        if not all(math.isfinite(value) for value in candidate_core):
            return "identical source painter cannot prove disjoint placement"
        if candidate.render_mode != 0:
            # T16-4X S1 review M2: the SYMMETRIC outset.  A stroked twin's
            # ink escapes its own advance core by its own pen, so its core
            # grows the same way the target's did above -- in VISUAL space,
            # after the quad is mapped, so the two boxes stay commensurate
            # at ``_strict_overlap_depths``.  Only the mode-2 twin has a
            # computable bound; every other non-fill mode, and every pen
            # this planner cannot replay, reuses the EXISTING placement
            # string rather than compare against a core known to be too
            # small (no new code, no new reason, no new sentence).
            twin_outset = _twin_stroke_outset(page, candidate, frame=frame)
            if twin_outset is None:
                # Refuse -- but only once the UN-outset comparison below has
                # had its say.  An outset only ever GROWS the twin's core, so
                # it is monotone on the overlap predicate: a twin the bare
                # boxes already refuse is refused under any outset, and the
                # order decides the SENTENCE, never the verdict.  Refusing
                # here first would overwrite every older, more specific
                # string on an unboundable twin -- the measured core overlap,
                # and the "cannot prove exact extent" reach string the CID
                # population reaches through ``force_reach`` -- with a
                # blanket one that says less.
                bare = _strict_overlap_depths(target_core, candidate_core)
                if bare[0] <= 0.05 or bare[1] <= 0.05:
                    return (
                        "identical source painter cannot prove target placement"
                    )
            else:
                candidate_core = (
                    candidate_core[0] - twin_outset,
                    candidate_core[1] - twin_outset,
                    candidate_core[2] + twin_outset,
                    candidate_core[3] + twin_outset,
                )
        overlap_x, overlap_y = _strict_overlap_depths(target_core, candidate_core)
        if overlap_x > 0.05 and overlap_y > 0.05:
            if unproven:
                return (
                    f"identical source painter cannot prove {unproven}, and "
                    "its bounded ink can reach the target core"
                )
            return (
                "identical source painter overlaps target core by "
                f"{overlap_x:.3f}pt x {overlap_y:.3f}pt"
            )
    return None


def _content_token(
    fingerprint: str,
    replacement: StreamReplacement,
    *,
    target_bbox: tuple[float, float, float, float] | None = None,
    verify_bbox: tuple[float, float, float, float] | None = None,
    source_advance: float = 0.0,
    replacement_advance: float = 0.0,
    kern_adjustment: float = 0.0,
    font_resource: str = "",
    font_xref: int = 0,
    style_overrides: StyleOverrides | None = None,
    geometry_intent: tuple[float, float, float, float] | None = None,
    growth_direction: str | None = None,
    splice_kind: str = SPLICE_KIND_STRING_TOKEN,  # dto.SPLICE_KIND_* vocabulary
) -> str:
    """Content-derived plan token shared by every tier and by preview.

    Preimage includes full candidate semantics: page fingerprint, splice
    coordinates, replacement bytes, target/verify bboxes, advance pair,
    kern adjustment, font identity, style intent, geometry intent, and the
    splice grammar. Two candidates that differ in any property always
    produce different tokens.
    """
    bbox_str = ",".join(f"{v:.6f}" for v in target_bbox) if target_bbox else ""
    vbbox_str = ",".join(f"{v:.6f}" for v in verify_bbox) if verify_bbox else ""
    style_str = (
        "|".join(
            (
                style_overrides.font_family or "",
                ""
                if style_overrides.font_size is None
                else f"{style_overrides.font_size:.6f}",
                ""
                if style_overrides.color is None
                else ",".join(
                    f"{value:.6f}" for value in style_overrides.color
                ),
            )
        )
        if style_overrides is not None and style_overrides.changed
        else ""
    )
    geometry_str = (
        ",".join(f"{value:.6f}" for value in geometry_intent)
        if geometry_intent is not None
        else ""
    )
    return hashlib.sha256(
        "|".join(
            (
                fingerprint,
                str(replacement.stream_xref),
                str(replacement.start),
                str(replacement.end),
                replacement.replacement_bytes.hex(),
                bbox_str,
                vbbox_str,
                f"{source_advance:.6f}",
                f"{replacement_advance:.6f}",
                f"{kern_adjustment:.6f}",
                font_resource,
                str(font_xref),
                style_str,
                geometry_str,
                growth_direction or "",
                splice_kind,
            )
        ).encode("ascii")
    ).hexdigest()


def _read_one_stream(doc: fitz.Document, xref: int) -> bytes | None:
    """The decoded bytes of ONE content stream, or ``None``.

    The fallback for a :func:`tier0_show_gate` caller that did not pass its
    streams (the audit instrument).  Reads only the stream the show names,
    never the whole page, and answers ``None`` rather than raising -- an
    unreadable operand must reach the caller as a refusal, not an
    exception.
    """
    try:
        return doc.xref_stream(xref) or b""
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        # The same tuple ``inspect._page_contents_xrefs`` uses: MuPDF's own
        # error class does NOT derive from RuntimeError.
        logger.debug("content stream %s is unreadable", xref, exc_info=True)
        return None


def _tj_inner_item_span(
    show: ShowOp, stream: bytes | None
) -> TjSpan | PlanRejection:
    """The single inner string item of an admissible ``TJ``, or a refusal.

    Three independent verdicts, three codes (T16-4X S1): the operand range
    must re-lex to the recorded operand (``TJ_ITEM_RELEX_FAILED``), it must
    carry exactly one string item (``TJ_MULTI_ITEM_ARRAY`` -- kerns BETWEEN
    items are S4's problem), and no kern may PRECEDE that item
    (``TJ_LEADING_KERN_UNPROVEN``: a leading kern displaces the ink from
    ``origin_user``, which :func:`_painter_core_quad` and the
    ``target_bbox`` fallback both take as the ink origin).  Kerns AFTER the
    item are admitted -- their bytes lie outside the spliced range and stay
    byte-identical, so the advance they contribute is unchanged.
    """
    spans = tj_item_spans(stream, show) if stream is not None else None
    if spans is None:
        return PlanRejection(
            RejectReason.TJ_ITEM_RELEX_FAILED,
            "TJ operand byte range does not re-lex to the recorded operand",
        )
    strings = [span for span in spans if span.kind == "string"]
    if len(strings) != 1:
        return PlanRejection(
            RejectReason.TJ_MULTI_ITEM_ARRAY,
            f"TJ array carries {len(strings)} string items; Tier 0 splices "
            "exactly one",
        )
    item = strings[0]
    if any(span.kind == "kern" and span.start < item.start for span in spans):
        return PlanRejection(
            RejectReason.TJ_LEADING_KERN_UNPROVEN,
            "a kern precedes the TJ array's only string item, displacing its "
            "ink from the recorded show origin",
        )
    return item


# The bounded ``/Parent`` walk for an INHERITED ``/Resources`` dict.  Four
# hops is the same budget ``marked_content._deref`` uses for indirect
# references: deeper page trees exist, but a page whose resources are that
# far away is not evidence this gate should spend an unbounded walk on --
# and the walk must terminate even on a cyclic ``/Parent``.
_MAX_RESOURCE_PARENT_HOPS = 8
_PEN_READ_ERRORS = (RuntimeError, ValueError, fitz.mupdf.FzErrorBase)


def _deref_object(doc: fitz.Document, value: object, *, hops: int = 4) -> object:
    """Follow indirect-reference chains to a parsed object, bounded.

    ``model/text_commit/marked_content.py`` carries the same private helper
    for the ``/Properties`` lookup; both are three lines over the shared
    ``cid_fonts`` parser, and neither module imports the other.
    """
    while isinstance(value, PdfRef) and hops > 0:
        try:
            value = parse_pdf_value(doc.xref_object(value.xref))
        except _PEN_READ_ERRORS:
            return None
        hops -= 1
    return value


def _extgstate_resources(
    doc: fitz.Document, page: fitz.Page
) -> dict[str, object] | None:
    """The page's EFFECTIVE ``/Resources /ExtGState`` mapping, or ``None``.

    ``/Resources`` is an INHERITABLE page attribute, so a page carrying
    none of its own takes the nearest ancestor's whole dictionary -- hence
    the bounded ``/Parent`` walk.  Inheritance is all-or-nothing at the
    dictionary level: once a ``/Resources`` dict is found, a missing
    ``/ExtGState`` inside it means the page HAS no ExtGState resources, not
    that the search continues upward.

    ``None`` covers "no ``/ExtGState``", "unreadable" and "not a
    dictionary" alike -- every one of them makes a named ``gs`` lookup
    unprovable, which is what the caller refuses on.
    """
    xref = page.xref
    seen: set[int] = set()
    for _ in range(_MAX_RESOURCE_PARENT_HOPS):
        if xref in seen:
            return None  # cyclic /Parent chain
        seen.add(xref)
        try:
            node = parse_pdf_value(doc.xref_object(xref))
        except _PEN_READ_ERRORS:
            return None
        if not isinstance(node, dict):
            return None
        raw_resources = node.get("Resources")
        if raw_resources is not None:
            resources = _deref_object(doc, raw_resources)
            if not isinstance(resources, dict):
                return None
            extgstate = _deref_object(doc, resources.get("ExtGState"))
            return extgstate if isinstance(extgstate, dict) else None
        parent = node.get("Parent")
        if not isinstance(parent, PdfRef):
            return None
        xref = parent.xref
    return None


def _finite_number(value: object) -> float | None:
    """``value`` as a float when it is a finite PDF number, else ``None``.

    ``bool`` is an ``int`` subclass in Python, so ``/LW true`` would read as
    width ``1.0`` without the explicit exclusion -- a wrong pen silently
    admitted, which is the direction this gate must never fail in.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _resolve_stroke_pen(
    doc: fitz.Document, page: fitz.Page, show: ShowOp
) -> StrokePen | PlanRejection:
    """The show's stroke pen, replayed IN ORDER, or a refusal.

    Tandem plan D8: replay CAPTURES the ExtGState resource names and the
    pen operands (it has no document handle and gains none); the PLANNER
    resolves the names against the page's ``/Resources /ExtGState``.

    The pen starts from the INITIAL GRAPHICS STATE (width 1.0, join 0,
    miter limit 10.0 -- ISO 32000-1 8.4.1 Table 52) and
    ``show.pen_events`` is applied entry by entry, in execution order:

    * ``("w", x)`` / ``("j", x)`` / ``("M", x)`` => assign that component.
    * ``("gs", name)`` => resolve the ExtGState and apply ``/LW``, ``/LJ``,
      ``/ML`` if PRESENT.  Unresolvable resource dictionary, unresolvable
      or non-dictionary object, or a present key that is non-finite or of
      the wrong type => refuse ``STROKE_BOUND_UNPROVEN``: what that ``gs``
      did to the pen is simply not knowable, and a stroke bound over an
      unknown pen is not a bound.
    * a key ABSENT from a readable ExtGState => leave that component of the
      pen unchanged.  This is E8's branch and, per the plan's Step 0
      re-run, the office fixture's real path: its two ExtGState objects
      declare only ``/BM``/``/ca``/``/CA``, and in fact none of them is
      even in scope at a mode-2 show, so ``pen_events`` there carries no
      ``gs`` entry at all.  A blanket "any ``gs`` => unprovable" rule would
      refuse both shapes and silently kill the feature.
    * ``(op, None)`` -- replay's malformed-operand entry (a missing,
      non-numeric or non-finite ``w``/``M``, a non-integral ``j``, a
      nameless ``gs``) => refuse ``STROKE_BOUND_UNPROVEN`` naming the
      operator.  Replay deliberately does not mimic MuPDF's reset-to-zero
      recovery; the planner must refuse, not guess one renderer's.

    ``ShowOp``'s ``line_width``/``line_join``/``miter_limit`` scalars are
    NOT read here (they stay for the instruments).  T16-4 S1 review H1: the
    first spelling applied a present ``/LW`` over the recorded ``w``
    whichever ran LAST, so ``/GS1 gs 5 w 2 Tr`` with ``/GS1 <</LW 0.1>>``
    -- measured rendering the 5.0 pen -- was proved with 0.1, defeating the
    ``STROKE_BOUND_TOO_LARGE`` ceiling the gs-less twin page refuses at
    4.167x and shrinking the duplicate-gate outset from 25 pt to 0.5 pt.
    The scalars are also the wrong evidence for H3: a malformed ``w``
    parks the scalar on ``nan``, which a later ``gs`` carrying ``/LW``
    silently overwrites -- on exactly the pages H1 is about.
    """
    width = _PDF_DEFAULT_LINE_WIDTH
    line_join = _PDF_DEFAULT_LINE_JOIN
    miter_limit = _PDF_DEFAULT_MITER_LIMIT
    # Resolved on the FIRST ``gs`` event and reused: a page with no ``gs``
    # in scope (the fixture's own shape) must not pay for the parent walk,
    # and a page with several must not repeat it.
    resources: dict[str, object] | None = None
    resources_read = False
    for operator, value in show.pen_events:
        if value is None:
            return PlanRejection(
                RejectReason.STROKE_BOUND_UNPROVEN,
                f"render_mode={show.render_mode} malformed {operator} operand; "
                "the renderer's pen cannot be proven",
            )
        if operator == "w" or operator == "M":
            number = _finite_number(value)
            if number is None:
                # Unreachable from replay (it logs ``(op, None)`` for every
                # malformed shape) -- fail closed rather than coerce.
                return PlanRejection(
                    RejectReason.STROKE_BOUND_UNPROVEN,
                    f"render_mode={show.render_mode} recorded {operator} "
                    "operand is not a finite number",
                )
            if operator == "w":
                width = number
            else:
                miter_limit = number
        elif operator == "j":
            if isinstance(value, bool) or not isinstance(value, int):
                return PlanRejection(
                    RejectReason.STROKE_BOUND_UNPROVEN,
                    f"render_mode={show.render_mode} recorded j operand is "
                    "not an integer line join",
                )
            line_join = int(value)
        elif operator == "gs":
            if not isinstance(value, str):
                return PlanRejection(
                    RejectReason.STROKE_BOUND_UNPROVEN,
                    f"render_mode={show.render_mode} recorded gs operand is "
                    "not a resource name",
                )
            if not resources_read:
                resources = _extgstate_resources(doc, page)
                resources_read = True
            if resources is None:
                return PlanRejection(
                    RejectReason.STROKE_BOUND_UNPROVEN,
                    f"render_mode={show.render_mode} applies an ExtGState, but "
                    "the page's /Resources /ExtGState dictionary is not readable",
                )
            applied = _apply_extgstate_pen(
                doc, show, resources, value, width, line_join, miter_limit
            )
            if isinstance(applied, PlanRejection):
                return applied
            width, line_join, miter_limit = applied
        else:
            # An event kind replay does not emit today.  Refusing is the
            # only fail-closed reading: a pen operator this function does
            # not model has an unknown effect on the rendered stroke.
            return PlanRejection(
                RejectReason.STROKE_BOUND_UNPROVEN,
                f"render_mode={show.render_mode} recorded an unmodelled pen "
                f"event {operator!r}",
            )
    return StrokePen(width=width, line_join=line_join, miter_limit=miter_limit)


def _apply_extgstate_pen(
    doc: fitz.Document,
    show: ShowOp,
    resources: dict[str, object],
    name: str,
    width: float,
    line_join: int,
    miter_limit: float,
) -> tuple[float, int, float] | PlanRejection:
    """One ``gs``'s effect on the pen, or a refusal.

    Split out of :func:`_resolve_stroke_pen` so the ordered replay above
    reads as a ladder of events rather than a loop with a loop inside it.
    Every refusal string here is verbatim what the pre-ordering spelling
    produced -- the ordering fix moves WHEN these run, never what they say.
    """
    entry = _deref_object(doc, resources.get(name))
    if not isinstance(entry, dict):
        # Name-free detail (§10 privacy): a resource name is producer
        # metadata, and the code alone attributes the refusal.
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} applies an ExtGState the "
            "page does not resolve to a readable dictionary",
        )
    if "LW" in entry:
        value = _finite_number(entry["LW"])
        if value is None:
            return PlanRejection(
                RejectReason.STROKE_BOUND_UNPROVEN,
                f"render_mode={show.render_mode} ExtGState /LW is not a "
                "finite number",
            )
        width = value
    if "LJ" in entry:
        raw_join = entry["LJ"]
        if isinstance(raw_join, bool) or not isinstance(raw_join, int):
            return PlanRejection(
                RejectReason.STROKE_BOUND_UNPROVEN,
                f"render_mode={show.render_mode} ExtGState /LJ is not an "
                "integer line join",
            )
        line_join = int(raw_join)
    if "ML" in entry:
        value = _finite_number(entry["ML"])
        if value is None:
            return PlanRejection(
                RejectReason.STROKE_BOUND_UNPROVEN,
                f"render_mode={show.render_mode} ExtGState /ML is not a "
                "finite number",
            )
        miter_limit = value
    return (width, line_join, miter_limit)


def _prove_stroke_pen(
    doc: fitz.Document,
    page: fitz.Page,
    show: ShowOp,
    *,
    frame: PageVisualFrame | None,
) -> StrokePen | PlanRejection:
    """The mode-2 admission proof: a pen that is BOTH known and in scope.

    Two independent verdicts, two codes (§Fail-closed gates): the pen is
    not knowable (``STROKE_BOUND_UNPROVEN`` -- an unreadable ExtGState, a
    malformed operand, a ``0 w`` hairline, which renders device-thinnest
    and so is not bounded by half of it, an undefined join or a
    spec-illegal miter limit, an unprovable page frame), or it is known and
    too fat for the halo to prove anything (``STROKE_BOUND_TOO_LARGE``).

    The join and miter-limit refusals are T16-4 S1 review H2's, and they
    run BEFORE the ceiling so it never sees a value it would have to
    floor.  Admission is a stricter test than the BOUND
    :func:`_stroke_outset_visual` computes: that helper treats an undefined
    join as a miter and floors ``M`` at 1.0 (a bound is still a bound),
    while a show admitted here must have a pen the planner can PROVE.  An
    ``M < 1`` is spec-illegal (ISO 32000-1 8.5.2) and a join outside
    ``{0, 1, 2}`` is renderer-defined -- neither is a pen, so neither is
    floored into an admission.
    """
    resolved = _resolve_stroke_pen(doc, page, show)
    if isinstance(resolved, PlanRejection):
        return resolved
    pen = resolved
    if not math.isfinite(pen.width) or pen.width == 0.0:
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} pen width {pen.width} is not "
            "provable ('0 w' renders device-thinnest, which a half-pen "
            "bound understates)",
        )
    if pen.line_join not in _DEFINED_LINE_JOINS:
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} line join {pen.line_join} is "
            "outside 0-2, so what it paints is renderer-defined",
        )
    if not math.isfinite(pen.miter_limit) or pen.miter_limit < _MIN_MITER_LIMIT:
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} miter limit {pen.miter_limit} is "
            "below the spec minimum of 1, so the pen is not provable",
        )
    if not math.isfinite(show.font_size) or show.font_size <= 0.0:
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} font_size={show.font_size} "
            "leaves the stroke bound unprovable",
        )
    reach = abs(pen.width) * max(pen.miter_limit, _MIN_MITER_LIMIT)
    if not math.isfinite(reach):
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} miter limit {pen.miter_limit} "
            "leaves the stroke bound unprovable",
        )
    ceiling = 0.5 * show.font_size
    if reach > ceiling:
        return PlanRejection(
            RejectReason.STROKE_BOUND_TOO_LARGE,
            f"render_mode={show.render_mode} stroke bound is "
            f"{reach / ceiling:.3f}x the 0.5*font_size ceiling "
            f"(abs(w)*max(M,1.0)={reach:.5f}, 0.5*font_size={ceiling:.5f})",
        )
    page_frame = frame if frame is not None else page_visual_frame_or_none(page)
    if page_frame is None:
        # Unreachable from either production caller (``_classify_common``
        # refuses PAGE_GEOMETRY_UNSUPPORTED first; the audit refuses the
        # show before it calls this gate) -- fail closed rather than guess
        # a frame the pen bound would be silently wrong in.
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} page visual frame is not "
            "provable, so the stroke outset is not either",
        )
    if (
        _stroke_outset_visual(show, frame=page_frame, pen=pen, conservative=True)
        is None
    ):
        return PlanRejection(
            RejectReason.STROKE_BOUND_UNPROVEN,
            f"render_mode={show.render_mode} stroke outset is not provable "
            "in visual space",
        )
    return pen


def tier0_show_gate(
    doc: fitz.Document,
    page: fitz.Page,
    show: ShowOp,
    *,
    wrappers: tuple[McWrapper, ...],
    emc_underflows: int,
    registry: DocumentFontRegistry,
    streams: Mapping[int, bytes] | None = None,
    frame: PageVisualFrame | None = None,
) -> ShowGateAdmission | PlanRejection:
    """The show-level Tier 0 ladder: everything the SHOW alone decides.

    Extracted verbatim from :func:`_classify_common` (T16-4X S1, plan
    §8.6) so the one production ladder is also what the audit instrument
    runs.  Gate order and every detail string are pinned by
    ``test_text_commit_structural_gates.py``.  In order:

    1. operator/``string_kind`` is a complete single-string ``Tj``, or a
       ``TJ`` whose array holds exactly one string item with no kern
       before it (T16-4X S1)
    2. ``rise``, then the render-mode ladder: mode 0 admitted, mode 2
       admitted with a PROVEN stroke pen, every other mode refused by name
       (T16-4 Steps 7-8)
    3. horizontal scale (``Tz``) is positive and finite
    4. the marked-content wrapper stack (``admit_show_wrappers``)
    5. a font resource is selected at the show
    6. that resource resolves to a capability on this page
    7. the capability's own Tier 0 refusal (Type0 details stay code-only)
    8. the Type0 hex-only operand scope

    Replacement-independent BY CONTRACT: nothing here may read the
    replacement text, the target text or the caller's geometry -- those
    gates stay in :func:`_classify_common` on either side of this call.
    The gates BEFORE it there (the quote operators, then the shared
    content stream) are deliberately not folded in: the first is a
    document-order pin between them, and the second is a property of the
    DOCUMENT, not of the show.

    ``wrappers``/``emc_underflows`` are the show's resolved marked-content
    stack and the page's EMC underflow count (``SourceSpanBinding``'s
    ``mc_wrappers``/``mc_emc_underflows``, or ``PageReplay.wrappers_for``
    plus ``mc_emc_underflows`` for a caller that never binds).

    ``streams`` maps stream xref -> decoded bytes; the ``TJ`` rung re-lexes
    the show's own operand from them.  A caller that already holds the
    page's streams should pass them.  When it does not, this reads the one
    stream the show names -- correct, but one decode per ``TJ`` show, which
    is why passing them is the documented path.

    ``frame`` is the page's visual frame, which the mode-2 stroke bound is
    measured in.  Same contract as ``streams``: a caller that already
    derived one (``_classify_common`` does, once per prepare) passes it;
    one that did not gets it derived here, for the mode-2 rung only.
    """
    # A hex operand is admitted alongside a literal one: the two encode the
    # same bytes, and the patch below replaces the operand token
    # (delimiters included) with a freshly encoded one, so nothing of the
    # source string's spelling survives to matter.  T16-4X S1 admits ``TJ``
    # as well, but ONLY the single-string-item shape, and the splice then
    # covers that inner item alone -- ``[``, ``]``, every kern and the
    # operator keyword stay byte-identical (tandem plan D3).
    item_span: TjSpan | None = None
    if show.operator == "TJ":
        if show.string_kind != "array":
            return PlanRejection(
                RejectReason.NOT_SINGLE_LITERAL_TJ,
                f"target is a {show.string_kind} {show.operator}; a TJ operand "
                "must be an array",
            )
        stream = None if streams is None else streams.get(show.stream_xref)
        if stream is None:
            stream = _read_one_stream(doc, show.stream_xref)
        proven = _tj_inner_item_span(show, stream)
        if isinstance(proven, PlanRejection):
            return proven
        item_span = proven
    elif show.operator != "Tj" or show.string_kind not in ("literal", "hex"):
        return PlanRejection(
            RejectReason.NOT_SINGLE_LITERAL_TJ,
            f"target is a {show.string_kind} {show.operator}; v1 patches only "
            "complete single-string Tj operators",
        )
    # Rise is split out of the render-mode ladder (T16-4 Steps 7-8) and
    # keeps its code, its position and its detail STRING verbatim: a raised
    # baseline is refused whatever the mode paints, including the mode-2
    # shape admitted below.
    if show.rise != 0.0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"render_mode={show.render_mode} rise={show.rise}",
        )
    # The render-mode ladder (tandem plan D7): every non-fill mode gets its
    # OWN branch, naming itself and the hazard that refuses it.  A mode that
    # is only refused incidentally, by falling through a neighbour's
    # condition, is exactly what D7 forbids -- the next reader cannot tell
    # whether it was considered.
    pen: StrokePen | None = None
    mode = show.render_mode
    if mode == 2:
        # Fill THEN stroke: the fill leg is the ink Tier 0 already proves,
        # and the stroke leg is preserved by construction (``2 Tr`` and the
        # ``w`` operand sit before ``op_start``, outside every splice this
        # tier makes).  Admitted only with a PROVEN pen.
        proven_pen = _prove_stroke_pen(doc, page, show, frame=frame)
        if isinstance(proven_pen, PlanRejection):
            return proven_pen
        pen = proven_pen
    elif mode == 1:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "render_mode=1 has no fill leg; the glyphs are stroke-only ink "
            "this tier cannot reproduce",
        )
    elif mode == 3:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "render_mode=3 is invisible; refused until S7 (glyph-coverage "
            "plan section 4)",
        )
    elif 4 <= mode <= 7:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"render_mode={mode} adds glyphs to the clipping path, a "
            "persistent state effect on everything painted afterwards",
        )
    elif mode != 0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"render_mode={mode} is not a defined text render mode",
        )
    # Tz does not participate in the admitted TRM shape, and verification
    # re-derives growth direction from bbox geometry; the planner is the only
    # defense against a zero/negative/non-finite horizontal scale.
    if not math.isfinite(show.hscale) or show.hscale <= 0.0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"hscale={show.hscale} is not a positive finite horizontal scale",
        )
    # Task 13 P1: the blanket "inside a marked-content sequence" refusal
    # is replaced by the taxonomy admission — a stack of default-visible
    # pure /OC layer wrappers is provably splice-inert (proof obligations
    # 1-5, test_text_commit_mc_admission.py); everything else keeps a
    # fail-closed refusal with its own stable MC_* code.
    mc_rejection = admit_show_wrappers(
        doc,
        page,
        show,
        wrappers=wrappers,
        emc_underflows=emc_underflows,
    )
    if mc_rejection is not None:
        return PlanRejection(mc_rejection.reason, mc_rejection.detail)

    if show.font_resource is None:
        return PlanRejection(
            RejectReason.FONT_FACE_UNAVAILABLE, "no font selected at the show op"
        )
    capability = registry.capability(page, show.font_resource)
    if capability is None:
        return PlanRejection(
            RejectReason.FONT_FACE_UNAVAILABLE,
            f"font resource /{show.font_resource} not resolvable on this page",
        )
    if capability.tier0_reject_reason is not None:
        if capability.subtype == "Type0":
            # Code-only detail (§10 privacy): the type0_* gates never
            # surface the basefont name — a subset-tagged basename can
            # identify a private document's producer pipeline.
            return PlanRejection(
                capability.tier0_reject_reason,
                capability.tier0_reject_detail
                or "type0 evidence gate refused this font resource",
            )
        return PlanRejection(
            capability.tier0_reject_reason,
            f"font /{show.font_resource} ({capability.basefont})",
        )

    # ---- Task 12 P0-D: the Identity-H/CIDFontType2 codec path ----
    # The locked v1 scope is a single HEX operand: a literal-string
    # spelling of a Type0 operand is spec-legal but stays out of scope
    # rather than silently widening it (post-review pin, wf_1757a5fb-8e9).
    # Detail stays code-only (§10 privacy).  Flattened out of the
    # ``if capability.cid is not None:`` block it used to open (the rest
    # of that block is replacement-dependent and stayed behind in
    # ``_classify_common``) — same position in the ladder, same detail.
    #
    # T16-4X S1: an ``array`` operand is admitted here too, but only when
    # the ONE inner item proven above is itself a hex string -- a literal
    # inner item is exactly the spelling the hex-only scope refuses, and
    # the second emission site must not mask the first (PITFALLS.md:1997).
    if capability.cid is not None:
        hex_operand = (
            item_span.token_kind is TokenKind.HEXSTRING
            if item_span is not None
            else show.string_kind == "hex"
        )
        if not hex_operand:
            return PlanRejection(
                RejectReason.NOT_SINGLE_LITERAL_TJ,
                "type0 v1 scope admits only single HEX-string Tj operands",
            )

    return ShowGateAdmission(capability=capability, item_span=item_span, pen=pen)


def _classify_common(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    replacement_text: str,
    expected_origin: tuple[float, float] | None,
    target_bbox: tuple[float, float, float, float] | None,
    registry: DocumentFontRegistry,
    style_overrides: StyleOverrides | None,
    new_rect: object | None,
    page_has_pending_maintenance: bool,
    evidence_cache: ReplayEvidenceCache | None = None,
) -> _ClassifiedTarget | PlanRejection:
    """Classify and bind the candidate; shared by every tier.

    Gate order and every detail string are pinned by
    ``test_text_commit_structural_gates.py`` -- this is
    ``prepare_tier0_plan``'s original body, verbatim, plus two new gates
    (operator, shared-content-stream) inserted before the existing
    ``NOT_SINGLE_LITERAL_TJ`` gate.

    The show-level rungs from that ``NOT_SINGLE_LITERAL_TJ`` gate down to
    the Type0 hex-only scope now live in :func:`tier0_show_gate`, which the
    audit instrument calls as well; they run at exactly the same point in
    this ladder, and nothing before or after them moved.
    """
    if replacement_text == target_text:
        return PlanRejection(RejectReason.NO_CHANGE, "replacement equals source")
    if not replacement_text:
        return PlanRejection(
            RejectReason.EMPTY_REPLACEMENT, "deletion is not a Tier 0 operation"
        )
    if "\n" in replacement_text or "\r" in replacement_text:
        return PlanRejection(
            RejectReason.MULTILINE_REPLACEMENT,
            "line-count changes require paragraph layout (Tier 1+)",
        )
    if style_overrides is not None and style_overrides.changed:
        return PlanRejection(
            RejectReason.STYLE_OVERRIDE_PRESENT,
            "explicit user restyle cannot reuse the source show op unchanged",
        )
    if new_rect is not None:
        return PlanRejection(
            RejectReason.GEOMETRY_OVERRIDE_PRESENT,
            "user-dragged geometry requires re-layout (Tier 1+)",
        )
    if page_has_pending_maintenance:
        return PlanRejection(
            RejectReason.PENDING_MAINTENANCE,
            "page has pending legacy cleanup that may run clean_contents",
        )
    if page_has_widgets_or_signatures(doc, page):
        return PlanRejection(
            RejectReason.SIGNED_OR_WIDGET_TARGET,
            "form widgets or signatures present; high-fidelity edit refused",
        )

    # The page's visual frame is derived ONCE, here, at the last cheap gate
    # and BEFORE any geometry is read -- binding's origin mapping and TRM
    # direction gate are both downstream of it, and the duplicate-painter
    # gate alone maps three quads per candidate.  A page whose frame cannot
    # be PROVEN against what MuPDF renders is refused outright (review "sol"
    # F2): every coordinate the tier would derive from a guessed frame --
    # halo, growth band, origin -- would be silently wrong, and MuPDF draws
    # no ink at all on those shapes, so there is nothing to mirror either.
    try:
        frame = page_visual_frame(page)
    except UnsupportedPageGeometryError as exc:
        return PlanRejection(RejectReason.PAGE_GEOMETRY_UNSUPPORTED, str(exc))

    # P3-B: the ONE decoded stream read of this prepare.  Placed after
    # the cheap early gates on purpose -- early rejects keep paying zero
    # stream reads.  The snapshot's fresh-bytes key is the lookup-time
    # pull-validation; a digest match reuses the retained production
    # PageReplay (Shape A), a mismatch replays and replaces the slot.
    # Refused/malformed replays never produce evidence to store.
    snapshot = capture_page_streams(doc, page)
    if not snapshot.streams:
        # Review F4: preserve the pre-P3-B surface verbatim -- bind's
        # empty-streams gate, reached with zero replay work and nothing
        # stored (empty-page evidence must never evict a valid entry).
        return PlanRejection(
            RejectReason.NO_MATCH, "page has no content streams"
        )
    cached = (
        evidence_cache.lookup(snapshot.key)
        if evidence_cache is not None
        else None
    )
    resolved = resolve_replay(snapshot, cached)
    if (
        evidence_cache is not None
        and resolved.evidence is not None
        and not resolved.from_cache
    ):
        evidence_cache.store(resolved.evidence)

    binding = bind_source_text(
        doc,
        page,
        target_text=target_text,
        expected_origin=expected_origin,
        registry=registry,
        resolved=resolved,
        frame=frame,
    )
    if isinstance(binding, BindingFailure):
        return PlanRejection(binding.reason, binding.detail)

    show = binding.show

    # NEW (Task 11 Slice 1): ' and " carry persistent text-state side
    # effects INSIDE their recorded op range that a whole-op splice would
    # silently delete -- refuse both tiers here, in the shared classifier,
    # rather than only at the patch.py mechanism level.
    if show.operator in ("'", '"'):
        if show.operator == "'":
            detail = (
                "target show operator is ' (quote), which folds an implicit "
                "T* line break into its recorded range; a whole-op splice "
                "would delete it"
            )
        else:
            detail = (
                'target show operator is " (double-quote), whose recorded '
                "range includes the aw/ac operands that assign Tw/Tc; a "
                "whole-op splice would silently delete those persistent "
                "state assignments"
            )
        return PlanRejection(RejectReason.UNSUPPORTED_SHOW_OPERATOR, detail)

    # NEW (Task 11 Slice 1): every high-fidelity tier mutates its stream in
    # place, so a stream shared by another page's /Contents would silently
    # rewrite that page too. Tier-independent: covers Tier 0 as well.
    foreign = find_pages_sharing_content_stream(
        doc, stream_xref=show.stream_xref, page_number=page.number
    )
    if foreign:
        return PlanRejection(
            RejectReason.SHARED_CONTENT_STREAM,
            f"content stream is /Contents of {len(foreign)} other page(s)",
        )

    # The replacement-independent show-level ladder, in ONE function the
    # audit instrument calls too (T16-4X S1, plan §8.6): operator, render
    # mode/rise, hscale, marked-content wrappers, font resource, capability
    # and the Type0 hex-only scope.  It sits exactly where those gates used
    # to be spelled out, between the shared-content-stream gate above and
    # the replacement-dependent codec work below.
    # Hoisted above the gate (T16-4X S1): the ``TJ`` rung re-lexes the
    # show's operand from these bytes, and the duplicate-painter gate's
    # exact arm below re-lexes twin operands from the same map.
    streams = dict(snapshot.streams)

    admission = tier0_show_gate(
        doc,
        page,
        show,
        wrappers=binding.mc_wrappers,
        emc_underflows=binding.mc_emc_underflows,
        registry=registry,
        streams=streams,
        frame=frame,
    )
    if isinstance(admission, PlanRejection):
        return admission
    capability = admission.capability

    # The CIDs this edit will PAINT, for the duplicate-painter gate's exact
    # arm; ``None`` on the simple-font path, where that arm never runs.
    replacement_cids: tuple[int, ...] | None = None

    if capability.cid is not None:
        # ---- Task 12 P0-D: the Identity-H/CIDFontType2 codec path ----
        # Its operand-scope gate (hex only) is the last rung of
        # ``tier0_show_gate`` above; what follows is replacement-dependent
        # and therefore stays here.
        cid = capability.cid
        # Source-reproduction proof (binding already ran it; re-proven here
        # because the capability may have been rebuilt since, and this
        # plan's evidence must be the one the splice is built from).
        reproduced = cid.encode_first_wins(target_text)
        if isinstance(reproduced, CidCapabilityFailure):
            return PlanRejection(reproduced.reason, reproduced.detail)
        if reproduced != show.decoded_bytes:
            return PlanRejection(
                RejectReason.TYPE0_SOURCE_BYTES_NOT_REPRODUCED,
                "deterministic reverse encoding does not reproduce the "
                "source show operand bytes",
            )
        source_cids = tuple(
            int.from_bytes(show.decoded_bytes[i : i + 2], "big")
            for i in range(0, len(show.decoded_bytes), 2)
        )
        strict = cid.encode_strict(replacement_text)
        if isinstance(strict, CidCapabilityFailure):
            return PlanRejection(strict.reason, strict.detail)
        replacement_cids = strict
        # GID + glyph-repertoire gates for EVERY cid the edit touches:
        # source first (broken map evidence for glyphs already on the page
        # is broken evidence, full stop), then the replacement.
        glyph_failure = cid.glyph_gate(source_cids, target_text) or cid.glyph_gate(
            replacement_cids, replacement_text
        )
        if glyph_failure is not None:
            return PlanRejection(glyph_failure.reason, glyph_failure.detail)

        source_encoded = show.decoded_bytes
        replacement_encoded = cid.encode_cids(replacement_cids)
        old_advance = cid.advance_points(
            source_cids, show.font_size, show.char_spacing
        )
        new_advance = cid.advance_points(
            replacement_cids, show.font_size, show.char_spacing
        )
        # /W and /DW are exact rational arithmetic, same as simple /Widths.
        tolerance = max(_ADVANCE_TOL_PER_PT_EXACT * show.font_size, 1e-9)
        operand_kind = "hex"
    else:
        # Verify the reverse encoder against the *source* bytes before trusting
        # it for the replacement (the make-or-break sanity check).
        source_encoded_simple = capability.encode_simple(target_text)
        if source_encoded_simple is None or source_encoded_simple != show.decoded_bytes:
            return PlanRejection(
                RejectReason.ENCODING_FAILED,
                "reverse encoder does not reproduce the source string bytes",
            )
        source_encoded = source_encoded_simple
        replacement_encoded_simple = capability.encode_simple(replacement_text)
        if replacement_encoded_simple is None:
            return PlanRejection(
                RejectReason.ENCODING_FAILED,
                "replacement contains characters outside the verified simple "
                "encoding or the font's glyph set",
            )
        replacement_encoded = replacement_encoded_simple

        # Both strings must be measurable before either is measured: a code with
        # no usable /Widths entry (out of [FirstChar, LastChar], or declared
        # zero) has no advance the document proves, and /MissingWidth is never
        # substituted for it.  Counts only — never the characters themselves.
        uncovered = capability.uncovered_codes(target_text) or capability.uncovered_codes(
            replacement_text
        )
        if uncovered:
            return PlanRejection(
                RejectReason.FONT_WIDTHS_INCOMPLETE,
                f"font /{show.font_resource} ({capability.basefont}) declares no "
                f"usable /Widths entry for {len(uncovered)} character code(s)",
            )

        old_advance = _advance(
            capability, target_text, show.font_size, show.char_spacing, show.word_spacing
        )
        new_advance = _advance(
            capability,
            replacement_text,
            show.font_size,
            show.char_spacing,
            show.word_spacing,
        )
        if capability.advance_source == "widths":
            tolerance = max(_ADVANCE_TOL_PER_PT_EXACT * show.font_size, 1e-9)
        else:
            tolerance = max(_ADVANCE_TOL_PER_PT * show.font_size, 1e-4)
        operand_kind = "literal"

    th = show.hscale / 100.0
    derived_scale_values = (
        th,
        old_advance * th,
        new_advance * th,
        (new_advance - old_advance) * th,
    )
    if th <= 0.0 or not all(math.isfinite(value) for value in derived_scale_values):
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "effective horizontal scale or scaled advance is non-finite",
        )

    if not all(
        math.isfinite(float(value)) for value in (*show.tm, *show.ctm)
    ):
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "text matrix or CTM holds a non-finite value",
        )

    # ``streams`` was hoisted above the show gate; the duplicate-painter
    # gate (P4-B2 slice 3b) reads the same map, because a ``TJ`` twin's kern
    # numbers are not in its ShowOp and the exact arm re-lexes them from the
    # twin's own byte range in its own stream.
    duplicate_detail = duplicate_source_painter_detail(
        page,
        show,
        target_text=target_text,
        target_capability=capability,
        source_advance=old_advance,
        registry=registry,
        shows=resolved.replay.shows,
        streams=streams,
        replacement_cids=replacement_cids,
        glyph_boxes=registry.glyph_boxes,
        frame=frame,
        # T16-4 Step 9: the pen the show gate PROVED for this target, or
        # ``None`` for the fill mode.  Resolved once, at the gate, and read
        # here by name -- never re-derived, which is the whole point of
        # carrying it on ``ShowGateAdmission``.
        pen=admission.pen,
    )
    if duplicate_detail is not None:
        return PlanRejection(RejectReason.DUPLICATE_SOURCE_PAINTER, duplicate_detail)

    stream_bytes = streams[show.stream_xref]

    fingerprint = page_fingerprint(doc, page, streams=snapshot.streams)
    # Task 13 P2: the show's cardinal visual baseline direction — it is
    # recomputed (cheap, pure) rather than threaded through the binding.
    # Usually an admission (binding proved it); the exception is a bound
    # replay-uniform show whose boundary residuals the relative shape
    # checks would refuse (review F2) — its direction is None and it
    # rides the axis path exactly as before P2.
    trm_direction = admission_verdict(
        page, show.tm, show.ctm, frame=frame
    ).direction
    if target_bbox is None:
        # ``old_advance``/``font_size`` are text space.  Build the metric
        # quad IN TEXT SPACE (advance along the baseline, ascent toward
        # the ascender; below-baseline ≈ 0.35·size, above ≈ 1.0·size) and
        # map it through the show's full ``Tm × CTM`` and then the page's
        # visual frame — never a user-space ``+x`` assumption.  Without the
        # frame's /Rotate term a /Rotate 90/270 page keeps a horizontal
        # halo while pixmap ink runs vertically (V0d false-reject /
        # false-accept risk); without its computed base, a rotated CROPPED
        # or /UserUnit page puts the halo off the ink entirely.  On an
        # unrotated page the frame reproduces the historical halo exactly.
        target_bbox = map_text_quad_to_visual(
            page,
            show.tm,
            show.ctm,
            (
                0.0,
                -0.35 * show.font_size,
                old_advance * th,
                show.font_size,
            ),
            frame=frame,
        )
        # T16-4 Step 8: a stroked show paints past its metric quad by the
        # pen, so the FALLBACK box grows by the HONEST outset on every side
        # -- ``(w/2) * sigma_max``, deliberately WITHOUT the miter factor
        # (D4: this box is V0d's halo, where an over-bound erodes how much
        # of the page the diff proof exempts; E7 measured the fixture's own
        # miter bound already exceeding ``verify._HALO_MARGIN_PT``).  A
        # caller-SUPPLIED ``target_bbox`` is left exactly as given: it comes
        # from the extractor and already reflects rendered ink, so
        # outsetting it would double-count the pen.
        if admission.pen is not None:
            outset = _stroke_outset_visual(
                show, frame=frame, pen=admission.pen, conservative=False
            )
            if outset is not None:
                # ``None`` is unreachable here (the same guards proved the
                # conservative bound at the gate, and the honest one only
                # drops the miter factor); skipping the growth would merely
                # shrink the halo, which fails closed at V0d anyway.
                target_bbox = (
                    target_bbox[0] - outset,
                    target_bbox[1] - outset,
                    target_bbox[2] + outset,
                    target_bbox[3] + outset,
                )
    renderable_target_bbox = _renderable_bbox(target_bbox)
    if renderable_target_bbox is None:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "target_bbox escapes renderable coordinates",
        )

    return _ClassifiedTarget(
        binding=binding,
        show=show,
        capability=capability,
        stream_bytes=stream_bytes,
        target_text=target_text,
        replacement_text=replacement_text,
        source_encoded=source_encoded,
        replacement_encoded=replacement_encoded,
        source_advance=old_advance,
        replacement_advance=new_advance,
        advance_tolerance=tolerance,
        target_bbox_page=renderable_target_bbox,
        fingerprint=fingerprint,
        style_overrides=style_overrides,
        geometry_intent=(
            tuple(float(value) for value in new_rect)
            if new_rect is not None
            else None
        ),
        operand_kind=operand_kind,
        show_item_span=admission.item_span,
        trm_direction=trm_direction,
        frame=frame,
    )


def _build_tier0(
    classified: _ClassifiedTarget, page: fitz.Page
) -> PreparedEdit | PlanRejection:
    """The advance-equality gate, plus the string-range splice and token."""
    show = classified.show
    # _classify_common already refused a None font_resource
    # (FONT_FACE_UNAVAILABLE); this is a type narrowing, not a new check.
    assert show.font_resource is not None
    # Raw-vs-raw advance equality is scale-invariant: the same positive Th
    # multiplies both sides, so the existing tolerance floors stay meaningful.
    if abs(classified.replacement_advance - classified.source_advance) > (
        classified.advance_tolerance
    ):
        return PlanRejection(
            RejectReason.ADVANCE_MISMATCH,
            "consumed advance would change by "
            f"{classified.replacement_advance - classified.source_advance:+.3f}pt; "
            "Tier 0 must preserve it exactly",
        )

    # T16-4X S1: a single-item ``TJ`` splices the INNER item alone, so
    # ``[``, ``]``, every kern and the ``TJ`` keyword are byte-identical
    # pre/post and the operand still lexes as exactly one string token
    # (tandem plan D3).  A ``Tj`` splices its whole string operand, as
    # before -- the range is the gate's, never re-derived here.
    item_span = classified.show_item_span
    if item_span is None:
        splice_start, splice_end = show.string_start, show.string_end
    else:
        splice_start, splice_end = item_span.start, item_span.end
    expected = classified.stream_bytes[splice_start:splice_end]
    replacement = StreamReplacement(
        stream_xref=show.stream_xref,
        start=splice_start,
        end=splice_end,
        expected_bytes=expected,
        replacement_bytes=(
            encode_hex_string(classified.replacement_encoded)
            if classified.operand_kind == "hex"
            else encode_literal_string(classified.replacement_encoded)
        ),
        expected_stream_digest=classified.binding.stream_digest,
    )
    token = _content_token(
        classified.fingerprint,
        replacement,
        target_bbox=classified.target_bbox_page,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
        splice_kind=SPLICE_KIND_STRING_TOKEN,
    )
    return PreparedEdit(
        token=token,
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        replacement=replacement,
        binding=classified.binding,
        original_text=classified.target_text,
        replacement_text=classified.replacement_text,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
        font_size=show.font_size,
        target_bbox_page=classified.target_bbox_page,
        page_fingerprint=classified.fingerprint,
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
        splice_kind=SPLICE_KIND_STRING_TOKEN,
    )


def _grown_verify_bbox(
    page: fitz.Page,
    show: ShowOp,
    target_bbox_page: tuple[float, float, float, float],
    growth_advance: float,
    *,
    frame: PageVisualFrame | None = None,
) -> tuple[float, float, float, float]:
    """``target_bbox_page`` widened FORWARD along the show's transformed
    baseline by ``growth_advance`` effective-displacement points, mapped
    through the page's visual frame so /Rotate, the CropBox origin and
    /UserUnit are handled correctly by construction (the same frame as the
    fallback ``target_bbox`` in :func:`_classify_common`).  The band is
    ``growth_advance × |Tm×CTM linear| × /UserUnit`` visual points wide;
    losing the /UserUnit factor on a rotated page would UNDERSIZE the
    growth zone, which is the false-ACCEPT direction.

    The forward direction comes from the combined ``Tm × CTM`` baseline
    vector — never a user-space ``+x`` assumption.  The admitted family is
    quarter-turn only, so the user-space baseline is axis-aligned and the
    caller box's CROSS extent is preserved exactly (the growth strip
    inherits the target's own thickness, not the metric quad's).

    Returns ``target_bbox_page`` UNCHANGED (no round trip, no float noise)
    when there is no growth: callers rely on exact equality to decide
    ``PreparedEdit.has_ink_growth``.
    """
    if growth_advance <= 0.0:
        return target_bbox_page
    linear = combined_linear(show.tm, show.ctm)
    norm = math.hypot(linear[0], linear[1])
    if norm <= 0.0 or not math.isfinite(norm):
        # Unreachable for admitted shows (the binding gate refused these);
        # fail toward the historical axis assumption rather than crash.
        norm = 1.0
    ux = linear[0] / norm
    uy = linear[1] / norm
    growth_user = growth_advance * norm
    page_frame = page_visual_frame(page) if frame is None else frame
    visual = page_frame.visual
    user = fitz.Rect(*target_bbox_page) * page_frame.inverse
    if abs(ux) >= abs(uy):
        if ux >= 0.0:
            user.x1 = user.x1 + growth_user
        else:
            user.x0 = user.x0 - growth_user
    else:
        if uy >= 0.0:
            user.y1 = user.y1 + growth_user
        else:
            user.y0 = user.y0 - growth_user
    mapped = user * visual
    return (
        min(target_bbox_page[0], float(mapped.x0)),
        min(target_bbox_page[1], float(mapped.y0)),
        max(target_bbox_page[2], float(mapped.x1)),
        max(target_bbox_page[3], float(mapped.y1)),
    )


def _bbox_within_page(
    page: fitz.Page, bbox: tuple[float, float, float, float]
) -> bool:
    page_rect = page.rect
    x0, y0, x1, y1 = bbox
    tol = _PAGE_CONTAINMENT_TOL_PT
    return (
        x0 >= float(page_rect.x0) - tol
        and y0 >= float(page_rect.y0) - tol
        and x1 <= float(page_rect.x1) + tol
        and y1 <= float(page_rect.y1) + tol
    )


def _build_tier1(
    classified: _ClassifiedTarget, page: fitz.Page
) -> PreparedEdit | PlanRejection:
    """The kern-compensated transplant candidate: same op range, wider ink
    admitted only under a verified blank-growth-zone proof (checked later,
    in :func:`~model.text_commit.verify.verify_tier1_commit`, not here)."""
    show = classified.show
    # T16-4 Step 10 fence, FIRST rung.  Tier 0 admits ``render_mode == 2``
    # behind a proven pen because its splice cannot touch the stroke leg
    # (``2 Tr`` and the ``w`` operand sit before ``op_start``) and its halo
    # carries the honest outset.  Tier 1 proves neither: it transplants the
    # WHOLE operator and verifies through ``_grown_verify_bbox`` and
    # ``background_bbox_page`` (below), two boxes derived from the metric
    # quad with no pen term at all -- an unproven verification surface over
    # ink that escapes them by the pen.  The fence DELETES that surface
    # rather than widen it, which costs nothing today: ``max_tier``
    # defaults to 0, so no production caller escalates a mode-2 target.
    # Written against ``!= 0``, not against ``== 2``, so it stays correct
    # structurally -- mode 2 is the only non-fill mode that can reach here
    # now (every other one dies in ``tier0_show_gate``), and whatever S7
    # admits later arrives fenced instead of silently verified.
    if show.render_mode != 0:
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            f"render_mode={show.render_mode} is admitted at Tier 0 only, "
            "behind a proven stroke pen; Tier 1's widened verify and "
            "background boxes carry no pen term and prove nothing over "
            "stroked ink",
        )
    # _classify_common already refused a None font_resource
    # (FONT_FACE_UNAVAILABLE); this is a type narrowing, not a new check.
    assert show.font_resource is not None
    # T16-4X S1 fence.  Tier 0 splices a single-item ``TJ``'s INNER item, so
    # the array's own kerns are byte-identical pre/post; Tier 1 replaces the
    # WHOLE operator with ``[(new) K] TJ`` (``patch.
    # build_kern_compensated_transplant``), which DELETES those kerns while
    # ``K`` compensates only the string advance -- every downstream show on
    # the line moves.  MEASURED before this fence existed: such a commit
    # succeeded and verification did not catch it (a page whose only show is
    # the target has no neighbour to move), so this is a real fail-closed
    # gate, not belt and braces.  Re-lexed here rather than carried on the
    # classification: this is the tier that needs the fact.  Kern-sum
    # arithmetic (admitting these under a ``"tj_run"`` splice) is S4.
    if show.operator == "TJ":
        spans = tj_item_spans(classified.stream_bytes, show)
        if spans is None:
            return PlanRejection(
                RejectReason.TJ_ITEM_RELEX_FAILED,
                "target TJ operand range does not re-lex to the recorded "
                "array, so a whole-op transplant cannot be proven safe",
            )
        if any(span.kind == "kern" for span in spans):
            return PlanRejection(
                RejectReason.TJ_KERN_IN_TIER1_RANGE,
                "target TJ array carries kern numbers inside the operator "
                "range that a whole-op Tier 1 transplant would delete",
            )
    th = show.hscale / 100.0
    growth = max(
        0.0, classified.replacement_advance - classified.source_advance
    ) * th
    verify_bbox_page = _grown_verify_bbox(
        page, show, classified.target_bbox_page, growth, frame=classified.frame
    )
    background_bbox_page = map_text_quad_to_visual(
        page,
        show.tm,
        show.ctm,
        (
            0.0,
            -0.35 * show.font_size,
            classified.source_advance * th,
            show.font_size,
        ),
        frame=classified.frame,
    )
    # Derived geometry gets its own proof: ``_classify_common`` cleared the
    # TARGET bbox (possibly caller-supplied) and the show's matrices, but a
    # widened or metric box is a fresh computation.  Verification must never
    # be the thing that discovers an unrenderable extent, by exception or by
    # clamping — so the bound is the SAMPLER's (``_RENDERABLE_COORD_LIMIT``),
    # not merely ``isfinite``.
    if (
        _renderable_bbox(verify_bbox_page) is None
        or _renderable_bbox(background_bbox_page) is None
    ):
        return PlanRejection(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "derived verify or background bbox escapes renderable coordinates",
        )
    if not _bbox_within_page(page, verify_bbox_page):
        return PlanRejection(
            _GROWTH_OUTSIDE_PAGE_REASON,
            "widened verify bbox escapes page bounds",
        )
    try:
        kern = kern_for_displacement(
            show, classified.source_advance - classified.replacement_advance
        )
    except ValueError as exc:
        # ``kern_for_displacement`` is a serialization chokepoint that raises
        # rather than emit a wrong token.  Reaching it from the planner means
        # the numeric boundary is a PLAN outcome, so it becomes a stable
        # reason code here instead of an exception escaping ``prepare``.
        return PlanRejection(RejectReason.UNSUPPORTED_TEXT_STATE, str(exc))
    replacement = build_kern_compensated_transplant(
        classified.stream_bytes,
        show,
        replacement_encoded=classified.replacement_encoded,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        string_kind=classified.operand_kind,
    )
    token = _content_token(
        classified.fingerprint,
        replacement,
        target_bbox=classified.target_bbox_page,
        verify_bbox=verify_bbox_page,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        kern_adjustment=kern,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
        # T16-4X S1 review L1: this tier transplants the WHOLE operator, so
        # it must SAY so -- both in the token preimage (a Tier 1 candidate
        # can never collide with a Tier 0 one over the same range) and on
        # the dataclass ``verify._target_operator_failure`` dispatches on.
        splice_kind=SPLICE_KIND_WHOLE_OPERATOR,
    )
    return PreparedEdit(
        token=token,
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        replacement=replacement,
        binding=classified.binding,
        original_text=classified.target_text,
        replacement_text=classified.replacement_text,
        font_resource=show.font_resource,
        font_xref=classified.capability.font_xref,
        font_size=show.font_size,
        target_bbox_page=classified.target_bbox_page,
        page_fingerprint=classified.fingerprint,
        tier=CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE,
        splice_kind=SPLICE_KIND_WHOLE_OPERATOR,
        verify_bbox_page=verify_bbox_page,
        background_bbox_page=background_bbox_page,
        source_advance=classified.source_advance,
        replacement_advance=classified.replacement_advance,
        kern_adjustment=kern,
        style_overrides=classified.style_overrides,
        geometry_intent=classified.geometry_intent,
        growth_direction=classified.trm_direction,
    )


def prepare_tier0_plan(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    replacement_text: str,
    expected_origin: tuple[float, float] | None,
    target_bbox: tuple[float, float, float, float] | None,
    registry: DocumentFontRegistry,
    style_overrides: StyleOverrides | None = None,
    new_rect: object | None = None,
    page_has_pending_maintenance: bool = False,
) -> PreparedEdit | PlanRejection:
    """Classify and build the Tier 0 candidate, or reject with a reason."""
    classified = _classify_common(
        doc,
        page,
        target_text=target_text,
        replacement_text=replacement_text,
        expected_origin=expected_origin,
        target_bbox=target_bbox,
        registry=registry,
        style_overrides=style_overrides,
        new_rect=new_rect,
        page_has_pending_maintenance=page_has_pending_maintenance,
    )
    if isinstance(classified, PlanRejection):
        return classified
    return _build_tier0(classified, page)


# The only Tier 0 refusal Slice 1's composite candidate actually removes: the
# kern term absorbs an arbitrary advance delta while every other property of
# the candidate is identical. Every other reason is terminal for both tiers
# (see plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md).
_TIER1_ESCALATION_REASONS = frozenset({RejectReason.ADVANCE_MISMATCH})


def prepare_plan(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    replacement_text: str,
    expected_origin: tuple[float, float] | None,
    target_bbox: tuple[float, float, float, float] | None,
    registry: DocumentFontRegistry,
    style_overrides: StyleOverrides | None = None,
    new_rect: object | None = None,
    page_has_pending_maintenance: bool = False,
    max_tier: int = 0,
    evidence_cache: ReplayEvidenceCache | None = None,
) -> PreparedEdit | PlanRejection:
    """Classify once; try Tier 0, escalate to Tier 1 only on ADVANCE_MISMATCH.

    The single product both preview and commit consume, so a Tier 1
    candidate's token is automatically identical on both paths. Tier 0
    always runs first and always wins when it accepts.

    ``evidence_cache`` (P3-B) opts into session-scoped replay reuse --
    the preview keystroke loop passes its renderer-owned single-slot
    cache; every other caller stays ephemeral by default.
    """
    classified = _classify_common(
        doc,
        page,
        target_text=target_text,
        replacement_text=replacement_text,
        expected_origin=expected_origin,
        target_bbox=target_bbox,
        registry=registry,
        style_overrides=style_overrides,
        new_rect=new_rect,
        page_has_pending_maintenance=page_has_pending_maintenance,
        evidence_cache=evidence_cache,
    )
    if isinstance(classified, PlanRejection):
        return classified

    tier0_result = _build_tier0(classified, page)
    if isinstance(tier0_result, PreparedEdit):
        return tier0_result
    if max_tier < 1 or tier0_result.reason not in _TIER1_ESCALATION_REASONS:
        return tier0_result
    return _build_tier1(classified, page)
