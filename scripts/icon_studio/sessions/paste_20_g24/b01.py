"""Batch 1 of the 20_貼上圖片 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, PEEK24, PURPLE, PURPLE_LIGHT, TEAL, TEAL_DARK, YELLOW, pixmap
from studio import Studio

SKY = "#BFE0F5"
BOARD = "#CF8F55"
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版定稿：2.5 px 深藍框的棕色寫字板、白紙、淡紫框小風景圖、上窄下寬的紫色夾板、從夾板上緣探頭的倉鼠。減半後小圖只剩 8×8，"
        "淡紫框再吃掉一圈、風景剩 6×6，在 24–32 px 只看得到一塊青綠；草稿比較後拿掉淡紫框，讓風景 8×8 直接貼在白紙上，山和太陽才讀得出來。",
        "寫字板外緣 x 3–21、y 7–23（1.5 px），棕色邊 2.5 格；白紙 x 7–17、y 9–20；風景 8×8（x 8–15、y 11–18）照插入圖片 16 格版的"
        "構成縮小：左山平頂、右山尖頂、右上 2×2 太陽；夾板 10×4 逐像素：上排窄、下排寬（同 48 格的梯形），左上 2 格淡紫光澤；"
        "倉鼠 PEEK24 在第 0–5 列，兩隻手掌各 1 格壓在夾板上角。",
        tempo="normal")
pixmap(s, "hm", PEEK24, 8, 0, "hamster")
s.add("board", "path", "object", d=rrect_d(3.75, 7.75, 20.25, 22.25, 1.5), fill=BOARD, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("paper", "path", "object", d=rrect_d(7, 9, 17, 20, 0.5), fill=PAPER, anim="fill")
LAND = [
    "SSSSSSYY",
    "SSSSSSYY",
    "SSDDSSSS",
    "SDTTDSSS",
    "DTTTTDSD",
    "TTTTTTDT",
    "TTTTTTTT",
    "TTTTTTTT",
]
pixmap(s, "land", LAND, 8, 11, "object_fx", legend={"S": ("sky", SKY), "T": ("hill", TEAL), "D": ("ridge", TEAL_DARK),
                                                     "Y": ("sun", YELLOW)})
CLIP = [
    ".NNNNNNNN.",
    "NPLLPPPPPN",
    "NPPPPPPPPN",
    "NNNNNNNNNN",
]
pixmap(s, "clip", CLIP, 7, 6, "front", legend={"P": ("fill", PURPLE), "L": ("gloss", PURPLE_LIGHT), "N": ("ink", INK)})
pixmap(s, "paw", ["P......P"], 8, 6, "front")
s.commit()
