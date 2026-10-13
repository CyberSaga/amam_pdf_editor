"""Batch 2 of the 18_新增註解 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import f
from parts import INK, YELLOW, pixmap
from studio import Studio


def rrect_d(x0: float, y0: float, x1: float, y1: float, r: float) -> str:
    """The bubble body without its tail (the tail becomes a pixel map at 24)."""
    return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}H{f(x0 + r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")


s = Studio.open()
s.begin(6, "24 格：右眼離框一格、尾巴改逐像素",
        "放大看：倉鼠右眼直接貼著對話框的深藍框，眼睛和框線黏成一塊；向量尾巴在 24 格變成一團糊掉的深藍，看不出是對話框的尾巴；"
        "字線偏下，上面空兩列、下面只剩一列。草稿試了向量尾巴和兩種逐像素尾巴，2 格開口的直角三角在 1× 最清楚。",
        "對話框左緣右移一格（外緣 x 9–21），讓右頰那一欄桃色隔開眼睛和框線，框緣只蓋住倉鼠的右輪廓；尾巴改成逐像素：框底開 2 格口、"
        "左邊垂直 3 列、斜邊一格一格收到尖端；字線跟著右移並上移一列（y 6/9/12）。",
        tempo="normal")
s.look((5, 8, 6, 4), "右眼貼框")
s.look((10, 15, 6, 5), "尾巴糊掉")
s.mod("bubble", note="左緣右移一格、尾巴拿掉改逐像素", d=rrect_d(9.75, 3.75, 20.25, 16.25, 1.5))
TAIL = [
    ".YY.",
    "NYYN",
    "NYN.",
    "NN..",
]
pixmap(s, "tail", TAIL, 11, 15, "object", legend={"Y": ("fill", YELLOW), "N": ("ink", INK)})
s.mod("text", note="字線右移、上移一列", d="M12 6.5H18M12 9.5H18M12 12.5H15")
s.commit()
