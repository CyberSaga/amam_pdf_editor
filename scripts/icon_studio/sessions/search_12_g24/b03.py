"""Batch 3 of the 12_搜尋 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成儲存構造的臉",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。這張的臉是 10 格寬的逐像素方臉，塞滿整個開口；48 格已改成擺正的寬圓頂、"
        "平底壓在鏡框下緣。",
        "改用同一套圓頂構造（k 0.6，1 px 外框的向量頭、耳朵、白口鼻，整數像素的眼睛、2 格鼻子、腮紅），平底放在 y 15.5："
        "下半條底線藏在鏡框內框裡、上半條被白口鼻蓋住，這樣腮紅那列（y 13）還在開口裡；若放到 y 16，腮紅會被鏡框吃掉。",
        tempo="normal")
s.look((4, 4, 12, 12), "方臉塞滿開口")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face_px(s, "hf", 24, 10, 15.5, 0.6)
s.commit()
