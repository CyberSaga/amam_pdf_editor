"""Batch 2 of the 20_貼上圖片 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格是逐像素的方盒臉（直邊、斜角耳朵）；改成圓頂頭後底寬約 9.6 格，"
        "比夾板較窄的上排（8 格）寬，頭的平底兩角會露在夾板上角外面。",
        "倉鼠改用同一套構造縮到 24 格（k 0.5、中心 x 12、平底在夾板上緣 y 6.5），眼睛 2×2 帶反光、鼻子、腮紅放整數像素；"
        "夾板上排改成和下排一樣寬（10 格），蓋住頭的平底；拿掉壓在夾板上的手掌。",
        tempo="normal")
s.look((6, 0, 12, 8), "方盒臉、耳朵像貓")
old = [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
CLIP = [
    "NNNNNNNNNN",
    "NPLLPPPPPN",
    "NPPPPPPPPN",
    "NNNNNNNNNN",
]
s.mod("clip_ink", note="夾板上排加寬", d=pix_d(CLIP, "N", 7, 6))
hamster_face_px(s, "hf", 24, 12, 6.5, 0.5)
s.commit()
