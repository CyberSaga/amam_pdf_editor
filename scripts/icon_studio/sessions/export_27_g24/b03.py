"""Batch 3 of the 27_匯出頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import grow_ears, shift_ids
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這隻的耳朵是半徑 1.5 的小圓，大半藏在圓頂後面，"
        "只在頭頂露出一小片，看起來像沒有耳朵。",
        "耳朵改用 BIG_EARS：半徑 1.6 倍，圓心往外 0.7k、往上 0.35k，露出的耳朵約寬 1.6 倍、高 1.75 倍，"
        "兩耳在頭頂仍分開；粉色內耳一起放大。放大後右耳超出畫布右邊，整隻往左挪 1 格（整格移動，眼睛鼻子仍對齊像素）。",
        tempo="normal")
s.look((11.7, 2.3, 12.3, 6), "耳朵太小")
grow_ears(s, "hb", note="耳朵放大 1.6 倍")
s.look((0, 0, 24, 24), "右耳超出畫布右邊")
shift_ids(s, [e for e in s.elements if e.startswith(('hb_',))], -1, 0, note="整隻往左挪 1 格")
s.commit()
