"""Batch 2 of the 22_添加浮水印 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAPER_SHADE, badge_plus, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、手、水滴與加號",
        "色塊和參考吻合；印章蓋住倉鼠下巴，臉要擠在 y 14 以上。",
        "補臉（不畫嘴）、兩隻手掌抓在印章圓鈕兩側；淡紫水滴（深一階紫框 1.25、左上白色反光）中心 x 23.5，下面一條淡線；"
        "右下角加號章（外半徑 6.5）；紙內側淡陰影。",
        tempo="normal")
hamster48(s, "hm", 20.5, 12.4, 9.0, 7.6, k=0.92, eye_y=10.2, mouth=False, parts=("face",))
paw48(s, "hm_paw0", 17.3, 16.4, layer="front", k=0.85)
paw48(s, "hm_paw1", 24.7, 16.4, layer="front", k=0.85)
s.add("drop", "path", "object_fx", d="M23.5 27.6C24.8 29.9 28 32.6 28 35.4A4.5 4.5 0 0 1 19 35.4C19 32.6 22.2 29.9 23.5 27.6Z",
      fill="#CBC4EF", stroke="#8F86CF", stroke_width=1.25, stroke_linejoin="round", anim="fill")
s.add("drop_hl", "path", "object_fx", d="M21.2 35.2Q21.2 33.6 22.4 32.4", fill="none", stroke="#FFFFFF", stroke_width=1.1,
      stroke_linecap="round", anim="draw")
s.add("drop_line", "path", "object_fx", d="M17.5 41H29.5", fill="none", stroke="#D3CFEC", stroke_width=1.6,
      stroke_linecap="round", anim="draw")
s.add("sheet_shade", "path", "object_fx", d="M35.25 23.25V41.1Q35.25 42.25 34.1 42.25H11.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw", z=0.5)
badge_plus(s, "badge", 48, 36.5, 39.5)
s.commit()
