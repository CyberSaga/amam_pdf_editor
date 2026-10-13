"""Batch 1 of the 08_復原 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEEK16, PURPLE, WHITE, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：1.5 px 深藍框的紫色彎箭頭、鉤身 2–3 格紫色、上緣一道白光，PEEK24 的臉趴在箭頭上緣。"
        "草稿先用向量畫 16 格：頭部斜邊和鉤全是灰色鋸齒，鉤的紫色只剩 1 格，糊成一團。",
        "箭頭改逐像素：桿子三列（深藍、紫 2 列、深藍），頭部 6×8 的斜階梯、尖端 2 格；鉤往右再往下、往左捲，紫色保持 2 格寬，"
        "尾端收在第 14 列；上排紫色左段 4 格疊 50% 白光；臉用 PEEK16（7×5）放 x 6–12，鼻子那列貼著箭頭上緣，左側由箭頭頭部的角當輪廓。"
        "16 格不畫手（試過：臉看起來被拉長、上緣斷掉）。",
        tempo="normal")
ARROW = [
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
pixmap(s, "arrow", ARROW, 0, 4, "object", legend={"U": ("fill", PURPLE), "N": ("ink", INK)})
pixmap(s, "hm", PEEK16, 6, 1, "hamster")
s.add("arrow_gloss", "path", "glint", d="M6 7h4v1h-4Z", fill=WHITE, fill_opacity=0.5, anim="pop")
s.commit()
