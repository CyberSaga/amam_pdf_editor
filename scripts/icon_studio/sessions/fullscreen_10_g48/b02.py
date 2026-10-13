"""Batch 2 of the 10_全螢幕 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：倉鼠的臉",
        "色塊疊參考吻合：四支箭頭的 L 角、臂長和斜桿方向都對，箭頭粗細比參考略重一點（和其他圖示的弧形箭頭同重）；中間的頭還沒有臉。",
        "補上儲存的 48 格五官（k 0.68）：白色口鼻、帶反光的眼睛、鼻子、嘴、鬍鬚、腮紅；擦掉草稿與對角參考線。",
        tempo="normal")
hamster48(s, "hm", 24, 25, 6.4, 5.4, k=0.68, parts=("face",))
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
