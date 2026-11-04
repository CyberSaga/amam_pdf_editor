"""Batch 1 of the 35_文件資訊 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import BIG_EARS, INK, LINE, PAPER, PURPLE, PURPLE_LIGHT, WHITE, flap_d, hamster_face_px, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：折角紙、左上探頭的倉鼠兩手搭在紙緣、4 列欄位、右下外半徑 8.5 的 i 章。原型比較過三種 24 格的 i："
        "2×2 圓點＋空 1 列＋2×4 直線、加襯線、圓點貼著外框——第一種在 24–32 px 最清楚，貼框的圓點和外框黏成一條。",
        "紙外緣 x 2/17、y 7/23（上方 7 列給倉鼠）、1.5 px 外框、折角 3.5；倉鼠用 48 格同一套構造（k 0.55、1 px 向量外框、"
        "眼睛鼻子腮紅放整數像素），cx 8；手掌各 2 格桃色壓在紙上緣；欄位 3 列（2 格淺紫標籤＋1 px 灰紫線，最上一列"
        "讓開折角）；圓章中心 (18, 18)、外半徑 5、1 px 外框，白色 i：圓點 2×2、空 1 列、直線 2×4，上下各留 1 列紫色。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(2.75, 7.75, 16.25, 22.25, 1.5, 3.5), fill=PAPER, stroke=INK,
      stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(16.25, 7.75, 3.5, 0.75), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
hamster_face_px(s, "hf", 24, 8, 7.8, 0.55, ears=BIG_EARS)
pixmap(s, "hf_paws", ["PP......PP"], 3, 7, "front")
rows = [(11, 12), (14, 11), (17, 10)]
s.add("keys", "path", "object_fx", d="".join(f"M4 {y}h2v1h-2Z" for y, _ in rows), fill=PURPLE_LIGHT, anim="pop")
s.add("vals", "path", "object_fx", d="".join(f"M7 {y}H{x1}v1H7Z" for y, x1 in rows), fill=LINE, anim="draw")
s.add("badge_disc", "circle", "badge", cx=18, cy=18, r=4.5, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
s.add("info_i", "path", "badge", d="M17 15h2v2h-2ZM17 18h2v4h-2Z", fill=WHITE, anim="pop")
s.commit()
