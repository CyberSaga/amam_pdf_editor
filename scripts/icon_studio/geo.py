"""Geometry helpers: number formatting, path builders, sketch strokes."""
from __future__ import annotations

import math
import random

from shapely.geometry import LineString, Point, Polygon


def f(v: float) -> str:
    """Compact number formatting (2 decimals, trimmed)."""
    if isinstance(v, int):
        return str(v)
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def pts_d(points, closed=False) -> str:
    """Polyline path through points (M/L)."""
    out = [f"M{f(points[0][0])} {f(points[0][1])}"]
    for x, y in points[1:]:
        out.append(f"L{f(x)} {f(y)}")
    if closed:
        out.append("Z")
    return "".join(out)


def smooth_d(points, closed=False, tension=1.0) -> str:
    """Catmull-Rom spline through points, emitted as cubic Beziers."""
    n = len(points)
    if n < 2:
        raise ValueError("need >= 2 points")
    if n == 2:
        return pts_d(points)
    pts = list(points)
    out = [f"M{f(pts[0][0])} {f(pts[0][1])}"]
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = pts[(i - 1) % n] if (closed or i > 0) else pts[i]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if (closed or i + 2 < n) else pts[(i + 1) % n]
        t = tension / 6.0
        c1 = (p1[0] + (p2[0] - p0[0]) * t, p1[1] + (p2[1] - p0[1]) * t)
        c2 = (p2[0] - (p3[0] - p1[0]) * t, p2[1] - (p3[1] - p1[1]) * t)
        out.append(
            f"C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(p2[0])} {f(p2[1])}"
        )
    if closed:
        out.append("Z")
    return "".join(out)


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_pt(p, q, t):
    return (lerp(p[0], q[0], t), lerp(p[1], q[1], t))


def wobble_pts(p0, p1, rng: random.Random, amp=1.2, n=6, overshoot=0.0, bow=0.0):
    """Points along p0->p1 with hand jitter, optional overshoot and bow."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    a = -overshoot * rng.uniform(0.3, 1.0)
    b = 1 + overshoot * rng.uniform(0.3, 1.0)
    pts = []
    for i in range(n):
        t = a + (b - a) * i / (n - 1)
        off = rng.uniform(-amp, amp) + bow * math.sin(math.pi * t) * length
        pts.append((p0[0] + dx * t + nx * off, p0[1] + dy * t + ny * off))
    return pts


def ellipse_pts(cx, cy, rx, ry, a0=0.0, a1=360.0, n=24, rot=0.0):
    pts = []
    cr, sr = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    for i in range(n):
        a = math.radians(a0 + (a1 - a0) * i / (n - 1))
        x, y = rx * math.cos(a), ry * math.sin(a)
        pts.append((cx + x * cr - y * sr, cy + x * sr + y * cr))
    return pts


def wobble_ellipse(cx, cy, rx, ry, rng, amp=1.0, a0=None, sweep=None, n=18):
    """A hand-drawn ellipse stroke that does not close perfectly."""
    a0 = rng.uniform(0, 360) if a0 is None else a0
    sweep = rng.uniform(340, 380) if sweep is None else sweep
    pts = []
    for i in range(n):
        a = math.radians(a0 + sweep * i / (n - 1))
        k = 1 + rng.uniform(-amp, amp) / max(rx, ry)
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    return pts


def body_outline_pts(x0, y0, x1, y1, r, ch, rch, seg=6):
    """Rounded rect with a chamfered top-right corner, as a dense point loop.

    r: corner radius for the three square corners; ch: chamfer leg length;
    rch: rounding radius at the two chamfer corners. Point count is fixed for
    given seg so morphs between parameter sets stay compatible.
    """
    pts = []

    def arc(cx, cy, rad, a_start, a_end):
        for i in range(seg + 1):
            a = math.radians(a_start + (a_end - a_start) * i / seg)
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))

    # top-left corner
    arc(x0 + r, y0 + r, r, 180, 270)
    # top edge to chamfer start (rounded with rch): chamfer from (x1-ch, y0) to (x1, y0+ch)
    # corner between top edge (dir +x) and chamfer (dir +x,+y at 45deg): turn 45 deg
    t = rch * math.tan(math.radians(22.5))
    c1 = (x1 - ch - t, y0 + rch)
    arc(c1[0], c1[1], rch, 270, 315)
    c2 = (x1 - rch, y0 + ch + t)
    arc(c2[0], c2[1], rch, 315, 360)
    # bottom-right corner
    arc(x1 - r, y1 - r, r, 0, 90)
    # bottom-left corner
    arc(x0 + r, y1 - r, r, 90, 180)
    return pts


def rrect_pts(x0, y0, x1, y1, r, seg=6):
    pts = []

    def arc(cx, cy, rad, a_start, a_end):
        for i in range(seg + 1):
            a = math.radians(a_start + (a_end - a_start) * i / seg)
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))

    arc(x0 + r, y0 + r, r, 180, 270)
    arc(x1 - r, y0 + r, r, 270, 360)
    arc(x1 - r, y1 - r, r, 0, 90)
    arc(x0 + r, y1 - r, r, 90, 180)
    return pts


def poly(points) -> Polygon:
    return Polygon(points)


def clip_line(p0, p1, region: Polygon):
    """Clip segment to region; returns list of (a, b) inside pieces."""
    inter = LineString([p0, p1]).intersection(region)
    out = []
    if inter.is_empty:
        return out
    geoms = getattr(inter, "geoms", [inter])
    for g in geoms:
        if g.geom_type == "LineString" and g.length > 0.5:
            cs = list(g.coords)
            out.append((cs[0], cs[-1]))
    return out


def inside(region: Polygon, x, y, margin=0.0) -> bool:
    p = Point(x, y)
    if margin <= 0:
        return region.contains(p)
    return region.buffer(-margin).contains(p)


def tri_d(p, q, r) -> str:
    return pts_d([p, q, r], closed=True)


def taper_stroke_d(points, w0, w1) -> str:
    """Closed filled path for a stroke tapering from width w0 to w1."""
    n = len(points)
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
        w = lerp(w0, w1, i / (n - 1)) / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    loop = left + right[::-1]
    return smooth_d(loop, closed=True, tension=0.8)


def body_outline_d(x0, y0, x1, y1, r, ch, rch) -> str:
    """SVG path (M/L/A) for the floppy body: rounded rect, chamfered top-right.

    Always emits the same command sequence, so two parameter sets morph cleanly.
    """
    t = rch * math.tan(math.radians(22.5))
    k = math.sqrt(0.5)
    c1 = (x1 - ch - t, y0 + rch)
    p1a = (c1[0], y0)
    p1b = (c1[0] + rch * k, c1[1] - rch * k)
    c2 = (x1 - rch, y0 + ch + t)
    p2a = (c2[0] + rch * k, c2[1] - rch * k)
    p2b = (x1, c2[1])
    seq = [
        f"M{f(x0)} {f(y0 + r)}",
        f"A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}",
        f"L{f(p1a[0])} {f(p1a[1])}",
        f"A{f(rch)} {f(rch)} 0 0 1 {f(p1b[0])} {f(p1b[1])}",
        f"L{f(p2a[0])} {f(p2a[1])}",
        f"A{f(rch)} {f(rch)} 0 0 1 {f(p2b[0])} {f(p2b[1])}",
        f"L{f(x1)} {f(y1 - r)}",
        f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}",
        f"L{f(x0 + r)} {f(y1)}",
        f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}",
        "Z",
    ]
    return "".join(seq)


def rrect_d(x0, y0, x1, y1, r) -> str:
    """SVG path for a rounded rectangle (fixed command sequence)."""
    seq = [
        f"M{f(x0)} {f(y0 + r)}",
        f"A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}",
        f"L{f(x1 - r)} {f(y0)}",
        f"A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}",
        f"L{f(x1)} {f(y1 - r)}",
        f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}",
        f"L{f(x0 + r)} {f(y1)}",
        f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}",
        "Z",
    ]
    return "".join(seq)


def poly_d(geom, closed=True) -> str:
    """Path data for a shapely Polygon / MultiPolygon (exteriors + holes)."""
    parts = []
    geoms = getattr(geom, "geoms", [geom])
    for g in geoms:
        if g.is_empty:
            continue
        rings = [list(g.exterior.coords)[:-1]] + [list(i.coords)[:-1] for i in g.interiors]
        for ring in rings:
            if len(ring) >= 3:
                parts.append(pts_d(ring, closed=True))
    return "".join(parts)


def inner_band(outer_pts, dx, dy):
    """Region of the hole `outer` NOT covered by `outer` shifted by (dx, dy)."""
    from shapely.affinity import translate
    o = Polygon(outer_pts)
    return o.difference(translate(o, dx, dy))


def catmull_pts(points, closed=False, k=8, tension=1.0):
    """Sample the same Catmull-Rom curve smooth_d draws (k samples per segment)."""
    n = len(points)
    pts = list(points)
    out = []
    rng_ = range(n) if closed else range(n - 1)
    for i in rng_:
        p0 = pts[(i - 1) % n] if (closed or i > 0) else pts[i]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if (closed or i + 2 < n) else pts[(i + 1) % n]
        t_ = tension / 6.0
        c1 = (p1[0] + (p2[0] - p0[0]) * t_, p1[1] + (p2[1] - p0[1]) * t_)
        c2 = (p2[0] - (p3[0] - p1[0]) * t_, p2[1] - (p3[1] - p1[1]) * t_)
        for j in range(k):
            t = j / k
            mt = 1 - t
            x = mt**3 * p1[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t**3 * p2[0]
            y = mt**3 * p1[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t**3 * p2[1]
            out.append((x, y))
    if not closed:
        out.append(pts[-1])
    return out
