"""Batch 2 of the 08_復原 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手掌與箭頭的光",
        "色塊疊參考吻合：箭頭頭部、桿子與鉤的外緣都對齊；倉鼠頭的左下角藏在箭頭頭部後面，身體只露出頭右下方一小塊。",
        "倉鼠補臉（沿用儲存的 48 格五官，跟頭一起轉 16°）與白肚子；左手搭在箭頭頭部的上斜邊、右手搭在桿子上緣（放在箭頭上層）；"
        "箭頭沿上緣加一道 1.5 px、55% 的白色光；擦掉草稿。",
        tempo="normal")
s.add("hm_belly", "ellipse", "hamster", cx=27.2, cy=19.0, rx=2.4, ry=3.2, fill=WHITE, transform="rotate(-12 28.6 17.8)",
      anim="fill", z=s.elements["hm_body"]["z"] + 0.5)
hamster48(s, "hm", 24.5, 11.5, 7.2, 6.4, k=0.78, rot=16, parts=("face",))
paw48(s, "hm_paw0", 16.9, 17.9, layer="front", k=0.85)
paw48(s, "hm_paw1", 24.2, 19.9, layer="front", k=0.85)
s.add("arrow_gloss", "path", "glint", d="M14.3 24.8L17.75 22M22.75 23.75H26.75A10.25 9.25 0 0 1 36.4 29.85", fill="none",
      stroke=WHITE, stroke_width=1.5, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
