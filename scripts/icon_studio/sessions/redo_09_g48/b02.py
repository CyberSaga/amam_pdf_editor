"""Batch 2 of the 09_重做 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、抓住尾巴的手、箭頭的光",
        "色塊疊參考：鏡射的箭頭形狀和參考一致（參考大一號）；倉鼠兩耳都露在鉤口下，鉤的尾巴尖剛好停在倉鼠的左頰上，"
        "看起來像尾巴戳進臉裡。",
        "倉鼠補臉（儲存的 48 格五官，跟頭一起轉 16°）；左手抓住鉤的尾巴尖（放在箭頭上層），把「戳到臉」變成「抱著尾巴」，"
        "參考裡倉鼠的左手也伸向尾端；白光沿用復原的路徑、一起鏡射；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 22, 35.5, 7.4, 6.6, k=0.8, rot=16, parts=("face",))
paw48(s, "hm_paw", 16.5, 36.1, layer="front", k=0.85)
s.add("arrow_gloss", "path", "glint", d="M14.3 23.3L17.75 20.5M22.75 22.25H26.75A10.25 9.25 0 0 1 36.4 28.35", fill="none",
      stroke=WHITE, stroke_width=1.5, stroke_opacity=0.55, stroke_linecap="round", transform="matrix(-1 0 0 1 48 -7)",
      anim="draw")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
