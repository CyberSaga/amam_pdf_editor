"""Batch 3 of the 29_從檔案插入頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻大頭是普通橢圓，揮手的手是一顆圓豆子。",
        "頭換成儲存的圓頂（k 0.85、正面），底邊落在前片上緣；右手改成肉墊舉在臉旁揮手，左手搭在前片邊上。",
        tempo="normal")
s.look((8, 14, 21, 17), "普通橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 17.2, 29.0, 0.85)
paws48(s, "hf_paws", [(27.0, 26.6), (10.6, 29.4)], k=0.95)
s.commit()
