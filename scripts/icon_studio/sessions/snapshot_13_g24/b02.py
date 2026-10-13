"""Batch 2 of the 13_快照 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import LEGEND, PEEK24, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：鏡頭放大成 8×8",
        "24–32 px 看：鏡頭只有 7×7、佔機身高度 54%（48 格是 70%），深藍鏡片只剩 3×3，像一顆鈕扣；而且 7 格寬的鏡頭讓整台相機"
        "中線落在 12.5、倉鼠在 13，左右各歪半格。鏡頭正上方是凸起的內部，沒有機身上緣，可以往上長。",
        "鏡頭改 8×8（深藍環、白環、4×4 鏡片、左上青綠反光）放 x 8–15、y 11–18，下面仍留 1 格白；機身放寬到 x 3–21、凸起改 x 7–17，"
        "倉鼠移到 x 8–15，全部對齊中線 12；按鈕跟著左移 1 格，和凸起之間仍隔 1 欄。試過十字形鏡片，看起來像加號，不用。",
        tempo="normal")
s.look((7, 11, 10, 9), "鏡頭太小、整體歪半格")
s.mod("cam", note="機身放寬、凸起置中",
      d="M3.75 11.25A1.5 1.5 0 0 1 5.25 9.75H7.75V7.75Q7.75 6.75 8.75 6.75H15.25Q16.25 6.75 16.25 7.75V9.75H18.75A1.5 "
        "1.5 0 0 1 20.25 11.25V19.75A1.5 1.5 0 0 1 18.75 21.25H5.25A1.5 1.5 0 0 1 3.75 19.75Z")
s.mod("band", d="M4.5 14H19.5V19.5Q19.5 20.5 18.5 20.5H5.5Q4.5 20.5 4.5 19.5Z")
LENS8 = [
    "..NNNN..",
    ".NWWWWN.",
    "NWGLLLWN",
    "NWLLLLWN",
    "NWLLLLWN",
    "NWLLLLWN",
    ".NWWWWN.",
    "..NNNN..",
]
for ch, suffix in (("W", "white"), ("L", "glass"), ("G", "glint"), ("N", "ink")):
    s.mod(f"lens_{suffix}", note="鏡頭 7×7 → 8×8" if ch == "W" else None, d=pix_d(LENS8, ch, 8, 11))
for ch, (suffix, _color) in LEGEND.items():
    if f"hm_{suffix}" in s.elements:
        s.mod(f"hm_{suffix}", note="倉鼠左移 1 格對齊中線" if suffix == "peach" else None, d=pix_d(PEEK24, ch, 8, 0))
s.mod("paw_peach", d=pix_d(["P......P"], "P", 8, 6))
s.mod("button_ink", note="按鈕左移 1 格", d=pix_d(["NN", "DD"], "N", 4, 7))
s.mod("button_fill", d=pix_d(["NN", "DD"], "D", 4, 7))
s.commit()
