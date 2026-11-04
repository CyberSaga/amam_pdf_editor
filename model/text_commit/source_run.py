"""Click-time source-show grouping of index runs (UI stage G2, 2026-09-30).

The block index splits runs at every space and at every character-kind
change (``model/text_block_parsing.py``), so ONE content-stream show such as
``(Buffer Tank) Tj`` or ``<設計圖說A版> Tj`` arrives as several runs.  A
run-mode click therefore returned a single word, which the engine's exact
show binding can never match.  The owner decided (plan section 6,
2026-09-30) to group at CLICK time and never merge runs in the index: the
index cannot learn show identity from extraction (``<Buffer> Tj < Tank> Tj``
extracts to the same two runs as one show), and everything else that reads
word runs would change with it.

:func:`group_page_runs` proves, per extracted line, that the line's runs are
exactly one show, and only then groups them:

1. members = every run of the (block, line), ordered by ``span_idx``
   (PARSER order -- ``origin.x`` reverses a mirrored show);
2. exactly one RELIABLE-origin show has its origin within
   :data:`ORIGIN_TOL_PT` of the first member's origin;
3. that show is ONE string item painted with zero character spacing
   (VERIFY F2, 2026-09-30): MuPDF synthesizes page-text spaces from TJ
   kern gaps and from ``Tc`` gaps (helv 12 pt: kern -100 no space, -150 a
   space; Tc 1.5 none, Tc 2.0 'B u f f e r'), and those spaces are not in
   the decoded show.  Where MuPDF inserts one is its own gap heuristic,
   which stream bytes cannot prove, so such shows never group (the editor
   must show what the page shows, plan section 3).  With one string item
   and ``Tc == 0`` consecutive glyphs abut exactly, so the only page-text
   whitespace is the show's own; ``Tw`` only widens a real space, and a
   gap big enough to break the line fails step 5;
4. that show decodes (Type0 Identity-H through its ToUnicode evidence,
   simple fonts through latin-1, the same two legs as binding);
5. the decoded text minus whitespace equals the concatenated member texts
   minus whitespace, and the non-space glyph-code count equals the
   non-space character count of the members;
6. no other reliable show origin lies strictly inside the members' union
   bbox, and the show's own successor does not continue its pen with an
   untracked (``origin_reliable=False``) origin;
7. no untracked-origin show can paint into the union (VERIFY F1): replay
   does not track advances, so such a show lies SOMEWHERE on the text line
   of its last repositioning.  Its painted extent is that line, unbounded
   along the baseline and :data:`UNTRACKED_BAND_EM` em either side of it;
   the proof fails when the union meets that band, and fails outright when
   the band cannot be bounded (no font evidence, Type3, Type0 without the
   Identity-H codec -- possibly vertical --, or a singular text matrix);
8. per page, a show is claimed by at most one line (VERIFY F1): when two
   extracted lines both prove the same show, neither groups -- one of them
   is a repaint by some other painter.

Any failed step leaves the line ungrouped: the caller keeps today's
single-run hit, which refuses at binding -- safe.

Known limit: text painted from inside a Form XObject is invisible to
replay, so it is neither an origin candidate nor an untracked painter;
rule 8 still refuses when such a repaint yields a second line claiming
the same show.

Side-effect contract (critique B5): only content-stream BYTES (``xref_stream``)
and the font registry are read.  Never ``get_text``/``get_texttrace``/
``get_drawings``/``get_image_rects`` on the live document -- plan section 6
records that those re-serialise the page dict or warm MuPDF's image store.
Geometry is the index's own (dict space == the page visual frame's BASE
space, so the proof runs in base space; ``SourceShowRef.origin`` is emitted
in VISUAL space through the same frame binding uses).
"""
from __future__ import annotations

import logging
import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import fitz

from model.edit_requests import SourceShowRef
from model.text_commit.evidence import ReplayEvidenceKey, compute_evidence_key
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.inspect import read_page_streams
from model.text_commit.replay import ShowOp, replay_page_streams
from model.text_commit.transforms import page_visual_frame_or_none

logger = logging.getLogger(__name__)

# First member's origin vs the show origin (points, base == visual distance:
# the quarter turn between them is rigid).
ORIGIN_TOL_PT = 0.05
# Strict-interior inset for the foreign-origin test: an origin ON the union's
# edge (the next show starting exactly where this one ends) is not inside.
_INTERIOR_EPS_PT = 0.01
# Half-height, in em of the show's own font size, of the band an
# untracked-origin show may paint across its baseline (rule 7).  Generous on
# purpose: no text font's FontBBox reaches 3 em from the baseline, and the
# proven corpus pages carry no untracked-origin show, so the width costs no
# proven group.
UNTRACKED_BAND_EM = 3.0
# |det| below this is a singular text matrix (rule 7 fails closed).
_SINGULAR_DET = 1e-12


# Reopen-anchor key namespace for a multi-member group (UI step 3): the
# anchor of a grouped show is the show's union, keyed by ALL its members, so a
# per-word anchor recorded for its first run can never shrink the group's
# overlap cluster (critique B1).  A one-member group keys by its span id,
# exactly like an ungrouped run.
GROUP_ANCHOR_PREFIX = "show@"
_GROUP_ANCHOR_SEP = "+"


def group_anchor_key(member_span_ids: Sequence[str]) -> str:
    members = [str(m) for m in member_span_ids]
    if len(members) == 1:
        return members[0]
    return GROUP_ANCHOR_PREFIX + _GROUP_ANCHOR_SEP.join(members)


def group_anchor_first_member(key: str) -> str | None:
    """The first member span id of a group anchor key; ``None`` for a run key."""
    if not key.startswith(GROUP_ANCHOR_PREFIX):
        return None
    first = key[len(GROUP_ANCHOR_PREFIX):].split(_GROUP_ANCHOR_SEP, 1)[0]
    return first or None


@dataclass(frozen=True)
class SourceRunGroup:
    """One proven show-equals-line group, in the index's (dict) space."""

    text: str  # the decoded show text, verbatim (spaces included)
    member_span_ids: tuple[str, ...]  # parser (span_idx) order
    bbox: tuple[float, float, float, float]  # union of the member bboxes
    origin: tuple[float, float]  # first member's origin
    source_ref: SourceShowRef

    @property
    def first_span_id(self) -> str:
        return self.member_span_ids[0]

    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.bbox)

    @property
    def anchor_key(self) -> str:
        return group_anchor_key(self.member_span_ids)


def _strip(text: str) -> str:
    return "".join((text or "").split())


def _capability(
    page: fitz.Page,
    show: ShowOp,
    registry: DocumentFontRegistry,
    resolved: dict[str, FontCapability | None],
) -> FontCapability | None:
    name = show.font_resource
    if name is None:
        return None
    if name not in resolved:
        try:
            resolved[name] = registry.capability(page, name)
        except Exception:  # any evidence failure is "cannot prove"
            logger.debug("source-run: capability lookup failed for a font resource")
            resolved[name] = None
    return resolved[name]


def _decode_show(
    page: fitz.Page,
    show: ShowOp,
    registry: DocumentFontRegistry,
    resolved: dict[str, FontCapability | None],
) -> tuple[str, int] | None:
    """``(decoded text, non-space glyph-code count)`` or ``None``."""
    capability = _capability(page, show, registry, resolved)
    if capability is None:
        return None
    data = show.decoded_bytes
    if capability.subtype == "Type0":
        cid = capability.cid
        if cid is None:
            return None
        decoded = cid.decode_show_bytes(data)
        if not isinstance(decoded, str):
            return None
        # decode_show_bytes refuses multi-char clusters, so codes and chars
        # are 1:1; the count is still taken per CODE, independently.
        glyphs = 0
        for i in range(0, len(data), 2):
            char = cid.tounicode.decode_cid(int.from_bytes(data[i : i + 2], "big"))
            if char is None:
                return None
            if not char.isspace():
                glyphs += 1
        return decoded, glyphs
    text = data.decode("latin-1")
    return text, sum(1 for byte in data if not chr(byte).isspace())


class _OriginIndex:
    """Reliable show origins indexed for the two per-line proof queries.

    Step 12 latency: ``_prove_line`` used to scan EVERY show for EVERY
    extracted line (O(lines x shows) ``fitz.Point`` arithmetic, ~140 ms on
    HVAC p4).  Both queries now pre-filter through this index and then apply
    the unchanged exact predicate to the survivors, so the answer is the
    same set: a non-finite origin can satisfy neither predicate (NaN compares
    false, and the members' bboxes are finite), so it is never indexed.
    """

    # >= ORIGIN_TOL_PT: a point within the tolerance is in a neighbouring cell.
    _CELL = 0.1

    def __init__(self, base_origins: Sequence[fitz.Point | None]) -> None:
        self._grid: dict[tuple[int, int], list[int]] = {}
        by_x: list[tuple[float, int]] = []
        for idx, origin in enumerate(base_origins):
            if origin is None:
                continue
            x, y = float(origin.x), float(origin.y)
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            key = (math.floor(x / self._CELL), math.floor(y / self._CELL))
            self._grid.setdefault(key, []).append(idx)
            by_x.append((x, idx))
        by_x.sort()
        self._xs = [x for x, _ in by_x]
        self._x_ids = [idx for _, idx in by_x]

    def near(self, point: fitz.Point) -> list[int]:
        """A sorted superset of the indexed origins within the tolerance of ``point``."""
        x, y = float(point.x), float(point.y)
        if not (math.isfinite(x) and math.isfinite(y)):
            return []
        cx, cy = math.floor(x / self._CELL), math.floor(y / self._CELL)
        found: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                found.extend(self._grid.get((cx + dx, cy + dy), ()))
        found.sort()
        return found

    def x_between(self, low: float, high: float) -> list[int]:
        """Indexed origins with ``low <= x <= high`` (a superset of strict)."""
        return self._x_ids[bisect_left(self._xs, low) : bisect_right(self._xs, high)]


def _strictly_inside(rect: fitz.Rect, point: fitz.Point) -> bool:
    eps = _INTERIOR_EPS_PT
    return (
        rect.x0 + eps < point.x < rect.x1 - eps
        and rect.y0 + eps < point.y < rect.y1 - eps
    )


# (base -> text-space matrix, band low y, band high y) of one untracked show,
# or ``None`` when its painted extent cannot be bounded at all.
_UntrackedBand = tuple[fitz.Matrix, float, float]


def _untracked_band(
    page: fitz.Page,
    show: ShowOp,
    base: fitz.Matrix,
    registry: DocumentFontRegistry,
    resolved: dict[str, FontCapability | None],
) -> _UntrackedBand | None:
    """Where an untracked-origin show may paint (rule 7), in its text space.

    The pen of an untracked show is its last repositioning's text matrix
    (``show.tm``: replay never advances it) moved by an unknown advance.  In
    horizontal writing every advance (glyph widths, Tc, Tw, TJ kerns) is
    along text-space x, so the glyphs sit in ``y in [rise - K*fs, rise +
    K*fs]`` for some x.  Vertical writing, Type3 FontMatrix glyph spaces and
    fonts without evidence have no such bound: ``None``.
    """
    capability = _capability(page, show, registry, resolved)
    if capability is None or capability.subtype == "Type3":
        return None
    if capability.subtype == "Type0" and capability.cid is None:
        return None  # only the Identity-H codec proves horizontal writing
    text_to_base = fitz.Matrix(*show.tm) * fitz.Matrix(*show.ctm) * base
    det = text_to_base.a * text_to_base.d - text_to_base.b * text_to_base.c
    size = abs(float(show.font_size))
    if not (math.isfinite(det) and math.isfinite(size)) or abs(det) < _SINGULAR_DET:
        return None
    half = UNTRACKED_BAND_EM * size
    rise = float(show.rise)
    return ~text_to_base, rise - half, rise + half


def _band_meets(band: _UntrackedBand, union: fitz.Rect) -> bool:
    base_to_text, low, high = band
    ys = [
        (fitz.Point(x, y) * base_to_text).y
        for x, y in (
            (union.x0, union.y0),
            (union.x1, union.y0),
            (union.x0, union.y1),
            (union.x1, union.y1),
        )
    ]
    if not all(math.isfinite(y) for y in ys):
        return True
    # The band is unbounded along text-space x, so the (parallelogram) image
    # of the union meets it exactly when their y-ranges overlap.
    return min(ys) <= high and max(ys) >= low


def group_page_runs(
    doc: fitz.Document,
    page: fitz.Page,
    runs: Sequence,
    *,
    registry: DocumentFontRegistry,
    streams: Sequence[tuple[int, bytes]] | None = None,
) -> dict[str, SourceRunGroup]:
    """Every proven group on ``page``, keyed by EACH member's span id.

    ``runs`` are the page's index runs (``EditableSpan``, dict space).
    ``streams`` lets a caller that already read the page's decoded content
    streams (the cache's pull-validation) avoid a second read.
    """
    if not runs:
        return {}
    if streams is None:
        streams = read_page_streams(doc, page)
    if not streams:
        return {}
    replay = replay_page_streams(list(streams))
    if replay.refusal_reason is not None or replay.malformed:
        return {}
    frame = page_visual_frame_or_none(page)
    if frame is None:
        return {}
    base = frame.base
    visual = frame.visual

    shows = replay.shows
    base_origins: list[fitz.Point | None] = [
        (fitz.Point(*s.origin_user) * base) if s.origin_reliable else None
        for s in shows
    ]

    lines: dict[tuple[int, int], list] = {}
    for run in runs:
        lines.setdefault((int(run.block_idx), int(run.line_idx)), []).append(run)

    resolved: dict[str, FontCapability | None] = {}
    # Rule 7: one band per untracked-origin show; ``None`` = unbounded.
    untracked: list[_UntrackedBand | None] = [
        _untracked_band(page, s, base, registry, resolved)
        for s in shows
        if not s.origin_reliable
    ]
    origin_index = _OriginIndex(base_origins)
    proven: list[SourceRunGroup] = []
    for members in lines.values():
        members.sort(key=lambda r: int(r.span_idx))
        group = _prove_line(
            page,
            members,
            shows,
            base_origins,
            registry,
            resolved,
            visual,
            untracked,
            origin_index=origin_index,
        )
        if group is not None:
            proven.append(group)
    # Rule 8: a show claimed by two lines is a repaint -- neither groups.
    claims = Counter(group.source_ref.seq for group in proven)
    groups: dict[str, SourceRunGroup] = {}
    for group in proven:
        if claims[group.source_ref.seq] > 1:
            logger.debug("source-run: show %s claimed by several lines", group.source_ref.seq)
            continue
        for span_id in group.member_span_ids:
            groups[span_id] = group
    return groups


def _prove_line(
    page: fitz.Page,
    members: list,
    shows: Sequence[ShowOp],
    base_origins: list[fitz.Point | None],
    registry: DocumentFontRegistry,
    resolved: dict[str, FontCapability | None],
    visual: fitz.Matrix,
    untracked: Sequence[_UntrackedBand | None] = (),
    *,
    origin_index: _OriginIndex | None = None,
) -> SourceRunGroup | None:
    first = members[0]
    first_origin = fitz.Point(first.origin)
    near = (
        origin_index.near(first_origin)
        if origin_index is not None
        else range(len(base_origins))
    )
    candidates = [
        idx
        for idx in near
        if (origin := base_origins[idx]) is not None
        and abs(origin - first_origin) <= ORIGIN_TOL_PT
    ]
    if len(candidates) != 1:
        return None
    seq = candidates[0]
    show = shows[seq]
    # Rule 3: no MuPDF-synthesized page-text space can exist inside the show.
    if show.array_item_count != 1 or show.char_spacing != 0.0:
        return None
    decoded = _decode_show(page, show, registry, resolved)
    if decoded is None:
        return None
    text, glyph_codes = decoded
    member_text = "".join(_strip(r.text) for r in members)
    if not member_text or _strip(text) != member_text:
        return None
    if glyph_codes != len(member_text):
        return None
    successor = seq + 1
    if successor < len(shows) and not shows[successor].origin_reliable:
        return None
    union = fitz.Rect(members[0].bbox)
    for run in members[1:]:
        union |= fitz.Rect(run.bbox)
    inside_x: Sequence[int]
    if origin_index is not None and all(
        math.isfinite(float(v)) for v in (union.x0, union.y0, union.x1, union.y1)
    ):
        inside_x = origin_index.x_between(
            union.x0 + _INTERIOR_EPS_PT, union.x1 - _INTERIOR_EPS_PT
        )
    else:
        inside_x = range(len(base_origins))
    for idx in inside_x:
        origin = base_origins[idx]
        if idx == seq or origin is None:
            continue
        if _strictly_inside(union, origin):
            return None
    for band in untracked:
        if band is None or _band_meets(band, union):
            return None
    origin_visual = fitz.Point(*show.origin_user) * visual
    return SourceRunGroup(
        text=text,
        member_span_ids=tuple(str(r.span_id) for r in members),
        bbox=(float(union.x0), float(union.y0), float(union.x1), float(union.y1)),
        origin=(float(first_origin.x), float(first_origin.y)),
        source_ref=SourceShowRef(
            page_xref=int(page.xref),
            stream_xref=int(show.stream_xref),
            op_start=int(show.op_start),
            seq=int(show.seq),
            origin=(float(origin_visual.x), float(origin_visual.y)),
        ),
    )


@dataclass
class _PageEntry:
    runs: object  # the index's run list object (identity-compared, held alive)
    key: ReplayEvidenceKey
    groups: dict[str, SourceRunGroup]


@dataclass
class SourceRunResolver:
    """Per-document, per-page cache of :func:`group_page_runs` results.

    Pull-validated on EVERY lookup (the P3-A lesson: several mutation classes
    change live stream bytes with no signal): the page's decoded streams are
    re-read and digested, and the entry is reused only when the digest key,
    the document object and the index's run-list object all match.  Index
    rebuilds (stale pages, commit, undo/redo) replace the run list, and
    content changes replace the digest, so both invalidate without hooks.
    ``invalidate`` exists for explicit drops.  GUI-thread, not thread-safe.
    """

    _doc: fitz.Document | None = None
    _registry: DocumentFontRegistry | None = None
    _pages: dict[int, _PageEntry] = field(default_factory=dict)
    cold: int = 0
    warm: int = 0

    def invalidate(self, page_idx: int | None = None) -> None:
        if page_idx is None:
            self._pages.clear()
        else:
            self._pages.pop(page_idx, None)

    def page_groups(
        self, doc: fitz.Document, page_idx: int, runs: Sequence
    ) -> dict[str, SourceRunGroup]:
        if not runs or doc is None or page_idx < 0 or page_idx >= len(doc):
            return {}
        if self._doc is not doc:
            self._doc = doc
            self._registry = DocumentFontRegistry(doc)
            self._pages.clear()
        registry = self._registry
        assert registry is not None
        try:
            page = doc[page_idx]
            streams = read_page_streams(doc, page)
            key = compute_evidence_key(page.xref, streams)
        except Exception:  # unreadable page: nothing provable
            logger.debug("source-run: page %s streams unreadable", page_idx)
            self._pages.pop(page_idx, None)
            return {}
        entry = self._pages.get(page_idx)
        if entry is not None and entry.runs is runs and entry.key == key:
            self.warm += 1
            return entry.groups
        self.cold += 1
        try:
            groups = group_page_runs(
                doc, page, runs, registry=registry, streams=streams
            )
        except Exception:  # fail closed: no grouping
            logger.debug("source-run: grouping failed on page %s", page_idx, exc_info=True)
            groups = {}
        self._pages[page_idx] = _PageEntry(runs=runs, key=key, groups=groups)
        return groups

    def group_for_span(
        self, doc: fitz.Document, page_idx: int, runs: Sequence, span_id: str
    ) -> SourceRunGroup | None:
        return self.page_groups(doc, page_idx, runs).get(span_id)
