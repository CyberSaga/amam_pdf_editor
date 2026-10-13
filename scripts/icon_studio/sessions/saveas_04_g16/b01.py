"""Batch 1 of the 04_另存新檔 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import body_outline_d
from parts import FACE16, INK, LINE, WHITE, badge_plus, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：縮小的磁片、左邊探頭的倉鼠、加號章。",
        "磁片照儲存 16 格版：1 px 外框、擋板一列加 1 格槽孔、白色標籤一條字線；倉鼠 16 格臉藏在磁片左緣後；加號章中心 (11.5, 11.5)。",
        tempo="normal")
pixmap(s, "hm", FACE16, 0, 4, "hamster")
s.add("floppy", "path", "object", d=body_outline_d(6.5, 1.5, 14.5, 12.5, 0.8, 2.0, 0.3), fill="#9285D5", stroke=INK,
      stroke_width=1, stroke_linejoin="round", anim="fill")
s.add("shutter_plate", "path", "object", d="M8.5 1.5H12.5V4.5H8.5Z", fill="#F7F7FA", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("slot", "rect", "object", x=11, y=2, width=1, height=2, fill="#2E3052", anim="fill")
s.add("label_paper", "path", "object", d="M7.5 6.5H13.5V11.5H7.5Z", fill=WHITE, stroke=INK, stroke_width=1, anim="fill")
s.add("label_line", "path", "object_fx", d="M9 8.5H12", fill="none", stroke=LINE, stroke_width=1, anim="draw")
badge_plus(s, "badge", 16, 11.5, 11.5)
s.commit()
