"""Batch 8 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

from studio import Studio
from geo import body_outline_d, rrect_d

s = Studio.open()
s.begin(4, "明暗關係：定光源、本體與投影",
        "目前是純平塗，像剪紙，沒有前後空間。參考圖本體左上偏亮偏紫、下方偏灰偏暗。",
        "光源定在左上。本體改線性漸層（左上亮紫 → 右下灰紫），卡片由白到極淡紫；磁碟在卡片上投出往右下的柔和陰影（四層逐漸放大、變淡，模擬模糊），卡片本身也有一圈很淡的落影。",
        tempo="normal")
P = s.params["P"]
g = s.gradient("g_body", "linear", [(0, "#A08BE8", 1), (0.5, "#9285D5", 1), (1, "#7E77C2", 1)],
               gradientUnits="userSpaceOnUse", x1=150, y1=110, x2=362, y2=398)
s.mod("body_base", note="平塗 → 左上亮、右下暗的漸層", fill=g)
gc = s.gradient("g_card", "linear", [(0, "#FFFFFF", 1), (1, "#F4F3FA", 1)],
                gradientUnits="userSpaceOnUse", x1=0, y1=26, x2=0, y2=482)
s.mod("card_base", fill=gc)
# card drop shadow (beneath card)
cx0, cy0, cx1, cy1, cr = P["card"]
z0 = s.elements["card_base"]["z"]
for i, (dy, grow, op) in enumerate([(3, 0.5, 0.07), (6, 1.5, 0.05), (10, 3, 0.035), (15, 5, 0.025)]):
    s.add(f"card_shadow{i}", "path", "card", z=z0 - 1 - i * 0.1,
          d=rrect_d(cx0 - grow, cy0 + dy - grow, cx1 + grow, cy1 + dy + grow, cr + grow),
          fill="#5B5486", fill_opacity=op, anim="glaze")
# floppy cast shadow on card (light from top-left -> shadow to bottom-right)
x0, y0, x1, y1, r, ch, rch = P["body"]
for i, (dx, dy, e, op) in enumerate([(3, 4, 0, 0.12), (6, 8, 1.5, 0.08), (9, 12, 3.5, 0.055), (13, 17, 6, 0.035)]):
    s.add(f"cast{i}", "path", "cast",
          d=body_outline_d(x0 + dx - e, y0 + dy - e, x1 + dx + e, y1 + dy + e, r + e, ch, rch + e * 0.5),
          fill="#3F3878", fill_opacity=op, anim="glaze")
s.commit(zooms=[(110, 90, 300, 330)])
