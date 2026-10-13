"""Batch 3 of the 04_另存新檔 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻；25、28、07、14 的身體尤其怪。放大比對：這隻頭歪 -10°、身體像一截細香腸，手臂是一顆橢圓。",
        "改成儲存的圓頂頭（k 0.75、正面）＋圓胖身體，藏在磁片左緣後面，一隻肉墊手搭在磁片邊上（磁片上層）。",
        tempo="normal")
s.look((2, 10, 16, 28), "頭歪、身體細長")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 9.8, 22.0, 0.75, layer="hamster", body=13, arms=(False, False))
paws48(s, "hb_paw", [(16.4, 27.4)], k=0.9, layer="front")
s.commit()
