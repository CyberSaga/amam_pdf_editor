"""Batch 3 of the 07_操作物件 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import hamster_bean48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻，07 的身體尤其怪。放大到 192 px 和儲存並排：這隻是一顆普通橢圓頭疊在"
        "細長橢圓身體上、白肚子很大、兩隻橢圓手臂像兩根棒子，整隻像保齡球瓶；儲存的頭是高橢圓被切平的寬圓頂（兩頰最寬）、正面、"
        "五官在下三分之二。",
        "整隻重畫成儲存構造的圓胖倉鼠（k 0.72、身體 13）：圓頂頭和梨形身體一體、圓鼻口、奶油色肚子、胸前一隻小手；"
        "左手改成帶腳趾線的肉墊，搭在右下控點右緣（畫在控點上層）。新站姿比較矮，右下控點要落在胸口高度，"
        "選取框連四個控點整組下移 3 格（中心線 y 11/35），上下留白也跟著平均。",
        tempo="normal")
s.look((29, 17, 18, 30), "保齡球瓶身體、橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
corners = ((9, 11), (31, 11), (9, 35), (31, 35))
s.mod("frame", note="選取框下移 3 格", d="M9 11H31V35H9Z")
for i, (hx, hy) in enumerate(corners):
    s.mod(f"handle{i}", d=rrect_d(hx - 3, hy - 3, hx + 3, hy + 3, 1.0))
s.mod("handle_gloss", d="".join(f"M{hx - 1.5} {hy + 0.5}V{hy - 1.5}H{hx + 0.5}" for hx, hy in corners))
hamster_bean48(s, "hb", 38.2, 31.4, 0.72, layer="hamster", body=13, arms=(False, True))
paws48(s, "hp", [(34.6, 34.6)], k=0.85, layer="front")
s.commit()
