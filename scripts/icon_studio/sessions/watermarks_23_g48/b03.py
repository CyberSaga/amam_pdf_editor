"""Batch 3 of the 23_浮水印列表 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻是一顆歪 18° 的小橢圓頭，五官擠成一團、浮在紙疊旁邊。",
        "改成儲存的圓頂頭（k 0.65、正面）＋圓胖身體，藏在紙疊後面、從右側探出，左邊一小截被最後一張紙擋住。",
        tempo="normal")
s.look((34, 20, 14, 18), "歪頭、五官擠")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 41.0, 29.6, 0.65, layer="hamster", body=10, arms=(False, False))
s.commit()
