"""Batch 1 of the 02_列印 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import rrect_d
from kit import pencil_ellipse, pencil_line
from parts import INK, PAPER, hamster48
from studio import Studio

BODY, TRAY, SLOT = "#CFCCEA", "#7B79B8", "#55537F"
s = Studio.open()
s.begin(1, "48 格：草稿與大色塊",
        "參考圖：淡紫灰的印表機機身（外緣 x 6–41、y 20–39）上方一條深一階的進紙匣，倉鼠從進紙匣後探頭、"
        "兩手抓著一張白紙的上緣；機身下半一道深色出紙口，一張有字的白紙從裡面吐出來（下緣 y 45、左下角捲起）。",
        "機身外緣 x 6/42、y 21/39，2.5 px 外框、圓角 3；進紙匣外緣 x 10/38、y 16 起，2 px 框；進紙白紙外緣 x 14/34、y 15 起；"
        "出紙口 x 13–35、y 30 起的深石板色；出紙白紙 2 px 框、下緣 y 45；倉鼠頭 15×13（k 0.78）放在白紙後面，先鋪頭耳色塊。",
        tempo="slow")
rng = random.Random(248)
for name, p0, p1 in [("bt", (6.2, 21.1), (41.8, 21)), ("bb", (6.1, 38.9), (41.9, 39)), ("bl", (6.1, 21.1), (6.2, 38.9)),
                     ("br", (41.9, 21), (41.8, 38.9)), ("tt", (10.2, 16.1), (37.8, 16)), ("st", (14.1, 15.1), (33.9, 15)),
                     ("slot", (13.1, 30.1), (34.9, 30)), ("ot", (15.2, 44.9), (32.8, 45))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 24, 11, 7.4, 6.6, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("tray", "path", "back", d=rrect_d(11, 17, 37, 24, 1.5), fill=TRAY, stroke=INK, stroke_width=2,
      stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 24, 11, 7.4, 6.6, k=0.78, eye_y=10.2, parts=("blocks",))
s.add("sheet_in", "path", "object", d="M15 24V17A1 1 0 0 1 16 16H32A1 1 0 0 1 33 17V24Z", fill=PAPER, stroke=INK,
      stroke_width=2, stroke_linejoin="round", anim="fill")
s.add("printer", "path", "object", d=rrect_d(7.25, 22.25, 40.75, 37.75, 3), fill=BODY, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
s.add("slot", "path", "object", d="M13.75 39V31.75A1 1 0 0 1 14.75 30.75H33.25A1 1 0 0 1 34.25 31.75V39Z", fill=SLOT,
      stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("sheet_out", "path", "object", d="M16 32H32V43A1 1 0 0 1 31 44H13Q11.9 44 12.6 43.1L15.2 39.6Q16 38.5 16 37.2Z",
      fill=PAPER, stroke=INK, stroke_width=2, stroke_linejoin="round", anim="fill")
s.commit(compare=True)
