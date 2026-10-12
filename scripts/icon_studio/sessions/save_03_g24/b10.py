"""Batch 10 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

INK = "#1E1D38"


def rects(*rs):
    return "".join(f"M{x} {y}h{w}v{h}h{-w}Z" for x, y, w, h in rs)


s = Studio.open()
s.begin(6, "24 格：逐像素對齊臉部",
        "放大 1× 的每一格檢查：0.7 px 的深藍框橫跨像素邊界，臉上大半格子變成深藍與杏色的混色，整張臉發灰；眼睛只剩各 1 格深色，反光點完全消失；耳朵變成兩團灰色。",
        "臉部改成逐格決定的形狀（風格元素不減）：第 11 列耳尖、第 12 列耳朵兩格粉紅＋頭頂深藍線、兩側 1 px 深藍框；第 13–15 列杏色，眼睛各 2×2 格、左上角 1 格白色反光；兩眼之間第 15 列是白色口鼻區的尖角；第 16–17 列白色口鼻，兩頰各 1 格腮紅，中間 2 格鼻子、下方 2 格嘴。",
        tempo="normal")
s.look((7, 11, 10, 7), "臉部混色發灰、眼睛反光消失")
for eid in ("ear0", "ear0_in", "ear1", "ear1_in", "head", "muzzle", "eye0", "eye0_hl", "eye1", "eye1_hl",
            "nose", "mouth", "blush0", "blush1"):
    s.rm(eid, note="改為逐格對齊" if eid == "ear0" else None)
s.add("face_peach", "path", "hamster", d=rects((8, 12, 8, 4)), fill="#F6C58E", anim="fill")
s.add("face_muzzle", "path", "hamster", d=rects((8, 16, 8, 2), (11, 15, 2, 1)), fill="#FFFFFF", anim="fill")
s.add("face_outline", "path", "hamster", d=rects((8, 11, 2, 1), (14, 11, 2, 1), (7, 12, 1, 6), (16, 12, 1, 6), (10, 12, 4, 1)),
      fill=INK, anim="fill")
s.add("ears_inner", "path", "hamster", d=rects((8, 12, 2, 1), (14, 12, 2, 1)), fill="#F2A3A0", anim="fill")
s.add("eyes", "path", "hamster", d=rects((9, 14, 2, 2), (13, 14, 2, 2)), fill=INK, anim="pop")
s.add("eyes_hl", "path", "hamster", d=rects((9, 14, 1, 1), (13, 14, 1, 1)), fill="#FFFFFF", anim="pop")
s.add("blush", "path", "hamster", d=rects((8, 16, 1, 1), (15, 16, 1, 1)), fill="#F6A3B0", anim="pop")
s.add("nose", "path", "hamster", d=rects((11, 16, 2, 1)), fill="#E35D6A", anim="pop")
s.add("mouth", "path", "hamster", d=rects((11, 17, 2, 1)), fill="#5A4250", anim="pop")
s.commit()
