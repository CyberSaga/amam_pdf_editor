"""Batch 3 of the 28_插入空白頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAPER_SHADE, WHITE, hamster48, paw48, plus_d
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手、加號與紙的明暗",
        "1× 實際大小：紙的 2.5 px 外框和儲存圖示的磁片同重，整組一致；但倉鼠身體整段露在紙右邊，像一顆花生，"
        "參考裡身體窄、大半被紙和圓章擋住，視線先落在臉上。",
        "身體收窄縮短（rx 4.6→4.0、ry 7.6→6.8）並加白肚子；臉沿用儲存的 48 格五官（k 0.73，跟頭一起轉 18°）；"
        "手掌壓在紙的右緣上（放在紙的上層）；圓章內放 3 px 寬的白色加號；紙內側右、下緣加一道淡紫灰陰影。",
        tempo="normal")
s.look((29, 20, 13, 18), "身體太搶眼")
s.mod("hm_body", note="身體收窄縮短", rx=4.0, ry=6.8, cx=35.2, cy=30.0, transform="rotate(8 35.2 30)")
s.add("hm_belly", "ellipse", "hamster", cx=33.9, cy=31.2, rx=2.1, ry=4.4, fill=WHITE,
      transform="rotate(8 35.2 30)", anim="fill", z=14.5)
hamster48(s, "hm", 36.2, 18.3, 7.0, 6.3, k=0.73, rot=18, parts=("face",))
paw48(s, "hm_paw", 29.4, 25.6, layer="front", k=0.85)
s.add("sheet_shade", "path", "object_fx", d="M25.75 12.75V37.6Q25.75 38.75 24.6 38.75H7.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw")
s.add("badge_plus", "path", "badge", d=plus_d(28.5, 39.5, 3.5, 3), fill=WHITE, anim="pop")
s.commit(compare=True)
