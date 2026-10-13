"""Batch 1 of the 19_插入圖片 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PEEK16, PURPLE, TEAL, TEAL_DARK, WHITE, YELLOW, pixmap, plus_px_d
from studio import Studio

SKY = "#BFE0F5"
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：1.5 px 相框、1 格白邊、13×13 逐像素風景（平頂左山、尖頂右山、右上太陽）、下框探頭的倉鼠、加號章。16 格的畫面只剩"
        "10×10，倉鼠臉就佔了下半；白邊放不下。草稿試了四種：十字形的 3×3 太陽看起來像加號，3×3 太陽塞不進角落；圓章貼著倉鼠的腮紅，"
        "整個相框要往左移 1 格才隔得開。",
        "相框外緣 x 0–12、y 1–13（1 px），不留白邊；風景 10×10：左山 2 格平頂、右山 1 格尖頂，稜線離耳朵 1 列，太陽 2×2 放右上角；"
        "倉鼠 PEEK16 放 x 1–7、第 7–11 列，左邊由相框當輪廓；加號章外半徑 3.5、中心 (12.5, 12.5)，和倉鼠之間留 1 欄青綠。",
        tempo="normal")
s.add("frame", "path", "object", d=rrect_d(0.5, 1.5, 11.5, 12.5, 1.0), fill="none", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="draw")
LAND = [
    "SSSSSSSSYY",
    "SSSDDSSSYY",
    "SSDTTDSSSS",
    "SDTTTTDSDS",
    "STTTTTTDTD",
    "TTTTTTTTTT",
    "TTTTTTTTTT",
    "TTTTTTTTTT",
    "TTTTTTTTTT",
    "TTTTTTTTTT",
]
pixmap(s, "land", LAND, 1, 2, "back", legend={"S": ("sky", SKY), "T": ("hill", TEAL), "D": ("ridge", TEAL_DARK),
                                               "Y": ("sun", YELLOW)})
pixmap(s, "hm", PEEK16, 1, 7, "hamster")
s.add("badge_disc", "circle", "badge", cx=12.5, cy=12.5, r=3, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
s.add("badge_plus", "path", "badge", d=plus_px_d(12, 12, 2), fill=WHITE, anim="pop")
s.commit()
