"""Batch 2 of the 25_刪除頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠身體怪、不如儲存精緻。逐像素的方盒頭配直邊身體，耳朵兩格斜角像貓耳；48 格已改成儲存的圓頂頭與圓胖身體。",
        "改用同一套構造縮到 24 格：圓頂頭、耳朵、身體與白色口鼻／肚子用 1 px 外框的向量（輪廓才圓），眼睛 2×2 帶反光、鼻子與腮紅放整數像素；"
        "倉鼠仍站在紙左緣前面。",
        tempo="normal")
s.look((0, 4, 11, 18), "方盒倉鼠像貓")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 5, 13.5, 0.5, layer="front", body=12)
s.commit()
