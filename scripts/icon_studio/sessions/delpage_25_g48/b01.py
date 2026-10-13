"""Batch 1 of the 25_刪除頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEACH, WHITE, flap_d, hamster48, page_d
from studio import Studio

TRASH, TRASH_DARK = "#9A98D0", "#7B79B8"
s = Studio.open()
s.begin(3, "48 格：紙、垃圾桶、站著的倉鼠",
        "參考圖：折角紙在右（x 16–38、y 3–42），紙中央紅色叉叉，垃圾桶壓在紙的右下角；倉鼠整隻站在左邊、身體擋住紙的左緣、一手搭在紙上。",
        "紙沿用規格；垃圾桶外緣 x 29–45、y 30–46（蓋子深一階）；倉鼠第一次畫全身：頭 13.6×12、身體 14×19.6 的橢圓、白肚子、兩隻腳，"
        "放在紙的上層。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(17.25, 4.25, 36.75, 40.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(36.75, 4.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("can_body", "path", "badge", d="M31.25 35.25L42.75 35.25L41.8 44.6Q41.7 45.25 41 45.25L33 45.25Q32.3 45.25 32.2 44.6Z",
      fill=TRASH, stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("can_lid", "path", "badge", d="M31 31.75H43A1.25 1.25 0 0 1 44.25 33V34A1.25 1.25 0 0 1 43 35.25H31A1.25 1.25 0 0 1 29.75 34V33A1.25 1.25 0 0 1 31 31.75Z",
      fill=TRASH_DARK, stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
for i, (x, y) in enumerate(((7.2, 41.4), (13.8, 41.6))):
    s.add(f"hm_foot{i}", "ellipse", "front", cx=x, cy=y, rx=2.5, ry=1.4, fill=PEACH, stroke=INK, stroke_width=1.1, anim="fill")
s.add("hm_body", "ellipse", "front", cx=10.6, cy=31.2, rx=7.0, ry=9.8, fill=PEACH, stroke=INK, stroke_width=1.25, anim="fill")
s.add("hm_belly", "ellipse", "front", cx=11.4, cy=32.6, rx=4.3, ry=6.8, fill=WHITE, anim="fill")
hamster48(s, "hm", 10.5, 15.2, 6.8, 6.0, layer="front", k=0.72, parts=("blocks",))
s.commit()
