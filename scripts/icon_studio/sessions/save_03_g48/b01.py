"""Batch 1 of the 03_儲存 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import pts_d
from kit import pencil_ellipse, pencil_line
from studio import Studio

s = Studio.open()
s.begin(1, "48 格：像素格與構圖草稿",
        "24 格版在 1× 已經清楚，但只容得下兩點眼睛。48 px 用在 200% 縮放的 24 px 圖示、150% 的 32 px 圖示，臉部可以多一層：眼睛反光、嘴、鬍鬚。",
        "主體 36×40（4 px 留白，比例沿用 24 格版的 18×20），擋板 20×15，標籤窗 26×17；倉鼠頭約 20 格寬，耳朵與內耳分開畫。",
        tempo="slow")
grid = "".join(f"M{i} 0V48M0 {i}H48" for i in range(49))
s.add("gd_pixels", "path", "guides", d=grid, fill="none", stroke="#78A6D8", stroke_width=0.05, stroke_opacity=0.5, anim="draw")
s.add("gd_keyline", "path", "guides", d=pts_d([(4, 4), (44, 4), (44, 44), (4, 44)], closed=True), fill="none",
      stroke="#D0605E", stroke_width=0.1, stroke_opacity=0.7, stroke_dasharray="0.8 0.6", anim="draw")
rng = random.Random(48)
W, OP = 0.2, 0.55
for name, p0, p1 in [("t", (6, 4.3), (42, 4.2)), ("l", (6.2, 4.3), (6.1, 43.8)), ("r", (41.9, 4.2), (42, 43.8)),
                     ("b", (6.1, 43.8), (42, 43.9)), ("ch", (34.5, 4.2), (42, 11.7)),
                     ("sh_l", (14, 4.3), (14, 18.5)), ("sh_r", (34, 4.3), (34, 18.5)), ("sh_b", (14, 18.5), (34, 18.5)),
                     ("lb_t", (11, 22), (37, 22)), ("lb_l", (11, 22), (11, 39.5)), ("lb_r", (37, 22), (37, 39.5)),
                     ("lb_b", (11, 39.5), (37, 39.5))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=W, op=OP, amp=0.08, overshoot=0.04)
pencil_line(s, "sk_slot", (27.5, 7.5), (27.5, 14.5), rng, w=0.9, op=0.35, amp=0.03, overshoot=0.0, n=3)
pencil_ellipse(s, "sk_head", 24, 39, 9.6, 10.2, rng, w=W, op=0.5, amp=0.12, a0=165, sweep=210)
pencil_ellipse(s, "sk_ear_l", 18.2, 28.6, 2.9, 2.9, rng, w=W, op=0.5, amp=0.06)
pencil_ellipse(s, "sk_ear_r", 29.8, 28.6, 2.9, 2.9, rng, w=W, op=0.5, amp=0.06)
s.commit(compare=True)
