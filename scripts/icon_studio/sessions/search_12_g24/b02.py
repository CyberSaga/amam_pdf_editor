"""Batch 2 of the 12_搜尋 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import pixmap
from studio import Studio

CX = CY = 10
TILT = f"rotate(45 {CX} {CY})"
s = Studio.open()
s.begin(6, "24 格：鏡片放大、臉改回標準 24 格臉",
        "放大看：開口只有 10 格，耳蓋貼著鏡框內緣、兩團深藍黏在一起；最下兩列的桃色角被鏡框蓋掉一半，混成褐色斑點；"
        "9 格臉的眼睛只隔 1 格，像 16 格的臉被放大。草稿裡試了三種：鏡框外緣半徑 9、開口 11 格時，10 格寬的標準臉放得下，"
        "耳朵和腮紅都離鏡框 1 格。",
        "鏡框圓心移到 (10, 10)、外緣半徑 9（外緣仍落在 x/y 1），開口直徑 11；臉換成 BEAN24 的五官（眼間 2 格、眼間白口鼻尖、"
        "2 格鼻子、腮紅貼著臉緣），耳朵那列兩側不畫深藍（鏡框就是輪廓），最下兩列只留白肚子與兩側桃色；握把跟著外移。",
        tempo="normal")
s.look((4, 5, 12, 10), "耳蓋貼鏡框、下巴角變褐色")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="重畫臉")
s.mod("glass", note="開口放大", cx=CX, cy=CY, r=6)
FACE = [
    ".NN....NN.",
    "PKKNNNNKKP",
    "PPPPPPPPPP",
    "PPHEPPHEPP",
    "PPEEWWEEPP",
    "PBWWRRWWBP",
    "PPWWWWWWPP",
    "WWPWWWWPWW",
]
pixmap(s, "hm", FACE, 5, 7, "hamster")
s.mod("neck", note="握把跟著外移", d="M18 9H20.3V11H18Z", transform=TILT)
s.mod("grip", d="M22.25 8.5H26.15A1.5 1.5 0 0 1 26.15 11.5H22.25A1.5 1.5 0 0 1 22.25 8.5Z", transform=TILT)
s.mod("ring_ink", note="鏡框外緣半徑 9", cx=CX, cy=CY, r=7.25)
s.mod("ring", cx=CX, cy=CY, r=7.25)
s.commit()
