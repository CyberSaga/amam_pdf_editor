"""Batch 1 of the 16_矩形 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, PAPER_SHADE, PEEK24, TEAL_DARK, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：2.5 px 深藍框的白色矩形、框內右下淡陰影、倉鼠在左下從底邊後面探頭（左耳與下巴藏在框下）、"
        "兩手搭在底邊上、右手邊一支青綠小筆筆尖朝左下。",
        "矩形外緣 x 1–23、y 3–21，1.5 px 框（路徑內縮 0.75），框內白、右下 1 px 淡陰影；倉鼠用 PEEK24 再接一列白色口鼻，"
        "最下一列被底邊蓋住一半，左側直接靠著左框（不畫側框）；筆在 24 格是細線：3 格深青綠斜線＋1 格深藍筆尖，不包邊；"
        "手掌是壓在底邊上的桃色像素。",
        tempo="normal")
d = rrect_d(1.75, 3.75, 22.25, 20.25, 0.75)
s.add("rect_fill", "path", "back", d=d, fill=PAPER, anim="fill")
s.add("rect_shade", "path", "back", d="M20.5 5.5V18.5H12", fill="none", stroke=PAPER_SHADE, stroke_width=1, anim="draw")
pixmap(s, "hm", PEEK24 + ["PWWWWWWP"], 3, 13, "hamster")
s.add("rect", "path", "object", d=d, fill="none", stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="draw")
pixmap(s, "pen", ["...D", "..D.", ".D..", "K..."], 11, 15, "front", legend={"D": ("body", TEAL_DARK), "K": ("nib", INK)})
pixmap(s, "paw", ["P.....PP"], 3, 19, "front")
s.commit()
