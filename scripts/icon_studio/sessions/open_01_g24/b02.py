"""Batch 2 of the 01_開啟 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭的那隻",
        "使用者回饋：倉鼠怪、不如儲存精緻。逐像素的方臉、斜角耳朵像貓；48 格已改成儲存的圓頂頭。",
        "改用 48 格同一套構造（1 px 向量外框讓輪廓變圓，眼睛、鼻子、腮紅放整數像素），底邊落在前片上緣、左下由標籤擋住。",
        tempo="normal")
s.look((3, 3, 11, 9), "方臉")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face_px(s, "hf", 24, 9, 12.0, 0.55)
s.commit()
