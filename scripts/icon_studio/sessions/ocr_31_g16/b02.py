"""Batch 2 of the 31_OCR（文字辨識） 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "16 格：T 拉高一列",
        "1× 看：T 只有 9×5，和 7×5 的臉一樣高，臉的顏色又多，16 px 時倉鼠比 T 搶眼；最下面一列除了角框是空的。",
        "T 的直畫多一列，腳落到 y 15（和下方角框同一列），T 變成 9×6；臉、掃描線不動。",
        tempo="normal")
s.look((2, 9, 11, 7), "T 和臉一樣大")
s.mod("letter_t_ink", note="T 拉高一列",
      d=pix_d(["NNNNNNNNN", "N..NNN..N", "...NNN...", "...NNN...", "...NNN...", "..NNNNN.."], "N", 3, 10))
s.commit()
