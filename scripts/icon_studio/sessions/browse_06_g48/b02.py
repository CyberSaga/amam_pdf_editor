"""Batch 2 of the 06_瀏覽模式 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：倉鼠的臉與游標的光",
        "色塊：游標比參考正了 6°，頭部、分叉、尾巴的比例和參考一致；倉鼠頭塞滿游標頭部下半，身體在分叉處被白邊切掉，"
        "石板藍的游標是一整片平色。",
        "補上儲存的 48 格五官（k 0.68）；游標頭部沿長斜邊內側加一道 1.5 px、35% 的白光（48 格大色塊的光）；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 20.8, 24.4, 6.0, 5.4, k=0.68, parts=("face",))
s.add("cursor_gloss", "path", "glint", d="M17.2 12.7L21.25 16.4", fill="none", stroke=WHITE, stroke_width=1.5,
      stroke_opacity=0.35, stroke_linecap="round", anim="draw")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit()
