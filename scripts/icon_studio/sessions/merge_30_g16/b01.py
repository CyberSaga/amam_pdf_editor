"""Batch 1 of the 30_合併PDF 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER, PEEK16, PURPLE_DARK, PURPLE_LIGHT, RED, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：兩張 PDF 紙、倉鼠臉、深紫匯流箭頭、兩層紙疊。",
        "兩張紙縮成 5×6（1 px 框、紅點標誌），倉鼠 16 格探頭臉放中間，箭頭各一格斜線，紙疊兩層。",
        tempo="normal")
PAGES = [
    "NNNN.....NNNN.",
    "NWWNN....NWWNN",
    "NWRWN....NWRWN",
    "NRWRN....NRWRN",
    "NNNNN....NNNNN",
]
pixmap(s, "pages", PAGES, 1, 0, "object", legend={"W": ("paper", PAPER), "R": ("mark", RED), "N": ("ink", INK)})
pixmap(s, "hm", PEEK16, 4, 5, "hamster")
pixmap(s, "arrows", ["D..........D", ".D........D."], 2, 6, "front", legend={"D": ("fill", PURPLE_DARK)})
STACK = [
    "NNNNNNNNN",
    "NWWWWWWWN",
    "NNNNNNNNN",
    "NLLLLLLLN",
    "NNNNNNNNN",
]
pixmap(s, "stack", STACK, 3, 11, "badge", legend={"W": ("paper", PAPER), "L": ("lower", PURPLE_LIGHT), "N": ("ink", INK)})
s.commit()
