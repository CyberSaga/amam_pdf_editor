"""Batch 2 of the 14_編輯文字 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAW24, hamster_bean_px, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格這隻是 BEAN24 的方盒頭，四周深藍框加直邊身體，像戴面罩的貓；"
        "48 格已改成儲存構造的圓胖倉鼠、左手握住游標下段。",
        "改用同一套構造縮到 24 格（k 0.5、身體 12、cx 19，右側外框貼齊畫布邊、左頰和游標之間留一欄）：圓頂頭、耳朵、身體與"
        "白色口鼻／肚子用 1 px 外框的向量，眼睛、鼻子、腮紅放整數像素；手掌下移一列到胸口高度（第 17–19 列），包住游標下端。",
        tempo="normal")
s.look((11, 10, 13, 13), "方盒倉鼠像貓")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉" if eid == "hm_peach" else None)
hamster_bean_px(s, "hb", 24, 19, 16.2, 0.5, layer="hamster", body=12)
pixmap(s, "hp", PAW24, 11, 17, "front")
s.commit()
