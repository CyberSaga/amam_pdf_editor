"""Round-3 probes 4, 5 + controls for 1 and 2 (scratch only). argv: src pdf, out dir."""
from __future__ import annotations

import io
import re
import shutil
import sys

import fitz
import pymupdf.mupdf as mupdf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src, outdir = sys.argv[1], sys.argv[2]
PH = 842.04


def hdr(t: str) -> None:
    print(f"\n===== {t} =====")


# ------------------------------------------------- P1 control: re-create at a freed xref
hdr("P1b re-create an object at a freed xref after a garbage=1 round trip")
d = fitz.open(src)
x = d.get_new_xref()
d.update_object(x, "<</ProbeOrphan true>>")
r = fitz.open("pdf", d.tobytes(garbage=1))
print("freed slot reads:", repr(r.xref_object(x, compressed=True)))
try:
    r.update_object(x, "<</ProbeOrphan true/Again true>>")
    print("update_object on freed slot OK:", r.xref_object(x, compressed=True))
    r.xref_set_key(r[0].xref, "Resources/Font/FProbe", f"{x} 0 R")
    r2 = fitz.open("pdf", r.tobytes(garbage=1))
    print("referenced + saved again:", r2.xref_object(x, compressed=True), "| len", r2.xref_length())
except Exception as e:  # noqa: BLE001
    print("update_object on freed slot FAILED:", type(e).__name__, e)
# garbage=3/4 renumber?
r4 = fitz.open("pdf", d.tobytes(garbage=4))
print("garbage=4: xref_length", d.xref_length(), "->", r4.xref_length())
# restoring the page object bytes exactly (instead of xref_set_key null)
d2 = fitz.open(src)
p = d2[0]
before_obj = d2.xref_object(p.xref, compressed=True)
res = d2.xref_get_key(p.xref, "Resources")
print("page /Resources kind:", res[0], res[1][:80])
d2.xref_set_key(p.xref, "Resources/Font/FDonor", "3966 0 R")
mid_obj = d2.xref_object(p.xref, compressed=True)
d2.update_object(p.xref, before_obj)
print("page object restored byte-equal:", d2.xref_object(p.xref, compressed=True) == before_obj, "| changed in between:", mid_obj != before_obj)
if res[0] == "xref":
    rx = int(res[1].split()[0])
    print("resources obj:", d2.xref_object(rx, compressed=True)[:200])

# ------------------------------------------------- P2 control: a kern-made word gap
hdr("P2b positive control: [(Hello) -500 (world)] TJ and a wide Tm gap")
t = fitz.open()
tp = t.new_page(width=300, height=200)
tp.insert_font(fontname="helv")
cx = t.get_new_xref()
t.update_object(cx, "<<>>")
t.update_stream(cx, b"BT /helv 12 Tf 1 0 0 1 20 150 Tm [(Hello) -500 (world)] TJ ET BT /helv 12 Tf 1 0 0 1 20 120 Tm (Left) Tj ET BT /helv 12 Tf 1 0 0 1 60 120 Tm (Right) Tj ET")
t.xref_set_key(tp.xref, "Contents", f"{cx} 0 R")
tp = t[0]
tr = [(chr(c[0]), round(c[2][0], 2), round(c[2][1], 2)) for sp in tp.get_texttrace() for c in sp["chars"]]
print("trace chars:", "".join(c[0] for c in tr), "| spaces in trace:", sum(1 for c in tr if c[0] == " "))
for label, kw in (("default", {}), ("INHIBIT_SPACES", {"flags": fitz.TEXTFLAGS_RAWDICT | fitz.TEXT_INHIBIT_SPACES})):
    rd = tp.get_text("rawdict", **kw)
    for b in rd["blocks"]:
        for ln in b["lines"]:
            s = "".join(c["c"] for spn in ln["spans"] for c in spn["chars"])
            sp_ = [(round(c["origin"][0], 2), round(c["bbox"][2] - c["bbox"][0], 2), c.get("synthetic")) for spn in ln["spans"] for c in spn["chars"] if c["c"] == " "]
            hits = [any(abs(o[0] - q[1]) < 0.05 for q in tr if q[0] == " ") for o in sp_]
            print(f"  [{label}] {s!r} spaces(origin,width,synthetic-key)={sp_} trace-glyph-at-origin={hits}")
    print(f"  [{label}] char keys:", sorted(rd["blocks"][0]["lines"][0]["spans"][0]["chars"][0].keys()))

# ------------------------------------------------- P4 glyph-id renderer
hdr("P4 fz_show_glyph renders a gid of an embedded program")
doc = fitz.open(src)
page = doc[0]
Z = 2.0
full = page.get_pixmap(matrix=fitz.Matrix(Z, Z), alpha=False)


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


def render_glyphs(data: bytes, items: list[tuple[int, float, float, float]], irect: fitz.IRect) -> fitz.Pixmap:
    buf = mupdf.fz_new_buffer_from_copied_data(data)
    font = mupdf.fz_new_font_from_buffer(None, buf, 0, 0)
    text = mupdf.FzText()
    for gid, size, ox, oy in items:
        trm = mupdf.FzMatrix(size * Z, 0, 0, -size * Z, ox * Z, oy * Z)
        mupdf.fz_show_glyph(text, font, trm, gid, -1, 0, 0, mupdf.FZ_BIDI_LTR, mupdf.FZ_LANG_UNSET)
    pm = fitz.Pixmap(fitz.csRGB, irect, False)
    pm.clear_with(255)
    dev = mupdf.fz_new_draw_device(mupdf.FzMatrix(), pm.this)
    mupdf.fz_fill_text(dev, text, mupdf.FzMatrix(), mupdf.fz_device_gray(), mupdf.floats_to_floatarray([0.0]) if hasattr(mupdf, "floats_to_floatarray") else [0.0], 1.0, mupdf.FzColorParams())
    mupdf.fz_close_device(dev)
    return pm


def cmp(a: fitz.Pixmap, b: fitz.Pixmap) -> tuple[int, int]:
    sa, sb = a.samples, b.samples
    if len(sa) != len(sb):
        return (-1, -1)
    n = mx = 0
    for u, v in zip(sa, sb):
        if u != v:
            n += 1
            mx = max(mx, abs(u - v))
    return n, mx


# line 2 of item 1 (baseline 484.15): all F2 glyphs
spans = [sp for sp in page.get_texttrace() if abs(sp["chars"][0][2][1] - 484.15) < 0.2]
f2 = font_bytes(3771)
f1 = font_bytes(3770)
print("spans on line 2:", len(spans), "fonts:", sorted({s["font"] for s in spans}), "sizes:", sorted({round(s["size"], 2) for s in spans}))
clip = fitz.Rect(100, 470, 545, 490)
irect = (clip * fitz.Matrix(Z, Z)).irect
page_pm = fitz.Pixmap(full, full.width, full.height, irect) if False else page.get_pixmap(matrix=fitz.Matrix(Z, Z), clip=clip, alpha=False)
irect = page_pm.irect
try:
    # which glyph belongs to which program: decide from the replay order (F1 = simple, 1 byte; F2 = 2 bytes)
    cxs = page.get_contents()[0]
    stream = doc.xref_stream(cxs).decode("latin-1")
    pat = re.compile(r"BT(?: [\d.\-]+ Tc)?/(F\d) 14\.04 Tf 1 0 0 1 ([\d.]+) 357\.89 Tm")
    font_at_x = {round(float(m.group(2)), 2): m.group(1) for m in pat.finditer(stream)}
    items_f = {"F1": [], "F2": [], "F3": []}
    for sp in spans:
        fx = font_at_x.get(round(sp["chars"][0][2][0], 2))
        if fx is None:
            print("  span without show match at x", sp["chars"][0][2][0])
            continue
        for ch in sp["chars"]:
            items_f[fx].append((ch[1], sp["size"], ch[2][0], ch[2][1]))
    print("glyphs per resource:", {k: len(v) for k, v in items_f.items()})
    mine = fitz.Pixmap(fitz.csRGB, irect, False)
    mine.clear_with(255)
    # draw both programs into one pixmap
    for res, data in (("F2", f2), ("F1", f1)):
        if not items_f[res]:
            continue
        buf = mupdf.fz_new_buffer_from_copied_data(data)
        font = mupdf.fz_new_font_from_buffer(None, buf, 0, 0)
        text = mupdf.FzText()
        for gid, size, ox, oy in items_f[res]:
            trm = mupdf.FzMatrix(size * Z, 0, 0, -size * Z, ox * Z, oy * Z)
            mupdf.fz_show_glyph(text, font, trm, gid, -1, 0, 0, mupdf.FZ_BIDI_LTR, mupdf.FZ_LANG_UNSET)
        dev = mupdf.fz_new_draw_device(mupdf.FzMatrix(), mine.this)
        try:
            mupdf.fz_fill_text(dev, text, mupdf.FzMatrix(), mupdf.fz_device_gray(), [0.0], 1.0, mupdf.FzColorParams())
        except Exception as e1:  # noqa: BLE001
            print("  fz_fill_text with list failed:", type(e1).__name__, str(e1)[:120])
            fa = mupdf.new_floatArray(1) if hasattr(mupdf, "new_floatArray") else None
            arr = mupdf.floatArray(1)
            arr[0] = 0.0
            mupdf.fz_fill_text(dev, text, mupdf.FzMatrix(), mupdf.fz_device_gray(), arr.cast(), 1.0, mupdf.FzColorParams())
        mupdf.fz_close_device(dev)
    n, mx = cmp(page_pm, mine)
    print(f"line-2 band {irect}: differing samples={n} of {len(page_pm.samples)} max delta={mx}")
    page_pm.save(f"{outdir}/p4_page.png")
    mine.save(f"{outdir}/p4_showglyph.png")
except Exception as e:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    print("P4 FAILED:", type(e).__name__, e)

# ------------------------------------------------- P5 whole-BT-body rewrite, twice
hdr("P5 whole BT body rewrite identity, then a second rewrite of the result")


def scan_array(s: str, i: int) -> int:
    """index just past the matching ']' of a TJ array starting at s[i] == '['"""
    assert s[i] == "["
    i += 1
    while True:
        c = s[i]
        if c == "]":
            return i + 1
        if c == "(":
            depth = 1
            i += 1
            while depth:
                if s[i] == "\\":
                    i += 2
                    continue
                if s[i] == "(":
                    depth += 1
                elif s[i] == ")":
                    depth -= 1
                i += 1
        elif c == "<":
            i = s.index(">", i) + 1
        else:
            i += 1


def lit_bytes(body: str) -> bytes:
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            n = body[i + 1]
            if n in "nrtbf":
                out.append({"n": 10, "r": 13, "t": 9, "b": 8, "f": 12}[n])
                i += 2
            elif n.isdigit():
                j = i + 1
                while j < len(body) and j < i + 4 and body[j].isdigit():
                    j += 1
                out.append(int(body[i + 1 : j], 8) & 255)
                i = j
            elif n == "\n":
                i += 2
            else:
                out.append(ord(n))
                i += 2
        else:
            out.append(ord(c))
            i += 1
    return bytes(out)


def array_codes(arr: str, width: int) -> list:
    """items of a TJ array: glyph codes (bytes) and kerns (str)"""
    codes: list = []
    i = 1
    while i < len(arr) - 1:
        c = arr[i]
        if c == "(":
            depth, j = 1, i + 1
            while depth:
                if arr[j] == "\\":
                    j += 2
                    continue
                if arr[j] == "(":
                    depth += 1
                elif arr[j] == ")":
                    depth -= 1
                j += 1
            raw = lit_bytes(arr[i + 1 : j - 1])
            codes += [raw[k : k + width] for k in range(0, len(raw), width)]
            i = j
        elif c == "<":
            j = arr.index(">", i)
            raw = bytes.fromhex(re.sub(r"\s", "", arr[i + 1 : j]))
            codes += [raw[k : k + width] for k in range(0, len(raw), width)]
            i = j + 1
        elif c in "-.0123456789":
            mnum = re.compile(r"-?[\d.]+").match(arr, i)
            codes.append(mnum.group(0))
            i = mnum.end()
        else:
            i += 1
    return codes


def emit_array(items: list) -> str:
    """codes + kerns back to a TJ array; leading/trailing kerns dropped (position comes from Tm)"""
    while items and isinstance(items[0], str):
        items = items[1:]
    while items and isinstance(items[-1], str):
        items = items[:-1]
    out, run = "[", ""
    for it in items:
        if isinstance(it, str):
            if run:
                out += f"<{run}>"
                run = ""
            out += it
        else:
            run += it.hex().upper()
    if run:
        out += f"<{run}>"
    return out + "]"


WIDTH = {"F1": 1, "F2": 2, "F3": 1}
YS = ("378.89", "357.89", "336.89")
head = re.compile(r"BT((?: [\d.\-]+ Tc)?)/(F\d) ([\d.]+) Tf 1 0 0 1 ([\d.]+) ([\d.]+) Tm")


def trace_of(pg: fitz.Page) -> list[tuple]:
    out = []
    for sp in pg.get_texttrace():
        for ch in sp["chars"]:
            out.append((sp["font"], round(sp["size"], 3), ch[0], ch[1], round(ch[2][0], 2), round(ch[2][1], 2), sp["color"], sp["type"], sp["opacity"]))
    return sorted(out)


def rewrite(stream: str, pg: fitz.Page, per_glyph: bool) -> tuple[str, int, int]:
    """Rewrite every BT body on the item-1 lines. Glyph x comes from texttrace (origin), per show."""
    tr = {}
    for sp in pg.get_texttrace():
        for ch in sp["chars"]:
            tr.setdefault(round(ch[2][1], 2), []).append((ch[2][0], ch[1]))
    out, pos, nshow, nglyph = [], 0, 0, 0
    for m in head.finditer(stream):
        if m.group(5) not in YS:
            continue
        # body runs to the matching ET; parse all (Tm, array) pairs inside
        i = m.end()
        tc, res, size, y = m.group(1), m.group(2), m.group(3), m.group(5)
        runs: list[tuple[float, list[bytes]]] = []
        x = float(m.group(4))
        while True:
            mm = re.compile(r"((?: 0 [gG])*)\[").match(stream, i)
            if mm:
                a0 = mm.end() - 1
                a1 = scan_array(stream, a0)
                assert stream[a1 : a1 + 2] == "TJ", stream[a1 : a1 + 10]
                runs.append((x, array_codes(stream[a0:a1], WIDTH[res])))
                i = a1 + 2
                continue
            mt = re.compile(r" ?1 0 0 1 ([\d.]+) ([\d.]+) Tm").match(stream, i)
            if mt:
                x = float(mt.group(1))
                i = mt.end()
                continue
            break
        assert stream[i : i + 3] == " ET", repr(stream[i - 40 : i + 20])
        allitems = [c for _, cs in runs for c in cs]
        # a kern that sat between two runs is not in the array any more; positions come from the trace
        codes = [c for c in allitems if isinstance(c, bytes)]
        if len(codes) < 2:
            continue
        # glyph origins of this show: the trace glyphs on this baseline from the first run's x on
        base = round(PH - float(y), 2)
        cand = sorted(g for g in tr.get(base, []) if g[0] >= runs[0][0] - 0.01)[: len(codes)]
        if len(cand) != len(codes) or abs(cand[0][0] - runs[0][0]) > 0.02:
            print("  skip show at", runs[0][0], y, "codes", len(codes), "cand", len(cand))
            continue
        cut = range(1, len(codes)) if per_glyph else [len(codes) // 2]
        pieces, start = [], 0
        # index of each code inside allitems, so kerns inside a piece are kept
        code_pos = [k for k, it in enumerate(allitems) if isinstance(it, bytes)]
        for c in list(cut) + [len(codes)]:
            lo = code_pos[start]
            hi = code_pos[c - 1] + 1
            pieces.append((cand[start][0], allitems[lo:hi]))
            start = c
        body = f"BT{tc}/{res} {size} Tf"
        for px, pcs in pieces:
            body += f" 1 0 0 1 {px:.4f} {y} Tm{emit_array(pcs)}TJ"
        out.append(stream[pos : m.start()])
        out.append(body)
        pos = i  # keep " ET"
        nshow += 1
        nglyph += len(codes)
    out.append(stream[pos:])
    return "".join(out), nshow, nglyph


copy = f"{outdir}/p5.pdf"
shutil.copyfile(src, copy)
d5 = fitz.open(copy)
pg = d5[0]
cx5 = pg.get_contents()[0]
pix0 = pg.get_pixmap(matrix=fitz.Matrix(2, 2)).samples
tr0 = trace_of(pg)
txt0 = pg.get_text()
s0 = d5.xref_stream(cx5).decode("latin-1")
print("BDC/EMC/q/Q counts before:", s0.count("BDC"), s0.count("EMC"), len(re.findall(r"(?<![A-Za-z])q(?![A-Za-z])", s0)), len(re.findall(r"(?<![A-Za-z])Q(?![A-Za-z])", s0)))
for rnd, per_glyph in ((1, False), (2, True)):
    s_in = d5.xref_stream(cx5).decode("latin-1")
    s_out, ns, ng = rewrite(s_in, pg, per_glyph)
    d5.update_stream(cx5, s_out.encode("latin-1"))
    pg = d5[0]
    pix = pg.get_pixmap(matrix=fitz.Matrix(2, 2)).samples
    ndiff = sum(1 for a, b in zip(pix, pix0) if a != b)
    tr = trace_of(pg)
    print(f"round {rnd} ({'one Tm per glyph' if per_glyph else 'split in two'}): shows rewritten={ns} glyphs={ng} "
          f"raster-diff-samples={ndiff} trace-equal(2dp)={tr == tr0} text-equal={pg.get_text() == txt0} "
          f"Tm count={s_out.count(' Tm')}")
    if tr != tr0:
        bad = [(a, b) for a, b in zip(tr, tr0) if a != b][:4]
        print("   first trace diffs:", bad)
saved = f"{outdir}/p5_saved.pdf"
d5.save(saved, garbage=3, deflate=True)
r5 = fitz.open(saved)
rp = r5[0]
pix = rp.get_pixmap(matrix=fitz.Matrix(2, 2)).samples
print("reopen: raster-diff-samples=", sum(1 for a, b in zip(pix, pix0) if a != b), "trace-equal=", trace_of(rp) == tr0, "text-equal=", rp.get_text() == txt0)
# rawdict segmentation after the per-glyph split: same lines/blocks?
def seg(pgx: fitz.Page) -> list[tuple]:
    rd = pgx.get_text("dict", clip=fitz.Rect(70, 445, 560, 535))
    return [(b["number"], len(b["lines"]), [round(ln["bbox"][1], 1) for ln in b["lines"]], "".join(s["text"] for ln in b["lines"] for s in ln["spans"])) for b in rd["blocks"]]
a, b = seg(fitz.open(src)[0]), seg(rp)
print("block/line segmentation equal after rewrites:", a == b)
if a != b:
    for u in a:
        print("   before:", u[:3], u[3][:40])
    for u in b:
        print("   after :", u[:3], u[3][:40])
