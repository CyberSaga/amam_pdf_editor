"""Batch 29 of the 03_儲存 large design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。大圖的耳朵是半徑 16 的圓，大半藏在頭後面，"
        "只在頭頂兩側露出一小片，粉紅內耳也只露出一角。",
        "和 16/24/48 格一樣把耳朵放大 1.6 倍：每隻耳朵整組（底色、內耳、血管、耳褶、外框、耳朵上的毛、左耳亮邊）"
        "套同一個縮放矩陣，圓心往外 4.2、往上 2；線寬除以 1.6，畫出來還是原本的粗細；外框改成整圈"
        "（藏在頭後面的那段被頭蓋住）；粉紅內耳、血管和耳褶一起往外上方移，落在露出來的那一塊。",
        tempo="normal")
s.look((180, 245, 152, 70), "耳朵太小")
G = 1.6
EARS = ((221.0, 283.0), (291.0, 283.0))


def side(eid: str) -> int:
    a = s.elements[eid]["attrs"]
    x = float(a["cx"]) if "cx" in a else float(a["d"][1:].replace("-", " ").split()[0])
    return 0 if x < 256 else 1


fur = [e for e in s.elements if e.startswith("fur_ear")]
for i, (ox, oy) in enumerate(EARS):
    sgn = -1 if i == 0 else 1
    nx, ny = ox + sgn * 4.2, oy - 2.0
    tx, ty = nx - G * ox, ny - G * oy
    # inner ear: from (inward 3.2, down 2.5) of the centre to (outward 0.8, up 2.3) after scaling
    ix, iy = tx + sgn * 5.9, ty - 6.3
    ear = [f"hm_ear{i}_base", f"ink_ear{i}"] + [e for e in fur if side(e) == i]
    ear += ["hm_ear0_lit"] if i == 0 else []
    inner = [f"hm_ear{i}_inner"] + [f"hm_ear{i}_vein{j}" for j in range(3)] + [f"ink_earfold{i}"]
    for n, eid in enumerate(ear + inner):
        a = s.elements[eid]["attrs"]
        dx, dy = (ix, iy) if eid in inner else (tx, ty)
        kw = {"transform": f"matrix({G:g} 0 0 {G:g} {dx:.3f} {dy:.3f})"}
        if "stroke-width" in a and a.get("stroke", "none") != "none":
            kw["stroke_width"] = round(float(a["stroke-width"]) / G, 3)
        s.mod(eid, note=("耳朵放大 1.6 倍" if n == 0 else None), **kw)
    r = 16.0
    s.mod(f"ink_ear{i}", note="外框改成整圈",
          d=f"M{ox - r:g} {oy:g}A{r:g} {r:g} 0 1 1 {ox + r:g} {oy:g}A{r:g} {r:g} 0 1 1 {ox - r:g} {oy:g}Z")
s.commit()
