"""Batch 1 of the 24_顯示-隱藏註解 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK24, PURPLE, TEAL, WHITE, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：杏仁形大眼睛（2.5 px 框）、青綠虹膜帶深藍框與瞳孔、左上大反光；倉鼠從上眼瞼後探頭；右下紫色減號章。"
        "座標減半後眼睛內高只剩 8 格、虹膜 7–8 格，上下都貼到眼瞼；向量小圓在 24 格糊成一團。草稿試了 8 種：把眼睛加高、"
        "往下移 1 格，虹膜改逐像素最清楚。",
        "眼睛路徑兩角 x 2.75/20.25、y 14，控制點 (11.5, 2.5)/(11.5, 25.5)，1.5 px 框；虹膜 8×8 逐像素（深藍外圈、青綠、"
        "3×3 瞳孔、左上 3 格白色反光），上下各離眼瞼 1 格；倉鼠用 PEEK24 再多一列白口鼻，讓眼瞼切在口鼻那列、鼻子完整露出；"
        "減號章外半徑 4、中心 (19.5, 18.5)，白色橫槓 5×1（加號的橫臂）。",
        tempo="normal")
pixmap(s, "hm", PEEK24 + ["PPWWWWPP"], 9, 1, "hamster")
s.add("eye", "path", "object", d="M2.75 14Q11.5 2.5 20.25 14Q11.5 25.5 2.75 14Z", fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
IRIS = [
    "..NNNN..",
    ".NTTTTN.",
    "NTHHTTTN",
    "NTHNNNTN",
    "NTTNNNTN",
    "NTTNNNTN",
    ".NTTTTN.",
    "..NNNN..",
]
pixmap(s, "iris", IRIS, 7, 10, "object_fx", legend={"T": ("teal", TEAL), "N": ("ink", INK), "H": ("hl", WHITE)})
s.add("badge_disc", "circle", "badge", cx=19.5, cy=18.5, r=3.5, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
s.add("badge_minus", "path", "badge", d="M17 18h5v1h-5Z", fill=WHITE, anim="pop")
s.commit()
