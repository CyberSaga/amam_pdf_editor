"""Batch 3 of the 03_儲存 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(5, "16 格：倉鼠（6×4 格）",
        "標籤窗內白只剩 6×4 個像素。24 格版的經驗：深色一多，臉就糊成一團。",
        "不畫輪廓線：第 8 列兩個耳朵（各 2×1，偏粉的杏色）、第 9–11 列杏色圓頂、第 10 列兩顆 1×1 的眼睛（第 6、9 欄，對稱於中線）；鼻子、嘴、鬍鬚全部省略。杏色比 24 格版再深一階，才和白紙分得開。",
        tempo="normal")
for i, x in enumerate((5, 9)):
    s.add(f"ear{i}", "rect", "hamster", x=x, y=8, width=2, height=1.1, rx=0.45, fill="#E48F7A", anim="fill")
s.add("head", "path", "hamster", d="M5 12V10.15Q5 9 6.15 9H9.85Q11 9 11 10.15V12Z", fill="#F0AC68", anim="fill")
for i, x in enumerate((6, 9)):
    s.add(f"eye{i}", "rect", "hamster", x=x, y=10, width=1, height=1, fill=INK, anim="pop")
s.commit()
