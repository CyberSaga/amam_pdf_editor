"""Batch 3 of the 03_儲存 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f, smooth_d
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(5, "48 格：倉鼠（21×14 格的標籤窗）",
        "外形在 1× 銳利。標籤窗內有 21×14 個白色像素，比 24 格版多出四倍空間，容得下精細版的臉部結構。",
        "頭 19×11 格的半橢圓，墨框 1.25（和精細版一樣用深藍墨線）；耳朵加內耳粉；下半臉白色口鼻區；眼睛 2.5×3.2 格加左上反光點；鼻、ω 嘴、兩側各兩根鬍鬚、腮紅。",
        tempo="normal")
cx, cy, rx, ry = 24.0, 39.2, 9.6, 11.0


def ell(a, k=1.0):
    t = math.radians(a)
    return (cx + rx * k * math.cos(t), cy + ry * k * math.sin(t))


a0 = math.degrees(math.asin((38.0 - cy) / ry))
head = [ell(180 - a0 + (360 + 2 * a0 - 180) * i / 16) for i in range(17)]
for i, ex in enumerate((18.3, 29.7)):
    s.add(f"ear{i}", "circle", "hamster", cx=ex, cy=29.6, r=3.0, fill="#F6C58E", stroke=INK, stroke_width=1.25, anim="fill")
    s.add(f"ear{i}_in", "circle", "hamster", cx=ex + (0.55 if i == 0 else -0.55), cy=30.0, r=1.55, fill="#F2A3A0", anim="fill")
s.add("head", "path", "hamster", d="M" + "L".join(f"{f(x)} {f(y)}" for x, y in head) + "Z", fill="#F6C58E",
      stroke=INK, stroke_width=1.25, stroke_linejoin="round", anim="fill")
k = 0.93  # stay inside the head outline


def side(y):
    return rx * k * math.sqrt(max(0.0, 1 - ((y - cy) / (ry * k)) ** 2))


top = [(cx - side(35.2), 35.2), (19.2, 34.2), (21.6, 34.5), (24, 32.9), (26.4, 34.5), (28.8, 34.2), (cx + side(35.2), 35.2)]
muzzle = smooth_d(top) + f"L{f(cx + side(38))} 38L{f(cx - side(38))} 38Z"
s.add("muzzle", "path", "hamster", d=muzzle, fill="#FFFFFF", anim="fill")
for i, ex in enumerate((20.4, 27.6)):
    s.add(f"eye{i}", "ellipse", "hamster", cx=ex, cy=32.5, rx=1.25, ry=1.6, fill=INK, anim="pop")
    s.add(f"eye{i}_hl", "circle", "hamster", cx=ex - 0.4, cy=31.9, r=0.55, fill="#FFFFFF", anim="pop")
s.add("nose", "path", "hamster", d="M23.05 34.55Q24 34.15 24.95 34.55Q24.6 35.4 24 35.65Q23.4 35.4 23.05 34.55Z", fill="#E35D6A", anim="pop")
s.add("mouth", "path", "hamster", d="M22.1 36Q23 37.05 24 35.95Q25 37.05 25.9 36", fill="none", stroke=INK,
      stroke_width=0.8, stroke_linecap="round", stroke_linejoin="round", anim="draw")
for i, (y0, y1) in enumerate(((34.3, 33.7), (35.6, 36.1))):
    s.add(f"whisker_l{i}", "path", "hamster", d=f"M16.6 {f(y0)}L13.9 {f(y1)}", fill="none", stroke=INK,
          stroke_width=0.6, stroke_linecap="round", anim="draw")
    s.add(f"whisker_r{i}", "path", "hamster", d=f"M31.4 {f(y0)}L34.1 {f(y1)}", fill="none", stroke=INK,
          stroke_width=0.6, stroke_linecap="round", anim="draw")
for i, bx in enumerate((18.2, 29.8)):
    s.add(f"blush{i}", "ellipse", "hamster", cx=bx, cy=34.9, rx=1.5, ry=0.85, fill="#F48FA0", fill_opacity=0.55, anim="pop")
s.params["head"] = [cx, cy, rx, ry]
s.commit()
