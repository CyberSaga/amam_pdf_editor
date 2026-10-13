"""Batch 3 of the 02_列印 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。放到 192 px 和儲存並排：這隻的頭是一顆普通圓橢圓、耳朵頂在頭頂、五官擠在中間，"
        "手掌是兩顆沒有指頭的橢圓豆子；儲存的頭是高橢圓被切平的寬圓頂（兩頰最寬）、正面、五官在下三分之二。",
        "頭換成儲存的圓頂構造（k 0.9，底寬 17.2），平底落在進紙白紙上緣的線上（y 14.8），白口鼻、帶反光的大眼睛、鼻子、嘴、腮紅、鬍鬚照儲存；"
        "兩隻手掌換成帶指痕的小肉墊，搭在紙緣、位在兩頰下方；耳朵頂到 y 3.8，和出紙白紙下緣上下置中。",
        tempo="normal")
s.look((13, 1, 22, 17), "頭是普通橢圓、手掌像豆子")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 24, 14.8, 0.9, whiskers=True)
paws48(s, "hf_paw", [(18.1, 15.0), (29.9, 15.0)], k=0.85)
s.commit()
