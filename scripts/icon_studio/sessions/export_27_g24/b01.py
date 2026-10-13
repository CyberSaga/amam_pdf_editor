"""Batch 1 of the 27_匯出頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import BEAN24, INK, PAPER, PAPER_SHADE, TEAL, block_arrow_d, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：折角紙、從紙右緣後探頭的倉鼠、穿出紙緣的青綠箭頭蓋住倉鼠身體。",
        "紙外緣 x 2/14、y 2/22；倉鼠用 BEAN24，左側輪廓藏在紙緣下，身體被箭頭擋住；箭頭 1 px 深藍框（桿 y 13/18、箭頭 y 10/21、"
        "尖端 x 20.5），框的外緣落在整數格。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(2.75, 2.75, 13.25, 21.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(13.25, 2.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("sheet_shade", "path", "object_fx", d="M12 7.5V20H3.5", fill="none", stroke=PAPER_SHADE, stroke_width=1, anim="draw")
pixmap(s, "hm", BEAN24, 13, 4, "hamster")
s.add("arrow", "path", "front", d=block_arrow_d(6.5, 20.5, 15.5, 4, 10, 6), fill=TEAL, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.commit()
