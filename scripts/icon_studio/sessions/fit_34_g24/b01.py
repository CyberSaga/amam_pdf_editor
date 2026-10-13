"""Batch 1 of the 34_適應畫面 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, TEAL_DARK, flap_d, page_d, pixmap
from studio import Studio

SLATE = "#5B6F95"
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：四角藍灰取景角、置中折角紙、兩支往內的青綠箭頭、左下的小倉鼠。",
        "取景角逐像素 2 px 粗、臂長 4；紙外緣 x 7/18、y 5/20；箭頭逐像素 4×4 深青綠、不包邊；倉鼠用探頭臉（側邊不畫框）＋三列身體，"
        "站在左下角取景角前面。",
        tempo="normal")
L = ["SSSS", "SSSS", "SS..", "SS.."]
for i, (rows, x, y) in enumerate(((L, 1, 1), ([r[::-1] for r in L], 19, 1), (L[::-1], 1, 19),
                                  ([r[::-1] for r in L[::-1]], 19, 19))):
    pixmap(s, f"corner{i}", rows, x, y, "back", legend={"S": ("fill", SLATE)})
s.add("sheet", "path", "object", d=page_d(7.75, 5.75, 17.25, 19.25, 1.5, 3), fill=PAPER, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(17.25, 5.75, 3, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "arrow_tl", ["T...", ".T.T", "..TT", ".TTT"], 4, 4, "badge", legend={"T": ("fill", TEAL_DARK)})
pixmap(s, "arrow_br", ["TTT.", "TT..", "T.T.", "...T"], 16, 16, "badge", legend={"T": ("fill", TEAL_DARK)})
HAMSTER = [
    ".NN..NN.",
    "NKKNNKKN",
    "PPPPPPPP",
    "PHEPPHEP",
    "PEEWWEEP",
    "BWWRRWWB",
    "PPWWWWPP",
    "PPWWWWPP",
    ".PPPPPP.",
]
pixmap(s, "hm", HAMSTER, 0, 13, "front")
s.commit()
