"""Batch 3 of the 19_插入圖片 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from studio import Studio

RIDGE = [(0.0, 0.70), (0.31, 0.34), (0.56, 0.62), (0.72, 0.47), (1.0, 0.76)]


def ridge_d(x0, y0, w, h, pr, inset):
    """The b01 ridge with both ends pulled ``inset`` along their slopes (butt ends stay inside the sky)."""
    pts = [(x0 + u * w, y0 + v * h) for u, v in RIDGE]
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


s = Studio.open()
s.begin(6, "48 格：稜線端點收進天空",
        "48 px 實際像素看：整體和參考一致，臉、太陽、山、加號都讀得出來；但稜線是斜的平頭線，左端的切角凸出天空左緣約 0.6 格，"
        "白邊上多了一格淡青綠，右端在圓章下也一樣。",
        "稜線兩端沿著山坡各收進 0.9 格（1.5 px 線的切角剛好落在天空內），山的色塊不動、仍然貼齊天空邊緣。",
        tempo="normal")
s.look((5, 26, 4, 5), "稜線左端凸出天空")
s.mod("ridge", note="兩端收進 0.9 格", d=ridge_d(7, 9, 29, 29, 1.6, 0.9))
s.commit()
