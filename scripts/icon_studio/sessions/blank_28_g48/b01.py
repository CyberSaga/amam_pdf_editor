"""Batch 1 of the 28_插入空白頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import pts_d
from kit import pencil_ellipse, pencil_line
from studio import Studio

s = Studio.open()
s.begin(1, "48 格：構圖草稿",
        "參考圖：左邊一張折角白紙佔畫面六成，倉鼠從紙的右緣後面探出頭、一手扶著紙邊，紫色加號圓章壓在紙的右下角。",
        "紙 25×39（外緣 x 4–29、y 3–42，折角 7 格）；倉鼠頭約 14×12 放右上、身體藏在紙後；加號圓章直徑 15、中心 (28.5, 38.5)。",
        tempo="slow")
grid = "".join(f"M{i} 0V48M0 {i}H48" for i in range(49))
s.add("gd_pixels", "path", "guides", d=grid, fill="none", stroke="#78A6D8", stroke_width=0.05, stroke_opacity=0.5, anim="draw")
s.add("gd_keyline", "path", "guides", d=pts_d([(3, 3), (45, 3), (45, 45), (3, 45)], closed=True), fill="none",
      stroke="#D0605E", stroke_width=0.1, stroke_opacity=0.7, stroke_dasharray="0.8 0.6", anim="draw")
rng = random.Random(2848)
W, OP = 0.2, 0.55
for name, p0, p1 in [("t", (4.2, 3.2), (22, 3.1)), ("fold", (22, 3.1), (29, 10)), ("r", (29, 10), (28.9, 42)),
                     ("b", (28.9, 41.9), (4.1, 42)), ("l", (4.1, 42), (4.2, 3.2)), ("flap", (22, 3.2), (22.1, 10.1))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=W, op=OP, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 36.5, 17.5, 7.0, 6.0, rng, w=W, op=0.5, amp=0.1)
pencil_ellipse(s, "sk_body", 35.5, 29, 5.2, 8.0, rng, w=W, op=0.45, amp=0.12, a0=-80, sweep=200)
pencil_ellipse(s, "sk_badge", 28.5, 38.5, 7.5, 7.5, rng, w=W, op=0.5, amp=0.08)
s.commit(compare=True)
