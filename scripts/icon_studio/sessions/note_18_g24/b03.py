"""Batch 3 of the 18_新增註解 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。這隻是逐像素的方盒頭（BEAN24）：直邊、耳朵兩格斜角，在 1× 像戴面罩的貓；"
        "48 格已改成儲存的圓頂頭與圓胖身體。",
        "改用同一套構造縮到 24 格（k 0.5）：圓頂頭、耳朵、身體、白色鼻口與肚子用 1 px 外框的向量（輪廓才圓），"
        "眼睛 2×2 帶反光、鼻子與腮紅放整數像素；中心 x 5，右頰那欄仍隔開右眼和框緣，眼睛維持在第 9–10 列。",
        tempo="normal")
s.look((0, 5, 10, 13), "方盒倉鼠像貓")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 5, 12.5, 0.5, layer="hamster", body=12)
s.commit()
