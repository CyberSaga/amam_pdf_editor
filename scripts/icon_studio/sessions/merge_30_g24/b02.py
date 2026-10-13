"""Batch 2 of the 30_合併PDF 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠怪、不如儲存精緻。中間是逐像素方臉、斜角耳朵。",
        "改用 48 格同一套構造（1 px 向量外框＋整數像素五官），小一點（k 0.42）放在兩支箭頭之間、紙疊上方。",
        tempo="normal")
s.look((8, 8, 9, 8), "方臉")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 12, 13.6, 0.42, layer="hamster", body=5, feet=False)
s.commit()
