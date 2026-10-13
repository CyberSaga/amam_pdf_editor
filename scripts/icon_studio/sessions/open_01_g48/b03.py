"""Batch 3 of the 01_開啟 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻大頭是普通橢圓，左手是一顆浮在臉旁的豆子。",
        "頭換成儲存的圓頂（k 0.85、正面），底邊落在前片上緣、左下由前片的標籤擋住；兩隻肉墊手搭在前片的邊上。",
        tempo="normal")
s.look((8, 4, 20, 20), "普通橢圓頭、浮著的手")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 17.4, 24.0, 0.85)
paws48(s, "hf_paws", [(12.0, 21.6), (23.4, 24.6)], k=0.9)
s.commit()
