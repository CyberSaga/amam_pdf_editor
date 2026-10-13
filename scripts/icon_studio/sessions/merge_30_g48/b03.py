"""Batch 3 of the 30_合併PDF 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻是普通橢圓頭，舉起的手臂藏在頭後幾乎看不到。",
        "改成儲存的圓頂頭（k 0.68）流進一小截圓胖身體，兩隻肉墊手舉在臉頰旁（歡呼），身體底停在紙疊上方。",
        tempo="normal")
s.look((16, 17, 16, 14), "普通橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 24.0, 27.4, 0.68, layer="hamster", body=6, arms=(True, True), arm_pos=(8.2, -0.75), feet=False)
s.commit()
