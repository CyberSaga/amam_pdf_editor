"""Batch 2 of the 25_刪除頁 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import flap_d, page_d, pix_d
from studio import Studio

s = Studio.open()
s.begin(6, "16 格：叉叉離臉一格",
        "1× 看：紅叉緊貼倉鼠的右眼，臉、紙緣、叉叉擠成一團，看不出是哪一隻眼睛、哪一個叉。",
        "紙右移 1 格（外緣 x 6/14），紅叉跟著移到 x 8–11，和臉之間留出一欄白紙。",
        tempo="normal")
s.look((4, 4, 8, 6), "叉叉貼著眼睛")
s.mod("sheet", note="紙右移一格", d=page_d(6.5, 1.5, 13.5, 13.5, 1, 3))
s.mod("flap", d=flap_d(13.5, 1.5, 3, 0.5))
s.mod("x_mark", note="叉叉跟著移", d=pix_d(["R..R", ".RR.", ".RR.", "R..R"], "R", 8, 5))
s.commit()
