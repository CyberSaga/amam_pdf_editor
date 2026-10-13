"""Batch 4 of the 13_快照 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import grow_ears, shift_ids
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這隻的耳朵是半徑 1.6 的小圓，大半藏在圓頂後面，"
        "只在頭頂露出一小片，看起來像沒有耳朵。",
        "耳朵改用 BIG_EARS：半徑 1.6 倍，圓心往外 0.7k、往上 0.35k，露出的耳朵約寬 1.6 倍、高 1.75 倍，"
        "兩耳在頭頂仍分開；粉色內耳一起放大。放大後耳朵頂出畫布上緣快 1 格、耳尖的深藍外框被切掉；倉鼠、相機和快門鍵一起往下 1 格（相機底邊停在下方取景框角那一列之上），四個取景框角不動。",
        tempo="normal")
s.look((5.5, 0, 13, 6.1), "耳朵太小")
grow_ears(s, "hf", note="耳朵放大 1.6 倍")
s.look((0, 0, 24, 24), "耳朵頂出畫布上緣")
shift_ids(s, [e for e in s.elements if e.startswith(("hf_", "cam", "band", "lens_", "button_"))], 0, 1, note="倉鼠和相機往下 1 格")
s.commit()
