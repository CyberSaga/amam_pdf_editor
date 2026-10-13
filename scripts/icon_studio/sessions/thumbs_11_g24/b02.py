"""Batch 2 of the 11_縮圖 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import hamster_face_px, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格是逐像素的方盒臉：直邊、頭頂一條深藍線、耳朵兩格斜角像貓，"
        "和 48 格改好的圓頂頭對不起來；框上方只有 6 列，k 0.55 的圓頂放進去耳朵會被畫布上緣切平。",
        "倉鼠改用同一套構造縮到 24 格（k 0.55、中心 x 13、平底落在框上緣 y 7.6）：圓頂、耳朵、白色口鼻是 1 px 外框的向量，"
        "眼睛 2×2 帶反光、鼻子、腮紅放整數像素；框與四個方塊整組下移 1 格（框外緣 y 7–24）讓出耳朵的空間；"
        "拿掉壓在框上的 1 格手掌。",
        tempo="normal")
s.look((8, 0, 10, 8), "方盒臉、耳朵像貓")
old = [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
s.mod("frame", note="框下移 1 格", d=rrect_d(3.75, 7.75, 19.25, 23.25, 1.5))
TILES = [
    "DDDDD.KKKKK",
    "DGLLD.KGTTK",
    "DLLLD.KTTTK",
    "DLLLD.KTTTK",
    "DDDDD.KKKKK",
    "...........",
    "DDDDD.KKKKK",
    "DGLLD.KGTTK",
    "DLLLD.KTTTK",
    "DLLLD.KTTTK",
    "DDDDD.KKKKK",
]
for ch, suffix in (("L", "purple"), ("T", "teal"), ("G", "gloss"), ("D", "purple_ink"), ("K", "teal_ink")):
    s.mod(f"tiles_{suffix}", note="方塊跟著下移" if ch == "L" else None, d=pix_d(TILES, ch, 6, 10))
hamster_face_px(s, "hf", 24, 13, 7.6, 0.55)
s.commit()
