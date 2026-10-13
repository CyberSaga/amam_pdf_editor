"""Batch 2 of the 30_合併PDF 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEACH, PURPLE, arc_arrow, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：舉手、臉與匯流箭頭",
        "色塊位置和參考相符；倉鼠還沒有手，中間到紙疊之間空著。",
        "倉鼠補臉、雙手斜舉到兩張紙的下角（手臂在頭後面）；右箭頭：圓心 (27, 22)、半徑 8，從 0° 順時針到 65°，深藍包邊；"
        "左箭頭用鏡射畫，兩支箭頭尖端停在紙疊上方左右各一。",
        tempo="normal")
for i, (x, rot) in enumerate(((17.6, 32), (30.4, -32))):
    s.add(f"hm_arm{i}", "ellipse", "hamster", cx=x, cy=21.0, rx=1.7, ry=3.2, fill=PEACH, stroke=INK, stroke_width=1.1,
          transform=f"rotate({rot} {x} 21)", anim="pop", z=0.5 + i * 0.1)
hamster48(s, "hm", 24, 24.6, 6.8, 5.8, k=0.7, parts=("face",))
arc_arrow(s, "arrow_r", 27, 22, 8, 0, 65, "front", width=2.6, head_w=3.4, head_len=4.4, color=PURPLE, ink_width=1.2)
arc_arrow(s, "arrow_l", 27, 22, 8, 0, 65, "front", width=2.6, head_w=3.4, head_len=4.4, color=PURPLE, ink_width=1.2,
          transform="matrix(-1 0 0 1 48 0)")
s.commit()
