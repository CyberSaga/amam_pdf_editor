"""Batch 1 of the 16_矩形 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, TEAL_DARK, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：1.5 px 框的白色矩形、左下探頭的倉鼠臉、兩格手掌壓在底邊、右邊一支 3 格深青綠小筆加深藍筆尖。",
        "矩形外緣 x 1–15、y 2–14，1 px 框、框內白；倉鼠用 16 格五列探頭臉，鼻子那列落在底邊上方、左側靠著左框；"
        "筆縮成 2 格深青綠＋1 格深藍筆尖，放在臉的右邊、不碰到腮紅；兩格桃色手掌壓在底邊上。",
        tempo="normal")
s.add("rect_fill", "path", "back", d="M1.5 2.5H14.5V13.5H1.5Z", fill=PAPER, anim="fill")
pixmap(s, "hm", PEEK16, 2, 8, "hamster")
s.add("rect", "path", "object", d="M1.5 2.5H14.5V13.5H1.5Z", fill="none", stroke=INK, stroke_width=1, anim="draw")
pixmap(s, "pen", ["..D", ".D.", "K.."], 9, 10, "front", legend={"D": ("body", TEAL_DARK), "K": ("nib", INK)})
pixmap(s, "paw", ["P....P"], 2, 13, "front")
s.commit()
