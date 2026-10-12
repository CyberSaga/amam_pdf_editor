"""Batch 1 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import pts_d
from kit import pencil_ellipse, pencil_line
from studio import Studio

s = Studio.open()
s.begin(1, "24 格：像素格與構圖草稿",
        "24×24 只有 576 個像素。實測：1,550 元素版縮到 24 px 時，卡片底佔掉一半畫面，磁碟只剩約 12 px 寬，倉鼠縮成 3–4 px 的橘點。",
        "這版不畫卡片底，主體填滿 2 px 留白內的 20×20。先鋪像素格與留白線，再用目測草稿定出本體、擋板、標籤窗與倉鼠頭的位置。",
        tempo="slow")
grid = "".join(f"M{i} 0V24M0 {i}H24" for i in range(25))
s.add("gd_pixels", "path", "guides", d=grid, fill="none", stroke="#78A6D8", stroke_width=0.03, stroke_opacity=0.55, anim="draw")
s.add("gd_keyline", "path", "guides", d=pts_d([(2, 2), (22, 2), (22, 22), (2, 22)], closed=True), fill="none",
      stroke="#D0605E", stroke_width=0.06, stroke_opacity=0.7, stroke_dasharray="0.4 0.3", anim="draw")
rng = random.Random(24)
W, OP = 0.11, 0.55
pencil_line(s, "sk_body_t", (2.2, 2.3), (21.8, 2.2), rng, w=W, op=OP, amp=0.05, overshoot=0.04)
pencil_line(s, "sk_body_l", (2.2, 2.3), (2.3, 21.8), rng, w=W, op=OP, amp=0.05, overshoot=0.04)
pencil_line(s, "sk_body_r", (21.9, 2.2), (21.8, 21.8), rng, w=W, op=OP, amp=0.05, overshoot=0.04)
pencil_line(s, "sk_body_b", (2.3, 21.8), (21.8, 21.9), rng, w=W, op=OP, amp=0.05, overshoot=0.04)
pencil_line(s, "sk_chamfer", (17.8, 2.2), (21.9, 6.3), rng, w=W, op=OP, amp=0.04, overshoot=0.06)
pencil_line(s, "sk_sh_l", (7, 2.2), (7, 9.6), rng, w=W, op=OP, amp=0.04, overshoot=0.05)
pencil_line(s, "sk_sh_r", (17, 2.2), (17, 9.6), rng, w=W, op=OP, amp=0.04, overshoot=0.05)
pencil_line(s, "sk_sh_b", (7, 9.6), (17, 9.6), rng, w=W, op=OP, amp=0.04, overshoot=0.05)
pencil_line(s, "sk_slot", (13, 4.4), (13, 7.6), rng, w=0.35, op=0.4, amp=0.02, overshoot=0.0, n=3)
for name, p0, p1 in [("t", (5, 11), (19, 11)), ("l", (5, 11), (5, 19.6)), ("r", (19, 11), (19, 19.6)), ("b", (5, 19.6), (19, 19.6))]:
    pencil_line(s, f"sk_lb_{name}", p0, p1, rng, w=W, op=OP, amp=0.04, overshoot=0.05)
pencil_ellipse(s, "sk_head", 12, 18.2, 4.6, 4.6, rng, w=W, op=0.5, amp=0.08, a0=160, sweep=220)
pencil_ellipse(s, "sk_ear_l", 9.2, 13.9, 1.3, 1.3, rng, w=W, op=0.5, amp=0.04)
pencil_ellipse(s, "sk_ear_r", 14.8, 13.9, 1.3, 1.3, rng, w=W, op=0.5, amp=0.04)
s.commit(compare=True)
