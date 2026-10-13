"""Batch 2 of the 06_瀏覽模式 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。PEEK24 是方臉、斜角耳朵像貓；48 格已改成儲存的圓頂頭、圓鼻口靠在游標分叉的白邊上。",
        "改用 48 格同一套構造（1 px 向量外框、眼睛鼻子腮紅放整數像素），k 0.5、頭心 x 11、底線 y 14.5，圓鼻口在石板藍上；"
        "圓頂比游標頭部寬一點，所以臉放在游標本體那一層、白邊和外框移到臉的上面，左右兩側被白邊切掉而不是蓋住白邊，"
        "游標的左緣保持完整。",
        tempo="normal")
s.look((6, 7, 11, 9), "方臉、貓耳")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hm_")]):
    s.rm(eid, note="舊倉鼠擦掉" if i == 0 else None)
hamster_face_px(s, "hf", 24, 11, 14.5, 0.5, layer="back", chin=2.4)
top = s.zc
s.restack("cursor_rim", top + 1, note="白邊移到臉的上面")
s.restack("cursor_ink", top + 2)
s.commit()
