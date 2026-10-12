"""Batch 8 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(2, "使用者回饋：改用 48 px 版的風格重畫",
        "使用者回饋：只有 48 px 版的風格令人滿意，24 px 版的精細度不足以呈現那個風格（暖棕框、沒有白色口鼻、眼睛沒有反光、本體與擋板是平塗）。把 48 版直接縮到 24 px：風格還在但全部變灰變糊。版面上的差異：48 版的臉有 14 列，對半是 7 列，我的 24 版只給了 6 列。",
        "重排版面讓臉有 7 列：擋板白區改 4 列（2–9）、紫色間隔 1 列、標籤窗 10–19（內白 7 列）。擦掉舊的倉鼠，改用 48 版的結構對半移植（x/2, y/2−1），再逐一對齊像素。",
        tempo="normal")
for eid in ("ear0", "ear1", "head", "eye0", "eye1", "nose"):
    s.rm(eid, note="擦掉舊版倉鼠" if eid == "ear0" else None)
s.look((6, 2, 12, 17.5), "版面：臉要 7 列")
s.mod("shutter_plate", note="擋板 2–10 → 2–9", d=rrect_d(7.5, 2.5, 16.5, 8.5, 0.75))
s.mod("slot", note="槽孔 2×3 移到第 4–6 列", y=4, height=3)
s.mod("label_paper", note="標籤窗 11–19 → 10–19，內白 7 列", d=rrect_d(6.5, 10.5, 17.5, 18.5, 1.0))
s.mod("label_frame", d=rrect_d(6.5, 10.5, 17.5, 18.5, 1.0))
s.commit()
