"""Batch 2 of the 03_儲存 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import body_outline_d, rrect_d, smooth_d, wobble_pts
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(2, "48 格：大形與比例",
        "疊上精細版：擋板、槽孔、頭的位置都吻合；標籤窗草稿左右各寬了約 2 格（原作標籤窗是本體寬的 0.61）。",
        "標籤窗收窄到 x 12–36；本體外框 2.5 px、擋板與標籤窗 1.5 px（線寬層級 5:3），外緣都落在整數像素；槽孔 4×7 放整數格，右側留 1.5 格白；標籤窗框獨立放在倉鼠上層。",
        tempo="normal")
s.look((10.5, 21.5, 27, 19), "標籤窗偏寬")
r2 = random.Random(482)
s.mod("sk_lb_l", note="標籤窗左緣 11 → 12", d=smooth_d(wobble_pts((12, 22), (12, 39.5), r2, amp=0.08, n=6, overshoot=0.04)))
s.mod("sk_lb_r", note="標籤窗右緣 37 → 36", d=smooth_d(wobble_pts((36, 22), (36, 39.5), r2, amp=0.08, n=6, overshoot=0.04)))
s.layer("sketch", opacity=0.6)
s.add("floppy", "path", "body", d=body_outline_d(7.25, 5.25, 40.75, 42.75, 2.5, 7.0, 1.2), fill="#9285D5",
      stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("shutter_plate", "path", "shutter", d=rrect_d(15.75, 4.75, 32.25, 18.25, 1.5), fill="#F7F7FA",
      stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("slot", "rect", "shutter", x=26, y=8, width=4, height=7, rx=1, fill="#2E3052", anim="fill")
s.add("label_paper", "path", "label", d=rrect_d(12.75, 23.25, 35.25, 38.75, 1.75), fill="#FFFFFF", anim="fill")
s.add("label_frame", "path", "ink", d=rrect_d(12.75, 23.25, 35.25, 38.75, 1.75), fill="none", stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="draw")
s.commit()
