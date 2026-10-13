"""Batch 04 of deskew_33_g48. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：臉坐到框線頂上、手掌放輕",
        "放大和儲存並排：臉的平底放在框線中間，框線蓋掉了口鼻區下緣，嘴巴貼著粗框；兩隻肉墊手壓在臉頰下、邊線太黑，搶走腮紅。",
        "照儲存的做法把平底對齊框線的上緣（歪紙上緣框線頂約 y 15），白色口鼻區整條露出；手掌縮小（k 0.75）、邊線 0.8，移到臉頰外側。",
        tempo="normal")
s.look((14.600000000000001, 5.199999999999999, 18, 12), "嘴貼框線、手掌太黑")
for eid in [e for e in list(s.elements) if e.startswith("hf_")]:
    s.rm(eid, note="臉往上、手掌放輕")
hamster_face48(s, "hg", 23.6, 15.2, 0.72)
paws48(s, "hg_paws", [(17.4, 15.4), (29.8, 16.2)], k=0.75, outline=0.8)
s.commit()
