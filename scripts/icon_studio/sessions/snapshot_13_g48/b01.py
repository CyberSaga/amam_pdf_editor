"""Batch 1 of the 13_快照 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from geo import f
from kit import pencil_ellipse, pencil_line
from parts import INK, PAPER, PURPLE, PURPLE_DARK, WHITE, hamster48
from studio import Studio

LENS = "#3B3D6B"
BAND = "#DCDAEC"


def body_d(x0, y0, x1, y1, r, hx0, hx1, hy, run=3.0, rr=1.0):
    """Camera body: rounded rect with a raised hump on top (base hx0..hx1, top at hy, slopes ``run`` wide)."""
    ln = math.hypot(run, y0 - hy)
    ux, uy = run / ln, (hy - y0) / ln
    return (f"M{f(x0)} {f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}H{f(hx0 - rr)}"
            f"Q{f(hx0)} {f(y0)} {f(hx0 + ux * rr)} {f(y0 + uy * rr)}L{f(hx0 + run - ux * rr)} {f(hy - uy * rr)}"
            f"Q{f(hx0 + run)} {f(hy)} {f(hx0 + run + rr)} {f(hy)}H{f(hx1 - run - rr)}"
            f"Q{f(hx1 - run)} {f(hy)} {f(hx1 - run + ux * rr)} {f(hy - uy * rr)}L{f(hx1 - ux * rr)} {f(y0 + uy * rr)}"
            f"Q{f(hx1)} {f(y0)} {f(hx1 + rr)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}"
            f"V{f(y1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}H{f(x0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}Z")


s = Studio.open()
s.begin(1, "48 格：草稿與大色塊",
        "參考圖：四個深色 L 形取景框角（x 3–45、y 7–44）圍著一台白色相機（機身 x 8–41、y 18–40.5，上方中間一塊凸起、左上一顆"
        "小按鈕）；鏡頭是白環＋深藍鏡片、左上一道青綠反光，機身下半淡紫；倉鼠從凸起後面探頭，一手搭在凸起肩上。",
        "機身外緣 x 8–40、y 17–40（2.5 px 深藍框）連同凸起畫成一條路徑（凸起頂 y 13、寬 11）；取景框角：純深藍細線在深色背景會"
        "整個消失，改成和其他 48 格線狀符號一樣的紫色芯＋深藍邊（3.5 px）；鏡頭外環半徑 8、鏡片半徑 5；機身下半鋪淡紫；"
        "倉鼠頭 13.2×11.2 放在凸起後面、眼睛在凸起頂上 3 格；先鋪色塊。",
        tempo="slow")
rng = random.Random(1348)
for name, p0, p1 in [("t", (8.3, 17.2), (39.7, 17.1)), ("r", (39.8, 17.3), (39.9, 39.8)), ("b", (39.7, 39.9), (8.2, 39.8)),
                     ("l", (8.1, 39.7), (8.2, 17.3)), ("hump", (15.5, 17.1), (32.5, 17.2))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_lens", 24, 28.5, 8.0, 8.0, rng, w=0.2, op=0.5, amp=0.08)
pencil_ellipse(s, "sk_head", 24, 11.4, 6.6, 5.6, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
brackets = ("M4.75 12.25V10.25Q4.75 7.75 7.25 7.75H9.25M43.25 12.25V10.25Q43.25 7.75 40.75 7.75H38.75"
            "M4.75 38.75V40.75Q4.75 43.25 7.25 43.25H9.25M43.25 38.75V40.75Q43.25 43.25 40.75 43.25H38.75")
s.add("brackets_ink", "path", "back", d=brackets, fill="none", stroke=INK, stroke_width=3.5, stroke_linecap="round",
      stroke_linejoin="round", anim="draw")
s.add("brackets", "path", "back", d=brackets, fill="none", stroke=PURPLE, stroke_width=2.0, stroke_linecap="round",
      stroke_linejoin="round", anim="draw")
s.add("button", "path", "back", d="M11 18V16Q11 15.25 11.75 15.25H13.75Q14.5 15.25 14.5 16V18", fill=PURPLE_DARK,
      stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 24, 11.4, 6.6, 5.6, k=0.68, eye_y=9.8, parts=("blocks",))
s.add("cam", "path", "object", d=body_d(9.25, 18.25, 38.75, 38.75, 2.5, 15.5, 32.5, 14.25), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("band", "path", "object_fx", d="M10.5 24H37.5V36.25Q37.5 37.5 36.25 37.5H11.75Q10.5 37.5 10.5 36.25Z", fill=BAND,
      anim="fill")
s.add("ring", "circle", "object_fx", cx=24, cy=28.5, r=7.25, fill=WHITE, stroke=INK, stroke_width=1.5, anim="fill")
s.add("lens", "circle", "object_fx", cx=24, cy=28.5, r=4.25, fill=LENS, stroke=INK, stroke_width=1.5, anim="fill")
s.commit(compare=True)
