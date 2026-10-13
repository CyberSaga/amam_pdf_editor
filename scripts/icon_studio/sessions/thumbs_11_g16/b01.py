"""Batch 1 of the 11_縮圖 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, PAPER, PEEK16, PURPLE_DARK, PURPLE_LIGHT, TEAL, TEAL_DARK, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：17 格的框、四塊 5×5 方塊（深色框、淺色心、白光澤）、框上緣偏右的探頭臉。16 格的框只剩 11 格、框內 9×9，"
        "方塊只能 3×3；草稿試了五種：純淺色、純中紫、深色環＋白心（像四個小窗）、光澤點（缺角）、淺色 2×2＋右下深色 L，"
        "最後一種保留了 24 格「淺色心＋深色框」的感覺、在 1× 也最像方塊。手掌壓在 1 px 框上會把框線打斷，16 格不畫。",
        "框外緣 x 2–13、y 5–16（1 px）；方塊 3×3、間隔 1 格；臉用 PEEK16（耳蓋、粉耳、2×2 反光眼睛、白口鼻與鼻子、腮紅）"
        "放在第 0–4 列、比框中線偏右半格。",
        tempo="normal")
s.add("frame", "path", "object", d=rrect_d(2.5, 5.5, 12.5, 15.5, 1.0), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
TILES = [
    "LLD.TTK",
    "LLD.TTK",
    "DDD.KKK",
    ".......",
    "LLD.TTK",
    "LLD.TTK",
    "DDD.KKK",
]
pixmap(s, "tiles", TILES, 4, 7, "object", legend={"L": ("purple", PURPLE_LIGHT), "T": ("teal", TEAL),
                                                   "D": ("purple_ink", PURPLE_DARK), "K": ("teal_ink", TEAL_DARK)})
pixmap(s, "hm", PEEK16, 5, 0, "hamster")
s.commit()
