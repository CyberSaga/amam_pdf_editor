"""Batch 1 of the 04_另存新檔 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import body_outline_d, rrect_d
from parts import BEAN24, INK, LINE, PAW24, WHITE, badge_plus, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：縮小的儲存磁片（標籤上字線）、從左緣後面探頭抱住磁片的倉鼠、右下加號章。",
        "磁片照儲存 24 格版的構造縮小：1.5 px 外框、1 px 擋板與標籤框、2×2 槽孔、右下陰影線；倉鼠 BEAN24 藏在磁片左緣後、"
        "手掌壓在磁片邊上；加號章中心 (18.5, 18.5)。",
        tempo="normal")
pixmap(s, "hm", BEAN24, 0, 6, "hamster")
s.add("floppy", "path", "object", d=body_outline_d(8.75, 2.75, 21.25, 18.25, 1.25, 3.0, 0.6), fill="#9285D5", stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("shade", "path", "object_fx", d="M20.4 7V16.9Q20.4 17.4 19.9 17.4H10.2", fill="none", stroke="#6A5EB6",
      stroke_width=0.8, stroke_opacity=0.5, stroke_linecap="round", anim="draw")
s.add("shutter_plate", "path", "object", d=rrect_d(11.5, 2.5, 18.5, 7.5, 0.6), fill="#F7F7FA", stroke=INK,
      stroke_width=1, stroke_linejoin="round", anim="fill")
s.add("slot", "rect", "object", x=15, y=4, width=2, height=2, rx=0.3, fill="#2E3052", anim="fill")
s.add("label_paper", "path", "object", d=rrect_d(10.5, 10.5, 19.5, 17.5, 0.8), fill=WHITE, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("label_lines", "path", "object_fx", d="M12 12.5H18M12 14.5H16", fill="none", stroke=LINE, stroke_width=1, anim="draw")
pixmap(s, "paw", PAW24, 7, 12, "front")
badge_plus(s, "badge", 24, 18.5, 18.5)
s.commit()
