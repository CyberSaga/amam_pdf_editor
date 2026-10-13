"""Batch 1 of the 05_另存為最佳化的副本 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PAPER, PEEK16, PURPLE_DARK, RED, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：探頭臉、紙上的紅標誌與一條線、兩側往內的深紫箭頭。",
        "紙收窄到外緣 x 5/12、y 5/15，讓兩側各放一支 4×5 箭頭；臉用 16 格五列；紅標誌改逐像素 3×4（像一個 A）。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(4.5, 5.5, 11.5, 14.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(11.5, 5.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK16, 4, 0, "hamster")
pixmap(s, "pdf", [".R.", ".R.", "R.R", "RRR"], 6, 8, "object_fx", legend={"R": ("mark", RED)})
pixmap(s, "line", ["LLLL"], 6, 13, "object_fx", legend={"L": ("fill", LINE)})
ARROW = ["..D.", "..DD", "DDDD", "..DD", "..D."]
pixmap(s, "arrow_l", ARROW, 0, 8, "front", legend={"D": ("fill", PURPLE_DARK)})
pixmap(s, "arrow_r", [r[::-1] for r in ARROW], 12, 8, "front", legend={"D": ("fill", PURPLE_DARK)})
s.commit()
