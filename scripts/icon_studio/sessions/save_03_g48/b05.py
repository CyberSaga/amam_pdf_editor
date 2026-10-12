"""Batch 5 of the 03_儲存 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import PROCESS_LAYERS, Studio

s = Studio.open()
s.begin(7, "48 格：收尾",
        "和精細版在 48–96 px 並排：新版外框與臉部清楚得多；精細版在這個尺寸只剩一張帶卡片底的縮圖。1× 時鬍鬚、嘴、腮紅都還分得出來，沒有糊成一團。",
        "擦掉像素格、留白線與草稿；28 個元素定稿。",
        tempo="normal")
for e in sorted((e for e in s.elements.values() if e["layer"] in PROCESS_LAYERS), key=lambda e: -e["z"]):
    s.rm(e["id"])
s.commit()
