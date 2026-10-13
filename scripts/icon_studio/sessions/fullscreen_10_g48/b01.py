"""Batch 1 of the 10_全螢幕 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import f
from kit import guide_line, pencil_ellipse, pencil_line
from parts import INK, PURPLE, hamster48
from studio import Studio

CORNERS = [(1, 1), (-1, 1), (1, -1), (-1, -1)]  # top-left, top-right, bottom-left, bottom-right


def corner_d(c, arm, diag, sx, sy):
    """One outward arrow: L-shaped head in the corner (arms to ``arm``) plus a diagonal shaft to (diag, diag)."""
    def x(v):
        return v if sx > 0 else 48 - v

    def y(v):
        return v if sy > 0 else 48 - v
    return f"M{f(x(c))} {f(y(arm))}V{f(y(c))}H{f(x(arm))}M{f(x(c))} {f(y(c))}L{f(x(diag))} {f(y(diag))}"


s = Studio.open()
s.begin(3, "48 格：四支角落箭頭與倉鼠頭的色塊",
        "參考圖：四支紫色箭頭從中間往四個角指出去（每支是角落的 L 形箭頭加一條斜桿，圓頭、深藍細框，L 的臂長約 12、粗約 4），"
        "正中間一顆倉鼠頭（約 12.5×10.5，耳朵在左右上方）。",
        "箭頭照弧形箭頭的規格畫成線條：深藍 5 px 墊底、紫色 2.6 px 在上，形成 1.2 px 外框；L 的中心線在 5.5（外緣落在 3/8 整數格）、"
        "臂與斜桿都到 14（圓頭外緣 16.5），四支用同一條路徑鏡射；倉鼠頭 12.8×10.8（k 0.68）放在 (24, 25)，先鋪色塊。",
        tempo="slow")
guide_line(s, "gd_diag0", (3, 3), (45, 45), w=0.15, dash="1 0.8")
guide_line(s, "gd_diag1", (45, 3), (3, 45), w=0.15, dash="1 0.8")
rng = random.Random(1048)
for i, (sx, sy) in enumerate(CORNERS):
    def x(v, sx=sx):
        return v if sx > 0 else 48 - v

    def y(v, sy=sy):
        return v if sy > 0 else 48 - v
    pencil_line(s, f"sk_l{i}a", (x(5.6), y(14.2)), (x(5.5), y(5.5)), rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
    pencil_line(s, f"sk_l{i}b", (x(5.5), y(5.6)), (x(14.2), y(5.5)), rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
    pencil_line(s, f"sk_d{i}", (x(5.6), y(5.6)), (x(14.1), y(14.2)), rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 24, 25, 6.4, 5.4, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.layer("guides", opacity=0.6)
for i, (sx, sy) in enumerate(CORNERS):
    s.add(f"arrow{i}_ink", "path", "object", d=corner_d(5.5, 14, 14, sx, sy), fill="none", stroke=INK, stroke_width=5,
          stroke_linecap="round", stroke_linejoin="round", anim="draw")
for i, (sx, sy) in enumerate(CORNERS):
    s.add(f"arrow{i}", "path", "object", d=corner_d(5.5, 14, 14, sx, sy), fill="none", stroke=PURPLE, stroke_width=2.6,
          stroke_linecap="round", stroke_linejoin="round", anim="draw")
hamster48(s, "hm", 24, 25, 6.4, 5.4, k=0.68, parts=("blocks",))
s.commit(compare=True)
