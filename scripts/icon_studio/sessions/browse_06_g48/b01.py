"""Batch 1 of the 06_瀏覽模式 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from geo import f
from kit import pencil_ellipse, pencil_line
from parts import INK, PEACH, WHITE, hamster48
from studio import Studio

NAVY = "#454A78"  # the reference cursor's slate navy, a step lighter than the INK outline
# Cursor measured on the reference (tip, wing tip, right notch, tail corners, left notch, left wing), turned
# upright (left edge vertical), scaled 0.88 about the tip and placed with the tip at (14.5, 7.5).
UPRIGHT = [(12.3, 6.2), (33.62, 25.77), (25.34, 29.14), (31.06, 41.99), (24.86, 43.67), (19.44, 30.75), (12.3, 35.75)]
CURSOR = [(14.5 + (x - 12.3) * 0.88, 7.5 + (y - 6.2) * 0.88) for x, y in UPRIGHT]


def poly_d(pts):
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"


def offset_d(pts, d):
    """Outward offset of a clockwise polygon: arcs of radius d at convex corners, mitred at the notches."""
    n = len(pts)
    nrm = []
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        ln = math.hypot(x1 - x0, y1 - y0)
        nrm.append(((y1 - y0) / ln, -(x1 - x0) / ln))
    out = []
    for i in range(n):
        vx, vy = pts[i]
        na, nb = nrm[i - 1], nrm[i]
        ea = (vx - pts[i - 1][0], vy - pts[i - 1][1])
        eb = (pts[(i + 1) % n][0] - vx, pts[(i + 1) % n][1] - vy)
        cmd = "L" if out else "M"
        if ea[0] * eb[1] - ea[1] * eb[0] > 0:
            out.append(f"{cmd}{f(vx + d * na[0])} {f(vy + d * na[1])}A{f(d)} {f(d)} 0 0 1 {f(vx + d * nb[0])} {f(vy + d * nb[1])}")
        else:
            k = d / (1 + na[0] * nb[0] + na[1] * nb[1])
            out.append(f"{cmd}{f(vx + k * (na[0] + nb[0]))} {f(vy + k * (na[1] + nb[1]))}")
    return "".join(out) + "Z"


s = Studio.open()
s.begin(3, "48 格：游標、白邊與倉鼠的大色塊",
        "參考圖：一支深石板藍的滑鼠游標（往左歪約 6°），外面一圈 1.8 px 白邊和細黑框；倉鼠的臉在游標頭部的下半，"
        "身體被游標分叉處的白邊切掉，像從游標的窗口裡探頭。",
        "游標改成正立（左緣垂直）：左緣落在整數格，24、16 格的像素游標也只能正立，三個尺寸一致；形狀照參考量的七個頂點、"
        "縮 0.88。結構：石板藍的游標本體在最底、倉鼠在中間、白邊做成一圈（外圈減本體）蓋在倉鼠上面，切出探頭的效果；"
        "外框 2.5 px 深藍沿外圈描，轉角是圓角、分叉處是尖角，白邊留 2 px。倉鼠頭 12×10.8（k 0.68）放 (20.8, 24.4)，"
        "左緣由白邊當輪廓，身體藏到分叉處的白邊後面。",
        tempo="slow")
rng = random.Random(648)
for i in range(len(CURSOR)):
    pencil_line(s, f"sk_e{i}", CURSOR[i], CURSOR[(i + 1) % len(CURSOR)], rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 20.8, 24.4, 6.0, 5.4, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("cursor", "path", "back", d=poly_d(CURSOR), fill=NAVY, anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=19.8, cy=31.2, rx=4.6, ry=4.0, fill=PEACH, stroke=INK, stroke_width=1.25,
      anim="fill")
hamster48(s, "hm", 20.8, 24.4, 6.0, 5.4, k=0.68, parts=("blocks",))
s.add("cursor_rim", "path", "object", d=offset_d(CURSOR, 3.25) + poly_d(CURSOR), fill=WHITE, fill_rule="evenodd",
      anim="fill")
s.add("cursor_ink", "path", "object", d=offset_d(CURSOR, 3.25), fill="none", stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="draw")
s.commit(compare=True)
