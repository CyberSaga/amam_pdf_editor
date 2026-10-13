"""Batch 1 of the 33_拉正PDF頁面 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, TEAL, TEAL_DARK, flap_d, hamster48, page_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：歪掉的紙、對齊框與參考線",
        "參考圖：一張略向右歪的折角紙（約 4°），四角青綠色 L 形對齊框、紙後面一圈虛線框與十字虛線，紙上一支往右上彎的紫色箭頭，"
        "倉鼠從紙上緣探頭。",
        "紙沿用規格、繞中心轉 4°；虛線（深青綠 1 px）放最底層；四個 L 角用深藍 3.8 墊底、青綠 2.2 在上；倉鼠頭 13×11.6 放紙上緣。",
        tempo="normal")
dash = {"fill": "none", "stroke": TEAL_DARK, "stroke_width": 1.0, "stroke_dasharray": "2 1.6", "stroke_opacity": 0.8}
s.add("guide_v", "path", "back", d="M24 2V46", anim="draw", **dash)
s.add("guide_h", "path", "back", d="M6 28.5H42", anim="draw", **dash)
s.add("guide_box", "path", "back", d="M10.5 17.5H37.5V40.5H10.5Z", anim="draw", **dash)
corners = ["M8 20V17Q8 15 10 15H13", "M35 15H38Q40 15 40 17V20", "M8 37V40Q8 42 10 42H13", "M35 42H38Q40 42 40 40V37"]
for i, d in enumerate(corners):
    s.add(f"corner{i}_ink", "path", "back", d=d, fill="none", stroke=INK, stroke_width=3.8, stroke_linecap="round",
          stroke_linejoin="round", anim="draw")
for i, d in enumerate(corners):
    s.add(f"corner{i}", "path", "back", d=d, fill="none", stroke=TEAL, stroke_width=2.2, stroke_linecap="round",
          stroke_linejoin="round", anim="draw")
tilt = "rotate(4 24 29)"
s.add("sheet", "path", "object", d=page_d(14.25, 16.25, 33.75, 41.75, 2.5, 6), fill=PAPER, stroke=INK, stroke_width=2.5,
      stroke_linejoin="round", transform=tilt, anim="fill")
s.add("flap", "path", "object", d=flap_d(33.75, 16.25, 6, 1.5), fill="#DCDAEC", stroke=INK, stroke_width=1.5,
      stroke_linejoin="round", transform=tilt, anim="fill")
hamster48(s, "hm", 23.6, 11.6, 6.6, 5.8, k=0.68, eye_y=10.2, parts=("blocks",))
s.commit()
