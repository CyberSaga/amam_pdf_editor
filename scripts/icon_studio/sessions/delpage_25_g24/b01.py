"""Batch 1 of the 25_刪除頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PAPER_SHADE, RED, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：右邊折角紙＋紅叉、右下垃圾桶、左邊站著的倉鼠擋住紙的左緣、一手搭在紙上。",
        "紙外緣 x 8/19、y 2/21；紅叉 2 px 不包邊；垃圾桶逐像素 9×9（三列蓋子、兩道直紋）；倉鼠用 BEAN24 加長身體、加兩隻腳，"
        "右邊蓋住紙緣，手掌 2 格搭進紙裡。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(8.75, 2.75, 18.25, 20.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(18.25, 2.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("sheet_shade", "path", "object_fx", d="M17 7.5V19H10.5", fill="none", stroke=PAPER_SHADE, stroke_width=1, anim="draw")
s.add("x_mark", "path", "object_fx", d="M11.5 7.5L15.5 11.5M15.5 7.5L11.5 11.5", fill="none", stroke=RED, stroke_width=2,
      stroke_linecap="round", anim="draw")
CAN = [
    "...NNN...",
    "NNNNNNNNN",
    "NLLLLLLLN",
    "NNNNNNNNN",
    ".NTlTlTN.",
    ".NTlTlTN.",
    ".NTlTlTN.",
    ".NTTTTTN.",
    "..NNNNN..",
]
pixmap(s, "can", CAN, 14, 14, "badge", legend={"T": ("body", "#9A98D0"), "L": ("lid", "#7B79B8"),
                                                "l": ("lines", "#5E5C9C"), "N": ("ink", INK)})
HAMSTER = [
    ".NN....NN.",
    "NKKNNNNKKN",
    "NPPPPPPPPN",
    "NPHEPPHEPN",
    "NPEEWWEEPN",
    "NBWWRRWWBN",
    "NPWWWWWWSN",
    "NPPWWWWPSN",
    "NPPWWWWPSN",
    "NPPWWWWPSN",
    "NPPPWWPPSN",
    ".NPPPPPSN.",
    "NPPN..NPPN",
    ".NN....NN.",
]
pixmap(s, "hm", HAMSTER, 0, 5, "front")
pixmap(s, "paw", [".NN.", "NPPN", ".NN."], 8, 12, "front")
s.commit()
