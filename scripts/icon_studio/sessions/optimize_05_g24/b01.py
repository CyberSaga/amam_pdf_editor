"""Batch 1 of the 05_另存為最佳化的副本 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PAPER, PEEK24, PURPLE_DARK, RED, flap_d, page_d, pdf_mark_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：紙上緣探頭的倉鼠、紅色 PDF 標誌與兩條線、左右往內壓的紫色箭頭。",
        "紙外緣 x 6/18、y 7/23；探頭臉 8×6；PDF 標誌縮成 6×6.5、1 px 紅線；線只留一條；箭頭改逐像素 5×5 深紫、不包邊（線狀小符號規則）。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(6.75, 7.75, 17.25, 22.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(17.25, 7.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK24, 8, 1, "hamster")
pixmap(s, "paw", ["P......P"], 8, 7, "front")
s.add("pdf_mark", "path", "object_fx", d=pdf_mark_d(8.9, 10.4, 6.2, 6.6), fill="none", stroke=RED, stroke_width=1.1,
      stroke_linejoin="round", anim="draw")
s.add("line0", "path", "object_fx", d="M9 19.5H15", fill="none", stroke=LINE, stroke_width=1, anim="draw")
ARROW = ["..D..", "..DD.", "DDDDD", "..DD.", "..D.."]
pixmap(s, "arrow_l", ARROW, 0, 13, "front", legend={"D": ("fill", PURPLE_DARK)})
pixmap(s, "arrow_r", [r[::-1] for r in ARROW], 19, 13, "front", legend={"D": ("fill", PURPLE_DARK)})
s.commit()
