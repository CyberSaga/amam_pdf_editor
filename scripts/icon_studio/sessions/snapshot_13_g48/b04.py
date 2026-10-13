"""Batch 4 of the 13_快照 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import grow_ears
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這隻的耳朵是半徑 2.1 的小圓，大半藏在圓頂後面，"
        "只在頭頂露出一小片，看起來像沒有耳朵。",
        "耳朵改用 BIG_EARS：半徑 1.6 倍，圓心往外 0.7k、往上 0.35k，露出的耳朵約寬 1.6 倍、高 1.75 倍，"
        "兩耳在頭頂仍分開；粉色內耳一起放大。",
        tempo="normal")
s.look((15.9, 3.9, 16.2, 7.2), "耳朵太小")
grow_ears(s, "hf", note="耳朵放大 1.6 倍")
s.commit()
