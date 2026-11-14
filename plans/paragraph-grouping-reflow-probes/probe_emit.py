from __future__ import annotations

import io
import re
import shutil
import sys

import fitz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src, outdir = sys.argv[1], sys.argv[2]

ref = fitz.open(src)
for x in (3861, 3862, 3860, 3859):
    print(x, "S=", ref.xref_get_key(x, "S"), "P=", ref.xref_get_key(x, "P"))
print(3858, "obj:", ref.xref_object(int(ref.xref_get_key(3860, "P")[1].split()[0]), compressed=True)[:200])


def trace(page: fitz.Page) -> list[tuple]:
    out = []
    for span in page.get_texttrace():
        for ch in span["chars"]:
            out.append((span["font"], round(span["size"], 3), ch[0], ch[1], round(ch[2][0], 3), round(ch[2][1], 3)))
    return sorted(out)


copy = f"{outdir}/emit_probe.pdf"
shutil.copyfile(src, copy)
d = fitz.open(copy)
p = d[0]
before_pix = p.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes()
before_trace = trace(p)
cx = p.get_contents()[0]
stream = d.xref_stream(cx).decode("latin-1")
pat = re.compile(r"BT( [\d.]+ Tc)?/(F\d) 14\.04 Tf 1 0 0 1 ([\d.]+) 357\.89 Tm((?: 0 G)*)(\[.*?\])TJ ET")
shows = list(pat.finditer(stream))
print("shows on line 2:", len(shows))
runs = []
for m in shows:
    tc = m.group(1).strip().split()[0] if m.group(1) else "0"
    runs.append(f"{tc} Tc/{m.group(2)} 14.04 Tf 0 g 1 0 0 1 {m.group(3)} 357.89 Tm{m.group(5)}TJ")
out = []
pos = 0
for i, m in enumerate(shows):
    out.append(stream[pos : m.start(5)])
    out.append("[]")
    out.append(stream[m.end(5) : m.end(5) + 2])  # "TJ"
    if i == 0:
        out.append(" " + " ".join(runs))
    pos = m.end(5) + 2
out.append(stream[pos:])
d.update_stream(cx, "".join(out).encode("latin-1"))
p = d[0]
after_pix = p.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes()
after_trace = trace(p)
print("live raster identical:", after_pix == before_pix)
print("live texttrace identical:", after_trace == before_trace, len(before_trace), len(after_trace))
saved = f"{outdir}/emit_probe_saved.pdf"
d.save(saved, garbage=3, deflate=True)
r = fitz.open(saved)
print("reopen raster identical:", r[0].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes() == before_pix)
print("reopen texttrace identical:", trace(r[0]) == before_trace)
print("reopen text equal:", r[0].get_text() == ref[0].get_text())
