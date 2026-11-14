from __future__ import annotations

import io
import re
import sys

import fitz
from fontTools.ttLib import TTFont

doc = fitz.open(sys.argv[1])


def fontfile(xref_fd: int) -> bytes:
    fd = doc.xref_object(xref_fd, compressed=True)
    m = re.search(r"/FontFile2 (\d+) 0 R", fd)
    return doc.xref_stream(int(m.group(1)))


def load(data: bytes) -> TTFont:
    return TTFont(io.BytesIO(data), lazy=True)


subset_f2 = load(fontfile(3902))
subset_f1 = load(fontfile(3905))
full_doc = load(fontfile(3969))
system = load(open("C:/Windows/Fonts/kaiu.ttf", "rb").read())


def compare(name: str, sub: TTFont, full: TTFont) -> None:
    sg, fg = sub["glyf"], full["glyph" if False else "glyf"]
    order_s, order_f = sub.getGlyphOrder(), full.getGlyphOrder()
    print(f"{name}: numGlyphs sub={len(order_s)} full={len(order_f)} upm={sub['head'].unitsPerEm}/{full['head'].unitsPerEm}")
    same = diff = empty = 0
    hm_same = hm_diff = 0
    for gid in range(min(len(order_s), len(order_f))):
        a = sg.glyphs[order_s[gid]]
        a_data = a.data if hasattr(a, "data") else a.compile(sg)
        if not a_data:
            empty += 1
            continue
        b = fg.glyphs[order_f[gid]]
        b_data = b.data if hasattr(b, "data") else b.compile(fg)
        if a_data.rstrip(b"\0") == b_data.rstrip(b"\0"):
            same += 1
        else:
            diff += 1
        if sub["hmtx"].metrics[order_s[gid]][0] == full["hmtx"].metrics[order_f[gid]][0]:
            hm_same += 1
        else:
            hm_diff += 1
    print(f"  non-empty glyphs: same={same} diff={diff} (empty in subset={empty}); advance same={hm_same} diff={hm_diff}")


compare("F2 subset vs in-doc full F0", subset_f2, full_doc)
compare("F2 subset vs system kaiu.ttf", subset_f2, system)
compare("F1 subset vs system kaiu.ttf", subset_f1, system)
compare("in-doc full F0 vs system kaiu.ttf", full_doc, system)
cmap = system.getBestCmap()
order = system.getGlyphOrder()
for ch in "包含測試點位範本（）":
    g = cmap.get(ord(ch))
    print(ch, g, system["hmtx"].metrics[g][0] if g else None)
