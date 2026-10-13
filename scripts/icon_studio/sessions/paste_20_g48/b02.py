"""Batch 2 of the 20_貼上圖片 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手掌與夾子光澤",
        "色塊疊參考：寫字板、白紙、小圖的位置吻合；倉鼠頭露在夾板上方，下巴整個藏在夾板後面；夾板是一塊平的紫色。",
        "倉鼠補臉，兩隻手掌搭在夾板上緣（x 19.6 / 28.4，夾板的上層）；夾板左上一道 0.6 透明度的白色光澤；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 24, 11.6, 6.6, 5.6, k=0.68, eye_y=10.0, parts=("face",))
s.add("clip_gloss", "path", "glint", d="M19.2 15.9H22.5", fill="none", stroke=WHITE, stroke_width=1.0, stroke_opacity=0.6,
      stroke_linecap="round", anim="draw")
paw48(s, "hm_paw0", 19.6, 13.9, layer="front", k=0.8)
paw48(s, "hm_paw1", 28.4, 13.9, layer="front", k=0.8)
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
