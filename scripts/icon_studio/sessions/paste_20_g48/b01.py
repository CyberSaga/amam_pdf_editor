"""Batch 1 of the 20_貼上圖片 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from geo import f, rrect_d
from kit import pencil_ellipse, pencil_line
from parts import INK, PAPER, PURPLE, PURPLE_LIGHT, TEAL, TEAL_DARK, YELLOW, YELLOW_DARK, hamster48
from studio import Studio

SKY = "#BFE0F5"
BOARD = "#CF8F55"
# Landscape in a unit box (shared with 19_插入圖片): sun (cx, cy, r) and the ridge, peaks rounded.
SUN = (0.73, 0.24, 0.125)
RIDGE = [(0.0, 0.70), (0.31, 0.34), (0.56, 0.62), (0.72, 0.47), (1.0, 0.76)]


def ridge_d(x0, y0, w, h, pr, inset=0.0):
    pts = [(x0 + u * w, y0 + v * h) for u, v in RIDGE]
    if inset:
        for i, j in ((0, 1), (4, 3)):
            d = math.dist(pts[i], pts[j])
            pts[i] = tuple(pts[i][k] + (pts[j][k] - pts[i][k]) * inset / d for k in (0, 1))
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
        "參考圖：棕色寫字板（x 10–37.6、y 14–44.6，深藍外框＋內側一道深藍線）上夾著一張白紙，紙上一張淡紫框的小風景圖（天空、太陽、"
        "兩座山）；紫色夾子上方有一個帶孔的圓頂，倉鼠從夾子後面探頭，夾子的圓頂正好擋在牠的嘴前。",
        "寫字板外緣 x 9–39、y 14–45（2.5 px 深藍框）；內側那道深藍線在 24/16 格會變成「深藍－棕－深藍」三條，這裡就省掉，"
        "白紙直接放在棕色上（四周 2.5 格棕）；小圖 16×16、淡紫框 1.5 px，風景照插入圖片同一組單位座標縮成 13×13，線寬按比例縮成 0.75"
        "（稜線兩端照插入圖片的修正收進 0.6 倍線寬）。夾子：草稿試過參考的圓頂，深藍框的圓頂蓋在倉鼠嘴上，1× 像一撇黑鬍子——"
        "改成上窄下寬的夾板、不畫圓頂，倉鼠從夾板上緣探頭（頭 13.2×11.2，眼睛在夾板上 3 格）。",
        tempo="slow")
rng = random.Random(2048)
for name, p0, p1 in [("t", (9.3, 14.2), (38.7, 14.1)), ("r", (38.8, 14.3), (38.9, 44.8)), ("b", (38.7, 44.9), (9.2, 44.8)),
                     ("l", (9.1, 44.7), (9.2, 14.3)), ("clip", (15.2, 19.8), (32.8, 19.9))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_pic", 24, 29, 8, 8, rng, w=0.2, op=0.45, amp=0.1)
pencil_ellipse(s, "sk_head", 24, 11.6, 6.6, 5.6, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
hamster48(s, "hm", 24, 11.6, 6.6, 5.6, k=0.68, eye_y=10.0, parts=("blocks",))
s.add("board", "path", "object", d=rrect_d(10.25, 15.25, 37.75, 43.75, 2.5), fill=BOARD, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
s.add("paper", "path", "object", d=rrect_d(14, 18, 34, 40, 1.0), fill=PAPER, anim="fill")
s.add("pic", "path", "object", d=rrect_d(16.75, 21.75, 31.25, 36.25, 0.75), fill=SKY, stroke=PURPLE_LIGHT, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
x0, y0, w, h = 17.5, 22.5, 13, 13
k = w / 29  # the 19_插入圖片 picture is 29 wide: same construction, scaled
s.add("sun", "circle", "object_fx", cx=round(x0 + SUN[0] * w, 2), cy=round(y0 + SUN[1] * h, 2),
      r=round(SUN[2] * w - 0.375, 2), fill=YELLOW, stroke=YELLOW_DARK, stroke_width=0.75, anim="fill")
s.add("hills", "path", "object_fx", d=hills_d(x0, y0, w, h, 1.6 * k, 0.0), fill=TEAL, anim="fill")
s.add("ridge", "path", "object_fx", d=ridge_d(x0, y0, w, h, 1.6 * k, inset=0.45), fill="none", stroke=TEAL_DARK,
      stroke_width=0.75, stroke_linejoin="round", anim="draw")
s.add("clip", "path", "front", d="M16 17.5V15.5Q18 14 19.5 14H28.5Q30 14 32 15.5V17.5Q32 19 30.5 19H17.5Q16 19 16 17.5Z",
      fill=PURPLE, stroke=INK, stroke_width=2.0, stroke_linejoin="round", anim="fill")
s.commit(compare=True)
