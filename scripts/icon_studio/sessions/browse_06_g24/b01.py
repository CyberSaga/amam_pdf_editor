"""Batch 1 of the 06_瀏覽模式 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEEK24, WHITE, pixmap
from studio import Studio

NAVY = "#454A78"
CURSOR = [  # rows 1-22: ink outline N, white rim W, slate-navy body U (the 48 cursor at 0.51, rasterized)
    ".......N...........",
    "......NWN..........",
    ".....NWUWN.........",
    ".....NWUUWN........",
    ".....NWUUUWN.......",
    ".....NWUUUUWNN.....",
    ".....NWUUUUUWWN....",
    ".....NWUUUUUUUWN...",
    ".....NWUUUUUUUUWN..",
    ".....NWUUUUUUUUUWN.",
    ".....NWUUUUUUUUUUWN",
    ".....NWUUUUUUUUUUWN",
    ".....NWUUUUUUUUWWN.",
    ".....NWUUUUUUUWNN..",
    ".....NWUUUWUUUWN...",
    ".....NWUWWWUUUUWN..",
    "......NWNNNWUUUWN..",
    ".......N..NWUUUWN..",
    "..........NWUUUUWN.",
    "...........NWUUUWN.",
    "............NWWWN..",
    ".............NNN...",
]
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：正立的石板藍游標、2 px 白邊、2.5 px 深藍外框，倉鼠臉在頭部下半、身體被分叉處的白邊切掉，長斜邊內側一道白光。"
        "草稿：照 48 格斜 6° 的向量游標縮到 24 格，白邊和外框全是半透明的鋸齒，臉也壓到白邊上。",
        "游標改逐像素：深藍外框 1 格、白邊 1 格、石板藍本體，48 格的游標乘 0.51 點陣化（4 鄰格擴邊，斜邊是乾淨的 1 格階梯）；"
        "頭部第 8–13 列剛好有 8 格寬的石板藍，PEEK24 放 x 7–14、y 8–13，耳尖的深藍落在石板藍上、臉的兩側由石板藍襯出來，"
        "鼻子那列下面就是游標分叉；長斜邊內側 3 格 40% 白光。",
        tempo="normal")
pixmap(s, "cursor", CURSOR, 0, 1, "back", legend={"U": ("body", NAVY), "W": ("rim", WHITE), "N": ("ink", INK)})
pixmap(s, "hm", PEEK24, 7, 8, "hamster")
s.add("cursor_gloss", "path", "glint", d="M8 5h1v1h-1ZM9 6h1v1h-1ZM10 7h1v1h-1Z", fill=WHITE, fill_opacity=0.4,
      anim="pop")
s.commit()
