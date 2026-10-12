"""Batch 4 of the 03_儲存 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import PROCESS_LAYERS, Studio

s = Studio.open()
s.begin(7, "16 格：收尾",
        "和 24 格版縮到 16 px、舊 PNG 並排：只有 16 格版的槽孔是一條乾淨的深色、倉鼠讀得出兩隻眼睛和耳朵；另外兩個都糊成色塊。高光在 16 格只會變成一顆雜點，不加。",
        "擦掉像素格、留白線與草稿；9 個元素定稿。",
        tempo="normal")
for e in sorted((e for e in s.elements.values() if e["layer"] in PROCESS_LAYERS), key=lambda e: -e["z"]):
    s.rm(e["id"])
s.commit()
