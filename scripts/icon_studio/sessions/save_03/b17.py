"""Batch 17 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from studio import Studio
from geo import smooth_d, f
from brush import pressure_d

s = Studio.open()
s.begin(5, "細化焦點：眼睛、鼻子、腮紅、內耳",
        "整張圖最精緻的地方現在是擋板，焦點跑到了金屬上；倉鼠的眼睛還是兩個實心深色橢圓，沒有神采。另外槽孔磁軌的亮線對比太強，像條紋。",
        "眼睛做成有深度的玻璃珠：上深下帶藍綠的漸層、下緣虹膜反光、左上主高光（與全圖光源一致）、右下小反光；鼻子加漸層、描邊與高光；腮紅改成柔邊漸層加三筆斜線；內耳加漸層與細血管；鬍鬚根部加毛孔點。磁軌亮線降低不透明度。",
        tempo="normal")
for eid, el in list(s.elements.items()):
    if eid.startswith("disk_trk") and el["attrs"].get("stroke") == "#7C83B8":
        s.mod(eid, stroke_opacity=0.2)
rng = random.Random(1701)
for i, (ex, ey, erx, ery) in enumerate(s.params["eyes"]):
    g = s.gradient(f"g_eye{i}", "linear", [(0, "#12162A", 1), (0.6, "#1F2A44", 1), (1, "#2F5368", 1)],
                   gradientUnits="userSpaceOnUse", x1=0, y1=ey - ery, x2=0, y2=ey + ery)
    s.mod(f"hm_eye{i}_base", note="眼睛：實心 → 有深度的漸層", fill=g)
    s.add(f"hm_eye{i}_iris", "path", "hamster_fx",
          d=f"M{f(ex - erx * 0.78)} {f(ey + ery * 0.18)}Q{f(ex)} {f(ey + ery * 1.02)} {f(ex + erx * 0.78)} {f(ey + ery * 0.18)}"
            f"Q{f(ex)} {f(ey + ery * 0.62)} {f(ex - erx * 0.78)} {f(ey + ery * 0.18)}Z",
          fill="#5FA1B8", fill_opacity=0.55, anim="fill")
    s.add(f"hm_eye{i}_rim", "ellipse", "hamster_fx", cx=ex, cy=ey, rx=erx, ry=ery, fill="none",
          stroke="#0E1122", stroke_width=1.0, stroke_opacity=0.8, anim="draw")
    s.add(f"hm_eye{i}_hl", "ellipse", "hamster_fx", cx=ex - erx * 0.32, cy=ey - ery * 0.38, rx=erx * 0.42, ry=ery * 0.36,
          fill="#FFFFFF", anim="pop", transform=f"rotate(-18 {f(ex - erx * 0.32)} {f(ey - ery * 0.38)})")
    s.add(f"hm_eye{i}_hl2", "circle", "hamster_fx", cx=ex + erx * 0.38, cy=ey + ery * 0.3, r=erx * 0.17,
          fill="#FFFFFF", fill_opacity=0.85, anim="pop")
    s.add(f"hm_eye{i}_spark", "circle", "hamster_fx", cx=ex + erx * 0.12, cy=ey - ery * 0.62, r=erx * 0.1,
          fill="#FFFFFF", fill_opacity=0.7, anim="pop")
# nose
gn = s.gradient("g_nose", "linear", [(0, "#F59AA3", 1), (1, "#D85466", 1)], gradientUnits="userSpaceOnUse",
                x1=0, y1=329.6, x2=0, y2=336.6)
s.mod("hm_nose_base", fill=gn, stroke="#9E3A4C", stroke_width=0.9, stroke_linejoin="round")
s.add("hm_nose_hl", "ellipse", "hamster_fx", cx=254.2, cy=331.4, rx=1.7, ry=0.9, fill="#FFFFFF", fill_opacity=0.85,
      transform="rotate(-8 254.2 331.4)", anim="pop")
s.add("hm_nose_shadow", "path", "hamster_fx", d="M250.8 337.4Q256 340.6 261.2 337.4Q256 339.2 250.8 337.4Z",
      fill="#B79A9C", fill_opacity=0.35, anim="glaze")
# blush: soft gradient + three hatch strokes
for i, (bx, by) in enumerate([(224, 333.5), (288, 333.5)]):
    gb = s.gradient(f"g_blush{i}", "radial", [(0, "#F68E9C", 0.55), (0.6, "#F7A3AE", 0.3), (1, "#F7A3AE", 0)],
                    gradientUnits="userSpaceOnUse", cx=bx, cy=by, r=11.5)
    s.mod(f"hm_blush{i}_base", note="腮紅改柔邊", fill=gb, fill_opacity=1, rx=11.5, ry=7)
    for k in range(3):
        hx = bx - 4.5 + k * 4.2
        pts = [(hx + 1.6, by - 2.6), (hx + 0.2, by), (hx - 1.4, by + 2.4)]
        s.add(f"hm_blush{i}_h{k}", "path", "hamster_fx", d=pressure_d(pts, 1.1, rng, taper=0.45, w_end=0.2),
              fill="#E46F83", fill_opacity=0.5, anim="draw")
# inner ears: gradient + veins
for i, (ix, iy, irx, iry) in enumerate(s.params["ear_inner"]):
    gi = s.gradient(f"g_ear_inner{i}", "radial", [(0, "#F8C6BE", 1), (0.7, "#F2AAA3", 1), (1, "#E58D8C", 1)],
                    gradientUnits="userSpaceOnUse", cx=ix - (2 if i == 0 else -2), cy=iy - 3, r=irx * 1.2)
    s.mod(f"hm_ear{i}_inner", fill=gi)
    sgn = 1 if i == 0 else -1
    for k, (a0, ln) in enumerate([(-120, 6.5), (-150, 5.5), (-95, 5)]):
        a = math.radians(a0 if sgn == 1 else 180 - a0)
        px, py = ix + math.cos(a) * 1.5, iy + math.sin(a) * 1.5
        pts = [(px, py), (px + math.cos(a) * ln * 0.5 + rng.uniform(-0.6, 0.6), py + math.sin(a) * ln * 0.5),
               (px + math.cos(a) * ln, py + math.sin(a) * ln)]
        s.add(f"hm_ear{i}_vein{k}", "path", "hamster", z=s.elements[f"hm_ear{i}_inner"]["z"] + 0.02 + k * 0.001,
              d=smooth_d(pts), fill="none", stroke="#DB7F86", stroke_width=0.55, stroke_opacity=0.55,
              stroke_linecap="round", anim="draw")
# whisker-pad pores
for side in (0, 1):
    for k, (px, py) in enumerate([(213.5, 331.6), (215.5, 336.2), (213.8, 340.8), (218.2, 333.8)]):
        x = px if side == 0 else 512 - px
        s.add(f"hm_pore{side}{k}", "circle", "hamster_fx", cx=x, cy=py, r=0.75, fill="#8E6A5E", fill_opacity=0.55, anim="pop")
s.commit(zooms=[(176, 250, 160, 112), (220, 306, 72, 44)])
