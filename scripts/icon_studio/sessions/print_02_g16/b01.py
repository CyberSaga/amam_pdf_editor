"""Batch 1 of the 02_列印 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PAPER, pixmap
from studio import Studio

BODY, BODY_TOP, TRAY, SLOT = "#CFCCEA", "#ECEBF7", "#7B79B8", "#55537F"
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：探頭的 8 格臉、兩隻 2 格手掌壓住進紙白紙的上角、兩側露出的進紙匣、深藍 + 石板色的出紙口、兩行字的出紙白紙。"
        "16 格只有 16 列：臉 5 列、紙緣 1 列、機身 7 列，出紙白紙只能和機身下半重疊。",
        "臉用儲存 16 格版的五列（耳蓋、粉耳、2×2 眼睛帶反光、白口鼻與鼻子）放 x 4–10，手掌併進同一張像素圖、各 2 格伸出臉外壓在紙角；"
        "進紙匣與進紙白紙放在最底層；機身 1 px 框、外緣 x 1/14、y 7/14，頂面一列淺色、按鈕 1 格；出紙口一列石板色，"
        "出紙白紙 1 px 框、左下角捲出 1 格、一行字線。",
        tempo="normal")
s.add("tray", "path", "back", d="M2.5 8V5.5H12.5V8", fill=TRAY, stroke=INK, stroke_width=1, anim="fill")
s.add("sheet_in", "path", "back", d="M4.5 8V5.5H10.5V8", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
HAMSTER = [
    "..NN.NN..",
    "..KKPKK..",
    ".PHEPHEP.",
    ".PEEPEEP.",
    ".BWWRWWB.",
    "PP.....PP",
]
pixmap(s, "hm", HAMSTER, 3, 0, "hamster")
s.add("printer", "path", "object", d="M2.5 7.5H12.5A1 1 0 0 1 13.5 8.5V12.5A1 1 0 0 1 12.5 13.5H2.5A1 1 0 0 1 1.5 12.5V8.5A1 1 0 0 1 2.5 7.5Z",
      fill=BODY, stroke=INK, stroke_width=1, anim="fill")
s.add("printer_top", "path", "object_fx", d="M2 8H13V9H2Z", fill=BODY_TOP, anim="fill")
pixmap(s, "button", ["N"], 11, 9, "object_fx", legend={"N": ("dot", INK)})
s.add("slot", "path", "object", d="M3 10H12V11H3Z", fill=SLOT, anim="fill")
s.add("sheet_out", "path", "object", d="M3.5 11.5H11.5V15.5H2.5V14.5H3.5Z", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
s.add("text_line", "path", "object_fx", d="M5 13.5H10", fill="none", stroke=LINE, stroke_width=1, anim="draw")
s.commit()
