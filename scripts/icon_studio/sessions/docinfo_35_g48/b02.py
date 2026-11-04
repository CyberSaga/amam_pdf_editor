"""Batch 2 of the 35_文件資訊 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import BIG_EARS, INK, PAPER, PURPLE, flap_d, hamster_face48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：鋪大色塊",
        "草稿：紙、欄位、圓章都落在格線上；圓章下緣到 y 46，和 28 的加號章一樣比安全框多 1 格（圓章本來就壓在紙角外）。"
        "頭的草稿弧只是定位置，實際用 03 的圓頂頭構造。",
        "紙 2.5 px 外框（外緣 x 6/35、y 12/45 落在整數格）、折角 7、折片 1.5 px 線；倉鼠用 03 的圓頂頭（k 0.78、大耳朵），"
        "平的底邊放在紙上緣外框的頂上（y 12），整顆頭在紙的下層；圓章外半徑 8.5、1.5 px 深藍外框。",
        tempo="normal")
s.layer("sketch", opacity=0.5)
s.add("sheet", "path", "object", d=page_d(7.25, 13.25, 33.75, 43.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(33.75, 13.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
hamster_face48(s, "hf", 15.5, 12.0, 0.78, parts=("blocks",), ears=BIG_EARS)
s.add("badge_disc", "circle", "badge", cx=36.5, cy=37.5, r=7.75, fill=PURPLE, stroke=INK, stroke_width=1.5,
      anim="fill")
s.commit()
