"""Batch 1 of the 21_註解列表 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import f
from kit import pencil_ellipse, pencil_line
from parts import INK, PURPLE_LIGHT, TEAL, YELLOW, hamster48
from studio import Studio


def bubble_d(x0: float, y0: float, x1: float, y1: float, r: float, ta: float, tb: float, ty: float) -> str:
    """Speech bubble outline (same construction as 18_新增註解): rounded rect with a tail under the bottom edge.

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
        "參考圖：三個疊在一起的對話框——青綠在最後（右側，尾巴在右下）、黃色在中上（尾巴在右下、右邊垂直）、淡紫在最前（左下，"
        "尾巴在左下、左邊垂直）；黃框三條、紫框兩條字線；倉鼠從左邊探頭，躲在黃框和紫框後面，兩隻眼睛夾在兩個框之間。",
        "對話框沿用新增註解的做法：2.5 px 深藍框、圓角 2.5、尾巴寬 6 高 4.5；黃框外緣 x 13–38、y 3–25，青綠 x 21–45、y 19–35，"
        "淡紫 x 10–31、y 27–41（尾巴尖約到 y 45.5）；倉鼠頭 13.2×12 放 (9, 24)、往外歪 15°，和新增註解同一個姿勢。",
        tempo="slow")
rng = random.Random(2148)
W, OP = 0.2, 0.55
for name, p0, p1 in [("y_t", (14, 3.1), (37, 3)), ("y_r", (38, 4.5), (37.9, 24)), ("y_b", (37, 25), (14, 25.1)),
                     ("y_l", (13, 24), (13.1, 4.5)), ("t_t", (38, 19.1), (44.6, 19)), ("t_r", (45, 20), (44.9, 34)),
                     ("t_b", (44, 35), (31, 35.1)), ("p_t", (11, 27.1), (30, 27)), ("p_r", (31, 28), (30.9, 40)),
                     ("p_b", (30, 41), (11, 41.1)), ("p_l", (10, 40), (10.1, 28))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=W, op=OP, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 9, 24, 6.6, 6.0, rng, w=W, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
hamster48(s, "hm", 9, 24, 6.6, 6.0, k=0.72, rot=-15, parts=("blocks",))
s.add("bubble_teal", "path", "back", d=bubble_d(22.25, 20.25, 43.75, 33.75, 2.5, 39.25, 33.25, 38.25), fill=TEAL,
      stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("bubble_yellow", "path", "object", d=bubble_d(14.25, 4.25, 36.75, 23.75, 2.5, 31.25, 25.25, 28.25), fill=YELLOW,
      stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("bubble_purple", "path", "front", d=bubble_d(11.25, 28.25, 29.75, 39.75, 2.5, 15.25, 21.25, 44.25),
      fill=PURPLE_LIGHT, stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.commit(compare=True)
