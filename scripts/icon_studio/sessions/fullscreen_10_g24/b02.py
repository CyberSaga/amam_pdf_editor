"""Batch 2 of the 10_全螢幕 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import INK, hamster_face_px
from studio import Studio


def snout_ink_d(cx, base, k, chin):
    """Outline of the part of hamster_face_px(chin=...)'s rounded snout that hangs below the base line."""
    rx, ry, cy = 9.6 * k, 11.0 * k, base + 1.2 * k

    def side(y):
        return rx * 0.93 * math.sqrt(max(0.0, 1 - ((y - cy) / (ry * 0.93)) ** 2))

    ys = base - 2.8 * k
    sx, cb = side(ys) * 0.93, base + chin * k
    p = [(cx + side(ys), ys), (cx + sx + 0.4 * k, base), (cx + 3.2 * k, cb), (cx, cb)]

    def bez(t):
        u = 1 - t
        return tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t ** 3 * d for a, b, c, d in zip(*p))

    lo, hi = 0.0, 1.0
    for _ in range(40):
        lo, hi = ((lo + hi) / 2, hi) if bez((lo + hi) / 2)[1] < base else (lo, (lo + hi) / 2)
    t = (lo + hi) / 2

    def lerp(a, b):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    p12, p23 = lerp(p[1], p[2]), lerp(p[2], p[3])
    p123 = lerp(p12, p23)
    q0 = lerp(lerp(lerp(p[0], p[1]), p12), p123)
    return (f"M{f(q0[0])} {f(q0[1])}C{f(p123[0])} {f(p123[1])} {f(p23[0])} {f(p23[1])} {f(cx)} {f(cb)}"
            f"C{f(2 * cx - p23[0])} {f(p23[1])} {f(2 * cx - p123[0])} {f(p123[1])} {f(2 * cx - q0[0])} {f(q0[1])}")


s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓頂頭的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。8×8 的逐像素臉是方臉、斜角耳朵像貓；48 格已改成儲存的圓頂頭加圓鼻口。",
        "改用 48 格同一套構造（1 px 向量外框、眼睛鼻子腮紅放整數像素），k 0.55、頭心 x 12、底線 y 14.5，置中；"
        "嘴部收成圓鼻口，下緣補一道 1 px 深藍線；耳朵離左上、右上箭頭的斜桿末端還有 1 格以上。",
        tempo="normal")
s.look((7, 7, 11, 10), "方臉、貓耳")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hm_")]):
    s.rm(eid, note="舊倉鼠擦掉" if i == 0 else None)
hamster_face_px(s, "hf", 24, 12, 14.5, 0.55, chin=2.4)
s.add("hf_chin_ink", "path", "hamster", d=snout_ink_d(12, 14.5, 0.55, 2.4), fill="none", stroke=INK, stroke_width=1,
      stroke_linecap="round", anim="draw")
s.commit()
