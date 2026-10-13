"""Batch 1 of the 07_操作物件 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, PEACH, TEAL, hamster48
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：選取框、四個控點、站著的倉鼠",
        "參考圖：左上一個略呈直立的選取框（框線約 x 7.5–30、y 6.5–32），四角各一個深藍框的青綠方形控點；"
        "倉鼠整隻站在右下，頭靠在框的右緣，雙手抱住右下角的控點。",
        "框線 2 px、中心線 x 9/31、y 8/32（邊緣都落在整數格），框內填白，深色底上也看得出框；控點 8×8、2 px 深藍框、"
        "中間 4×4 青綠；倉鼠頭 12.8×11.4（k 0.67）、身體 12.8×14、兩隻腳，畫在框的上層，頭蓋住框右緣約 1 格；"
        "右下控點壓在倉鼠身上。",
        tempo="normal")
s.add("frame", "path", "back", d="M9 8H31V32H9Z", fill=PAPER, stroke=INK, stroke_width=2, anim="fill")
for i, (hx, hy) in enumerate(((9, 8), (31, 8), (9, 32), (31, 32))):
    s.add(f"handle{i}", "path", "object", d=rrect_d(hx - 3, hy - 3, hx + 3, hy + 3, 1.0), fill=TEAL, stroke=INK,
          stroke_width=2, stroke_linejoin="round", anim="fill")
for i, x in enumerate((34.2, 40.6)):
    s.add(f"hm_foot{i}", "ellipse", "hamster", cx=x, cy=44.2, rx=2.3, ry=1.3, fill=PEACH, stroke=INK,
          stroke_width=1.1, anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=37.2, cy=36.8, rx=6.4, ry=7.0, fill=PEACH, stroke=INK, stroke_width=1.25,
      anim="fill")
hamster48(s, "hm", 38.0, 24.6, 6.4, 5.7, k=0.67, parts=("blocks",))
s.commit()
