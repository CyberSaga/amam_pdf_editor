"""Batch 2 of the 16_矩形 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：筆從手掌長出來",
        "48 格版把右手掌移到筆的根部；24 格的右手掌（第 9–10 欄）還在筆尖左下方，筆和手之間隔著一格。",
        "右手掌右移一格到第 10–11 欄，正好在深藍筆尖下面，筆從手掌往右上斜出去。",
        tempo="normal")
s.look((8, 17, 6, 4), "筆和手分開")
s.mod("paw_peach", note="右手掌移到筆尖下", d=pix_d(["P......PP"], "P", 3, 19))
s.commit()
