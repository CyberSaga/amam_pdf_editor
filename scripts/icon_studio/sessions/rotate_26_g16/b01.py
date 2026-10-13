"""Batch 1 of the 26_旋轉頁 16 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import INK, PAPER, PURPLE_DARK, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：8 格寬的倉鼠臉趴在紙上緣、紙中央 2 px 深紫環形箭頭。",
        "紙外緣 x 3/13、y 5/15，折角 3；臉用儲存 16 格版的五列（耳蓋、粉耳、2×2 眼睛帶反光、白口鼻與鼻子），7 格寬放 x 4–10；"
        "箭頭半徑 2.5、1.5 px 深紫，箭頭三角放大一點才讀得到方向。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(3.5, 5.5, 12.5, 14.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(12.5, 5.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
FACE = [
    ".NN.NN.",
    ".KKPKK.",
    "PHEPHEP",
    "PEEPEEP",
    "BWWRWWB",
]
pixmap(s, "hm", FACE, 4, 0, "hamster")
cx, cy, r = 8.0, 10.5, 2.5
a0, a1 = 60.0, 342.0


def at(a):
    t = math.radians(a)
    return cx + r * math.cos(t), cy + r * math.sin(t)


p0, p1 = at(a0), at(a1)
tan = (-math.sin(math.radians(a1)), math.cos(math.radians(a1)))
nrm = (math.cos(math.radians(a1)), math.sin(math.radians(a1)))
w, ln = 1.7, 2.0
c1 = (p1[0] + nrm[0] * w, p1[1] + nrm[1] * w)
c2 = (p1[0] - nrm[0] * w, p1[1] - nrm[1] * w)
tip = (p1[0] + tan[0] * ln, p1[1] + tan[1] * ln)
s.add("ring", "path", "object_fx", d=f"M{f(p0[0])} {f(p0[1])}A{f(r)} {f(r)} 0 1 1 {f(p1[0])} {f(p1[1])}", fill="none",
      stroke=PURPLE_DARK, stroke_width=1.5, stroke_linecap="round", anim="draw")
s.add("ring_head", "path", "object_fx", d=f"M{f(c1[0])} {f(c1[1])}L{f(tip[0])} {f(tip[1])}L{f(c2[0])} {f(c2[1])}Z",
      fill=PURPLE_DARK, anim="pop")
s.commit()
