"""Batch 4 of the 22_添加浮水印 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import grow_ears, shift_ids
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這隻的耳朵是半徑 1.8 的小圓，大半藏在圓頂後面，"
        "只在頭頂露出一小片，看起來像沒有耳朵。",
        "耳朵改用 BIG_EARS：半徑 1.6 倍，圓心往外 0.7k、往上 0.35k，露出的耳朵約寬 1.6 倍、高 1.75 倍，"
        "兩耳在頭頂仍分開；粉色內耳一起放大。放大後耳朵頂出畫布上緣 0.8 格、耳尖的深藍外框被切掉；倉鼠和手上的印章一起往下 1 格（印章多壓進紙裡一格），紙和加號徽章不動（底下沒有空間）。",
        tempo="normal")
s.look((2.8, 0, 14.4, 6.6), "耳朵太小")
grow_ears(s, "hf", note="耳朵放大 1.6 倍")
s.look((0, 0, 24, 24), "耳朵頂出畫布上緣")
shift_ids(s, [e for e in s.elements if e.startswith(("hf_", "stamp_"))], 0, 1, note="倉鼠和印章往下 1 格")
s.commit()
