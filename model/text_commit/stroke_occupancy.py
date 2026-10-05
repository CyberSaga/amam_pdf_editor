"""Exact stroke geometry for the Tier 1 growth-zone occupancy gate (Task D).

``verify._drawings_intersect_growth`` refuses when a drawing's PATH BBOX
overlaps the growth zone.  For a stroke-only path of straight segments the
bbox says nothing about ink: an open page frame (three ``l`` segments along
the page edges) has a bbox covering the whole page while its ink is a thin
line along the edges.  This module proves -- for that narrow shape only --
that the STROKED geometry stays clear of a zone.  It is a stricter-precision
proof, never a loosening: anything it cannot model exactly returns "not
proven" and the caller keeps its bbox verdict.

Why a private MuPDF device instead of ``page.get_drawings()``: PyMuPDF
reports ``width = pathfactor * linewidth`` where ``pathfactor`` is ``|a|``
only when ``|a| == |d|`` (or ``|b|`` when ``|b| == |c|``) and ``1``
otherwise, and it never sees shear -- so the reported width can understate
the rendered ink.  Its ``lineJoin`` is likewise ``pathfactor * linejoin``
and the miter limit is not reported at all.  The device below records the
real CTM and ``fz_stroke_state`` for every ``stroke_path`` call.

The model (all radii in the device space ``fz_run_page`` emits with the
identity matrix, i.e. the page's VISUAL space at 72 dpi):

- the CTM must be a similarity (orthogonal columns of equal norm), so a
  user-space pen circle of radius ``linewidth / 2`` maps to a circle of
  radius ``hw = linewidth / 2 * sigma_max`` and user-space angles survive;
- every segment is a capsule of radius ``hw * sqrt(2) + margin``: the body
  lies within ``hw`` of the centreline and a butt, round or square cap lies
  within ``hw * sqrt(2)`` of its endpoint (a zero-length segment is a dot);
- every join vertex is a disc: ``hw`` for round/bevel joins, and for miter
  joins ``hw * max(1, min(miter_limit, 1 / sin(theta / 2)))`` -- the miter
  tip sits ``hw / sin(theta / 2)`` from the vertex and a miter whose ratio
  exceeds the limit is bevelled (extent ``hw``); a zero-length neighbour
  makes the angle unknown, so the bound falls back to ``hw * max(1, limit)``;
- a closed subpath adds its closing segment and joins at every vertex;
- curves, dashes, hairlines (``linewidth == 0``), unknown join or cap codes,
  non-similarity transforms and any walker/device error are "not proven".

Which device records must be proven (Task T): a record is RELEVANT when its
path extent (every point, curve controls included), inflated by the record's
maximum ink reach, meets the zone.  The reach is ``hw_max * max(sqrt(2),
miter factor) + margin`` with ``hw_max = linewidth / 2 * sigma_max`` of the
record's CTM -- computable for ANY CTM, similarity or not -- and the miter
factor ``max(1, miter_limit)`` for miter joins (``1`` for round/bevel).  Ink
never lies farther than that from the path's extent box (a Bezier stays in
its control hull; dashes are a subset of the solid stroke), so a stroke
whose centreline extent misses the zone but whose half-width, cap or miter
spike reaches into it is still selected.  Anything that makes the reach
unknowable (non-finite or negative width/limit/CTM, an unknown join or cap
code, a non-finite extent) makes the reach infinite: always relevant, and a
relevant record that is not exactly modelled refuses.

``S``/``s`` never fill (ISO 32000-1 8.5.3.1: only ``f``/``F``/``f*``/``B``/
``B*``/``b``/``b*`` paint the interior), so the interior of a closed
stroke-only path is not ink and there is no fill rule to consider.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import fitz

logger = logging.getLogger(__name__)

Point = tuple[float, float]

_LINEJOIN_MITER = 0
_LINEJOIN_ROUND = 1
_LINEJOIN_BEVEL = 2
_KNOWN_JOINS = frozenset({_LINEJOIN_MITER, _LINEJOIN_ROUND, _LINEJOIN_BEVEL})
# fz_linecap: butt 0, round 1, square 2, triangle 3 (triangle stays within
# hw of the endpoint, but it is not a PDF cap -- refuse what PDF cannot say).
_KNOWN_CAPS = frozenset({0, 1, 2})
_SIMILARITY_REL_TOL = 1e-6
# How far a get_drawings vertex may sit from the device-recorded vertex
# (both come from the same fz_path and CTM; measured drift is ~1e-5).
_VERTEX_MATCH_TOL = 1e-3
# Slack for "this record's ink-reach box overlaps the zone", on top of the
# reach itself (``_ink_reach``): float drift can only pull MORE records into
# proof.
_RELEVANCE_SLACK = 1.0


@dataclass(frozen=True)
class StrokeSubpath:
    points: tuple[Point, ...]
    closed: bool


@dataclass(frozen=True)
class StrokeRecord:
    """One ``stroke_path`` device call, in visual space."""

    ctm: tuple[float, float, float, float, float, float]
    line_width: float
    line_join: int
    miter_limit: float
    caps: tuple[int, int, int]
    dash_len: int
    subpaths: tuple[StrokeSubpath, ...]
    has_curve: bool
    extent: tuple[float, float, float, float]  # every point incl. controls

    def vertices(self) -> tuple[Point, ...]:
        return tuple(point for sub in self.subpaths for point in sub.points)


class _PathWalker(fitz.mupdf.FzPathWalker2):
    """Record straight subpaths; ``rectto``/``quadto``/``curvetov``/
    ``curvetoy`` are left unimplemented so ``fz_walk_path`` decomposes them
    into moveto/lineto/closepath and curveto respectively."""

    def __init__(self, ctm: tuple[float, float, float, float, float, float]) -> None:
        super().__init__()
        self.use_virtual_moveto()
        self.use_virtual_lineto()
        self.use_virtual_curveto()
        self.use_virtual_closepath()
        self._ctm = ctm
        self.subpaths: list[StrokeSubpath] = []
        self._current: list[Point] | None = None
        self._start: Point | None = None
        self.has_curve = False
        self.failed = False
        self.extent_points: list[Point] = []

    def _map(self, x: float, y: float) -> Point:
        a, b, c, d, e, f = self._ctm
        point = (a * x + c * y + e, b * x + d * y + f)
        self.extent_points.append(point)
        return point

    def _flush(self, *, closed: bool) -> None:
        if self._current is not None:
            self.subpaths.append(StrokeSubpath(tuple(self._current), closed))
        self._current = None

    def moveto(self, ctx, x, y):  # SWIG director callback
        try:
            self._flush(closed=False)
            point = self._map(float(x), float(y))
            self._current = [point]
            self._start = point
        except Exception:  # pragma: no cover - SWIG swallows director errors
            self.failed = True

    def lineto(self, ctx, x, y):
        try:
            if self._current is None:
                if self._start is None:
                    self.failed = True
                    return
                # after closepath a lineto continues from the subpath start
                self._current = [self._start]
            self._current.append(self._map(float(x), float(y)))
        except Exception:  # pragma: no cover
            self.failed = True

    def curveto(self, ctx, x1, y1, x2, y2, x3, y3):
        try:
            self.has_curve = True
            self._map(float(x1), float(y1))
            self._map(float(x2), float(y2))
            end = self._map(float(x3), float(y3))
            if self._current is None:
                self._current = [self._start] if self._start is not None else []
            self._current.append(end)
        except Exception:  # pragma: no cover
            self.failed = True

    def closepath(self, ctx):
        try:
            if self._current is None:
                self.failed = True
                return
            self._flush(closed=True)
        except Exception:  # pragma: no cover
            self.failed = True

    def finish(self) -> None:
        self._flush(closed=False)


class _StrokeDevice(fitz.mupdf.FzDevice2):
    def __init__(self) -> None:
        super().__init__()
        self.use_virtual_stroke_path()
        self.records: list[StrokeRecord] = []
        self.failed = False

    def stroke_path(
        self, ctx, path, stroke, ctm, colorspace, color, alpha, color_params
    ):
        try:
            matrix = (
                float(ctm.a), float(ctm.b), float(ctm.c),
                float(ctm.d), float(ctm.e), float(ctm.f),
            )
            walker = _PathWalker(matrix)
            fitz.mupdf.fz_walk_path(
                fitz.mupdf.FzPath(fitz.mupdf.ll_fz_keep_path(path)),
                walker,
                walker.m_internal,
            )
            walker.finish()
            if walker.failed or not walker.extent_points:
                self.failed = True
                return
            xs = [p[0] for p in walker.extent_points]
            ys = [p[1] for p in walker.extent_points]
            self.records.append(
                StrokeRecord(
                    ctm=matrix,
                    line_width=float(stroke.linewidth),
                    line_join=int(stroke.linejoin),
                    miter_limit=float(stroke.miterlimit),
                    caps=(
                        int(stroke.start_cap),
                        int(stroke.dash_cap),
                        int(stroke.end_cap),
                    ),
                    dash_len=int(stroke.dash_len),
                    subpaths=tuple(walker.subpaths),
                    has_curve=walker.has_curve,
                    extent=(min(xs), min(ys), max(xs), max(ys)),
                )
            )
        except Exception:  # pragma: no cover - SWIG swallows director errors
            self.failed = True


def collect_stroke_records(page: fitz.Page) -> tuple[StrokeRecord, ...] | None:
    """Every stroked path on ``page`` in VISUAL space, or ``None`` when the
    run could not be observed completely (fail closed)."""
    device = _StrokeDevice()
    try:
        raw = page.this
        fz_page = fitz.mupdf.FzPage(raw) if isinstance(raw, fitz.mupdf.PdfPage) else raw
        fitz.mupdf.fz_run_page(
            fz_page, device, fitz.mupdf.FzMatrix(), fitz.mupdf.FzCookie()
        )
        fitz.mupdf.fz_close_device(device)
    except (RuntimeError, ValueError, TypeError, fitz.mupdf.FzErrorBase):
        logger.debug("stroke device run failed", exc_info=True)
        return None
    if device.failed:
        return None
    return tuple(device.records)


def _sigma_max(ctm: tuple[float, float, float, float, float, float]) -> float:
    """Largest singular value of the CTM's linear part, for ANY matrix:
    the most a user-space unit length can stretch.  ``inf`` when it cannot
    be computed (non-finite entries)."""
    a, b, c, d = ctm[:4]
    trace = a * a + b * b + c * c + d * d
    det = a * d - b * c
    disc = max(trace * trace - 4.0 * det * det, 0.0)
    sigma = math.sqrt((trace + math.sqrt(disc)) / 2.0)
    return sigma if math.isfinite(sigma) else math.inf


def _similarity_sigma(ctm: tuple[float, float, float, float, float, float]) -> float | None:
    """Largest singular value of the linear part when it is a similarity."""
    a, b, c, d = ctm[:4]
    n1 = math.hypot(a, b)
    n2 = math.hypot(c, d)
    scale = max(n1, n2)
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    if abs(n1 - n2) > _SIMILARITY_REL_TOL * scale:
        return None
    if abs(a * c + b * d) > _SIMILARITY_REL_TOL * scale * scale:
        return None
    sigma = _sigma_max(ctm)
    return sigma if math.isfinite(sigma) else None


def _ink_reach(record: StrokeRecord, *, margin: float) -> float:
    """Upper bound on how far this record's ink (plus ``margin``) lies from
    its path extent box, in visual space; ``inf`` when unknowable."""
    width = record.line_width
    if not math.isfinite(width) or width < 0.0:
        return math.inf
    if record.line_join not in _KNOWN_JOINS or not set(record.caps) <= _KNOWN_CAPS:
        return math.inf
    if record.line_join == _LINEJOIN_MITER:
        if not math.isfinite(record.miter_limit):
            return math.inf
        join_factor = max(1.0, record.miter_limit)
    else:
        join_factor = 1.0
    hw_max = 0.5 * width * _sigma_max(record.ctm)
    reach = hw_max * max(math.sqrt(2.0), join_factor) + margin
    if not math.isfinite(reach) or reach < 0.0:
        return math.inf
    return reach


def _point_rect_distance(point: Point, rect: fitz.Rect) -> float:
    x, y = point
    dx = max(rect.x0 - x, 0.0, x - rect.x1)
    dy = max(rect.y0 - y, 0.0, y - rect.y1)
    return math.hypot(dx, dy)


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    ax, ay = a
    vx, vy = b[0] - ax, b[1] - ay
    length2 = vx * vx + vy * vy
    if length2 == 0.0:
        return math.hypot(point[0] - ax, point[1] - ay)
    t = ((point[0] - ax) * vx + (point[1] - ay) * vy) / length2
    t = min(1.0, max(0.0, t))
    return math.hypot(point[0] - (ax + t * vx), point[1] - (ay + t * vy))


def _segment_hits_rect(a: Point, b: Point, rect: fitz.Rect) -> bool:
    """Liang-Barsky: does the closed segment meet the closed rect?"""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in (
        (-dx, a[0] - rect.x0),
        (dx, rect.x1 - a[0]),
        (-dy, a[1] - rect.y0),
        (dy, rect.y1 - a[1]),
    ):
        if p == 0.0:
            if q < 0.0:
                return False
            continue
        r = q / p
        if p < 0.0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


def segment_rect_distance(a: Point, b: Point, rect: fitz.Rect) -> float:
    """Exact Euclidean distance between a segment and an axis-aligned rect.

    Two disjoint convex polygons attain their distance between a vertex of
    one and an edge of the other, so the endpoint-to-rect and
    corner-to-segment distances cover every case."""
    if _segment_hits_rect(a, b, rect):
        return 0.0
    corners = (
        (rect.x0, rect.y0), (rect.x1, rect.y0), (rect.x0, rect.y1), (rect.x1, rect.y1),
    )
    return min(
        _point_rect_distance(a, rect),
        _point_rect_distance(b, rect),
        *(_point_segment_distance(corner, a, b) for corner in corners),
    )


def _join_radius(prev: Point, vertex: Point, nxt: Point, record: StrokeRecord, hw: float) -> float:
    if record.line_join != _LINEJOIN_MITER:
        return hw
    limit = max(1.0, record.miter_limit)
    ux, uy = prev[0] - vertex[0], prev[1] - vertex[1]
    wx, wy = nxt[0] - vertex[0], nxt[1] - vertex[1]
    nu, nw = math.hypot(ux, uy), math.hypot(wx, wy)
    if nu == 0.0 or nw == 0.0:
        return hw * limit
    cos_theta = max(-1.0, min(1.0, (ux * wx + uy * wy) / (nu * nw)))
    sin_half = math.sqrt((1.0 - cos_theta) / 2.0)
    if sin_half == 0.0:
        return hw * limit
    return hw * max(1.0, min(limit, 1.0 / sin_half))


def stroke_record_clears(record: StrokeRecord, zone: fitz.Rect, *, margin: float) -> bool:
    """True only when the record is exactly modelled and its stroked ink
    (plus ``margin``) provably misses ``zone``."""
    if record.has_curve or record.dash_len != 0:
        return False
    if not math.isfinite(record.line_width) or record.line_width <= 0.0:
        return False
    if record.line_join not in _KNOWN_JOINS or not set(record.caps) <= _KNOWN_CAPS:
        return False
    if not math.isfinite(record.miter_limit):
        return False
    sigma = _similarity_sigma(record.ctm)
    if sigma is None:
        return False
    hw = 0.5 * record.line_width * sigma
    segment_radius = hw * math.sqrt(2.0) + margin
    if not record.subpaths:
        return False
    for sub in record.subpaths:
        points = sub.points
        if not points:
            return False
        if len(points) == 1:
            if _point_rect_distance(points[0], zone) <= segment_radius:
                return False
            continue
        segments = list(zip(points, points[1:]))
        if sub.closed:
            segments.append((points[-1], points[0]))
        for a, b in segments:
            if segment_rect_distance(a, b, zone) <= segment_radius:
                return False
        count = len(points)
        join_indices = range(count) if sub.closed else range(1, count - 1)
        for index in join_indices:
            prev = points[index - 1]
            nxt = points[(index + 1) % count]
            vertex = points[index]
            radius = _join_radius(prev, vertex, nxt, record, hw) + margin
            if _point_rect_distance(vertex, zone) <= radius:
                return False
    return True


def drawing_is_exact_stroke_candidate(drawing: Mapping[str, object]) -> bool:
    """A ``get_drawings`` entry the exact proof may speak for: stroke-only
    (``type == 's'``, no fill), solid, straight ``l``/``re`` items only."""
    if drawing.get("type") != "s" or drawing.get("fill") is not None:
        return False
    if drawing.get("dashes") != "[] 0":
        return False
    items = drawing.get("items")
    if not isinstance(items, list) or not items:
        return False
    return all(isinstance(item, tuple) and item and item[0] in ("l", "re") for item in items)


def _drawing_vertices_visual(
    drawing: Mapping[str, object], to_visual: fitz.Matrix
) -> list[Point] | None:
    points: list[Point] = []
    items = drawing.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if item[0] == "l":
            raw = [item[1], item[2]]
        elif item[0] == "re":
            rect = fitz.Rect(item[1])
            raw = [rect.tl, rect.tr, rect.br, rect.bl]
        else:
            return None
        for point in raw:
            mapped = fitz.Point(point) * to_visual
            points.append((float(mapped.x), float(mapped.y)))
    return points


def _vertices_cover(left: Sequence[Point], right: Sequence[Point]) -> bool:
    return all(
        any(abs(p[0] - q[0]) <= _VERTEX_MATCH_TOL and abs(p[1] - q[1]) <= _VERTEX_MATCH_TOL for q in right)
        for p in left
    )


def _record_is_relevant(record: StrokeRecord, zone: fitz.Rect, *, margin: float) -> bool:
    """Could this record's INK come within ``margin`` of ``zone``?  Its path
    extent is inflated by ``_ink_reach`` plus ``_RELEVANCE_SLACK``; anything
    non-finite counts as relevant (fail closed: relevant records must be
    proven clear, irrelevant ones are never looked at again)."""
    extent = record.extent
    if not all(math.isfinite(v) for v in extent):
        return True
    grow = _ink_reach(record, margin=margin)
    if not math.isfinite(grow):
        return True
    grow += _RELEVANCE_SLACK
    return (
        extent[0] - grow <= zone.x1
        and extent[2] + grow >= zone.x0
        and extent[1] - grow <= zone.y1
        and extent[3] + grow >= zone.y0
    )


def strokes_provably_clear(
    page: fitz.Page,
    overlapping: Sequence[Mapping[str, object]],
    zone_visual: fitz.Rect,
    *,
    to_visual: fitz.Matrix,
    margin: float,
) -> bool:
    """True only when every drawing in ``overlapping`` (the ``get_drawings``
    entries whose bbox met the zone) is an exact stroke candidate, every
    device stroke whose INK REACH box meets the zone (``_record_is_relevant``)
    is exactly modelled and clear, and each candidate is matched
    vertex-for-vertex by one of those strokes -- the cross-check that
    ``get_drawings`` space mapped by ``to_visual`` and the device's visual
    space agree."""
    if not overlapping:
        return False
    if not all(drawing_is_exact_stroke_candidate(d) for d in overlapping):
        return False
    records = collect_stroke_records(page)
    if records is None:
        return False
    zone = fitz.Rect(zone_visual)
    zone.normalize()
    relevant = [r for r in records if _record_is_relevant(r, zone, margin=margin)]
    if not relevant:
        return False
    for record in relevant:
        if not stroke_record_clears(record, zone, margin=margin):
            return False
    for drawing in overlapping:
        vertices = _drawing_vertices_visual(drawing, to_visual)
        if not vertices:
            return False
        if not any(
            _vertices_cover(vertices, r.vertices()) and _vertices_cover(r.vertices(), vertices)
            for r in relevant
        ):
            return False
    return True
