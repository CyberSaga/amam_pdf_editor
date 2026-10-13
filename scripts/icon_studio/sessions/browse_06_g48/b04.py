"""Batch 4 of the 06_瀏覽模式 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import BIG_EARS, hamster_face48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這隻的耳朵是半徑 2.25 的小圓，大半藏在圓頂後面，"
        "只在頭頂露出一小片，看起來像沒有耳朵。",
        "耳朵改用 BIG_EARS：半徑 1.6 倍，圓心往外 0.7k、往上 0.35k，露出的耳朵約寬 1.6 倍、高 1.75 倍，"
        "兩耳在頭頂仍分開；粉色內耳一起放大。這隻在游標窗口裡，k 0.75 時大耳朵大半被游標白邊切掉、1× 看不出耳朵；頭縮到 k 0.68、往左下靠（下巴仍貼在分叉處的白邊上），兩隻大耳朵大半露出來。",
        tempo="normal")
s.look((13.3, 16.2, 17.1, 7.5), "耳朵太小")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hf_")]):
    s.rm(eid, note="倉鼠擦掉重畫" if i == 0 else None)
hamster_face48(s, "hf", 21.6, 26.97, 0.68, chin=2.4, ears=BIG_EARS)
s.commit()
