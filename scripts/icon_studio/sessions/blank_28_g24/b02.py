"""Batch 2 of the 28_插入空白頁 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠改成圓胖的一團",
        "1× 看起來像戴黑面罩的貓：頭四周都是深藍外框、下巴收成 V 形，左耳又和紙的折角斜線黏在一起；加號章直徑 9 格太搶。"
        "在草稿裡試了 10 個版本：倉鼠頭身連成一團、兩頰最寬、不畫下巴線時最像倉鼠，和儲存 24 格版的臉一致。",
        "紙收窄 1 格（外緣 x 2/13），倉鼠下移 1 格、頭身一體 10×11 格（左側輪廓藏在紙緣下、右側加一列陰影）；"
        "手掌壓在紙緣；加號章縮為直徑 8、中心 (13.5, 18.5)。",
        tempo="normal")
s.look((12, 4, 11, 13), "像貓、左耳黏到折角")
s.mod("sheet", note="紙收窄 1 格", d=page_d(2.75, 2.75, 12.25, 20.25, 1.5, 3.5))
s.mod("flap", note="折角跟著移", d=flap_d(12.25, 2.75, 3.5, 0.75))
s.mod("sheet_shade", note="陰影跟著移", d="M11 7.5V19H3.5")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="重畫倉鼠")
BEAN = [
    ".NN....NN.",
    "NKKNNNNKKN",
    "NPPPPPPPPN",
    "NPHEPPHEPN",
    "NPEEWWEEPN",
    "NBWWRRWWBN",
    "NPWWWWWWSN",
    "NPPWWWWPSN",
    "NPPWWWWPSN",
    ".NPPPPPSN.",
    "..NNNNNN..",
]
pixmap(s, "hm", BEAN, 12, 6, "hamster")
pixmap(s, "paw", [".NN.", "NPPN", ".NN."], 10, 13, "front")
s.mod("badge_disc", note="加號章縮小", cx=13.5, r=3.5)
s.mod("badge_plus", note="加號跟著移", d="M13 16h1v2h2v1h-2v2h-1v-2h-2v-1h2Z")
s.commit()
