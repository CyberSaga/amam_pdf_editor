"""Batch 1 of the 23_浮水印列表 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：前紙＋水滴、一張後紙、倉鼠夾在兩張紙之間探頭。",
        "後紙外緣 x 3/12、y 1/13；倉鼠 16 格探頭臉放 x 9–15；前紙外緣 x 1/10、y 3/15；水滴逐像素 4×5。",
        tempo="normal")
s.add("back1", "path", "object", d="M4 1.5H11A0.5 0.5 0 0 1 11.5 2V12A0.5 0.5 0 0 1 11 12.5H4A0.5 0.5 0 0 1 3.5 12V2A0.5 0.5 0 0 1 4 1.5Z",
      fill="#F1F0F8", stroke=INK, stroke_width=1, stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK16 + ["PPWWWPP"], 9, 6, "object")
s.add("sheet", "path", "object", d=page_d(1.5, 3.5, 9.5, 14.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(9.5, 3.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "drop", [".L..", ".LL.", "LLLL", "LLLL", ".LL."], 3, 7, "object_fx", legend={"L": ("fill", "#B3A9E6")})
s.commit()
