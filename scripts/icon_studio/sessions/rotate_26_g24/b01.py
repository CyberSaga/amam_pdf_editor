"""Batch 1 of the 26_旋轉頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import FACE24, INK, PAPER, PURPLE, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：置中的折角紙、紙上緣探頭的倉鼠、紙中央順時針環形箭頭（深藍包邊的紫色弧 + 三角箭頭）。",
        "紙外緣 x 6/19、y 7/23（上方留 6 列給倉鼠臉）；臉用 FACE24（10×6，耳朵到鼻子那列），兩隻手掌各 2 格桃色壓斷紙的上緣；"
        "箭頭：中心 (12.5, 15.5)、半徑 3.5，深藍 3 px 弧墊底、紫色 1.2 px 在上。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(6.75, 7.75, 18.25, 22.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(18.25, 7.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", FACE24, 6, 1, "hamster")
pixmap(s, "paw", ["PP....PP"], 7, 7, "front")
cx, cy, r = 12.5, 15.5, 3.5
a0, a1 = 60.0, 342.0


def at(a):
    t = math.radians(a)
    return cx + r * math.cos(t), cy + r * math.sin(t)


p0, p1 = at(a0), at(a1)
arc = f"M{f(p0[0])} {f(p0[1])}A{f(r)} {f(r)} 0 1 1 {f(p1[0])} {f(p1[1])}"
tan = (-math.sin(math.radians(a1)), math.cos(math.radians(a1)))
nrm = (math.cos(math.radians(a1)), math.sin(math.radians(a1)))
w, ln = 2.1, 2.5
c1 = (p1[0] + nrm[0] * w, p1[1] + nrm[1] * w)
c2 = (p1[0] - nrm[0] * w, p1[1] - nrm[1] * w)
tip = (p1[0] + tan[0] * ln, p1[1] + tan[1] * ln)
s.add("ring_ink", "path", "object_fx", d=arc, fill="none", stroke=INK, stroke_width=3, stroke_linecap="round", anim="draw")
s.add("ring_head", "path", "object_fx", d=f"M{f(c1[0])} {f(c1[1])}L{f(tip[0])} {f(tip[1])}L{f(c2[0])} {f(c2[1])}Z",
      fill=PURPLE, stroke=INK, stroke_width=0.9, stroke_linejoin="round", anim="pop")
s.add("ring", "path", "object_fx", d=arc, fill="none", stroke=PURPLE, stroke_width=1.2, stroke_linecap="round", anim="draw")
s.commit()
