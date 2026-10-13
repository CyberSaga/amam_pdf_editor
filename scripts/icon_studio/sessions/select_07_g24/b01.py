"""Batch 1 of the 07_操作物件 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, TEAL, pixmap
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
        "48 格版：白底選取框、四角 8×8 青綠控點、右下站著的倉鼠用兩隻手抱住右下控點、頭靠在框的右緣。"
        "座標減半後倉鼠頭只剩 6 格寬，放不下 2×2 的眼睛和反光；框若照比例，右下控點會蓋到倉鼠的臉頰。",
        "框線 1 px（x 2/12、y 4/15，框內白）；控點 5×5：深藍 1 px 框＋3×3 青綠，四個合成一條路徑；倉鼠用 BEAN24 加一列身體和兩隻腳"
        "（10×13），站在框右邊、和框線隔一欄白；右下控點的右框線剛好當倉鼠的左輪廓，只壓到身體、不碰臉；一隻手掌搭在控點上。",
        tempo="normal")
s.add("frame", "path", "back", d="M2.5 4.5H12.5V15.5H2.5Z", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
STAND = [
    ".NN....NN.",
    "NKKNNNNKKN",
    "NPPPPPPPPN",
    "NPHEPPHEPN",
    "NPEEWWEEPN",
    "NBWWRRWWBN",
    "NPWWWWWWSN",
    "NPPWWWWPSN",
    "NPPWWWWPSN",
    "NPPWWWWPSN",
    ".NPPPPPSN.",
    "NPPN..NPPN",
    ".NN....NN.",
]
pixmap(s, "hm", STAND, 14, 10, "hamster")
HANDLE = ["NNNNN", "NTTTN", "NTTTN", "NTTTN", "NNNNN"]
pixmap(s, "handles", stamp(24, [(x - 2, y - 2, HANDLE) for x, y in ((2, 4), (12, 4), (2, 15), (12, 15))]), 0, 0,
       "object", legend={"N": ("ink", INK), "T": ("fill", TEAL)})
pixmap(s, "paw", [".NN.", "NPPN", ".NN."], 11, 14, "front")
s.commit()
