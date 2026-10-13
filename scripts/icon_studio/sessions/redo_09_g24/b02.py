"""Batch 2 of the 09_重做 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PEEK24, pix_d
from studio import Studio

FACE = PEEK24 + [  # 8 x 8: PEEK24 closed by a peach chin with shaded corners (same face as 10_全螢幕 24 px)
    "SPWWWWPS",
    ".SPPPPS.",
]
s = Studio.open()
s.begin(6, "24 格：倉鼠改成 8 格寬的臉",
        "和其他圖示一起在 24–32 px 看：10×10、四周包深藍框的豆子比箭頭還搶眼，復原的倉鼠只有 8 格寬，兩個圖示並排時重做頭重腳輕；"
        "鉤的內緣加上豆子的左框，左邊是一條 2–3 格的黑帶。",
        "倉鼠改成 8×8 的臉（PEEK24 耳朵以下不畫側框，加桃色下巴、兩角陰影桃色，和全螢幕 24 格同一張臉），放 x 8–15、y 14–21："
        "耳朵和箭頭頭部下角隔一列，鉤的尾巴尖停在臉的左頰旁，鉤的內緣直接當臉的左輪廓。",
        tempo="normal")
s.look((5, 12, 13, 11), "豆子太重、左邊黑帶")
for i, eid in enumerate([e for e in list(s.elements) if e.startswith("hm_")]):
    ch = {"outline": "N", "ears_in": "K", "peach": "P", "peach_shade": "S", "eyes": "E", "eyes_hl": "H", "blush": "B",
          "muzzle": "W", "nose": "R"}[eid[3:]]
    s.mod(eid, note="換成 8 格寬的臉" if i == 0 else None, d=pix_d(FACE, ch, 8, 14))
s.commit()
