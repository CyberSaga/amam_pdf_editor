"""Batch 3 of the 35_文件資訊 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import LINE, PAPER_SHADE, PURPLE_LIGHT, WHITE, hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手、欄位與資訊章",
        "色塊：紙、頭、耳朵、圓章的大小關係對；頭的平底剛好落在紙上緣外框的頂上，兩隻大耳朵露出完整的圓，"
        "紙的右上留給折角，右下留給圓章。",
        "補上 03 的臉（k 0.78）；兩隻肉墊手搭在紙緣（紙的上層、白口鼻兩側）；4 列欄位：淺紫圓角標籤 4.5×2.6 加 2 px "
        "灰紫數值線，越往下越短（右下讓給圓章）；紙內側右、下緣一道淡紫灰陰影；圓章裡放白色 i："
        "圓點半徑 1.6、3 px 圓頭直線，中間留 1.4 px 紫色。",
        tempo="normal")
hamster_face48(s, "hf", 15.5, 12.0, 0.78, parts=("face",))
paws48(s, "hf_paws", [(10.5, 13.3), (20.5, 13.3)], k=0.85)
s.add("sheet_shade", "path", "object_fx", d="M32.25 21.25V41.1Q32.25 42.25 31.1 42.25H9.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw")
for i, (y, x1) in enumerate([(21.5, 29.5), (27.0, 27.5), (32.5, 24.0), (38.0, 22.0)]):
    s.add(f"key{i}", "rect", "object_fx", x=10.5, y=y - 1.3, width=4.5, height=2.6, rx=1.3, fill=PURPLE_LIGHT,
          anim="pop")
    s.add(f"val{i}", "path", "object_fx", d=f"M17.6 {y}H{x1}", fill="none", stroke=LINE, stroke_width=2.0,
          stroke_linecap="round", anim="draw")
s.add("info_dot", "circle", "badge", cx=36.5, cy=33.5, r=1.6, fill=WHITE, anim="pop")
s.add("info_stem", "path", "badge", d="M36.5 38V41", fill="none", stroke=WHITE, stroke_width=3,
      stroke_linecap="round", anim="draw")
s.commit(zooms=[(4, 0, 24, 18), (26, 26, 21, 21)])
