"""Batch 1 of the 12_搜尋 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, pixmap
from studio import Studio

RIM = "#9A98D0"
CX = CY = 9.5
TILT = f"rotate(45 {CX} {CY})"
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：深藍外框 + 紫灰鏡框 + 深藍內框的鏡框、45° 的細頸與圓頭握柄、鏡片裡歪頭的倉鼠。座標減半後開口只剩直徑 9.75，"
        "歪頭的臉在格點上畫不出來。",
        "鏡框圓心 (9.5, 9.5)、外緣半徑 8.5（外緣落在 x/y 1 與 18）：深藍 1 + 紫灰 1.5 + 深藍 1，開口直徑 10；握把細頸 2 px 深藍、"
        "握柄外寬 4.5、1.5 px 框；倉鼠臉改成正面、逐像素 9 格寬：深藍耳蓋配粉色內耳、2×2 眼睛各帶白反光、眼間 1 格白色口鼻尖、"
        "鼻子、腮紅，下面兩列白色下巴，兩側與下緣交給鏡框當輪廓。",
        tempo="normal")
s.add("glass", "circle", "back", cx=CX, cy=CY, r=5.5, fill=PAPER, anim="fill")
FACE = [
    ".NN...NN.",
    "NKKNNNKKN",
    "PPPPPPPPP",
    "PPHEPHEPP",
    "PPEEWEEPP",
    "BWWWRWWWB",
    "PWWWWWWWP",
    "PPWWWWWPP",
]
pixmap(s, "hm", FACE, 5, 6, "hamster")
s.add("neck", "path", "object", d="M17 8.5H19.3V10.5H17Z", fill=INK, transform=TILT, anim="fill")
s.add("grip", "path", "object", d="M21.25 8H25.85A1.5 1.5 0 0 1 25.85 11H21.25A1.5 1.5 0 0 1 21.25 8Z", fill=RIM, stroke=INK,
      stroke_width=1.5, transform=TILT, anim="fill")
s.add("ring_ink", "circle", "object", cx=CX, cy=CY, r=6.75, fill="none", stroke=INK, stroke_width=3.5, anim="draw")
s.add("ring", "circle", "object", cx=CX, cy=CY, r=6.75, fill="none", stroke=RIM, stroke_width=1.5, anim="draw")
s.commit()
