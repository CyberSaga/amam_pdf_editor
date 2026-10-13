"""Batch 2 of the 26_旋轉頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import INK, PAPER_SHADE, PURPLE, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：環形箭頭、臉與手掌",
        "色塊疊參考吻合：紙、頭的位置都對；頭只露出紙緣上方約 8 格，五官要全部放在 y 11 以上。",
        "環形箭頭：中心 (24, 30.5)、半徑 7，深藍 4.6 寬的弧墊底、紫色 2.2 寬的弧在上，形成 1.2 px 外框；尾端圓頭在五點鐘，"
        "順時針掃 282° 到兩點半接三角箭頭（朝下）。倉鼠補上臉、兩隻手掌搭在紙緣（紙的上層）；紙內側加淡陰影；擦掉草稿。",
        tempo="normal")
cx, cy, r = 24.0, 30.5, 7.0
a0, a1 = 60.0, 342.0


def at(a, rr=r):
    t = math.radians(a)
    return cx + rr * math.cos(t), cy + rr * math.sin(t)


p0, p1 = at(a0), at(a1)
arc = f"M{f(p0[0])} {f(p0[1])}A{f(r)} {f(r)} 0 1 1 {f(p1[0])} {f(p1[1])}"
tan = (-math.sin(math.radians(a1)), math.cos(math.radians(a1)))
nrm = (math.cos(math.radians(a1)), math.sin(math.radians(a1)))
w, ln = 3.4, 4.2
c1 = (p1[0] + nrm[0] * w, p1[1] + nrm[1] * w)
c2 = (p1[0] - nrm[0] * w, p1[1] - nrm[1] * w)
tip = (p1[0] + tan[0] * ln, p1[1] + tan[1] * ln)
s.add("ring_ink", "path", "object_fx", d=arc, fill="none", stroke=INK, stroke_width=4.6, stroke_linecap="round", anim="draw")
s.add("ring_head", "path", "object_fx", d=f"M{f(c1[0])} {f(c1[1])}L{f(tip[0])} {f(tip[1])}L{f(c2[0])} {f(c2[1])}Z",
      fill=PURPLE, stroke=INK, stroke_width=1.25, stroke_linejoin="round", anim="pop")
s.add("ring", "path", "object_fx", d=arc, fill="none", stroke=PURPLE, stroke_width=2.2, stroke_linecap="round", anim="draw")
s.add("sheet_shade", "path", "object_fx", d="M34.25 20.25V41.1Q34.25 42.25 33.1 42.25H14.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw", z=0.5)
hamster48(s, "hm", 23, 9.6, 6.6, 5.6, k=0.68, eye_y=8.0, parts=("face",))
paw48(s, "hm_paw0", 18.6, 12.2, layer="front", k=0.8)
paw48(s, "hm_paw1", 27.4, 12.2, layer="front", k=0.8)
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
