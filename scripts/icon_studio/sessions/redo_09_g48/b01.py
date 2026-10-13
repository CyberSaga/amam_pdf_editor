"""Batch 1 of the 09_重做 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math
import random

from geo import f
from kit import pencil_ellipse, pencil_line
from parts import INK, PURPLE, hamster48
from studio import Studio

MIRROR = "matrix(-1 0 0 1 48 -7)"  # 08_復原's arrow, mirrored left-right and raised 7 units


def undo_arrow_d(tip_x, cy, head_h, back_x, top, bot, ocx, rx, ry, tail_deg, qx):
    """The 08_復原 hook arrow (left-pointing outline, stroke centre line, pointed tail); mirror it with MIRROR."""
    t = math.radians(tail_deg)
    px, py = ocx + rx * math.cos(t), top + ry + ry * math.sin(t)
    r = ((px - qx) ** 2 + (py - bot) ** 2) / (2 * (py - bot))
    return (f"M{f(tip_x)} {f(cy)}L{f(back_x)} {f(cy - head_h / 2)}V{f(top)}H{f(ocx)}"
            f"A{f(rx)} {f(ry)} 0 0 1 {f(px)} {f(py)}A{f(r)} {f(r)} 0 0 0 {f(qx)} {f(bot)}"
            f"H{f(back_x)}V{f(cy + head_h / 2)}Z")


s = Studio.open()
s.begin(3, "48 格：鏡射復原的箭頭、倉鼠的大色塊",
        "參考圖：往右指的紫色粗彎箭頭佔上半（尖端朝右、桿子往左再向下彎成鉤），倉鼠縮在鉤的彎裡、頭往右歪，左上被鉤擋住、"
        "右耳露在箭頭頭部的下角旁。參考的箭頭比復原的大一號；照復原鏡射後，鉤口只有 12 格寬，倉鼠頭放進去右耳會撞到箭頭頭部的下角。",
        "箭頭直接用復原 48 格的路徑：左右鏡射、整支上移 7 格，線寬、顏色、尖尾巴都和復原一樣，兩個圖示並排才是一對；"
        "倉鼠頭 14.8×13.2（k 0.8）轉 16°，頭心放 (22, 35.5)：左耳收在鉤口裡、右耳落在箭頭頭部下角的下方 2 格，先鋪色塊。",
        tempo="slow")
rng = random.Random(948)
for name, p0, p1 in [("tip_t", (38.6, 16.9), (27.8, 8.3)), ("tip_b", (38.6, 17.1), (27.7, 25.7)),
                     ("back", (27.8, 8.3), (27.7, 25.7)), ("top", (27.8, 12.7), (21.2, 12.8))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_outer", 21.25, 24.5, 12.75, 11.75, rng, w=0.2, op=0.5, amp=0.1, a0=-90, sweep=-156)
pencil_ellipse(s, "sk_inner", 21.25, 29.2, 7.95, 7.95, rng, w=0.2, op=0.5, amp=0.1, a0=-90, sweep=-130)
pencil_ellipse(s, "sk_head", 22, 35.5, 7.4, 6.6, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("arrow", "path", "object", d=undo_arrow_d(9.5, 24, 17.5, 20.25, 19.75, 28.25, 26.75, 12.75, 11.75, 66, 26.75),
      fill=PURPLE, stroke=INK, stroke_width=2.5, stroke_linejoin="round", transform=MIRROR, anim="fill")
hamster48(s, "hm", 22, 35.5, 7.4, 6.6, k=0.8, rot=16, parts=("blocks",))
s.commit(compare=True)
