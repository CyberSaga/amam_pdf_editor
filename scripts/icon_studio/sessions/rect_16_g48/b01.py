"""Batch 1 of the 16_矩形 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, hamster48
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：矩形框與探頭的倉鼠",
        "參考圖：一個橫長的深藍粗框矩形（外緣約 x 3–45、y 5.5–42.5，四角微圓），框內左下一隻倉鼠從底邊後面探出頭，"
        "臉頰貼著左邊框、兩隻手搭在底邊上，右手拿著一支小筆。",
        "矩形外緣 x 3–45、y 6–42，2.5 px 框（路徑內縮 1.25，外緣落在整數格）、角半徑 2.5，框內填白；框線獨立一層放在倉鼠上面，"
        "讓底邊擋住倉鼠的下巴、左邊框蓋住頭的左輪廓與左耳外緣；倉鼠頭 15.6×13.6（k 0.84），中心 (12, 33.6)。",
        tempo="normal")
d = rrect_d(4.25, 7.25, 43.75, 40.75, 1.25)
s.add("rect_fill", "path", "back", d=d, fill=PAPER, anim="fill")
hamster48(s, "hm", 12.0, 33.6, 7.8, 6.8, k=0.84, parts=("blocks",))
s.add("rect", "path", "object", d=d, fill="none", stroke=INK, stroke_width=2.5, stroke_linejoin="round", anim="draw")
s.commit()
