"""Batch 3 of the 15_新增文字框 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻是一顆普通橢圓頭，從框上緣探出時下半被切掉，"
        "剩下像一顆球、五官擠在中間；儲存的頭是高橢圓被窗框切平的寬圓頂，兩頰最寬、五官在下三分之二。",
        "改用儲存的頭（k 0.78、cx 22）：平底壓在框的上緣線裡（base 14.8，2 px 框線蓋住平底），兩頰最寬處和左上控點之間留 1 格；"
        "兩隻帶腳趾線的肉墊扒在框的上緣（cx ± 5.1，畫在框的上層）。",
        tempo="normal")
s.look((10, 2, 24, 16), "普通橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 22, 14.8, 0.78, layer="hamster")
paws48(s, "hp", [(16.9, 15.2), (27.1, 15.2)], k=0.85, layer="front")
s.commit()
