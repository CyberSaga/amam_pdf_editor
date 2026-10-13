"""Batch 1 of the 08_復原 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from geo import f
from kit import pencil_ellipse, pencil_line
from parts import INK, PEACH, PURPLE, hamster48
from studio import Studio


def undo_arrow_d(tip_x, cy, head_h, back_x, top, bot, ocx, rx, ry, tail_deg, qx):
    """Left-pointing hook arrow outline (stroke centre line), pointed tail.

    Head: tip (tip_x, cy), back edge x=back_x; shaft top/bottom y=top/bot. Outer edge: straight to
    (ocx, top), then an elliptical arc (rx, ry) clockwise to ``tail_deg``; inner edge: a circular arc
    tangent to y=bot at x=qx that meets the outer arc at the tail tip.
    """
    t = math.radians(tail_deg)
    px, py = ocx + rx * math.cos(t), top + ry + ry * math.sin(t)
    r = ((px - qx) ** 2 + (py - bot) ** 2) / (2 * (py - bot))
    return (f"M{f(tip_x)} {f(cy)}L{f(back_x)} {f(cy - head_h / 2)}V{f(top)}H{f(ocx)}"
            f"A{f(rx)} {f(ry)} 0 0 1 {f(px)} {f(py)}A{f(r)} {f(r)} 0 0 0 {f(qx)} {f(bot)}"
            f"H{f(back_x)}V{f(cy + head_h / 2)}Z")


s = Studio.open()
s.begin(3, "48 格：彎箭頭與倉鼠的大色塊",
        "參考圖：一支往左指的紫色粗彎箭頭佔下面三分之二（箭頭尖 x 8、頭高 y 16–36，桿子往右再向下彎成鉤，尾巴尖收在 (31, 44)），"
        "倉鼠從箭頭上緣後面探出頭、頭往右歪，兩隻手搭在箭頭頭部和桿子上緣。",
        "箭頭 2.5 px 深藍外框：桿子外緣 y 20/31（整數格）、頭部後緣 x 19–21.5，外弧是 12.75×11.75 的橢圓弧、內弧一段圓弧，"
        "兩弧在尾端收成尖；倉鼠頭 14.4×12.8（k 0.78）轉 16°、身體藏在箭頭後面，先鋪色塊。",
        tempo="slow")
rng = random.Random(848)
for name, p0, p1 in [("tip_t", (9.4, 25.4), (20.2, 16.8)), ("tip_b", (9.4, 25.6), (20.3, 34.2)),
                     ("back", (20.2, 16.8), (20.3, 34.2)), ("top", (20.2, 21.2), (26.8, 21.3))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_outer", 26.75, 33.0, 12.75, 11.75, rng, w=0.2, op=0.5, amp=0.1, a0=-90, sweep=156)
pencil_ellipse(s, "sk_inner", 26.75, 37.7, 7.95, 7.95, rng, w=0.2, op=0.5, amp=0.1, a0=-90, sweep=130)
pencil_ellipse(s, "sk_head", 24.5, 11.5, 7.2, 6.4, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("arrow", "path", "object", d=undo_arrow_d(9.5, 25.5, 17.5, 20.25, 21.25, 29.75, 26.75, 12.75, 11.75, 66, 26.75),
      fill=PURPLE, stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=28.6, cy=17.8, rx=4.8, ry=5.6, fill=PEACH, stroke=INK, stroke_width=1.25,
      transform="rotate(-12 28.6 17.8)", anim="fill")
hamster48(s, "hm", 24.5, 11.5, 7.2, 6.4, k=0.78, rot=16, parts=("blocks",))
s.commit(compare=True)
