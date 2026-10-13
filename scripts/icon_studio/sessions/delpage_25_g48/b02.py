"""Batch 2 of the 25_刪除頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER_SHADE, PEACH, RED, hamster48
from studio import Studio

TRASH_LINE = "#5E5C9C"
s = Studio.open()
s.begin(5, "48 格：叉叉、垃圾桶細節、臉與手",
        "大形和參考吻合：紙、垃圾桶、倉鼠的位置都對；紙上還空著，倉鼠沒有臉，手還沒伸到紙上。",
        "紅叉中心 (27, 21)、臂長 4.2：深紅 4.6 墊底、紅 3.0 在上，兩條墊底先畫，交叉處才會是紅的；垃圾桶加把手與三道直紋；"
        "倉鼠補臉，右手搭到紙上（在身體上層）；紙內側淡陰影。",
        tempo="normal")
arms = ("M22.8 16.8L31.2 25.2", "M31.2 16.8L22.8 25.2")
for i, d in enumerate(arms):
    s.add(f"x_dark{i}", "path", "object_fx", d=d, fill="none", stroke="#A9323A", stroke_width=4.6, stroke_linecap="round", anim="draw")
for i, d in enumerate(arms):
    s.add(f"x_red{i}", "path", "object_fx", d=d, fill="none", stroke=RED, stroke_width=3.0, stroke_linecap="round", anim="draw")
s.add("sheet_shade", "path", "object_fx", d="M35.25 12.25V38.1Q35.25 39.25 34.1 39.25H19.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw", z=0.5)
s.add("can_handle", "path", "badge", d="M34.75 31.75V30.5Q34.75 29.75 35.5 29.75H38.5Q39.25 29.75 39.25 30.5V31.75",
      fill="none", stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="draw")
for i, x in enumerate((34.6, 37.0, 39.4)):
    s.add(f"can_line{i}", "path", "badge", d=f"M{x} 37.8V42.8", fill="none", stroke=TRASH_LINE, stroke_width=1.3,
          stroke_linecap="round", anim="draw")
s.add("hm_arm", "ellipse", "front", cx=17.6, cy=28.0, rx=3.1, ry=1.6, fill=PEACH, stroke=INK, stroke_width=1.1,
      transform="rotate(-18 17.6 28)", anim="pop", z=s.elements["hm_belly"]["z"] + 0.5)
hamster48(s, "hm", 10.5, 15.2, 6.8, 6.0, layer="front", k=0.72, parts=("face",))
s.commit()
