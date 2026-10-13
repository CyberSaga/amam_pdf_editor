"""Batch 1 of the 23_浮水印列表 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK24, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：前紙＋大水滴，後面兩張紙往右上錯開，倉鼠從紙疊右後方探頭。24 格放不下藏在紙疊後的臉：右側只剩 5 格，只露得出一隻眼。",
        "後紙一張（1 px 框，外緣 x 5/18、y 1/20）；倉鼠改夾在後紙和前紙之間，8 格寬的探頭臉放 x 15–22，兩隻眼都看得到；"
        "前紙外緣 x 2/15、y 4/22，水滴 6×8。",
        tempo="normal")
s.add("back1", "path", "object", d="M6.5 1.5H16.5A1 1 0 0 1 17.5 2.5V18.5A1 1 0 0 1 16.5 19.5H6.5A1 1 0 0 1 5.5 18.5V2.5A1 1 0 0 1 6.5 1.5Z",
      fill="#F1F0F8", stroke=INK, stroke_width=1, stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK24 + ["NPWWWWPN", ".NPPPPN."], 15, 9, "object")
s.add("sheet", "path", "object", d=page_d(2.75, 4.75, 14.25, 21.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(14.25, 4.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("drop", "path", "object_fx", d="M8.5 9.5C9.5 11.4 12 13.4 12 15.6A3.5 3.5 0 0 1 5 15.6C5 13.4 7.5 11.4 8.5 9.5Z",
      fill="#CBC4EF", stroke="#8F86CF", stroke_width=1, stroke_linejoin="round", anim="fill")
s.add("drop_hl", "path", "object_fx", d="M6.9 15.8Q6.9 14.6 7.7 13.8", fill="none", stroke="#FFFFFF", stroke_width=0.9,
      stroke_linecap="round", anim="draw")
s.commit()
