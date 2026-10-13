"""Batch 1 of the 27_匯出頁 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE16, INK, PAPER, TEAL, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：窄紙、紙後探頭的倉鼠、穿出紙緣的青綠箭頭。",
        "紙外緣 x 1/9、y 1/15；倉鼠用儲存 16 格的臉（右側不畫框）；箭頭改用逐像素畫：3 格高的青綠桿、斜一格一格的箭頭，"
        "框線落在整數格，放低一格避開鼻子那列。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(1.5, 1.5, 8.5, 14.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(8.5, 1.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", FACE16, 9, 2, "hamster")
ARROW = [
    "........N....",
    "........NN...",
    "NNNNNNNNNTN..",
    "NTTTTTTTTTTN.",
    "NTTTTTTTTTTTN",
    "NTTTTTTTTTTN.",
    "NNNNNNNNNTN..",
    "........NN...",
    "........N....",
]
pixmap(s, "arrow", ARROW, 3, 7, "front", legend={"T": ("fill", TEAL), "N": ("ink", INK)})
s.commit()
