"""Batch 7 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import PROCESS_LAYERS, Studio

s = Studio.open()
s.begin(7, "24 格：收尾",
        "和 1,550 元素版、舊 PNG 在相同像素下並排：新版在 1× 外框銳利、槽孔與標籤窗清楚、倉鼠兩隻眼睛分得開；舊版縮到 24 px 時磁碟只有約 12 px、倉鼠是一團橘色。",
        "擦掉像素格、留白線與草稿；12 個元素定稿。",
        tempo="normal")
for e in sorted((e for e in s.elements.values() if e["layer"] in PROCESS_LAYERS), key=lambda e: -e["z"]):
    s.rm(e["id"])
s.commit()
