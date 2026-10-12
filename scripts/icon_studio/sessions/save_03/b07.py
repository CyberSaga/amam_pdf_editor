"""Batch 7 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

from studio import Studio
from geo import smooth_d, rrect_d, f

s = Studio.open()
s.begin(3, "鋪色塊：次要色塊與口鼻區修形",
        "大色塊整體色相和參考一致（本體中間調 #9285D5 與參考取樣 #9385D6 幾乎相同）。白色口鼻區在兩眼之間的尖角太高，頂到眼睛中線，參考的尖角在眼睛下半部；耳朵還沒有內耳色，卡片沒有邊框色。",
        "把口鼻區尖角壓低到 y≈323、兩側在眼下略微上弧；加內耳粉、鼻頭、腮紅底色與卡片淡紫邊框。",
        tempo="normal")
s.look((226, 312, 60, 30), "口鼻區尖角太高")
m = s.params["muzzle_pts"]
top = m["top"]
new_top = [top[0], (212, 330.5), (226, 330.5), (239, 331), (248.5, 327.5), (256, 323), (263.5, 327.5), (273, 331), (286, 330.5), (300, 330.5), top[-1]]
right, left = m["right"], m["left"]
muzzle_d = smooth_d(new_top) + "L" + "L".join(f"{f(x)} {f(y)}" for x, y in right[1:]) + "L" + "L".join(f"{f(x)} {f(y)}" for x, y in left[:-1]) + "Z"
s.params["muzzle_pts"]["top"] = new_top
s.mod("hm_muzzle_base", note="口鼻區尖角 318 → 323，兩側眼下微弧", d=muzzle_d)
s.mod("sk_fur", d=smooth_d(new_top))
# inner ears: offset toward the head center (ear opening faces inward/down)
inner = []
for i, (ex, ey, er) in enumerate(s.params["ears"]):
    dx = 3.2 if i == 0 else -3.2
    ix, iy, irx, iry = ex + dx, ey + 2.5, er * 0.62, er * 0.66
    inner.append((ix, iy, irx, iry))
    s.add(f"hm_ear{i}_inner", "ellipse", "hamster", z=s.elements[f"hm_ear{i}_base"]["z"] + 0.1,
          cx=ix, cy=iy, rx=irx, ry=iry, fill="#F3B2AA", anim="fill")
s.params["ear_inner"] = inner
# nose
s.add("hm_nose_base", "path", "hamster", d="M251.4 331.2Q256 329.6 260.6 331.2Q259.4 334.6 256 336.6Q252.6 334.6 251.4 331.2Z",
      fill="#E8707C", anim="fill")
# blush base under the eyes, on the peach/white border
for i, (bx, by) in enumerate([(224, 333.5), (288, 333.5)]):
    s.add(f"hm_blush{i}_base", "ellipse", "hamster", cx=bx, cy=by, rx=10, ry=5.6, fill="#F7A7A6", fill_opacity=0.55, anim="fill")
# card border band (lavender rim)
P = s.params["P"]
s.add("card_rim", "path", "card", d=rrect_d(*P["card"]), fill="none", stroke="#E1DEEF", stroke_width=3.2, anim="draw")
s.commit(zooms=[(176, 250, 160, 112)])
