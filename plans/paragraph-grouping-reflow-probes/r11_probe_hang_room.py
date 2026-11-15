"""Round-11 probe: free width to the right of the measure M of a paragraph (C.2 `hang_room`, clip excluded).

Usage: python -I r11_probe_hang_room.py <pdf> <block:line> [<block:line> ...]
The given lines are the paragraph. M = largest plain end (trailing no-line-start marks set aside).
Band = top of the first line's box to the top of the nearest text line below (open there), else the
bottom of the last line's box. Reports the nearest object with x1 > M in that band. Prints no text.
"""
from __future__ import annotations

import sys

import fitz

MARKS = set("、。，．：；！？）」』】〕〉》｝］”’")  # NO_LINE_START of plan C.3


def main() -> None:
    doc = fitz.open(sys.argv[1])
    page = doc[0]
    want = {tuple(int(v) for v in a.split(":")) for a in sys.argv[2:]}
    d = page.get_text("rawdict")
    own: list[dict] = []
    others: list[dict] = []
    for bi, b in enumerate(d["blocks"]):
        for li, ln in enumerate(b.get("lines", [])):
            (own if (bi, li) in want else others).append(ln)
    plain_ends = []
    for ln in own:
        chars = [ch for sp in ln["spans"] for ch in sp["chars"] if not ch["c"].isspace()]
        while len(chars) > 1 and chars[-1]["c"] in MARKS:
            chars.pop()
        plain_ends.append(chars[-1]["bbox"][2])
    m = max(plain_ends)
    top = min(ln["bbox"][1] for ln in own)
    last_bottom = max(ln["bbox"][3] for ln in own)
    below = [ln["bbox"][1] for ln in others if ln["bbox"][1] >= last_bottom - 0.5]
    floor = min(below) if below else last_bottom
    print(f"M={m:.2f} band y=[{top:.2f},{floor:.2f}) cropbox x1={page.cropbox.x1:.2f} mediabox x1={page.mediabox.x1:.2f}")

    def hit(kind: str, x0: float, y0: float, x1: float, y1: float, found: list) -> None:
        if x1 > m and y1 > top and y0 < floor:
            found.append((max(0.0, x0 - m), kind, round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)))

    found: list = []
    for ln in others:
        for sp in ln["spans"]:
            for ch in sp["chars"]:
                if not ch["c"].isspace():
                    hit("glyph", *ch["bbox"], found)
    for dr in page.get_drawings():
        hit("drawing", *dr["rect"], found)
    for im in page.get_image_info():
        hit("image", *im["bbox"], found)
    for an in page.annots() or []:
        hit("annot", *an.rect, found)
    for w in page.widgets() or []:
        hit("widget", *w.rect, found)
    found.sort()
    print("objects right of M in band:", len(found))
    for f in found[:8]:
        print("  ", f)
    room = min([page.cropbox.x1 - m] + [f[0] for f in found])
    print(f"hang_room (no clip) = {room:.2f}")


main()
