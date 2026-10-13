"""Batch 3 of the 06_瀏覽模式 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：游標裡是一顆普通橢圓頭加一團橢圓身體，"
        "頭和身體各自一圈深藍框，像兩顆疊起來的豆子；儲存的頭是被窗框切平的圓頂：正面、兩頰最寬、五官在下三分之二。",
        "頭換成儲存的圓頂（k 0.75、正面），身體拿掉；圓頂的平底在游標裡沒有水平的邊可以藏，所以嘴部收成圓鼻口（chin 2.4），"
        "白色鼻口在石板藍上自己就有輪廓、下緣正好靠在分叉處的白邊上；左右兩側和右耳尖被游標的白邊切掉一點，像從游標的窗口探頭。",
        tempo="normal")
s.look((14, 17, 15, 14), "橢圓頭疊橢圓身體")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hm_")]):
    s.rm(eid, note="舊倉鼠擦掉" if i == 0 else None)
hamster_face48(s, "hf", 21.8, 26.8, 0.75, chin=2.4)
s.commit()
