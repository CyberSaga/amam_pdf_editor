"""Batch 5 of the 03_儲存 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import body_outline_d, rrect_d
from studio import Studio

INK = "#1E1D38"


def rects(*rs):
    return "".join(f"M{x} {y}h{w}v{h}h{-w}Z" for x, y, w, h in rs)


s = Studio.open()
s.begin(2, "使用者回饋：16 格也要 48 版的風格",
        "使用者回饋：16 px 的精細度不足以呈現 48 px 版的風格。把 48 版直接縮到 16 px 是一團灰；我的 16 格版標籤窗內只有 6×4 格，放不下 48 版的元素（框線耳朵、內耳粉、兩色臉、反光眼睛、腮紅、鼻子）。",
        "重排版面：本體放寬成 14×14（16 px 軟碟常用的方形），標籤窗內白變成 8×5 格；擋板 8×4、槽孔移到第 9 欄。臉部逐格畫：耳尖深藍、2 格粉紅內耳、頭頂 2 格深藍線、2×2 反光眼睛、眼間白色尖角、白色口鼻區帶腮紅與鼻子。外側不加框線（由窗框代替）。",
        tempo="normal")
for eid in ("ear0", "ear1", "head", "eye0", "eye1"):
    s.rm(eid, note="擦掉舊版倉鼠" if eid == "ear0" else None)
s.look((1, 1, 14, 14), "版面：臉只有 6×4 格")
s.mod("floppy", note="本體 12×14 → 14×14", d=body_outline_d(1.5, 1.5, 14.5, 14.5, 1.0, 2.6, 0.4))
s.mod("shutter_plate", note="擋板 4–12 × 1–5", d=rrect_d(4.5, 1.5, 11.5, 4.5, 0.5))
s.mod("slot", note="槽孔移到第 9 欄", x=9, y=2, width=1, height=2)
s.mod("label_paper", note="標籤窗 3–13 × 6–13，內白 8×5", d=rrect_d(3.5, 6.5, 12.5, 12.5, 0.6))
s.add("face_peach", "path", "hamster", d=rects((4, 9, 8, 2), (6, 8, 4, 1)), fill="#F6C58E", anim="fill")
s.add("face_muzzle", "path", "hamster", d=rects((4, 11, 8, 1), (7, 10, 2, 1)), fill="#FFFFFF", anim="fill")
s.add("face_outline", "path", "hamster", d=rects((5, 7, 2, 1), (9, 7, 2, 1), (7, 8, 2, 1)), fill=INK, anim="fill")
s.add("ears_inner", "path", "hamster", d=rects((5, 8, 2, 1), (9, 8, 2, 1)), fill="#F2A3A0", anim="fill")
s.add("eyes", "path", "hamster", d=rects((5, 9, 2, 2), (9, 9, 2, 2)), fill=INK, anim="pop")
s.add("eyes_hl", "path", "hamster", d=rects((5, 9, 1, 1), (9, 9, 1, 1)), fill="#FFFFFF", anim="pop")
s.add("blush", "path", "hamster", d=rects((4, 11, 1, 1), (11, 11, 1, 1)), fill="#F6A3B0", anim="pop")
s.add("nose", "path", "hamster", d=rects((7, 11, 2, 1)), fill="#EC7684", anim="pop")
s.add("label_frame", "path", "ink", d=rrect_d(3.5, 6.5, 12.5, 12.5, 0.6), fill="none", stroke=INK,
      stroke_width=1, stroke_linejoin="round", anim="draw")
s.mod("label_paper", stroke="none")
s.commit()
