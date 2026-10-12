"""Batch 12 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
from studio import Studio
from geo import smooth_d, taper_stroke_d, f

INK = "#1E1D38"
s = Studio.open()
s.begin(5, "細化結構：倉鼠線稿",
        "外框上墨後，倉鼠反而變成最模糊的地方，視覺焦點跑掉了。參考圖倉鼠輪廓同樣是深色墨線，但比外框細一級。",
        "頭輪廓 3.4、耳朵 3.2（只畫頭外側的弧，端點接到頭線上）、內耳一道摺線；嘴巴 ω 與人中；鬍鬚改成由粗到細的錐形筆觸，從臉頰內穿出輪廓。",
        tempo="normal")
cx, cy, rx, ry = s.params["head"]
head_pts = s.params["head_pts"]
s.add("ink_head", "path", "hamster", d=smooth_d(head_pts), fill="none", stroke=INK, stroke_width=3.4,
      stroke_linecap="round", stroke_linejoin="round", anim="draw")

def in_head(x, y):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 < 1.0

for i, (ex, ey, er) in enumerate(s.params["ears"]):
    a_start, a_end = s.params["ear_arcs"][i]
    sweep = (a_end - a_start) % 360
    p0 = (ex + er * math.cos(math.radians(a_start - 3)), ey + er * math.sin(math.radians(a_start - 3)))
    p1 = (ex + er * math.cos(math.radians(a_end + 3)), ey + er * math.sin(math.radians(a_end + 3)))
    large = 1 if sweep + 6 > 180 else 0
    s.add(f"ink_ear{i}", "path", "hamster", z=s.elements[f"hm_ear{i}_inner"]["z"] + 0.1,
          d=f"M{f(p0[0])} {f(p0[1])}A{f(er)} {f(er)} 0 {large} 1 {f(p1[0])} {f(p1[1])}",
          fill="none", stroke=INK, stroke_width=3.2, stroke_linecap="round", anim="draw")
# inner-ear fold: short curve on the inner-lower side of each inner ear
folds = [[(219.5, 277.5), (223.5, 281.5), (224.6, 287.5)], [(292.5, 277.5), (288.5, 281.5), (287.4, 287.5)]]
for i, pts in enumerate(folds):
    s.add(f"ink_earfold{i}", "path", "hamster", z=s.elements[f"hm_ear{i}_inner"]["z"] + 0.05,
          d=smooth_d(pts), fill="none", stroke="#6A4048", stroke_width=1.5, stroke_opacity=0.75,
          stroke_linecap="round", anim="draw")
# mouth + philtrum
s.add("ink_philtrum", "path", "hamster", d="M256 336.4L256 338.8", fill="none", stroke=INK,
      stroke_width=2.1, stroke_linecap="round", anim="draw")
s.add("ink_mouth", "path", "hamster",
      d="M243.6 340.6Q247.2 346.2 251.8 343.8Q254.6 342.2 256 338.8Q257.4 342.2 260.2 343.8Q264.8 346.2 268.4 340.6",
      fill="none", stroke=INK, stroke_width=2.4, stroke_linecap="round", stroke_linejoin="round", anim="draw")
# whiskers: tapered, rooted inside the cheek, crossing the outline
wh = [((209, 330.5), (198, 328.4), (187.5, 326.8)), ((209.5, 336.2), (198, 336.4), (186.5, 337.4)),
      ((209.5, 341.8), (199, 344.2), (189, 348.2))]
s.params["whiskers"] = []
for side in (0, 1):
    for j, (a, b, c) in enumerate(wh):
        pts = [a, b, c] if side == 0 else [(512 - p[0], p[1]) for p in (a, b, c)]
        dense = []
        for k in range(7):
            t = k / 6
            # quadratic through a, b, c
            x = (1 - t) ** 2 * pts[0][0] + 2 * (1 - t) * t * (2 * pts[1][0] - 0.5 * (pts[0][0] + pts[2][0])) + t * t * pts[2][0]
            y = (1 - t) ** 2 * pts[0][1] + 2 * (1 - t) * t * (2 * pts[1][1] - 0.5 * (pts[0][1] + pts[2][1])) + t * t * pts[2][1]
            dense.append((x, y))
        s.params["whiskers"].append(dense)
        s.add(f"ink_whisker{side}{j}", "path", "hamster", d=taper_stroke_d(dense, 2.0, 0.45),
              fill=INK, anim="fill")
s.commit(zooms=[(176, 250, 160, 112)])
