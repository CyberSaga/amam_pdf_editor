"""Batch 1 of the 27_匯出頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEACH, WHITE, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：紙、倉鼠與色塊",
        "參考圖：左邊折角紙（x 5–30、y 3–45），一支青綠色粗箭頭從紙中間穿出右緣，倉鼠從紙的右緣後面探頭，身體被箭頭擋住。",
        "紙沿用前兩張的規格；倉鼠頭 13×12、轉 14°，身體藏在紙與箭頭後面；先鋪紙、倉鼠身體與頭耳。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(6.25, 4.25, 28.75, 43.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(28.75, 4.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=36.6, cy=29, rx=4.6, ry=6.6, fill=PEACH, stroke=INK, stroke_width=1.25,
      transform="rotate(8 36.6 29)", anim="fill")
s.add("hm_belly", "ellipse", "hamster", cx=35.3, cy=29.8, rx=2.1, ry=4.2, fill=WHITE, transform="rotate(8 36.6 29)",
      anim="fill")
hamster48(s, "hm", 36.8, 17.6, 6.6, 5.8, k=0.7, rot=14, parts=("blocks",))
s.commit()
