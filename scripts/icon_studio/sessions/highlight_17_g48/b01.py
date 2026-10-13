"""Batch 1 of the 17_螢光筆 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from kit import pencil_ellipse, pencil_line
from parts import INK, YELLOW, hamster48
from studio import Studio

COLLAR = "#6C6E9E"  # the reference's slate grip (no palette entry)
ROT = "rotate(-28 28 31.5)"  # marker drawn upright, then tilted so the tip points to the lower right


def tilt(x: float, y: float) -> tuple[float, float]:
    """Where a point of the upright marker lands after ROT (for the sketch lines)."""
    a = math.radians(-28)
    dx, dy = x - 28, y - 31.5
    return 28 + dx * math.cos(a) - dy * math.sin(a), 31.5 + dx * math.sin(a) + dy * math.cos(a)


s = Studio.open()
s.begin(1, "48 格：構圖草稿與大色塊",
        "參考圖：一支粗胖的黃色螢光筆斜放（筆身往右下傾約 28°，寬約 14.7 格），下端接一段灰藍色筆夾往下收窄、最下面是黃色斜頭；"
        "倉鼠趴在筆的上端，頭擋住筆頭蓋、兩隻手抱住筆身左右兩邊；筆尖下面一道黃色橫向螢光筆痕（x 11–37、y 41–45）。",
        "筆先直立畫好再整支轉 -28°（以筆身和筆夾交界的中心 (28, 31.5) 為軸）：筆身 2.5 px 深藍框、黃色；筆夾梯形從 12.2 收到 5.3；"
        "筆尖短梯形；筆痕 4 px 寬黃色圓頭線，放在最底層；倉鼠頭 15×12.4 中心 (20.5, 10.5)、往左歪 8°，蓋在筆身上端前面。",
        tempo="slow")
rng = random.Random(1748)
W, OP = 0.2, 0.55
for name, p0, p1 in [("l", (21.9, 12), (21.9, 31.5)), ("r", (34.1, 12), (34.1, 31.5)), ("b", (21.9, 31.5), (34.1, 31.5)),
                     ("cl", (21.9, 31.5), (25.35, 37.5)), ("cr", (34.1, 31.5), (30.65, 37.5)),
                     ("tip", (25.6, 41.3), (30.4, 41.3))]:
    pencil_line(s, f"sk_{name}", tilt(*p0), tilt(*p1), rng, w=W, op=OP, amp=0.08, overshoot=0.04)
pencil_line(s, "sk_band", (12.5, 43.3), (36, 42.2), rng, w=W, op=OP, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 20.5, 10.5, 7.5, 6.2, rng, w=W, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("band", "path", "back", d="M13 43.25L35.5 42.25", fill="none", stroke=YELLOW, stroke_width=4, stroke_linecap="round",
      anim="draw")
s.add("barrel", "path", "object", d="M21.9 31.5V14A2 2 0 0 1 23.9 12H32.1A2 2 0 0 1 34.1 14V31.5Z", fill=YELLOW,
      stroke=INK, stroke_width=2.5, stroke_linejoin="round", transform=ROT, anim="fill")
s.add("tip", "path", "object", d="M25.6 37.5H30.4L29.6 41.25H26.4Z", fill=YELLOW, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", transform=ROT, anim="fill")
s.add("collar", "path", "object", d="M21.9 31.5H34.1L30.65 37.5H25.35Z", fill=COLLAR, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", transform=ROT, anim="fill")
hamster48(s, "hm", 20.5, 10.5, 7.5, 6.2, layer="front", k=0.78, rot=-8, parts=("blocks",))
s.commit(compare=True)
