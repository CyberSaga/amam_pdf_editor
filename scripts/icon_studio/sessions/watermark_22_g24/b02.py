"""Batch 2 of the 22_添加浮水印 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PURPLE, PURPLE_DARK, pixmap
from studio import Studio

s = Studio.open()
s.begin(6, "24 格：印章往下放到紙上",
        "1× 看：印章底座的上框正好壓在紙的上緣，兩條深藍線疊成一道粗黑槓，看不出印章。",
        "印章按 48 格的比例下移：圓鈕跨在紙緣、脖子 2 列、底座落在 y 10–12，和紙緣之間隔一列白紙。",
        tempo="normal")
s.look((5, 6, 9, 6), "印章和紙緣黏成黑槓")
for eid in [e for e in list(s.elements) if e.startswith("stamp_")]:
    s.rm(eid, note="印章下移")
STAMP = [
    "..PNNNP..",
    "...NUN...",
    "...NUN...",
    "NNNNNNNNN",
    "NUUUUUUUN",
    "NNNNNNNNN",
]
pixmap(s, "stamp", STAMP, 5, 7, "front", legend={"P": ("paws", "#F6C58E"), "U": ("body", PURPLE),
                                                  "D": ("rim", PURPLE_DARK), "N": ("ink", INK)})
s.commit()
