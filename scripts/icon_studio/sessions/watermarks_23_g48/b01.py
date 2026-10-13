"""Batch 1 of the 23_浮水印列表 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：一疊紙與探頭的倉鼠",
        "參考圖：前面一張折角紙（x 4–30、y 7–45）印著一大滴淡紫水滴，後面三張紙往右上錯開，倉鼠從整疊紙的右側後面探出半張臉。",
        "後面的紙簡化成兩張、改用 1.5 px 框和淡灰紫底，免得右側變成三條粗黑線；前紙沿用 2.5 px 規格；倉鼠臉 k 0.58、轉 18°，"
        "放在所有紙的下層。",
        tempo="normal")
hamster48(s, "hm", 41.6, 27.6, 5.4, 4.8, k=0.58, rot=18, parts=("blocks",))
s.add("back2", "path", "object", d="M14.75 7.75H34.25A2 2 0 0 1 36.25 9.75V36.25A2 2 0 0 1 34.25 38.25H14.75A2 2 0 0 1 12.75 36.25V9.75A2 2 0 0 1 14.75 7.75Z",
      fill="#EEEDF7", stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("back1", "path", "object", d="M11.75 3.75H30.25A2 2 0 0 1 32.25 5.75V38.25A2 2 0 0 1 30.25 40.25H11.75A2 2 0 0 1 9.75 38.25V5.75A2 2 0 0 1 11.75 3.75Z",
      fill="#F6F5FC", stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("sheet", "path", "object", d=page_d(5.25, 8.25, 28.75, 43.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(28.75, 8.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.commit()
