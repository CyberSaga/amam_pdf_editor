"""Batch 1 of the 28_插入空白頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PAPER_SHADE, PURPLE, WHITE, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版定稿：2.5 px 外框的折角紙、從紙後探頭扶著紙緣的倉鼠、壓在右下角的紫色加號章。座標減半後倉鼠頭只剩 7 格寬，"
        "放不下 2×2 的眼睛和反光。",
        "紙外框 1.5 px（外緣 x 2/15、y 2/21），折角 3.5；倉鼠頭放大到 9 格寬、逐像素畫：深藍耳緣配粉色內耳、2×2 眼睛各帶 1 格白反光、"
        "眼間 1 格白色口鼻尖、鼻 1 格、腮紅，左側輪廓交給紙緣；手掌 2 格壓在紙緣上；加號章外半徑 4.5、1 px 線、5×5 白加號。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(2.75, 2.75, 14.25, 20.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(14.25, 2.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("sheet_shade", "path", "object_fx", d="M13 7.5V19H3.5", fill="none", stroke=PAPER_SHADE, stroke_width=1, anim="draw")
HAMSTER = [
    "..NN...NN..",
    ".NKKNNNKKN.",
    ".NPPPPPPPN.",
    ".NPHEPHEPN.",
    ".NPEEWEEPN.",
    ".NBWWRWWBN.",
    "..NWWMWWN..",
    "..NNNNNNN..",
    "..NWWPPPN..",
    "..NWWPPPN..",
    "..NWPPPPN..",
    "...NPPPN...",
    "....NNN....",
]
pixmap(s, "hm", HAMSTER, 13, 5, "hamster")
PAW = [
    ".NN.",
    "NPPN",
    ".NN.",
]
pixmap(s, "paw", PAW, 13, 12, "front")
s.add("badge_disc", "circle", "badge", cx=14.5, cy=18.5, r=4, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
s.add("badge_plus", "path", "badge", d="M14 16h1v2h2v1h-2v2h-1v-2h-2v-1h2Z", fill=WHITE, anim="pop")
s.commit()
