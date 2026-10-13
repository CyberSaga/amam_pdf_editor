"""Batch 1 of the 05_另存為最佳化的副本 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：紙與倉鼠",
        "參考圖：置中的折角紙（x 13–35、y 13–45），中央紅色 PDF 緞帶標誌、下面兩條淡線；左右各一支紫色小箭頭往紙中間壓；"
        "倉鼠從紙上緣探頭、一手搭著紙緣。",
        "紙沿用規格；倉鼠頭 13×11.6 放在紙上緣，眼睛提到 y 8；先鋪紙、折角與倉鼠頭耳。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(14.25, 14.25, 33.75, 43.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(33.75, 14.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 24.5, 9.4, 6.6, 5.8, k=0.68, eye_y=8.0, parts=("blocks",))
s.commit()
