"""Batch 1 of the 21_註解列表 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import f
from parts import BEAN24, INK, PURPLE_LIGHT, TEAL, YELLOW, pixmap
from studio import Studio

BROWN = "#96602A"
LINE_PURPLE = "#4A478F"


def rrect_d(x0: float, y0: float, x1: float, y1: float, r: float) -> str:
    """Bubble body without its tail (tails are pixel maps at 24, as in 18_新增註解)."""
    return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}H{f(x0 + r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")


def bubble(s, name: str, layer: str, box: tuple, color: str, tail: list[str], tx: int, ty: int) -> None:
    s.add(name, "path", layer, d=rrect_d(*box, 1), fill=color, stroke=INK, stroke_width=1, stroke_linejoin="round",
          anim="fill")
    pixmap(s, f"{name}_tail", tail, tx, ty, layer, legend={"Y": ("fill", color), "N": ("ink", INK)})


TAIL_L = ["NYYN", "NYN.", "NN.."]  # 18_新增註解's tail (vertical left edge) on a 1 px bottom edge
TAIL_R = ["NYYN", ".NYN", "..NN"]  # mirrored: vertical right edge
s = Studio.open()
s.begin(3, "24 格：從 48 格移植",
        "48 格版：黃框在上、青綠框在右後、淡紫框在左下最前，倉鼠從左邊探頭、兩眼夾在黃紫兩框之間。座標減半後三個框只剩 9–12 格寬，"
        "草稿試了 1.5 px 框：框線內側的半格混色把三個框疊在一起的地方糊成一片，1 px 框才分得開（小物件用 1 px）。",
        "倉鼠用 BEAN24 放 x 0–9，黃框外緣 x 9–21、y 1–12（框緣蓋住倉鼠右輪廓，右頰那欄隔開眼睛）；淡紫框 x 6–16、y 11–20，"
        "上緣和黃框下緣共用同一列框線；青綠框 x 14–23、y 10–18 在最後；三個尾巴都用新增註解的逐像素直角尾巴（黃、青綠鏡像）；"
        "字線 1 px：黃框三條（y 4/6/8）、紫框兩條（y 14/16）。",
        tempo="normal")
pixmap(s, "hm", BEAN24, 0, 4, "hamster")
bubble(s, "teal", "back", (14.5, 10.5, 22.5, 17.5), TEAL, TAIL_R, 18, 17)
bubble(s, "yellow", "object", (9.5, 1.5, 20.5, 11.5), YELLOW, TAIL_R, 16, 11)
s.add("text_y", "path", "object", d="M12 4.5H18M12 6.5H18M12 8.5H15", fill="none", stroke=BROWN, stroke_width=1,
      anim="draw")
bubble(s, "purple", "front", (6.5, 11.5, 15.5, 19.5), PURPLE_LIGHT, TAIL_L, 8, 19)
s.add("text_p", "path", "front", d="M8 14.5H14M8 16.5H12", fill="none", stroke=LINE_PURPLE, stroke_width=1,
      anim="draw")
s.commit()
