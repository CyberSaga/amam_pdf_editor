"""Batch 1 of the 18_新增註解 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import f
from parts import FACE16, INK, YELLOW, badge_plus, pixmap
from studio import Studio

BROWN = "#96602A"


def rrect_d(x0: float, y0: float, x1: float, y1: float, r: float) -> str:
    """The bubble body without its tail (the tail is a pixel map)."""
    return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}H{f(x0 + r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")


s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：倉鼠頭身一團從左邊探出、框緣代替牠的右輪廓；對話框 1.5 px 框、逐像素直角尾巴、三條 1 px 字線；右下加號章。"
        "16 格裡加號章（直徑 7）一定會壓到框底，草稿試了 8 種排法：尾巴內縮時會和章的深藍環黏成一團。",
        "倉鼠臉用 16 格版（7×8，2×2 眼睛帶反光、白口鼻、鼻、腮紅）放 x 0–6，右頰那一欄隔開眼睛和框；對話框外緣 x 7–15、y 1–10、"
        "1 px 框；尾巴放在框的左下角（左緣直接往下延伸 2 列、2 格開口），避開加號章；字線 y 3/5/7；加號章中心 (12.5, 12.5)。",
        tempo="normal")
pixmap(s, "hm", FACE16, 0, 5, "hamster")
s.add("bubble", "path", "object", d=rrect_d(7.5, 1.5, 14.5, 9.5, 1), fill=YELLOW, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
TAIL = [
    "NYYN",
    "NYN.",
    "NN..",
]
pixmap(s, "tail", TAIL, 7, 9, "object", legend={"Y": ("fill", YELLOW), "N": ("ink", INK)})
s.add("text", "path", "object_fx", d="M9 3.5H13M9 5.5H13M9 7.5H11", fill="none", stroke=BROWN, stroke_width=1,
      anim="draw")
badge_plus(s, "badge", 16, 12.5, 12.5)
s.commit()
