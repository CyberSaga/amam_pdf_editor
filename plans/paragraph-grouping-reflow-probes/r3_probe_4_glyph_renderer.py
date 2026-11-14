"""P4 diagnosis: glyph-id renderer vs page raster. argv: src pdf, out dir."""
from __future__ import annotations

import io
import re
import sys

import fitz
import pymupdf.mupdf as mupdf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src, outdir = sys.argv[1], sys.argv[2]
PH = 842.04
Z = 2.0
doc = fitz.open(src)
page = doc[0]
print("mediabox", page.mediabox, "cropbox", page.cropbox, "rotation", page.rotation)


def font_bytes(font_xref: int) -> bytes:
    obj = doc.xref_object(font_xref, compressed=True)
    m = re.search(r"/DescendantFonts\s*\[?\s*(\d+) 0 R", obj)
    if m:
        dx = int(m.group(1))
        dobj = doc.xref_object(dx, compressed=True)
        if dobj.strip().startswith("["):
            dx = int(re.search(r"(\d+) 0 R", dobj).group(1))
            dobj = doc.xref_object(dx, compressed=True)
        obj = dobj
    fd = int(re.search(r"/FontDescriptor (\d+) 0 R", obj).group(1))
    ff = int(re.search(r"/FontFile2 (\d+) 0 R", doc.xref_object(fd, compressed=True)).group(1))
    return doc.xref_stream(ff)


cxs = page.get_contents()[0]
stream = doc.xref_stream(cxs).decode("latin-1")
pat = re.compile(r"BT(?: [\d.\-]+ Tc)?/(F\d) 14\.04 Tf 1 0 0 1 ([\d.]+) 357\.89 Tm")
font_at_x = {round(float(m.group(2)), 2): m.group(1) for m in pat.finditer(stream)}
spans = [sp for sp in page.get_texttrace() if abs(sp["chars"][0][2][1] - 484.15) < 0.2]
items = {"F1": [], "F2": []}
for sp in spans:
    fx = font_at_x[round(sp["chars"][0][2][0], 2)]
    for ch in sp["chars"]:
        items[fx].append((ch[1], sp["size"], ch[2][0], ch[2][1], ch[3]))
fonts = {}
for res, xr in (("F1", 3770), ("F2", 3771)):
    buf = mupdf.fz_new_buffer_from_copied_data(font_bytes(xr))
    fonts[res] = mupdf.fz_new_font_from_buffer(None, buf, 0, 0)

clip = fitz.Rect(100, 470, 545, 490)
CS = fitz.csGRAY
page_pm = page.get_pixmap(matrix=fitz.Matrix(Z, Z), clip=clip, alpha=False, colorspace=CS)
irect = page_pm.irect


def draw(mode: str, aa: int | None = None) -> fitz.Pixmap:
    pm = fitz.Pixmap(CS, irect, False)
    pm.clear_with(255)
    if mode == "device":
        ctm = mupdf.FzMatrix()
    else:  # replicate the page pipeline: user-space trm, page ctm
        ctm = mupdf.FzMatrix(Z, 0, 0, -Z, 0, Z * PH)
    for res in ("F2", "F1"):
        text = mupdf.FzText()
        for gid, size, ox, oy, _bb in items[res]:
            if mode == "device":
                trm = mupdf.FzMatrix(size * Z, 0, 0, -size * Z, ox * Z, oy * Z)
            else:
                trm = mupdf.FzMatrix(size, 0, 0, size, ox, PH - oy)
            mupdf.fz_show_glyph(text, fonts[res], trm, gid, -1, 0, 0, mupdf.FZ_BIDI_LTR, mupdf.FZ_LANG_UNSET)
        dev = mupdf.fz_new_draw_device(mupdf.FzMatrix(), pm.this)
        cp = mupdf.FzColorParams()
        cp.ri, cp.bp, cp.op, cp.opm = 1, 1, 0, 0
        mupdf.fz_fill_text(dev, text, ctm, mupdf.fz_device_gray(), [0.0], 1.0, cp)
        mupdf.fz_close_device(dev)
    return pm


def cmp(a: fitz.Pixmap, b: fitz.Pixmap) -> tuple[int, int]:
    n = mx = 0
    for u, v in zip(a.samples, b.samples):
        if u != v:
            n += 1
            mx = max(mx, abs(u - v))
    return n, mx


print("aa levels:", mupdf.fz_aa_level(), mupdf.fz_text_aa_level(), mupdf.fz_graphics_aa_level())
for mode in ("device", "pagectm"):
    pm = draw(mode)
    print(mode, "diff samples / max delta:", cmp(page_pm, pm), "of", len(page_pm.samples))
    pm.save(f"{outdir}/p4_{mode}.png")

pm = draw("pagectm")
sa, sb = page_pm.samples, pm.samples
print("ink mask (sample != 255) equal:", all((u == 255) == (v == 255) for u, v in zip(sa, sb)),
      "| mask mismatches:", sum(1 for u, v in zip(sa, sb) if (u == 255) != (v == 255)))
print("binarised at 128 mismatches:", sum(1 for u, v in zip(sa, sb) if (u < 128) != (v < 128)))
# a wrong glyph as a control: shift every gid by one
items_bad = {k: [(g + 1, s, x, y, bb) for g, s, x, y, bb in v] for k, v in items.items()}
items, keep = items_bad, items
bad = draw("pagectm")
items = keep
print("control (gid+1) mask mismatches:", sum(1 for u, v in zip(sa, bad.samples) if (u == 255) != (v == 255)),
      "binarised mismatches:", sum(1 for u, v in zip(sa, bad.samples) if (u < 128) != (v < 128)))
# control: one glyph moved by 0.3 pt
g0 = keep["F2"][5]
items = {"F1": keep["F1"], "F2": keep["F2"][:5] + [(g0[0], g0[1], g0[2] + 0.3, g0[3], g0[4])] + keep["F2"][6:]}
mv = draw("pagectm")
items = keep
print("control (one glyph +0.3pt) mask mismatches:", sum(1 for u, v in zip(sa, mv.samples) if (u == 255) != (v == 255)),
      "binarised mismatches:", sum(1 for u, v in zip(sa, mv.samples) if (u < 128) != (v < 128)))
sys.exit(0)
# is the page raster itself reproducible, and what does the display list path give?
again = page.get_pixmap(matrix=fitz.Matrix(Z, Z), clip=clip, alpha=False)
print("page raster reproducible:", cmp(page_pm, again))
# the page with ONLY this line's text (all other content removed) to rule out neighbours / clip effects
d2 = fitz.open(src)
p2 = d2[0]
shows = re.findall(r"BT(?: [\d.\-]+ Tc)?/F\d 14\.04 Tf 1 0 0 1 [\d.]+ 357\.89 Tm.*?ET", stream, re.S)
d2.update_stream(p2.get_contents()[0], ("0 g " + " ".join(shows)).encode("latin-1"))
p2 = d2[0]
only = p2.get_pixmap(matrix=fitz.Matrix(Z, Z), clip=clip, alpha=False)
print("page vs only-this-line content stream:", cmp(page_pm, only))
print("only-line vs show_glyph(pagectm):", cmp(only, draw("pagectm")))
# per-glyph: where do differences sit
pm = draw("pagectm")
w = page_pm.width
sa, sb = page_pm.samples, pm.samples
per = []
for res in ("F2", "F1"):
    for gid, size, ox, oy, bb in items[res]:
        x0, x1 = int(bb[0] * Z) - irect.x0, int(bb[2] * Z) + 1 - irect.x0
        n = 0
        for yy in range(page_pm.height):
            for xx in range(max(0, x0), min(w, x1)):
                o = (yy * w + xx) * 3
                if sa[o] != sb[o]:
                    n += 1
        per.append((res, gid, round(ox, 2), n))
print("per-glyph differing pixels:", per)
