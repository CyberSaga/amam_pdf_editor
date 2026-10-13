"""Batch 1 of the 10_全螢幕 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE16, PURPLE_DARK, pixmap
from studio import Studio

ARROW = [  # top-left arrow: 3-px triangle head in the corner plus a 1-px diagonal shaft
    "DDD.",
    "DD..",
    "D.D.",
    "...D",
]
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：四支深紫實心的角落箭頭（L 形頭 + 2 格斜階梯），中間 8 格寬的倉鼠臉。16 格裡臉要 7×8 才放得下耳朵、反光眼睛、"
        "口鼻與腮紅，四角只剩 4×4；草稿試了實心三角頭、空心 L、加長 L 三種，實心三角頭加 1 格斜桿最像箭頭。",
        "四角各一支 4×4 深紫箭頭（3 格實心三角頭頂住角落、斜桿 1 格），用同一張圖鏡射；臉用 FACE16 放 x 4–10、y 4–11，"
        "耳朵和箭頭的斜桿末端隔 1 格。",
        tempo="normal")
for i, (mx, my) in enumerate([(False, False), (True, False), (False, True), (True, True)]):
    rows = [r[::-1] for r in ARROW] if mx else ARROW
    rows = rows[::-1] if my else rows
    pixmap(s, f"arrow{i}", rows, 12 if mx else 0, 12 if my else 0, "object", legend={"D": ("fill", PURPLE_DARK)})
pixmap(s, "hm", FACE16, 4, 4, "hamster")
s.commit()
