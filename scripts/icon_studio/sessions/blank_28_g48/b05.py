"""Batch 5 of the 28_插入空白頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(7, "48 格：調整收尾",
        "放大看：手掌在紙緣上，但和身體之間空了將近 1 格，像一顆浮在紙邊的豆子。",
        "手掌拉長成一截手臂（rx 2.5、斜 12°），從身體左緣伸到紙緣，蓋在身體與紙的上層；擦掉草稿與參考線。",
        tempo="normal")
s.look((27, 23, 7, 6), "手掌浮著")
s.mod("hm_paw", note="手掌接成手臂", cx=30.6, cy=26.2, rx=2.5, ry=1.4, transform="rotate(-12 30.6 26.2)")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit(small=True)
