"""Batch 2 of the 23_浮水印列表 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "16 格：水滴不要像加號",
        "1× 看：4×5 的水滴兩側對稱突出，讀起來是一個加號，會和「新增」的加號章混淆。",
        "改成 5 格寬、上尖下圓的水滴，顏色加深一階，左側留一格白色反光。",
        tempo="normal")
s.look((2, 6, 7, 7), "水滴像加號")
s.mod("drop_fill", note="上尖下圓", d=pix_d(["..L..", ".LLL.", "LLLLL", "LLLLL", ".LLL."], "L", 3, 7), fill="#A99EE2")
s.add("drop_hl", "path", "object_fx", d="M4 9h1v1h-1Z", fill="#FFFFFF", anim="pop")
s.commit()
