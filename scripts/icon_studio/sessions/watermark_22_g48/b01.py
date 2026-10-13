"""Batch 1 of the 22_添加浮水印 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PURPLE, PURPLE_DARK, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：紙、倉鼠、印章的色塊",
        "參考圖：折角紙在下（x 8–38、y 14–45），倉鼠大頭從紙上緣後面探出、雙手抓著一顆紫色印章壓在紙上；紙中央一滴淡紫水滴、"
        "下面一條淡線，右下角加號章。",
        "紙沿用規格；倉鼠頭 18×15（和儲存的臉同尺寸），眼睛提高到 y 10.2，嘴巴交給印章擋住；印章：圓鈕 + 脖子 + 寬底座，"
        "紫色 1.5 px 深藍框，底座下緣一條深紫。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(9.25, 15.25, 36.75, 43.75, 2.5, 7), fill=PAPER, stroke=INK,
      stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(36.75, 15.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 20.5, 12.4, 9.0, 7.6, k=0.92, eye_y=10.2, mouth=False, parts=("blocks",))
s.add("stamp_neck", "path", "front", d="M19.25 16.5H22.75V20.75H19.25Z", fill=PURPLE, stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("stamp_knob", "ellipse", "front", cx=21, cy=16.6, rx=2.9, ry=2.1, fill=PURPLE, stroke=INK, stroke_width=1.5, anim="fill")
s.add("stamp_base", "path", "front", d="M15 20.75H27A1.25 1.25 0 0 1 28.25 22V23.5A1.25 1.25 0 0 1 27 24.75H15A1.25 1.25 0 0 1 13.75 23.5V22A1.25 1.25 0 0 1 15 20.75Z",
      fill=PURPLE, stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("stamp_rim", "path", "front", d="M15 23.2H27", fill="none", stroke=PURPLE_DARK, stroke_width=1.2, stroke_linecap="round", anim="draw")
s.commit()
