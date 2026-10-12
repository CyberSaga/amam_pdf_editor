"""Batch 24 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import random
from shapely.geometry import Point, Polygon
from studio import Studio
from geo import body_outline_d, body_outline_pts, rrect_pts
from brush import offset_ring, runs, pressure_d

s = Studio.open()
s.begin(5, "細化空間：柔化投影、接觸陰影、卡片倒角與紙感",
        "第 8 批留下的問題還在：磁碟投影是四層硬邊疊出來的，右側切角處看得到階梯；磁碟底邊和卡片之間沒有接觸陰影，看起來有點浮。卡片本身是光滑的白色塊。",
        "投影改成八層、每層更淡、偏移與擴張更連續，階梯消失；底邊加一道很窄的深色接觸陰影；卡片內緣上方加白色倒角高光、下方加淡紫背光；卡片空白處撒極淡的紙紋顆粒。",
        tempo="fast")
P = s.params["P"]
x0, y0, x1, y1, r, ch, rch = P["body"]
s.look((370, 120, 50, 290), "投影有階梯")
layers = [(2.0, 2.8, 0.0, 0.07), (3.6, 5.0, 0.8, 0.06), (5.2, 7.2, 1.7, 0.05), (6.8, 9.4, 2.7, 0.042),
          (8.4, 11.6, 3.8, 0.035), (10.0, 13.8, 5.0, 0.028), (11.8, 16.0, 6.3, 0.022), (13.8, 18.4, 7.8, 0.016)]
for i, (dx, dy, e, op) in enumerate(layers):
    d = body_outline_d(x0 + dx - e, y0 + dy - e, x1 + dx + e, y1 + dy + e, r + e, ch, rch + e * 0.5)
    if i < 4:
        s.mod(f"cast{i}", note="投影四層 → 八層連續" if i == 0 else None, d=d, fill_opacity=op)
    else:
        s.add(f"cast{i}", "path", "cast", d=d, fill="#3F3878", fill_opacity=op, anim="glaze")
s.add("cast_contact", "path", "cast", d=body_outline_d(x0 + 0.6, y0 + 1.6, x1 + 1.2, y1 + 2.2, r, ch, rch),
      fill="#231E4E", fill_opacity=0.28, anim="glaze")
rng = random.Random(2401)
cx0, cy0, cx1, cy1, cr = P["card"]
card_pts = rrect_pts(cx0, cy0, cx1, cy1, cr, seg=10)
ring = offset_ring(card_pts, 3.2, step=2.0)
top = runs(ring, lambda x, y: y < cy0 + 26)
top.sort(key=len, reverse=True)
s.add("card_bevel_top", "path", "card", d=pressure_d(top[0], 2.2, rng, taper=0.2), fill="#FFFFFF", fill_opacity=0.95, anim="draw")
bot = runs(ring, lambda x, y: y > cy1 - 26)
bot.sort(key=len, reverse=True)
s.add("card_bevel_bottom", "path", "card", d=pressure_d(bot[0], 2.4, rng, taper=0.2), fill="#D9D5EA", fill_opacity=0.7, anim="draw")
card = Polygon(card_pts).buffer(-5)
floppy = Polygon(body_outline_pts(x0 - 4, y0 - 4, x1 + 18, y1 + 22, r, ch, rch, seg=6))
vis = card.difference(floppy)
minx, miny, maxx, maxy = vis.bounds
n = 0
while n < 138:
    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
    if not vis.contains(Point(x, y)):
        continue
    s.add(f"ctx_g{n:03d}", "circle", "card", cx=round(x, 2), cy=round(y, 2), r=round(rng.uniform(0.3, 0.7), 2),
          fill=rng.choice(["#D6D2E8", "#CFCBE3", "#E0DDEE"]), fill_opacity=round(rng.uniform(0.25, 0.5), 2), anim="pop")
    n += 1
s.commit(zooms=[(330, 100, 120, 330), (60, 20, 200, 120)])
