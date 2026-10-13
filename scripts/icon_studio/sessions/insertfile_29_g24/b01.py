"""Batch 1 of the 29_從檔案插入頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE24, INK, LINE, PAPER, TEAL_DARK, YELLOW, YELLOW_DARK, arc_arrow, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：資料夾前後片、從後面抽出的有字紙、坐在夾子裡的倉鼠、往右上的青綠彎箭頭。",
        "紙外緣 x 10/20、y 2/…（下緣藏在夾子裡），三條 1 px 字線；資料夾 1.5 px 框，後片帶標籤；倉鼠 FACE24 卡在前後片之間；"
        "彎箭頭 2 px 深青綠、不包邊。",
        tempo="normal")
s.add("sheet", "path", "back", d=page_d(10.75, 2.75, 19.25, 18, 1.5, 3.5), fill=PAPER, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "back", d=flap_d(19.25, 2.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("lines", "path", "back", d="M12.5 7.5H16M12.5 9.5H17.5", fill="none", stroke=LINE, stroke_width=1, anim="draw")
s.add("folder_back", "path", "back", d="M3.75 11.75H7L8 12.75H18.25V22.25H2.75V12.75Z", fill=YELLOW_DARK, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
pixmap(s, "hm", FACE24, 3, 8, "hamster")
s.add("folder_front", "path", "front", d="M4.5 14.75H18.25V22.25H3.75V15.5Z", fill=YELLOW, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
arc_arrow(s, "arrow", 20.5, 17, 5, 180, 250, "front", width=2, head_w=2.3, head_len=2.9, color=TEAL_DARK)
s.commit()
