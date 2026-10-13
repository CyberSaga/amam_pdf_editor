"""Batch 2 of the 21_註解列表 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。這隻是逐像素的方盒頭（BEAN24），在 1× 像戴面罩的貓；"
        "48 格已改成儲存的圓頂頭與圓胖身體。",
        "改用同一套構造縮到 24 格（k 0.5、中心 x 5）：兩頰線放在 y 12，眼睛第 8–9 列、鼻子第 10 列，整張臉落在黃框左緣左邊、"
        "紫框上緣（第 11 列）上面；右頰那欄隔開右眼和黃框框線，身體下半藏到紫框後。",
        tempo="normal")
s.look((0, 3, 10, 12), "方盒倉鼠像貓")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 5, 12, 0.5, layer="hamster", body=12)
s.commit()
