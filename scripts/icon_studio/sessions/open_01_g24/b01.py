"""Batch 1 of the 01_開啟 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE24, INK, PAPER, RED, YELLOW, YELLOW_DARK, flap_d, page_d, pdf_mark_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：打開的資料夾（前後片都帶標籤）、右後方的 PDF 紙、從夾子裡探頭的大臉倉鼠。",
        "紙外緣 x 13/22，PDF 標誌 1 px 紅線；資料夾 1.5 px 框；倉鼠用 FACE24 夾在前後片之間，前片的標籤上緣剛好擋在鼻子下面。",
        tempo="normal")
s.add("sheet", "path", "back", d=page_d(13.75, 3.75, 21.25, 20, 1.5, 3), fill=PAPER, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "back", d=flap_d(21.25, 3.75, 3, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("pdf_mark", "path", "back", d=pdf_mark_d(14.8, 6.6, 5.2, 5.4), fill="none", stroke=RED, stroke_width=1.0,
      stroke_linejoin="round", anim="draw")
s.add("folder_back", "path", "back", d="M3.25 7.75H6.8Q7.6 7.75 8 8.4L8.6 9.25H21.25A1 1 0 0 1 22.25 10.25V21.25H2.25V8.75A1 1 0 0 1 3.25 7.75Z",
      fill=YELLOW_DARK, stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
pixmap(s, "hm", FACE24, 4, 4, "hamster")
s.add("folder_front", "path", "front", d="M3.25 10.75H8.6Q9.3 10.75 9.7 11.3L10.4 12.25H19.25A1 1 0 0 1 20.25 13.25V21.25H2.25V11.75A1 1 0 0 1 3.25 10.75Z",
      fill=YELLOW, stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.commit()
