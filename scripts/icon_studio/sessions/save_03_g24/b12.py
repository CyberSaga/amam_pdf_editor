"""Batch 12 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio


def rects(*rs):
    return "".join(f"M{x} {y}h{w}v{h}h{-w}Z" for x, y, w, h in rs)


s = Studio.open()
s.begin(6, "24 格：找回耳朵與圓頂的輪廓",
        "黑邊拿掉後臉清爽了，但耳朵變成一條粉紅帶子，48 版「兩個圓耳朵＋圓頂頭」的剪影不見了；下排鼻子＋嘴是一塊紅棕色方塊，比 48 版的鼻嘴重。",
        "耳朵改回 3 格寬：外側 1 格深藍框、內側 2 格粉紅，耳尖深藍；頭頂線之外，肩膀那一列（第 13 列）兩端留 1 格深藍，做出圓頂轉折，第 14 列以下才接到窗框。嘴改淺玫瑰色。",
        tempo="normal")
s.look((7, 11, 10, 3), "耳朵變成粉紅帶")
s.mod("face_outline", note="耳朵外框與肩膀轉折", d=rects((8, 11, 2, 1), (14, 11, 2, 1), (7, 12, 1, 2), (16, 12, 1, 2), (10, 12, 4, 1)))
s.mod("ears_inner", d=rects((8, 12, 2, 1), (14, 12, 2, 1)))
s.mod("face_peach", d=rects((8, 13, 8, 1), (7, 14, 10, 2)))
s.mod("mouth", note="嘴改淺玫瑰", fill="#D49AA4")
s.commit()
