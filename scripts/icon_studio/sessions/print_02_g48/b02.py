"""Batch 2 of the 02_列印 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from parts import INK, LINE, PURPLE, hamster48, paw48
from studio import Studio

BODY_TOP = "#ECEBF7"
s = Studio.open()
s.begin(5, "48 格：出紙口、臉、手掌與機身細節",
        "色塊疊參考吻合；但出紙口的石板色被白紙的框蓋住，只剩一圈黑框，看不出是一道開口；出紙白紙也只剩 8 格高，放不下三行字。",
        "機身、進紙匣、進紙白紙整組上移 1 格（機身外緣 y 20/38）；出紙口加寬到 x 12–36、只畫上緣與兩側，"
        "白紙的上框落在 y 32–34，讓 1.5 格石板色露在開口上緣與兩側；白紙上三行淡紫字線；倉鼠補臉、兩隻手掌抓住進紙白紙的上緣；"
        "機身頂面加一條淺色帶、右上角一顆按鈕；擦掉草稿。",
        tempo="normal")
s.look((11, 28, 26, 17), "出紙口只剩黑框")
s.mod("tray", note="上移 1 格", d=rrect_d(11, 16, 37, 23, 1.5))
s.mod("sheet_in", note="上移 1 格", d="M15 23V16A1 1 0 0 1 16 15H32A1 1 0 0 1 33 16V23Z")
s.mod("printer", note="機身上移 1 格", d=rrect_d(7.25, 21.25, 40.75, 36.75, 3))
s.mod("slot", note="開口加寬、下緣接機身外框", d="M12.75 35.5V30.75A1 1 0 0 1 13.75 29.75H34.25A1 1 0 0 1 35.25 30.75V35.5")
s.mod("sheet_out", note="白紙上框下移，露出石板色", d="M16 33H32V43A1 1 0 0 1 31 44H13.2Q12.1 44 12.7 43.1L15.3 39.4Q16 38.4 16 37.2Z")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
hamster48(s, "hm", 24, 11, 7.4, 6.6, k=0.78, eye_y=10.2, parts=("face",))
paw48(s, "hm_paw0", 17.2, 14.4, layer="front", k=0.95)
paw48(s, "hm_paw1", 30.8, 14.4, layer="front", k=0.95)
s.add("printer_top", "path", "object_fx", d="M8.5 24.5V24.25A1.75 1.75 0 0 1 10.25 22.5H37.75A1.75 1.75 0 0 1 39.5 24.25V24.5Z",
      fill=BODY_TOP, anim="fill")
s.add("button", "circle", "object_fx", cx=36.5, cy=26.5, r=1.2, fill=PURPLE, stroke=INK, stroke_width=1, anim="pop")
s.add("text_lines", "path", "object_fx", d="M18.5 35.75H29.5M18.5 38.25H29.5M18.5 40.75H25", fill="none", stroke=LINE,
      stroke_width=1.5, stroke_linecap="round", anim="draw")
s.commit(compare=True)
