"""Batch 2 of the 28_插入空白頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEACH, PURPLE, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：鋪大色塊",
        "疊圖：紙的外框和參考吻合；圓章草稿半徑 7.5，參考只有約 6；倉鼠頭中心在參考裡是 (36, 18.3)、高 12.6，"
        "而且左耳在頂、右耳在側，頭向右傾約 20°。",
        "紙外框 2.5 px（外緣落在 x 4/29、y 3/42 整數格），折角 7 格、折片 1.5 px 線；圓章外半徑收為 6.5、中心 (28.5, 39.5)，"
        "外緣剛好落在整數格；倉鼠先鋪身體與頭耳的色塊，頭轉 18°，身體與頭都放在紙的下層。",
        tempo="normal")
s.look((22, 32, 13, 14), "圓章太大")
s.mod("sk_badge", note="圓章草稿縮到外半徑 6.5", stroke_opacity=0.25)
s.layer("sketch", opacity=0.5)
s.add("sheet", "path", "object", d=page_d(5.25, 4.25, 27.75, 40.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(27.75, 4.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=35.6, cy=29.5, rx=4.6, ry=7.6, fill=PEACH, stroke=INK,
      stroke_width=1.25, transform="rotate(8 35.6 29.5)", anim="fill")
hamster48(s, "hm", 36.2, 18.3, 7.0, 6.3, k=0.73, rot=18, parts=("blocks",))
s.add("badge_disc", "circle", "badge", cx=28.5, cy=39.5, r=5.75, fill=PURPLE, stroke=INK, stroke_width=1.5,
      anim="fill")
s.commit(compare=True)
