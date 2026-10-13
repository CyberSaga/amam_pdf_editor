"""Batch 3 of the 31_OCR（文字辨識） 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "48 格：檢查整體，T 加粗",
        "1×、1.5×、2× 看：48 格版會用到 95 px，放大後 T 的 3 px 直畫、2.5 px 橫畫比 2 px 的 L 框和 2.5 px 的掃描器外框還細，"
        "T 不再是最重的形狀；24 格版的 T（3 格直畫）相對畫布粗一倍，兩個尺寸切換時 T 會突然變瘦。",
        "T 直畫 3→4（x 22–26）、橫畫 2.5→3（y 25.5–28.5），兩端襯線 2.5 寬、垂到 y 31，腳 9×2.5；外框寬度不變（x 17–31）。",
        tempo="normal")
s.look((15, 24, 18, 18), "T 比框線還細")
s.mod("letter_t", note="T 加粗",
      d="M17 25.5H31V30.5Q31 31 30.5 31H29Q28.5 31 28.5 30.5V29.5Q28.5 28.5 27.5 28.5H26V37Q26 38 27 38H28Q28.5 38 28.5 38.5"
        "V40Q28.5 40.5 28 40.5H20Q19.5 40.5 19.5 40V38.5Q19.5 38 20 38H21Q22 38 22 37V28.5H20.5Q19.5 28.5 19.5 29.5V30.5"
        "Q19.5 31 19 31H17.5Q17 31 17 30.5Z")
s.commit(small=True)
