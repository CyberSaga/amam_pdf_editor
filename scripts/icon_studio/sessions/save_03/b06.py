"""Batch 6 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

import math
from studio import Studio
from geo import body_outline_d, rrect_d, smooth_d, f

s = Studio.open()
s.begin(3, "鋪大色塊：平塗固有色",
        "線稿與參考吻合。舊的頭部正圓、耳朵粗圓已被新輪廓取代，留著會干擾判斷。",
        "擦掉過時構造線，草稿層降低不透明度；在草稿下方平塗各大塊的固有色：卡片白、本體紫、擋板淺灰、槽孔藍灰、標籤白、倉鼠杏色與白色口鼻區；眼睛先放最深色當明度基準。",
        tempo="normal")
for eid in ("sk_head", "sk_ear_l", "sk_ear_r", "sk_eye_line"):
    s.rm(eid, note="擦掉過時的構造線")
s.layer("sketch", opacity=0.72, note="草稿層調淡")
P = s.params["P"]
s.add("card_base", "path", "card", d=rrect_d(*P["card"]), fill="#FBFBFE", anim="fill")
x0, y0, x1, y1, r, ch, rch = P["body"]
s.add("body_base", "path", "body", d=body_outline_d(x0, y0, x1, y1, r, ch, rch), fill="#9285D5", anim="fill")
sx0, sy0, sx1, sy1, sr = P["shutter"]
sh_d = (f"M{sx0} {sy0}L{sx0} {sy1 - sr}A{sr} {sr} 0 0 0 {sx0 + sr} {sy1}"
        f"L{sx1 - sr} {sy1}A{sr} {sr} 0 0 0 {sx1} {sy1 - sr}L{sx1} {sy0}Z")
s.params["shutter_d"] = sh_d
s.add("sh_base", "path", "shutter", d=sh_d, fill="#F3F3F7", anim="fill")
s.add("slot_base", "path", "shutter", d=rrect_d(*P["slot"]), fill="#4E537B", anim="fill")
s.add("lb_base", "path", "label", d=rrect_d(*P["label"]), fill="#FBFBFD", anim="fill")
# hamster flats
cx, cy, rx, ry = s.params["head"]
def ell(a):
    return (cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
for i, (ex, ey, er) in enumerate(s.params["ears"]):
    s.add(f"hm_ear{i}_base", "circle", "hamster", cx=ex, cy=ey, r=er, fill="#F7CF9C", anim="fill")
head_pts = s.params["head_pts"]
head_d = smooth_d(head_pts)[:-0 or None] + "Z"
s.params["head_fill_d"] = head_d
s.add("hm_head_base", "path", "hamster", d=head_d, fill="#F9D3A0", anim="fill")
# white muzzle/cheek region: fur boundary on top, head ellipse on the sides, cut at y=355
fb = s.params["fur_boundary"]
a_left = 180 - math.degrees(math.asin((334 - cy) / ry)) if 334 > cy else 180 + math.degrees(math.asin((cy - 334) / ry))
a_bot_l = 180 - math.degrees(math.asin((355 - cy) / ry))
a_bot_r = math.degrees(math.asin((355 - cy) / ry))
a_right = 360 - math.degrees(math.asin((cy - 334) / ry))
left_side = [ell(a_bot_l + (a_left - a_bot_l) * i / 3) for i in range(4)]  # bottom-left up to boundary start
right_side = [ell(a_right + (360 + a_bot_r - a_right) * i / 3) for i in range(4)]  # boundary end down to bottom-right
fb2 = [left_side[-1]] + fb[1:-1] + [right_side[0]]
muzzle_d = smooth_d(fb2) + "L" + "L".join(f"{f(x)} {f(y)}" for x, y in right_side[1:]) + "L" + "L".join(f"{f(x)} {f(y)}" for x, y in left_side[:-1]) + "Z"
s.params["muzzle_pts"] = {"top": fb2, "right": right_side, "left": left_side}
s.add("hm_muzzle_base", "path", "hamster", d=muzzle_d, fill="#FFFFFF", anim="fill")
for i, (ex, ey, erx, ery) in enumerate(s.params["eyes"]):
    s.add(f"hm_eye{i}_base", "ellipse", "hamster", cx=ex, cy=ey, rx=erx, ry=ery, fill="#20263F", anim="fill")
s.commit(compare=True, zooms=[(176, 250, 160, 112)])
