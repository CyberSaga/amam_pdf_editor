"""Batch 13 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
from studio import Studio
from geo import taper_stroke_d

s = Studio.open()
s.begin(5, "觀察修正：內耳摺線與鬍鬚粗細",
        "放大看：內耳摺線落在粉色區正中、幾乎垂直，讀起來像一道刮痕；參考圖的摺線是貼著內耳靠頭頂那一側的「)」形弧線。鬍鬚根部 2.0 太粗，在白色臉頰上顯得很重。",
        "摺線改為沿內耳內側邊緣的錐形弧、尾端收進頭的輪廓線下；鬍鬚根部改細到 1.55。",
        tempo="normal")
s.look((206, 264, 34, 26), "內耳摺線位置錯誤")
for i, (ix, iy, irx, iry) in enumerate(s.params["ear_inner"]):
    sgn = 1 if i == 0 else -1
    pts = []
    for k in range(5):
        a = math.radians(-82 + 58 * k / 4)
        pts.append((ix + sgn * irx * 0.86 * math.cos(a), iy + iry * 0.86 * math.sin(a)))
    s.mod(f"ink_earfold{i}", note="摺線改沿內耳內側的弧", d=taper_stroke_d(pts, 0.6, 1.9),
          fill="#6A4048", fill_opacity=0.7, stroke="none", stroke_width=None)
s.look((184, 324, 30, 28), "鬍鬚根部太重")
for idx, dense in enumerate(s.params["whiskers"]):
    side, j = divmod(idx, 3)
    s.mod(f"ink_whisker{side}{j}", d=taper_stroke_d(dense, 1.55, 0.4))
s.commit(zooms=[(176, 250, 160, 112)])
