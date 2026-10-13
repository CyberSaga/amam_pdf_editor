"""Batch 1 of the 06_瀏覽模式 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEEK16, WHITE, pixmap
from studio import Studio

NAVY = "#454A78"
CURSOR = [  # ink outline N, white rim W, slate-navy body U (the 48 cursor at 0.38, rasterized)
    ".NWNN.......",
    "NWUWWN......",
    "NWUUUWN.....",
    "NWUUUUWN....",
    "NWUUUUUWN...",
    "NWUUUUUUWN..",
    "NWUUUUUUUWN.",
    "NWUUUUUUUUWN",
    "NWUUUUUUUWN.",
    "NWUUUUUWWN..",
    "NWUUWUUUWN..",
    "NWUWNWUUWN..",
    ".NWNNWUUUWN.",
    "..N..NWUUWN.",
    ".....NWUWN..",
    "......NWN...",
]
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：逐像素的正立游標（深藍框、白邊、石板藍本體），PEEK24 的臉在頭部下半。16 格的游標頭部最寬只有 8 格、"
        "而且只有 2 列，7×5 的臉放不進石板藍裡；試過臉放 x 1（蓋掉左邊的白邊）、加一列下巴（蓋住分叉、游標只剩尖端）。",
        "游標照 48 格乘 0.38 點陣化，佔滿 16 列；臉用 PEEK16 放在頭部下半 x 2–8、y 6–10，疊在游標上面：左邊留著白邊和外框、"
        "右邊是長斜邊，鼻子那列正好坐在游標分叉的白邊上，像從游標的窗口探頭；尖端和尾巴都露在臉外，游標形狀讀得出來。",
        tempo="normal")
pixmap(s, "cursor", CURSOR, 0, 0, "back", legend={"U": ("body", NAVY), "W": ("rim", WHITE), "N": ("ink", INK)})
pixmap(s, "hm", PEEK16, 2, 6, "hamster")
s.commit()
