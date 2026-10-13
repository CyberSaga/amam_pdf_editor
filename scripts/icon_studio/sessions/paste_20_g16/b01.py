"""Batch 1 of the 20_貼上圖片 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import (BLUSH, EAR_IN, INK, NOSE, PAPER, PEACH, PURPLE, PURPLE_LIGHT, TEAL, TEAL_DARK, WHITE, YELLOW,
                   pixmap)
from studio import Studio

SKY = "#BFE0F5"
BOARD = "#CF8F55"
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：棕色寫字板（2.5 格棕邊）、白紙、8×8 風景、上窄下寬的夾板、探頭的倉鼠和兩隻手掌。16 格由上往下排：臉 5 列、夾板 3 列、"
        "棕邊 1 格、白紙留邊，風景只剩 7×5；元素上限 16 個，倉鼠、手掌和夾板合成一張像素圖（同色像素併成一條路徑）。夾板試了兩種："
        "上下都描深藍時紫色只剩 1 列、像一條黑槓；上緣改由倉鼠的白色口鼻那列來分界，紫色有 2 列，才看得出是夾子。",
        "寫字板外緣 x 1–14、y 6–16（1 px），棕邊 1 格，白紙 x 3–12、y 7–14；風景 7×5（x 4–10、y 8–12）照 24 格縮小："
        "左山平頂、右山尖頂、右上 2×2 太陽；夾板 7×3：紫色 2 列（左上 2 格淡紫光澤）＋深藍下緣與兩側；臉用 PEEK16，"
        "手掌各 1 格在夾板上角兩側。",
        tempo="normal")
s.add("board", "path", "object", d=rrect_d(1.5, 6.5, 13.5, 15.5, 1.0), fill=BOARD, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("paper", "path", "object", d="M3 7H12V14H3Z", fill=PAPER, anim="fill")
LAND = [
    "SSSSSYY",
    "SDDSSYY",
    "DTTDSSS",
    "TTTTDSD",
    "TTTTTDT",
]
pixmap(s, "land", LAND, 4, 8, "object_fx", legend={"S": ("sky", SKY), "T": ("hill", TEAL), "D": ("ridge", TEAL_DARK),
                                                    "Y": ("sun", YELLOW)})
TOP = [  # PEEK16 (eyes merged into the navy, catchlights into the white) + paws + clip
    ".NN.NN.",
    ".KKPKK.",
    "PWNPWNP",
    "PNNPNNP",
    "BWWRWWB",
    "PLLCCCP",
    "NCCCCCN",
    "NNNNNNN",
]
pixmap(s, "top", TOP, 4, 0, "front", legend={"P": ("peach", PEACH), "W": ("white", WHITE), "N": ("ink", INK),
                                              "K": ("ears_in", EAR_IN), "B": ("blush", BLUSH), "R": ("nose", NOSE),
                                              "C": ("clip", PURPLE), "L": ("clip_gloss", PURPLE_LIGHT)})
s.commit()
