"""Batch 2 of the 16_矩形 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "16 格：筆從手掌長出來",
        "48、24 格版都把右手掌移到筆的根部；16 格的右手掌（第 7 欄）離筆尖還有兩格，看起來是一顆散落的桃色點。",
        "右手掌移到第 9 欄，正好在筆尖下面，筆從手掌往右上斜出去。",
        tempo="normal")
s.look((6, 11, 5, 3), "筆和手分開")
s.mod("paw_peach", note="右手掌移到筆尖下", d=pix_d(["P......P"], "P", 2, 13))
s.commit()
