"""Batch 2 of the 07_操作物件 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEACH, WHITE, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、肚子、抱住控點的手、控點光澤",
        "色塊到位：框、四個控點、倉鼠的頭身腳；頭蓋住框右緣、右下控點壓在身體左上。倉鼠還沒有臉和肚子，"
        "手也還沒伸到控點上，四個控點是平塗的青綠。",
        "補白肚子與臉（k 0.67 的 48 格五官）；兩隻手掌拉成短手臂，從身體伸到右下控點的右緣、一上一下抱住控點"
        "（畫在控點上層）；四個控點的青綠內框左上各加一道 1 px、55% 白的光澤。",
        tempo="normal")
s.add("hm_belly", "ellipse", "hamster", cx=37.6, cy=38.0, rx=3.9, ry=4.9, fill=WHITE, anim="fill")
hamster48(s, "hm", 38.0, 24.6, 6.4, 5.7, k=0.67, parts=("face",))
for i, (x, y, rot) in enumerate(((33.6, 28.4, -10), (34.2, 35.0, 10))):
    s.add(f"hm_arm{i}", "ellipse", "front", cx=x, cy=y, rx=2.4, ry=1.5, fill=PEACH, stroke=INK, stroke_width=1.1,
          transform=f"rotate({rot} {x} {y})", anim="pop")
gloss = "".join(f"M{hx - 1.5} {hy + 0.5}V{hy - 1.5}H{hx + 0.5}" for hx, hy in ((9, 8), (31, 8), (9, 32), (31, 32)))
s.add("handle_gloss", "path", "glint", d=gloss, fill="none", stroke=WHITE, stroke_width=1, stroke_opacity=0.55,
      anim="draw")
s.commit()
