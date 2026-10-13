"""Batch 3 of the 08_復原 48 px grid design. Run via run_session.py."""
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
s.begin(6, "48 格：倉鼠改成從箭頭上緣探頭",
        "1× 實際大小：下巴的框線、右手的框線和箭頭上緣三條深藍線擠在 3 格之內，臉下面糊成一團黑；身體只露出一小塊，"
        "看不出是身體。草稿試了四種：頭往右上移、拿掉右手都還是擠，只有讓下巴藏到箭頭後面最乾淨。",
        "倉鼠頭下移到 (27.4, 14)、稍放大（k 0.8）、傾斜收為 10°，下半藏在箭頭後面，由箭頭上緣當下輪廓；身體與肚子拿掉；"
        "左手搭在頭部後緣的台階、右手搭在彎弧上緣；箭頭整支上移 1.5 格，上下留白平均。",
        tempo="normal")
s.look((15, 12, 20, 10), "下巴、右手、箭頭上緣擠成一團")
s.mod("arrow", note="箭頭上移 1.5 格",
      d=undo_arrow_d(9.5, 24, 17.5, 20.25, 19.75, 28.25, 26.75, 12.75, 11.75, 66, 26.75))
s.mod("arrow_gloss", d="M14.3 23.3L17.75 20.5M22.75 22.25H26.75A10.25 9.25 0 0 1 36.4 28.35")
s.rm("hm_belly", note="身體藏到箭頭後面")
s.rm("hm_body")
c = _Collect()
hamster48(c, "hm", 27.4, 14.0, 7.4, 6.6, k=0.8, rot=10)
for i, (eid, attrs) in enumerate(c.attrs.items()):
    s.mod(eid, note="頭下移、下巴藏到箭頭後面" if i == 0 else None, **attrs)
s.mod("hm_paw0", note="左手搭在頭部後緣的台階", cx=21.9, cy=18.4)
s.mod("hm_paw1", note="右手搭在彎弧上緣", cx=33.6, cy=20.0)
s.commit(compare=True)
