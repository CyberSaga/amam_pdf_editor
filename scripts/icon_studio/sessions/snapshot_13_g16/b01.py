"""Batch 1 of the 13_快照 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, PEEK16, PURPLE_DARK, TEAL, pix_d, pixmap
from studio import Studio

LENS = "#3B3D6B"
BAND = "#DCDAEC"
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：1 px 深紫取景框角、直邊凸起的相機（按鈕、下半淡紫）、7×7 鏡頭、凸起後的探頭臉。16 格排列：臉 5 列、機身至少 9 列"
        "（鏡頭上下各留 1 格白），最下一列給框角，凸起和按鈕放不下——凸起由倉鼠的頭代替，按鈕試了 1 格，只像一顆雜點。"
        "鏡頭試了白環版（像靶心）和深藍鏡片版，後者在 1× 才像鏡頭。",
        "機身外緣 x 2–13、y 5–14（1 px），第 9–12 列淡紫；鏡頭 5×5：深藍環、3×3 深藍鏡片、左上 1 格青綠反光；框角 1 px 深紫、"
        "臂長 3，和機身之間各隔 1 格；臉用 PEEK16 放在第 0–4 列、和機身同一條中線。",
        tempo="normal")
L = ["DDD", "D..", "D.."]
corners = [(L, 0, 2), ([r[::-1] for r in L], 12, 2), (L[::-1], 0, 13), ([r[::-1] for r in L[::-1]], 12, 13)]
s.add("brackets", "path", "back", d="".join(pix_d(rows, "D", x, y) for rows, x, y in corners), fill=PURPLE_DARK,
      anim="draw")
pixmap(s, "hm", PEEK16, 4, 0, "hamster")
s.add("cam", "path", "object", d=rrect_d(2.5, 5.5, 12.5, 13.5, 1.0), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("band", "path", "object", d="M3 9H12V13H3Z", fill=BAND, anim="fill")
pixmap(s, "lens", [".NNN.", "NGLLN", "NLLLN", "NLLLN", ".NNN."], 5, 7, "object_fx",
       legend={"L": ("glass", LENS), "G": ("glint", TEAL), "N": ("ink", INK)})
s.commit()
