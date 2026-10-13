"""Batch 1 of the 28_插入空白頁 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PURPLE, WHITE, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：窄紙、頭身一團的倉鼠扶著紙緣、直徑 8 的加號章。16 格只剩 7 欄給倉鼠：右側再畫外框，眼睛就貼著框線、臉變成一個黑盒子；"
        "加號章試過有框／無框、3×3／5×5，深藍環配 5×5 白加號在 1× 最清楚。",
        "紙外緣 x 1/9、y 1/14，折角 3；倉鼠臉照儲存 16 格版：耳朵 2 格深藍蓋 + 粉色內耳、2×2 眼睛帶反光、1 格眼距、"
        "白色口鼻只留一列，左邊由紙緣當輪廓、右邊不畫框；加號章外半徑 3.5、中心 (9.5, 11.5)，壓住倉鼠身體。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(1.5, 1.5, 8.5, 13.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(8.5, 1.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
HAMSTER = [
    ".NN.NN.",
    ".KKPKK.",
    "PHEPHEP",
    "PEEPEEP",
    "BWWRWWB",
    "PPWWWPP",
    "PPPPPPP",
    ".PPPPP.",
]
pixmap(s, "hm", HAMSTER, 9, 2, "hamster")
s.add("badge_disc", "circle", "badge", cx=9.5, cy=11.5, r=3, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
s.add("badge_plus", "path", "badge", d="M9 9h1v2h2v1h-2v2h-1v-2h-2v-1h2Z", fill=WHITE, anim="pop")
s.commit()
