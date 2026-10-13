"""Batch 1 of the 10_全螢幕 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PEEK24, PURPLE_DARK, pixmap
from studio import Studio

ARROW = [  # top-left arrow: L-shaped head (2-px arms) and a 2-px staircase shaft, a 1-px notch between them
    "DDDDD..",
    "DDDDD..",
    "DD.....",
    "DD.DD..",
    "DD..DD.",
    ".....DD",
    ".......",
]
FACE = PEEK24 + [  # PEEK24 (no side outline below the ears) closed by a peach chin with shaded corners
    "SPWWWWPS",
    ".SPPPPS.",
]
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：四支深藍框的紫色角落箭頭（L 形箭頭加斜桿、圓頭），正中間一顆倉鼠頭。照比例縮成 24 格，箭頭只剩 2.5 px 粗、"
        "深藍框把紫色吃掉；草稿試了 2 px 圓頭向量線（L 的內角被斜桿填成一團）和四種像素圖，10 格寬、四周包深藍框的頭像一個盒子。",
        "箭頭改逐像素的深紫實心線、不包框（細線符號規則）：L 的兩臂 5 格長、2 格粗，2 格寬的斜階梯從 L 內角再斜下一格才開始，"
        "留 1 格缺口讓 L 形讀得出來；四支用同一張圖鏡射。臉用 PEEK24 的 8 格寬（耳朵以下不畫側框）加兩列下巴，白色口鼻包在桃色裡、"
        "下巴兩角用陰影桃色，放正中 x 8–15、y 8–15。",
        tempo="normal")
for i, (mx, my) in enumerate([(False, False), (True, False), (False, True), (True, True)]):
    rows = [r[::-1] for r in ARROW] if mx else ARROW
    rows = rows[::-1] if my else rows
    pixmap(s, f"arrow{i}", rows, 16 if mx else 1, 16 if my else 1, "object", legend={"D": ("fill", PURPLE_DARK)})
pixmap(s, "hm", FACE, 8, 8, "hamster")
s.commit()
