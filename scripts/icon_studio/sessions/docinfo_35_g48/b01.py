"""Batch 1 of the 35_文件資訊 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from geo import pts_d
from kit import pencil_ellipse, pencil_line
from studio import Studio

s = Studio.open()
s.begin(1, "48 格：構圖草稿",
        "新圖示，沒有參考圖：文件資訊打開 PDF 的標題、作者、主旨、關鍵字欄位。檔案分頁的鄰居是 04 另存新檔"
        "（倉鼠在左、加號圓章在右下）和 05 最佳化（倉鼠在紙的正上方）；整組的語彙是折角白紙、03 的圓頂倉鼠、"
        "紫色圓章（＋新增、－隱藏）。",
        "折角紙外緣 x 6–35、y 12–45（折角 7），紙上排 4 列欄位（標籤 + 數值線）；倉鼠從紙的左上緣探頭、"
        "兩手搭在紙緣；右下角一顆比加號章大的紫色資訊章（外半徑 8.5、中心 (36.5, 37.5)）放白色 i。"
        "倉鼠在左上、圓章在右下成一條對角線，和 05、26、28 分得開。",
        tempo="slow")
grid = "".join(f"M{i} 0V48M0 {i}H48" for i in range(49))
s.add("gd_pixels", "path", "guides", d=grid, fill="none", stroke="#78A6D8", stroke_width=0.05, stroke_opacity=0.5,
      anim="draw")
s.add("gd_keyline", "path", "guides", d=pts_d([(3, 3), (45, 3), (45, 45), (3, 45)], closed=True), fill="none",
      stroke="#D0605E", stroke_width=0.1, stroke_opacity=0.7, stroke_dasharray="0.8 0.6", anim="draw")
rng = random.Random(3548)
W, OP = 0.2, 0.55
for name, p0, p1 in [("t", (6.2, 12.2), (28, 12.1)), ("fold", (28, 12.1), (35, 19)), ("r", (35, 19), (34.9, 45)),
                     ("b", (34.9, 44.9), (6.1, 45)), ("l", (6.1, 45), (6.2, 12.2)), ("flap", (28, 12.2), (28.1, 19.1))]:
    pencil_line(s, f"sk_{name}", p0, p1, rng, w=W, op=OP, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 15.5, 9.0, 7.6, 4.8, rng, w=W, op=0.5, amp=0.1, a0=170, sweep=200)
for i, x in enumerate((10.5, 20.5)):
    pencil_ellipse(s, f"sk_ear{i}", x, 5.2, 3.7, 3.7, rng, w=W, op=0.45, amp=0.08)
for i, (y, x1) in enumerate([(21.5, 30.5), (27.0, 28.0), (32.5, 24.5), (38.0, 22.5)]):
    pencil_line(s, f"sk_row{i}", (10.5, y), (x1, y + 0.05), rng, w=W, op=0.45, amp=0.05, overshoot=0.03)
pencil_ellipse(s, "sk_badge", 36.5, 37.5, 8.5, 8.5, rng, w=W, op=0.5, amp=0.08)
s.commit()
