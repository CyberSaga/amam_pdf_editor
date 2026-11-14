from __future__ import annotations

import re
import sys
from collections import Counter

import fitz

path, out = sys.argv[1], sys.argv[2]
doc = fitz.open(path)
page = doc[0]
lines: list[str] = []
w = lines.append

cat = doc.pdf_catalog()
w(f"catalog: {doc.xref_object(cat, compressed=True)[:400]}")
w(f"producer/creator: {doc.metadata.get('producer')} | {doc.metadata.get('creator')}")
w(f"page obj: {doc.xref_object(page.xref, compressed=True)[:600]}")
w("")
for f in page.get_fonts(full=True):
    xref = f[0]
    w(f"FONT {f}")
    obj = doc.xref_object(xref, compressed=True)
    w(f"  obj: {obj[:500]}")
    m = re.search(r"/DescendantFonts\s*\[\s*(\d+) 0 R", obj) or re.search(r"/DescendantFonts (\d+) 0 R", obj)
    if m:
        dx = int(m.group(1))
        dobj = doc.xref_object(dx, compressed=True)
        if dobj.strip().startswith("["):
            m2 = re.search(r"(\d+) 0 R", dobj)
            dx = int(m2.group(1))
            dobj = doc.xref_object(dx, compressed=True)
        w(f"  desc[{dx}]: {dobj[:700]}")
        m3 = re.search(r"/FontDescriptor (\d+) 0 R", dobj)
        if m3:
            fd = doc.xref_object(int(m3.group(1)), compressed=True)
            w(f"  fd: {fd[:500]}")
            m4 = re.search(r"/FontFile\d? (\d+) 0 R", fd)
            if m4:
                data = doc.xref_stream(int(m4.group(1)))
                w(f"  fontfile bytes: {len(data)}")
                try:
                    ff = fitz.Font(fontbuffer=data)
                    w(f"  fontfile name={ff.name} glyphs={ff.glyph_count}")
                    probe = "包含測試點位範本（）()請文件"
                    w("  has_glyph: " + " ".join(f"{c}:{ff.has_glyph(ord(c))}" for c in probe))
                except Exception as e:  # noqa: BLE001
                    w(f"  fontfile open failed: {e}")
    mt = re.search(r"/ToUnicode (\d+) 0 R", obj)
    if mt:
        tu = doc.xref_stream(int(mt.group(1))).decode("latin-1")
        w(f"  ToUnicode len={len(tu)} bfchar={tu.count('beginbfchar')} bfrange={tu.count('beginbfrange')}")
        w("  " + tu[:300].replace("\n", " | "))
w("")
raw = b"".join(doc.xref_stream(x) for x in page.get_contents())
txt = raw.decode("latin-1")
w(f"content streams: {page.get_contents()} total bytes {len(raw)}")
ops = re.findall(r"(?<![A-Za-z'\"*])(BT|ET|Tj|TJ|Td|TD|Tm|T\*|Tf|Tc|Tw|Tz|TL|Tr|Ts|BDC|BMC|EMC|cm|q|Q|re|W\*?|n|Do|'|\")(?![A-Za-z])", txt)
w(f"op counts: {dict(Counter(ops))}")
w("")
w("---- stream head (first 1500 chars) ----")
w(txt[:1500])
# locate the item-1 region: find Tm/Td with y ~ 842.04-463.15 = 378.89
for key in ("378.8", "378.9", "357.8", "357.9", "336.8", "336.9", "315.8", "315.9"):
    for m in re.finditer(re.escape(key), txt):
        s = max(0, m.start() - 250)
        w(f"---- around '{key}' @ {m.start()} ----")
        w(txt[s : m.start() + 900])
        break
open(out, "w", encoding="utf-8").write("\n".join(lines))
print("ok", len(lines))
