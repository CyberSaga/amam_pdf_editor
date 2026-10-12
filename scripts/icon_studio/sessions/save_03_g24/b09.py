"""Batch 9 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f, smooth_d
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(5, "24 格：移植 48 版的倉鼠與光影",
        "版面已讓出 10×7 的臉部空間，正好是 48 版臉部的一半。",
        "依 48 版座標對半移植（x/2, y/2−1）：深藍框耳朵加內耳粉、深藍框杏色頭、白色口鼻區（尖角在兩眼之間）、眼睛加左上反光、鼻子、ω 嘴、腮紅；線寬低於 0.7 的一律加粗到 0.7，眼睛放大到 1.6×1.9 才讀得到。鬍鬚在 24 格沒有空間（頭的外緣就貼著窗框），不畫。擋板加下緣灰帶、槽孔加亮邊，本體加右下背光。",
        tempo="normal")
cx, cy, rx, ry = 12.0, 18.6, 4.8, 5.5


def ell_x(y, k=1.0):
    return rx * k * math.sqrt(max(0.0, 1 - ((y - cy) / (ry * k)) ** 2))


for i, ex in enumerate((9.15, 14.85)):
    s.add(f"ear{i}", "circle", "hamster", cx=ex, cy=13.8, r=1.5, fill="#F6C58E", stroke=INK, stroke_width=0.7, anim="fill")
    s.add(f"ear{i}_in", "circle", "hamster", cx=ex + (0.3 if i == 0 else -0.3), cy=14.0, r=0.8, fill="#F2A3A0", anim="fill")
a0 = math.degrees(math.asin((18.0 - cy) / ry))
head = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
        for a in [180 - a0 + (360 + 2 * a0 - 180) * i / 16 for i in range(17)]]
s.add("head", "path", "hamster", d="M" + "L".join(f"{f(x)} {f(y)}" for x, y in head) + "Z", fill="#F6C58E",
      stroke=INK, stroke_width=0.7, stroke_linejoin="round", anim="fill")
k = 0.93
top = [(cx - ell_x(16.6, k), 16.6), (9.6, 16.1), (10.8, 16.25), (12, 15.45), (13.2, 16.25), (14.4, 16.1), (cx + ell_x(16.6, k), 16.6)]
s.add("muzzle", "path", "hamster", d=smooth_d(top) + f"L{f(cx + ell_x(18, k))} 18L{f(cx - ell_x(18, k))} 18Z",
      fill="#FFFFFF", anim="fill")
for i, ex in enumerate((10.2, 13.8)):
    s.add(f"eye{i}", "ellipse", "hamster", cx=ex, cy=15.25, rx=0.8, ry=0.95, fill=INK, anim="pop")
    s.add(f"eye{i}_hl", "circle", "hamster", cx=ex - 0.25, cy=14.85, r=0.36, fill="#FFFFFF", anim="pop")
s.add("nose", "path", "hamster", d="M11.4 16.2Q12 15.95 12.6 16.2Q12.38 16.75 12 16.92Q11.62 16.75 11.4 16.2Z", fill="#E35D6A", anim="pop")
s.add("mouth", "path", "hamster", d="M11 17.05Q11.5 17.6 12 17.05Q12.5 17.6 13 17.05", fill="none", stroke=INK,
      stroke_width=0.55, stroke_linecap="round", stroke_linejoin="round", anim="draw")
for i, bx in enumerate((9.0, 15.0)):
    s.add(f"blush{i}", "ellipse", "hamster", cx=bx, cy=16.5, rx=0.9, ry=0.5, fill="#F48FA0", fill_opacity=0.6, anim="pop")
s.add("shutter_shade", "rect", "shutter", x=8, y=7, width=8, height=1, fill="#D9D9E5", anim="fill")
s.add("slot_glint", "path", "shutter", d="M13.45 4.45V6.55", fill="none", stroke="#7D84BE", stroke_width=0.5,
      stroke_linecap="round", anim="draw")
s.add("shade", "path", "body_fx", d="M18.9 7.5V19.1Q18.9 19.9 18.1 19.9H5.9", fill="none", stroke="#6A5EB6",
      stroke_width=0.8, stroke_opacity=0.5, stroke_linecap="round", anim="draw")
s.params["head"] = [cx, cy, rx, ry]
s.commit()
