"""Batch 2 of the 19_插入圖片 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px, plus_px_d
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格是逐像素的方盒臉；換成圓頂頭後底寬 10.5 格：放在 x 8 時左側圓弧貼著相框內緣、"
        "左下角成一團深色，放在 x 9 又碰到加號章。",
        "倉鼠改用同一套構造縮到 24 格（k 0.55、中心 x 9、平底在下框 y 20.1，耳朵離山谷仍隔 1 列）；加號章往右下移 1 格"
        "（中心 (19.5, 19.5)，仍在畫布內），頭的左右各留約 1 格青綠；拿掉壓在下框上的手掌。",
        tempo="normal")
s.look((2, 12, 14, 10), "方盒臉；圓頂頭左右都貼邊")
old = [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
hamster_face_px(s, "hf", 24, 9, 20.1, 0.55)
s.mod("badge_disc", note="加號章右下移 1 格", cx=19.5, cy=19.5)
s.mod("badge_plus", d=plus_px_d(19, 19, 2))
s.commit()
