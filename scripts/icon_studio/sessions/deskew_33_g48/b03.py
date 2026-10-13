"""Batch 3 of the 33_拉正PDF頁面 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻是普通橢圓頭、手掌像豆子。",
        "頭換成儲存的圓頂（k 0.72、正面），底邊藏在歪紙的上緣線下；肉墊手搭在紙緣兩側。",
        tempo="normal")
s.look((16, 3, 16, 14), "普通橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 23.6, 16.0, 0.72)
paws48(s, "hf_paws", [(19.0, 16.1), (28.2, 16.7)], k=0.8)
s.commit()
