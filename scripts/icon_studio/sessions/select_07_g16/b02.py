"""Batch 2 of the 07_操作物件 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import pix_d
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
s.begin(6, "16 格：左耳離開框線",
        "放大看：框的右緣（第 9 欄）在第 3–6 列露出來，緊貼倉鼠左耳的深藍（第 10 欄），耳朵和框線黏成一塊；"
        "第 7 列以下框線又被倉鼠蓋住，右緣忽隱忽現。",
        "框的右緣左移一欄到第 8 欄，右上、右下控點跟著移；倉鼠左耳和框線之間空出一欄白，框線整條都看得到，"
        "右下控點仍只壓到倉鼠的身體。",
        tempo="normal")
s.look((7, 3, 6, 5), "左耳黏到框線")
s.mod("frame", note="右緣左移一欄", d="M1.5 2.5H8.5V11.5H1.5Z")
rows = stamp(16, [(x - 1, y - 1, ["DDD"] * 3) for x, y in ((1, 2), (8, 2), (1, 11), (8, 11))])
s.mod("handles_fill", note="右側兩個控點跟著移", d=pix_d(rows, "D"))
s.commit()
