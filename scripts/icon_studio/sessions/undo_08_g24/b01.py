"""Batch 1 of the 08_復原 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import INK, PEEK24, PURPLE, WHITE, pixmap
from studio import Studio


def undo_arrow_d(tip_x, cy, head_h, back_x, top, bot, ocx, rx, ry, tail_deg, qx):
    """Left-pointing hook arrow outline (stroke centre line), pointed tail (same build as the 48 design)."""
    t = math.radians(tail_deg)
    px, py = ocx + rx * math.cos(t), top + ry + ry * math.sin(t)
    r = ((px - qx) ** 2 + (py - bot) ** 2) / (2 * (py - bot))
    return (f"M{f(tip_x)} {f(cy)}L{f(back_x)} {f(cy - head_h / 2)}V{f(top)}H{f(ocx)}"
            f"A{f(rx)} {f(ry)} 0 0 1 {f(px)} {f(py)}A{f(r)} {f(r)} 0 0 0 {f(qx)} {f(bot)}"
            f"H{f(back_x)}V{f(cy + head_h / 2)}Z")


s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：往左的紫色彎箭頭（2.5 px 深藍框、尖尾巴的鉤、上緣一道白光），倉鼠從箭頭上緣後面探頭、兩手搭在箭頭上。"
        "座標直接減半時，鉤的內弧貼近外弧，尾段只剩 1 格紫色夾在兩條深藍線之間，1× 看起來是一條黑鉤。",
        "箭頭 1.5 px 深藍框：桿子外緣 y 9/15（紫色 3 格）、頭部尖端 x 4、後緣 x 11；外弧放大到 7.5×6.5、內弧切點左移到 x 12，"
        "鉤身加粗、紫色一路延伸到尾段；倉鼠用 PEEK24（8×6，耳朵以下不畫側框）放 x 11–18、鼻子那列貼著箭頭上緣，"
        "兩手各 1 格桃色壓在箭頭上緣；沿上緣補一道 1 px、50% 的白光。",
        tempo="normal")
s.add("arrow", "path", "object", d=undo_arrow_d(4.75, 12, 8.5, 10.25, 9.75, 14.25, 13.75, 7.5, 6.5, 62, 12),
      fill=PURPLE, stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK24, 11, 3, "hamster")
pixmap(s, "paw", ["P......P"], 11, 9, "front")
s.add("arrow_gloss", "path", "glint", d="M12.5 11.5H13.75A5.75 4.75 0 0 1 18.2 13.3", fill="none", stroke=WHITE,
      stroke_width=1, stroke_opacity=0.5, stroke_linecap="round", anim="draw")
s.commit()
