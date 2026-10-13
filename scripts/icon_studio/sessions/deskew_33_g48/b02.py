"""Batch 2 of the 33_拉正PDF頁面 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PURPLE, arc_arrow, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：拉正箭頭、臉與手",
        "紙、對齊框、虛線都到位；紙歪得剛好看得出來，紙面還空著。",
        "紫色箭頭：圓心 (22, 22)、半徑 12，從 120° 逆時針到 30°（用上下鏡射的順時針弧畫），尖端往右上，深藍包邊；倉鼠補臉、兩隻手掌搭在紙緣。",
        tempo="normal")
arc_arrow(s, "arrow", 22, 36, 12, 240, 330, "object_fx", width=2.6, head_w=3.4, head_len=4.4, color=PURPLE, ink_width=1.2,
          transform="matrix(1 0 0 -1 0 58)")
hamster48(s, "hm", 23.6, 11.6, 6.6, 5.8, k=0.68, eye_y=10.2, parts=("face",))
paw48(s, "hm_paw0", 19.2, 16.2, layer="front", k=0.8)
paw48(s, "hm_paw1", 28.0, 16.8, layer="front", k=0.8)
s.commit()
