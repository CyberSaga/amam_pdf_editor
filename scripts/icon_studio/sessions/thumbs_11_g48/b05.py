"""Batch 5 of the 11_縮圖 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻的頭是一顆普通扁橢圓（13.2×11.2），"
        "耳朵擠在頭頂、五官縮在中間，手掌是兩顆橢圓豆子；儲存的頭是高橢圓被窗框切平的圓頂，兩頰最寬、五官在下三分之二。",
        "頭照儲存的構造重畫（k 0.85：底寬 16.2，平底落在框上緣的線上 y 13.9，眼睛帶反光、白色口鼻、粉紅鼻子、腮紅、鬍鬚），"
        "中心仍在 x 27；手掌換成有腳趾的小肉墊，搭在框上緣、頭的兩個下角。",
        tempo="normal")
s.look((18, 2, 18, 14), "頭是普通橢圓、手掌是豆子")
old = [e for e in list(s.elements) if e.startswith("hm_")]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
k = 0.85
hamster_face48(s, "hf", 27, 13.9, k, whiskers=k >= 0.75)
paws48(s, "hp", [(27 - 6.54 * k, 14.37), (27 + 6.54 * k, 14.37)], k=0.85)
s.commit()
