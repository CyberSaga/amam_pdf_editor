"""Batch 1 of the 26_旋轉頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from kit import pencil_ellipse, pencil_line
from parts import INK, PAPER, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(1, "48 格：草稿與大色塊",
        "參考圖：折角紙置中（外緣 x 11–37、y 11–45），紙中央一個順時針的紫色環形箭頭，尾端在五點鐘、箭頭在兩點半朝下；"
        "倉鼠從紙的上緣探出頭，兩隻手掌搭在紙緣。",
        "沿用插入空白頁定下的紙（2.5 px 外框、折角 7）；倉鼠頭 13×11 放在紙上緣、中心 x 23（避開折角），只露出紙緣以上的部分，"
        "所以眼睛提高到 y 8；先鋪紙與倉鼠頭耳的色塊。",
        tempo="slow")
rng = random.Random(2648)
for name, p0, p1 in [("t", (11.2, 11.1), (30, 11)), ("fold", (30, 11), (37, 18)), ("r", (37, 18), (36.9, 45)),
                     ("b", (36.9, 44.9), (11.1, 45)), ("l", (11.1, 45), (11.2, 11.1))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_ring", 24, 30.5, 7.0, 7.0, rng, w=0.2, op=0.5, amp=0.1, a0=60, sweep=282)
pencil_ellipse(s, "sk_head", 23, 9.6, 6.6, 5.6, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("sheet", "path", "object", d=page_d(12.25, 12.25, 35.75, 43.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(35.75, 12.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 23, 9.6, 6.6, 5.6, k=0.68, eye_y=8.0, parts=("blocks",))
s.commit(compare=True)
