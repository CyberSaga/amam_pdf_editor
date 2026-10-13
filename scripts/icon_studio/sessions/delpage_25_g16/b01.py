"""Batch 1 of the 25_刪除頁 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, RED, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：紙＋紅叉、右下垃圾桶、左邊站著的倉鼠。",
        "紙外緣 x 5/13、y 1/14；紅叉逐像素 4×4；垃圾桶 7×7（蓋子一列、一道直紋）；倉鼠用 16 格的臉加長身體與兩隻腳，右側蓋住紙緣。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(5.5, 1.5, 12.5, 13.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(12.5, 1.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "x", ["R..R", ".RR.", ".RR.", "R..R"], 7, 5, "object_fx", legend={"R": ("mark", RED)})
CAN = [
    "..NNN..",
    "NNNNNNN",
    "NLLLLLN",
    "NNNNNNN",
    ".NTlTN.",
    ".NTlTN.",
    "..NNN..",
]
pixmap(s, "can", CAN, 9, 9, "badge", legend={"T": ("body", "#9A98D0"), "L": ("lid", "#7B79B8"),
                                              "l": ("lines", "#5E5C9C"), "N": ("ink", INK)})
HAMSTER = [
    ".NN.NN.",
    ".KKPKK.",
    "PHEPHEP",
    "PEEPEEP",
    "BWWRWWB",
    "PPWWWPP",
    "PPWWWPP",
    "PPPPPPP",
    ".PP.PP.",
]
pixmap(s, "hm", HAMSTER, 0, 4, "front")
s.commit()
