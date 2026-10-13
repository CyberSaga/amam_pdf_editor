"""Batch 4 of the 01_開啟 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠坐上前片的標籤",
        "底邊放在前片主上緣（y 24），頭左下被前片標籤（y 21）擋住，只剩眼睛露出來，口鼻與腮紅都看不到，像沉進資料夾裡。",
        "頭縮到 k 0.72 並整個移到標籤上方（x 4.7–18.5），底邊落在標籤上緣 y 21，整張臉露出；右邊的 PDF 紙因此露出更多；兩隻肉墊手搭在標籤邊上。",
        tempo="normal")
s.look((8, 12, 20, 14), "臉沉進資料夾")
for eid in [e for e in list(s.elements) if e.startswith("hf_")]:
    s.rm(eid, note="移到標籤上")
hamster_face48(s, "hc", 11.6, 21.0, 0.72)
paws48(s, "hc_paws", [(7.0, 21.4), (16.2, 21.4)], k=0.8)
s.commit()
