"""Batch 19 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import re
from studio import Studio
from geo import f

s = Studio.open()
s.begin(5, "觀察修正：移除雀斑、交界毛太像睫毛",
        "使用者回饋：臉頰上的棕色小點看起來像雀斑。自己放大檢查也發現：杏白交界的短毛太亮、太規律，排成一整排像睫毛梳；頭頂與左上的深杏色毛有幾根彎得太大，像眉毛。",
        "擦掉鬍鬚根部的棕色小點；交界毛縮短到 0.72、變細、降低不透明度；深色毛的彎度減半、不透明度降低，讓毛流退到「看近才看得到」的層次。",
        tempo="rapid")
s.look((206, 326, 22, 18), "使用者回饋：移除雀斑")
for eid in sorted(e for e in s.elements if e.startswith("hm_pore")):
    s.rm(eid, note="移除雀斑（棕色小點）")
num = r"(-?\d+(?:\.\d+)?)"
pat = re.compile(rf"M{num} {num}Q{num} {num} {num} {num}")

def parse(d):
    m = pat.fullmatch(d)
    return [float(v) for v in m.groups()]

s.look((196, 316, 120, 24), "交界毛像一排睫毛")
for eid in sorted(e for e in s.elements if e.startswith("fur_bd")):
    a = s.elements[eid]["attrs"]
    x0, y0, cx, cy, x2, y2 = parse(a["d"])
    k = 0.72
    nx2, ny2 = x0 + (x2 - x0) * k, y0 + (y2 - y0) * k
    ncx, ncy = x0 + (cx - x0) * k, y0 + (cy - y0) * k
    s.mod(eid, d=f"M{f(x0)} {f(y0)}Q{f(ncx)} {f(ncy)} {f(nx2)} {f(ny2)}",
          stroke_width=round(float(a["stroke-width"]) * 0.72, 2),
          stroke_opacity=round(float(a["stroke-opacity"]) * 0.6, 2))
for eid in sorted(e for e in s.elements if e.startswith("fur_sh")):
    a = s.elements[eid]["attrs"]
    x0, y0, cx, cy, x2, y2 = parse(a["d"])
    mx, my = (x0 + x2) / 2, (y0 + y2) / 2
    ncx, ncy = mx + (cx - mx) * 0.5, my + (cy - my) * 0.5
    s.mod(eid, d=f"M{f(x0)} {f(y0)}Q{f(ncx)} {f(ncy)} {f(x2)} {f(y2)}",
          stroke_opacity=round(float(a["stroke-opacity"]) * 0.75, 2))
s.commit(zooms=[(176, 250, 160, 112), (190, 300, 70, 56)])
