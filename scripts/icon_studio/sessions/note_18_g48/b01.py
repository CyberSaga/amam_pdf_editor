"""Batch 1 of the 18_新增註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import f
from kit import pencil_ellipse, pencil_line
from parts import INK, PEACH, PURPLE, YELLOW, hamster48
from studio import Studio


def bubble_d(x0: float, y0: float, x1: float, y1: float, r: float, ta: float, tb: float, ty: float) -> str:
    """Speech bubble outline: rounded rect with a tail under the bottom edge.

    The tail's straight edge drops vertically at x=ta to the tip (ta, ty); its slanted
    edge returns to the bottom edge at x=tb (tb > ta: tail on the left; tb < ta: mirrored).
    """
    if tb > ta:
        tail = f"H{f(tb)}L{f(ta)} {f(ty)}V{f(y1)}"
    else:
        tail = f"H{f(ta)}V{f(ty)}L{f(tb)} {f(y1)}"
    return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}{tail}H{f(x0 + r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")


s = Studio.open()
s.begin(1, "48 格：構圖草稿與大色塊",
        "參考圖：一個黃色圓角對話框佔畫面大半（x 12–40、y 8–36），尾巴在左下、左邊垂直、右邊斜回框底，框內三條咖啡色字線；"
        "倉鼠從框的左緣後面探頭，只露出半張臉；紫色加號圓章壓在右下角。",
        "對話框外緣 x 14–40、y 8–36（比參考窄 2 格，讓倉鼠露出兩隻眼睛），2.5 px 深藍框、圓角 2.5，尾巴左邊 x 18.25 垂直落到 y 39.25、"
        "斜邊回到 x 24.25；倉鼠頭 13.6×12.4 放左邊、往外歪 15°，右頰藏進框後；圓章外半徑 6.5、中心 (37.5, 33.5)。",
        tempo="slow")
rng = random.Random(1848)
W, OP = 0.2, 0.55
for name, p0, p1 in [("t", (15.2, 8.1), (38.8, 8.0)), ("r", (40, 9.6), (39.9, 34.6)), ("b", (38.6, 35.9), (25, 36)),
                     ("tail_r", (25, 36), (18.6, 40.4)), ("tail_l", (18.2, 40.4), (18.1, 36)), ("b2", (18.1, 36), (15.4, 35.9)),
                     ("l", (14, 34.6), (14.1, 9.6))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=W, op=OP, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 9.5, 22, 6.8, 6.2, rng, w=W, op=0.5, amp=0.1)
pencil_ellipse(s, "sk_badge", 37.5, 33.5, 6.5, 6.5, rng, w=W, op=0.5, amp=0.08)
s.layer("sketch", opacity=0.55)
hamster48(s, "hm", 9.5, 22, 6.8, 6.2, k=0.72, rot=-15, parts=("blocks",))
s.add("bubble", "path", "object", d=bubble_d(15.25, 9.25, 38.75, 34.75, 2.5, 18.25, 24.25, 39.25), fill=YELLOW,
      stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("badge_disc", "circle", "badge", cx=37.5, cy=33.5, r=5.75, fill=PURPLE, stroke=INK, stroke_width=1.5, anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=12.6, cy=30.6, rx=4.2, ry=5.0, fill=PEACH, stroke=INK, stroke_width=1.25,
      anim="fill", z=0.5)
s.commit(compare=True)
