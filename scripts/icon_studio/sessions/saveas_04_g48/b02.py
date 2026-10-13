"""Batch 2 of the 04_另存新檔 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PEACH, badge_plus, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：磁片的光影、字線、臉與加號",
        "磁片和倉鼠的大形與參考吻合；磁片還是平的，標籤空白，倉鼠沒有臉。",
        "照儲存版：右下內側深紫陰影線、左上白色光、擋板下緣陰影與反光；標籤上兩條淡紫字線；倉鼠補臉、右手抱住磁片左緣（磁片上層）；"
        "加號章中心 (37.5, 35.5)。",
        tempo="normal")
s.add("shade", "path", "object_fx", d="M39.9 12.6V32.4Q39.9 33.9 38.4 33.9H18.4", fill="none", stroke="#6A5EB6",
      stroke_width=1.2, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
s.add("gloss", "path", "glint", d="M18.6 14.2V9.6Q18.6 7.4 20.8 7.4H21.4", fill="none", stroke="#FFFFFF", stroke_width=1.0,
      stroke_opacity=0.55, stroke_linecap="round", anim="draw")
s.add("shutter_shade", "rect", "object_fx", x=23.4, y=13.0, width=11.2, height=1.5, fill="#D3D3E0", anim="fill")
s.add("shutter_sheen", "rect", "object_fx", x=25.0, y=6.4, width=1.0, height=6.6, fill="#FFFFFF", fill_opacity=0.9, anim="fill")
for i, (y, x1) in enumerate(((24.6, 34.2), (28.0, 31.4))):
    s.add(f"label_line{i}", "path", "object_fx", d=f"M23.8 {y}H{x1}", fill="none", stroke=LINE, stroke_width=1.5,
          stroke_linecap="round", anim="draw")
s.add("hm_arm", "ellipse", "front", cx=16.6, cy=28.6, rx=2.6, ry=1.5, fill=PEACH, stroke=INK, stroke_width=1.0,
      transform="rotate(-15 16.6 28.6)", anim="pop")
hamster48(s, "hm", 9.8, 17.6, 6.6, 5.8, k=0.7, rot=-10, parts=("face",))
badge_plus(s, "badge", 48, 37.5, 35.5)
s.commit()
