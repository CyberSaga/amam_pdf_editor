"""Batch 1 of the 11_縮圖 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, PEEK24, PURPLE_DARK, PURPLE_LIGHT, TEAL, TEAL_DARK, WHITE, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版定稿：2.5 px 深藍框、四塊帶白色光澤的方塊（左淡紫、右青綠）、框上緣偏右探頭的倉鼠。座標減半後框是 16 格、"
        "1.5 px 框線內側剩半格灰，5×5 的方塊兩邊放不下各 1 格白；草稿試了四種排法：方塊包深藍框時框內 64% 是深藍、像四個黑盒子，"
        "改用各自的深色框（深紫／深青綠）在 24–32 px 最像 48 格。",
        "框 17×17（外緣 x 3–20、y 6–23，1.5 px），讓方塊四周都有 1 格白；方塊 5×5 逐像素：深色框、3×3 淺色、左上 1 格白光澤；"
        "倉鼠用 PEEK24（8×6）放在第 0–5 列、比框中線偏右 1.5 格（和 48 格同比例），兩隻手掌各 1 格壓在框的上緣。",
        tempo="normal")
s.add("frame", "path", "object", d=rrect_d(3.75, 6.75, 19.25, 22.25, 1.5), fill=PAPER, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
TILES = [
    "DDDDD.KKKKK",
    "DGLLD.KGTTK",
    "DLLLD.KTTTK",
    "DLLLD.KTTTK",
    "DDDDD.KKKKK",
    "...........",
    "DDDDD.KKKKK",
    "DGLLD.KGTTK",
    "DLLLD.KTTTK",
    "DLLLD.KTTTK",
    "DDDDD.KKKKK",
]
pixmap(s, "tiles", TILES, 6, 9, "object", legend={"L": ("purple", PURPLE_LIGHT), "T": ("teal", TEAL),
                                                   "G": ("gloss", WHITE), "D": ("purple_ink", PURPLE_DARK),
                                                   "K": ("teal_ink", TEAL_DARK)})
pixmap(s, "hm", PEEK24, 9, 0, "hamster")
pixmap(s, "paw", ["P......P"], 9, 6, "front")
s.commit()
