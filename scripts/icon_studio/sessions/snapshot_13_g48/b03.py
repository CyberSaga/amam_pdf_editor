"""Batch 3 of the 13_快照 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 比對：這隻是普通扁橢圓頭、五官縮在中間、手掌是兩顆豆子；"
        "儲存的頭是切平的寬圓頂。這裡的切邊是相機凸起的頂：平段只有約 11 格寬、兩側是斜坡，圓頂的平底要整條藏在凸起的框線下。",
        "頭照儲存的構造重畫（k 0.7：底寬 13.4，兩個底角剛好落在斜坡的框線裡；平底在凸起頂 y 13.9；k 小於 0.75 不畫鬍鬚），"
        "手掌換成有腳趾的小肉墊，搭在凸起頂的兩角。",
        tempo="normal")
s.look((16, 3, 16, 13), "頭是普通橢圓、手掌是豆子")
old = [e for e in list(s.elements) if e.startswith("hm_")]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
k = 0.7
hamster_face48(s, "hf", 24, 13.9, k, whiskers=k >= 0.75)
paws48(s, "hp", [(24 - 6.54 * k, 14.37), (24 + 6.54 * k, 14.37)], k=0.85)
s.commit()
