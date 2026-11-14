"""Round-3 probes 1, 2, 3, 6 (scratch only). argv: src pdf, out dir."""
from __future__ import annotations

import io
import re
import shutil
import sys

import fitz
from fontTools.ttLib import TTFont

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src, outdir = sys.argv[1], sys.argv[2]
DONOR = 3966
INS = "包含測試點位範本（）"


def hdr(t: str) -> None:
    print(f"\n===== {t} =====")


# ---------------------------------------------------------------- probe 1
hdr("P1 garbage=1 save vs unreferenced objects")
copy = f"{outdir}/p1.pdf"
shutil.copyfile(src, copy)
d = fitz.open(copy)
n0 = d.xref_length()
x = d.get_new_xref()
d.update_object(x, "<</ProbeOrphan true>>")
x2 = d.get_new_xref()
d.update_object(x2, "<</ProbeStream true>>")
d.update_stream(x2, b"orphan stream")
# a donor entry added then removed again (the undo shape)
p = d[0]
d.xref_set_key(p.xref, "Resources/Font/FDonor", f"{DONOR} 0 R")
d.xref_set_key(p.xref, "Resources/Font/FDonor", "null")
print("xref_length before/after alloc:", n0, d.xref_length(), "orphans:", x, x2)
print("page Font dict after add+null:", d.xref_get_key(p.xref, "Resources/Font"))
out = f"{outdir}/p1_saved.pdf"
d.save(out, garbage=1)
print("LIVE after save(other path, garbage=1): orphan obj =", d.xref_object(x, compressed=True)[:60],
      "| stream =", d.xref_stream(x2), "| xref_length", d.xref_length())
r = fitz.open(out)
print("SAVED file: xref_length", r.xref_length())
for xx in (x, x2):
    try:
        print("  saved obj", xx, "=", repr(r.xref_object(xx, compressed=True)[:60]))
    except Exception as e:  # noqa: BLE001
        print("  saved obj", xx, "raises", type(e).__name__, e)
print("  saved donor obj still there:", r.xref_object(DONOR, compressed=True)[:50])
print("  saved page Font dict:", r.xref_get_key(r[0].xref, "Resources/Font"))
# does a NEW allocation on the reopened file reuse the freed number?
y = r.get_new_xref()
print("  new xref on reopened saved file:", y, "(orphans were", x, x2, ")")
# tobytes round trip (the app reopens the temp file after saving over the open file)
b = d.tobytes(garbage=1)
rr = fitz.open("pdf", b)
print("tobytes(garbage=1) reopen: orphan =", repr(rr.xref_object(x, compressed=True)[:40]), "len", rr.xref_length())
b0 = d.tobytes(garbage=0)
r0 = fitz.open("pdf", b0)
print("tobytes(garbage=0) reopen: orphan =", repr(r0.xref_object(x, compressed=True)[:40]))

# ---------------------------------------------------------------- probe 2
hdr("P2 synthetic spaces: rawdict char vs texttrace glyph at the origin")
doc = fitz.open(src)
page = doc[0]
trace = []
for sp in page.get_texttrace():
    for ch in sp["chars"]:
        trace.append((ch[0], ch[1], ch[2][0], ch[2][1], sp["font"]))


def has_glyph_at(ox: float, oy: float) -> tuple | None:
    for u, g, tx, ty, fn in trace:
        if abs(tx - ox) < 0.05 and abs(ty - oy) < 0.05:
            return (chr(u), g, fn)
    return None


def scan(flags: int | None, label: str) -> None:
    kw = {} if flags is None else {"flags": flags}
    rd = page.get_text("rawdict", clip=fitz.Rect(70, 445, 560, 535), **kw)
    spaces = real = synth = 0
    samples = []
    text_lines = []
    for b in rd["blocks"]:
        for ln in b.get("lines", []):
            s = ""
            for spn in ln["spans"]:
                for c in spn["chars"]:
                    s += c["c"]
                    if c["c"].isspace() or c["c"] == " ":
                        spaces += 1
                        hit = has_glyph_at(*c["origin"])
                        if hit:
                            real += 1
                        else:
                            synth += 1
                        if len(samples) < 14:
                            bb = c["bbox"]
                            samples.append((round(c["origin"][0], 2), round(c["origin"][1], 2), round(bb[2] - bb[0], 2), spn["font"], "REAL" if hit else "SYNTH", hit))
            text_lines.append(s)
    print(f"[{label}] spaces={spaces} with-trace-glyph={real} without={synth}")
    for s in samples:
        print("   ", s)
    for t in text_lines[:6]:
        print("    line:", repr(t))


scan(None, "default flags")
scan(fitz.TEXTFLAGS_RAWDICT | fitz.TEXT_INHIBIT_SPACES, "RAWDICT|INHIBIT_SPACES")
print("trace space glyphs on page:", sum(1 for t in trace if t[0] in (32, 160)), "of", len(trace))
print("trace space glyph fonts:", sorted({t[4] for t in trace if t[0] in (32, 160)}))

# ---------------------------------------------------------------- probe 3 + 6
hdr("P3 texttrace font names: subset vs donor; P6 donor ToUnicode / W coverage")
for f in page.get_fonts(full=True):
    print("page font:", f)
dobj = doc.xref_object(DONOR, compressed=True)
print("donor obj:", dobj[:400])
m = re.search(r"/DescendantFonts\s*\[?\s*(\d+) 0 R", dobj)
dx = int(m.group(1))
desc = doc.xref_object(dx, compressed=True)
if desc.strip().startswith("["):
    dx = int(re.search(r"(\d+) 0 R", desc).group(1))
    desc = doc.xref_object(dx, compressed=True)
print("descendant:", re.sub(r"/W\s*\[.*", "/W[...]", desc, flags=re.S)[:400])
print("CIDToGIDMap:", doc.xref_get_key(dx, "CIDToGIDMap"), "DW:", doc.xref_get_key(dx, "DW"))
fd = int(re.search(r"/FontDescriptor (\d+) 0 R", desc).group(1))
ff = int(re.search(r"/FontFile2 (\d+) 0 R", doc.xref_object(fd, compressed=True)).group(1))
data = doc.xref_stream(ff)
tt = TTFont(io.BytesIO(data), lazy=True)
cmap = tt.getBestCmap()
order = tt.getGlyphOrder()
gid = {c: tt.getGlyphID(cmap[ord(c)]) if ord(c) in cmap else None for c in INS}
print("gids in full face:", gid)
upm = tt["head"].unitsPerEm
hmtx = tt["hmtx"]

# ToUnicode parse
tu_x = int(re.search(r"/ToUnicode (\d+) 0 R", dobj).group(1))
tu = doc.xref_stream(tu_x).decode("latin-1")
mapping: dict[int, str] = {}
for blk in re.findall(r"beginbfchar(.*?)endbfchar", tu, re.S):
    for a, b_ in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
        mapping[int(a, 16)] = bytes.fromhex(b_).decode("utf-16-be", "replace")
for blk in re.findall(r"beginbfrange(.*?)endbfrange", tu, re.S):
    for a, b_, c in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
        lo, hi, base = int(a, 16), int(b_, 16), int(c, 16)
        for i in range(lo, hi + 1):
            mapping[i] = chr(base + i - lo)
    for a, b_, arr in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", blk, re.S):
        lo = int(a, 16)
        for i, h in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", arr)):
            mapping[lo + i] = bytes.fromhex(h).decode("utf-16-be", "replace")
print("donor ToUnicode entries:", len(mapping), "of", len(order), "glyphs")
# reverse uniqueness
rev: dict[str, list[int]] = {}
for k, v in mapping.items():
    rev.setdefault(v, []).append(k)

# /W parse
wraw = doc.xref_get_key(dx, "W")
wtxt = wraw[1]
if wraw[0] == "xref":
    wtxt = doc.xref_object(int(wraw[1].split()[0]), compressed=True)
widths: dict[int, float] = {}
toks = re.findall(r"\[|\]|-?[\d.]+", wtxt)
i = 1 if toks and toks[0] == "[" else 0
while i < len(toks) and toks[i] != "]":
    c0 = int(float(toks[i]))
    if toks[i + 1] == "[":
        j = i + 2
        k = 0
        while toks[j] != "]":
            widths[c0 + k] = float(toks[j])
            k += 1
            j += 1
        i = j + 1
    else:
        c1 = int(float(toks[i + 1]))
        for c in range(c0, c1 + 1):
            widths[c] = float(toks[i + 2])
        i += 3
dw = doc.xref_get_key(dx, "DW")
dwv = float(dw[1]) if dw[0] not in ("null",) else 1000.0
print("W entries:", len(widths), "DW:", dwv)
for c in INS:
    g = gid[c]
    if g is None:
        print(f"  {c}: not in cmap")
        continue
    adv = hmtx[order[g]][0] * 1000 / upm
    print(f"  {c} gid={g} ToUnicode={mapping.get(g)!r} ok={mapping.get(g) == c} "
          f"reverse-unique={len(rev.get(c, [])) == 1} ({rev.get(c)}) W={widths.get(g, 'DW')} hmtx1000={adv:.1f}")

# live extraction + texttrace names with the donor showing all inserted CIDs
copy3 = f"{outdir}/p3.pdf"
shutil.copyfile(src, copy3)
d3 = fitz.open(copy3)
p3 = d3[0]
d3.xref_set_key(p3.xref, "Resources/Font/FDonor", f"{DONOR} 0 R")
cx = p3.get_contents()[0]
st = d3.xref_stream(cx)
old = b"BT/F2 14.04 Tf 1 0 0 1 511.08 378.89 Tm[<00AE00A8>]TJ ET"
assert st.count(old) == 1
hexs = "".join(f"{gid[c]:04X}" for c in INS)
new = f"BT/FDonor 14.04 Tf 1 0 0 1 300 100 Tm[<{hexs}>]TJ ET ".encode() + old
d3.update_stream(cx, st.replace(old, new))
p3 = d3[0]
names = {}
for sp in p3.get_texttrace():
    names.setdefault(sp["font"], 0)
    names[sp["font"]] += len(sp["chars"])
print("texttrace font names -> glyph count:", names)
got = p3.get_text("text", clip=fitz.Rect(290, 842.04 - 100 - 16, 560, 842.04 - 100 + 6)).strip()
print("extracted donor text:", repr(got), "equal:", got == INS)
dspans = [(s["font"], s["text"]) for b in p3.get_text("dict", clip=fitz.Rect(290, 726, 560, 748))["blocks"] for ln in b.get("lines", []) for s in ln["spans"]]
print("dict span fonts for donor show:", dspans)
print("trace donor glyphs:", [(chr(c[0]), c[1]) for sp in p3.get_texttrace() if abs(sp["chars"][0][2][1] - 742.04) < 1 for c in sp["chars"]])
