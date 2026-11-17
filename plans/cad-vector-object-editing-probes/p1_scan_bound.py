"""S0-P1 lower bounds (not the scanner): decode time, token count, pure-Python token loop vs numpy float parse. Usage: python p1_scan_bound.py <sample.pdf>"""
from __future__ import annotations

import re
import sys
import time

import fitz
import numpy as np

doc = fitz.open(sys.argv[1])
t = time.perf_counter()
data = b"".join(doc.xref_stream(x) for x in doc[0].get_contents())
print(f"decode {len(data)/1e6:.1f} MB in {time.perf_counter()-t:.2f}s")

TOK = re.compile(rb"[^\s()<>\[\]{}/%]+")
t = time.perf_counter()
toks = TOK.findall(data)
dt = time.perf_counter() - t
print(f"regex findall: {len(toks):,} tokens in {dt:.2f}s")

# operator tokens = alphabetic-leading
t = time.perf_counter()
ops = [k for k in toks if k[:1].isalpha() or k[:1] in b"'\"*"]
print(f"operator filter: {len(ops):,} ops in {time.perf_counter()-t:.2f}s")

# numeric parse of all numeric tokens via numpy
t = time.perf_counter()
nums = [k for k in toks if k[:1] not in b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'\"*"]
arr = np.array(nums, dtype="S24").astype(np.float64)
print(f"numeric parse: {arr.size:,} numbers in {time.perf_counter()-t:.2f}s")

try:
    import psutil

    print(f"process RSS now {psutil.Process().memory_info().rss/1e6:.0f} MB (peak not tracked)")
except ImportError:
    pass
