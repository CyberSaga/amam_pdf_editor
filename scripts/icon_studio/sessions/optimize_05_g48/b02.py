"""Batch 2 of the 05_另存為最佳化的副本 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PAPER_SHADE, PURPLE, RED, block_arrow_d, hamster48, mirror_x_d, paw48, pdf_mark_d
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：PDF 標誌、壓縮箭頭、臉與手",
        "紙和倉鼠的位置對齊參考；紙面還是空的。",
        "紅色緞帶標誌 14×14.6、1.7 px（從參考描出三個圈的單筆路徑）；下面兩條淡紫線；左右紫色小箭頭（1.25 px 深藍框）尖端各離紙 1.5 格；"
        "倉鼠補臉、兩隻手掌搭在紙緣；紙內側淡陰影。",
        tempo="normal")
s.add("pdf_mark", "path", "object_fx", d=pdf_mark_d(17.4, 21.2, 13.6, 14.6), fill="none", stroke=RED, stroke_width=1.7,
      stroke_linejoin="round", anim="draw")
for i, y in enumerate((38.6, 41.2)):
    s.add(f"line{i}", "path", "object_fx", d=f"M18.5 {y}H29.5", fill="none", stroke=LINE, stroke_width=1.5,
          stroke_linecap="round", anim="draw")
s.add("sheet_shade", "path", "object_fx", d="M32.25 22.25V41.1Q32.25 42.25 31.1 42.25H16.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw", z=0.5)
left = block_arrow_d(3.75, 11.5, 30, 3.5, 8.5, 4.5)
s.add("arrow_l", "path", "front", d=left, fill=PURPLE, stroke=INK, stroke_width=1.25, stroke_linejoin="round", anim="fill")
s.add("arrow_r", "path", "front", d=mirror_x_d(left, 48), fill=PURPLE, stroke=INK, stroke_width=1.25,
      stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 24.5, 9.4, 6.6, 5.8, k=0.68, eye_y=8.0, parts=("face",))
paw48(s, "hm_paw0", 20.0, 14.2, layer="front", k=0.8)
paw48(s, "hm_paw1", 29.0, 14.2, layer="front", k=0.8)
s.commit()
