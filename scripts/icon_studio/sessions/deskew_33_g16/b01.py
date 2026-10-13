"""Batch 1 of the 33_拉正PDF頁面 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, PURPLE_DARK, TEAL_DARK, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：中間直虛線、四角 L 框、歪紙、深紫彎箭頭、探頭臉。",
        "虛線拿掉；L 框 2×2 逐像素；紙 1 px 框轉 4°；箭頭逐像素 ↗；臉用 16 格五列。",
        tempo="normal")
for i, (rows, x, y) in enumerate(((["TT", "T."], 1, 5), (["TT", ".T"], 13, 5), (["T.", "TT"], 1, 14), ([".T", "TT"], 13, 14))):
    pixmap(s, f"corner{i}", rows, x, y, "back", legend={"T": ("fill", TEAL_DARK)})
tilt = "rotate(4 8 10)"
s.add("sheet", "path", "object", d=page_d(4.5, 5.5, 11.5, 14.5, 1, 2), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", transform=tilt, anim="fill")
s.add("flap", "path", "object", d=flap_d(11.5, 5.5, 2, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", transform=tilt, anim="fill")
pixmap(s, "hm", PEEK16, 4, 1, "hamster")
pixmap(s, "arrow", ["..DD", "...D", "D.D.", ".D.."], 6, 9, "object_fx", legend={"D": ("fill", PURPLE_DARK)})
s.commit()
