"""Batch 2 of the 08_復原 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。逐像素的 PEEK24 是方臉、斜角耳朵像貓；48 格已改成儲存的圓頂頭。",
        "改用 48 格同一套構造（1 px 向量外框讓輪廓變圓，眼睛 2×2 帶反光、鼻子、腮紅放整數像素），k 0.55、頭心 x 15，"
        "底邊藏在桿子上緣的線下；左手 2 格搭在頭部後緣的台階，右手 2×2 壓在彎弧上緣、蓋住彎弧下降處露出的頭底線。",
        tempo="normal")
s.look((9, 2, 12, 9), "方臉、貓耳")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]):
    s.rm(eid, note="舊倉鼠擦掉" if i == 0 else None)
hamster_face_px(s, "hf", 24, 15, 9.6, 0.55)
pixmap(s, "hf_paws", ["PP......PP", "........PP"], 10, 9, "front")
s.commit()
