"""Batch 1 of the 15_新增文字框 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK24, TEAL, badge_plus, pix_d, pixmap
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
s.begin(3, "24 格：從 48 格移植",
        "48 格版：白底文字框（2 px 框、三角 8×8 青綠控點）、框中央 11×14 的襯線 T、右下紫色加號章，倉鼠在左上方從框的上緣探頭、"
        "兩手扒著框。",
        "框線 1 px（x 4/19、y 7/19，框內白）；控點和操作物件 24 格同款（5×5：深藍框＋3×3 青綠），三個合成一條路徑；"
        "T 逐像素 6×7（直筆 2、兩端襯線各垂 1 格、底腳 4 格），是 48 格 T 的一半；倉鼠用 8 格寬的 PEEK24，鼻子那列剛好落在框線上方，"
        "兩格桃色手掌壓在框線上；加號章外半徑 4、中心 (19, 19)。",
        tempo="normal")
pixmap(s, "hm", PEEK24, 7, 1, "hamster")
s.add("box", "path", "object", d="M4.5 7.5H19.5V19.5H4.5Z", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
HANDLE = ["NNNNN", "NTTTN", "NTTTN", "NTTTN", "NNNNN"]
pixmap(s, "handles", stamp(24, [(x - 2, y - 2, HANDLE) for x, y in ((4, 7), (19, 7), (4, 19))]), 0, 0, "object",
       legend={"N": ("ink", INK), "T": ("fill", TEAL)})
T = ["NNNNNN", "N.NN.N", "..NN..", "..NN..", "..NN..", "..NN..", ".NNNN."]
s.add("glyph", "path", "object_fx", d=pix_d(T, "N", 9, 10), fill=INK, anim="fill")
pixmap(s, "paw", ["P......P"], 7, 7, "front")
badge_plus(s, "badge", 24, 19, 19)
s.commit()
