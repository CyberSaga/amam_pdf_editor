"""Batch 2 of the 03_儲存 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import body_outline_d, rrect_d
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(2, "16 格：大形（每條框線剛好 1 格）",
        "和 24 格版縮到 16 格對照：比例一致；但 24 格版的槽孔在第 9 欄，到了 16 格會貼住擋板右框。",
        "所有框線 1 px、路徑放在 .5 座標（框線剛好佔滿一格）；槽孔放第 8 欄、1×2 格，右邊留一欄白；標籤窗 8×6 格（內白 6×4）。",
        tempo="normal")
s.look((7.5, 1.5, 3, 3), "槽孔要離開右框一欄")
s.add("floppy", "path", "body", d=body_outline_d(2.5, 1.5, 13.5, 14.5, 1.0, 2.6, 0.4), fill="#9285D5",
      stroke=INK, stroke_width=1, stroke_linejoin="round", anim="fill")
s.add("shutter_plate", "path", "shutter", d=rrect_d(5.5, 1.5, 10.5, 5.5, 0.5), fill="#F7F7FA",
      stroke=INK, stroke_width=1, stroke_linejoin="round", anim="fill")
s.add("slot", "rect", "shutter", x=8, y=2, width=1, height=2, fill="#2E3052", anim="fill")
s.add("label_paper", "path", "label", d=rrect_d(4.5, 7.5, 11.5, 12.5, 0.6), fill="#FFFFFF",
      stroke=INK, stroke_width=1, stroke_linejoin="round", anim="fill")
s.layer("sketch", opacity=0.55)
s.commit()
