"""Batch 2 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import random
from studio import Studio
from kit import pencil_line, pencil_ellipse

s = Studio.open()
s.begin(1, "草稿：切出內部大塊",
        "兩個框的位置大致成立，本體看起來偏方。內部還是空的，看不出是磁碟片。",
        "用經驗比例切分：右上切角約 1/5 寬；金屬擋板約一半寬、1/3 高；標籤窗約 3/5 寬、從中線下方開始；倉鼠先用一個大圓和兩個耳朵圓定位。",
        tempo="slow")
rng = random.Random(22)
# chamfer (top-right corner cut): ~1/5 of the body width
pencil_line(s, "sk_chamfer", (333, 115), (384, 166), rng, op=0.5, overshoot=0.08)
# metal shutter: ~half width, ~1/3 height, hanging from the top edge
pencil_line(s, "sk_sh_l", (192, 113), (192, 209), rng, op=0.46, overshoot=0.04)
pencil_line(s, "sk_sh_r", (320, 113), (320, 209), rng, op=0.46, overshoot=0.04)
pencil_line(s, "sk_sh_b", (192, 209), (320, 209), rng, op=0.46, overshoot=0.06)
# slot window in the right part of the shutter
pencil_line(s, "sk_slot_l", (272, 136), (272, 190), rng, op=0.42, overshoot=0.05, amp=0.6, n=4)
pencil_line(s, "sk_slot_r", (296, 136), (296, 190), rng, op=0.42, overshoot=0.05, amp=0.6, n=4)
pencil_line(s, "sk_slot_t", (272, 136), (296, 136), rng, op=0.42, overshoot=0.08, amp=0.5, n=4)
pencil_line(s, "sk_slot_b", (272, 190), (296, 190), rng, op=0.42, overshoot=0.08, amp=0.5, n=4)
# label window: ~3/5 width, starting a little below the middle
pencil_line(s, "sk_lb_t", (179, 242), (333, 242), rng, op=0.46, overshoot=0.05)
pencil_line(s, "sk_lb_l", (179, 242), (179, 355), rng, op=0.46, overshoot=0.05)
pencil_line(s, "sk_lb_r", (333, 242), (333, 355), rng, op=0.46, overshoot=0.05)
pencil_line(s, "sk_lb_b", (179, 355), (333, 355), rng, op=0.46, overshoot=0.05)
# hamster: big head circle + ear circles + face cross
pencil_ellipse(s, "sk_head", 256, 332, 56, 56, rng, op=0.44, amp=1.6, a0=150, sweep=375)
pencil_ellipse(s, "sk_ear_l", 220, 284, 15, 15, rng, op=0.42, amp=0.8)
pencil_ellipse(s, "sk_ear_r", 292, 284, 15, 15, rng, op=0.42, amp=0.8)
pencil_line(s, "sk_eye_line", (214, 320), (298, 320), rng, op=0.3, overshoot=0.0, amp=0.6, n=4)
pencil_ellipse(s, "sk_eye_l", 236, 320, 6, 6, rng, op=0.42, amp=0.4, n=10)
pencil_ellipse(s, "sk_eye_r", 276, 320, 6, 6, rng, op=0.42, amp=0.4, n=10)
s.params["est"].update({"chamfer": 51, "shutter": [192, 115, 320, 209], "slot": [272, 136, 296, 190],
                        "label": [179, 242, 333, 355], "head": [256, 332, 56], "ears": [[220, 284, 15], [292, 284, 15]],
                        "eyes": [[236, 320], [276, 320]]})
s.commit(compare=True)
