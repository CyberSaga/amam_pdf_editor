"""Batch 27 of the 03_儲存 (save) icon session. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "檢查整體：退後看全圖與小尺寸",
        "隱藏草稿後退一步看整體，並縮到 16/24/32/48/64/96 px 和參考圖並排：剪影、比例、色相都對了；但擋板的髮絲紋在 48–96 px 時把擋板染成灰色，失去參考圖那塊「白色金屬片」的清楚對比；倉鼠的杏色偏淡，在小尺寸時和白紙背景的分離度不如參考圖。",
        "髮絲紋整體不透明度降到約 55%，擋板漸層的下端提亮；頭部漸層的三個色標都加一點飽和與深度，拉開倉鼠和紙面的明度差。",
        tempo="fast")
s.thumbs("縮小到工具列尺寸檢查辨識度")
s.compare("和參考圖並排比對")
s.look((190, 108, 132, 104), "擋板髮絲紋太重 → 擋板發灰")
for eid in sorted(e for e in s.elements if e.startswith("shtx_")):
    a = s.elements[eid]["attrs"]
    s.mod(eid, stroke_opacity=round(float(a["stroke-opacity"]) * 0.55, 3))
s.gradient("g_shutter", "linear", [(0, "#FCFCFE", 1), (0.55, "#F1F1F6", 1), (1, "#E2E2EB", 1)],
           note="擋板下端提亮", gradientUnits="userSpaceOnUse", x1=0, y1=110, x2=0, y2=210)
s.look((196, 270, 120, 86), "倉鼠杏色偏淡")
s.gradient("g_head", "radial", [(0, "#FCDFB2", 1), (0.55, "#F7C98F", 1), (1, "#EAA86C", 1)],
           note="頭部顏色加深加飽和", gradientUnits="userSpaceOnUse", cx=238, cy=296, r=82, fx=232, fy=290)
for i, (ex, ey, er) in enumerate(s.params["ears"]):
    s.gradient(f"g_ear{i}", "radial", [(0, "#FAD7A6", 1), (1, "#EAAA70", 1)],
               gradientUnits="userSpaceOnUse", cx=ex - 5, cy=ey - 6, r=er * 1.35)
s.commit(small=True, final_view=True)
