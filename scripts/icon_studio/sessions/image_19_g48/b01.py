"""Batch 1 of the 19_插入圖片 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from geo import f, rrect_d
from kit import pencil_ellipse, pencil_line
from parts import INK, PAPER, PURPLE, TEAL, TEAL_DARK, YELLOW, YELLOW_DARK, hamster48
from studio import Studio

SKY = "#BFE0F5"
# Landscape in a unit box (shared with 20_貼上圖片): sun (cx, cy, r) and the ridge, peaks rounded.
SUN = (0.73, 0.24, 0.125)
RIDGE = [(0.0, 0.70), (0.31, 0.34), (0.56, 0.62), (0.72, 0.47), (1.0, 0.76)]


def ridge_d(x0, y0, w, h, pr):
    pts = [(x0 + u * w, y0 + v * h) for u, v in RIDGE]
    out = [f"M{f(pts[0][0])} {f(pts[0][1])}"]
    for i in (1, 2, 3):
        p, q, n = pts[i - 1], pts[i], pts[i + 1]
        if i == 2:
            out.append(f"L{f(q[0])} {f(q[1])}")
            continue
        a = [q[k] + (p[k] - q[k]) * pr / math.dist(p, q) for k in (0, 1)]
        b = [q[k] + (n[k] - q[k]) * pr / math.dist(n, q) for k in (0, 1)]
        out.append(f"L{f(a[0])} {f(a[1])}Q{f(q[0])} {f(q[1])} {f(b[0])} {f(b[1])}")
    return "".join(out) + f"L{f(pts[4][0])} {f(pts[4][1])}"


def hills_d(x0, y0, w, h, pr, r):
    x1, y1 = x0 + w, y0 + h
    return (ridge_d(x0, y0, w, h, pr) + f"V{f(y1 - r)}Q{f(x1)} {f(y1)} {f(x1 - r)} {f(y1)}H{f(x0 + r)}"
            f"Q{f(x0)} {f(y1)} {f(x0)} {f(y1 - r)}Z")


s = Studio.open()
s.begin(1, "48 格：草稿與大色塊",
        "參考圖：深藍圓角相框（外緣約 x 3–40.5、y 5–42）內留一圈白邊，裡面是淺藍天空、右上黃色太陽、兩座青綠山（左高右低）；"
        "倉鼠從相框下緣探出頭、兩隻手掌搭在下框；紫色加號圓章壓在右下角。",
        "相框外緣 x 3–40、y 5–42（2.5 px），白邊 1.5 格，畫面 29×29（x 7–36、y 9–38）；風景用單位方塊座標定義（太陽、"
        "兩座圓頂山的稜線），之後貼上圖片照同一組比例縮放；倉鼠頭 14.4×11、中心 (17.8, 35.8)，夾在畫面和下框之間——"
        "相框分成白底（最底層）與框線（倉鼠上層）兩個元素；圓章外半徑 6.5、中心 (37.5, 37.5)。",
        tempo="slow")
rng = random.Random(1948)
for name, p0, p1 in [("t", (3.3, 5.2), (39.7, 5.1)), ("r", (39.8, 5.3), (39.7, 41.8)), ("b", (39.6, 41.9), (3.2, 41.8)),
                     ("l", (3.1, 41.7), (3.2, 5.3))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_sun", 28.2, 16, 3.6, 3.6, rng, w=0.2, op=0.5, amp=0.06)
pencil_ellipse(s, "sk_head", 17.8, 35.8, 7.2, 5.5, rng, w=0.2, op=0.5, amp=0.1)
pencil_ellipse(s, "sk_badge", 37.5, 37.5, 6.5, 6.5, rng, w=0.2, op=0.5, amp=0.08)
s.layer("sketch", opacity=0.55)
s.add("mat", "path", "back", d=rrect_d(4.25, 6.25, 38.75, 40.75, 2.5), fill=PAPER, anim="fill")
x0, y0, w, h = 7, 9, 29, 29
s.add("sky", "path", "back", d=rrect_d(x0, y0, x0 + w, y0 + h, 1.0), fill=SKY, anim="fill")
s.add("sun", "circle", "back", cx=round(x0 + SUN[0] * w, 2), cy=round(y0 + SUN[1] * h, 2), r=round(SUN[2] * w - 0.75, 2),
      fill=YELLOW, stroke=YELLOW_DARK, stroke_width=1.5, anim="fill")
s.add("hills", "path", "back", d=hills_d(x0, y0, w, h, 1.6, 1.0), fill=TEAL, anim="fill")
s.add("ridge", "path", "back", d=ridge_d(x0, y0, w, h, 1.6), fill="none", stroke=TEAL_DARK, stroke_width=1.5,
      stroke_linejoin="round", anim="draw")
hamster48(s, "hm", 17.8, 35.8, 7.2, 5.5, k=0.78, eye_y=35.2, parts=("blocks",))
s.add("frame", "path", "object", d=rrect_d(4.25, 6.25, 38.75, 40.75, 2.5), fill="none", stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="draw")
s.add("badge_disc", "circle", "badge", cx=37.5, cy=37.5, r=5.75, fill=PURPLE, stroke=INK, stroke_width=1.5, anim="fill")
s.commit(compare=True)
