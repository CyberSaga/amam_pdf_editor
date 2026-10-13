"""Batch 3 of the 27_匯出頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻；25、28、07、14 的身體尤其怪。放大比對：這隻頭歪 14°、普通橢圓頭，身體細長。",
        "改成儲存的圓頂頭（k 0.75、正面）＋圓胖身體，藏在紙右緣與箭頭後面，箭頭擋住下半身。",
        tempo="normal")
s.look((29, 10, 16, 22), "頭歪、身體細長")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 37.2, 21.6, 0.75, layer="hamster", body=12, arms=(False, False), feet=False)
s.commit()
