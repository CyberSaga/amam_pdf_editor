from __future__ import annotations

import io
import sys

import fitz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
doc = fitz.open(sys.argv[1])
page = doc[0]
d = page.get_text("dict")
for bi in (18, 19, 21):
    b = d["blocks"][bi]
    for li, ln in enumerate(b["lines"]):
        s0 = ln["spans"][0]
        print(
            f"B{bi} L{li} x0={ln['bbox'][0]:.1f} x1={ln['bbox'][2]:.1f} "
            f"origin=({s0['origin'][0]:.2f},{s0['origin'][1]:.2f}) "
            f"asc={s0['ascender']:.3f} desc={s0['descender']:.3f} flags={s0['flags']} "
            f"fonts={[(s['font'][:12], round(s['size'],2)) for s in ln['spans']]}"
        )
# drawings/paths near the text? count
print("drawings", len(page.get_drawings()), "images", len(page.get_images()))
print("fonts", [(f[3], f[2], f[1]) for f in page.get_fonts()])
