"""Batch 2 of the 31_OCR（文字辨識） 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px, pix_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成儲存構造的臉",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。這張是 7×5 的逐像素方臉，48 格已改成儲存的寬圓頂頭；同一套構造在 24 格要 k 0.5 "
        "才放得下 2×2 眼睛和看得出的耳朵，可是掃描線在 y 11 時，耳朵頂到 y 5.3，貼著掃描器下緣。",
        "掃描線和 T 一起下移一列（掃描線 y 12、T 佔 y 14–22，腳和下方角框同一列），倉鼠用圓頂構造（k 0.5、中線 x 12.5、1 格鼻子），"
        "平底落在掃描線上，耳朵頂到 y 6、和掃描器隔一格；兩隻手掌各 2 格搭在掃描線上、兩頰正下方。",
        tempo="normal")
s.look((7, 5, 11, 8), "方臉、耳朵沒地方")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
s.mod("scan_line", note="掃描線下移一列", d="M7 12H18V13H7Z")
LETTER_T = [
    "NNNNNNNNNNN",
    "NNNNNNNNNNN",
    "N...NNN...N",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "..NNNNNNN..",
]
s.mod("letter_t_ink", note="T 跟著下移", d=pix_d(LETTER_T, "N", 7, 14))
hamster_face_px(s, "hf", 24, 12.5, 12.45, 0.5)
pixmap(s, "hf_paw", ["PP.....PP"], 8, 12, "front")
s.commit()
