"""Batch 1 of the 22_添加浮水印 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, PURPLE, badge_plus, flap_d, page_d, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：紙上緣的倉鼠臉、印章、淡紫水滴、加號章。",
        "紙外緣 x 2/13、y 5/15；臉用 16 格五列放 x 3–9；印章縮成 5 格寬的一列底座加鈕；水滴 3×4 逐像素；加號章中心 (11.5, 11.5)。",
        tempo="normal")
s.add("sheet", "path", "object", d=page_d(2.5, 5.5, 12.5, 14.5, 1, 3), fill=PAPER, stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
s.add("flap", "path", "object", d=flap_d(12.5, 5.5, 3, 0.5), fill="#DCDAEC", stroke=INK, stroke_width=1,
      stroke_linejoin="round", anim="fill")
pixmap(s, "hm", PEEK16, 3, 0, "hamster")
pixmap(s, "stamp", [".NNN.", "NUUUN", "NNNNN"], 4, 5, "front", legend={"U": ("body", PURPLE), "N": ("ink", INK)})
pixmap(s, "drop", [".L.", "LLL", "LLL"], 5, 9, "object_fx", legend={"L": ("fill", "#B3A9E6")})
badge_plus(s, "badge", 16, 11.5, 11.5)
s.commit()
