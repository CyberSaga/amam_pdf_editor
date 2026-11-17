"""S0-P14: F with a mask pass instead of admit-or-G. Blank strings, hex strings, dictionaries, comments and whole
BT..ET objects (offsets unchanged), tokenise the copy, level-wise CTM, geometry. Reports time per stage and the
working-set peak. Probe only: names are not yet a token class. Usage: python p14_masked_f.py <pdf> <page-index> [workers] [chunk-bytes]"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import sys
import time
from pathlib import Path

import fitz
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import p1_path_stage as P  # noqa: E402
import p13_ctm_levels as L  # noqa: E402
from p11_inline_image_ladder import skip_string  # noqa: E402

HOP = re.compile(rb"[(<%]|(?<![^\s\[\]<>(){}/%])BT(?=[\s/\[(<])")
IN_BT = re.compile(rb"[(<%]|(?<![^\s\[\]<>(){}/%])ET(?=[\s/\[\]<>(){}%]|$)")


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [
        (n, ctypes.c_size_t)
        for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                  "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")
    ]


def peak_mb() -> float:
    k = ctypes.WinDLL("kernel32")
    ps = ctypes.WinDLL("psapi")
    k.GetCurrentProcess.restype = wt.HANDLE
    ps.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    ps.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.PeakWorkingSetSize / 1e6


def special_end(buf: bytes, j: int) -> int:
    c = buf[j]
    if c == 0x28:
        return skip_string(buf, j)
    if c == 0x25:
        m = re.compile(rb"[\r\n]").search(buf, j)
        return m.start() if m else len(buf)
    if buf[j + 1 : j + 2] == b"<":  # dictionary: to the matching >>
        depth, i = 0, j
        pat = re.compile(rb"<<|>>|\(")
        while True:
            m = pat.search(buf, i)
            if not m:
                return len(buf)
            if m.group() == b"(":
                i = skip_string(buf, m.start())
                continue
            depth += 1 if m.group() == b"<<" else -1
            i = m.end()
            if depth == 0:
                return i
    e = buf.find(b">", j)
    return e + 1 if e >= 0 else len(buf)


def mask_spans(buf: bytes):
    spans = []
    i, n = 0, len(buf)
    while i < n:
        m = HOP.search(buf, i)
        if not m:
            break
        j = m.start()
        if buf[j] != 0x42:  # not BT
            e = special_end(buf, j)
        else:
            e = m.end()
            while True:
                m2 = IN_BT.search(buf, e)
                if not m2:
                    e = n
                    break
                if buf[m2.start()] == 0x45:
                    e = m2.end()
                    break
                e = special_end(buf, m2.start())
        spans.append((j, e))
        i = e
    return spans


if __name__ == "__main__":
    doc = fitz.open(sys.argv[1])
    data = doc[int(sys.argv[2])].read_contents()
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    base = peak_mb()
    t0 = time.perf_counter()
    spans = mask_spans(data)
    arr = np.frombuffer(data, dtype=np.uint8).copy()
    for a, b in spans:
        arr[a:b] = 32
    masked = arr.tobytes()
    t_mask = time.perf_counter() - t0
    t0 = time.perf_counter()
    chunk = int(sys.argv[4]) if len(sys.argv) > 4 else 1_000_000
    vals, ops, nb = P.tokenize_all(masked, workers, chunk)
    t_tok = time.perf_counter() - t0
    del arr, masked
    peak_tok = peak_mb()
    P.ctm_fast = lambda *a: L.ctm_levels(*a)[:2]
    seg, pid, npaths, how, t_ctm, t_geom = P.build(vals, ops, nb)
    total = t_mask + t_tok + t_ctm + t_geom
    print(f"{len(data) / 1e6:.1f} MB, {workers} workers: mask {t_mask:.2f}s ({len(spans):,} spans, {sum(b - a for a, b in spans) / 1e6:.2f} MB blanked), "
          f"tokenize {t_tok:.2f}s, ctm {t_ctm:.2f}s, geometry {t_geom:.2f}s, total {total:.2f}s")
    print(f"paints {npaths:,}, segments {seg.shape[0]:,}; working-set peak after tokenize {peak_tok:.0f} MB, after build {peak_mb():.0f} MB (baseline before scan {base:.0f} MB)")
