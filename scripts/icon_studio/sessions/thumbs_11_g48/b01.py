"""Batch 1 of the 11_縮圖 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import rrect_d
from kit import pencil_ellipse, pencil_line
from parts import INK, PAPER, PURPLE_LIGHT, TEAL, hamster48
from studio import Studio

s = Studio.open()
s.begin(1, "48 格：草稿與大色塊",
        "參考圖：深藍圓角框（外緣約 x 8–40、y 12–44.5）裡排著 2×2 的方塊，左欄兩塊淡紫、右欄兩塊青綠；倉鼠從框的上緣偏右"
        "探出頭，頭向右歪約 20°，兩隻手掌搭在框緣。",
        "框外緣定在 x 8–40、y 13–45（32×32），2.5 px 深藍框；方塊各 10×10、1.5 px 框，彼此間隔 2、離框 2.5；倉鼠頭 13.2×11.2"
        "放在框上緣、中心 x 27，只露出框緣以上，頭轉 10°（參考的一半，五官才不會散在半格上）；先鋪色塊。",
        tempo="slow")
rng = random.Random(1148)
for name, p0, p1 in [("t", (8.4, 13.2), (39.6, 13.1)), ("r", (39.8, 13.3), (39.7, 44.8)), ("b", (39.6, 44.9), (8.4, 44.8)),
                     ("l", (8.2, 44.7), (8.3, 13.3)), ("mid_v", (24, 17), (24.1, 41)), ("mid_h", (12, 29), (36, 29.1))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 27, 11.6, 6.6, 5.6, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("frame", "path", "object", d=rrect_d(9.25, 14.25, 38.75, 43.75, 2.5), fill=PAPER, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
for i, (x0, y0, col) in enumerate(((13, 18, PURPLE_LIGHT), (25, 18, TEAL), (13, 30, PURPLE_LIGHT), (25, 30, TEAL))):
    s.add(f"tile{i}", "path", "object", d=rrect_d(x0 + 0.75, y0 + 0.75, x0 + 9.25, y0 + 9.25, 1.0), fill=col, stroke=INK,
          stroke_width=1.5, stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 27, 11.6, 6.6, 5.6, k=0.68, eye_y=10.0, rot=10, parts=("blocks",))
s.commit(compare=True)
