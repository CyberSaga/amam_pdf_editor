"""Batch 3 of the 09_重做 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from studio import Studio

MIRROR = "matrix(-1 0 0 1 48 -7)"


def undo_arrow_d(tip_x, cy, head_h, back_x, top, bot, ocx, rx, ry, tail_deg, qx):
    """The 08_復原 hook arrow (left-pointing outline, stroke centre line, pointed tail); mirror it with MIRROR."""
    t = math.radians(tail_deg)
    px, py = ocx + rx * math.cos(t), top + ry + ry * math.sin(t)
    r = ((px - qx) ** 2 + (py - bot) ** 2) / (2 * (py - bot))
    return (f"M{f(tip_x)} {f(cy)}L{f(back_x)} {f(cy - head_h / 2)}V{f(top)}H{f(ocx)}"
            f"A{f(rx)} {f(ry)} 0 0 1 {f(px)} {f(py)}A{f(r)} {f(r)} 0 0 0 {f(qx)} {f(bot)}"
            f"H{f(back_x)}V{f(cy + head_h / 2)}Z")


s = Studio.open()
s.begin(6, "48 格：跟著復原把箭頭外緣對回整數格",
        "復原的箭頭修正了半格外緣（桿子上下緣 18.5 / 29.5、頭部後緣 21.5、彎弧最右 40.75）；重做是它的鏡射，同樣的灰邊也在這裡"
        "（鏡射後桿子外緣 11.5 / 22.5、頭部後緣 26.5、彎弧最左 7.25）。",
        "換上復原修正後的同一條路徑（鏡射、上移 7 格不變），外緣落回 12 / 23、27、7；白光同步；尾巴尖往左下移了半格，"
        "抓著尾巴的左手跟過去。",
        tempo="normal")
s.look((6, 6, 34, 18), "鏡射的箭頭也在半格上")
s.mod("arrow", note="換上復原修正後的路徑",
      d=undo_arrow_d(9.5, 24.5, 17.5, 19.75, 20.25, 28.75, 27, 12.75, 11.75, 66, 27))
s.mod("arrow_gloss", d="M14.2 23.78L17.48 20.98M22.75 22.75H27A10.25 9.25 0 0 1 36.63 28.84")
s.mod("hm_paw", note="左手跟著尾巴尖", cx=16.25, cy=36.6)
s.commit()
