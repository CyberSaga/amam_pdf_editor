"""Batch 2 of the 14_編輯文字 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEACH, WHITE, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：T 的白邊、臉、肚子、握住游標的手",
        "實際大小在淺色與深色底各看一次：淺色底 T、游標、倉鼠都清楚；深色底（墨瓷主題）上深藍 T 和背景幾乎同色，"
        "只剩游標和倉鼠，認不出是「文字」。倉鼠還沒有臉，手也沒碰到游標。",
        "T 底下墊一層同形的白色描邊（2 px 圓角，只外擴 1 格）：淺色底上看不出來，深色底上把 T 勾出來；"
        "倉鼠補白肚子與臉；左手拉成短手臂斜搭在游標下段（畫在游標上層），游標下端從手下面露出一點。",
        tempo="normal")
glyph = s.elements["glyph"]["attrs"]["d"]
s.add("glyph_halo", "path", "back", d=glyph, fill=WHITE, stroke=WHITE, stroke_width=2, stroke_linejoin="round",
      anim="fill")
s.add("hm_belly", "ellipse", "hamster", cx=38.0, cy=40.3, rx=3.7, ry=4.0, fill=WHITE, anim="fill")
hamster48(s, "hm", 38.2, 30.2, 6.4, 5.6, k=0.67, parts=("face",))
s.add("hm_arm", "ellipse", "front", cx=30.6, cy=35.6, rx=2.5, ry=1.6, fill=PEACH, stroke=INK, stroke_width=1.1,
      transform="rotate(-20 30.6 35.6)", anim="pop")
s.commit()
