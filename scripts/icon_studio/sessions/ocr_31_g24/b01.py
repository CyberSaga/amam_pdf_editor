"""Batch 1 of the 31_OCR（文字辨識） 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEEK16, TEAL, TEAL_DARK, WHITE, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：青綠掃描器（出光縫 + 反光）、單一半透明光束、四角深藍 L 框、從掃描線後探頭的倉鼠、大襯線 T。"
        "草稿裡先用 PEEK24（8×6）的臉，臉和 T 一樣大、顏色又多，20–24 px 看起來倉鼠比 T 搶眼；48 格的臉縮半正好是 7×5。",
        "整組以 x 12.5 為中線（奇數寬）：掃描器 15×4 逐像素（深藍框、青綠、左上 3 格白反光、一列深青綠出光縫）；"
        "光束從 y 4.5 的 x 9–16 張到 y 22.5 的 x 4.5–20.5，0.3 透明 + 1 px 青綠邊；臉用 16 格的五列（耳蓋、粉耳、2×2 眼睛帶反光、"
        "白口鼻與鼻子），坐在一列深青綠掃描線上，手掌各 2 格；T 11×9：兩列橫畫、兩端襯線、3 格直畫、7 格腳；四角 3 格 L 框。",
        tempo="normal")
s.add("beam", "path", "back", d="M9 4.5L4.5 22.5H20.5L16 4.5Z", fill=TEAL, fill_opacity=0.3, anim="fill")
s.add("beam_edges", "path", "back", d="M9.5 4.5L5 22.5M15.5 4.5L20 22.5", fill="none", stroke=TEAL, stroke_width=1, anim="draw")
pixmap(s, "hm", PEEK16, 9, 6, "hamster")
s.add("scan_line", "path", "object", d="M7 11H18V12H7Z", fill=TEAL_DARK, anim="fill")
pixmap(s, "paw", ["PP.....PP"], 8, 11, "front")
L = ["NNN", "N..", "N.."]
grid = [["."] * 21 for _ in range(17)]
for rows, x, y in ((L, 0, 0), ([r[::-1] for r in L], 18, 0), (L[::-1], 0, 14), ([r[::-1] for r in L[::-1]], 18, 14)):
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "N":
                grid[y + j][x + i] = "N"
pixmap(s, "corner", ["".join(r) for r in grid], 2, 6, "object", legend={"N": ("ink", INK)})
LETTER_T = [
    "NNNNNNNNNNN",
    "NNNNNNNNNNN",
    "N...NNN...N",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "..NNNNNNN..",
]
pixmap(s, "letter_t", LETTER_T, 7, 13, "object", legend={"N": ("ink", INK)})
SCANNER = [
    ".NNNNNNNNNNNNN.",
    "NTWWWTTTTTTTTTN",
    "NTDDDDDDDDDDDTN",
    ".NNNNNNNNNNNNN.",
]
pixmap(s, "scanner", SCANNER, 5, 1, "front", legend={"T": ("teal", TEAL), "W": ("gloss", WHITE), "D": ("slit", TEAL_DARK),
                                                      "N": ("ink", INK)})
s.commit()
