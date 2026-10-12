"""Batch 11 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
from studio import Studio
from geo import body_outline_d, rrect_d, f

INK = "#1E1D38"
s = Studio.open()
s.begin(5, "細化結構：上墨線（本體、擋板、槽孔、標籤窗）",
        "明暗關係建立後，形體邊界仍靠淡鉛筆線，放大看邊緣是軟的、不確定的。參考圖有一圈很有份量的深藍黑描邊，是這套圖示的辨識特徵。",
        "用深藍黑 #1E1D38 上墨：本體 5.0、標籤窗 4.2、擋板 4.0、槽孔 3.2；擋板描邊做成開口路徑，兩端接進本體上緣；背光側（右、下）再補一道細線加重，做出手繪墨線的粗細變化。草稿層再調淡。",
        tempo="normal")
P = s.params["P"]
x0, y0, x1, y1, r, ch, rch = P["body"]
s.add("ink_body", "path", "ink", d=body_outline_d(x0, y0, x1, y1, r, ch, rch), fill="none",
      stroke=INK, stroke_width=5, stroke_linejoin="round", anim="draw")
sx0, sy0, sx1, sy1, sr = P["shutter"]
d = (f"M{sx0} {sy0}L{sx0} {sy1 - sr}A{sr} {sr} 0 0 0 {sx0 + sr} {sy1}"
     f"L{sx1 - sr} {sy1}A{sr} {sr} 0 0 0 {sx1} {sy1 - sr}L{sx1} {sy0}")
s.add("ink_shutter", "path", "ink", d=d, fill="none", stroke=INK, stroke_width=4,
      stroke_linejoin="round", stroke_linecap="round", anim="draw")
s.add("ink_slot", "path", "ink", d=rrect_d(*P["slot"]), fill="none", stroke=INK, stroke_width=3.2, anim="draw")
s.add("ink_label", "path", "ink", d=rrect_d(*P["label"]), fill="none", stroke=INK, stroke_width=4.2, anim="draw")
# weight on the shadow side: bottom-right of the body, just inside the main line
t = rch * math.tan(math.radians(22.5))
heavy = (f"M{f(x1 - 1.6)} {f(y0 + ch + t + 6)}L{f(x1 - 1.6)} {f(y1 - r)}"
         f"A{f(r - 1.6)} {f(r - 1.6)} 0 0 1 {f(x1 - r)} {f(y1 - 1.6)}L{f(x0 + r + 10)} {f(y1 - 1.6)}")
s.add("ink_body_heavy", "path", "ink", d=heavy, fill="none", stroke=INK, stroke_width=2.2,
      stroke_linecap="round", stroke_linejoin="round", anim="draw")
# shutter: heavier at the bottom edge (it overhangs the body)
heavy2 = f"M{f(sx0 + sr)} {f(sy1 - 1.2)}L{f(sx1 - sr)} {f(sy1 - 1.2)}"
s.add("ink_shutter_heavy", "path", "ink", d=heavy2, fill="none", stroke=INK, stroke_width=1.8,
      stroke_linecap="round", anim="draw")
s.layer("sketch", opacity=0.45, note="上墨後草稿層再調淡")
s.layer("guides", opacity=0.6)
s.commit(zooms=[(110, 90, 300, 330), (300, 96, 100, 90)])
