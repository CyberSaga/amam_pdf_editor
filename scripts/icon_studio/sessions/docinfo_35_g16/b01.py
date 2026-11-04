"""Batch 1 of the 35_文件資訊 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PAPER, PURPLE, WHITE, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：左上探頭的倉鼠、寫了 3 列欄位的紙、右下的 i 章（2×2 圓點＋2×3 直線）。16 格放不下標籤和手掌；"
        "原型裡加號章那種向量圓章，i 的圓點黏在外框的反鋸齒上，讀成一條直線。",
        "紙外緣 x 1/12、y 5/16，1 px 外框、折角 3；臉用 16 格五列的大耳朵臉（7 格寬）放 x 1–7、坐在紙上緣；"
        "3 條 1 px 灰紫線（4/4/3 格，讓開折角和圓章）；圓章改成 8×8 的像素圓（深藍外框、紫色內面），"
        "白色 i 2 格寬：圓點 1 列、空 1 列、直線 3 列。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(1.5, 5.5, 11.5, 15.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(11.5, 5.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", ["NN...NN", "KKKPKKK", "PHEPHEP", "PEEPEEP", "BWWRWWB"], 1, 0, "hamster")
s.add("lines", "path", "object_fx", d="M3 8H7v1H3ZM3 10H7v1H3ZM3 12H6v1H3Z", fill=LINE, anim="draw")
BADGE = [
    "..NNNN..",
    ".NuuuuN.",
    "NuuWWuuN",
    "NuuuuuuN",
    "NuuWWuuN",
    "NuuWWuuN",
    ".NuWWuN.",
    "..NNNN..",
]
pixmap(s, "badge", BADGE, 8, 8, "badge",
       legend={"u": ("disc", PURPLE), "N": ("ring", INK), "W": ("info", WHITE)})
s.commit()
