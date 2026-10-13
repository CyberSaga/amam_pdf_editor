"""Batch 2 of the 02_列印 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成儲存構造的臉",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。這張是 8×6 的方盒臉，兩側直邊、耳朵兩格斜角，和 48 格新換上的寬圓頂頭對不起來；"
        "手掌在紙角各 2 格，貼在方盒臉的外側像肩膀。",
        "改用同一套圓頂構造縮到 24 格（k 0.5，底寬 9.6，剛好收在進紙白紙 x 7–17 之內）：頭、耳朵、白口鼻用 1 px 外框的向量，"
        "眼睛 2×2 帶反光、2 格鼻子、腮紅放整數像素；平底落在紙緣那列；手掌改到兩頰正下方（x 8–9、14–15），像 48 格搭在紙緣上。",
        tempo="normal")
s.look((6, 0, 12, 9), "方盒臉對不上新的圓頂頭")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face_px(s, "hf", 24, 12, 7.4, 0.5)
pixmap(s, "hf_paw", ["PP....PP"], 8, 7, "front")
s.commit()
