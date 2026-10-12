"""Batch 4 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(5, "24 格：倉鼠（10×6 格的標籤窗）",
        "外形在 1× 已經乾淨。標籤窗內只有 10×6 個白色像素，要放得下一顆看得出是倉鼠的頭。",
        "頭用被窗底切掉的半橢圓（寬約 9 格、高約 4.5 格）加 1 px 墨框；耳朵畫大一點（直徑約 2.8 格）並填內耳粉，否則外框會把耳朵吃成黑點；眼睛各 1 格寬、1.5 格高，對稱放在第 10、13 欄；鼻子只留一個小粉點。毛、鬍鬚、腮紅全部不畫。",
        tempo="normal")
cx, cy, rx, ry = 12.0, 18.4, 4.35, 4.45
a0 = math.degrees(math.asin((18.0 - cy) / ry))
pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
       for a in [180 - a0 + (360 + 2 * a0 - 180) * i / 12 for i in range(13)]]
head_d = "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"
for i, ex in enumerate((9.15, 14.85)):
    s.add(f"ear{i}", "circle", "hamster", cx=ex, cy=14.15, r=1.35, fill="#F2A3A0", stroke=INK, stroke_width=0.9, anim="fill")
s.add("head", "path", "hamster", d=head_d, fill="#F5BD7E", stroke=INK, stroke_width=1.0, stroke_linejoin="round", anim="fill")
for i, ex in enumerate((10.0, 13.0)):
    s.add(f"eye{i}", "rect", "hamster", x=ex, y=15.2, width=1, height=1.5, rx=0.45, fill=INK, anim="pop")
s.add("nose", "circle", "hamster", cx=12, cy=17.05, r=0.48, fill="#E35D6A", anim="pop")
s.params["head"] = [cx, cy, rx, ry]
s.commit()
