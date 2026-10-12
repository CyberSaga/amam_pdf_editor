"""Batch 1 of the 03_儲存 16 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import pts_d
from kit import pencil_line
from studio import Studio

s = Studio.open()
s.begin(1, "16 格：像素格與構圖草稿",
        "16×16 只有 256 個像素，每一列都要算：外框、擋板、標籤窗各自需要 1 px 框線和至少 1 px 的間隔，否則會黏成一塊。",
        "先排列預算（由上而下）：第 1 列外框、2–4 擋板白、5 擋板框、6 紫色、7 標籤框、8–11 標籤白、12 標籤框、13 紫色、14 外框。本體 12×14 格（比例 1.17，和原作一致）。",
        tempo="slow")
grid = "".join(f"M{i} 0V16M0 {i}H16" for i in range(17))
s.add("gd_pixels", "path", "guides", d=grid, fill="none", stroke="#78A6D8", stroke_width=0.025, stroke_opacity=0.55, anim="draw")
s.add("gd_keyline", "path", "guides", d=pts_d([(1, 1), (15, 1), (15, 15), (1, 15)], closed=True), fill="none",
      stroke="#D0605E", stroke_width=0.05, stroke_opacity=0.7, stroke_dasharray="0.3 0.2", anim="draw")
rng = random.Random(16)
W, OP = 0.08, 0.55
for name, p0, p1 in [("t", (2, 1.2), (14, 1.15)), ("l", (2.1, 1.2), (2.05, 14.9)), ("r", (13.9, 1.2), (13.95, 14.9)),
                     ("b", (2.1, 14.9), (13.9, 14.95)), ("ch", (11, 1.15), (14, 4.2)),
                     ("sh_l", (5, 1.2), (5, 6)), ("sh_r", (11, 1.2), (11, 6)), ("sh_b", (5, 6), (11, 6)),
                     ("lb_t", (4, 7), (12, 7)), ("lb_l", (4, 7), (4, 13)), ("lb_r", (12, 7), (12, 13)), ("lb_b", (4, 13), (12, 13))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=W, op=OP, amp=0.03, overshoot=0.04)
pencil_line(s, "sk_slot", (8.5, 2.2), (8.5, 3.8), rng, w=0.6, op=0.35, amp=0.01, overshoot=0.0, n=3)
s.commit(compare=True)
