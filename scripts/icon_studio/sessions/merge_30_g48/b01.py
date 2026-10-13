"""Batch 1 of the 30_合併PDF 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, LINE, PAPER, PURPLE_LIGHT, RED, flap_d, hamster48, page_d, pdf_mark_d
from studio import Studio

s = Studio.open()
s.begin(3, "48 格：兩張 PDF、倉鼠、紙疊",
        "參考圖：上方左右兩張帶紅色 PDF 標誌的折角紙（各約 14×18），倉鼠在中間舉起雙手，兩支紫色彎箭頭從兩張紙往下匯到底部的一疊紙。",
        "上方兩張紙較小，外框用 2 px、折角 4.5；紙疊三層（白紙＋兩層淡紫），2 px 框、每層錯開 3 格；倉鼠頭 13.6×11.6 放正中，先鋪色塊。",
        tempo="normal")
for i, x0 in enumerate((7.0, 28.0)):
    s.add(f"page{i}", "path", "object", d=page_d(x0, 4.0, x0 + 12, 20.0, 2.0, 4.5), fill=PAPER, stroke=INK,
          stroke_width=2.0, stroke_linejoin="round", anim="fill")
    s.add(f"page{i}_flap", "path", "object", d=flap_d(x0 + 12, 4.0, 4.5, 1.0), fill="#DCDAEC", stroke=INK,
          stroke_width=1.25, stroke_linejoin="round", anim="fill")
    s.add(f"page{i}_mark", "path", "object_fx", d=pdf_mark_d(x0 + 1.8, 8.4, 7.6, 8.6), fill="none", stroke=RED,
          stroke_width=1.4, stroke_linejoin="round", anim="draw")
for i, (y0, fill) in enumerate(((40, PURPLE_LIGHT), (37, "#DAD5F6"), (33, PAPER))):
    s.add(f"stack{i}", "path", "badge", d=f"M15.5 {y0 + 1}H32.5A1.5 1.5 0 0 1 34 {y0 + 2.5}V{y0 + 4.5}A1.5 1.5 0 0 1 32.5 {y0 + 6}H15.5A1.5 1.5 0 0 1 14 {y0 + 4.5}V{y0 + 2.5}A1.5 1.5 0 0 1 15.5 {y0 + 1}Z",
          fill=fill, stroke=INK, stroke_width=2.0, stroke_linejoin="round", anim="fill")
s.add("stack_line", "path", "badge", d="M19 36.5H29", fill="none", stroke=LINE, stroke_width=1.4, stroke_linecap="round", anim="draw")
hamster48(s, "hm", 24, 24.6, 6.8, 5.8, k=0.7, parts=("blocks",))
s.commit()
