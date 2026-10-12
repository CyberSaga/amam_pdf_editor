"""Batch 25 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import LineString
from studio import Studio
from geo import f
from brush import pressure_d
from hamster_geo import regions, flow

INK = "#1E1D38"
s = Studio.open()
s.begin(5, "細化倉鼠：輪廓粗細、反光、絨毛與第三層細毛",
        "倉鼠的輪廓是一條等粗的線，圓頭顯得硬；右側背光處和紙面之間沒有反光，頭頂也缺一塊毛的光澤。中距離看毛流還不夠綿密。",
        "頭部背光的右下補一道墨線加粗；右緣內側加一道紙面反射上來的暖色反光；頭頂左上加一塊柔邊毛光澤；左耳受光緣加亮；頭頂與兩頰各加幾縷越出輪廓的細絨毛；最後依毛流再鋪一層更細更短的毛。",
        tempo="rapid")
R = regions(s)
cx, cy, rx, ry = s.params["head"]
rng = random.Random(2501)
def ell(a, k=1.0):
    t = math.radians(a)
    return (cx + rx * k * math.cos(t), cy + ry * k * math.sin(t))
# heavier ink on the shadow side (right, from ~ -40deg down to the cut)
a_end = math.degrees(math.asin((355 - cy) / ry))
pts = [ell(-38 + (a_end + 38) * i / 10, 1.0 - 0.012) for i in range(11)]
s.add("ink_head_heavy", "path", "hamster", d=pressure_d(pts, 2.0, rng, taper=0.35, w_end=0.3), fill=INK, anim="draw")
# warm bounce light inside the right edge
pts = [ell(-30 + (a_end + 24) * i / 10, 0.93) for i in range(11)]
s.add("hm_rimlight", "path", "hamster_fx", d=pressure_d(pts, 2.4, rng, taper=0.35), fill="#FFE7C6", fill_opacity=0.75, anim="draw")
# fur sheen on the top-left of the head
g = s.gradient("g_fur_sheen", "radial", [(0, "#FFF6E8", 0.7), (1, "#FFF6E8", 0)], gradientUnits="userSpaceOnUse",
               cx=236, cy=292, r=22)
s.add("hm_sheen", "ellipse", "hamster_fx", cx=236, cy=292, rx=22, ry=14, fill=g, transform="rotate(-28 236 292)", anim="glaze")
# lit rim of the left ear
ex, ey, er = s.params["ears"][0]
pts = [(ex + (er - 2.2) * math.cos(math.radians(a)), ey + (er - 2.2) * math.sin(math.radians(a))) for a in range(150, 262, 14)]
s.add("hm_ear0_lit", "path", "hamster_fx", d=pressure_d(pts, 1.6, rng, taper=0.35), fill="#FFF1DA", fill_opacity=0.85, anim="draw")
# fur wisps escaping the silhouette (top of head, cheeks)
k = 0
for a in [-118, -104, -92, -80, -66, 186, 194, 201, -14, -6, 2]:
    if -60 < a < -10 and a not in (-14,):
        pass
    t = math.radians(a)
    bx, by = ell(a, 0.985)
    nx, ny = math.cos(t), math.sin(t)
    d = flow(bx, by)
    vx, vy = nx * 0.75 + d[0] * 0.25, ny * 0.75 + d[1] * 0.25
    vl = math.hypot(vx, vy)
    vx, vy = vx / vl, vy / vl
    ln = rng.uniform(2.6, 4.2)
    tip = (bx + vx * ln, by + vy * ln)
    if tip[1] > 353:
        continue
    q = ((bx + tip[0]) / 2 - vy * 0.7, (by + tip[1]) / 2 + vx * 0.7)
    s.add(f"hm_wisp{k:02d}", "path", "hamster", d=f"M{f(bx - vx * 1.5)} {f(by - vy * 1.5)}Q{f(q[0])} {f(q[1])} {f(tip[0])} {f(tip[1])}",
          fill="none", stroke=INK, stroke_width=1.1, stroke_opacity=0.85, stroke_linecap="round", anim="draw")
    k += 1
# third fur layer: finer, shorter strands everywhere in the peach area + white cheeks
avoid = R["avoid"].buffer(1.2)
def place(prefix, region, count, cols, op_rng, w_rng, ln_rng):
    n = 0
    minx, miny, maxx, maxy = region.bounds
    tries = 0
    while n < count and tries < 60000:
        tries += 1
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        d = flow(x, y)
        ln = rng.uniform(*ln_rng)
        x2, y2 = x + d[0] * ln, y + d[1] * ln
        line = LineString([(x, y), (x2, y2)])
        if not region.contains(line) or line.intersects(avoid):
            continue
        b = rng.uniform(-0.5, 0.5)
        q = ((x + x2) / 2 - d[1] * b, (y + y2) / 2 + d[0] * b)
        s.add(f"{prefix}{n:03d}", "path", "hamster_fx", d=f"M{f(x)} {f(y)}Q{f(q[0])} {f(q[1])} {f(x2)} {f(y2)}",
              fill="none", stroke=rng.choice(cols), stroke_width=round(rng.uniform(*w_rng), 2),
              stroke_opacity=round(rng.uniform(*op_rng), 2), stroke_linecap="round", anim="pop")
        n += 1
    return n
n1 = place("fur_fine", R["peach"].buffer(-2.4), 70, ["#E7AE70", "#FBE0B8"], (0.16, 0.34), (0.4, 0.62), (1.8, 3.4))
n2 = place("fur_wfine", R["muzzle"].buffer(-2.4), 28, ["#E2DAD7", "#FFFFFF"], (0.3, 0.55), (0.4, 0.6), (1.8, 3.2))
print("wisps", k, "fine", n1, n2)
s.commit(zooms=[(176, 250, 160, 112)])
