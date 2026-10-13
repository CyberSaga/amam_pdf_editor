"""Batch 3 of the 11_縮圖 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠轉正",
        "48 px 實際像素看：頭轉 10° 後右耳和右側外框糊成一團灰、兩眼高低差 1 格、白色口鼻歪向右下，比 26 旋轉頁同尺寸的倉鼠髒；"
        "草稿試了 5°，耳朵仍然一高一低。方塊、框在 1× 都乾淨。",
        "倉鼠改回正面（不轉），頭、耳、五官在原位置重畫；右手掌移到和左手掌以頭中心對稱的位置（x 33.6）。",
        tempo="normal")
s.look((19, 3, 16, 11), "轉 10° 的臉在 1× 糊掉")
head = [e for e in list(s.elements) if e.startswith("hm_") and not e.startswith("hm_paw")]
for eid in head:
    s.rm(eid, note="轉正重畫" if eid == head[0] else None)
hamster48(s, "hm", 27, 11.6, 6.6, 5.6, k=0.68, eye_y=10.0)
s.mod("hm_paw1", note="手掌左右對稱", cx=33.6)
s.commit()
