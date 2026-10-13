"""Batch 2 of the 24_顯示-隱藏註解 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。這隻是逐像素的方盒臉（PEEK24 加一列口鼻）；48 格已改成儲存的探頭臉加兩隻手掌。"
        "草稿把探頭臉縮到 24 格：24 格的眼睛比較高、眼瞼兩側比中間低 2 格，切平的底角露在眼瞼上，手掌縮到 2–3 格只剩兩團灰點。",
        "改用同一套頭的圓胖倉鼠（k 0.55、中心 x 12，在眼瞼最高點正上方）：兩頰以下是往內收的身體、沒有切平的底角，"
        "身體藏在眼睛後面；眼睛 2×2 帶反光在第 4–5 列、鼻子第 6 列，整張臉在眼瞼上方。",
        tempo="normal")
s.look((8, 0, 9, 9), "方盒臉")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_bean_px(s, "hb", 24, 12, 8, 0.55, layer="hamster", body=10, feet=False)
s.commit()
