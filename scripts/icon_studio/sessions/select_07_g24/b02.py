"""Batch 2 of the 07_操作物件 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PEACH, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：手掌讓出控點",
        "實際大小看：4×3 的手掌（深藍框）蓋掉右下控點 9 格青綠裡的 7 格，右下角變成一團深色，看不出是控點。"
        "草稿試了四種：手掌下移、2 格桃色短手臂、3 格帶框手臂、不畫手；短手臂保留最多青綠，仍看得出倉鼠伸手抓著控點。",
        "手掌改成從倉鼠左側伸出的 2 格桃色短手臂，穿過控點的右框搭進青綠裡（上下由控點和倉鼠的深藍框夾住）；控點留下 8 格青綠。",
        tempo="normal")
s.look((10, 13, 6, 5), "手掌蓋住控點")
for eid in ("paw_peach", "paw_outline"):
    s.rm(eid, note="拿掉 4×3 手掌" if eid == "paw_peach" else None)
s.add("paw", "path", "front", d=pix_d(["PP"], "P", 13, 15), fill=PEACH, anim="pop")
s.commit()
