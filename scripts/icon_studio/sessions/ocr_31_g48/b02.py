"""Batch 2 of the 31_OCR（文字辨識） 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f, smooth_d
from parts import BLUSH48, INK, NOSE48, TEAL, WHITE, paw48
from studio import Studio

HX, HY, HRX, HRY, K, CUT, EY = 24.0, 20.5, 6.4, 5.6, 0.64, 23.0, 19.6
s = Studio.open()
s.begin(5, "48 格：臉、手掌、掃描器細節與光束邊",
        "色塊疊參考吻合：掃描器、光束、L 框、T 都到位，倉鼠圓頂坐在掃描線上；但掃描器還是一塊平平的青綠、光束沒有邊，"
        "倉鼠沒有臉。",
        "倉鼠補臉：白口鼻（下緣也切在掃描線）、帶白反光的眼睛、鼻子、腮紅、鬍鬚，不畫嘴（離掃描線太近）；兩隻手掌搭在掃描線上；"
        "掃描器下半一道深藍出光縫、左上一道白色反光；光束兩側加 1.5 px 青綠邊（不透明，光束本身仍是單一 0.3 透明的形狀）；擦掉草稿。",
        tempo="normal")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.add("beam_edges", "path", "back", d="M16 11.75L8.5 43M32 11.75L39.5 43", fill="none", stroke=TEAL, stroke_width=1.5,
      stroke_linecap="round", anim="draw")
my = EY + 1.7 * K
side = HRX * 0.93
top = [(HX - side * 0.98, my + 1.0 * K), (HX - 4.8 * K, my), (HX - 2.4 * K, my + 0.3 * K), (HX, my - 1.3 * K),
       (HX + 2.4 * K, my + 0.3 * K), (HX + 4.8 * K, my), (HX + side * 0.98, my + 1.0 * K)]
hw = (HRX - 0.62) * math.sqrt(1 - ((CUT - HY) / (HRY - 0.62)) ** 2)
s.add("hm_muzzle", "path", "hamster", d=smooth_d(top) + f"L{f(HX + hw)} {f(CUT)}H{f(HX - hw)}Z", fill=WHITE, anim="fill")
for i, sgn in enumerate((-1, 1)):
    ex = HX + sgn * 3.6 * K
    s.add(f"hm_eye{i}", "ellipse", "hamster", cx=ex, cy=EY, rx=1.25 * K, ry=1.6 * K, fill=INK, anim="pop")
    s.add(f"hm_eye{i}_hl", "circle", "hamster", cx=ex - 0.4 * K, cy=EY - 0.6 * K, r=0.55 * K, fill=WHITE, anim="pop")
ny = EY + 2.05 * K
s.add("hm_nose", "path", "hamster",
      d=f"M{f(HX - 0.95 * K)} {f(ny)}Q{f(HX)} {f(ny - 0.4 * K)} {f(HX + 0.95 * K)} {f(ny)}"
        f"Q{f(HX + 0.6 * K)} {f(ny + 0.85 * K)} {f(HX)} {f(ny + 1.1 * K)}"
        f"Q{f(HX - 0.6 * K)} {f(ny + 0.85 * K)} {f(HX - 0.95 * K)} {f(ny)}Z", fill=NOSE48, anim="pop")
wy = EY + 1.8 * K
for i, (dy0, dy1) in enumerate(((0.0, -0.6), (1.3, 1.8))):
    for name, sgn in (("l", -1), ("r", 1)):
        s.add(f"hm_whisker_{name}{i}", "path", "hamster",
              d=f"M{f(HX + sgn * HRX * 0.77)} {f(wy + dy0 * K)}L{f(HX + sgn * HRX * 1.05)} {f(wy + dy1 * K)}", fill="none",
              stroke=INK, stroke_width=0.6, stroke_linecap="round", anim="draw")
for i, sgn in enumerate((-1, 1)):
    s.add(f"hm_blush{i}", "ellipse", "hamster", cx=HX + sgn * 5.8 * K, cy=EY + 2.4 * K, rx=1.5 * K, ry=0.85 * K,
          fill=BLUSH48, fill_opacity=0.55, anim="pop")
paw48(s, "hm_paw0", 19.6, CUT, layer="front", k=0.75)
paw48(s, "hm_paw1", 28.4, CUT, layer="front", k=0.75)
s.add("scanner_gloss", "path", "front", d="M14.5 6.5H22", fill="none", stroke=WHITE, stroke_width=1, stroke_opacity=0.6,
      stroke_linecap="round", anim="draw")
s.add("scanner_slit", "path", "front", d="M16.5 8.4H31.5", fill="none", stroke=INK, stroke_width=1, stroke_linecap="round",
      anim="draw")
s.commit(compare=True)
