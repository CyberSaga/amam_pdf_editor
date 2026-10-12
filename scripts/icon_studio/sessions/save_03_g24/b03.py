"""Batch 3 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from studio import Studio

s = Studio.open()
s.begin(2, "24 格：在實際像素上修正擋板與標籤窗",
        "用 QtSvg 實際點陣化檢查 1×：槽孔落在半像素邊界，糊成一條 3 px 的灰柱；標籤窗 1.5 px 框的下緣和本體外框之間只剩半格紫色，兩條黑線幾乎黏在一起；左右紫邊也只有半格。",
        "擋板與標籤窗屬於次要結構，框線改 1 px（規格的細節線寬），路徑放在 .5 座標讓框線剛好佔滿一格；標籤窗內縮到 6–18 × 11–19，上下左右各留 1.5 格紫色；槽孔改到整數格 x 13–15、y 5–8，上下各留一排白。",
        tempo="normal")
s.look((12, 4, 3.5, 4), "槽孔糊成灰柱")
s.mod("slot", note="槽孔 → 整數格 2×3", x=13, y=5, width=2, height=3, rx=0.3)
s.look((5, 10.5, 14, 10), "標籤窗下框黏住外框")
s.mod("shutter_plate", note="擋板框 1.5 → 1 px", d=rrect_d(7.5, 2.5, 16.5, 9.5, 0.75), stroke_width=1)
s.mod("label_paper", note="標籤窗 → 6–18 × 11–19，框 1 px", d=rrect_d(6.5, 11.5, 17.5, 18.5, 1.0), stroke_width=1)
s.commit()
