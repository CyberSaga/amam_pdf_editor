"""Batch 1 of the 01_開啟 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, RED, YELLOW, YELLOW_DARK, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：資料夾前後片、右後方的 PDF 紙、夾子裡的倉鼠臉。",
        "紙外緣 x 9/15、紅標誌逐像素 3×4；資料夾 1 px 框；倉鼠 16 格探頭臉夾在前後片之間。",
        tempo="normal")
s.add("sheet", "path", "back", d=page_d(9.5, 1.5, 14.5, 12, 1, 2), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "back", d=flap_d(14.5, 1.5, 2, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "pdf", [".R.", ".R.", "R.R"], 11, 3, "back", legend={"R": ("mark", RED)})
s.add("folder_back", "path", "back", d="M1.5 5.5H4L5 6.5H14.5V14.5H1.5Z", fill=YELLOW_DARK, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK16, 2, 2, "hamster")
s.add("folder_front", "path", "front", d="M1.5 7.5H5L6 8.5H13.5V14.5H1.5Z", fill=YELLOW, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.commit()
