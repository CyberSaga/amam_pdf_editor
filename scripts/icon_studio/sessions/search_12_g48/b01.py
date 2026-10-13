"""Batch 1 of the 12_搜尋 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from kit import pencil_ellipse, pencil_line
from parts import INK, PAPER, PEACH, hamster48
from studio import Studio

RIM, RIM_DARK = "#9A98D0", "#7B79B8"
CX = CY = 18.5
TILT = f"rotate(45 {CX} {CY})"
s = Studio.open()
s.begin(1, "48 格：草稿與大色塊",
        "參考圖：放大鏡的紫灰色鏡框（外緣 x 3.5–34、y 3–35，圓心約 (18.7, 19)）佔畫面左上，45° 斜下的握把先接一段細頸、"
        "再接寬握柄到 (44.5, 45)；鏡片裡一隻倉鼠，頭向右歪約 20°，身體被鏡框切掉。",
        "鏡框圓心 (18.5, 18.5)、外緣半徑 15.5（外緣落在 x/y 3 與 34）：深藍 2 px 外框、紫灰 2.5 px 鏡框、深藍 1.25 px 內框，"
        "鏡片開口半徑 9.75、填白；握把沿 45°：細頸 3.5 寬（2 px 框、深一階紫灰）、握柄外寬 7、2.5 px 框、兩端全圓；"
        "倉鼠頭 13.6×12（k 0.7）轉 18°，身體橢圓藏在鏡框下，先鋪色塊。",
        tempo="slow")
rng = random.Random(1248)
pencil_ellipse(s, "sk_ring", CX, CY, 15.4, 15.4, rng, w=0.2, op=0.5, amp=0.1)
pencil_ellipse(s, "sk_open", CX, CY, 9.8, 9.8, rng, w=0.2, op=0.45, amp=0.1)
pencil_line(s, "sk_axis", (29.5, 29.5), (44.6, 44.6), rng, w=0.2, op=0.55, amp=0.08, overshoot=0.04)
pencil_ellipse(s, "sk_head", 18.0, 18.6, 6.8, 6.0, rng, w=0.2, op=0.5, amp=0.1)
s.layer("sketch", opacity=0.55)
s.add("glass", "circle", "back", cx=CX, cy=CY, r=10.25, fill=PAPER, anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=20.2, cy=27, rx=6.4, ry=5.6, fill=PEACH, stroke=INK, stroke_width=1.25,
      transform="rotate(18 20.2 27)", anim="fill")
hamster48(s, "hm", 18.0, 18.6, 6.8, 6.0, k=0.7, rot=18, parts=("blocks",))
s.add("neck", "path", "object", d=f"M{CX + 14} 16.75H{CX + 19.5}V20.25H{CX + 14}Z", fill=RIM_DARK, stroke=INK,
      stroke_width=2, stroke_linejoin="round", transform=TILT, anim="fill")
s.add("grip", "path", "object", d="M41 16.25H51.5A2.25 2.25 0 0 1 51.5 20.75H41A2.25 2.25 0 0 1 41 16.25Z", fill=RIM,
      stroke=INK, stroke_width=2.5, stroke_linejoin="round", transform=TILT, anim="fill")
s.add("ring_ink", "circle", "object", cx=CX, cy=CY, r=12.625, fill="none", stroke=INK, stroke_width=5.75, anim="draw")
s.add("ring", "circle", "object", cx=CX, cy=CY, r=12.25, fill="none", stroke=RIM, stroke_width=2.5, anim="draw")
s.commit(compare=True)
