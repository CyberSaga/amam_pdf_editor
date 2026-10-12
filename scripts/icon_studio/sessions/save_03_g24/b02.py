"""Batch 2 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import body_outline_d, rrect_d, smooth_d, wobble_pts
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(2, "24 格：大形與比例（描邊對齊像素）",
        "疊上 1,550 元素版對照：原作本體高寬比約 1.16，草稿畫成 20×20 正方偏矮；槽孔在原作偏右，但照比例放在 24 格會貼到擋板內框、糊成一塊。",
        "本體改成 18×20（x 3–21）；外框 1.5 px，路徑內縮 0.75 讓外緣落在整數像素、輪廓銳利；擋板 10×8、槽孔 2×3 往左移 1 px 留出白邊；標籤窗 14×8.5。",
        tempo="normal")
s.look((1.5, 1.5, 21, 21), "本體偏方 → 18×20")
r2 = random.Random(242)
s.mod("sk_body_l", note="本體左緣 2 → 3", d=smooth_d(wobble_pts((3, 2.3), (3.05, 21.8), r2, amp=0.05, n=6, overshoot=0.04)))
s.mod("sk_body_r", note="本體右緣 22 → 21", d=smooth_d(wobble_pts((21, 2.2), (20.95, 21.8), r2, amp=0.05, n=6, overshoot=0.04)))
s.mod("sk_chamfer", d=smooth_d(wobble_pts((17, 2.2), (21, 6.2), r2, amp=0.04, n=6, overshoot=0.06)))
s.mod("sk_slot", note="槽孔左移 1 px，右側留白", d=smooth_d(wobble_pts((13.5, 4.5), (13.5, 7.5), r2, amp=0.02, n=3)))
s.layer("sketch", opacity=0.6)
s.add("floppy", "path", "body", d=body_outline_d(3.75, 2.75, 20.25, 21.25, 1.25, 3.6, 0.6), fill="#9285D5",
      stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("shutter_plate", "path", "shutter", d=rrect_d(7.75, 2.75, 16.25, 9.25, 0.75), fill="#F7F7FA",
      stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("slot", "rect", "shutter", x=12.5, y=4.5, width=2, height=3, rx=0.4, fill="#2E3052", anim="fill")
s.add("label_paper", "path", "label", d=rrect_d(5.75, 11.75, 18.25, 18.75, 1.0), fill="#FFFFFF",
      stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.commit()
