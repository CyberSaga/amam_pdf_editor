"""Batch 1 of the 14_編輯文字 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE16, INK, PURPLE_DARK, WHITE, pix_d, pixmap
from studio import Studio


def halo(rows, x0, y0, size):
    """1-px ring (8-neighbour) around a pixel map, as a canvas-sized map of 'W'."""
    pts = {(x0 + c, y0 + r) for r, row in enumerate(rows) for c, ch in enumerate(row) if ch != "."}
    ring = {(x + dx, y + dy) for x, y in pts for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - pts
    grid = [["."] * size for _ in range(size)]
    for x, y in ring:
        if 0 <= x < size and 0 <= y < size:
            grid[y][x] = "W"
    return ["".join(row) for row in grid]


s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：11×14 的逐像素襯線 T（白邊 1 格）、深紫游標、右下 BEAN24 倉鼠握住游標。16 格寬度只夠 T＋一欄空白＋游標＋7 格的臉。",
        "T 8×10（直筆 2、橫筆 1、襯線下垂 2 列、底腳 6 格加托），白邊保留；游標第 9 欄、從 T 頂到第 13 列；倉鼠用 16 格的臉"
        "（無側邊框）放右下，游標壓過臉的最左一欄，游標尾端下面露出的一格桃色就像握著游標的手。",
        tempo="normal")
T = [
    "NNNNNNNN",
    "NN.NN.NN",
    "N..NN..N",
    "...NN...",
    "...NN...",
    "...NN...",
    "...NN...",
    "...NN...",
    "..NNNN..",
    ".NNNNNN.",
]
s.add("glyph_halo", "path", "back", d=pix_d(halo(T, 0, 1, 16), "W"), fill=WHITE, anim="fill")
s.add("glyph", "path", "object", d=pix_d(T, "N", 0, 1), fill=INK, anim="fill")
pixmap(s, "hm", FACE16, 9, 8, "hamster")
s.add("cursor", "path", "object_fx", d="M9 1h1v13h-1Z", fill=PURPLE_DARK, anim="draw")
s.commit()
