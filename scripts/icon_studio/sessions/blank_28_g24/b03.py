"""Batch 3 of the 28_插入空白頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAW24, hamster_bean_px, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠身體怪、不如儲存精緻。逐像素的方盒頭身，耳朵兩格斜角像貓耳；48 格已改成儲存的圓頂頭與圓胖身體。",
        "改用同一套構造縮到 24 格（1 px 向量外框讓輪廓變圓，眼睛、鼻子、腮紅放整數像素），仍藏在紙右緣後、一隻手搭在紙緣。",
        tempo="normal")
s.look((12, 5, 11, 12), "方盒倉鼠")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 18, 11.0, 0.5, layer="hamster", body=11)
pixmap(s, "hb_paw", PAW24, 11, 12, "front")
s.commit()
