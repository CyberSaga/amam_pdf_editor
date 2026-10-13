"""Batch 1 of the 13_快照 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK24, PURPLE_DARK, TEAL, pix_d, pixmap
from studio import Studio

LENS = "#3B3D6B"
BAND = "#DCDAEC"
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版定稿：紫芯深藍邊的取景框角、凸起的白色相機（左上小按鈕、下半淡紫）、白環深藍鏡片帶青綠反光、從凸起後探頭的倉鼠。"
        "減半後凸起只剩 2 列、斜邊全是半格灰，按鈕和凸起黏成一團深藍；草稿改了三次：凸起改成直邊、3 列高、10 格寬，"
        "機身下移 1 列，鏡頭 7×7 才能上下各留 1 格白。",
        "機身外緣 x 4–21、y 9–22（1.5 px），凸起 x 8–18、頂 y 6；按鈕 2×2（深藍頂＋深紫）放 x 5–6，和凸起隔 1 欄；"
        "鏡頭逐像素：深藍環、白環、3×3 深藍鏡片、左上 1 格青綠反光；機身第 14 列以下淡紫；取景框角改 1 px 深紫 L（3 px 以下的線不包邊）、"
        "臂長 4 格貼在四角；倉鼠 PEEK24 在第 0–5 列，手掌各 1 格壓在凸起頂上。",
        tempo="normal")
L = ["DDDD", "D...", "D...", "D..."]
corners = [(L, 0, 1), ([r[::-1] for r in L], 20, 1), (L[::-1], 0, 20), ([r[::-1] for r in L[::-1]], 20, 20)]
s.add("brackets", "path", "back", d="".join(pix_d(rows, "D", x, y) for rows, x, y in corners), fill=PURPLE_DARK,
      anim="draw")
pixmap(s, "button", ["NN", "DD"], 5, 7, "back", legend={"D": ("fill", PURPLE_DARK), "N": ("ink", INK)})
pixmap(s, "hm", PEEK24, 9, 0, "hamster")
s.add("cam", "path", "object", d="M4.75 11.25A1.5 1.5 0 0 1 6.25 9.75H8.75V7.75Q8.75 6.75 9.75 6.75H16.25Q17.25 6.75 "
      "17.25 7.75V9.75H18.75A1.5 1.5 0 0 1 20.25 11.25V19.75A1.5 1.5 0 0 1 18.75 21.25H6.25A1.5 1.5 0 0 1 4.75 19.75Z",
      fill=PAPER, stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("band", "path", "object", d="M5.5 14H19.5V19.5Q19.5 20.5 18.5 20.5H6.5Q5.5 20.5 5.5 19.5Z", fill=BAND, anim="fill")
LENS7 = [
    "..NNN..",
    ".NWWWN.",
    "NWGLLWN",
    "NWLLLWN",
    "NWLLLWN",
    ".NWWWN.",
    "..NNN..",
]
pixmap(s, "lens", LENS7, 9, 12, "object_fx", legend={"W": ("white", PAPER), "L": ("glass", LENS), "G": ("glint", TEAL),
                                                      "N": ("ink", INK)})
pixmap(s, "paw", ["P......P"], 9, 6, "front")
s.commit()
