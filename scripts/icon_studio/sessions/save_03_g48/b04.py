"""Batch 4 of the 03_儲存 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(4, "48 格：最少量的光影",
        "臉部在 1× 讀得出來；但本體、擋板都是平塗，和 1.5×、2× 時精細版的立體感差距明顯。",
        "只加四筆光影：本體左上一道白色高光、右下一道深紫背光邊、擋板下緣淡灰的金屬陰影與一條垂直反光、槽孔內左緣一條亮線。底部的防寫孔在 48 px 只有 2 格，會像髒點，不畫。",
        tempo="normal")
s.add("gloss", "path", "glint", d="M9.7 17V10.6Q9.7 7.7 12.6 7.7H14.4", fill="none", stroke="#FFFFFF",
      stroke_width=1.2, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
s.add("shade", "path", "body_fx", d="M38.35 14.5V38.6Q38.35 40.35 36.6 40.35H11.5", fill="none", stroke="#6A5EB6",
      stroke_width=1.5, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
s.add("shutter_shade", "rect", "shutter", x=16.5, y=15.6, width=15, height=1.9, fill="#D3D3E0", anim="fill")
s.add("shutter_sheen", "rect", "shutter", x=18.6, y=6.6, width=1.3, height=9, fill="#FFFFFF", fill_opacity=0.9, anim="fill")
s.add("slot_glint", "path", "shutter", d="M26.9 9.2V13.8", fill="none", stroke="#7D84BE", stroke_width=0.8,
      stroke_linecap="round", anim="draw")
s.commit()
