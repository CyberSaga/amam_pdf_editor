"""Batch 21 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import Point, LineString, Polygon
from shapely.affinity import translate
from studio import Studio
from geo import rrect_pts, poly_d, f
from brush import offset_ring, runs, pressure_d

s = Studio.open()
s.begin(5, "細化空間：標籤紙的紙纖維與倉鼠落影",
        "倉鼠和後面的白紙之間沒有空間關係，倉鼠像貼在紙上的貼紙；標籤紙本身也太乾淨、看起來像塑膠。",
        "光從左上來，倉鼠的頭與耳朵在紙上往右下投出很淡的柔影（兩層）；可見的紙面撒上細短的紙纖維與極小的纖維點；標籤窗右緣內側加一道受光的唇邊。",
        tempo="rapid")
P = s.params["P"]
bx0, by0, bx1, by1, br = P["label"]
label = Polygon(rrect_pts(bx0, by0, bx1, by1, br, seg=8))
cx, cy, rx, ry = s.params["head"]
head = Polygon([(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in range(0, 360, 4)])
ears = [Point(ex, ey).buffer(er, 24) for ex, ey, er in s.params["ears"]]
ham = head.union(ears[0]).union(ears[1])
inside = label.buffer(-2.6)
for i, (dx, dy, op) in enumerate([(3.0, 2.6, 0.1), (5.5, 4.8, 0.05)]):
    sh = translate(ham, dx, dy).intersection(inside).difference(ham)
    s.add(f"lb_hamshadow{i}", "path", "label", d=poly_d(sh), fill="#6B5F8E", fill_opacity=op, anim="glaze")
paper = inside.difference(ham.buffer(1.5))
rng = random.Random(2101)
minx, miny, maxx, maxy = paper.bounds
n = 0
tries = 0
while n < 84 and tries < 20000:
    tries += 1
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    a = rng.uniform(0, math.pi)
    ln = rng.uniform(2.2, 5.5)
    bend = rng.uniform(-1.2, 1.2)
    x2, y2 = x + math.cos(a) * ln, y + math.sin(a) * ln
    qx, qy = (x + x2) / 2 - math.sin(a) * bend, (y + y2) / 2 + math.cos(a) * bend
    if not paper.contains(LineString([(x, y), (x2, y2)])):
        continue
    s.add(f"lbtx_fib{n:03d}", "path", "label", d=f"M{f(x)} {f(y)}Q{f(qx)} {f(qy)} {f(x2)} {f(y2)}", fill="none",
          stroke=rng.choice(["#CFCDE0", "#D8D6E6", "#E2E0EC"]), stroke_width=round(rng.uniform(0.35, 0.6), 2),
          stroke_opacity=round(rng.uniform(0.35, 0.6), 2), stroke_linecap="round", anim="pop")
    n += 1
k = 0
while k < 26:
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    if not paper.contains(Point(x, y)):
        continue
    s.add(f"lbtx_dot{k:02d}", "circle", "label", cx=round(x, 2), cy=round(y, 2), r=round(rng.uniform(0.3, 0.6), 2),
          fill="#C9C6DB", fill_opacity=round(rng.uniform(0.35, 0.6), 2), anim="pop")
    k += 1
ring = offset_ring(rrect_pts(bx0, by0, bx1, by1, br, seg=8), 3.4, step=1.6)
right = runs(ring, lambda x, y: x > bx1 - 6 and by0 + 12 < y < by1 - 10)
right.sort(key=len, reverse=True)
s.add("lb_lip_right", "path", "label", d=pressure_d(right[0], 1.6, rng, taper=0.3), fill="#FFFFFF", fill_opacity=0.95, anim="draw")
print("fibers", n, "dots", k)
s.commit(zooms=[(170, 236, 172, 130)])
