"""Batch 2 of the 17_螢光筆 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEACH, YELLOW, hamster_bean_px, pixmap
from studio import Studio

COLLAR = "#6C6E9E"
GLOSS = "#FFF1BF"
s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。這隻是畫在同一張逐像素圖裡的方盒臉，在 1× 像戴面罩的貓，左手是一條三格長的手臂；"
        "48 格已改成躲在筆後的圓胖倉鼠，兩隻手掌抱在筆頭兩邊。",
        "倉鼠拆出來改用同一套構造（k 0.5、中心 (9, 7)，1 px 外框的向量輪廓、整數像素的眼睛鼻子腮紅），放在筆的下層；"
        "筆重畫成一張只有筆的逐像素圖：筆頭照 2:1 階梯斜切過倉鼠胸口，其餘筆身、筆夾、筆尖、筆痕不變；兩隻手掌各 2 格桃色加框，"
        "搭在筆頭左上角和右上角（筆的上層）。",
        tempo="normal")
s.look((2, 0, 14, 13), "方盒臉、長手臂")
for eid in [e for e in list(s.elements) if e.startswith("hl_")]:
    s.rm(eid, note="舊圖擦掉（倉鼠和筆畫在同一張）")
hamster_bean_px(s, "hb", 24, 9, 7, 0.5, layer="hamster", body=10, feet=False)
MARKER = [
    "........................",
    "........................",
    "........................",
    "........................",
    "........................",
    "........................",
    "........................",
    "........................",
    "..............N.........",
    "............NNN.........",
    "..........NNYLN.........",
    "........NNYYYYLN........",
    "........NYYYYYLN........",
    ".........NYYYYYLN.......",
    ".........NYYYYYLN.......",
    "..........NYYYYNNN......",
    "..........NYYNNCCN......",
    "...........NNCCCCN......",
    "...........NCCCCNN......",
    "............NNNNN.......",
    ".............NYYN.......",
    "......yyyyyyyNYYNyy.....",
    ".....yyyyyyyyyNNyyyy....",
    "........................",
]
pixmap(s, "mk", MARKER, 0, 0, "object", legend={"y": ("band", YELLOW), "Y": ("barrel", YELLOW), "L": ("gloss", GLOSS),
                                                 "C": ("collar", COLLAR), "N": ("ink", INK)})
PAWS = [
    ".......NN.",
    "......NPPN",
    ".NN....NN.",
    "NPPN......",
    ".NN.......",
]
pixmap(s, "pw", PAWS, 6, 8, "front", legend={"P": ("pads", PEACH), "N": ("rim", INK)})
s.commit()
