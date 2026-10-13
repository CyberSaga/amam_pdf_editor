"""Batch 2 of the 29_從檔案插入頁 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import flap_d, page_d, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "16 格：箭頭改成清楚的 ↗",
        "1× 看：彎箭頭的頭只有 2 格、桿子中間斷一格，讀起來像一個歪掉的 7；紙也壓到箭頭。",
        "箭頭改成 4×4 的斜上箭頭（3 格直角頭 + 斜桿）放 x 12–15；紙收窄一格（外緣 x 6/12）讓出位置。",
        tempo="normal")
s.look((11, 4, 5, 6), "箭頭像 7")
s.mod("sheet", note="紙收窄", d=page_d(6.5, 1.5, 11.5, 12, 1, 2))
s.mod("flap", d=flap_d(11.5, 1.5, 2, 0.5))
s.mod("arrow_fill", note="改成 ↗", d=pix_d([".TTT", "..TT", ".T.T", "T..."], "T", 12, 6))
s.commit()
