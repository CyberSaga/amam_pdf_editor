"""Batch 3 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import random
from studio import Studio
from geo import smooth_d, wobble_ellipse, wobble_pts
from kit import pencil_line, RED_PENCIL

s = Studio.open()
s.begin(2, "對照參考：量比例、改頭形",
        "和參考圖疊在一起看：頭畫成正圓、往下掉出標籤窗太多，參考的頭是寬圓頂、底部幾乎撐滿標籤窗寬度；本體上緣低了約 5；標籤上緣高了約 3。擋板、槽孔、切角都很接近。",
        "頭改成寬圓頂（寬 128、從 276 往下到標籤底被切掉）；本體上緣上移、標籤上緣下移；用紅鉛筆標出關鍵比例刻度。",
        tempo="normal")
s.compare("疊參考圖檢查比例")
s.look((180, 270, 152, 120), "頭：正圓 → 寬圓頂，底部被標籤窗切掉")
# reshape head: same stroke structure (18-pt ellipse) so the change reads as a redraw
rng = random.Random(22)
# replay the rng exactly as b02 did, to rebuild comparable stroke data
pts = wobble_ellipse(256, 340, 66, 64, random.Random(5), amp=1.4, a0=150, sweep=375)
s.mod("sk_head", note="頭形 r56 正圓 → 寬 132 的圓頂", d=smooth_d(pts))
s.look((120, 100, 270, 20), "本體上緣偏低")
r2 = random.Random(31)
s.mod("sk_body_t", note="上緣 115 → 110", d=smooth_d(wobble_pts((128, 110), (384, 110), r2, amp=0.9, n=6, overshoot=0.06)))
s.mod("sk_body_l", d=smooth_d(wobble_pts((128, 110), (128, 397), r2, amp=0.9, n=6, overshoot=0.05)))
s.mod("sk_body_r", d=smooth_d(wobble_pts((384, 110), (384, 397), r2, amp=0.9, n=6, overshoot=0.05)))
s.mod("sk_chamfer", note="切角跟著上緣移動", d=smooth_d(wobble_pts((335, 110), (384, 159), r2, amp=0.9, n=6, overshoot=0.08)))
s.mod("sk_lb_t", note="標籤上緣 242 → 245", d=smooth_d(wobble_pts((179, 245), (333, 245), r2, amp=0.9, n=6, overshoot=0.05)))
# red-pencil proportion ticks (process marks)
rr = random.Random(7)
ticks = [
    ("gd_tick_sh", (192, 103), (320, 103), "擋板寬 ≈ 本體 0.52"),
    ("gd_tick_lb", (179, 368), (333, 368), "標籤寬 ≈ 本體 0.61"),
    ("gd_tick_top", (116, 110), (116, 245), "標籤上緣 ≈ 本體高 0.47"),
]
for tid, p0, p1, note in ticks:
    pencil_line(s, tid, p0, p1, rr, w=1.2, op=0.7, amp=0.4, overshoot=0.0, color=RED_PENCIL, layer="guides", n=4)
    # end caps
    vert = p0[0] == p1[0]
    for k, p in enumerate((p0, p1)):
        if vert:
            a, b = (p[0] - 5, p[1]), (p[0] + 5, p[1])
        else:
            a, b = (p[0], p[1] - 5), (p[0], p[1] + 5)
        pencil_line(s, f"{tid}_c{k}", a, b, rr, w=1.2, op=0.7, amp=0.2, overshoot=0.0, color=RED_PENCIL, layer="guides", n=3)
s.params["est"].update({"body": [128, 110, 384, 397], "head_dome": [256, 276, 66], "label": [179, 245, 333, 355], "chamfer": 49})
s.commit(compare=True)
