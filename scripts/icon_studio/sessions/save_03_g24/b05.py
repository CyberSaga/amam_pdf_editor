"""Batch 5 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：1× 檢查——臉糊成一團黑",
        "2× 時倉鼠清楚，但 1× 時頭的墨框、耳框、眼睛全部相鄰，整顆頭變成一團深色，兩隻眼睛完全分不出來。問題是深色太多，不是細節不夠。",
        "讓眼睛成為臉上唯一的深色：頭與耳朵的框改成暖棕色、線寬 0.8；頭頂再高半格，框線和眼睛之間留出一排杏色。",
        tempo="normal")
s.look((7, 12, 10, 6.5), "1× 時臉糊成一團")
cx, cy, rx, ry = 12.0, 18.4, 4.35, 4.95
a0 = math.degrees(math.asin((18.0 - cy) / ry))
pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
       for a in [180 - a0 + (360 + 2 * a0 - 180) * i / 12 for i in range(13)]]
s.mod("head", note="頭框改暖棕 0.8，頭頂升高半格", d="M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z",
      stroke="#B26E3A", stroke_width=0.8)
for i in range(2):
    s.mod(f"ear{i}", note="耳框改暖棕" if i == 0 else None, stroke="#B26E3A", stroke_width=0.75, cy=13.85)
for i in range(2):
    s.mod(f"eye{i}", y=15.0)
s.mod("nose", cy=16.95)
s.params["head"] = [cx, cy, rx, ry]
s.commit()
