"""Batch 16 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import Polygon, LineString, box
from studio import Studio
from geo import rrect_pts, poly_d, pts_d, f
from brush import offset_ring, runs, pressure_d

s = Studio.open()
s.begin(5, "細化結構與質感：金屬擋板與槽孔裡的磁碟",
        "擋板只有一層上下漸層，看起來像白色塑膠片而不是金屬；槽孔是一塊深藍，缺乏「洞裡有東西」的深度。順帶發現：本體右下暗部的斜邊仍有一道淡淡的界線。",
        "擋板：左緣受光、下緣背光的折邊；一道垂直的柔和鏡面反光；沿滑動方向的水平髮絲紋（避開槽孔）。槽孔內畫出磁碟面：以碟心為圓心的同心磁軌弧線與一道斜向反光。暗部多邊形往左上延伸，讓漸層在邊界前就歸零。",
        tempo="fast")
P = s.params["P"]
x0, y0, x1, y1, r, ch, rch = P["body"]
core = Polygon([(x1 + 5, y0 + 40), (x1 + 5, y1 + 5), (x0 + 40, y1 + 5)]).intersection(Polygon(s.params["body_poly"]).buffer(-2.5))
s.mod("bfx_core", note="暗部邊界延伸，消除斜線", d=poly_d(core))
sx0, sy0, sx1, sy1, sr = P["shutter"]
lx0, ly0, lx1, ly1, lr = P["slot"]
# shutter region polygon (top edge is the body's top edge)
sh_pts = [(sx0, sy0)] + [(sx0 + sr - sr * math.cos(math.radians(a)), sy1 - sr + sr * math.sin(math.radians(a))) for a in range(0, 91, 10)] \
         + [(sx1 - sr + sr * math.cos(math.radians(a)), sy1 - sr + sr * math.sin(math.radians(a))) for a in range(90, -1, -10)] + [(sx1, sy0)]
shutter = Polygon(sh_pts)
slot = Polygon(rrect_pts(lx0, ly0, lx1, ly1, lr, seg=8))
s.params["shutter_poly"] = list(shutter.exterior.coords)
rng = random.Random(1601)
# --- folded edges
ring = offset_ring(list(shutter.exterior.coords), 4.6, step=1.6)
left = runs(ring, lambda x, y: x < sx0 + 8 and y > sy0 + 6)
bottom = runs(ring, lambda x, y: y > sy1 - 8 and x > sx0 + 4)
right = runs(ring, lambda x, y: x > sx1 - 8 and y > sy0 + 6 and y < sy1 - 6)
for k, run in enumerate(sorted(left, key=len, reverse=True)[:1]):
    s.add("shfx_lit_left", "path", "shutter", d=pressure_d(run, 2.2, rng, taper=0.25), fill="#FFFFFF", fill_opacity=0.9, anim="draw")
for k, run in enumerate(sorted(bottom, key=len, reverse=True)[:1]):
    s.add("shfx_shade_bottom", "path", "shutter", d=pressure_d(run, 2.6, rng, taper=0.2), fill="#9C9DB4", fill_opacity=0.55, anim="draw")
for k, run in enumerate(sorted(right, key=len, reverse=True)[:1]):
    s.add("shfx_shade_right", "path", "shutter", d=pressure_d(run, 2.0, rng, taper=0.3), fill="#A9AABF", fill_opacity=0.45, anim="draw")
# --- brushed hairlines (horizontal, along the sliding direction), clipped around the slot
inner = shutter.buffer(-3.2).difference(slot.buffer(2.6))
nlines = 0
y = sy0 + 4.0
while y < sy1 - 3:
    y += rng.uniform(0.45, 1.05)
    xa = rng.uniform(sx0, sx0 + 40)
    xb = rng.uniform(sx1 - 40, sx1)
    seg = LineString([(xa, y), (xb, y + rng.uniform(-0.25, 0.25))]).intersection(inner)
    for g in getattr(seg, "geoms", [seg]):
        if g.is_empty or g.length < 6:
            continue
        (ax, ay), (bx, by) = g.coords[0], g.coords[-1]
        light = rng.random() < 0.55
        s.add(f"shtx_{nlines:03d}", "path", "shutter", d=f"M{f(ax)} {f(ay)}L{f(bx)} {f(by)}", fill="none",
              stroke="#FFFFFF" if light else "#9A9CB2", stroke_width=round(rng.uniform(0.35, 0.75), 2),
              stroke_opacity=round(rng.uniform(0.18, 0.42) if light else rng.uniform(0.07, 0.16), 3),
              stroke_linecap="round", anim="pop")
        nlines += 1
# --- specular band (vertical, soft) + thin bright core
spec_x = sx0 + 22
band = box(spec_x - 9, sy0 + 2.5, spec_x + 9, sy1 - 3).intersection(shutter.buffer(-2.5))
g = s.gradient("g_shutter_spec", "linear", [(0, "#FFFFFF", 0), (0.5, "#FFFFFF", 0.75), (1, "#FFFFFF", 0)],
               gradientUnits="userSpaceOnUse", x1=spec_x - 9, y1=0, x2=spec_x + 9, y2=0)
s.add("shfx_spec_band", "path", "shutter", d=poly_d(band), fill=g, anim="glaze")
s.add("shfx_spec_line", "path", "shutter", d=pressure_d([(spec_x - 1, sy0 + 6 + i * (sy1 - sy0 - 14) / 8) for i in range(9)], 1.3, rng, taper=0.3),
      fill="#FFFFFF", fill_opacity=0.9, anim="draw")
# --- disk visible through the slot: concentric tracks around an imagined hub below
hub = (256.0, 262.0)
inside = slot.buffer(-1.6)
tracks = 0
rad = math.hypot(lx0 - hub[0], ly1 - hub[1]) - 2
while rad < math.hypot(lx1 - hub[0], ly0 - hub[1]) + 2:
    rad += rng.uniform(1.7, 2.6)
    arc = LineString([(hub[0] + rad * math.cos(math.radians(a / 4)), hub[1] + rad * math.sin(math.radians(a / 4)))
                      for a in range(-4 * 100, -4 * 30)]).intersection(inside)
    for gg in getattr(arc, "geoms", [arc]):
        if gg.is_empty or gg.length < 4:
            continue
        cs = list(gg.coords)
        cs = cs[:: max(1, len(cs) // 6)] + [cs[-1]]
        dark = tracks % 2 == 0
        s.add(f"disk_trk{tracks:02d}", "path", "shutter", d=pts_d(cs), fill="none",
              stroke="#262948" if dark else "#7C83B8", stroke_width=0.6,
              stroke_opacity=0.5 if dark else 0.32, anim="pop")
        tracks += 1
disk_sheen = Polygon([(lx0, ly0 + 30), (lx1, ly0 + 12), (lx1, ly0 + 24), (lx0, ly0 + 42)]).intersection(inside)
g2 = s.gradient("g_disk_sheen", "linear", [(0, "#C9CEF5", 0), (0.5, "#C9CEF5", 0.3), (1, "#C9CEF5", 0)],
                gradientUnits="userSpaceOnUse", x1=0, y1=ly0 + 14, x2=0, y2=ly0 + 40)
s.add("disk_sheen", "path", "shutter", d=poly_d(disk_sheen), fill=g2, anim="glaze")
for eid in ("slot_inshadow", "slot_rimlight"):
    s.restack(eid, s.zc + 1)
    s.zc += 1
print("hairlines", nlines, "tracks", tracks)
s.commit(zooms=[(186, 104, 140, 112), (266, 128, 40, 66)])
