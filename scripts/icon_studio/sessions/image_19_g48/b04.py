"""Batch 4 of the 19_插入圖片 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 比對：這隻是一顆扁橢圓頭（14.4×11）、五官擠在中間、"
        "手掌是兩顆豆子；儲存的頭是被窗框切平的寬圓頂、五官在下三分之二——這隻正好也是被下框切平的探頭姿勢。",
        "頭照儲存的構造重畫（k 0.78：底寬 14.9，平底落在下框的線上 y 40.4，中心仍在 x 17.8，有鬍鬚）；手掌換成有腳趾的小肉墊，"
        "搭在下框上、頭的兩個下角；耳朵頂在 y 31.5，離山谷還有 4 格。",
        tempo="normal")
s.look((8, 28, 20, 15), "頭是扁橢圓、手掌是豆子")
old = [e for e in list(s.elements) if e.startswith("hm_")]
for eid in old:
    s.rm(eid, note="舊倉鼠擦掉" if eid == old[0] else None)
k = 0.78
hamster_face48(s, "hf", 17.8, 40.4, k, whiskers=k >= 0.75)
paws48(s, "hp", [(17.8 - 6.54 * k, 40.87), (17.8 + 6.54 * k, 40.87)], k=0.85)
s.commit()
