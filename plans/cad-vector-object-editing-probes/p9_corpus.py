"""S0-P9 (first cut): per file, pages with BI, path-paint op counts, stream sizes. Usage: python p9_corpus.py <dir> [file ...]"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import fitz

PAINT = re.compile(rb"(?<![^\s\]\)>])(S|s|f|F|f\*|B|B\*|b|b\*)(?![^\s\[\(<%/])")
BI = re.compile(rb"(?<![^\s>\]\)])BI(?![^\s/<\[])")
GS = re.compile(rb"\sgs(?![^\s])")
ROOT = Path(sys.argv[1])
files = sorted(ROOT.glob("*.pdf"))
if len(sys.argv) > 2:
    files = [ROOT / n for n in sys.argv[2:]]
print("file | pages | bytes | pages_with_BI | paint_ops | gs_pages | max_stream_bytes | scan_s")
for f in files:
    try:
        d = fitz.open(f)
    except Exception as e:  # noqa: BLE001
        print(f.name, "open failed", type(e).__name__)
        continue
    if d.is_encrypted and not d.authenticate(""):
        print(f.name, "encrypted")
        continue
    t = time.perf_counter()
    bi_pages = gs_pages = paints = biggest = total = 0
    n = min(d.page_count, 60)
    for i in range(n):
        data = b"".join(d.xref_stream(x) or b"" for x in d[i].get_contents())
        total += len(data)
        biggest = max(biggest, len(data))
        paints += len(PAINT.findall(data))
        bi_pages += 1 if BI.search(data) else 0
        gs_pages += 1 if GS.search(data) else 0
    print(f"{f.name} | {d.page_count}(scanned {n}) | {f.stat().st_size} | {bi_pages} | {paints} | {gs_pages} | {biggest} | {time.perf_counter() - t:.2f}")
