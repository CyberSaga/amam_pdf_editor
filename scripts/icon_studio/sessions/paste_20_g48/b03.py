"""Batch 3 of the 20_貼上圖片 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 比對：扁橢圓頭、五官擠在中間、手掌是兩顆豆子；儲存是切平的"
        "寬圓頂。這裡的切邊是夾板上緣：夾板上窄下寬，兩個上角往下斜，圓頂的平底要整條藏在夾板的框線下。",
        "頭照儲存的構造重畫（k 0.75：底寬 14.3，有鬍鬚），平底放在 y 14.0（夾板上緣框線的中段，斜角處的框線也蓋得住）；"
        "手掌換成有腳趾的小肉墊，搭在夾板上緣的兩角。",
        tempo="normal")
s.look((15, 2, 18, 13), "頭是扁橢圓、手掌是豆子")
old = [e for e in list(s.elements) if e.startswith("hm_")]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
k = 0.75
hamster_face48(s, "hf", 24, 14.0, k, whiskers=k >= 0.75)
paws48(s, "hp", [(24 - 6.54 * k, 14.12), (24 + 6.54 * k, 14.12)], k=0.85)
s.commit()
