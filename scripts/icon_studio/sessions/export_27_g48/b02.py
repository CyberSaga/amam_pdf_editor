"""Batch 2 of the 27_匯出頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER_SHADE, TEAL, block_arrow_d, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：箭頭、臉與收尾",
        "紙和倉鼠的位置與參考吻合；倉鼠身體露在紙右邊，等箭頭擋住下半。",
        "青綠箭頭：桿 7.5 高、箭頭 17.5 高，1.5 px 深藍外框的外緣落在整數格（桿 y 26/35、箭頭 y 21/40），尖端 x 39.5，"
        "放在最上層蓋過紙緣與倉鼠身體；桿上緣一道白色光；倉鼠補臉；紙內側淡陰影。",
        tempo="normal")
s.add("arrow", "path", "front", d=block_arrow_d(13.75, 39.5, 30.5, 7.5, 17.5, 11.5), fill=TEAL, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("arrow_gloss", "path", "front", d="M16 28.4H26", fill="none", stroke="#FFFFFF", stroke_width=1.2,
      stroke_opacity=0.6, stroke_linecap="round", anim="draw")
s.add("sheet_shade", "path", "object_fx", d="M27.25 12.25V41.1Q27.25 42.25 26.1 42.25H8.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw")
hamster48(s, "hm", 36.8, 17.6, 6.6, 5.8, k=0.7, rot=14, parts=("face",))
s.commit()
