"""Batch 1 of the 14_編輯文字 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import BEAN24, INK, PURPLE_DARK, WHITE, pix_d, pixmap
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
s.begin(3, "24 格：從 48 格移植",
        "48 格版：22×28 的襯線 T 帶 1 格白邊、2 px 紫色游標、坐在游標右邊的倉鼠伸手握住游標下段。"
        "座標減半後 T 的橫筆只剩 1 格、襯線圓弧變成階梯；游標 1 px 的淡紫在白底上太淡。",
        "T 逐像素 11×14（直筆 3、橫筆 1、兩端襯線下垂 4 列並做出圓弧的階梯、底腳 7 格加 1 格托），貼左邊放；白邊照 48 格保留"
        "（四周 1 格）；游標改 1 px 深紫（細線規則）、第 12 欄；倉鼠用 BEAN24 放右下，和游標隔一欄白；一隻手掌包住游標下段，"
        "游標尾端從手下露出一格。",
        tempo="normal")
T = [
    "NNNNNNNNNNN",
    "NN..NNN..NN",
    "N...NNN...N",
    "N...NNN...N",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "....NNN....",
    "...NNNNN...",
    "..NNNNNNN..",
]
s.add("glyph_halo", "path", "back", d=pix_d(halo(T, 0, 2, 24), "W"), fill=WHITE, anim="fill")
s.add("glyph", "path", "object", d=pix_d(T, "N", 0, 2), fill=INK, anim="fill")
s.add("cursor", "path", "object_fx", d="M12 2h1v18h-1Z", fill=PURPLE_DARK, anim="draw")
pixmap(s, "hm", BEAN24, 14, 12, "hamster")
pixmap(s, "paw", [".NN.", "NPPN", ".NN."], 11, 16, "front")
s.commit()
