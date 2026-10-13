"""Batch 4 of the 30_合併PDF 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import grow_ears, move_to_layer
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這隻的耳朵是半徑 2.04 的小圓，大半藏在圓頂後面，"
        "只在頭頂露出一小片，看起來像沒有耳朵。",
        "耳朵改用 BIG_EARS：半徑 1.6 倍，圓心往外 0.7k、往上 0.35k，露出的耳朵約寬 1.6 倍、高 1.75 倍，"
        "兩耳在頭頂仍分開；粉色內耳一起放大。放大後兩耳頂到上面兩張 PDF 的下角、被紙蓋掉一半，夾在紙和箭頭之間很亂；兩張紙改畫在倉鼠後面，耳朵整個蓋在紙角前面。",
        tempo="normal")
s.look((16.1, 17.6, 15.8, 7.1), "耳朵太小")
grow_ears(s, "hb", note="耳朵放大 1.6 倍")
s.look((15, 17, 18, 8), "耳朵被紙角蓋掉")
move_to_layer(s, ["page0", "page0_flap", "page1", "page1_flap"], "back", note="兩張紙放到倉鼠後面")
s.commit()
