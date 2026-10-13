"""Batch 2 of the 29_從檔案插入頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import TEAL, arc_arrow, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、揮手、彎箭頭",
        "色塊吻合參考：紙從資料夾後片冒出，倉鼠頭卡在前後片之間。",
        "倉鼠補臉；右手舉起揮手（前片上層）；青綠彎箭頭：圓心 (41, 34)、半徑 10，從 180° 順時針到 250°，再接三角頭指向右上，"
        "深藍墊底 1.25 px 包邊；前片上緣加一道淺色反光。",
        tempo="normal")
hamster48(s, "hm", 17.2, 22.4, 8.2, 7.0, k=0.85, eye_y=21.0, parts=("face",))
paw48(s, "hm_paw", 27.6, 27.0, layer="front", k=1.0)
arc_arrow(s, "arrow", 41, 34, 10, 180, 250, "front", width=3.2, head_w=4.2, head_len=5.4, color=TEAL, ink_width=1.25)
s.add("folder_gloss", "path", "glint", d="M11.5 31.9H34", fill="none", stroke="#FFF3C4", stroke_width=1.3,
      stroke_linecap="round", anim="draw")
s.commit()
