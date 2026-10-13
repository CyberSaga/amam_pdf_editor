"""Batch 1 of the 34_適應畫面 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEACH, WHITE, flap_d, hamster48, page_d
from studio import Studio

SLATE = "#5B6F95"
s = Studio.open()
s.begin(3, "48 格：對齊角、紙與倉鼠",
        "參考圖（不在聯絡表上，照 PNG）：置中的折角紙（x 13–36、y 9–40），四角深藍灰 L 形取景角，左上與右下各一支青綠小箭頭往紙內指；"
        "小倉鼠站在左下角、一手扶著紙的左緣。",
        "取景角用功能藍灰 3 px、圓頭，不另包深藍邊（本身已夠深）；紙沿用規格；倉鼠頭 11×9.6（k 0.58）＋圓身體，放在左下取景角前面。",
        tempo="normal")
corners = ["M4.5 10.5V6.5Q4.5 4.5 6.5 4.5H10.5", "M37.5 4.5H41.5Q43.5 4.5 43.5 6.5V10.5",
           "M4.5 37.5V41.5Q4.5 43.5 6.5 43.5H10.5", "M37.5 43.5H41.5Q43.5 43.5 43.5 41.5V37.5"]
for i, d in enumerate(corners):
    s.add(f"corner{i}", "path", "back", d=d, fill="none", stroke=SLATE, stroke_width=3, stroke_linecap="round",
          stroke_linejoin="round", anim="draw")
s.add("sheet", "path", "object", d=page_d(14.25, 10.25, 34.75, 38.75, 2.5, 6), fill=PAPER, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(34.75, 10.25, 6, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
for i, (x, y) in enumerate(((7.0, 41.6), (12.0, 41.8))):
    s.add(f"hm_foot{i}", "ellipse", "front", cx=x, cy=y, rx=2.0, ry=1.2, fill=PEACH, stroke=INK, stroke_width=1.0, anim="fill")
s.add("hm_body", "ellipse", "front", cx=9.6, cy=37.0, rx=4.7, ry=4.8, fill=PEACH, stroke=INK, stroke_width=1.25, anim="fill")
s.add("hm_belly", "ellipse", "front", cx=10.0, cy=37.8, rx=2.6, ry=3.2, fill=WHITE, anim="fill")
hamster48(s, "hm", 9.4, 30.8, 5.6, 4.8, layer="front", k=0.58, parts=("blocks",))
s.commit()
