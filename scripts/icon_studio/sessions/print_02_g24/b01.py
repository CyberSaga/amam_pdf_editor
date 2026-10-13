"""Batch 1 of the 02_列印 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, LINE, PAPER, PEEK24, pixmap
from studio import Studio

BODY, BODY_TOP, TRAY, SLOT = "#CFCCEA", "#ECEBF7", "#7B79B8", "#55537F"
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：淡紫灰機身配淺色頂面、深一階的進紙匣、倉鼠從進紙白紙後探頭兩手抓紙緣，下方深石板色出紙口吐出一張三行字的白紙。"
        "座標減半後倉鼠頭只剩 7 格寬，手掌只有 1.8 格。",
        "機身外緣 x 3/21、y 10/19，1.5 px 框；進紙匣 1 px 框、外緣 x 4/20，兩側各露 2 格；進紙白紙外緣 x 7/17、上緣 y 7；"
        "倉鼠用 PEEK24（8×6，紙緣當下巴），兩隻手掌各 2 格桃色壓在紙的上角；出紙口一列深藍 + 一列石板色，白紙逐像素畫、左下角捲出 1 格，"
        "兩行淡紫字線；按鈕 1 格深藍。",
        tempo="normal")
s.add("tray", "path", "back", d=rrect_d(4.5, 8.5, 19.5, 12, 1), fill=TRAY, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK24, 8, 1, "hamster")
s.add("sheet_in", "path", "object", d="M7.5 12V7.5H16.5V12", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
s.add("printer", "path", "object", d=rrect_d(3.75, 10.75, 20.25, 18.25, 1.5), fill=BODY, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("printer_top", "path", "object_fx", d="M4.5 13V12.25A0.75 0.75 0 0 1 5.25 11.5H18.75A0.75 0.75 0 0 1 19.5 12.25V13Z",
      fill=BODY_TOP, anim="fill")
pixmap(s, "button", ["N"], 17, 13, "object_fx", legend={"N": ("dot", INK)})
s.add("slot", "path", "object", d="M6.5 17.5V14.5H17.5V17.5", fill=SLOT, stroke=INK, stroke_width=1, anim="fill")
SHEET = [
    ".NNNNNNNN",
    ".NWWWWWWN",
    ".NWWWWWWN",
    ".NWWWWWWN",
    "NWWWWWWWN",
    "NWWWWWWWN",
    "NNNNNNNNN",
]
pixmap(s, "sheet_out", SHEET, 7, 16, "object", legend={"W": ("paper", PAPER), "N": ("ink", INK)})
s.add("text_lines", "path", "object_fx", d="M9 18.5H14M9 20.5H13", fill="none", stroke=LINE, stroke_width=1, anim="draw")
pixmap(s, "paw", ["PP......PP"], 7, 7, "front")
s.commit()
