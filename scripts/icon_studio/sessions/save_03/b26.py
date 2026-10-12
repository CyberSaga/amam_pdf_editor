"""Batch 26 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import Point, LineString, Polygon
from studio import Studio
from geo import body_outline_pts, f, poly_d, rrect_pts
from brush import pressure_d
from hamster_geo import regions, flow

s = Studio.open()
s.begin(5, "觀察修正：拿掉輪廓上的短刺；墨線反光與質感補密",
        "越出輪廓的細絨毛用了墨色，又幾乎垂直於輪廓，看起來像縫線或刻度，破壞了參考圖乾淨的圓頭輪廓。擋板下緣沒有反映紫色本體；墨線本身是死黑，沒有受光。大面積的顆粒與紙紋在中距離仍偏稀。",
        "擦掉這些短刺；擋板下緣加一道紫色反射；在左上受光處的墨線上點幾道白色小反光（本體角、擋板、標籤窗、槽孔、倉鼠頭頂）；本體顆粒、卡片紙紋、耳朵與白毛各補一層密度。",
        tempo="rapid")
s.look((196, 268, 120, 30), "輪廓短刺像縫線")
for eid in sorted(e for e in s.elements if e.startswith("hm_wisp")):
    s.rm(eid, note="拿掉輪廓短刺")
P = s.params["P"]
rng = random.Random(2601)
sx0, sy0, sx1, sy1, sr = P["shutter"]
g = s.gradient("g_sh_reflect", "linear", [(0, "#8E7FD6", 0), (1, "#8E7FD6", 0.32)], gradientUnits="userSpaceOnUse",
               x1=0, y1=sy1 - 16, x2=0, y2=sy1 - 2.5)
sh = Polygon(s.params["shutter_poly"]).buffer(-2.4)
band = sh.intersection(Polygon([(sx0, sy1 - 16), (sx1, sy1 - 16), (sx1, sy1), (sx0, sy1)]))
s.add("sh_reflect", "path", "shutter", d=poly_d(band), fill=g, anim="glaze")
# glints on the ink, where the outline faces the light
x0, y0, x1, y1, r = P["body"][:5]
glints = [
    [(x0 + 0.2, y0 + r + 10), (x0 + 1.5, y0 + r - 3), (x0 + 5.5, y0 + 5.5)],
    [(x0 + r - 2, y0 + 0.1), (x0 + r + 10, y0 - 0.4), (x0 + r + 20, y0 - 0.2)],
    [(sx0 - 0.3, sy0 + 14), (sx0 - 0.3, sy0 + 26), (sx0 - 0.2, sy0 + 36)],
]
bx0, by0, bx1, by1, br = P["label"]
glints.append([(bx0 + 0.2, by0 + br + 6), (bx0 + 1.4, by0 + br - 3), (bx0 + br - 1, by0 + 1.2), (bx0 + br + 8, by0 + 0.1)])
lx0, ly0, lx1, ly1, lr = P["slot"]
glints.append([(lx0 + 0.3, ly0 + lr + 4), (lx0 + 1.3, ly0 + lr - 2.4), (lx0 + lr, ly0 + 0.4)])
cx, cy, rx, ry = s.params["head"]
glints.append([(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in (-128, -118, -108, -98)])
for i, pts in enumerate(glints):
    s.add(f"glint_ink{i}", "path", "glint", d=pressure_d(pts, 1.25, rng, taper=0.4, w_end=0.15), fill="#FFFFFF",
          fill_opacity=0.75, anim="draw")
# density top-up: body grain
body = Polygon(s.params["body_poly"]).buffer(-4.2)
vis = body.difference(Polygon(s.params["shutter_poly"]).buffer(3.0)).difference(Polygon(rrect_pts(*P["label"], seg=8)).buffer(3.0))
for h in s.params["holes"].values():
    vis = vis.difference(Polygon(rrect_pts(*h, 2.2, seg=4)).buffer(2.0))
minx, miny, maxx, maxy = vis.bounds
n = 0
while n < 92:
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    if not vis.contains(Point(x, y)):
        continue
    lightness = 1 - ((x - x0) / (x1 - x0) * 0.55 + (y - y0) / (y1 - y0) * 0.45)
    col, op = ("#C9C0FA", rng.uniform(0.16, 0.3)) if rng.random() < lightness else ("#5A4FAE", rng.uniform(0.1, 0.22))
    s.add(f"btx_h{n:03d}", "circle", "body_fx", cx=round(x, 2), cy=round(y, 2), r=round(rng.uniform(0.3, 0.7), 2),
          fill=col, fill_opacity=round(op, 3), anim="pop")
    n += 1
# card grain
cx0, cy0, cx1, cy1, cr = P["card"]
card = Polygon(rrect_pts(cx0, cy0, cx1, cy1, cr, seg=10)).buffer(-5)
ch, rch = P["body"][5], P["body"][6]
floppy = Polygon(body_outline_pts(x0 - 4, y0 - 4, x1 + 18, y1 + 22, r, ch, rch, seg=6))
cvis = card.difference(floppy)
minx, miny, maxx, maxy = cvis.bounds
m = 0
while m < 62:
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    if not cvis.contains(Point(x, y)):
        continue
    s.add(f"ctx_h{m:03d}", "circle", "card", cx=round(x, 2), cy=round(y, 2), r=round(rng.uniform(0.3, 0.65), 2),
          fill=rng.choice(["#D6D2E8", "#CFCBE3", "#E0DDEE"]), fill_opacity=round(rng.uniform(0.22, 0.45), 2), anim="pop")
    m += 1
# ear fur + white fur top-up
R = regions(s)
head_poly = R["head"]
e = 0
for i, (ex, ey, er) in enumerate(s.params["ears"]):
    a = rng.uniform(0, 10)
    while a < 360:
        a += rng.uniform(15, 22)
        t = math.radians(a)
        bx, by = ex + (er - 4.2) * math.cos(t), ey + (er - 4.2) * math.sin(t)
        tip = (ex + (er - 7.2) * math.cos(t - 0.1), ey + (er - 7.2) * math.sin(t - 0.1))
        line = LineString([(bx, by), tip])
        if line.intersects(head_poly.buffer(1.8)):
            continue
        s.add(f"fur_ear2_{e:02d}", "path", "hamster_fx", d=f"M{f(bx)} {f(by)}L{f(tip[0])} {f(tip[1])}", fill="none",
              stroke="#F9DDB4", stroke_width=round(rng.uniform(0.55, 0.8), 2), stroke_opacity=round(rng.uniform(0.45, 0.7), 2),
              stroke_linecap="round", anim="pop")
        e += 1
w = 0
avoid = R["avoid"].buffer(1.2)
white = R["muzzle"].buffer(-2.4)
minx, miny, maxx, maxy = white.bounds
while w < 30:
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    d = flow(x, y)
    ln = rng.uniform(2.0, 3.6)
    line = LineString([(x, y), (x + d[0] * ln, y + d[1] * ln)])
    if not white.contains(line) or line.intersects(avoid):
        continue
    s.add(f"fur_w3_{w:02d}", "path", "hamster_fx", d=f"M{f(x)} {f(y)}L{f(x + d[0] * ln)} {f(y + d[1] * ln)}", fill="none",
          stroke="#DCD3D0", stroke_width=round(rng.uniform(0.4, 0.6), 2), stroke_opacity=round(rng.uniform(0.25, 0.45), 2),
          stroke_linecap="round", anim="pop")
    w += 1
print("grain", n, "card", m, "ear", e, "white", w)
s.commit(zooms=[(110, 90, 300, 330), (186, 104, 140, 112)])
