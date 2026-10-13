"""Batch 4 of the 08_復原 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import f
from parts import hamster48
from studio import Studio


def undo_arrow_d(tip_x, cy, head_h, back_x, top, bot, ocx, rx, ry, tail_deg, qx):
    """Same hook arrow as batch 1 (left-pointing, pointed tail)."""
    t = math.radians(tail_deg)
    px, py = ocx + rx * math.cos(t), top + ry + ry * math.sin(t)
    r = ((px - qx) ** 2 + (py - bot) ** 2) / (2 * (py - bot))
    return (f"M{f(tip_x)} {f(cy)}L{f(back_x)} {f(cy - head_h / 2)}V{f(top)}H{f(ocx)}"
            f"A{f(rx)} {f(ry)} 0 0 1 {f(px)} {f(py)}A{f(r)} {f(r)} 0 0 0 {f(qx)} {f(bot)}"
            f"H{f(back_x)}V{f(cy + head_h / 2)}Z")


class _Collect:
    """Stand-in for the studio: records what hamster48 would add, so the head can morph in place."""

    def __init__(self):
        self.attrs: dict[str, dict] = {}

    def add(self, eid, tag, layer, anim=None, **attrs):
        self.attrs[eid] = attrs
        return eid


s = Studio.open()
s.begin(6, "48 格：箭頭外緣對回整數格",
        "放大檢查像素：上一批整支上移 1.5 格，桿子的上下外緣落在 18.5 / 29.5 半格上，1× 看是一列灰邊；頭部後緣的外側 21.5、"
        "彎弧最右點 40.75 從第一批起也在半格上。",
        "箭頭改上移 1 格（桿子外緣回到 19 / 30），頭部後緣中心線 20.25→19.75（外緣 21）、彎弧圓心 x 26.75→27（最右外緣 41）；"
        "倉鼠、兩手和白光跟著下移 0.5 格，和箭頭上緣的關係不變。",
        tempo="normal")
s.look((8, 14, 34, 18), "桿子上下緣、頭部後緣在半格上")
s.mod("arrow", note="外緣對回整數格",
      d=undo_arrow_d(9.5, 24.5, 17.5, 19.75, 20.25, 28.75, 27, 12.75, 11.75, 66, 27))
s.mod("arrow_gloss", d="M14.2 23.78L17.48 20.98M22.75 22.75H27A10.25 9.25 0 0 1 36.63 28.84")
c = _Collect()
hamster48(c, "hm", 27.4, 14.5, 7.4, 6.6, k=0.8, rot=10)
for i, (eid, attrs) in enumerate(c.attrs.items()):
    s.mod(eid, note="倉鼠跟著下移 0.5" if i == 0 else None, **attrs)
s.mod("hm_paw0", cx=21.9, cy=18.9)
s.mod("hm_paw1", cx=33.6, cy=20.4)
s.commit()
