"""Batch 1 of the 29_從檔案插入頁 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, TEAL_DARK, YELLOW, YELLOW_DARK, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：資料夾、抽出的紙、夾子裡的倉鼠臉、深青綠彎箭頭。",
        "紙外緣 x 7/13、y 1/…；資料夾 1 px 框；倉鼠 16 格探頭臉卡在前後片之間；彎箭頭逐像素放右側。",
        tempo="normal")
s.add("sheet", "path", "back", d=page_d(7.5, 1.5, 12.5, 12, 1, 2), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "back", d=flap_d(12.5, 1.5, 2, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("folder_back", "path", "back", d="M1.5 7.5H4L5 8.5H12.5V14.5H1.5Z", fill=YELLOW_DARK, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK16, 2, 5, "hamster")
s.add("folder_front", "path", "front", d="M2.5 10.5H12.5V14.5H2.5Z", fill=YELLOW, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "arrow", ["..TT", "...T", ".T.T", "T...", "T..."], 12, 5, "front", legend={"T": ("fill", TEAL_DARK)})
s.commit()
