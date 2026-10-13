"""Batch 2 of the 23_浮水印列表 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PAPER_SHADE, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：水滴與倉鼠的臉",
        "紙疊的錯位和參考相符，右側兩道 1.5 px 框不會糊成黑塊；倉鼠臉只露出右半，左眼剛好在最後一張紙的邊緣外。",
        "前紙中央畫大水滴（高 17、淡紫填色、深一階紫框、左側白色反光）；倉鼠補臉；前紙內側淡陰影。",
        tempo="normal")
s.add("drop", "path", "object_fx", d="M16.5 21.5C18.4 25 23 28.6 23 33A6.5 6.5 0 0 1 10 33C10 28.6 14.6 25 16.5 21.5Z",
      fill="#CBC4EF", stroke="#8F86CF", stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("drop_hl", "path", "object_fx", d="M12.8 33.4Q12.8 30.6 14.8 28.6", fill="none", stroke="#FFFFFF",
      stroke_width=1.4, stroke_linecap="round", anim="draw")
s.add("sheet_shade", "path", "object_fx", d="M27.25 16.25V41.1Q27.25 42.25 26.1 42.25H7.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw", z=0.5)
hamster48(s, "hm", 41.6, 27.6, 5.4, 4.8, k=0.58, rot=18, parts=("face",))
s.commit()
