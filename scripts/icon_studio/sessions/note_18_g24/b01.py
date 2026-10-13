"""Batch 1 of the 18_新增註解 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import f
from parts import BEAN24, INK, YELLOW, badge_plus, pixmap
from studio import Studio

BROWN = "#96602A"


def bubble_d(x0: float, y0: float, x1: float, y1: float, r: float, ta: float, tb: float, ty: float) -> str:
    """Speech bubble outline (same construction as the 48 design): rounded rect + tail under the bottom edge."""
    if tb > ta:
        tail = f"H{f(tb)}L{f(ta)} {f(ty)}V{f(y1)}"
    else:
        tail = f"H{f(ta)}V{f(ty)}L{f(tb)} {f(y1)}"
    return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}{tail}H{f(x0 + r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")


s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：2.5 px 深藍框的黃色對話框、左下尾巴、三條咖啡色字線；倉鼠從框左緣後面探頭、往外歪；右下紫色加號章。"
        "座標減半後倉鼠頭只剩 6.8 格寬，放不下 2×2 的眼睛和反光。",
        "對話框外緣 x 8–21、y 3–17，1.5 px 框、圓角 1.5，尾巴左邊 x 10.75 垂直落到 y 18.75、斜邊回到 x 13.75；字線 1 px 三條（y 7/10/13）；"
        "倉鼠用 BEAN24（10×11）放 x 0–9，右側兩欄（右頰與外框）藏進框後，框緣代替倉鼠右輪廓；加號章外半徑 4、中心 (19.5, 17.5)。",
        tempo="normal")
pixmap(s, "hm", BEAN24, 0, 6, "hamster")
s.add("bubble", "path", "object", d=bubble_d(8.75, 3.75, 20.25, 16.25, 1.5, 10.75, 13.75, 18.75), fill=YELLOW,
      stroke=INK, stroke_width=1.5, stroke_linejoin="round", anim="fill")
s.add("text", "path", "object_fx", d="M11 7.5H18M11 10.5H18M11 13.5H15", fill="none", stroke=BROWN, stroke_width=1,
      anim="draw")
badge_plus(s, "badge", 24, 19.5, 17.5)
s.commit()
