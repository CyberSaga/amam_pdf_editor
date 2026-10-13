"""Batch 4 of the 17_螢光筆 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻是歪 -8° 的普通橢圓頭擋在筆頭前面，下巴整圈框線，"
        "兩隻手是兩顆橢圓；儲存的頭是被切平的寬圓頂、正面、兩頰最寬。草稿試了儲存的探頭臉：筆是斜的，筆頭的斜邊會從右下切掉嘴和鼻子；"
        "改成整隻圓胖倉鼠躲在筆後面，筆頭從胸口斜切過去，臉就完整露在筆頭上方。",
        "換成圓胖倉鼠（k 0.75，不歪頭，中心 (17.5, 13.5)），放在筆的下層；筆身上端縮短 1 格，讓斜切的筆頭剛好落在下巴下面；"
        "身體和胸前的小手都藏在筆後，左邊露出一點身側；兩隻手掌抱在筆頭左上角和筆身右緣（筆的上層）。",
        tempo="normal")
s.look((10, 3, 20, 22), "歪頭橢圓擋在筆頭前面")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
s.mod("barrel", note="筆身上端縮短 1 格", d="M21.9 31.5V15A2 2 0 0 1 23.9 13H32.1A2 2 0 0 1 34.1 15V31.5Z")
s.mod("barrel_gloss", note="反光跟著縮短", d="M31.6 15.5V28.5")
hamster_bean48(s, "hb", 17.5, 13.5, 0.75, layer="hamster", body=10, feet=False, arms=(False, False))
paws48(s, "hp", [(16.0, 20.6), (26.6, 16.2)], k=0.9, layer="front")
s.commit()
