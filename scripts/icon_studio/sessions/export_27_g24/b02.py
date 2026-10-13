"""Batch 2 of the 27_匯出頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠怪、不如儲存精緻。方盒頭身、貓耳般的斜角耳朵。",
        "改用 48 格同一套構造（1 px 向量外框＋整數像素五官），藏在紙右緣與箭頭後面。",
        tempo="normal")
s.look((12, 3, 11, 12), "方盒倉鼠")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 18, 10.0, 0.5, layer="hamster", body=11, feet=False)
s.commit()
