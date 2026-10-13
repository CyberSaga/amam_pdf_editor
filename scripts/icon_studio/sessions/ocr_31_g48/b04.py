"""Batch 4 of the 31_OCR（文字辨識） 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠換成儲存的頭",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。192 px 並排看：這隻的切平圓頂是自己拼的，寬高比 6.4:5.6，比儲存的頭窄又扁，"
        "眼睛、鼻子的位置也是另一套；手掌是沒有指頭的橢圓。",
        "頭換成共用的儲存構造（k 0.75，底寬 14.3，和 T 一樣寬），平底一樣落在掃描線上（y 22.9），帶鬍鬚與嘴；"
        "兩隻手掌換成帶指痕的小肉墊，搭在掃描線上、位在兩頰下方；耳朵頂到 y 13.8，離掃描器下緣還有將近 2 格。",
        tempo="normal")
s.look((15, 12, 18, 13), "自拼的圓頂比例不對")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 24, 22.9, 0.75, whiskers=True)
paws48(s, "hf_paw", [(19.05, 23.0), (28.95, 23.0)], k=0.8)
s.commit()
