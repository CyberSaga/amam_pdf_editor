"""Batch 1 of the 17_螢光筆 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import BLUSH, EAR_IN, INK, NOSE, PEACH, WHITE, YELLOW, pixmap
from studio import Studio

COLLAR = "#6C6E9E"
GLOSS = "#FFF1BF"  # light yellow: the 48's white gloss over the yellow barrel
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：斜放的黃色螢光筆（筆身 2.5 px 框、灰藍筆夾、黃筆尖），倉鼠頭在筆的上端、兩隻手抱住筆身，筆尖落在一道黃色筆痕上。"
        "座標減半後斜邊全是半格，向量畫出來糊成鋸齒；草稿逐像素試了 7 版：倉鼠頭擋在筆頭前面、下巴畫一條框線時像戴面罩的方頭貓，"
        "改成倉鼠躲在筆後面、斜切的筆頭橫過胸口，兩隻手搭在筆頭兩個角上最像抱著筆。",
        "整張逐像素：倉鼠用 BEAN24 的臉（耳朵到口鼻）放 x 4–13；筆身每列 8 格（框 + 黃 + 右緣一排淡黃反光），每兩列往右移一格，"
        "筆頭斜邊照 2:1 階梯；筆夾 3 列灰藍、筆尖 2 格黃色，最後一列壓進筆痕；筆痕兩列黃色 x 5–19；左手 3 格、右手 2 格。",
        tempo="normal")
MAP = [
    "........................",
    ".....NN....NN...........",
    "....NKKNNNNKKN..........",
    "....NPPPPPPPPN..........",
    "....NPHNPPHNPN..........",
    "....NPNNWWNNPN..........",
    "....NBWWRRWWBNN.........",
    "....NPWWWWWWNPPN........",
    "....NPPWWWNNYNN.........",
    "...NNNPWNNYYYLN.........",
    "..NPPPNNYYYYYLN.........",
    "...NNNNYYYYYYLN.........",
    "........NYYYYYLN........",
    ".........NYYYYYLN.......",
    ".........NYYYYYLN.......",
    "..........NYYYYNNN......",
    "..........NYYNNCCN......",
    "...........NNCCCCN......",
    "...........NCCCCNN......",
    "............NNNNN.......",
    ".............NYYN.......",
    "......yyyyyyyNYYNyy.....",
    ".....yyyyyyyyyNNyyyy....",
    "........................",
]
pixmap(s, "hl", MAP, 0, 0, "object", legend={
    "y": ("band", YELLOW), "Y": ("barrel", YELLOW), "L": ("gloss", GLOSS), "C": ("collar", COLLAR),
    "P": ("peach", PEACH), "W": ("muzzle", WHITE), "N": ("ink", INK), "K": ("ears_in", EAR_IN),
    "H": ("eyes_hl", WHITE), "B": ("blush", BLUSH), "R": ("nose", NOSE)})
s.commit()
