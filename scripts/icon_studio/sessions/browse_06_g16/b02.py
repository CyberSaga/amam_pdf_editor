"""Batch 2 of the 06_瀏覽模式 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PEEK16, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "16 格：臉上移一列",
        "實際大小看：鼻子那列的白色口鼻正好壓在分叉的白邊上（第 3 欄上下相連），下巴和白邊連成一片，臉的下緣讀不出來，"
        "像臉從游標底下漏出來。",
        "臉上移一列（y 5–9）：下巴下面換成石板藍的游標本體，只剩 1 格碰到分叉的白邊；耳朵仍在石板藍上，臉更像在游標的窗口裡。",
        tempo="normal")
s.look((1, 9, 9, 3), "白色口鼻黏到分叉的白邊")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hm_")]):
    ch = {"outline": "N", "ears_in": "K", "peach": "P", "eyes": "E", "eyes_hl": "H", "blush": "B", "muzzle": "W",
          "nose": "R"}[eid[3:]]
    s.mod(eid, note="臉上移一列" if i == 0 else None, d=pix_d(PEEK16, ch, 2, 5))
s.commit()
