"""Batch 10 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

from studio import Studio
from geo import rrect_pts, inner_band, poly_d

s = Studio.open()
s.begin(4, "檢查明暗：修正溢出的內陰影",
        "放大看槽孔：內陰影用 evenodd 兩個矩形相減，位移後的矩形超出了洞口，右下角在擋板上多出一條灰色假影子；標籤窗右、下緣同樣的問題。這是陰影與形體的連接錯誤。",
        "改用真正的幾何差集（洞口 − 位移後洞口），陰影只留在洞內的左上，反光只留在洞內的右下。",
        tempo="normal")
P = s.params["P"]
lx0, ly0, lx1, ly1, lr = P["slot"]
slot = rrect_pts(lx0, ly0, lx1, ly1, lr, seg=8)
s.look((265, 128, 40, 68), "槽孔陰影溢出到擋板上")
s.mod("slot_inshadow", note="陰影改為洞口內的差集", d=poly_d(inner_band(slot, 2.5, 3.5)), fill_rule="nonzero")
s.mod("slot_rimlight", note="反光只留在洞內右下", d=poly_d(inner_band(slot, -1.8, -2.4)), fill_rule="nonzero")
bx0, by0, bx1, by1, br = P["label"]
lab = rrect_pts(bx0, by0, bx1, by1, br, seg=8)
s.look((170, 238, 172, 126), "標籤窗內陰影同樣修正")
s.mod("lb_inshadow", d=poly_d(inner_band(lab, 3.5, 4.5)), fill_rule="nonzero")
s.mod("lb_inshadow2", d=poly_d(inner_band(lab, 7, 9)), fill_rule="nonzero")
s.commit(zooms=[(186, 104, 140, 112), (170, 236, 172, 130)])
