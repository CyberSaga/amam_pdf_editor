"""Batch 3 of the 13_快照 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格的方盒臉直邊、頭頂一條深藍線、耳朵斜角像貓，和 48 格的圓頂頭對不起來；"
        "圓頂頭底寬約 10 格、和凸起一樣寬，凸起上緣的圓角蓋不住頭的平底兩角。",
        "倉鼠改用同一套構造縮到 24 格（k 0.52、中心 x 12、平底在凸起頂 y 6.6），眼睛 2×2 帶反光、鼻子、腮紅放整數像素；"
        "凸起上緣兩角改成直角，框線剛好蓋住頭的平底；拿掉壓在凸起上的手掌。",
        tempo="normal")
s.look((6, 0, 12, 8), "方盒臉、耳朵像貓")
old = [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
s.mod("cam", note="凸起上角改直角",
      d="M3.75 11.25A1.5 1.5 0 0 1 5.25 9.75H7.75V6.75H16.25V9.75H18.75A1.5 1.5 0 0 1 20.25 11.25V19.75A1.5 1.5 0 0 1 "
        "18.75 21.25H5.25A1.5 1.5 0 0 1 3.75 19.75Z")
hamster_face_px(s, "hf", 24, 12, 6.6, 0.52)
s.commit()
