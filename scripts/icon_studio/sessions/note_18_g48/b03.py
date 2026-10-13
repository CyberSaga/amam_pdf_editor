"""Batch 3 of the 18_新增註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "48 格：檢查整體",
        "1×（48 px）看：對話框、尾巴、加號章都清楚，臉也讀得出來；但下巴下面那截身體一路垂到框底（y 36），在 1× 像一條腿。"
        "參考只在下巴下露出約 4 格。",
        "身體縮短變小（rx 3.6、ry 3.8、中心 (14.4, 30.2)），只在下巴和框緣之間露出一小截，下緣停在 y 34。",
        tempo="normal")
s.look((9, 26, 6, 11), "身體像腿")
s.mod("hm_body", note="身體縮成一小截", cx=14.4, cy=30.2, rx=3.6, ry=3.8)
s.commit()
