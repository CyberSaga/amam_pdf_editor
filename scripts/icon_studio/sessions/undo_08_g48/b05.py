"""Batch 5 of the 08_復原 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻是一顆普通橢圓頭、還歪了 10°，"
        "五官被斜著拉開；手掌是兩顆圓豆子。儲存的頭是高橢圓被窗框切平的圓頂：正面、兩頰最寬、五官在下三分之二。",
        "頭換成儲存的圓頂（k 0.8、正面不歪），平的底邊藏在箭頭桿子上緣的線下（底線 y 20，線寬覆蓋 19–21.5），像儲存的頭坐在窗框上；"
        "頭心右移到 x 28，左耳避開箭頭頭部的上角。手換成帶趾紋的肉墊：左手搭在頭部後緣的台階，右手壓在彎弧上緣，"
        "順便蓋住彎弧下降處露出的頭底線。",
        tempo="normal")
s.look((17, 8, 22, 15), "普通橢圓頭、歪 10°、豆子手")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hm_")]):
    s.rm(eid, note="舊倉鼠擦掉" if i == 0 else None)
hamster_face48(s, "hf", 28.0, 20.0, 0.8)
paws48(s, "hf_paws", [(22.8, 20.3), (33.8, 20.6)], k=0.85)
s.commit()
