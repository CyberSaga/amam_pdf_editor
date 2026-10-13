"""Batch 5 of the 18_新增註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import grow_ears, shift_ids
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這隻的耳朵是半徑 2.25 的小圓，大半藏在圓頂後面，"
        "只在頭頂露出一小片，看起來像沒有耳朵。",
        "耳朵改用 BIG_EARS：半徑 1.6 倍，圓心往外 0.7k、往上 0.35k，露出的耳朵約寬 1.6 倍、高 1.75 倍，"
        "兩耳在頭頂仍分開；粉色內耳一起放大。左耳外緣貼到畫布左邊（x 0.3），整隻往右挪 0.5 格。",
        tempo="normal")
s.look((0.8, 15.6, 17.1, 7.5), "耳朵太小")
grow_ears(s, "hb", note="耳朵放大 1.6 倍")
shift_ids(s, [e for e in s.elements if e.startswith(("hb_", "hp_"))], 0.5, 0, note="左耳貼邊，往右挪 0.5")
s.commit()
