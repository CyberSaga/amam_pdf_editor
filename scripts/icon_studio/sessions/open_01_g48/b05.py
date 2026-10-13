"""Batch 5 of the 01_開啟 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：前片上緣拉平、大頭坐回去",
        "坐上標籤的頭只能縮到 k 0.72，而且標籤 2.5 px 的框線上緣在 y 20，蓋掉了嘴和口鼻的下緣，臉像被切了一刀，還是比參考小一圈。",
        "前片拿掉標籤台階、上緣拉平在 y 21.25（和從檔案插入頁的資料夾一致），倉鼠回到 k 0.85 的大頭，底邊對齊框線上緣 y 20.1（和儲存的頭坐在窗框上一樣），"
        "肉墊手搭在前片邊上；前片的反光線跟著拉直。",
        tempo="normal")
s.look((4, 12, 22, 12), "標籤框線切到嘴")
s.mod("folder_front", note="上緣拉平",
      d="M6.25 21.25H39.25A2 2 0 0 1 41.25 23.25V42.75A2 2 0 0 1 39.25 44.75H6.25A2 2 0 0 1 4.25 42.75V23.25A2 2 0 0 1 6.25 21.25Z")
s.mod("folder_gloss", note="反光拉直", d="M7.6 23.6H38")
for eid in [e for e in list(s.elements) if e.startswith("hc_")]:
    s.rm(eid, note="換回大頭")
hamster_face48(s, "hd", 17.4, 20.1, 0.85)
paws48(s, "hd_paws", [(11.6, 21.4), (23.2, 21.4)], k=0.9)
s.commit()
