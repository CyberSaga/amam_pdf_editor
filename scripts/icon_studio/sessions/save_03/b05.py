"""Batch 5 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from studio import Studio
from geo import smooth_d, wobble_ellipse, f
from kit import pencil_curve, pencil_line

DARK = "#3D5390"
s = Studio.open()
s.begin(2, "量頭部輪廓：修正頭形與耳朵的接合",
        "逐行量參考圖的頭部輪廓：頭最寬處在 y≈338（兩頰），到標籤底又微微收回，是橢圓被切掉下緣，不是圓頂；我的輪廓頂部太尖、下緣太寬。耳朵中心在 (221,283)/(291,283)，半徑 16，比我畫的更貼頭。眼睛是直立橢圓（約 11×16）。",
        "頭改為中心 (256,338)、rx58 ry62 的橢圓弧；耳朵重算與頭的交點，只保留頭外的弧；眼睛改成直立橢圓；補上鼻、嘴、白色口鼻區分界與鬍鬚的定位線。",
        tempo="normal")
HEAD = (256.0, 338.0, 58.0, 62.0)
s.params["head"] = HEAD
cx, cy, rx, ry = HEAD
a0 = math.degrees(math.asin((355 - cy) / ry))  # ~15.9
angles = [180 - a0 + (360 + 2 * a0 - 180) * i / 10 for i in range(11)]
head_pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in angles]
s.params["head_pts"] = head_pts
s.look((190, 270, 132, 90), "頭：頂部太尖、下緣太寬 → 改成被切掉的橢圓")
s.mod("ct_head", note="頭形改為橢圓 rx58 ry62，兩頰最寬、下緣收回", d=smooth_d(head_pts))

def in_head(x, y):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 < 1.0

def ear_arc(ex, ey, er):
    outside = [a for a in range(360) if not in_head(ex + er * math.cos(math.radians(a)), ey + er * math.sin(math.radians(a)))]
    # find contiguous run (wrapping)
    s_ = set(outside)
    start = next(a for a in outside if (a - 1) % 360 not in s_)
    end = start
    while (end + 1) % 360 in s_:
        end = (end + 1) % 360
    sweep = (end - start) % 360
    p0 = (ex + er * math.cos(math.radians(start)), ey + er * math.sin(math.radians(start)))
    p1 = (ex + er * math.cos(math.radians(end)), ey + er * math.sin(math.radians(end)))
    large = 1 if sweep > 180 else 0
    return f"M{f(p0[0])} {f(p0[1])}A{f(er)} {f(er)} 0 {large} 1 {f(p1[0])} {f(p1[1])}", (start, end)

EARS = [(221.0, 283.0, 16.0), (291.0, 283.0, 16.0)]
s.params["ears"] = EARS
s.look((200, 262, 112, 40), "耳朵與頭的接合點重新求交")
dl, al = ear_arc(*EARS[0])
dr, ar = ear_arc(*EARS[1])
s.params["ear_arcs"] = [al, ar]
s.mod("ct_ear_l", note="左耳貼近頭頂肩線", d=dl)
s.mod("ct_ear_r", note="右耳對稱", d=dr)
# eyes: upright ovals
s.mod("sk_eye_l", note="眼睛改直立橢圓 11×16", d=smooth_d(wobble_ellipse(235, 320.5, 5.6, 8.0, random.Random(3), amp=0.3, n=10)))
s.mod("sk_eye_r", d=smooth_d(wobble_ellipse(277, 320.5, 5.6, 8.0, random.Random(4), amp=0.3, n=10)))
s.params["eyes"] = [(235.0, 320.5, 5.6, 8.0), (277.0, 320.5, 5.6, 8.0)]
rng = random.Random(55)
# nose + mouth placement
pencil_curve(s, "sk_nose", [(251, 331), (261, 331), (256, 336.5), (251, 331)], w=1.3, op=0.55)
pencil_curve(s, "sk_mouth", [(243, 341), (247.5, 345), (252, 343.5), (256, 339), (260, 343.5), (264.5, 345), (269, 341)], w=1.3, op=0.55)
# white fur boundary (cheeks + muzzle rising between the eyes)
fur = [(198.5, 334), (212, 330), (226, 331), (240, 331), (249, 326), (256, 318), (263, 326), (272, 331), (286, 331), (300, 330), (313.5, 334)]
s.params["fur_boundary"] = fur
pencil_curve(s, "sk_fur", fur, w=1.2, op=0.42)
# whisker directions
for i, (p0, p1) in enumerate([((205, 329), (189, 327)), ((205, 336), (188, 337)), ((206, 343), (190, 347)),
                              ((307, 329), (323, 327)), ((307, 336), (324, 337)), ((306, 343), (322, 347))]):
    pencil_line(s, f"sk_wh{i}", p0, p1, rng, w=1.1, op=0.45, amp=0.3, overshoot=0.0, n=3)
s.commit(compare=True, zooms=[(176, 250, 160, 112)])
