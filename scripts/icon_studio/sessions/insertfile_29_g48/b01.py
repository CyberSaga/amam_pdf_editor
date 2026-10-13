"""Batch 1 of the 29_從檔案插入頁 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PAPER, YELLOW, YELLOW_DARK, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：資料夾、紙、倉鼠",
        "參考圖：黃色資料夾佔下半（後片帶左上角標籤 x 6–38、y 22–46，前片 x 8–38、y 29–46），一張有字線的折角紙從資料夾後面"
        "往上抽出（x 19–40、y 4–34），倉鼠坐在資料夾裡揮手，一支青綠彎箭頭從資料夾口往右上指。",
        "前後片都用 2.5 px 深藍框，後片深一階黃；紙夾在後片後面；倉鼠頭 16.4×14（k 0.85）放在前後片之間，前片擋住下巴。",
        tempo="normal")
s.add("sheet", "path", "back", d=page_d(20.25, 5.25, 38.75, 40, 2.5, 7), fill=PAPER, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "back", d=flap_d(38.75, 5.25, 7, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", anim="fill")
for i, y in enumerate((13.5, 17.0, 20.5)):
    s.add(f"line{i}", "path", "back", d=f"M24.5 {y}H{33.5 if i else 30.5}", fill="none", stroke=LINE, stroke_width=1.5,
          stroke_linecap="round", anim="draw")
s.add("folder_back", "path", "back", d="M8.5 22.75H14.4Q15.4 22.75 16 23.55L17.3 25.25H35.5A1.75 1.75 0 0 1 37.25 27V44A1.75 1.75 0 0 1 35.5 45.75H8.5A1.75 1.75 0 0 1 6.75 44V24.5A1.75 1.75 0 0 1 8.5 22.75Z",
      fill=YELLOW_DARK, stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
hamster48(s, "hm", 17.2, 22.4, 8.2, 7.0, k=0.85, eye_y=21.0, parts=("blocks",))
s.add("folder_front", "path", "front", d="M10.5 29.25H35.5A1.75 1.75 0 0 1 37.25 31V44A1.75 1.75 0 0 1 35.5 45.75H10.5A1.75 1.75 0 0 1 8.75 44V31A1.75 1.75 0 0 1 10.5 29.25Z",
      fill=YELLOW, stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="fill")
s.commit()
