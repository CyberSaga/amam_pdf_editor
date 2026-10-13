"""Batch 1 of the 34_適應畫面 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, TEAL_DARK, flap_d, page_d, pixmap
from studio import Studio

SLATE = "#5B6F95"
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：四角取景角、紙、兩支往內的箭頭、左下的倉鼠。",
        "取景角 1 px、臂長 3；紙外緣 x 5/12、y 3/13；箭頭 3×3；倉鼠用 16 格探頭臉加一列身體，站在左下角。",
        tempo="normal")
L = ["SSS", "S..", "S.."]
for i, (rows, x, y) in enumerate(((L, 0, 0), ([r[::-1] for r in L], 13, 0), (L[::-1], 0, 13),
                                  ([r[::-1] for r in L[::-1]], 13, 13))):
    pixmap(s, f"corner{i}", rows, x, y, "back", legend={"S": ("fill", SLATE)})
s.add("sheet", "path", "object", d=page_d(5.5, 3.5, 11.5, 12.5, 1, 2), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(11.5, 3.5, 2, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "arrows", ["T..", ".TT", ".TT"], 2, 2, "badge", legend={"T": ("fill", TEAL_DARK)})
pixmap(s, "arrows2", ["TT.", "TT.", "..T"], 11, 11, "badge", legend={"T": ("fill", TEAL_DARK)})
pixmap(s, "hm", PEEK16 + ["PPWWWPP", ".PPPPP."], 0, 8, "front")
s.commit()
