"""Batch 2 of the 01_開啟 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手與資料夾的光",
        "前後片、紙、倉鼠頭的位置都和參考吻合；倉鼠沒有臉，資料夾是平的。",
        "倉鼠補臉、左手搭在後片的標籤邊上（在前片的上層）；前片上緣與標籤內側加一道淡黃反光。",
        tempo="normal")
hamster48(s, "hm", 17.5, 14.4, 8.6, 7.4, k=0.88, eye_y=12.6, parts=("face",))
paw48(s, "hm_paw", 9.0, 18.4, layer="front", k=1.0)
s.add("folder_gloss", "path", "glint", d="M7 24.2V23.9Q7 23.4 7.6 23.4H16.6M21.8 26.9H38", fill="none", stroke="#FFF3C4",
      stroke_width=1.3, stroke_linecap="round", stroke_linejoin="round", anim="draw")
s.commit()
