"""Batch 9 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
from studio import Studio
from geo import rrect_d, f

s = Studio.open()
s.begin(4, "明暗關係：擋板、槽孔、標籤窗與倉鼠的體積",
        "本體有了前後感，但擋板、標籤、倉鼠仍是平的；磁碟投影右側有一點階梯感，先記下，細化時再柔化。",
        "擋板：金屬由上亮到下暗，並在本體上投出右下方小陰影（它是貼在上面的一片）。槽孔是洞：左上內緣暗、右下內緣反光。標籤窗是凹進去的：上、左內緣落影。倉鼠頭用左上偏亮的放射漸層做出球體，白色口鼻區下緣偏冷灰，被標籤下緣遮住處壓暗。",
        tempo="normal")
P = s.params["P"]
# --- shutter metal gradient + its cast shadow on the body
gs = s.gradient("g_shutter", "linear", [(0, "#FBFBFD", 1), (0.55, "#EEEEF4", 1), (1, "#D9D9E4", 1)],
                gradientUnits="userSpaceOnUse", x1=0, y1=110, x2=0, y2=210)
s.mod("sh_base", note="擋板改為上亮下暗的金屬漸層", fill=gs)
sx0, sy0, sx1, sy1, sr = P["shutter"]
zb = s.elements["body_base"]["z"]
for i, (dx, dy, op) in enumerate([(2.5, 3.5, 0.22), (5, 7, 0.1)]):
    d = (f"M{sx0 + dx} {sy0}L{sx0 + dx} {sy1 - sr + dy}A{sr} {sr} 0 0 0 {sx0 + sr + dx} {sy1 + dy}"
         f"L{sx1 - sr + dx} {sy1 + dy}A{sr} {sr} 0 0 0 {sx1 + dx} {sy1 - sr + dy}L{sx1 + dx} {sy0}Z")
    s.add(f"sh_cast{i}", "path", "body", z=zb + 0.5 + i * 0.01, d=d, fill="#3E3383", fill_opacity=op, anim="glaze")
# --- slot: dark hole with inner shadow and lit lower-right rim
lx0, ly0, lx1, ly1, lr = P["slot"]
gsl = s.gradient("g_slot", "linear", [(0, "#3C4068", 1), (1, "#5A6090", 1)],
                 gradientUnits="userSpaceOnUse", x1=lx0, y1=ly0, x2=lx1, y2=ly1)
s.mod("slot_base", fill=gsl)
band = rrect_d(lx0, ly0, lx1, ly1, lr) + rrect_d(lx0 + 2.5, ly0 + 3.5, lx1 + 2.5, ly1 + 3.5, lr)
s.add("slot_inshadow", "path", "shutter", d=band, fill="#1B1D36", fill_opacity=0.45, fill_rule="evenodd", anim="glaze")
rim = rrect_d(lx0, ly0, lx1, ly1, lr) + rrect_d(lx0 - 1.8, ly0 - 2.4, lx1 - 1.8, ly1 - 2.4, lr)
s.add("slot_rimlight", "path", "shutter", d=rim, fill="#9EA6D6", fill_opacity=0.35, fill_rule="evenodd", anim="glaze")
# --- label window recess: shadow along the inner top + left edges
bx0, by0, bx1, by1, br = P["label"]
gl = s.gradient("g_label", "linear", [(0, "#F3F2F8", 1), (0.4, "#FCFCFE", 1), (1, "#FFFFFF", 1)],
                gradientUnits="userSpaceOnUse", x1=0, y1=245, x2=0, y2=355)
s.mod("lb_base", fill=gl)
band = rrect_d(bx0, by0, bx1, by1, br) + rrect_d(bx0 + 3.5, by0 + 4.5, bx1 + 3.5, by1 + 4.5, br)
s.add("lb_inshadow", "path", "label", d=band, fill="#5E57A0", fill_opacity=0.16, fill_rule="evenodd", anim="glaze")
band2 = rrect_d(bx0, by0, bx1, by1, br) + rrect_d(bx0 + 7, by0 + 9, bx1 + 7, by1 + 9, br)
s.add("lb_inshadow2", "path", "label", d=band2, fill="#5E57A0", fill_opacity=0.06, fill_rule="evenodd", anim="glaze")
# --- hamster volume
cx, cy, rx, ry = s.params["head"]
gh = s.gradient("g_head", "radial", [(0, "#FCE2B9", 1), (0.55, "#F8D09B", 1), (1, "#EDB37A", 1)],
                gradientUnits="userSpaceOnUse", cx=238, cy=296, r=82, fx=232, fy=290)
s.mod("hm_head_base", note="頭部改為左上受光的球體漸層", fill=gh)
for i, (ex, ey, er) in enumerate(s.params["ears"]):
    ge = s.gradient(f"g_ear{i}", "radial", [(0, "#FBDDB2", 1), (1, "#EDB57E", 1)],
                    gradientUnits="userSpaceOnUse", cx=ex - 5, cy=ey - 6, r=er * 1.35)
    s.mod(f"hm_ear{i}_base", fill=ge)
gm = s.gradient("g_muzzle", "radial", [(0, "#FFFFFF", 1), (0.7, "#FBF8F6", 1), (1, "#E9E2E0", 1)],
                gradientUnits="userSpaceOnUse", cx=252, cy=334, r=64)
s.mod("hm_muzzle_base", fill=gm)
# ambient occlusion where the head disappears behind the label's bottom frame
y_top = 343
def half(y):
    return rx * math.sqrt(max(0.0, 1 - ((y - cy) / ry) ** 2))
pts = [(cx - half(y_top), y_top), (cx + half(y_top), y_top), (cx + half(355), 355), (cx - half(355), 355)]
gao = s.gradient("g_ao_bottom", "linear", [(0, "#8E7A8C", 0), (1, "#8E7A8C", 0.28)],
                 gradientUnits="userSpaceOnUse", x1=0, y1=y_top, x2=0, y2=355)
s.add("hm_ao_bottom", "path", "hamster",
      d=f"M{f(pts[0][0])} {f(pts[0][1])}L{f(pts[1][0])} {f(pts[1][1])}L{f(pts[2][0])} {f(pts[2][1])}L{f(pts[3][0])} {f(pts[3][1])}Z",
      fill=gao, anim="glaze")
s.commit(zooms=[(176, 240, 160, 120), (186, 104, 140, 112)])
