"""Batch 4 of the 16_矩形 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大到 192 px 和儲存並排：這隻是一顆普通橢圓頭，左耳塞在左框下，"
        "整顆頭比儲存的倉鼠高瘦、五官擠在中間；儲存的頭是被窗框切平的寬圓頂，兩頰最寬、五官在下三分之二。",
        "改用儲存的頭（k 0.95，矩形框很大、頭也放大）：平底壓在底邊線裡（base 40.4），整顆頭離開左框、像儲存那樣完整露出；"
        "兩隻帶腳趾線的肉墊：左手在左頰下，右手移到右頰外側握筆（筆在右頰前會蓋住臉），筆跟著右手平移、筆尖仍點在底邊上，"
        "手掌蓋住筆的根部。",
        tempo="normal")
s.look((4, 24, 22, 18), "普通橢圓頭、左耳塞在框下")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 16.2, 40.4, 0.95, layer="hamster")
s.mod("pen_ink", note="筆移到右手", d="M28.2 38.8L33 31.5")
s.mod("pen", d="M28.7 38L33 31.5")
s.mod("pen_nib", d="M26.7 41.2L27.4 38L29.7 39.5Z")
paws48(s, "hp", [(10.6, 40.9), (27.4, 40.9)], k=0.85, layer="front")
s.commit()
