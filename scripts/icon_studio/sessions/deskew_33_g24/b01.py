"""Batch 1 of the 33_拉正PDF頁面 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK24, PURPLE_DARK, TEAL_DARK, arc_arrow, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：歪 4° 的紙、四角青綠 L 框、虛線框與十字線、紫色彎箭頭、紙上緣的倉鼠。",
        "虛線在 24 格只剩雜訊，只留中間一條直虛線；L 框改逐像素 2 px 深青綠；紙 1.5 px 框、同樣轉 4°；箭頭 1.5 px 深紫不包邊；探頭臉 8×6。",
        tempo="normal")
s.add("guide_v", "path", "back", d="M12 1V23", fill="none", stroke=TEAL_DARK, stroke_width=1, stroke_dasharray="1 1",
      stroke_opacity=0.7, anim="draw")
L = ["TTT", "T..", "T.."]
for i, (rows, x, y) in enumerate(((L, 2, 7), ([r[::-1] for r in L], 19, 7), (L[::-1], 2, 20), ([r[::-1] for r in L[::-1]], 19, 20))):
    pixmap(s, f"corner{i}", rows, x, y, "back", legend={"T": ("fill", TEAL_DARK)})
tilt = "rotate(4 12 15)"
s.add("sheet", "path", "object", d=page_d(6.75, 8.75, 17.25, 21.25, 1.5, 3), fill=PAPER, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", transform=tilt, anim="fill")
s.add("flap", "path", "object", d=flap_d(17.25, 8.75, 3, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", transform=tilt, anim="fill")
pixmap(s, "hm", PEEK24, 8, 2, "hamster")
arc_arrow(s, "arrow", 11.5, 18.5, 5.5, 240, 330, "object_fx", width=1.5, head_w=1.8, head_len=2.2, color=PURPLE_DARK,
          transform="matrix(1 0 0 -1 0 30)")
s.commit()
