"""Batch 3 of the 22_添加浮水印 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭的那隻",
        "使用者回饋：倉鼠怪、不如儲存精緻。逐像素的方臉、斜角耳朵像貓；48 格已改成儲存的圓頂頭。",
        "改用 48 格同一套構造（1 px 向量外框讓輪廓變圓，眼睛、鼻子、腮紅放整數像素），底邊藏在紙上緣的線下，印章的手掌保留。",
        tempo="normal")
s.look((5, 0, 11, 9), "方臉")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face_px(s, "hf", 24, 10, 7.8, 0.6)
s.commit()
