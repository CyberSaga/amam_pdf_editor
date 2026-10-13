"""Batch 1 of the 31_OCR（文字辨識） 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from geo import f, rrect_d
from kit import pencil_ellipse, pencil_line
from parts import EAR_IN, INK, PEACH, TEAL, TEAL_DARK
from studio import Studio

HX, HY, HRX, HRY, K, CUT = 24.0, 20.5, 6.4, 5.6, 0.64, 23.0
T_D = ("M17 25.5H31V30Q31 30.5 30.5 30.5H29.5Q29 30.5 29 30V29Q29 28 28 28H25.5V37.5Q25.5 38.5 26.5 38.5H27.5"
       "Q28 38.5 28 39V40Q28 40.5 27.5 40.5H20.5Q20 40.5 20 40V39Q20 38.5 20.5 38.5H21.5Q22.5 38.5 22.5 37.5V28H20"
       "Q19 28 19 29V30Q19 30.5 18.5 30.5H17.5Q17 30.5 17 30Z")
s = Studio.open()
s.begin(1, "48 格：草稿與大色塊",
        "參考圖：上方一條青綠色掃描器（外緣 x 10–38、y 3–10），底下一道向下張開的半透明青綠光束；四角深藍 L 形框，"
        "光束裡一隻淡淡的倉鼠從一條掃描線後探頭，下面一個大大的深藍襯線 T（x 18–30、y 25–39）。",
        "掃描器外緣 x 10/38、y 3/12，2.5 px 框；光束梯形從掃描器下緣 x 16–32 張到 y 43 的 x 8.5–39.5，單一青綠 0.3 透明；"
        "四個 L 框 2 px 深藍、圓頭；T 的橫畫 2.5、直畫 3、兩端與腳都有襯線，外框 x 17–31、y 25.5–40.5；"
        "倉鼠頭 12.8×11.2（k 0.64）的上半圓頂坐在 y 23 的掃描線上（頭畫成切平的圓頂，不用遮罩），先鋪色塊。",
        tempo="slow")
rng = random.Random(3148)
for name, p0, p1 in [("bt", (10.2, 3.1), (37.8, 3)), ("bb", (10.1, 11.9), (37.9, 12)), ("bl", (16, 12), (8.6, 42.9)),
                     ("br", (32, 12), (39.4, 43)), ("scan", (13.4, 23), (34.6, 22.9)), ("tt", (17.1, 25.6), (30.9, 25.5)),
                     ("ts", (24, 25.6), (24.1, 40.4))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", HX, HY, HRX, HRY, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("beam", "path", "back", d="M16 11.75L8.5 43H39.5L32 11.75Z", fill=TEAL, fill_opacity=0.3, anim="fill")
for i, sgn in enumerate((-1, 1)):
    ex, ecy = HX + sgn * 0.6 * HRX, HY - HRY + 1.3 * K
    s.add(f"hm_ear{i}", "circle", "hamster", cx=ex, cy=ecy, r=3.0 * K, fill=PEACH, stroke=INK, stroke_width=1.25, anim="fill")
    s.add(f"hm_ear{i}_in", "circle", "hamster", cx=ex - sgn * 0.55 * K, cy=ecy + 0.4 * K, r=1.55 * K, fill=EAR_IN, anim="fill")
hw = HRX * math.sqrt(1 - ((CUT - HY) / HRY) ** 2)
s.add("hm_head", "path", "hamster", d=f"M{f(HX - hw)} {f(CUT)}A{f(HRX)} {f(HRY)} 0 1 1 {f(HX + hw)} {f(CUT)}Z", fill=PEACH,
      stroke=INK, stroke_width=1.25, stroke_linejoin="round", anim="fill")
s.add("scan_line", "path", "object", d="M13.3 23H34.7", fill="none", stroke=TEAL_DARK, stroke_width=1.5, stroke_linecap="round",
      anim="draw")
corners = ["M7 21V16.5Q7 15 8.5 15H12.5", "M35.5 15H39.5Q41 15 41 16.5V21", "M7 37V41.5Q7 43 8.5 43H12.5",
           "M35.5 43H39.5Q41 43 41 41.5V37"]
for i, d in enumerate(corners):
    s.add(f"corner{i}", "path", "object", d=d, fill="none", stroke=INK, stroke_width=2, stroke_linecap="round",
          stroke_linejoin="round", anim="draw")
s.add("letter_t", "path", "object", d=T_D, fill=INK, anim="fill")
s.add("scanner", "path", "front", d=rrect_d(11.25, 4.25, 36.75, 10.75, 3), fill=TEAL, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
s.commit(compare=True)
