"""Batch 1 of the 09_重做 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE16, INK, PURPLE, WHITE, pixmap
from studio import Studio

UNDO16 = [  # the 08_復原 16 px arrow (pixel map, rows 4-14 there)
    "....NN..........",
    "...NUN..........",
    "..NUUNNNNNNNN...",
    ".NUUUUUUUUUUUN..",
    ".NUUUUUUUUUUUUN.",
    "..NUUNNNNNNUUUN.",
    "...NUN....NNUUN.",
    "....NN.....NUUN.",
    "..........NUUN..",
    ".........NUUN...",
    ".........NNN....",
]
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：鏡射的彎箭頭在上、倉鼠豆子縮在鉤口下方。16 格的箭頭有 11 列、臉要 7 列，兩者只能疊 2 列："
        "草稿試了臉放進鉤口（耳朵和箭頭頭部下角、鉤的內緣黏成一條黑帶）、臉蓋住尾巴（左耳和尾巴尖連成一團），都不乾淨。",
        "箭頭照復原 16 格的像素圖左右鏡射、上移 4 列（頂端貼齊第 0 列，和旋轉頁、最佳化的 16 格一樣），白光同樣鏡射；"
        "臉用 FACE16 的前 7 列放 x 7–13、y 9–15：右耳和箭頭頭部下角隔一列，鉤的尾巴尖停在臉的左上角外一格，像把倉鼠圈在彎裡。",
        tempo="normal")
pixmap(s, "arrow", [r[::-1] for r in UNDO16], 0, 0, "object", legend={"U": ("fill", PURPLE), "N": ("ink", INK)})
pixmap(s, "hm", FACE16[:7], 7, 9, "hamster")
s.add("arrow_gloss", "path", "glint", d="M6 3h4v1h-4Z", fill=WHITE, fill_opacity=0.5, anim="pop")
s.commit()
