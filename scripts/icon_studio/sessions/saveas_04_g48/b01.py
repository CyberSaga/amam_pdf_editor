"""Batch 1 of the 04_另存新檔 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import body_outline_d, rrect_d
from parts import INK, PEACH, WHITE, hamster48
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：磁片、倉鼠、色塊",
        "參考圖：紫色磁片偏右（x 15–43、y 4–37），標籤上是字線而不是倉鼠臉；倉鼠從磁片左緣後面探出頭、抱著磁片；右下角加號章。",
        "磁片照儲存 48 格版的構造縮成 0.78 倍（同樣 2.5 px 外框、右上切角、擋板 1.5 px 框、深色槽孔、白色標籤）；倉鼠頭 13×11.6 轉 -10°，"
        "身體藏在磁片後面。",
        tempo="normal")
s.add("hm_body", "ellipse", "hamster", cx=11.2, cy=30.0, rx=4.6, ry=6.6, fill=PEACH, stroke=INK, stroke_width=1.25,
      transform="rotate(-6 11.2 30)", anim="fill")
s.add("hm_belly", "ellipse", "hamster", cx=12.4, cy=30.8, rx=2.1, ry=4.2, fill=WHITE, transform="rotate(-6 11.2 30)", anim="fill")
hamster48(s, "hm", 9.8, 17.6, 6.6, 5.8, k=0.7, rot=-10, parts=("blocks",))
s.add("floppy", "path", "object", d=body_outline_d(16.25, 5.25, 41.75, 35.75, 2.2, 5.6, 1.0), fill="#9285D5", stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("shutter_plate", "path", "object", d=rrect_d(22.75, 4.75, 35.25, 15.25, 1.2), fill="#F7F7FA", stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("slot", "rect", "object", x=30.5, y=7, width=3, height=5.5, rx=0.8, fill="#2E3052", anim="fill")
s.add("label_paper", "path", "object", d=rrect_d(20.75, 19.75, 37.25, 32.75, 1.5), fill=WHITE, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.commit()
