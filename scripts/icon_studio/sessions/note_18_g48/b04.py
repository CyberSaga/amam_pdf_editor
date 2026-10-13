"""Batch 4 of the 18_新增註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻是一顆歪 15° 的普通橢圓頭（歪頭讓五官在 1× 糊掉），"
        "下面接一小截橢圓身體，鬍鬚擠在小小的臉上；儲存的頭是被切平的寬圓頂、正面、兩頰最寬，五官在下三分之二。",
        "整隻換成儲存構造的圓胖倉鼠（k 0.75，頭身一體、白色圓鼻口、奶油色肚子、胸前一隻小手、兩隻腳），不歪頭，"
        "站在對話框左緣後面：右頰、右手和右腳藏進框後，眼睛離框緣 1 格；另一隻手搭在框緣上（框的上層），像扶著框探頭；腳底落在 y 35。",
        tempo="normal")
s.look((1, 15, 16, 22), "歪頭橢圓、身體一小截")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 9.3, 26.1, 0.75, layer="hamster", body=12, arms=(True, False))
paws48(s, "hp", [(14.6, 28.3)], k=0.8, layer="front")
s.commit()
