"""Batch 2 of the 26_旋轉頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import PURPLE_DARK, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：臉縮成 8 格、箭頭改實心深紫",
        "倉鼠臉 10 格寬、紙內只有 11 格，臉比紙還搶眼；環形箭頭深藍墊底只剩 1 px 紫色，在 1× 讀成一個黑環。"
        "草稿試了三種箭頭：深藍包邊、淺紫無框、深紫無框，深紫 2 px 在 24–32 px 最清楚。",
        "臉改成 8 格寬、耳朵以下不畫側邊外框（像儲存 16 格的臉）；紙放寬到 x 5/19；箭頭改成 2 px 深紫線條 + 實心三角頭，"
        "不再包深藍邊（3 px 以下的線狀符號在 24 格不包邊）。",
        tempo="normal")
s.look((5, 0, 13, 9), "臉太寬")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_", "ring"))]:
    s.rm(eid, note="重畫")
s.mod("sheet", note="紙放寬 1 格", d=page_d(5.75, 7.75, 18.25, 22.25, 1.5, 3.5))
s.mod("flap", d=flap_d(18.25, 7.75, 3.5, 0.75))
FACE = [
    ".NN..NN.",
    "NKKNNKKN",
    "PPPPPPPP",
    "PHEPPHEP",
    "PEEWWEEP",
    "BWWRRWWB",
]
pixmap(s, "hm", FACE, 8, 1, "hamster")
pixmap(s, "paw", ["P......P"], 8, 7, "front")
cx, cy, r = 12.0, 15.5, 3.5
a0, a1 = 60.0, 342.0


def at(a):
    t = math.radians(a)
    return cx + r * math.cos(t), cy + r * math.sin(t)


p0, p1 = at(a0), at(a1)
tan = (-math.sin(math.radians(a1)), math.cos(math.radians(a1)))
nrm = (math.cos(math.radians(a1)), math.sin(math.radians(a1)))
w, ln = 2.2, 2.6
c1 = (p1[0] + nrm[0] * w, p1[1] + nrm[1] * w)
c2 = (p1[0] - nrm[0] * w, p1[1] - nrm[1] * w)
tip = (p1[0] + tan[0] * ln, p1[1] + tan[1] * ln)
s.add("ring", "path", "object_fx", d=f"M{f(p0[0])} {f(p0[1])}A{f(r)} {f(r)} 0 1 1 {f(p1[0])} {f(p1[1])}", fill="none",
      stroke=PURPLE_DARK, stroke_width=2, stroke_linecap="round", anim="draw")
s.add("ring_head", "path", "object_fx", d=f"M{f(c1[0])} {f(c1[1])}L{f(tip[0])} {f(tip[1])}L{f(c2[0])} {f(c2[1])}Z",
      fill=PURPLE_DARK, anim="pop")
s.commit()
