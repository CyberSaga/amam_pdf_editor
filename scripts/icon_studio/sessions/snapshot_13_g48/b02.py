"""Batch 2 of the 13_快照 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import TEAL, WHITE, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手掌與鏡頭反光",
        "色塊疊參考吻合：取景框角、機身與凸起、鏡頭都到位，倉鼠頭只露出凸起頂上約 9 格；鏡片還是一塊平的深藍。",
        "倉鼠補臉，兩隻手掌搭在凸起頂的平段（x 20.2 / 27.8，避開圓角）；鏡片左上一道青綠反光（1.6 px 短線）、右下一顆"
        "0.7 透明度的小白點；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 24, 11.4, 6.6, 5.6, k=0.68, eye_y=9.8, parts=("face",))
paw48(s, "hm_paw0", 20.2, 14.2, layer="front", k=0.8)
paw48(s, "hm_paw1", 27.8, 14.2, layer="front", k=0.8)
s.add("lens_glint", "path", "glint", d="M21.9 28.1L23.1 26.9", fill="none", stroke=TEAL, stroke_width=1.6,
      stroke_linecap="round", anim="draw")
s.add("lens_dot", "circle", "glint", cx=26.1, cy=30.6, r=0.6, fill=WHITE, fill_opacity=0.7, anim="pop")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
