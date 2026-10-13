"""Batch 3 of the 26_旋轉頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻是一顆普通橢圓頭，下巴被紙緣切到，手掌是兩顆圓豆子。",
        "頭換成儲存的圓頂（k 0.75、正面），平的底邊藏在紙上緣的線下面，就像儲存的頭坐在標籤窗框上；手掌改成帶趾紋的肉墊搭在紙緣。",
        tempo="normal")
s.look((15, 2, 18, 13), "普通橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 23.0, 11.9, 0.75)
paws48(s, "hf_paws", [(18.2, 12.3), (27.8, 12.3)], k=0.85)
s.commit()
