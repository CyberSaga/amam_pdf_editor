"""Batch 1 of the 19_插入圖片 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, PEEK24, PURPLE, TEAL, TEAL_DARK, WHITE, YELLOW, YELLOW_DARK, pixmap, plus_px_d
from studio import Studio

SKY = "#BFE0F5"
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版定稿：深藍相框、白邊、天空＋太陽＋兩座圓頂山、從下框探頭的倉鼠、右下加號章。減半後畫面 13×13，倉鼠 PEEK24 的耳朵"
        "在畫面高度 62% 處，正好是山谷的高度——稜線會頂到右耳；草稿試了五種逐像素風景，稜線整體上移 2 列、保留「左山高、右山矮」"
        "的比例時最像 48 格，太陽因此移到右上角。",
        "相框外緣 x 1–20、y 2–21（1.5 px），白邊 1 格，畫面 x 4–16、y 5–17；風景逐像素：左山平頂、右山尖頂、稜線深青綠 1 px、"
        "山谷在第 11 列（耳朵在第 13 列，中間留 1 列青綠），太陽 3×3（四角深黃）；倉鼠 PEEK24 在第 13–18 列、手掌壓在下框內緣；"
        "加號章外半徑 4、中心 (18.5, 18.5)。",
        tempo="normal")
s.add("mat", "path", "back", d=rrect_d(1.75, 2.75, 19.25, 20.25, 1.5), fill=PAPER, anim="fill")
LAND = [
    "SSSSSSSSSSdYd",
    "SSSSSSSSSSYYY",
    "SSSDDSSSSSdYd",
    "SSDTTDSSSSSSS",
    "SDTTTTDSSSDSS",
    "DTTTTTTDSDTDS",
    "TTTTTTTTDTTTD",
    "TTTTTTTTTTTTT",
    "TTTTTTTTTTTTT",
    "TTTTTTTTTTTTT",
    "TTTTTTTTTTTTT",
    "TTTTTTTTTTTTT",
    "TTTTTTTTTTTTT",
]
pixmap(s, "land", LAND, 4, 5, "back", legend={"S": ("sky", SKY), "T": ("hill", TEAL), "D": ("ridge", TEAL_DARK),
                                               "Y": ("sun", YELLOW), "d": ("sun_rim", YELLOW_DARK)})
pixmap(s, "hm", PEEK24, 5, 13, "hamster")
s.add("frame", "path", "object", d=rrect_d(1.75, 2.75, 19.25, 20.25, 1.5), fill="none", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="draw")
pixmap(s, "paw", ["P......P"], 5, 19, "front")
s.add("badge_disc", "circle", "badge", cx=18.5, cy=18.5, r=3.5, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
s.add("badge_plus", "path", "badge", d=plus_px_d(18, 18, 2), fill=WHITE, anim="pop")
s.commit()
