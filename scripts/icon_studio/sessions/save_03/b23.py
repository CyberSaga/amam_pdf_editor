"""Batch 23 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import Point, Polygon, LineString
from studio import Studio
from geo import rrect_pts, f

s = Studio.open()
s.begin(5, "細化質感：塑膠表面的霧面顆粒與使用痕跡",
        "紫色本體在放大時是完全光滑的數位漸層，和已經有質感的金屬擋板、毛髮、紙張不在同一個精細度上。",
        "在本體可見區域撒細小顆粒：受光的左上偏亮色、背光的右下偏暗色，不透明度很低；再加十幾道極淡的細刮痕，讓塑膠有被使用過的真實感。",
        tempo="rapid")
P = s.params["P"]
body = Polygon(s.params["body_poly"]).buffer(-4.2)
sh = Polygon(s.params["shutter_poly"]).buffer(3.0)
lab = Polygon(rrect_pts(*P["label"], seg=8)).buffer(3.0)
holes = [Polygon(rrect_pts(*h, 2.2, seg=4)).buffer(2.0) for h in s.params["holes"].values()]
vis = body.difference(sh).difference(lab)
for h in holes:
    vis = vis.difference(h)
rng = random.Random(2301)
x0, y0, x1, y1 = P["body"][:4]
minx, miny, maxx, maxy = vis.bounds
n = 0
while n < 262:
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    if not vis.contains(Point(x, y)):
        continue
    lightness = 1 - ((x - x0) / (x1 - x0) * 0.55 + (y - y0) / (y1 - y0) * 0.45)  # 1 at top-left
    if rng.random() < lightness:
        col, op = "#C9C0FA", rng.uniform(0.18, 0.34)
    else:
        col, op = "#5A4FAE", rng.uniform(0.12, 0.26)
    s.add(f"btx_g{n:03d}", "circle", "body_fx", cx=round(x, 2), cy=round(y, 2), r=round(rng.uniform(0.32, 0.78), 2),
          fill=col, fill_opacity=round(op, 3), anim="pop")
    n += 1
m = 0
while m < 14:
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    a = math.radians(rng.choice([rng.uniform(-35, -10), rng.uniform(10, 40)]))
    ln = rng.uniform(5, 13)
    x2, y2 = x + math.cos(a) * ln, y + math.sin(a) * ln
    qx, qy = (x + x2) / 2 + rng.uniform(-0.8, 0.8), (y + y2) / 2 + rng.uniform(-0.8, 0.8)
    if not vis.contains(LineString([(x, y), (x2, y2)])):
        continue
    s.add(f"btx_scuff{m:02d}", "path", "body_fx", d=f"M{f(x)} {f(y)}Q{f(qx)} {f(qy)} {f(x2)} {f(y2)}", fill="none",
          stroke="#E4DFFF", stroke_width=round(rng.uniform(0.3, 0.55), 2), stroke_opacity=round(rng.uniform(0.14, 0.24), 2),
          stroke_linecap="round", anim="draw")
    m += 1
s.commit(zooms=[(128, 200, 120, 120)])
