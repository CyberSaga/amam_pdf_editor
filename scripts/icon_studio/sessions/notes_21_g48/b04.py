"""Batch 4 of the 21_註解列表 48 px grid design. Run via run_session.py."""
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
s.begin(6, "48 格：檢查整體",
        "1×（48 px）看：三個框疊得清楚、倉鼠讀得出來；但黃紫兩框之間的縫裡，青綠框的左框線剛好露成一根深藍短柱，把上下兩個框"
        "連成一塊；倉鼠右邊兩根鬍鬚也伸進縫裡、碰到黃框的框線。",
        "青綠框往左延伸到 x 12，左框線藏到倉鼠頭後面，縫裡只透出青綠色；拿掉右邊兩根鬍鬚（左邊兩根保留）。",
        tempo="normal")
s.look((19, 22, 6, 6), "青綠框線露成短柱")
s.mod("bubble_teal", note="左緣延伸到倉鼠頭後面", d=bubble_d(13.25, 20.25, 43.75, 33.75, 2.5, 39.25, 33.25, 38.25))
s.look((12, 21, 6, 5), "右鬍鬚戳到黃框")
s.rm("hm_whisker_r0", note="右鬍鬚拿掉")
s.rm("hm_whisker_r1", note="右鬍鬚拿掉")
s.commit(compare=True)
