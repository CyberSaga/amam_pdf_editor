"""Batch 4 of the 09_重做 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import INK, hamster_face48, paws48
from studio import Studio


def snout_ink_d(cx, base, k, chin):
    """Outline of the part of hamster_face48(chin=...)'s rounded snout that hangs below the base line.

    Same curves as the builder's snout, split where they cross ``base``: the stroke continues the dome's
    flat-bottom stroke round the chin, so a head that no edge cuts keeps a closed silhouette.
    """
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
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻是一顆普通橢圓頭、還歪了 16°，"
        "五官被斜著拉開；抓尾巴的手是一顆圓豆子。儲存的頭是被窗框切平的圓頂：正面、兩頰最寬、五官在下三分之二。",
        "頭換成儲存的圓頂（k 0.8、正面不歪），放在鉤口下方 (23, 38.4)：右耳在箭頭頭部下角下方 1 格、左耳離鉤的內緣 0.4 格。"
        "這顆頭下面沒有邊可以切，嘴部的白色收成圓鼻口（chin 2.4），再沿鼻口下緣補一道 1.25 px 深藍線接上頭的底線，"
        "淺色背景上下巴才有輪廓；抓住尾巴尖的手換成帶趾紋的肉墊。",
        tempo="normal")
s.look((11, 26, 22, 18), "普通橢圓頭、歪 16°、豆子手")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hm_")]):
    s.rm(eid, note="舊倉鼠擦掉" if i == 0 else None)
hamster_face48(s, "hf", 23.0, 38.4, 0.8, chin=2.4)
s.add("hf_chin_ink", "path", "hamster", d=snout_ink_d(23.0, 38.4, 0.8, 2.4), fill="none", stroke=INK,
      stroke_width=1.25, stroke_linecap="round", anim="draw")
paws48(s, "hf_paws", [(16.4, 36.4)], k=0.8)
s.commit()
