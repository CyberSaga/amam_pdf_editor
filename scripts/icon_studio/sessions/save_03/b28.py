"""Batch 28 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

from studio import Studio, PROCESS_LAYERS

s = Studio.open()
s.begin(7, "調整收尾：擦掉草稿與輔助線，點上最後的高光",
        "調整後擋板與倉鼠都清楚了。畫面上還留著鉛筆草稿、構造線和紅色比例刻度，蓋在完成稿上會讓邊緣發糊。",
        "依序擦掉輔助線、紅色刻度、草稿線；最後在本體左上光澤、擋板反光與槽孔上各點一顆小星芒高光收尾。",
        tempo="normal")
order = sorted((e for e in s.elements.values() if e["layer"] in PROCESS_LAYERS),
               key=lambda e: (e["layer"] != "guides", -e["z"]))
for e in order:
    s.rm(e["id"], note="擦除草稿" if e is order[0] else None)
def star(cx, cy, r, k=0.22):
    pts = []
    import math
    for i in range(8):
        a = math.radians(-90 + i * 45)
        rr = r if i % 2 == 0 else r * k
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + "Z"
s.add("glint_star_body", "path", "glint", d=star(146.5, 125.5, 5.2), fill="#FFFFFF", fill_opacity=0.95, anim="pop")
s.add("glint_star_shutter", "path", "glint", d=star(213.5, 121.5, 3.6), fill="#FFFFFF", fill_opacity=0.9, anim="pop")
s.add("glint_star_slot", "path", "glint", d=star(277.6, 140.2, 2.2), fill="#FFFFFF", fill_opacity=0.85, anim="pop")
s.layer("sketch", opacity=0)
s.commit(final_view=True, small=True, zooms=[(110, 90, 300, 330)])
