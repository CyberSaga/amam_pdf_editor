"""Batch 2 of the 24_顯示-隱藏註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER_SHADE, WHITE, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：瞳孔、反光、臉與減號",
        "色塊疊參考吻合：眼睛外形、虹膜、倉鼠頭和圓章的位置都對；倉鼠只露出眼瞼上方，五官要放在 y 14 以上。",
        "虹膜加 1.5 px 深藍框（外半徑 7）、深藍瞳孔 r 3.4 稍偏右下、左上一顆白色大反光 r 1.9；上眼瞼內側一道淡紫灰陰影；"
        "倉鼠補臉（k 0.72、歪 12°）；圓章放 7×3 白色橫槓（和加號章的橫臂同寬同高）；擦掉草稿。",
        tempo="normal")
s.mod("iris", note="虹膜加深藍框", stroke=INK, stroke_width=1.5)
s.add("pupil", "circle", "object_fx", cx=22, cy=26, r=3.4, fill=INK, anim="pop")
s.add("iris_hl", "circle", "glint", cx=19.2, cy=23.2, r=1.9, fill=WHITE, anim="pop")
s.add("lid_shade", "path", "object_fx", d="M8.5 23.4Q22 8.4 35.5 23.4", fill="none", stroke=PAPER_SHADE, stroke_width=1.5,
      stroke_linecap="round", anim="draw", z=s.elements["iris"]["z"] - 0.5)
hamster48(s, "hm", 25, 12.5, 7.0, 6.0, k=0.72, eye_y=11.2, rot=12, parts=("face",))
s.add("badge_minus", "path", "badge", d="M34 34H41V37H34Z", fill=WHITE, anim="pop")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit(compare=True)
