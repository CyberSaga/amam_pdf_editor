"""Batch 3 of the 01_開啟 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face_px
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：前片上緣拉平",
        "前片左邊的標籤只有 6.75 格寬，10.5 格寬的頭坐不上去，右半掉到低一階的上緣後面，口鼻被擋掉。",
        "24 格的前片拿掉標籤的台階，上緣拉平在 y 11.25（1.5 px 細節在這個尺寸本來就看不出來），倉鼠底邊坐在這條線上。",
        tempo="normal")
s.look((2, 9, 18, 4), "前片台階擋住臉")
s.mod("folder_front", note="上緣拉平", d="M3.25 11.25H19.25A1 1 0 0 1 20.25 12.25V21.25H2.25V12.25A1 1 0 0 1 3.25 11.25Z")
for eid in [e for e in list(s.elements) if e.startswith("hf_")]:
    s.rm(eid, note="頭往上 1 格")
hamster_face_px(s, "hc", 24, 9, 11.1, 0.55)
s.commit()
