"""Batch 1 of the 07_操作物件 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, TEAL_DARK, pixmap
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
        "24 格版：白底選取框、5×5 控點（深藍框＋3×3 青綠）、右邊站著的倉鼠搭著右下控點。16 格的控點只剩 3×3："
        "試過深藍框中間 1 格青綠，1× 看像四顆黑點；整塊 3×3 深青綠在淺、深兩種底上都讀得出是控點。",
        "框線 1 px（x 1/9、y 2/11，框內白）；控點 3×3 實心深青綠（小於 4 格的實心形狀不包深藍邊），四個合成一條路徑；"
        "倉鼠用 16 格的臉加長身體與兩隻腳（7×9），站在右邊、蓋住框的右緣，右下控點只壓到身體。",
        tempo="normal")
s.add("frame", "path", "back", d="M1.5 2.5H9.5V11.5H1.5Z", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
STAND = [
    ".NN.NN.",
    ".KKPKK.",
    "PHEPHEP",
    "PEEPEEP",
    "BWWRWWB",
    "PPWWWPP",
    "PPWWWPP",
    "PPPPPPP",
    ".PP.PP.",
]
pixmap(s, "hm", STAND, 9, 5, "hamster")
pixmap(s, "handles", stamp(16, [(x - 1, y - 1, ["DDD"] * 3) for x, y in ((1, 2), (9, 2), (1, 11), (9, 11))]), 0, 0,
       "object", legend={"D": ("fill", TEAL_DARK)})
s.commit()
