"""Batch 2 of the 15_新增文字框 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48, paw48, plus_d
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、扒著框的手、加號、控點光澤",
        "色塊到位：倉鼠頭從框的上緣後面冒出、下半被白框擋住；T 在框中央，圓章壓在右下角。倉鼠沒有臉，"
        "看起來只是框上的一顆球；圓章裡還是空的。",
        "補臉（k 0.68，眼睛提到 y 7.8，鼻嘴都在框線上方）；兩隻手掌扒在框的上緣（畫在框的上層）；圓章內放 3 px 寬的白加號；"
        "三個控點和操作物件一樣，左上加一道 1 px、55% 白的光澤。",
        tempo="normal")
hamster48(s, "hm", 19.5, 9.0, 6.6, 5.8, k=0.68, eye_y=7.8, parts=("face",))
for i, x in enumerate((15.4, 23.6)):
    paw48(s, f"hm_paw{i}", x, 14.9, layer="front", k=0.85)
s.add("badge_plus", "path", "badge", d=plus_d(38.5, 39.5, 3.5, 3), fill=WHITE, anim="pop")
gloss = "".join(f"M{hx - 1.5} {hy + 0.5}V{hy - 1.5}H{hx + 0.5}" for hx, hy in ((9, 15), (39, 15), (9, 40)))
s.add("handle_gloss", "path", "glint", d=gloss, fill="none", stroke=WHITE, stroke_width=1, stroke_opacity=0.55,
      anim="draw")
s.commit()
