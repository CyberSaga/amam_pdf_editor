"""Batch 3 of the 34_適應畫面 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻；25、28、07、14 的身體尤其怪。放大比對：這隻小倉鼠是圓身體加普通橢圓頭，手臂是斜放的橢圓。",
        "改成儲存的圓頂頭（k 0.62）＋圓胖身體，站在左下角取景角前面，兩隻小手在胸前、右手靠到紙的左緣。",
        tempo="normal")
s.look((3, 26, 14, 18), "小倉鼠")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 9.4, 33.4, 0.62, layer="front", body=11, arm_pos=(5.0, 0.32))
s.commit()
