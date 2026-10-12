"""Batch 1 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import random
from studio import Studio
from kit import guide_line, pencil_line

s = Studio.open()
s.begin(1, "構圖定位：中軸與兩個大框",
        "空白畫布。參考圖是直式白色按鈕卡片，中間一片紫色磁碟片，下方標籤窗裡有倉鼠。",
        "先拉中軸，用目測比例框出卡片（約畫布 3/4 寬、接近全高）與磁碟本體（約一半寬、高略大於寬）。線條要輕、可以超出。",
        tempo="slow")
rng = random.Random(11)
guide_line(s, "gd_axis_v", (256, 14), (256, 498))
guide_line(s, "gd_axis_h", (14, 256), (498, 256))
# card block-in (eyeballed: 3/4 width, near full height)
pencil_line(s, "sk_card_t", (64, 32), (448, 32), rng, op=0.38, overshoot=0.05)
pencil_line(s, "sk_card_l", (64, 32), (64, 480), rng, op=0.38, overshoot=0.04)
pencil_line(s, "sk_card_r", (448, 32), (448, 480), rng, op=0.38, overshoot=0.04)
pencil_line(s, "sk_card_b", (64, 480), (448, 480), rng, op=0.38, overshoot=0.05)
# floppy body block-in: ~half the canvas width, a bit taller than wide
pencil_line(s, "sk_body_t", (128, 115), (384, 115), rng, op=0.5, overshoot=0.06)
pencil_line(s, "sk_body_l", (128, 115), (128, 397), rng, op=0.5, overshoot=0.05)
pencil_line(s, "sk_body_r", (384, 115), (384, 397), rng, op=0.5, overshoot=0.05)
pencil_line(s, "sk_body_b", (128, 397), (384, 397), rng, op=0.5, overshoot=0.06)
# second, firmer pass on the body's left and bottom (weight side)
pencil_line(s, "sk_body_l2", (129, 118), (128, 395), rng, op=0.32, overshoot=0.02, amp=1.4)
pencil_line(s, "sk_body_b2", (131, 398), (382, 396), rng, op=0.32, overshoot=0.02, amp=1.4)
s.params["est"] = {"card": [64, 32, 448, 480], "body": [128, 115, 384, 397]}
s.commit()
