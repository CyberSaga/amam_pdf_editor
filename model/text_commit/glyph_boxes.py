"""Point-verified glyph ink boxes, and the pure geometry that places them.

The duplicate-source-painter gate needs to know where a painter's INK is,
not where its cursor goes.  A declared advance is not an ink bound: a wide
``/W`` over narrow glyphs over-states it, a narrow one under-states it, and
neither is a proof.  This module answers the only question that is
provable from the document itself — "what does this gid paint?" — by
reading the embedded TrueType outline.

**Point-verified, never header-trusted.**  A ``glyf`` entry's 10-byte
header carries a bounding box, but MEASURED (2026-09-04, MuPDF 1.27.1):
MuPDF ignores it.  Zeroing a simple glyph's header to ``(0, 0, 1, 1)``
left the outline exactly where it was and merely shifted the bound by the
``lsb − xMin`` translation; zeroing a composite's changed nothing at all.
A stale or malicious subset header would therefore under-bound live ink
without a whisper.  So the box here comes from the point arrays — ALL
points, on-curve and off-curve, which is FreeType's control box and hence
exactly what ``fz_bound_glyph`` returns — and the header is used only as a
CROSS-CHECK: disagreement past one font unit refuses the glyph.

The control box contains the true ink (a Bezier lies inside its control
polygon's hull), so every divergence between this box and the painted
outline is conservative: more refusals, never a false-safe.

**The lsb shift.**  FreeType translates a glyph's outline by
``hmtx.leftSideBearing − glyf.xMin``.  Measured on the fixture face: 2 of
50,483 gids have ``lsb != xMin``, both by exactly one unit, and both are
covered exactly once the shift is applied.  ``hmtx`` is
``longHorMetric[numberOfHMetrics]`` followed by ``int16
leftSideBearing[]`` — only the ADVANCE falls back to the last long metric,
never the bearing.  Measured on the one fixture gid past
``numberOfHMetrics``: the tail-array bearing bounds the ink, the
last-metric bearing misses it by 27 units.

**One font unit is not an epsilon.**  At upem 256 one unit exceeds the
gate's 0.05 pt epsilon once the font size passes 12.8 pt.  The pad is real
and must always be applied.

Re-homed here by COPYING from the P4-B2 spike's ``scripts/`` modules: this
package must not import ``scripts/`` (measurement code, not shipped) or
``fontTools`` (a dev dependency).  Pinned by
``test_scripts/test_layer_boundaries.py``.

LEAF-ward by design: imports ``cid_fonts``, ``pdf_lexer`` and ``replay``
only, never ``fonts`` — ``DocumentFontRegistry`` OWNS the cache defined
here, so the edge must point this way.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import fitz

from model.text_commit.cid_fonts import (
    CidCapabilityFailure,
    GlyphProgram,
    IdentityHCidCapability,
    parse_truetype_glyph_program,
    read_embedded_font_program,
)
from model.text_commit.pdf_lexer import (
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    lex_content_stream,
)
from model.text_commit.replay import ShowOp

logger = logging.getLogger(__name__)

Rect = tuple[float, float, float, float]
Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# The gate's overlap epsilon (``model/text_commit/plan.py``): a strict
# overlap deeper than this on BOTH axes is a real overlap.
OVERLAP_EPSILON = 0.05


# ============================================================== rectangles


def rect_is_empty(rect: Rect) -> bool:
    return rect[2] <= rect[0] or rect[3] <= rect[1]


def rect_union(rects: list[Rect] | tuple[Rect, ...]) -> Rect:
    """AABB of every non-empty rect; the empty rect when there are none."""
    live = [rect for rect in rects if not rect_is_empty(rect)]
    if not live:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(rect[0] for rect in live),
        min(rect[1] for rect in live),
        max(rect[2] for rect in live),
        max(rect[3] for rect in live),
    )


def rect_pad(rect: Rect, pad: float) -> Rect:
    return (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)


def strict_overlap_depths(first: Rect, second: Rect) -> tuple[float, float]:
    """Positive on BOTH axes means a real overlap; zero or negative means
    touching or apart.

    A deliberate DUPLICATE of ``plan._strict_overlap_depths`` rather than an
    import: commit 4 gives the planner a ``GlyphBoxCache``, so ``plan →
    glyph_boxes`` is the edge that must exist and the reverse would cycle.
    Six lines of arithmetic; the two must stay byte-identical in semantics.
    """
    return (
        min(first[2], second[2]) - max(first[0], second[0]),
        min(first[3], second[3]) - max(first[1], second[1]),
    )


# ================================================================ matrices


def matrix_concat(first: Matrix, second: Matrix) -> Matrix:
    """``first`` applied first, then ``second`` (PDF row-vector convention)."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def transform_point(point: Point, matrix: Matrix) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def transform_rect(rect: Rect, matrix: Matrix) -> Rect:
    """AABB of the four transformed corners: exact for quarter turns, a
    superset (never a subset) under shear or an arbitrary rotation."""
    corners = (
        transform_point((rect[0], rect[1]), matrix),
        transform_point((rect[2], rect[1]), matrix),
        transform_point((rect[0], rect[3]), matrix),
        transform_point((rect[2], rect[3]), matrix),
    )
    xs = [corner[0] for corner in corners]
    ys = [corner[1] for corner in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def scale_units_to_text(
    units: Rect, units_per_em: int, font_size: float, hscale: float
) -> Rect:
    """Font-unit bounds → the show's text space: ``[Tfs·Th, 0, 0, Tfs]``.

    ``hscale`` is ``Tz / 100`` and may be negative (mirrored text); the
    result is normalized so ``x0 <= x1``.  Th enters the geometry exactly
    ONCE, here — never again downstream.
    """
    sx = font_size * hscale / units_per_em
    sy = font_size / units_per_em
    x0, x1 = units[0] * sx, units[2] * sx
    y0, y1 = units[1] * sy, units[3] * sy
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


# ================================================================= TJ relex


@dataclass(frozen=True)
class TjItem:
    kind: str  # "string" | "kern"
    value: bytes | float


def tj_items(stream: bytes, show: ShowOp) -> tuple[TjItem, ...] | None:
    """The show's operand as ordered string/kern items, re-lexed from the
    show's own byte range in ``stream``.

    ``ShowOp.decoded_bytes`` drops the kern numbers, and a TJ cursor replay
    cannot be done without them.  ``None`` means the byte range does not
    reproduce the recorded operand — an integrity failure the caller must
    refuse, never paper over.
    """
    if not (0 <= show.string_start < show.string_end <= len(stream)):
        return None
    operand = stream[show.string_start : show.string_end]
    tokens = list(lex_content_stream(operand))
    items: list[TjItem] = []
    if show.operator == "TJ":
        if not tokens or tokens[0].kind is not TokenKind.ARRAY_OPEN:
            return None
        if tokens[-1].kind is not TokenKind.ARRAY_CLOSE:
            return None
        body = tokens[1:-1]
    else:
        body = tokens
    for token in body:
        raw = operand[token.start : token.end]
        if token.kind is TokenKind.WHITESPACE or token.kind is TokenKind.COMMENT:
            continue
        if token.kind is TokenKind.NUMBER:
            if show.operator != "TJ":
                return None
            try:
                items.append(TjItem("kern", float(raw)))
            except ValueError:
                return None
        elif token.kind is TokenKind.STRING:
            items.append(TjItem("string", decode_literal_string(raw)))
        elif token.kind is TokenKind.HEXSTRING:
            items.append(TjItem("string", decode_hex_string(raw)))
        else:
            return None
    strings = [item for item in items if item.kind == "string"]
    if len(strings) != show.array_item_count:
        return None
    joined = b"".join(
        item.value for item in strings if isinstance(item.value, bytes)
    )
    if joined != show.decoded_bytes:
        return None
    return tuple(items)


# =========================================================== cursor replay

PREDICTION_SLUGS = (
    "no_cid_capability",
    "tj_relex_failed",
    "odd_byte_count",
    "gid_unresolved",
    "text_state_unusable",
)


@dataclass(frozen=True)
class PredictedGlyph:
    index: int
    cid: int
    gid: int
    cursor_x: float  # text space, Th applied, relative to the show origin
    origin_user: Point  # PDF user space, rise applied (like ShowOp.origin_user)


@dataclass(frozen=True)
class PredictedShow:
    glyphs: tuple[PredictedGlyph, ...]
    slug: str | None  # one of PREDICTION_SLUGS when the prediction is unusable


def predict_glyphs(
    show: ShowOp,
    capability: IdentityHCidCapability | None,
    items: tuple[TjItem, ...] | None,
) -> PredictedShow:
    """Identity-H cursor replay for one show.

    ``tx = (w0/1000 · Tfs + Tc) · Th`` per glyph (PDF 32000-1 §9.4.4; ``Tw``
    NEVER applies to 2-byte codes), TJ kerns ``−n/1000 · Tfs · Th``.  The
    glyph origin in text space is ``(cursor_x, Ts)``; in user space it is
    ``origin_user + cursor_x · (a, b)`` of ``Tm × CTM``.

    Declared widths move the CURSOR here and bound NOTHING: the ink comes
    from :func:`glyph_unit_box` alone.
    """
    if capability is None:
        return PredictedShow((), "no_cid_capability")
    if items is None:
        return PredictedShow((), "tj_relex_failed")
    size = show.font_size
    th = show.hscale / 100.0
    if not (
        math.isfinite(size)
        and math.isfinite(th)
        and math.isfinite(show.char_spacing)
    ):
        return PredictedShow((), "text_state_unusable")
    tm_ctm = matrix_concat(show.tm, show.ctm)
    if not all(math.isfinite(value) for value in tm_ctm):
        return PredictedShow((), "text_state_unusable")
    ax, bx = tm_ctm[0], tm_ctm[1]
    ox, oy = show.origin_user
    cursor = 0.0
    glyphs: list[PredictedGlyph] = []
    for item in items:
        if item.kind == "kern":
            if not isinstance(item.value, float):
                return PredictedShow((), "tj_relex_failed")
            cursor -= item.value / 1000.0 * size * th
            continue
        data = item.value
        if not isinstance(data, bytes):
            return PredictedShow((), "tj_relex_failed")
        if len(data) % 2:
            return PredictedShow((), "odd_byte_count")
        for offset in range(0, len(data), 2):
            cid = int.from_bytes(data[offset : offset + 2], "big")
            gid = capability.gid_for(cid)
            if isinstance(gid, CidCapabilityFailure):
                return PredictedShow((), "gid_unresolved")
            glyphs.append(
                PredictedGlyph(
                    index=len(glyphs),
                    cid=cid,
                    gid=gid,
                    cursor_x=cursor,
                    origin_user=(ox + cursor * ax, oy + cursor * bx),
                )
            )
            width = capability.width_of_cid(cid)
            cursor += (width / 1000.0 * size + show.char_spacing) * th
    return PredictedShow(tuple(glyphs), None)


# ============================================================= glyph boxes

GLYPH_BOX_REASONS = (
    "glyf_unavailable",
    "glyf_parse_error",
    "glyf_header_disagrees",
    "glyf_degenerate",
    "composite_unsupported",
    "gid_out_of_range",
)

# One font unit on every side.  MEASURED: the point box equals
# ``fz_bound_glyph`` exactly on 300 simple and 30 composite fixture gids, so
# the pad is pure margin — but it is what absorbs an lsb shift whose
# direction FreeType and this module could disagree about, and it is never
# assumed to be below the gate's 0.05 pt epsilon.
_UNIT_PAD = 1.0

# The header cross-check tolerance, in the same font units.
_HEADER_TOLERANCE = 1.0

_MAX_COMPOSITE_DEPTH = 8
_MAX_COMPONENTS = 256

# ``head.unitsPerEm`` is a uint16; the spec's legal range is 16..16384.
_MIN_UPEM = 16
_MAX_UPEM = 16384

# Simple-glyph point flags (ISO/IEC 14496-22, glyf).
_X_SHORT_VECTOR = 0x02
_Y_SHORT_VECTOR = 0x04
_REPEAT_FLAG = 0x08
_X_IS_SAME_OR_POSITIVE = 0x10
_Y_IS_SAME_OR_POSITIVE = 0x20

# Composite component flags.
_ARG_1_AND_2_ARE_WORDS = 0x0001
_ARGS_ARE_XY_VALUES = 0x0002
_WE_HAVE_A_SCALE = 0x0008
_MORE_COMPONENTS = 0x0020
_WE_HAVE_AN_X_AND_Y_SCALE = 0x0040
_WE_HAVE_A_TWO_BY_TWO = 0x0080
_SCALED_COMPONENT_OFFSET = 0x0800

_F2DOT14 = 1.0 / 16384.0


@dataclass(frozen=True)
class GlyphBox:
    """One gid's ink bound in font units, or a closed refusal slug.

    Exactly one of the two is set: a box with ``reason`` is never produced,
    so a caller cannot accidentally treat a refusal as a bound.
    """

    units: Rect | None
    reason: str | None


class _GlyfError(Exception):
    """Internal: a structural failure carrying one GLYPH_BOX_REASONS slug."""

    def __init__(self, slug: str) -> None:
        super().__init__(slug)
        self.slug = slug


def _int16(data: bytes, at: int) -> int:
    if at + 2 > len(data):
        raise _GlyfError("glyf_parse_error")
    return int.from_bytes(data[at : at + 2], "big", signed=True)


def _uint16(data: bytes, at: int) -> int:
    if at + 2 > len(data):
        raise _GlyfError("glyf_parse_error")
    return int.from_bytes(data[at : at + 2], "big")


def _uint8(data: bytes, at: int) -> int:
    if at + 1 > len(data):
        raise _GlyfError("glyf_parse_error")
    return data[at]


def _glyph_span(program: GlyphProgram, gid: int) -> tuple[int, int]:
    """(absolute start, length) of ``gid``'s glyf entry; length 0 = blank."""
    length = program.glyph_data_length(gid)
    if length is None:
        raise _GlyfError("glyf_parse_error")
    return program.glyf_offset + program.loca[gid], length


def _left_side_bearing(data: bytes, program: GlyphProgram, gid: int) -> int:
    """``hmtx`` bearing for ``gid``.

    ISO/IEC 14496-22 §5.2.5: ``longHorMetric hMetrics[numberOfHMetrics]``
    then ``int16 leftSideBearing[numGlyphs − numberOfHMetrics]``.  The
    ADVANCE of a gid past ``numberOfHMetrics`` repeats the last long
    metric; the BEARING does not — it lives in the trailing array.
    MEASURED: applying the last long metric's bearing to the fixture face's
    one tail gid put the box 27 units off and missed real ink.
    """
    if program.hmtx_offset is None or program.number_of_h_metrics <= 0:
        raise _GlyfError("glyf_parse_error")
    metrics = program.number_of_h_metrics
    if gid < metrics:
        at = program.hmtx_offset + gid * 4 + 2
        limit = program.hmtx_offset + metrics * 4
    else:
        at = program.hmtx_offset + metrics * 4 + (gid - metrics) * 2
        limit = program.hmtx_offset + program.hmtx_length
    if at + 2 > min(limit, program.hmtx_offset + program.hmtx_length):
        raise _GlyfError("glyf_parse_error")
    return _int16(data, at)


def _header_box(data: bytes, start: int) -> Rect:
    return (
        float(_int16(data, start + 2)),
        float(_int16(data, start + 4)),
        float(_int16(data, start + 6)),
        float(_int16(data, start + 8)),
    )


def _simple_point_box(data: bytes, start: int, length: int) -> Rect | None:
    """Min/max over ALL points of a simple glyph — on-curve AND off-curve.

    That is FreeType's control box, which is exactly what
    ``fz_bound_glyph`` returns; taking on-curve points only would under-
    bound every curved glyph.  ``None`` means the glyph declares no points.
    """
    end = start + length
    contours = _int16(data, start)
    at = start + 10
    last_end = -1
    for _ in range(contours):
        last_end = _uint16(data, at)
        at += 2
    point_count = last_end + 1
    if point_count <= 0:
        return None
    instruction_length = _uint16(data, at)
    at += 2 + instruction_length
    if at > end:
        raise _GlyfError("glyf_parse_error")
    flags: list[int] = []
    while len(flags) < point_count:
        flag = _uint8(data, at)
        at += 1
        flags.append(flag)
        if flag & _REPEAT_FLAG:
            repeats = _uint8(data, at)
            at += 1
            flags.extend([flag] * repeats)
    if len(flags) > point_count:
        # A repeat count that overruns the declared point count is corrupt
        # evidence, not a glyph: the coordinate arrays cannot be addressed.
        raise _GlyfError("glyf_parse_error")
    xs: list[int] = []
    value = 0
    for flag in flags:
        if flag & _X_SHORT_VECTOR:
            delta = _uint8(data, at)
            at += 1
            value += delta if flag & _X_IS_SAME_OR_POSITIVE else -delta
        elif not flag & _X_IS_SAME_OR_POSITIVE:
            value += _int16(data, at)
            at += 2
        xs.append(value)
    ys: list[int] = []
    value = 0
    for flag in flags:
        if flag & _Y_SHORT_VECTOR:
            delta = _uint8(data, at)
            at += 1
            value += delta if flag & _Y_IS_SAME_OR_POSITIVE else -delta
        elif not flag & _Y_IS_SAME_OR_POSITIVE:
            value += _int16(data, at)
            at += 2
        ys.append(value)
    if at > end:
        raise _GlyfError("glyf_parse_error")
    return (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))


def _point_box(
    data: bytes,
    program: GlyphProgram,
    gid: int,
    depth: int,
    on_path: tuple[int, ...],
    budget: list[int],
) -> tuple[Rect | None, bool]:
    """Untranslated point box of ``gid`` and whether it is a composite.

    The lsb shift is the OUTER glyph's business — components are placed by
    their raw glyf coordinates, so this recursion never shifts.
    """
    if gid < 0 or gid >= program.num_glyphs:
        raise _GlyfError("gid_out_of_range")
    if depth > _MAX_COMPOSITE_DEPTH or gid in on_path:
        raise _GlyfError("composite_unsupported")
    start, length = _glyph_span(program, gid)
    if length == 0:
        return None, False
    if length < 10 or start + length > len(data):
        raise _GlyfError("glyf_parse_error")
    if _int16(data, start) >= 0:
        return _simple_point_box(data, start, length), False

    end = start + length
    at = start + 10
    boxes: list[Rect] = []
    while True:
        budget[0] -= 1
        if budget[0] < 0:
            raise _GlyfError("composite_unsupported")
        flags = _uint16(data, at)
        component = _uint16(data, at + 2)
        at += 4
        if flags & _ARG_1_AND_2_ARE_WORDS:
            arg1, arg2 = _int16(data, at), _int16(data, at + 2)
            at += 4
        else:
            arg1 = int.from_bytes(data[at : at + 1], "big", signed=True)
            arg2 = int.from_bytes(data[at + 1 : at + 2], "big", signed=True)
            at += 2
        if at > end:
            raise _GlyfError("glyf_parse_error")
        if flags & _WE_HAVE_A_SCALE:
            scale = _int16(data, at) * _F2DOT14
            at += 2
            two_by_two = (scale, 0.0, 0.0, scale)
        elif flags & _WE_HAVE_AN_X_AND_Y_SCALE:
            two_by_two = (
                _int16(data, at) * _F2DOT14,
                0.0,
                0.0,
                _int16(data, at + 2) * _F2DOT14,
            )
            at += 4
        elif flags & _WE_HAVE_A_TWO_BY_TWO:
            two_by_two = (
                _int16(data, at) * _F2DOT14,
                _int16(data, at + 2) * _F2DOT14,
                _int16(data, at + 4) * _F2DOT14,
                _int16(data, at + 6) * _F2DOT14,
            )
            at += 8
        else:
            two_by_two = (1.0, 0.0, 0.0, 1.0)
        if not flags & _ARGS_ARE_XY_VALUES:
            # Point-matching placement: the offset depends on the assembled
            # outline's own points, which a bounds-only walk cannot know.
            raise _GlyfError("composite_unsupported")
        # ROUND_XY_TO_GRID is deliberately ignored: it moves the component
        # by at most half a pixel at render ppem, never at the em scale
        # this box is expressed in.
        offset_x, offset_y = float(arg1), float(arg2)
        if flags & _SCALED_COMPONENT_OFFSET:
            # MEASURED: MuPDF honours this flag — with a 1.5x scale and a
            # (400, 200) offset the bound moved by exactly 200 units.
            offset_x, offset_y = (
                two_by_two[0] * arg1 + two_by_two[2] * arg2,
                two_by_two[1] * arg1 + two_by_two[3] * arg2,
            )
        sub, _ = _point_box(
            data, program, component, depth + 1, on_path + (gid,), budget
        )
        if sub is not None:
            placed = transform_rect(
                sub,
                (
                    two_by_two[0],
                    two_by_two[1],
                    two_by_two[2],
                    two_by_two[3],
                    offset_x,
                    offset_y,
                ),
            )
            boxes.append(placed)
        if not flags & _MORE_COMPONENTS:
            break
        if at >= end:
            raise _GlyfError("glyf_parse_error")
    if not boxes:
        return None, True
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ), True


def glyph_unit_box(
    program_bytes: bytes, program: GlyphProgram, gid: int
) -> GlyphBox:
    """One gid's ink bound in font units, padded by one unit on every side.

    A blank gid (an empty ``loca`` span) yields the empty rect with no
    reason — proven to paint nothing, which a union drops.  Everything the
    program cannot prove yields a closed slug from :data:`GLYPH_BOX_REASONS`
    and NO box.
    """
    if gid < 0 or gid >= program.num_glyphs:
        return GlyphBox(None, "gid_out_of_range")
    if not (_MIN_UPEM <= program.units_per_em <= _MAX_UPEM):
        return GlyphBox(None, "glyf_parse_error")
    try:
        start, length = _glyph_span(program, gid)
        if length == 0:
            return GlyphBox((0.0, 0.0, 0.0, 0.0), None)
        points, is_composite = _point_box(
            program_bytes, program, gid, 0, (), [_MAX_COMPONENTS]
        )
        if points is None:
            return GlyphBox(None, "glyf_degenerate")
        header = _header_box(program_bytes, start)
        # Cross-check BEFORE the shift: the header box and the raw point box
        # are the same quantity in the same frame, so honest glyphs agree
        # exactly.  Comparing after the shift would refuse every glyph whose
        # bearing legitimately differs from xMin.
        if max(
            abs(header[0] - points[0]),
            abs(header[1] - points[1]),
            abs(header[2] - points[2]),
            abs(header[3] - points[3]),
        ) > _HEADER_TOLERANCE:
            return GlyphBox(None, "glyf_header_disagrees")
        if rect_is_empty(points):
            return GlyphBox(None, "glyf_degenerate")
        shift = float(_left_side_bearing(program_bytes, program, gid)) - header[0]
        if is_composite and abs(shift) > _UNIT_PAD:
            # Composites with a bearing that disagrees with their header
            # were NOT observed on any measured face (0 of 50,483 fixture
            # gids), so whether FreeType translates a composite outline the
            # way it translates a simple one is unproven here.  Refuse
            # rather than guess; the pad already covers |shift| <= 1 under
            # EITHER reading.
            return GlyphBox(None, "composite_unsupported")
        shifted = (points[0] + shift, points[1], points[2] + shift, points[3])
    except _GlyfError as error:
        return GlyphBox(None, error.slug)
    except (IndexError, ValueError, OverflowError):
        return GlyphBox(None, "glyf_parse_error")
    return GlyphBox(rect_pad(shifted, _UNIT_PAD), None)


# ================================================================== caching


@dataclass
class GlyphBoxCache:
    """Document-lifetime unit boxes, keyed ``(font xref, digest, gid)``.

    OWNED by ``DocumentFontRegistry`` (``model/text_commit/fonts.py``): the
    registry is the one object that already knows when a document's font
    evidence went stale, and it clears this cache on ``bump_generation``.
    The digest in the key means an in-place font-program rewrite that keeps
    the same xref still misses.

    A one-slot memo of the last fetched program keeps ONE prepare from
    re-reading a multi-megabyte ``FontFile2`` per glyph: a page's shows are
    grouped by font in practice, so one slot serves them all.  The parse is
    redone alongside the fetch rather than taken from the capability, so the
    bytes and the table offsets used to address them always agree.
    """

    _boxes: dict[tuple[int, str, int], GlyphBox] = field(
        default_factory=dict, repr=False
    )
    _memo: tuple[int, str, bytes | None, GlyphProgram | None] | None = field(
        default=None, repr=False
    )

    @property
    def cached_count(self) -> int:
        return len(self._boxes)

    def clear(self) -> None:
        self._boxes.clear()
        self._memo = None

    def box(
        self,
        doc: fitz.Document,
        capability: IdentityHCidCapability,
        gid: int,
    ) -> GlyphBox:
        """``gid``'s padded ink bound in font units, cached per document."""
        key = (capability.font_xref, capability.evidence_digest, int(gid))
        hit = self._boxes.get(key)
        if hit is not None:
            return hit
        data, program = self._program(doc, capability)
        if data is None or program is None:
            result = GlyphBox(None, "glyf_unavailable")
        else:
            result = glyph_unit_box(data, program, int(gid))
        self._boxes[key] = result
        return result

    def _program(
        self, doc: fitz.Document, capability: IdentityHCidCapability
    ) -> tuple[bytes | None, GlyphProgram | None]:
        memo = self._memo
        if (
            memo is not None
            and memo[0] == capability.font_xref
            and memo[1] == capability.evidence_digest
        ):
            return memo[2], memo[3]
        try:
            data = read_embedded_font_program(doc, capability.font_xref)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            logger.debug("embedded font program unreadable", exc_info=True)
            data = None
        program = parse_truetype_glyph_program(data) if data else None
        self._memo = (
            capability.font_xref,
            capability.evidence_digest,
            data,
            program,
        )
        return data, program
