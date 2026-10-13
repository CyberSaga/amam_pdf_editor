"""Batch 3 of the 16_矩形 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PEACH, hamster_face_px, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成儲存的圓頂臉",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格這隻是 PEEK24 的方盒臉，左側貼著左框；48 格已改成儲存的圓頂頭、"
        "整顆露出，右手移到右頰外側握筆。",
        "改用 hamster_face_px（k 0.6、cx 9、base 20.1）：圓頂頭、耳朵、白色口鼻用 1 px 外框向量，眼睛、鼻子、腮紅放整數像素，"
        "整顆頭離開左框；左手掌一格在左頰下（第 6 欄），右手掌兩格移到右頰外側（第 15–16 欄），筆尖放在右手上方、筆身往右上。",
        tempo="normal")
s.look((2, 12, 16, 9), "方盒臉")
for eid in [e for e in list(s.elements) if e.startswith("hm_")] + ["paw_peach"]:
    s.rm(eid, note="舊倉鼠擦掉" if eid == "hm_peach" else None)
hamster_face_px(s, "hf", 24, 9, 20.1, 0.6, layer="hamster")
s.mod("pen_body", note="筆移到右手", d=pix_d(["..D", ".D.", "D.."], "D", 16, 15))
s.mod("pen_nib", d="M15 18h1v1h-1Z")
s.add("hp", "path", "front", d=pix_d(["P"], "P", 6, 19) + pix_d(["PP"], "P", 15, 19), fill=PEACH, anim="pop")
s.commit()
