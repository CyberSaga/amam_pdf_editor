"""O-flat (design plan section 9, card B1 completion item 2).

For every cubic of the rows: 2,000 points sampled on the exact curve (de Casteljau, here) lie within
``eps`` of the chord polyline, and every chord vertex lies on the curve.  Beyond the two stated
properties the oracle checks what makes them mean something: the cubic's chord run is a connected
polyline from the first to the last control point and every chord of it is flagged ``from_cubic``
(a missing segment is a gap, not a smaller error).

Independent source: the exact curve, evaluated by de Casteljau on the cubic's own control points; the
chord list is the product's input and is never used to build the curve.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from test_scripts.vector_index_rows import IndexRow

SAMPLES = 2000
EPS = 0.01
VERTEX_TOL = 1e-6  # design: float64 storage adds under 1e-9 pt at page scale; 1000x of room
_COARSE_GRID = 4001
_ZOOM_ROUNDS = 8  # the foot point must be found to 1e-12 in t for the absolute 1e-6 tolerance at 5,000 pt
_ZOOM_POINTS = 33
_CANDIDATES = 6


def vertex_tolerance(p4: np.ndarray) -> float:
    """The one tolerance of the vertex checks (gaps, end points, distance to the curve), shared by the
    oracle and the calibration's ground truth.  Absolute, not scaled with the page size: float64 storage
    adds under 1e-9 pt even at 5,000 pt, so a larger tolerance on a long curve would hide a real defect."""
    return VERTEX_TOL


def decasteljau(p4: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """Points of the cubic ``p4`` (4 x 2) at parameters ``ts`` (m,), by repeated linear interpolation."""
    t = ts[:, None]
    a = [np.broadcast_to(p4[k], (len(ts), 2)) for k in range(4)]
    for level in range(3, 0, -1):
        a = [(1.0 - t) * a[k] + t * a[k + 1] for k in range(level)]
    return a[0]


def _polyline_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray, chunk: int = 64) -> np.ndarray:
    """Distance of each point to the nearest segment ``a[i] -> b[i]``."""
    ab = b - a
    len2 = (ab * ab).sum(axis=1)
    safe = np.where(len2 > 0, len2, 1.0)
    out = np.empty(len(points))
    for s in range(0, len(points), chunk):
        p = points[s : s + chunk]
        rel = p[:, None, :] - a[None, :, :]
        t = np.clip((rel * ab[None, :, :]).sum(axis=2) / safe[None, :], 0.0, 1.0)
        t = np.where(len2[None, :] > 0, t, 0.0)
        proj = a[None, :, :] + t[:, :, None] * ab[None, :, :]
        out[s : s + chunk] = np.linalg.norm(p[:, None, :] - proj, axis=2).min(axis=1)
    return out


def _distance_to_curve(p4: np.ndarray, vertices: np.ndarray, chunk: int = 256) -> np.ndarray:
    """Distance of each vertex to the exact curve: a coarse grid, then repeated local zooms."""
    grid = np.linspace(0.0, 1.0, _COARSE_GRID)
    curve = decasteljau(p4, grid)
    out = np.empty(len(vertices))
    step0 = 1.0 / (_COARSE_GRID - 1)
    for s in range(0, len(vertices), chunk):
        v = vertices[s : s + chunk]
        d = np.linalg.norm(v[:, None, :] - curve[None, :, :], axis=2)
        # a loop or a cusp brings another branch close: refine from the best few local minima of the
        # coarse distance, not from the single nearest sample
        left = np.concatenate([np.full((len(v), 1), np.inf), d[:, :-1]], axis=1)
        right = np.concatenate([d[:, 1:], np.full((len(v), 1), np.inf)], axis=1)
        masked = np.where((d <= left) & (d <= right), d, np.inf)
        k = min(_CANDIDATES, masked.shape[1])
        pick = np.argpartition(masked, k - 1, axis=1)[:, :k]
        best = grid[pick].ravel()
        vv = np.repeat(v, k, axis=0)
        step = step0
        for _ in range(_ZOOM_ROUNDS):
            local = np.clip(best[:, None] + step * np.linspace(-1.0, 1.0, _ZOOM_POINTS)[None, :], 0.0, 1.0)
            pts = decasteljau(p4, local.ravel()).reshape(len(vv), _ZOOM_POINTS, 2)
            dd = np.linalg.norm(vv[:, None, :] - pts, axis=2)
            best = local[np.arange(len(vv)), dd.argmin(axis=1)]
            step = step * 2.0 / (_ZOOM_POINTS - 1)
        final = decasteljau(p4, best)
        out[s : s + chunk] = np.linalg.norm(vv - final, axis=1).reshape(len(v), k).min(axis=1)
    return out


def _check_cubic(ri: int, row: IndexRow, ci: int, eps: float, samples: int) -> list[str]:
    start, count, coords = row.cubics[ci]
    tag = f"O-flat: row {ri} cubic {ci}"
    if count < 1 or start < 0 or start + count > len(row.segments):
        return [f"{tag}: the chord run ({start}, {count}) lies outside the row's {len(row.segments)} segments"]
    run = row.segments[start : start + count]
    out: list[str] = []
    if not all(seg[4] for seg in run):
        out.append(f"{tag}: a chord of the run is not flagged from_cubic")
    p4 = np.array(coords, dtype=float).reshape(4, 2)
    a = np.array([[s[0], s[1]] for s in run], dtype=float)
    b = np.array([[s[2], s[3]] for s in run], dtype=float)
    # NaN compares False against every tolerance, so non-finite geometry would pass each check below:
    # refuse it first, in every position (control points, chord starts and ends).
    if not (np.isfinite(p4).all() and np.isfinite(a).all() and np.isfinite(b).all()):
        return [*out, f"{tag}: non-finite coordinate in the control points or the chord run"]
    tol = vertex_tolerance(p4)
    if count > 1:
        gaps = np.linalg.norm(b[:-1] - a[1:], axis=1)
        if (gaps > tol).any():
            out.append(f"{tag}: the chord run has {int((gaps > tol).sum())} gap(s) (a missing or displaced segment)")
    if np.linalg.norm(a[0] - p4[0]) > tol or np.linalg.norm(b[-1] - p4[3]) > tol:
        out.append(f"{tag}: the chord run does not start and end at the cubic's end points")
    vertices = np.vstack([a, b[-1:]])
    off = _distance_to_curve(p4, vertices)
    if (off > tol).any():
        out.append(f"{tag}: {int((off > tol).sum())} chord vertex(es) off the curve (worst {off.max():.3g} pt)")
    pts = decasteljau(p4, np.linspace(0.0, 1.0, samples))
    dev = _polyline_distance(pts, a, b)
    if (dev > eps + 1e-9).any():
        out.append(f"{tag}: the curve leaves the chord polyline by {dev.max():.3g} pt (epsilon {eps})")
    return out


def o_flat(rows: Sequence[IndexRow], *, eps: float = EPS, samples: int = SAMPLES) -> list[str]:
    """Violations (empty = accept) over every cubic of every row."""
    out: list[str] = []
    for ri, row in enumerate(rows):
        for ci in range(len(row.cubics)):
            out += _check_cubic(ri, row, ci, eps, samples)
    return out


o_flat.DOMAIN = frozenset({"CHORDS"})  # type: ignore[attr-defined]
