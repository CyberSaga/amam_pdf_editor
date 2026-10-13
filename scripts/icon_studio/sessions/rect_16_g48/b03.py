"""Batch 3 of the 16_矩形 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "48 格：筆握在手裡",
        "放大看：右手掌（x 18）停在筆尖左邊，筆像是立在手旁邊，不像握在手裡；參考圖的手掌包住筆的下段。",
        "右手掌右移到 x 20，蓋住筆尖與筆身的交界（手掌在筆的上層），筆從手裡斜伸出去，手掌仍壓在底邊上。",
        tempo="normal")
s.look((15, 35, 10, 8), "筆沒握在手裡")
s.mod("hm_paw1", note="手掌移到筆的根部", cx=20.0)
s.commit()
