"""Batch 2 of the 04_另存新檔 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAW24, hamster_bean_px, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠怪、不如儲存精緻。方盒頭身、貓耳般的斜角耳朵。",
        "改用 48 格同一套構造（1 px 向量外框＋整數像素五官），藏在磁片左緣後、一隻手搭在磁片邊上。",
        tempo="normal")
s.look((0, 5, 11, 12), "方盒倉鼠")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 5, 11.5, 0.5, layer="hamster", body=11)
pixmap(s, "hb_paw", PAW24, 7, 13, "front")
s.commit()
