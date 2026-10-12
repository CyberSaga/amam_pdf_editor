"""Batch 4 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

from studio import Studio
from geo import body_outline_d, rrect_d
from kit import pencil_curve

DARK = "#3D5390"
s = Studio.open()
s.begin(2, "確定大形：乾淨的外輪廓",
        "比例刻度和參考相符，頭形改寬之後整體氣質對了。現在還全是直線方框，看不出圓角和切角的轉折。",
        "用較深的鉛筆收出確定的輪廓：本體圓角 r18、切角兩端小圓角；擋板上緣併入本體上緣、下方兩角圓；槽孔與標籤窗圓角矩形；卡片置中於磁碟（左右各留 ~60）。",
        tempo="normal")
P = {"body": [128, 110, 384, 398, 18, 49, 6], "shutter": [192, 110, 320, 210, 8],
     "slot": [273, 135, 297, 188, 6], "label": [179, 245, 333, 355, 11],
     "card": [69, 26, 443, 482, 44]}
s.params["P"] = P
x0, y0, x1, y1, r, ch, rch = P["body"]
s.add("ct_body", "path", "sketch", d=body_outline_d(x0, y0, x1, y1, r, ch, rch), fill="none",
      stroke=DARK, stroke_width=1.7, stroke_opacity=0.62, stroke_linejoin="round", anim="draw")
sx0, sy0, sx1, sy1, sr = P["shutter"]
d = (f"M{sx0} {sy0}L{sx0} {sy1 - sr}A{sr} {sr} 0 0 0 {sx0 + sr} {sy1}"
     f"L{sx1 - sr} {sy1}A{sr} {sr} 0 0 0 {sx1} {sy1 - sr}L{sx1} {sy0}")
s.add("ct_shutter", "path", "sketch", d=d, fill="none", stroke=DARK, stroke_width=1.6,
      stroke_opacity=0.6, stroke_linejoin="round", anim="draw")
s.add("ct_slot", "path", "sketch", d=rrect_d(*P["slot"]), fill="none", stroke=DARK,
      stroke_width=1.5, stroke_opacity=0.6, anim="draw")
s.add("ct_label", "path", "sketch", d=rrect_d(*P["label"]), fill="none", stroke=DARK,
      stroke_width=1.6, stroke_opacity=0.6, anim="draw")
s.add("ct_card", "path", "sketch", d=rrect_d(*P["card"]), fill="none", stroke=DARK,
      stroke_width=1.4, stroke_opacity=0.42, anim="draw")
# head dome: wide top, cheeks flaring to almost the label width, cut at the label bottom
head = [(193, 355), (194, 338), (199, 318), (210, 299), (229, 284), (256, 277),
        (283, 284), (302, 299), (313, 318), (318, 338), (319, 355)]
s.params["head_pts"] = head
pencil_curve(s, "ct_head", head, w=1.7, op=0.62, color=DARK)
# ears: only the arcs that stay outside the head
s.add("ct_ear_l", "path", "sketch", d="M211 292A15 15 0 1 1 236 278", fill="none",
      stroke=DARK, stroke_width=1.6, stroke_opacity=0.6, stroke_linecap="round", anim="draw")
s.add("ct_ear_r", "path", "sketch", d="M276 278A15 15 0 1 1 301 292", fill="none",
      stroke=DARK, stroke_width=1.6, stroke_opacity=0.6, stroke_linecap="round", anim="draw")
s.layer("sketch", opacity=0.9)
s.commit(compare=True, zooms=[(170, 236, 172, 130)])
