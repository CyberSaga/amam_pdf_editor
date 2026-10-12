"""Batch 15 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
import random
from shapely.geometry import Polygon
from studio import Studio
from brush import offset_ring, runs, pressure_d, sub_run

s = Studio.open()
s.begin(5, "觀察修正：倒角高光重畫",
        "放大檢查發現三個問題：①左上高光弧的點排序錯誤，路徑自己閉合成一個白色三角形；②分段的倒角筆觸兩端都收尖，排在一起像一串珠子；③光澤帶與暗部是硬邊多邊形，在紫色面上留下一道像折痕的斜線。",
        "擦掉分段筆觸，改成沿邊緣一筆到底、帶壓力變化的連續筆觸，亮度用「長而淡 + 短而亮」疊色在左上角堆出漸層；高光弧按輪廓順序取點；光澤與暗部改用線性漸層的柔邊罩染。",
        tempo="normal")
P = s.params["P"]
x0, y0, x1, y1, r, ch, rch = P["body"]
body = Polygon(s.params["body_poly"])
s.look((128, 104, 70, 70), "高光弧閉合成三角形")
s.look((126, 120, 16, 260), "倒角筆觸像串珠")
for eid in [e for e in list(s.elements) if e.startswith(("bfx_lit", "bfx_shd", "bfx_bounce"))] + ["bfx_gloss_arc"]:
    s.rm(eid)
rng = random.Random(1501)
ring = offset_ring(list(body.exterior.coords), 6.0, step=2.0)
SH_L, SH_R = 189, 323
lit_runs = runs(ring, lambda x, y: (x < x0 + 14 and y < y1 - r - 4) or (y < y0 + 14 and (x < SH_L or x > SH_R))
                or (x > x1 - ch - 8 and y < y0 + ch + 8 and x < x1 - 9))
shade_runs = runs(ring, lambda x, y: (x > x1 - 14 and y > y0 + ch + 2) or (y > y1 - 14 and x > x0 + r - 4))
lit_runs.sort(key=len, reverse=True)
main = lit_runs[0]  # left edge -> top-left corner -> top edge (up to the shutter)
# orient main run so it starts at the bottom of the left edge
if main[0][1] < main[-1][1]:
    main = main[::-1]
s.add("bfx_lit_base", "path", "body_fx", d=pressure_d(main, 2.2, rng), fill="#FFFFFF", fill_opacity=0.32, anim="draw")
# corner accents: shorter, brighter strokes stacked toward the corner
ci = min(range(len(main)), key=lambda i: math.hypot(main[i][0] - x0, main[i][1] - y0))
cn = ci / (len(main) - 1)
for k, (span, w, op) in enumerate([(0.42, 2.4, 0.28), (0.26, 2.7, 0.3), (0.13, 3.1, 0.38)]):
    seg = sub_run(main, max(0, cn - span), min(1, cn + span * 0.8))
    s.add(f"bfx_lit_acc{k}", "path", "body_fx", d=pressure_d(seg, w, rng, taper=0.3), fill="#FFFFFF",
          fill_opacity=op, anim="draw")
for k, run in enumerate(lit_runs[1:]):
    if len(run) >= 4:
        s.add(f"bfx_lit_side{k}", "path", "body_fx", d=pressure_d(run, 2.0, rng, taper=0.3), fill="#FFFFFF",
              fill_opacity=0.26 if k == 0 else 0.2, anim="draw")
shade_runs.sort(key=len, reverse=True)
sh = shade_runs[0]
s.add("bfx_shade_base", "path", "body_fx", d=pressure_d(sh, 3.0, rng), fill="#4A3F98", fill_opacity=0.3, anim="draw")
ci = min(range(len(sh)), key=lambda i: math.hypot(sh[i][0] - x1, sh[i][1] - y1))
cn = ci / (len(sh) - 1)
for k, (span, w, op) in enumerate([(0.3, 3.2, 0.18), (0.14, 3.6, 0.2)]):
    seg = sub_run(sh, max(0, cn - span), min(1, cn + span))
    s.add(f"bfx_shade_acc{k}", "path", "body_fx", d=pressure_d(seg, w, rng, taper=0.35), fill="#40358E",
          fill_opacity=op, anim="draw")
ring3 = offset_ring(list(body.exterior.coords), 3.5, step=2.0)
bounce = runs(ring3, lambda x, y: y > y1 - 6 and x0 + r < x < x1 - r)
bounce.sort(key=len, reverse=True)
s.add("bfx_bounce", "path", "body_fx", d=pressure_d(bounce[0], 1.5, rng, taper=0.25), fill="#DCD7FB",
      fill_opacity=0.5, anim="draw")
# gloss arc in ring order around the top-left corner
arc_pts = sub_run(main, max(0, (ci0 := min(range(len(main)), key=lambda i: math.hypot(main[i][0] - x0, main[i][1] - y0))) / (len(main) - 1) - 0.09),
                  min(1, ci0 / (len(main) - 1) + 0.07))
ring_g = offset_ring(list(body.exterior.coords), 7.5, step=1.5)
g_run = [p for p in runs(ring_g, lambda x, y: (x < x0 + 40 and y < y0 + 46))][0]
if g_run[0][1] < g_run[-1][1]:
    g_run = g_run[::-1]
s.mod("bfx_sheen", note="硬邊光澤 → 柔邊漸層", fill=s.gradient("g_sheen", "linear",
      [(0, "#FFFFFF", 0), (0.5, "#FFFFFF", 0.16), (1, "#FFFFFF", 0)], gradientUnits="userSpaceOnUse",
      x1=x0 + 20, y1=y0 + 20, x2=x0 + 75, y2=y0 + 75), fill_opacity=1)
s.mod("bfx_sheen2", fill=s.gradient("g_sheen2", "linear",
      [(0, "#FFFFFF", 0), (0.5, "#FFFFFF", 0.12), (1, "#FFFFFF", 0)], gradientUnits="userSpaceOnUse",
      x1=x0 + 32, y1=y0 + 32, x2=x0 + 58, y2=y0 + 58), fill_opacity=1)
s.mod("bfx_core", fill=s.gradient("g_core", "linear",
      [(0, "#3B3282", 0), (1, "#3B3282", 0.2)], gradientUnits="userSpaceOnUse",
      x1=x0 + 190, y1=y0 + 190, x2=x1, y2=y1), fill_opacity=1)
s.add("bfx_gloss_arc", "path", "body_fx", d=pressure_d(g_run, 3.2, rng, taper=0.35), fill="#FFFFFF",
      fill_opacity=0.85, anim="draw")
s.commit(zooms=[(120, 100, 150, 150), (280, 280, 110, 125)])
