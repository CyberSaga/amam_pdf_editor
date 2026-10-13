"""Batch 2 of the 11_縮圖 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAPER_SHADE, WHITE, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手掌、方塊光澤與框內陰影",
        "色塊疊參考吻合：框、四個方塊、倉鼠頭的位置都對；頭只露出框緣以上約 9 格，五官要全部放在 y 13 以上。方塊是平塗，"
        "框裡也沒有明暗。",
        "倉鼠補臉（跟著頭轉 10°），兩隻手掌搭在框的上緣（框的上層、同一高度）；每個方塊左上角一道 1.2 px、0.6 透明度的白色 L 形光澤；"
        "框內側右、下緣一道淡紫灰陰影（和紙張圖示一致）；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 27, 11.6, 6.6, 5.6, k=0.68, eye_y=10.0, rot=10, parts=("face",))
paw48(s, "hm_paw0", 20.4, 14.2, layer="front", k=0.8)
paw48(s, "hm_paw1", 33.0, 14.2, layer="front", k=0.8)
gloss = "".join(f"M{x0 + 2.6} {y0 + 5.6}V{y0 + 3.6}Q{x0 + 2.6} {y0 + 2.6} {x0 + 3.6} {y0 + 2.6}H{x0 + 5.4}"
                for x0, y0 in ((13, 18), (25, 18), (13, 30), (25, 30)))
s.add("tile_gloss", "path", "glint", d=gloss, fill="none", stroke=WHITE, stroke_width=1.2, stroke_opacity=0.6,
      stroke_linecap="round", stroke_linejoin="round", anim="draw")
s.add("frame_shade", "path", "object_fx", d="M36.75 18.75V40.6Q36.75 41.75 35.6 41.75H12.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
