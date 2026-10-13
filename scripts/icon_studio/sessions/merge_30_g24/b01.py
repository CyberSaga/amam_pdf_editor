"""Batch 1 of the 30_合併PDF 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK24, PURPLE_DARK, PURPLE_LIGHT, RED, arc_arrow, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：兩張 PDF 紙、中間舉手的倉鼠、兩支紫色匯流箭頭、底部紙疊。",
        "上方兩張紙 1 px 框（外緣 x 2/10、14/22，y 1/11），紅色 PDF 標誌改成逐像素 3×4；倉鼠用探頭臉放中間；"
        "箭頭 1.5 px 深紫不包邊；紙疊兩層（白＋淡紫）1 px 框。",
        tempo="normal")
for i, x0 in enumerate((2.5, 14.5)):
    s.add(f"page{i}", "path", "object", d=page_d(x0, 1.5, x0 + 7, 10.5, 1.0, 2.5), fill=PAPER, stroke=INK, stroke_width=1,
          stroke_linejoin="round", anim="fill")
    s.add(f"page{i}_flap", "path", "object", d=flap_d(x0 + 7, 1.5, 2.5, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
          stroke_linejoin="round", anim="fill")
    pixmap(s, f"page{i}_pdf", [".R.", ".R.", "R.R", "RRR"], int(x0) + 2, 5, "object_fx", legend={"R": ("mark", RED)})
s.add("stack0", "path", "badge", d="M7.5 19.5H16.5V22.5H7.5Z", fill=PURPLE_LIGHT, stroke=INK, stroke_width=1, anim="fill")
s.add("stack1", "path", "badge", d="M7.5 16.5H16.5V19.5H7.5Z", fill=PAPER, stroke=INK, stroke_width=1, anim="fill")
pixmap(s, "hm", PEEK24, 8, 9, "hamster")
arc_arrow(s, "arrow_r", 14, 11.5, 4, 0, 70, "front", width=1.5, head_w=1.8, head_len=2.2, color=PURPLE_DARK)
arc_arrow(s, "arrow_l", 14, 11.5, 4, 0, 70, "front", width=1.5, head_w=1.8, head_len=2.2, color=PURPLE_DARK,
          transform="matrix(-1 0 0 1 24 0)")
s.commit()
