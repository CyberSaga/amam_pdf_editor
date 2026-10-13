"""Batch 2 of the 23_浮水印列表 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_bean_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠怪、不如儲存精緻。夾在兩張紙之間的是逐像素方臉、斜角耳朵像貓。",
        "改用 48 格同一套構造（1 px 向量外框＋整數像素五官），仍夾在後紙與前紙之間（重排圖層順序）。",
        tempo="normal")
s.look((14, 8, 10, 10), "方臉")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
before = set(s.elements)
hamster_bean_px(s, "hb", 24, 19, 13.4, 0.45, layer="object", body=9, feet=False)
new = [e for e in s.elements if e not in before]
zb, zs = s.elements["back1"]["z"], s.elements["sheet"]["z"]
for i, eid in enumerate(new):
    s.restack(eid, zb + (zs - zb) * (i + 1) / (len(new) + 1), note="夾在兩張紙之間")
s.commit()
