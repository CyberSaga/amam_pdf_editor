"""Batch 14 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import Polygon
from studio import Studio
from geo import body_outline_pts, poly_d
from brush import offset_ring, runs, chop, taper2_d

s = Studio.open()
s.begin(5, "細化光影：塑膠本體的倒角與光澤",
        "墨線讓形體清楚了，但紫色本體內部像一塊平板：邊緣沒有倒角厚度，左上沒有參考圖那道白色反光弧，右下也沒有背光的轉折。",
        "沿本體內側 6 單位的偏移線：受光側（左、上、切角）用白色分段筆觸，靠左上角最亮；背光側（右、下）用深紫分段筆觸；底邊加一道卡片反射上來的淡紫反光；左上角補一道明亮的高光弧；大面積上蓋一層斜向的淡光澤與右下的暗部。",
        tempo="fast")
P = s.params["P"]
x0, y0, x1, y1, r, ch, rch = P["body"]
body = Polygon(body_outline_pts(x0, y0, x1, y1, r, ch, rch, seg=10))
rng = random.Random(1401)
ring = offset_ring(list(body.exterior.coords), 6.0, step=2.0)
SH_L, SH_R = 189, 323

def lit(x, y):
    left = x < x0 + 14 and y < y1 - r - 4
    top = y < y0 + 14 and (x < SH_L or x > SH_R)
    cham = x > x1 - ch - 8 and y < y0 + ch + 8 and x < x1 - 9
    return left or top or cham

def shade(x, y):
    right = x > x1 - 14 and y > y0 + ch + 2
    bottom = y > y1 - 14 and x > x0 + r - 4
    return right or bottom

n = 0
for run in runs(ring, lit):
    for seg in chop(run, 9, 2, rng):
        if len(seg) < 2:
            continue
        mx = sum(p[0] for p in seg) / len(seg)
        my = sum(p[1] for p in seg) / len(seg)
        dist = math.hypot(mx - x0, my - y0)
        op = max(0.18, 0.78 - dist / 330) * rng.uniform(0.8, 1.1)
        s.add(f"bfx_lit{n:02d}", "path", "body_fx", d=taper2_d(seg, rng.uniform(2.0, 2.8)),
              fill="#FFFFFF", fill_opacity=round(op, 3), anim="pop")
        n += 1
m = 0
for run in runs(ring, shade):
    for seg in chop(run, 9, 2, rng):
        if len(seg) < 2:
            continue
        mx = sum(p[0] for p in seg) / len(seg)
        my = sum(p[1] for p in seg) / len(seg)
        dist = math.hypot(mx - x1, my - y1)
        op = max(0.16, 0.46 - dist / 700) * rng.uniform(0.8, 1.1)
        s.add(f"bfx_shd{m:02d}", "path", "body_fx", d=taper2_d(seg, rng.uniform(2.6, 3.4)),
              fill="#4A3F98", fill_opacity=round(op, 3), anim="pop")
        m += 1
# reflected light just inside the bottom ink line
ring3 = offset_ring(list(body.exterior.coords), 3.4, step=2.0)
k = 0
for run in runs(ring3, lambda x, y: y > y1 - 6 and x0 + r < x < x1 - r):
    for seg in chop(run, 12, 2, rng):
        if len(seg) < 2:
            continue
        s.add(f"bfx_bounce{k:02d}", "path", "body_fx", d=taper2_d(seg, 1.4), fill="#D9D4FA",
              fill_opacity=round(rng.uniform(0.35, 0.55), 3), anim="pop")
        k += 1
# bright gloss arc at the top-left corner (as in the reference)
corner = [p for p in ring if p[0] < x0 + 44 and p[1] < y0 + 52]
corner.sort(key=lambda p: math.atan2(p[1] - (y0 + r + 4), p[0] - (x0 + r + 4)))
s.add("bfx_gloss_arc", "path", "body_fx", d=taper2_d(corner, 3.4, 0.4), fill="#FFFFFF",
      fill_opacity=0.9, anim="draw")
# broad diagonal sheen + lower-right core shadow (clipped to the body)
sheen = Polygon([(x0 - 5, y0 + 30), (x0 + 30, y0 - 5), (x0 + 112, y0 - 5), (x0 - 5, y0 + 175)]).intersection(body.buffer(-2.5))
s.add("bfx_sheen", "path", "body_fx", d=poly_d(sheen), fill="#FFFFFF", fill_opacity=0.075, anim="glaze")
sheen2 = Polygon([(x0 - 5, y0 + 56), (x0 + 56, y0 - 5), (x0 + 82, y0 - 5), (x0 - 5, y0 + 116)]).intersection(body.buffer(-2.5))
s.add("bfx_sheen2", "path", "body_fx", d=poly_d(sheen2), fill="#FFFFFF", fill_opacity=0.06, anim="glaze")
core = Polygon([(x1 + 5, y0 + 150), (x1 + 5, y1 + 5), (x0 + 150, y1 + 5)]).intersection(body.buffer(-2.5))
s.add("bfx_core", "path", "body_fx", d=poly_d(core), fill="#3B3282", fill_opacity=0.09, anim="glaze")
s.params["body_poly"] = list(body.exterior.coords)
print("lit", n, "shade", m, "bounce", k)
s.commit(zooms=[(120, 100, 150, 150), (280, 280, 110, 125)])
