from __future__ import annotations

import sys

import fitz

doc = fitz.open(sys.argv[1])
print("pages", len(doc))
for pno, page in enumerate(doc):
    print("=== page", pno + 1, page.rect, "rot", page.rotation)
    d = page.get_text("dict")
    for bi, b in enumerate(d["blocks"]):
        if b["type"] != 0:
            print(f"B{bi} image/other bbox={tuple(round(x,1) for x in b['bbox'])}")
            continue
        print(f"B{bi} bbox={tuple(round(x,1) for x in b['bbox'])} lines={len(b['lines'])}")
        for li, ln in enumerate(b["lines"]):
            bb = tuple(round(x, 1) for x in ln["bbox"])
            spans = ln["spans"]
            txt = "".join(s["text"] for s in spans)
            fonts = {(s["font"], round(s["size"], 2)) for s in spans}
            print(f"  L{li} {bb} nsp={len(spans)} {fonts} | {txt[:70]!r}")
    if pno >= 1:
        break
