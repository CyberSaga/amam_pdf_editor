"""Batch 1 of the 24_顯示-隱藏註解 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, PURPLE, TEAL, WHITE, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：1.5 px 框的杏仁眼、8×8 逐像素虹膜、PEEK24 倉鼠趴在上眼瞼、右下減號章。16 格的向量眼瞼只有 1 px，"
        "斜段全變成淡灰階梯，眼睛讀不出來；草稿試了 10 種：逐像素杏仁眼 13×9（左右角各 1 格尖）最像眼睛，虹膜加深藍外圈會變成靶心，"
        "拿掉外圈、5×5 青綠圓盤配 3×3 瞳孔最清楚。",
        "眼睛畫成一張逐像素圖放 x 0–12、y 5–13：深藍眼瞼、白色眼白、青綠虹膜（圓角 5×5）、3×3 瞳孔左上一格白反光；"
        "倉鼠臉用 PEEK16（耳蓋、粉耳、2×2 眼睛帶反光、白口鼻、鼻、腮紅）放 x 4–10，鼻子那列正好坐在眼瞼頂上；"
        "減號章外半徑 3.5、中心 (12.5, 12.5)，白色橫槓 5×1，壓住眼睛右角。",
        tempo="normal")
pixmap(s, "hm", PEEK16, 4, 0, "hamster")
EYE = [
    "....NNNNN....",
    "..NNWWWWWNN..",
    ".NWWWTTTWWWN.",
    ".NWWTHNNTWWN.",
    "NWWWTNNNTWWWN",
    ".NWWTNNNTWWN.",
    ".NWWWTTTWWWN.",
    "..NNWWWWWNN..",
    "....NNNNN....",
]
pixmap(s, "eye", EYE, 0, 5, "object", legend={"W": ("white", PAPER), "T": ("iris", TEAL), "N": ("ink", INK),
                                               "H": ("hl", WHITE)})
s.add("badge_disc", "circle", "badge", cx=12.5, cy=12.5, r=3, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
s.add("badge_minus", "path", "badge", d="M10 12h5v1h-5Z", fill=WHITE, anim="pop")
s.commit()
