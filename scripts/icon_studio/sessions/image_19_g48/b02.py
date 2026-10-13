"""Batch 2 of the 19_插入圖片 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48, paw48, plus_d
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手掌與加號",
        "色塊疊參考吻合：相框、白邊、天空、太陽、兩座山的稜線都到位；倉鼠頭夾在畫面與下框之間，下框正好蓋住下巴；"
        "圓章還是一個空的紫色圓。",
        "倉鼠補臉（嘴巴在 y 38.9 以上，不被下框切到），兩隻手掌搭在下框上（框的上層）；圓章放 3 px 寬的白色加號；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 17.8, 35.8, 7.2, 5.5, k=0.78, eye_y=35.2, parts=("face",))
paw48(s, "hm_paw0", 10.6, 40.2, layer="front", k=0.9)
paw48(s, "hm_paw1", 25.0, 40.2, layer="front", k=0.9)
s.add("badge_plus", "path", "badge", d=plus_d(37.5, 37.5, 3.5, 3), fill=WHITE, anim="pop")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
