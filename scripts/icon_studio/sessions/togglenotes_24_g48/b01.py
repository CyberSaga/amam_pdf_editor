"""Batch 1 of the 24_顯示-隱藏註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import random

from kit import pencil_curve, pencil_ellipse
from parts import INK, PAPER, PURPLE, TEAL, hamster48
from studio import Studio

s = Studio.open()
s.begin(1, "48 格：構圖草稿與大色塊",
        "參考圖：一隻橫躺的大眼睛（杏仁形，左角尖在 x 3.5、右角在 x 38.5，上眼瞼最高 y 15、下眼瞼最低 y 36），青綠虹膜中心 "
        "(21, 25.5)、半徑約 7，深藍瞳孔帶白色反光；倉鼠從上眼瞼後面探頭、頭往右歪；紫色減號圓章壓在右下角。",
        "眼睛用兩條二次曲線（上下眼瞼）圍成，路徑兩角 x 4.75/39.25、控制點 (22, 6.5)/(22, 43.5)，2.5 px 深藍框、白色眼白；"
        "虹膜先鋪青綠圓 r 6.25（之後加框線）；倉鼠頭 14×12、中心 (25, 12.5)、往右歪 12°，眼睛提高到 y 11.2，下半藏在眼瞼後；"
        "圓章外半徑 6.5、中心 (37.5, 35.5)。",
        tempo="slow")
rng = random.Random(2448)
pencil_curve(s, "sk_lid_top", [(4.6, 25.1), (12, 18.2), (22, 15.6), (32, 18.0), (39.4, 24.9)], w=0.2, op=0.55)
pencil_curve(s, "sk_lid_bot", [(4.6, 25.0), (12, 31.8), (22, 34.4), (32, 32.1), (39.3, 25.1)], w=0.2, op=0.55)
pencil_ellipse(s, "sk_iris", 21.5, 25.5, 7.0, 7.0, rng, w=0.2, op=0.5, amp=0.08)
pencil_ellipse(s, "sk_head", 25, 12.5, 7.0, 6.0, rng, w=0.2, op=0.5, amp=0.1)
pencil_ellipse(s, "sk_badge", 37.5, 35.5, 6.5, 6.5, rng, w=0.2, op=0.5, amp=0.08)
s.layer("sketch", opacity=0.55)
hamster48(s, "hm", 25, 12.5, 7.0, 6.0, k=0.72, eye_y=11.2, rot=12, parts=("blocks",))
s.add("eye", "path", "object", d="M4.75 25Q22 6.5 39.25 25Q22 43.5 4.75 25Z", fill=PAPER, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
s.add("iris", "circle", "object_fx", cx=21.5, cy=25.5, r=6.25, fill=TEAL, anim="fill")
s.add("badge_disc", "circle", "badge", cx=37.5, cy=35.5, r=5.75, fill=PURPLE, stroke=INK, stroke_width=1.5, anim="fill")
s.commit(compare=True)
