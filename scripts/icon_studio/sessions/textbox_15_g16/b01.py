"""Batch 1 of the 15_新增文字框 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, TEAL_DARK, badge_plus, pix_d, pixmap
from studio import Studio


def stamp(size, stamps):
    """One canvas-sized pixel map from (x, y, rows) stamps ('.' stays empty)."""
    grid = [["."] * size for _ in range(size)]
    for x, y, rows in stamps:
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch != ".":
                    grid[y + r][x + c] = ch
    return ["".join(row) for row in grid]


s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：白底文字框、5×5 控點、6×7 的 T、右下加號章、左上方從框上緣探頭的倉鼠。",
        "框線 1 px（x 2/13、y 5/13）；控點和操作物件 16 格同款（3×3 實心深青綠）；T 縮成 5×5（直筆 1、襯線 1 格、底腳 3 格）放框內偏左，"
        "讓開加號章；倉鼠用 16 格五列探頭臉，放在框上方偏左、和左上控點錯開；加號章外半徑 3.5、中心 (12.5, 12.5)。",
        tempo="normal")
pixmap(s, "hm", PEEK16, 4, 0, "hamster")
s.add("box", "path", "object", d="M2.5 5.5H13.5V13.5H2.5Z", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
pixmap(s, "handles", stamp(16, [(x - 1, y - 1, ["DDD"] * 3) for x, y in ((2, 5), (13, 5), (2, 13))]), 0, 0,
       "object", legend={"D": ("fill", TEAL_DARK)})
T = ["NNNNN", "N.N.N", "..N..", "..N..", ".NNN."]
s.add("glyph", "path", "object_fx", d=pix_d(T, "N", 5, 7), fill=INK, anim="fill")
badge_plus(s, "badge", 16, 12.5, 12.5)
s.commit()
