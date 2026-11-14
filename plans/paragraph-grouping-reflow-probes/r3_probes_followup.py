"""Round-3 follow-up checks (scratch only). argv: src pdf, out dir, repo root.

P1c  does tobytes(garbage=4) renumber the LIVE handle?
P2c  between-show gap on one baseline: does rawdict mark the space synthetic?
P4c  glyph-id renderer with PyMuPDF's own colour-params form: exact raster?
P5c  one BT body holding atoms on two baselines and a donor Tf switch; re-parse; index regrouping.
"""
from __future__ import annotations

import io
import re
import shutil
import sys

import fitz
import pymupdf.mupdf as mupdf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src, outdir, repo = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo)
PH = 842.04
Z = 2.0


def hdr(t: str) -> None:
    print(f"\n===== {t} =====")


# ------------------------------------------------------------------ P1c
hdr("P1c live handle after tobytes(garbage=N)")
for g in (0, 1, 2):  # 3 and 4 renumber further (object 3771 itself goes out of range)
    d = fitz.open(src)
    n0 = d.xref_length()
    x = d.get_new_xref()
    d.update_object(x, "<</ProbeOrphan true>>")
    n1 = d.xref_length()
    page_xref0 = d[0].xref
    f2_before = d.xref_object(3771, compressed=True)[:60]
    out = fitz.open("pdf", d.tobytes(garbage=g))
    try:
        orphan = repr(d.xref_object(x, compressed=True)[:24])
    except RuntimeError as e:
        orphan = f"RAISES {e}"
    print(f"garbage={g}: live len {n0}->{n1}->{d.xref_length()} | live orphan={orphan} "
          f"| live page xref {page_xref0}->{d[0].xref} | live obj 3771 same={d.xref_object(3771, compressed=True)[:60] == f2_before} "
          f"| OUTPUT len {out.xref_length()} page xref {out[0].xref}")

# ------------------------------------------------------------------ P2c
hdr("P2c between-show gap on one baseline")
t = fitz.open()
tp = t.new_page(width=300, height=200)
tp.insert_font(fontname="helv")
cx = t.get_new_xref()
t.update_object(cx, "<<>>")
for gap_x in (44.0, 46.0, 50.0):
    t.update_stream(cx, f"BT /helv 12 Tf 1 0 0 1 20 120 Tm (Left) Tj ET BT /helv 12 Tf 1 0 0 1 {gap_x} 120 Tm (Right) Tj ET".encode())
    t.xref_set_key(tp.xref, "Contents", f"{cx} 0 R")
    tp = t[0]
    rd = tp.get_text("rawdict")
    for b in rd["blocks"]:
        for ln in b["lines"]:
            s = "".join(c["c"] for spn in ln["spans"] for c in spn["chars"])
            syn = [c.get("synthetic") for spn in ln["spans"] for c in spn["chars"] if c["c"] == " "]
            print(f"  second show at x={gap_x}: line {s!r} spans={len(ln['spans'])} space synthetic flags={syn}")

# ------------------------------------------------------------------ P4c
hdr("P4c glyph-id renderer, PyMuPDF colour-params form")
doc = fitz.open(src)
page = doc[0]


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


stream = doc.xref_stream(page.get_contents()[0]).decode("latin-1")
pat = re.compile(r"BT(?: [\d.\-]+ Tc)?/(F\d) 14\.04 Tf 1 0 0 1 ([\d.]+) 357\.89 Tm")
font_at_x = {round(float(m.group(2)), 2): m.group(1) for m in pat.finditer(stream)}
items: dict[str, list] = {"F1": [], "F2": []}
for sp in page.get_texttrace():
    if abs(sp["chars"][0][2][1] - 484.15) < 0.2:
        fx = font_at_x[round(sp["chars"][0][2][0], 2)]
        for ch in sp["chars"]:
            items[fx].append((ch[1], sp["size"], ch[2][0], ch[2][1]))
fonts = {}
for res, xr in (("F1", 3770), ("F2", 3771)):
    fonts[res] = mupdf.fz_new_font_from_buffer(None, mupdf.fz_new_buffer_from_copied_data(font_bytes(xr)), 0, 0)
clip = fitz.Rect(100, 470, 545, 490)


def draw(cs: fitz.Colorspace, irect: fitz.IRect, one_text: bool) -> fitz.Pixmap:
    pm = fitz.Pixmap(cs, irect, False)
    pm.clear_with(255)
    dev = mupdf.fz_new_draw_device(mupdf.FzMatrix(), pm.this)
    cp = mupdf.FzColorParams(mupdf.fz_default_color_params)
    texts = []
    text = mupdf.FzText()
    for res in ("F2", "F1"):
        if not one_text:
            text = mupdf.FzText()
        for gid, size, ox, oy in items[res]:
            trm = mupdf.FzMatrix(size * Z, 0, 0, -size * Z, ox * Z, oy * Z)
            mupdf.fz_show_glyph(text, fonts[res], trm, gid, -1, 0, 0, mupdf.FZ_BIDI_LTR, mupdf.FZ_LANG_UNSET)
        if not one_text:
            texts.append(text)
    if one_text:
        texts = [text]
    for tx in texts:
        mupdf.fz_fill_text(dev, tx, mupdf.FzMatrix(), mupdf.fz_device_gray(), [0.0, 0.0, 0.0, 0.0], 1.0, cp)
    mupdf.fz_close_device(dev)
    return pm


for cs, name in ((fitz.csRGB, "RGB"), (fitz.csGRAY, "GRAY")):
    ref_pm = page.get_pixmap(matrix=fitz.Matrix(Z, Z), clip=clip, alpha=False, colorspace=cs)
    for one in (False, True):
        pm = draw(cs, ref_pm.irect, one)
        sa, sb = ref_pm.samples, pm.samples
        n = sum(1 for u, v in zip(sa, sb) if u != v)
        mx = max((abs(u - v) for u, v in zip(sa, sb)), default=0)
        print(f"  {name} one_text={one}: differing samples={n} of {len(sa)} max delta={mx} "
              f"mask mismatches={sum(1 for u, v in zip(sa, sb) if (u == 255) != (v == 255))}")

# ------------------------------------------------------------------ P5c
hdr("P5c one BT body: two baselines + donor Tf switch; second rewrite; index regrouping")
from model.text_block import TextBlockManager  # noqa: E402


def paras(d: fitz.Document) -> list[tuple]:
    mgr = TextBlockManager()
    mgr.rebuild_page(0, d)
    return [(p.paragraph_id, tuple(round(v, 1) for v in p.bbox), len(p.run_ids), p.text) for p in mgr.get_paragraphs(0)]


def trace_of(pg: fitz.Page) -> list[tuple]:
    return sorted((sp["font"], ch[0], ch[1], round(ch[2][0], 2), round(ch[2][1], 2)) for sp in pg.get_texttrace() for ch in sp["chars"])


copy = f"{outdir}/p5c.pdf"
shutil.copyfile(src, copy)
d = fitz.open(copy)
pg = d[0]
before_paras = paras(d)
tr0 = trace_of(pg)
d.xref_set_key(pg.xref, "Resources/Font/FDonor", "3966 0 R")
cxr = pg.get_contents()[0]
st = d.xref_stream(cxr)
old = b"BT/F2 14.04 Tf 1 0 0 1 511.08 378.89 Tm[<00AE00A8>]TJ ET"
assert st.count(old) == 1
# first glyph stays, a donor glyph takes the second slot, the second glyph moves to the free tail of line 3
new1 = (b"BT/F2 14.04 Tf 1 0 0 1 511.08 378.89 Tm[<00AE>]TJ"
        b"/FDonor 14.04 Tf 1 0 0 1 525.12 378.89 Tm[<0445>]TJ"
        b"/F2 14.04 Tf 1 0 0 1 340 336.89 Tm[<00A8>]TJ ET")
d.update_stream(cxr, st.replace(old, new1))
pg = d[0]
tr1 = trace_of(pg)
moved = sorted(set(tr1) - set(tr0))
gone = sorted(set(tr0) - set(tr1))
print("after rewrite 1: trace added:", [(chr(u), g, x, y) for _, u, g, x, y in moved], "| removed:", [(chr(u), g, x, y) for _, u, g, x, y in gone])
# product replay: how does it see this body?
try:
    from model.text_commit import replay as rp

    names = [n for n in dir(rp) if "replay" in n.lower() or "Show" in n]
    print("replay module entry points:", names[:12])
except Exception as e:  # noqa: BLE001
    print("replay import failed:", type(e).__name__, e)
# second rewrite of the result: parse the three runs back out of the body and re-emit them in another order/shape
st2 = d.xref_stream(cxr)
mb = re.search(rb"BT/F2 14\.04 Tf 1 0 0 1 511\.08 378\.89 Tm.*? ET", st2, re.S)
runs = re.findall(rb"(?:/(\w+) 14\.04 Tf)? ?1 0 0 1 ([\d.]+) ([\d.]+) Tm\[(<[0-9A-F]+>)\]TJ", mb.group(0))
print("runs parsed from the rewritten body:", runs)
cur = b"F2"
body = b"BT"
for fn, x, y, arr in reversed(runs):  # paint order reversed: must still be identical
    body += b"/" + (fn or cur) + b" 14.04 Tf 1 0 0 1 " + x + b" " + y + b" Tm[" + arr + b"]TJ"
# NOTE: runs[i][0] is empty when the font did not change; resolve it in order first
resolved, cur = [], b""
for fn, x, y, arr in runs:
    cur = fn or cur
    resolved.append((cur, x, y, arr))
body = b"BT" + b"".join(b"/" + fn + b" 14.04 Tf 1 0 0 1 " + x + b" " + y + b" Tm[" + arr + b"]TJ" for fn, x, y, arr in reversed(resolved)) + b" ET"
d.update_stream(cxr, st2.replace(mb.group(0), body))
pg = d[0]
print("after rewrite 2 (runs re-emitted in reverse order): trace equal to rewrite 1:", trace_of(pg) == tr1)
saved = f"{outdir}/p5c_saved.pdf"
d.save(saved, garbage=3, deflate=True)
r = fitz.open(saved)
print("reopen trace equal:", trace_of(r[0]) == tr1)
after_paras = paras(r)
print("paragraph ids equal:", [p[0] for p in before_paras] == [p[0] for p in after_paras], "| count", len(before_paras), len(after_paras))
for a, b in zip(before_paras, after_paras):
    if a != b:
        print("  before:", a[0], a[1], a[2], repr(a[3][-24:]))
        print("  after :", b[0], b[1], b[2], repr(b[3][-24:]))
rd = r[0].get_text("dict", clip=fitz.Rect(70, 445, 560, 515))
for b in rd["blocks"]:
    print("  block", b["number"], "lines:", [(round(ln["bbox"][1], 1), "".join(s["text"] for s in ln["spans"])[-14:]) for ln in b["lines"]])

# ------------------------------------------------------------------ P5d
hdr("P5d a realistic push: last glyph of line 1 becomes the first glyph of line 2 (reading order kept)")
copy = f"{outdir}/p5d.pdf"
shutil.copyfile(src, copy)
d = fitz.open(copy)
pg = d[0]
d.xref_set_key(pg.xref, "Resources/Font/FDonor", "3966 0 R")
cxr = pg.get_contents()[0]
st = d.xref_stream(cxr)
# line 2 moves right by one em to make room at its start
st = re.sub(rb"1 0 0 1 ([\d.]+) 357\.89 Tm", lambda m: b"1 0 0 1 %.2f 357.89 Tm" % (float(m.group(1)) + 14.04), st)
new = (b"BT/F2 14.04 Tf 1 0 0 1 511.08 378.89 Tm[<00AE>]TJ"
       b"/FDonor 14.04 Tf 1 0 0 1 525.12 378.89 Tm[<0445>]TJ"
       b"/F2 14.04 Tf 1 0 0 1 104.66 357.89 Tm[<00A8>]TJ ET")
assert st.count(old) == 1
d.update_stream(cxr, st.replace(old, new))
saved = f"{outdir}/p5d_saved.pdf"
d.save(saved, garbage=3, deflate=True)
r = fitz.open(saved)
after = paras(r)
print("paragraph ids equal:", [p[0] for p in before_paras] == [p[0] for p in after], "| count", len(before_paras), len(after))
for a, b in zip(before_paras, after):
    if a != b:
        print("  before:", a[0], a[1], a[2], repr(a[3][:14]), "...", repr(a[3][-14:]))
        print("  after :", b[0], b[1], b[2], repr(b[3][:14]), "...", repr(b[3][-14:]))
rd = r[0].get_text("dict", clip=fitz.Rect(70, 445, 560, 515))
for b in rd["blocks"]:
    print("  block", b["number"], "lines:", [(round(ln["bbox"][1], 1), "".join(s["text"] for s in ln["spans"])[:6], "".join(s["text"] for s in ln["spans"])[-6:]) for ln in b["lines"]])
