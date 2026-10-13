"""Batch 4 of the 24_顯示-隱藏註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻是歪 12° 的普通橢圓頭趴在上眼瞼後，歪頭讓五官糊掉、"
        "鬍鬚擠在小臉上；儲存的頭是被切平的寬圓頂、正面、兩頰最寬，五官在下三分之二。",
        "換成儲存的探頭臉（k 0.75，不歪頭），放在上眼瞼最高點正上方（中心 x 22）：切平的底邊 y 15.5 藏進眼瞼框線，嘴巴剛好露在眼瞼上方；"
        "眼瞼是弧線、兩側比中間低 1.6 格，切平的兩個底角會露出來，所以兩隻手掌搭在眼瞼上、正好蓋住兩個底角（眼睛的上層）。",
        tempo="normal")
s.look((14, 4, 18, 13), "歪頭橢圓趴在眼瞼後")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 22, 15.5, 0.75, layer="hamster")
paws48(s, "hp", [(15.2, 15.4), (28.8, 15.4)], k=0.85, layer="front")
s.commit()
