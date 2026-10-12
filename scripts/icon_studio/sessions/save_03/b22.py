"""Batch 22 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

from studio import Studio
from geo import rrect_d, rrect_pts, poly_d, inner_band, f

s = Studio.open()
s.begin(5, "觀察修正紙纖維；加入本體的模具細節",
        "紙纖維太明顯，看起來像紙上沾了毛髮和灰塵，反而髒。本體下方左右兩角是大片空白紫色，真實的 3.5 吋磁碟這裡有防寫滑塊窗與高密度孔。",
        "紙纖維與纖維點不透明度降到約一半、顏色更淡；在本體左下、右下各開一個小方孔：凹陷的深色底、左上內緣陰影、右下內緣反光、細描邊；左孔內放一片防寫滑塊。對比壓低，不和倉鼠搶焦點。",
        tempo="normal")
s.look((180, 248, 150, 100), "紙纖維像灰塵")
for eid in sorted(e for e in s.elements if e.startswith(("lbtx_fib", "lbtx_dot"))):
    a = s.elements[eid]["attrs"]
    if eid.startswith("lbtx_fib"):
        s.mod(eid, stroke_opacity=round(float(a["stroke-opacity"]) * 0.5, 2), stroke="#DCDAE9")
    else:
        s.mod(eid, fill_opacity=round(float(a["fill-opacity"]) * 0.45, 2))
holes = {"wp": (146.0, 368.0, 160.0, 382.0), "hd": (352.0, 368.0, 366.0, 382.0)}
s.params["holes"] = holes
for name, (hx0, hy0, hx1, hy1) in holes.items():
    pts = rrect_pts(hx0, hy0, hx1, hy1, 2.2, seg=6)
    g = s.gradient(f"g_hole_{name}", "linear", [(0, "#2D2766", 1), (1, "#4A428E", 1)], gradientUnits="userSpaceOnUse",
                   x1=hx0, y1=hy0, x2=hx1, y2=hy1)
    s.add(f"mold_{name}_base", "path", "body_fx", d=rrect_d(hx0, hy0, hx1, hy1, 2.2), fill=g, anim="fill")
    if name == "wp":
        s.add("mold_wp_slider", "path", "body_fx", d=rrect_d(hx0 + 1.6, hy0 + 7.2, hx1 - 1.6, hy1 - 1.6, 1.2),
              fill="#C9C5E6", anim="fill")
        s.add("mold_wp_slider_hl", "path", "body_fx", d=f"M{f(hx0 + 2.6)} {f(hy0 + 8.2)}L{f(hx1 - 2.6)} {f(hy0 + 8.2)}",
              fill="none", stroke="#FFFFFF", stroke_width=0.8, stroke_opacity=0.8, stroke_linecap="round", anim="draw")
    s.add(f"mold_{name}_shadow", "path", "body_fx", d=poly_d(inner_band(pts, 1.4, 1.8)), fill="#16133D", fill_opacity=0.55, anim="glaze")
    s.add(f"mold_{name}_rim", "path", "body_fx", d=poly_d(inner_band(pts, -1.1, -1.3)), fill="#C4BDF2", fill_opacity=0.55, anim="glaze")
    s.add(f"mold_{name}_edge", "path", "body_fx", d=rrect_d(hx0, hy0, hx1, hy1, 2.2), fill="none", stroke="#231F4F",
          stroke_width=1.0, stroke_opacity=0.75, anim="draw")
    # outer lip catching light on the lower-right outside edge
    s.add(f"mold_{name}_lip", "path", "body_fx",
          d=f"M{f(hx0 + 2)} {f(hy1 + 1.2)}L{f(hx1 - 0.5)} {f(hy1 + 1.2)}Q{f(hx1 + 1.2)} {f(hy1 + 1.2)} {f(hx1 + 1.2)} {f(hy1 - 0.5)}L{f(hx1 + 1.2)} {f(hy0 + 2)}",
          fill="none", stroke="#B8AFF0", stroke_width=0.8, stroke_opacity=0.7, stroke_linecap="round", anim="draw")
s.commit(zooms=[(130, 350, 60, 48), (330, 350, 60, 48), (170, 236, 172, 130)])
