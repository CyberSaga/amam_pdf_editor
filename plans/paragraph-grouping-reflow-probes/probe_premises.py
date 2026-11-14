from __future__ import annotations

import io
import re
import shutil
import sys

import fitz
from fontTools.ttLib import TTFont

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src, outdir = sys.argv[1], sys.argv[2]

# --- 3 / 5: natural line height and embedding permission of the system face
sysfont = TTFont("C:/Windows/Fonts/kaiu.ttf", lazy=True)
hhea, os2, upm = sysfont["hhea"], sysfont["OS/2"], sysfont["head"].unitsPerEm
nat = (hhea.ascent - hhea.descent + hhea.lineGap) / upm
print(f"hhea asc={hhea.ascent} desc={hhea.descent} gap={hhea.lineGap} upm={upm} natural={nat:.4f} em")
print(f"OS/2 typo asc={os2.sTypoAscender} desc={os2.sTypoDescender} gap={os2.sTypoLineGap} win={os2.usWinAscent}/{os2.usWinDescent} fsType={os2.fsType:#06x}")
print(f"pitch 21.0 / (14.04 * natural) = {21.0 / (14.04 * nat):.4f}")

# --- 4: structure tree: which element owns each MCID of the page
doc = fitz.open(src)
page = doc[0]
cat = doc.pdf_catalog()
root = int(re.search(r"/StructTreeRoot (\d+) 0 R", doc.xref_object(cat, compressed=True)).group(1))
owner: dict[int, tuple[int, str]] = {}
seen: set[int] = set()


def walk(xref: int, depth: int) -> None:
    if xref in seen or depth > 40:
        return
    seen.add(xref)
    obj = doc.xref_object(xref, compressed=True)
    s = re.search(r"/S\s*/(\w+)", obj)
    tag = s.group(1) if s else "?"
    pg = re.search(r"/Pg (\d+) 0 R", obj)
    kraw = doc.xref_get_key(xref, "K")
    if kraw[0] in ("int",) and pg and int(pg.group(1)) == page.xref:
        owner[int(kraw[1])] = (xref, tag)
    elif kraw[0] == "array":
        for tok in re.finditer(r"(\d+) 0 R|(?<![\d.])(\d+)(?![\d.]* 0 R)", kraw[1]):
            if tok.group(1):
                walk(int(tok.group(1)), depth + 1)
            elif tok.group(2) and pg and int(pg.group(1)) == page.xref:
                owner[int(tok.group(2))] = (xref, tag)
    elif kraw[0] == "xref":
        walk(int(kraw[1].split()[0]), depth + 1)
    elif kraw[0] == "dict":
        m = re.search(r"/MCID (\d+)", kraw[1])
        if m:
            owner[int(m.group(1))] = (xref, tag)


walk(root, 0)
print(f"struct elems visited={len(seen)} mcids mapped on page={len(owner)}")
prev = None
for mcid in sorted(owner):
    if 105 <= mcid <= 150:
        cur = owner[mcid]
        if cur != prev:
            print(f"  MCID {mcid}.. -> elem {cur[0]} /{cur[1]}")
            prev = cur

# --- 1: donor premise: reference the in-document full face from the page, show one new glyph
copy = f"{outdir}/donor_probe.pdf"
shutil.copyfile(src, copy)
d = fitz.open(copy)
p = d[0]
before = p.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(40, 440, 560, 475)).tobytes()
res = d.xref_get_key(p.xref, "Resources/Font")
print("page font res:", res)
d.xref_set_key(p.xref, "Resources/Font/FDonor", "3966 0 R")
cx = p.get_contents()[0]
stream = d.xref_stream(cx)
old = b"BT/F2 14.04 Tf 1 0 0 1 511.08 378.89 Tm[<00AE00A8>]TJ ET"
assert stream.count(old) == 1, stream.count(old)
# gid of U+5305 in the full face is 1093 (probe_fonts); Identity CID=GID
new = b"BT/FDonor 14.04 Tf 1 0 0 1 511.08 378.89 Tm[<0445>]TJ/F2 14.04 Tf[<00A8>]TJ ET"
d.update_stream(cx, stream.replace(old, new))
p = d[0]
after = p.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(40, 440, 560, 475))
after.save(f"{outdir}/donor_probe_live.png")
print("live handle render changed:", after.tobytes() != before)
spans = [(s["font"], s["text"]) for b in p.get_text("dict", clip=fitz.Rect(500, 455, 545, 470))["blocks"] for ln in b.get("lines", []) for s in ln["spans"]]
print("live spans at line end:", spans)
saved = f"{outdir}/donor_probe_saved.pdf"
d.save(saved, garbage=3, deflate=True)
r = fitz.open(saved)
rp = r[0]
spans = [(s["font"], s["text"], round(s["origin"][0], 2)) for b in rp.get_text("dict", clip=fitz.Rect(500, 455, 545, 470))["blocks"] for ln in b.get("lines", []) for s in ln["spans"]]
print("reopened spans at line end:", spans)
rp.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(40, 440, 560, 475)).save(f"{outdir}/donor_probe_reopen.png")
