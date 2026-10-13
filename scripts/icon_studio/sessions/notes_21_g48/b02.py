"""Batch 2 of the 21_註解列表 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import f
from studio import Studio


def bubble_d(x0: float, y0: float, x1: float, y1: float, r: float, ta: float, tb: float, ty: float) -> str:
    """Speech bubble outline (same construction as 18_新增註解): rounded rect with a tail under the bottom edge."""
    if tb > ta:
        tail = f"H{f(tb)}L{f(ta)} {f(ty)}V{f(y1)}"
    else:
        tail = f"H{f(ta)}V{f(ty)}L{f(tb)} {f(y1)}"
    return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}{tail}H{f(x0 + r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")


s = Studio.open()
s.begin(2, "48 格：調整三個框的比例",
        "疊圖：三個框的位置都和參考吻合；但黃框尾巴的尖端剛好戳在紫框右上角，兩條深藍框線黏成一團；紫框內高只有 9 格，"
        "放兩條字線時上下留白不平均。",
        "黃框下緣上收 1 格（y 3–24），尾巴右移到垂直邊 x 33.75，和紫框角之間留出 1.5 格；紫框上移 1 格、加高 1 格（y 26–41），"
        "右緣收到 x 30；黃紫兩框之間仍留 2 格縫，讓倉鼠和青綠框透出來。",
        tempo="normal")
s.look((26, 22, 8, 8), "黃框尾巴戳到紫框角")
s.mod("bubble_yellow", note="下緣上收、尾巴右移", d=bubble_d(14.25, 4.25, 36.75, 22.75, 2.5, 33.75, 27.75, 27.25))
s.mod("bubble_purple", note="上移加高、右緣內收", d=bubble_d(11.25, 27.25, 28.75, 39.75, 2.5, 15.25, 21.25, 44.25))
s.commit(compare=True)
