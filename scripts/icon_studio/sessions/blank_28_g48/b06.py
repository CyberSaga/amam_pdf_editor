"""Batch 6 of the 28_插入空白頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻；25、28、07、14 的身體尤其怪。放大比對：這隻的頭是一顆斜放的普通橢圓（歪頭在 48 px 會糊），身體是細長橢圓加白肚子，像黃鼠狼。",
        "整隻重畫：儲存的圓頂頭（k 0.78、正面）流進圓胖的身體，嘴部白色收成圓鼻口、奶油色肚子；整隻仍藏在紙的右緣後面，"
        "只把一隻肉墊手放到紙緣上（紙的上層）。",
        tempo="normal")
s.look((28, 8, 18, 28), "頭歪、身體細長")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 37.6, 22.6, 0.78, layer="hamster", body=13, arms=(False, False))
paws48(s, "hb_paw", [(30.2, 26.4)], k=0.9, layer="front")
s.commit()
