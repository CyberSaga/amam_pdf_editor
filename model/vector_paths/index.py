"""Card B5 (design plan Step 4): selection queries over a VectorIndex.

Geometry is the path as constructed, in unrotated page space (D18).  A click tests the stroke centreline widened to
half the line width, and the fill (non-zero or even-odd by the paint operator) with segments.subpath as the contour
topology; touch and contain are marquee tests.  Design: plans/b5-fill-topology-clipped-design.md.

numpy is imported here only; the module is imported lazily by the model.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from model.vector_paths.scan import PAINT_NAMES, PathFlag, VectorIndex

Rect = tuple[float, float, float, float]

EDGE_BATCH = 65536  # edges per numpy crossing pass; a module constant so tests can force a batch break
CUBIC_EXTRA = 0.0025  # pt: one-sided allowance for a fill click beside a cubic (the stored chords are 0.01 pt)

_EDITABLE = int(PathFlag.EDITABLE)
_STROKE = frozenset({"S", "s", "B", "B*", "b", "b*"})
_FILL = frozenset({"f", "F", "f*", "B", "B*", "b", "b*"})
_EVEN_ODD = frozenset({"f*", "B*", "b*"})
_MODES = ("click", "touch", "contain")
_HOW = ("replace", "add", "toggle")


def _editable(index: VectorIndex) -> np.ndarray:
    return (index.paths["flags"].astype(np.int64) & _EDITABLE) != 0


def _check_mask(index: VectorIndex, mask: np.ndarray) -> None:
    if mask.shape != (len(index.paths),):
        raise ValueError("mask length does not match the index")


def _ranges(starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Concatenated arange(start, start + count) for every pair, without a Python loop."""
    counts = counts.astype(np.int64)
    total = int(counts.sum())
    if total == 0:
        return np.zeros(0, dtype=np.int64)
    ends = np.cumsum(counts)
    offsets = np.arange(total, dtype=np.int64) - np.repeat(ends - counts, counts)
    return np.repeat(starts.astype(np.int64), counts) + offsets


def select(index: VectorIndex, rect: Rect, tolerance: float, mode: Literal["click", "touch", "contain"]) -> np.ndarray:
    """Bool mask over paths; non-editable rows are never set."""
    return _select(index, rect, tolerance, mode, _editable(index)) if len(index.paths) else np.zeros(0, dtype=bool)


def select_counting_skipped(
    index: VectorIndex, rect: Rect, tolerance: float, mode: Literal["click", "touch", "contain"]
) -> tuple[np.ndarray, int]:
    """(mask, skipped): one geometry pass over all rows, split by EDITABLE.

    skipped = non-editable rows the geometry reaches (a click: 1 when nothing editable is hit but a non-editable row
    is).  The mask equals select(...) exactly."""
    n = len(index.paths)
    if n == 0:
        if mode not in _MODES:
            raise ValueError(f"unknown mode {mode!r}")
        return np.zeros(0, dtype=bool), 0
    editable = _editable(index)
    everything = np.ones(n, dtype=bool)
    hit = _select(index, rect, tolerance, mode, everything)
    if mode == "click":
        if not hit.any():
            return hit, 0
        if bool((hit & editable).any()):
            return hit, 0
        # the topmost row under the click is not editable: look underneath it for an editable one
        mask = _select(index, rect, tolerance, mode, editable)
        return mask, int(not mask.any())
    return hit & editable, int((hit & ~editable).sum())


def skipped_by_query(index: VectorIndex, rect: Rect, tolerance: float, mode: Literal["click", "touch", "contain"]) -> int:
    return select_counting_skipped(index, rect, tolerance, mode)[1]


def _select(index: VectorIndex, rect: Rect, tolerance: float, mode: str, editable: np.ndarray) -> np.ndarray:
    if mode not in _MODES:
        raise ValueError(f"unknown mode {mode!r}")
    n = len(index.paths)
    out = np.zeros(n, dtype=bool)
    if n == 0:
        return out
    x0, y0, x1, y1 = (float(v) for v in rect)
    if mode == "click":
        return _click(index, (x0 + x1) / 2.0, (y0 + y1) / 2.0, max(0.0, float(tolerance)), editable)
    if not (x1 > x0 and y1 > y0):
        return out
    bbox = index.paths["bbox"].astype(np.float64)
    has_seg = index.paths["seg_count"] > 0
    cand = editable & has_seg & (bbox[:, 0] <= x1) & (bbox[:, 2] >= x0) & (bbox[:, 1] <= y1) & (bbox[:, 3] >= y0)
    inside = (bbox[:, 0] >= x0) & (bbox[:, 2] <= x1) & (bbox[:, 1] >= y0) & (bbox[:, 3] <= y1)
    if mode == "contain":
        return cand & inside
    out |= cand & inside  # fast path: the box is inside, so every segment is
    rest = np.flatnonzero(cand & ~inside)
    if rest.size:
        starts = index.paths["seg_start"][rest]
        counts = index.paths["seg_count"][rest]
        seg_ids = _ranges(starts, counts)
        hit = _segments_touch(index.segments[seg_ids], (x0, y0, x1, y1))
        owner = np.repeat(np.arange(rest.size), counts.astype(np.int64))
        hit_rows = np.zeros(rest.size, dtype=bool)
        hit_rows[owner[hit]] = True
        out[rest[hit_rows]] = True
    return out


def _segments_touch(seg: np.ndarray, rect: Rect) -> np.ndarray:
    """Liang-Barsky over many segments at once: True where the closed segment meets the closed rectangle."""
    x0, y0, x1, y1 = rect
    ax, ay, bx, by = (seg[k].astype(np.float64) for k in ("x0", "y0", "x1", "y1"))
    dx, dy = bx - ax, by - ay
    t0: np.ndarray = np.zeros(len(seg))
    t1: np.ndarray = np.ones(len(seg))
    ok = np.ones(len(seg), dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
            parallel = p == 0
            ok &= ~(parallel & (q < 0))
            r = np.where(parallel, 0.0, q / np.where(parallel, 1.0, p))
            t0 = np.where(~parallel & (p < 0), np.maximum(t0, r), t0)
            t1 = np.where(~parallel & (p > 0), np.minimum(t1, r), t1)
    return ok & (t0 <= t1)


# --------------------------------------------------------------------------- click


def _click(index: VectorIndex, px: float, py: float, tol: float, editable: np.ndarray) -> np.ndarray:
    paths = index.paths
    out = np.zeros(len(paths), dtype=bool)
    bbox = paths["bbox"].astype(np.float64)
    codes = paths["paint"].astype(np.int64)
    stroke_row = np.array([name in _STROKE for name in PAINT_NAMES], dtype=bool)[codes]
    fill_row = np.array([name in _FILL for name in PAINT_NAMES], dtype=bool)[codes]
    lw = paths["line_width"].astype(np.float64)
    half = np.where(np.isfinite(lw) & (lw > 0), lw / 2.0, 0.0)
    radius = np.where(stroke_row, np.maximum(tol, half), tol) + np.where(fill_row, CUBIC_EXTRA, 0.0)
    near = (
        editable
        & (paths["seg_count"] > 0)
        & (bbox[:, 0] - radius <= px)
        & (bbox[:, 2] + radius >= px)
        & (bbox[:, 1] - radius <= py)
        & (bbox[:, 3] + radius >= py)
    )
    for i in np.flatnonzero(near)[::-1]:  # topmost (largest row) first
        name = PAINT_NAMES[int(codes[i])]
        if _row_hits(index, int(i), name, px, py, tol, float(half[i])):
            out[i] = True
            break
    return out


def _point_segment_distance(px: float, py: float, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distances from (px, py) to each segment a[i] -> b[i] (arrays of shape (K, 2))."""
    d = b - a
    len2 = d[:, 0] ** 2 + d[:, 1] ** 2
    t: np.ndarray = np.zeros(len(a))
    nz = len2 > 0
    t[nz] = ((px - a[nz, 0]) * d[nz, 0] + (py - a[nz, 1]) * d[nz, 1]) / len2[nz]
    t = np.clip(t, 0.0, 1.0)
    cx = a[:, 0] + t * d[:, 0]
    cy = a[:, 1] + t * d[:, 1]
    return np.hypot(px - cx, py - cy)


def _row_hits(index: VectorIndex, i: int, name: str, px: float, py: float, tol: float, half: float) -> bool:
    row = index.paths[i]
    a0, k = int(row["seg_start"]), int(row["seg_count"])
    seg = index.segments[a0 : a0 + k]
    if name in _STROKE:
        r = max(tol, half)
        a = np.stack([seg["x0"], seg["y0"]], axis=1)
        b = np.stack([seg["x1"], seg["y1"]], axis=1)
        if bool((_point_segment_distance(px, py, a, b) <= r).any()):
            return True
    if name in _FILL:
        return _fill_hits(index, i, seg, a0, name in _EVEN_ODD, px, py, tol)
    return False


def _fill_edges(index: VectorIndex, i: int, seg: np.ndarray, a0: int) -> tuple[np.ndarray, np.ndarray]:
    """Edges (E, 4) for winding, and a bool array marking edges that come from a cubic (they get the extra allowance)."""
    edges = np.stack([seg["x0"], seg["y0"], seg["x1"], seg["y1"]], axis=1).astype(np.float64)
    cubic = seg["from_cubic"].astype(bool)
    if cubic.any():
        edges, cubic = _bisect_cubic_chords(index, i, seg, a0, edges, cubic)
    sub = seg["subpath"]
    if len(sub):
        cuts = np.flatnonzero(np.diff(sub) != 0)
        first = np.concatenate([[0], cuts + 1])
        last = np.concatenate([cuts, [len(sub) - 1]])
        fx, fy = seg["x0"][first], seg["y0"][first]
        lx, ly = seg["x1"][last], seg["y1"][last]
        open_run = (fx != lx) | (fy != ly)
        if open_run.any():
            closing = np.stack([lx[open_run], ly[open_run], fx[open_run], fy[open_run]], axis=1).astype(np.float64)
            edges = np.concatenate([edges, closing])
            cubic = np.concatenate([cubic, np.zeros(len(closing), dtype=bool)])
    return edges, cubic


def _bisect_cubic_chords(index: VectorIndex, i: int, seg: np.ndarray, a0: int, edges: np.ndarray, cubic: np.ndarray):
    """Replace each stored chord of a cubic by two chords through the curve's parameter midpoint (quarters the error)."""
    cub = index.cubics
    sel = cub[cub["path"] == i]
    pieces: list[np.ndarray] = []
    flags: list[np.ndarray] = []
    covered = np.zeros(len(seg), dtype=bool)
    for c in sel:
        n = int(c["seg_count"])
        s0 = int(c["seg_start"]) - a0
        if n <= 0 or s0 < 0 or s0 + n > len(seg):
            continue
        p = np.asarray(c["pts"], dtype=np.float64).reshape(4, 2)
        t = (2.0 * np.arange(n) + 1.0) / (2.0 * n)
        u = 1.0 - t
        mid = (u**3)[:, None] * p[0] + (3 * u**2 * t)[:, None] * p[1] + (3 * u * t**2)[:, None] * p[2] + (t**3)[:, None] * p[3]
        e = edges[s0 : s0 + n]
        first = np.concatenate([e[:, :2], mid], axis=1)
        second = np.concatenate([mid, e[:, 2:]], axis=1)
        pieces.append(np.stack([first, second], axis=1).reshape(-1, 4))
        flags.append(np.ones(2 * n, dtype=bool))
        covered[s0 : s0 + n] = True
    keep = edges[~covered]
    keep_flags = cubic[~covered]
    if not pieces:
        return edges, cubic
    return np.concatenate([keep, *pieces]), np.concatenate([keep_flags, *flags])


def _fill_hits(index: VectorIndex, i: int, seg: np.ndarray, a0: int, even_odd: bool, px: float, py: float, tol: float) -> bool:
    edges, cubic = _fill_edges(index, i, seg, a0)
    if len(edges) == 0:
        return False
    # outline: on or within tolerance (cubic halves get the one-sided allowance)
    a, b = edges[:, 0:2], edges[:, 2:4]
    near = _point_segment_distance(px, py, a, b) <= np.where(cubic, tol + CUBIC_EXTRA, tol)
    if bool(near.any()):
        return True
    total = 0
    for s in range(0, len(edges), max(1, int(EDGE_BATCH))):
        e = edges[s : s + EDGE_BATCH]
        ex0, ey0, ex1, ey1 = e[:, 0], e[:, 1], e[:, 2], e[:, 3]
        d = (ex1 - ex0) * (py - ey0) - (ey1 - ey0) * (px - ex0)
        up = (ey0 <= py) & (py < ey1) & (d > 0)
        down = (ey1 <= py) & (py < ey0) & (d < 0)
        total += int(up.sum()) - int(down.sum())
    return (total % 2 == 1) if even_odd else total != 0


# --------------------------------------------------------------------------- selection helpers


def combine(old: np.ndarray, new: np.ndarray, how: Literal["replace", "add", "toggle"]) -> np.ndarray:
    if how not in _HOW:
        raise ValueError(f"unknown combine {how!r}")
    if old.shape != new.shape:
        raise ValueError("masks differ in length")
    if how == "replace":
        return new.copy()
    if how == "add":
        return old | new
    return old ^ new


def summary(index: VectorIndex, mask: np.ndarray) -> tuple[int, int, tuple[float, float, float, float] | None]:
    """(selected, skipped, bbox): a masked row that is not editable is skipped, never selected."""
    _check_mask(index, mask)
    editable = _editable(index)
    chosen = mask & editable
    skipped = int((mask & ~editable).sum())
    count = int(chosen.sum())
    if count == 0:
        return 0, skipped, None
    box = index.paths["bbox"][chosen].astype(np.float64)
    return count, skipped, (float(box[:, 0].min()), float(box[:, 1].min()), float(box[:, 2].max()), float(box[:, 3].max()))


def selected_segments(index: VectorIndex, mask: np.ndarray) -> np.ndarray:
    """float32 (K, 4) of the selected editable rows' segments (display only)."""
    _check_mask(index, mask)
    rows = np.flatnonzero(mask & _editable(index))
    if rows.size == 0:
        return np.zeros((0, 4), dtype=np.float32)
    ids = _ranges(index.paths["seg_start"][rows], index.paths["seg_count"][rows])
    seg = index.segments[ids]
    return np.stack([seg["x0"], seg["y0"], seg["x1"], seg["y1"]], axis=1).astype(np.float32)
