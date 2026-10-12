"""Batch 18 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import Point, LineString
from studio import Studio
from geo import f
from hamster_geo import regions, flow

s = Studio.open()
s.begin(5, "細化質感：毛流（一）杏白交界與背光側",
        "臉部五官有神了，但杏色與白色之間是一條光滑的向量曲線，像兩塊貼紙拼接；頭的兩側只有漸層，沒有毛的手感。",
        "沿杏白交界交錯畫短毛：白毛往上咬進杏色、杏毛往下咬進白色，讓交界蓬鬆。再沿頭部內緣、依「從鼻尖向外放射、兩頰下垂」的毛流畫深杏色短毛，背光的右側與下側較密，受光的左上較疏。",
        tempo="rapid")
R = regions(s)
rng = random.Random(1801)
head_in = R["head"].buffer(-2.2)
avoid = R["avoid"]

def strand(x, y, ln, bend, dirv):
    ux, uy = dirv
    nx, ny = -uy, ux
    x2, y2 = x + ux * ln, y + uy * ln
    cx_, cy_ = (x + x2) / 2 + nx * bend, (y + y2) / 2 + ny * bend
    return (x, y), (cx_, cy_), (x2, y2)

def ok(p0, p2, region):
    line = LineString([p0, p2])
    return region.contains(line) and not line.intersects(avoid)

n = 0
# (1) interlocking fur along the peach/white boundary
bd = R["boundary"]
line = LineString(bd)
L = line.length
t = 0.0
k = 0
while t < L:
    p = line.interpolate(t).coords[0]
    q = line.interpolate(min(L, t + 0.5)).coords[0]
    tx, ty = q[0] - p[0], q[1] - p[1]
    tl = math.hypot(tx, ty) or 1
    nx, ny = ty / tl, -tx / tl   # normal pointing up (into peach) for left->right curve
    if ny > 0:
        nx, ny = -nx, -ny
    fx, fy = flow(*p)
    for up in (True, False):
        if up:   # white tuft biting up into the peach
            d = (nx * 0.7 + fx * 0.3, ny * 0.7 + fy * 0.3)
            col, op, w = "#FFFFFF", round(rng.uniform(0.75, 0.95), 2), round(rng.uniform(0.8, 1.15), 2)
            base = (p[0] - nx * 1.2, p[1] - ny * 1.2)
        else:    # peach tuft dipping down into the white
            d = (-nx * 0.7 + fx * 0.3, -ny * 0.7 + fy * 0.3)
            col, op, w = "#F3C084", round(rng.uniform(0.55, 0.8), 2), round(rng.uniform(0.7, 1.0), 2)
            base = (p[0] + nx * 1.2, p[1] + ny * 1.2)
        dl = math.hypot(*d) or 1
        d = (d[0] / dl, d[1] / dl)
        ln = rng.uniform(2.6, 5.2)
        p0, c, p2 = strand(base[0] + rng.uniform(-0.6, 0.6), base[1], ln, rng.uniform(-1.0, 1.0), d)
        if not ok(p0, p2, head_in):
            continue
        s.add(f"fur_bd{n:03d}", "path", "hamster_fx", d=f"M{f(p0[0])} {f(p0[1])}Q{f(c[0])} {f(c[1])} {f(p2[0])} {f(p2[1])}",
              fill="none", stroke=col, stroke_width=w, stroke_opacity=op, stroke_linecap="round", anim="pop")
        n += 1
    t += rng.uniform(1.5, 2.3)
nb = n
# (2) shadow-side strands along the inside of the head outline, following the flow
edge_ring = list(R["head"].buffer(-4.5).exterior.coords)
er = LineString(edge_ring)
tries = 0
m = 0
while m < 110 and tries < 6000:
    tries += 1
    p = er.interpolate(rng.uniform(0, er.length)).coords[0]
    x, y = p
    if y > 352:
        continue
    # density: right/lower side dense, upper-left sparse
    shade = 0.5 + 0.5 * ((x - 256) / 60) + 0.35 * ((y - 300) / 55)
    if rng.random() > max(0.12, min(1.0, shade)):
        continue
    inset = rng.uniform(0, 5)
    cx0, cy0 = s.params["head"][0], s.params["head"][1]
    vx, vy = cx0 - x, cy0 - y
    vl = math.hypot(vx, vy) or 1
    x, y = x + vx / vl * inset, y + vy / vl * inset
    in_white = R["muzzle"].contains(Point(x, y))
    d = flow(x, y)
    ln = rng.uniform(3.2, 6.0)
    p0, c, p2 = strand(x, y, ln, rng.uniform(-1.4, 1.4), d)
    region = R["muzzle"].buffer(-0.8) if in_white else R["peach"].buffer(-0.8)
    if not ok(p0, p2, region):
        continue
    col = "#D9CFCB" if in_white else "#DE9A5A"
    op = round(rng.uniform(0.35, 0.6) if in_white else rng.uniform(0.28, 0.5), 2)
    s.add(f"fur_sh{m:03d}", "path", "hamster_fx", d=f"M{f(p0[0])} {f(p0[1])}Q{f(c[0])} {f(c[1])} {f(p2[0])} {f(p2[1])}",
          fill="none", stroke=col, stroke_width=round(rng.uniform(0.6, 0.95), 2), stroke_opacity=op,
          stroke_linecap="round", anim="pop")
    m += 1
print("boundary", nb, "shadow-side", m)
s.commit(zooms=[(176, 250, 160, 112), (190, 300, 70, 56)])
