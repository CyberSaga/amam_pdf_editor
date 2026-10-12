"""Brush utilities: resampled offset rings, runs along edges, double-taper strokes."""
from __future__ import annotations

import math
import random

from shapely.geometry import LineString, Point, Polygon

from geo import smooth_d


def resample(coords, step):
    line = LineString(coords)
    n = max(2, int(line.length / step))
    return [line.interpolate(i * line.length / n).coords[0] for i in range(n + 1)]


def offset_ring(pts, dist, step=2.0):
    """Closed ring offset inward (dist>0) or outward (dist<0), resampled."""
    poly = Polygon(pts).buffer(-dist, join_style=1)
    ring = list(poly.exterior.coords)
    # make it start at the left-most top point for determinism
    return resample(ring, step)


def runs(pts, pred):
    """Contiguous runs of points satisfying pred (handles wrap-around)."""
    flags = [pred(x, y) for x, y in pts]
    n = len(pts)
    if all(flags):
        return [pts]
    start = next(i for i in range(n) if not flags[i])
    out, cur = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        if flags[i]:
            cur.append(pts[i])
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def chop(run, seg_len, overlap, rng: random.Random, jitter=0.25):
    """Split a run of points into overlapping segments of ~seg_len (in points)."""
    segs = []
    i = 0
    while i < len(run) - 1:
        ln = max(2, int(seg_len * rng.uniform(1 - jitter, 1 + jitter)))
        j = min(len(run), i + ln)
        segs.append(run[i:j])
        if j >= len(run):
            break
        i = max(i + 1, j - overlap)
    return segs


def taper2_d(points, w_max, w_end=0.3):
    """Filled stroke, thin at both ends and w_max in the middle (sin profile)."""
    n = len(points)
    if n < 3:
        points = [points[0], ((points[0][0] + points[-1][0]) / 2, (points[0][1] + points[-1][1]) / 2), points[-1]]
        n = 3
    left, right = [], []
    for i, (x, y) in enumerate(points):
        if i == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        elif i == n - 1:
            dx, dy = x - points[i - 1][0], y - points[i - 1][1]
        else:
            dx, dy = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        t = i / (n - 1)
        w = (w_end + (w_max - w_end) * math.sin(math.pi * t)) / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    return smooth_d(left + right[::-1], closed=True, tension=0.7)


def scatter_in(poly: Polygon, n, rng: random.Random, margin=0.0, avoid=None, tries=50000):
    """Uniform random points inside poly (shrunk by margin), avoiding other polys."""
    region = poly.buffer(-margin) if margin else poly
    minx, miny, maxx, maxy = region.bounds
    pts = []
    t = 0
    while len(pts) < n and t < tries:
        t += 1
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        p = Point(x, y)
        if not region.contains(p):
            continue
        if avoid is not None and avoid.contains(p):
            continue
        pts.append((x, y))
    return pts


def pressure_d(points, w, rng: random.Random, taper=0.18, wobble=0.12, w_end=0.25):
    """Filled stroke with brush-pressure profile: tapered ends, gentle width noise."""
    n = len(points)
    if n < 3:
        raise ValueError("need >= 3 points")
    # low-frequency noise
    k1, k2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    f1, f2 = rng.uniform(1.0, 2.2), rng.uniform(2.5, 4.5)
    left, right = [], []
    for i, (x, y) in enumerate(points):
        if i == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        elif i == n - 1:
            dx, dy = x - points[i - 1][0], y - points[i - 1][1]
        else:
            dx, dy = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        t = i / (n - 1)
        env = 1.0
        if t < taper:
            u = t / taper
            env = u * u * (3 - 2 * u)
        elif t > 1 - taper:
            u = (1 - t) / taper
            env = u * u * (3 - 2 * u)
        noise = 1 + wobble * (0.6 * math.sin(f1 * math.pi * t * 2 + k1) + 0.4 * math.sin(f2 * math.pi * t * 2 + k2))
        ww = (w_end + (w - w_end) * env) * noise / 2
        left.append((x + nx * ww, y + ny * ww))
        right.append((x - nx * ww, y - ny * ww))
    return smooth_d(left + right[::-1], closed=True, tension=0.7)


def sub_run(run, t0, t1):
    n = len(run)
    a, b = int(t0 * (n - 1)), int(t1 * (n - 1))
    return run[a:b + 1]
