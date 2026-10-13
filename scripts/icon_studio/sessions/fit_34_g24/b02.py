"""Batch 2 of the 34_適應畫面 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠怪、不如儲存精緻。左下角是逐像素的方臉加三列身體。",
        "改用 48 格同一套構造（1 px 向量外框＋整數像素五官），小一點（k 0.42），站在左下取景角前面。",
        tempo="normal")
s.look((0, 12, 9, 10), "方臉倉鼠")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 4, 16.6, 0.42, layer="front", body=11)
s.commit()
