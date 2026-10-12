"""Batch 6 of the 03_儲存 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio


def rects(*rs):
    return "".join(f"M{x} {y}h{w}v{h}h{-w}Z" for x, y, w, h in rs)


s = Studio.open()
s.begin(6, "16 格：實際大小變成黑白棋盤",
        "實際尺寸看：反光點、眼間白色尖角、頭頂深藍線和耳尖疊在一起，臉變成黑白相間的棋盤格，杏色只剩 6 格，倉鼠的顏色識別幾乎消失（舊版 16 格反而一眼看得出是杏色的臉）。",
        "保留反光眼睛與耳朵（48 版的重點），其他讓給杏色：頭頂深藍線改成杏色額頭、眼間尖角改杏色，白色口鼻區只留最下一列（鼻子＋兩頰腮紅）。杏色 6 → 10 格，白色 11 → 6 格。",
        tempo="normal")
s.look((4, 7, 8, 5), "臉像黑白棋盤")
s.mod("face_outline", note="拿掉頭頂深藍線", d=rects((5, 7, 2, 1), (9, 7, 2, 1)))
s.mod("face_peach", note="額頭與眼間改杏色", d=rects((7, 8, 2, 1), (4, 9, 8, 2)))
s.mod("face_muzzle", note="口鼻只留最下一列", d=rects((4, 11, 8, 1)))
s.commit()
