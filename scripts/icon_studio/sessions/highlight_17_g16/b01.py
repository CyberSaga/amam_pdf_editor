"""Batch 1 of the 17_螢光筆 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import BLUSH, EAR_IN, INK, NOSE, PEACH, WHITE, YELLOW, pixmap
from studio import Studio

COLLAR = "#6C6E9E"
GLOSS = "#FFF1BF"
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：倉鼠躲在斜放的螢光筆後面、筆頭斜切過胸口、兩手搭在筆頭兩角；筆身 8 格寬帶淡黃反光、灰藍筆夾、黃筆尖、兩列筆痕。"
        "16 格裡筆身只剩 6 格寬；草稿試了 6 版：左手畫框線時和筆身左緣、下巴擠成一團深藍。",
        "倉鼠臉用 16 格版（7×8 去掉最下一列）放 x 1–7；筆身每列 6 格（框 + 3 黃 + 1 淡黃 + 框），每兩列右移一格，筆頭斜邊照 2:1 "
        "從倉鼠胸口切過；左手只留兩格桃色貼在筆身左緣、不畫框；筆夾 3 格灰藍、筆尖 1 格黃，壓進最下面兩列的筆痕（x 2–13）。",
        tempo="normal")
MAP = [
    "..NN.NN.........",
    "..KKPKK.........",
    ".PHNPHNP........",
    ".PNNPNNP........",
    ".BWWRWWNN.......",
    ".PPWWNNYLN......",
    ".PPPNYYYLN......",
    "..PPNYYYYLN.....",
    "....NNYYYLN.....",
    ".....NYYYYLN....",
    "......NYYYLN....",
    ".......NYNNN....",
    ".......NNCCN....",
    "........NCNN....",
    "...yyyyyyNYNyy..",
    "..yyyyyyyyNyyy..",
]
pixmap(s, "hl", MAP, 0, 0, "object", legend={
    "y": ("band", YELLOW), "Y": ("barrel", YELLOW), "L": ("gloss", GLOSS), "C": ("collar", COLLAR),
    "P": ("peach", PEACH), "W": ("muzzle", WHITE), "N": ("ink", INK), "K": ("ears_in", EAR_IN),
    "H": ("eyes_hl", WHITE), "B": ("blush", BLUSH), "R": ("nose", NOSE)})
s.commit()
