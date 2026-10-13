"""Batch 3 of the 14_編輯文字 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻，14 的身體尤其怪。放大到 192 px 和儲存並排：這隻是一顆普通橢圓頭疊在"
        "圓身體上、白肚子很大，伸向游標的手是一根斜放的橢圓棒子；儲存的頭是切平的寬圓頂、正面、五官在下三分之二。",
        "整隻重畫成儲存構造的圓胖倉鼠（k 0.7、身體 12），頭的左頰和游標之間留 1 格；胸前留右手，左手改成帶腳趾線的肉墊，"
        "握在游標下段（畫在游標上層），游標的圓頭從肉墊下面露出來；腳底落在 y 44。",
        tempo="normal")
s.look((28, 24, 18, 22), "橢圓頭、棒子手")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 38.4, 34.5, 0.7, layer="hamster", body=12, arms=(False, True))
paws48(s, "hp", [(30.8, 37.0)], k=0.85, layer="front")
s.commit()
