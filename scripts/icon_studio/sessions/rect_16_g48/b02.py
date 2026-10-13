"""Batch 2 of the 16_矩形 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER_SHADE, TEAL, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手、小筆、框內淡陰影",
        "色塊到位：倉鼠頭從底邊後面冒出，左耳外緣和下巴都藏在框線下；框內右側空著，倉鼠還沒有臉、手和筆。",
        "補臉（k 0.84）；兩隻手掌搭在底邊上（畫在框的上層）；右手握一支小筆：深藍 3.6 px 墊底、青綠 1.6 px 筆身、"
        "深藍筆尖朝左下點在底邊上；框內右、下緣加一道淡紫灰陰影（和紙張一樣的受光方向）。",
        tempo="normal")
hamster48(s, "hm", 12.0, 33.6, 7.8, 6.8, k=0.84, parts=("face",))
s.add("rect_shade", "path", "back", d="M41.75 10V37.6Q41.75 38.75 40.6 38.75H24", fill="none", stroke=PAPER_SHADE,
      stroke_width=1.5, stroke_linecap="round", anim="draw")
s.add("pen_ink", "path", "front", d="M20.8 38.2L25.6 30.9", fill="none", stroke=INK, stroke_width=3.6,
      stroke_linecap="round", anim="draw")
s.add("pen", "path", "front", d="M21.3 37.4L25.6 30.9", fill="none", stroke=TEAL, stroke_width=1.6,
      stroke_linecap="round", anim="draw")
s.add("pen_nib", "path", "front", d="M19.3 40.6L20 37.4L22.3 38.9Z", fill=INK, stroke=INK, stroke_width=0.8,
      stroke_linejoin="round", anim="pop")
for i, x in enumerate((8.0, 18.0)):
    paw48(s, f"hm_paw{i}", x, 40.3, layer="front")
s.commit()
