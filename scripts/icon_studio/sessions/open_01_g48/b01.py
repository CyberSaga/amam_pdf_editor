"""Batch 1 of the 01_開啟 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, RED, YELLOW, YELLOW_DARK, flap_d, hamster48, page_d, pdf_mark_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：資料夾、PDF、倉鼠",
        "參考圖：打開的黃色資料夾佔下半（後片深一階、左上帶標籤，前片 x 4–41、y 21–45 也帶左上標籤），一張帶紅色 PDF 標誌的折角紙"
        "從右側後面冒出（x 26.5–43、y 7–32），倉鼠大頭從資料夾裡探出、左手搭在後片邊上。",
        "前後片 2.5 px 深藍框，後片右緣多露出 2 格；紙在最底層；倉鼠頭 17×15（k 0.88）夾在前後片之間，前片擋住下巴；先鋪色塊。",
        tempo="normal")
s.add("sheet", "path", "back", d=page_d(27.75, 8.25, 41.75, 40, 2.5, 6), fill=PAPER, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "back", d=flap_d(41.75, 8.25, 6, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
s.add("pdf_mark", "path", "back", d=pdf_mark_d(29.8, 12.6, 9.4, 10.0), fill="none", stroke=RED, stroke_width=1.6,
      stroke_linejoin="round", anim="draw")
s.add("folder_back", "path", "back", d="M6.25 16.25H13.6Q15 16.25 15.8 17.5L17 19.75H41.25A2 2 0 0 1 43.25 21.75V42.75A2 2 0 0 1 41.25 44.75H6.25A2 2 0 0 1 4.25 42.75V18.25A2 2 0 0 1 6.25 16.25Z",
      fill=YELLOW_DARK, stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 17.5, 14.4, 8.6, 7.4, k=0.88, eye_y=12.6, parts=("blocks",))
s.add("folder_front", "path", "front", d="M6.25 21.25H17.2Q18.6 21.25 19.4 22.3L20.6 24.25H39.25A2 2 0 0 1 41.25 26.25V42.75A2 2 0 0 1 39.25 44.75H6.25A2 2 0 0 1 4.25 42.75V23.25A2 2 0 0 1 6.25 21.25Z",
      fill=YELLOW, stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.commit()
