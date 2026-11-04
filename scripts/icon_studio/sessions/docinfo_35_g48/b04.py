"""Batch 4 of the 35_文件資訊 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(7, "48 格：檢查整體與收尾",
        "36–48 px 實際大小（125–150 % 螢幕的 ribbon 用這一版）：紙、四列欄位、i 章都讀得出來，36 px 時欄位糊成灰紫細線"
        "但仍是「一張寫了資料的紙」；和 04、05、26 並排，外框粗細、倉鼠大小、圓章的紫色一致。",
        "不改形；擦掉草稿與參考線。",
        tempo="normal")
s.look((4, 0, 42, 47), "整體")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit(small=True)
