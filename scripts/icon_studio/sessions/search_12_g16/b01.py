"""Batch 1 of the 12_搜尋 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAPER, PURPLE_DARK, pixmap
from studio import Studio

CX = CY = 7
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：深藍 + 紫灰 + 深藍的 3.5 px 鏡框、9 格寬的正面倉鼠臉、深藍細頸與圓頭握柄。16 格若照抄三層鏡框，開口只剩 5 格，"
        "臉放不下；草稿裡試了五種：2 px 深紫實心鏡框、圓心 (7, 7)、外緣半徑 6 時開口 8 格，臉最清楚。",
        "鏡框改成 2 px 深紫實心環（3 px 以下的線狀符號不包深藍邊），外緣落在 x/y 1 與 13；握柄 3 px 深紫、圓頭，斜到 (15.8, 15.8)；"
        "臉 8×6 逐像素：耳蓋、粉耳、2×2 眼睛帶反光、白口鼻、2 格鼻子、腮紅、一列下巴，左右與下緣由鏡框當輪廓。",
        tempo="normal")
s.add("glass", "circle", "back", cx=CX, cy=CY, r=4.5, fill=PAPER, anim="fill")
FACE = [
    ".NN..NN.",
    ".KKPPKK.",
    "PHEPPHEP",
    "PEEWWEEP",
    "BWWRRWWB",
    ".PWWWWP.",
]
pixmap(s, "hm", FACE, 3, 4, "hamster")
s.add("handle", "path", "object", d="M12 7H17.9", fill="none", stroke=PURPLE_DARK, stroke_width=3, stroke_linecap="round",
      transform=f"rotate(45 {CX} {CY})", anim="draw")
s.add("ring", "circle", "object", cx=CX, cy=CY, r=5, fill="none", stroke=PURPLE_DARK, stroke_width=2, anim="draw")
s.commit()
