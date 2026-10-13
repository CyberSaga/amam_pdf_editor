"""Batch 3 of the 25_刪除頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻；25、28、07、14 的身體尤其怪。放大比對：這隻是細長橢圓身體加白肚子，"
        "頭是一顆普通橢圓，像保齡球瓶或黃鼠狼；儲存的頭是高橢圓被切平的圓頂（兩頰最寬）、正面、五官在下三分之二。",
        "整隻重畫：頭沿用儲存的圓頂構造（k 0.85），頭身一體的圓胖身體（身體 11 格、肚子奶油色、嘴部白色收成圓鼻口），"
        "兩隻小手在胸前、右手搭到紙的左緣，兩隻腳；腳底落在 y 41。",
        tempo="normal")
s.look((2, 8, 18, 36), "倉鼠身體細長、頭是普通橢圓")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 10.4, 29.0, 0.85, layer="front", body=13, arm_pos=(5.6, 0.3))
s.commit()
