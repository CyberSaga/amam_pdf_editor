"""Batch 1 of the 09_重做 24 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import BEAN24, INK, PURPLE, WHITE, pixmap
from studio import Studio

MIRROR = "matrix(-1 0 0 1 24 -5)"  # 08_復原's 24 px arrow, mirrored and raised 5 px (whole pixels)


def undo_arrow_d(tip_x, cy, head_h, back_x, top, bot, ocx, rx, ry, tail_deg, qx):
    """The 08_復原 hook arrow (left-pointing outline, stroke centre line, pointed tail); mirror it with MIRROR."""
    t = math.radians(tail_deg)
    px, py = ocx + rx * math.cos(t), top + ry + ry * math.sin(t)
    r = ((px - qx) ** 2 + (py - bot) ** 2) / (2 * (py - bot))
    return (f"M{f(tip_x)} {f(cy)}L{f(back_x)} {f(cy - head_h / 2)}V{f(top)}H{f(ocx)}"
            f"A{f(rx)} {f(ry)} 0 0 1 {f(px)} {f(py)}A{f(r)} {f(r)} 0 0 0 {f(qx)} {f(bot)}"
            f"H{f(back_x)}V{f(cy + head_h / 2)}Z")


s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：鏡射的彎箭頭在上，倉鼠的頭縮在鉤口下方、左上靠著鉤，左手抓著尾巴尖。24 格的鉤口只有 6 格寬；"
        "草稿裡豆子放 x 6 時，鉤的內緣半透明地壓在臉的第二欄，邊緣糊成土黃色；1 格的手放在尾巴尖只像一個雜點。",
        "箭頭直接用復原 24 格的箭頭，左右鏡射、上移 5 格（整數格，外緣仍在整數像素），白光一起鏡射；倉鼠是單獨的一顆頭、"
        "下面沒有邊可以擋住下巴，所以用 BEAN24（減一列身體成 10×10）放 x 7–16、y 13–22：鉤的內緣剛好疊在豆子的左輪廓上，"
        "右耳在箭頭頭部下角的下方隔一列；24 格不畫手。",
        tempo="normal")
s.add("arrow", "path", "object", d=undo_arrow_d(4.75, 12, 8.5, 10.25, 9.75, 14.25, 13.75, 7.5, 6.5, 62, 12),
      fill=PURPLE, stroke=INK, stroke_width=1.5, stroke_linejoin="round", transform=MIRROR, anim="fill")
pixmap(s, "hm", BEAN24[:7] + BEAN24[8:], 7, 13, "hamster")
s.add("arrow_gloss", "path", "glint", d="M12.5 11.5H13.75A5.75 4.75 0 0 1 18.2 13.3", fill="none", stroke=WHITE,
      stroke_width=1, stroke_opacity=0.5, stroke_linecap="round", transform=MIRROR, anim="draw")
s.commit()
