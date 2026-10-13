"""Batch 5 of the 21_註解列表 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻和新增註解一樣是歪 15° 的普通橢圓頭加一小截身體，"
        "夾在黃框和紫框之間時五官擠成一團；儲存的頭是被切平的寬圓頂、正面、兩頰最寬。",
        "換成和新增註解同一隻圓胖倉鼠（k 0.75，不歪頭）：兩頰那條線放在紫框上緣（y 26），臉正好落在黃框左下角和紫框左上角之間，"
        "右眼離黃框圓角 1 格；右耳、右半身藏到黃框和紫框後面，左手和左腳從紫框左邊露出來；青綠框的左框線仍藏在倉鼠頭後。",
        tempo="normal")
s.look((1, 16, 14, 22), "歪頭橢圓擠在兩個框之間")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean48(s, "hb", 8.6, 26, 0.75, layer="hamster", body=12, arms=(True, False))
s.commit()
