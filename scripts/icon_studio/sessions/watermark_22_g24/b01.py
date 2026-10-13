"""Batch 1 of the 22_添加浮水印 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE24, INK, PAPER, PURPLE, PURPLE_DARK, badge_plus, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：紙上緣探頭的大臉倉鼠抓著紫色印章、紙中淡紫水滴、右下加號章。",
        "紙外緣 x 4/19、y 7/23；臉用 FACE24 放在紙上緣後面；印章逐像素（圓鈕 3 格、底座 9 格，深藍框）壓在紙緣；"
        "水滴 4×6 淡紫、1 px 紫框；加號章中心 (17.5, 19.5)。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(4.75, 7.75, 18.25, 22.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(18.25, 7.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", FACE24, 5, 1, "hamster")
STAMP = [
    "..PNNNP..",
    "...NUN...",
    "NNNNNNNNN",
    "NUUUUUUUN",
    "NDDDDDDDN",
    "NNNNNNNNN",
]
pixmap(s, "stamp", STAMP, 5, 6, "front", legend={"P": ("paws", "#F6C58E"), "U": ("body", PURPLE),
                                                  "D": ("rim", PURPLE_DARK), "N": ("ink", INK)})
s.add("drop", "path", "object_fx", d="M10.5 13.5C11.2 14.8 13 16.2 13 17.7A2.5 2.5 0 0 1 8 17.7C8 16.2 9.8 14.8 10.5 13.5Z",
      fill="#CBC4EF", stroke="#8F86CF", stroke_width=1, stroke_linejoin="round", anim="fill")
badge_plus(s, "badge", 24, 17.5, 19.5)
s.commit()
