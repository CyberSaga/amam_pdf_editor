"""Batch 20 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import LineString, Polygon
from studio import Studio
from geo import f
from hamster_geo import regions, flow

s = Studio.open()
s.begin(5, "細化質感：毛流（二）內部毛向、受光毛與耳朵",
        "交界柔和了。現在頭部中間大片區域仍是光滑漸層，和邊緣的毛感脫節；左上受光面也缺少亮色的毛。耳朵外圈是平的。",
        "在杏色區依毛流撒稀疏的深色短毛（背光側較密）；左上受光區加奶油色亮毛；白色區補淡灰毛；耳朵沿外圈內側畫放射狀短毛。全部保持低不透明度，只在近看時出現。",
        tempo="rapid")
R = regions(s)
rng = random.Random(2001)
avoid = R["avoid"].buffer(1.0)
cx, cy, rx, ry = s.params["head"]

def qpath(x, y, d, ln, bend):
    ux, uy = d
    nx, ny = -uy, ux
    x2, y2 = x + ux * ln, y + uy * ln
    qx, qy = (x + x2) / 2 + nx * bend, (y + y2) / 2 + ny * bend
    return (x, y), (qx, qy), (x2, y2)

def place(prefix, region, count, col, op_rng, w_rng, ln_rng, weight, bend=0.6):
    n = 0
    minx, miny, maxx, maxy = region.bounds
    tries = 0
    while n < count and tries < 40000:
        tries += 1
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if rng.random() > weight(x, y):
            continue
        d = flow(x, y)
        p0, q, p2 = qpath(x, y, d, rng.uniform(*ln_rng), rng.uniform(-bend, bend))
        ln = LineString([p0, p2])
        if not region.contains(ln) or ln.intersects(avoid):
            continue
        s.add(f"{prefix}{n:03d}", "path", "hamster_fx",
              d=f"M{f(p0[0])} {f(p0[1])}Q{f(q[0])} {f(q[1])} {f(p2[0])} {f(p2[1])}", fill="none", stroke=col,
              stroke_width=round(rng.uniform(*w_rng), 2), stroke_opacity=round(rng.uniform(*op_rng), 2),
              stroke_linecap="round", anim="pop")
        n += 1
    return n

peach_in = R["peach"].buffer(-2.6)


def shade_w(x, y):
    return max(0.15, min(1.0, 0.45 + (x - cx) / 90 + (y - 300) / 120))


def lit_w(x, y):
    return max(0.0, min(1.0, 0.9 - (x - 200) / 70 - (y - 280) / 60))


n1 = place("fur_in", peach_in, 92, "#E3A466", (0.16, 0.3), (0.5, 0.78), (3.0, 5.4), shade_w)
lit_region = peach_in.intersection(Polygon([(180, 260), (262, 260), (262, 318), (180, 318)]))
n2 = place("fur_lt", lit_region, 46, "#FFF4E2", (0.35, 0.62), (0.6, 0.9), (2.8, 5.0), lit_w)
white_in = R["muzzle"].buffer(-2.4)
n3 = place("fur_wh", white_in, 34, "#D6CDCA", (0.22, 0.4), (0.5, 0.75), (2.6, 4.6), lambda x, y: 0.4 + (y - 335) / 30)
# ear fur: short radial strands just inside the outer rim (only where the ear is visible)
head_poly = R["head"]
m = 0
for i, (ex, ey, er) in enumerate(s.params["ears"]):
    a = rng.uniform(0, 8)
    while a < 360:
        a += rng.uniform(13, 19)
        t = math.radians(a)
        bx, by = ex + (er - 2.6) * math.cos(t), ey + (er - 2.6) * math.sin(t)
        tip = (ex + (er - 5.6) * math.cos(t + 0.12), ey + (er - 5.6) * math.sin(t + 0.12))
        line = LineString([(bx, by), tip])
        if line.intersects(head_poly.buffer(1.8)):
            continue
        s.add(f"fur_ear{m:02d}", "path", "hamster_fx", d=f"M{f(bx)} {f(by)}L{f(tip[0])} {f(tip[1])}", fill="none",
              stroke="#E09F60", stroke_width=round(rng.uniform(0.6, 0.85), 2), stroke_opacity=round(rng.uniform(0.35, 0.55), 2),
              stroke_linecap="round", anim="pop")
        m += 1
print("interior", n1, "lit", n2, "white", n3, "ear", m)
s.commit(zooms=[(176, 250, 160, 112)])
