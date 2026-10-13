"""Batch 4 of the 28_插入空白頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "48 格：檢查整體",
        "1.5×（72 px）看：臉讀得出來，但身體細長、白肚子一路到底，整隻像黃鼠狼；參考的身體短而圓，下半被圓章擋住。",
        "身體改成短圓（ry 6.8→6.0、rx 4.5），肚子跟著縮短；其他不動。",
        tempo="normal")
s.look((30, 22, 11, 16), "身體太長")
s.mod("hm_body", note="身體短圓一點", rx=4.5, ry=6.0, cx=35.0, cy=29.9, transform="rotate(8 35 29.9)")
s.mod("hm_belly", note="肚子跟著縮短", cx=33.8, cy=30.7, rx=2.1, ry=3.6, transform="rotate(8 35 29.9)")
s.commit()
