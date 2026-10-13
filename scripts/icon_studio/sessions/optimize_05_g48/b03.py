"""Batch 3 of the 05_另存為最佳化的副本 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻是普通橢圓頭、手掌像兩顆豆子。",
        "頭換成儲存的圓頂（k 0.75、正面），底邊藏在紙上緣；手掌改成肉墊搭在紙緣。",
        tempo="normal")
s.look((17, 2, 16, 14), "普通橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 24.5, 13.9, 0.75)
paws48(s, "hf_paws", [(19.7, 14.3), (29.3, 14.3)], k=0.85)
s.commit()
