"""S0-P15: touch marquee with a bbox-inside fast path (segment test only for paths whose bbox straddles the
rectangle), against the plain segment test. Usage: python p15_marquee_fast.py <pdf> <page-index>"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import fitz
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import p1_path_stage as P  # noqa: E402


def path_boxes(seg, pid, npaths):
    first = np.flatnonzero(np.concatenate([[True], pid[1:] != pid[:-1]]))
    ids = pid[first]
    box = np.full((npaths, 4), np.nan)
    box[ids, 0] = np.minimum.reduceat(np.minimum(seg[:, 0], seg[:, 2]), first)
    box[ids, 1] = np.minimum.reduceat(np.minimum(seg[:, 1], seg[:, 3]), first)
    box[ids, 2] = np.maximum.reduceat(np.maximum(seg[:, 0], seg[:, 2]), first)
    box[ids, 3] = np.maximum.reduceat(np.maximum(seg[:, 1], seg[:, 3]), first)
    start = np.zeros(npaths, dtype=np.int64)
    count = np.zeros(npaths, dtype=np.int64)
    start[ids] = first
    count[ids] = np.diff(np.concatenate([first, [pid.size]]))
    return box, start, count


def marquee_fast(seg, pid, box, start, count, rect):
    x0, y0, x1, y1 = rect
    hit = (box[:, 2] >= x0) & (box[:, 0] <= x1) & (box[:, 3] >= y0) & (box[:, 1] <= y1)
    inside = hit & (box[:, 0] >= x0) & (box[:, 2] <= x1) & (box[:, 1] >= y0) & (box[:, 3] <= y1)
    strad = np.flatnonzero(hit & ~inside)
    if strad.size:
        c = count[strad]
        idx = np.repeat(start[strad], c) + (np.arange(int(c.sum())) - np.repeat(np.cumsum(c) - c, c))
        extra = P.marquee_touch(seg[idx], pid[idx], rect)
    else:
        extra = np.empty(0, dtype=pid.dtype)
    return np.union1d(np.flatnonzero(inside), extra), strad.size


if __name__ == "__main__":
    doc = fitz.open(sys.argv[1])
    data = doc[int(sys.argv[2])].read_contents()
    vals, ops, nb = P.tokenize_all(data, 4)
    seg, pid, npaths, *_ = P.build(vals, ops, nb)
    t = time.perf_counter()
    box, start, count = path_boxes(seg, pid, npaths)
    print(f"path boxes built once in {time.perf_counter() - t:.3f}s")
    lo = np.nanmin(box[:, :2], axis=0)
    hi = np.nanmax(box[:, 2:], axis=0)
    # densest 100x100 cell by path-centre histogram
    cx, cy = (box[:, 0] + box[:, 2]) / 2, (box[:, 1] + box[:, 3]) / 2
    ok = ~np.isnan(cx)
    h, xe, ye = np.histogram2d(cx[ok], cy[ok], bins=[max(int((hi[0] - lo[0]) / 100), 1), max(int((hi[1] - lo[1]) / 100), 1)])
    i, j = np.unravel_index(h.argmax(), h.shape)
    rects = {"dense 100x100": (xe[i], ye[j], xe[i] + 100, ye[j] + 100), "whole page": (lo[0] - 1, lo[1] - 1, hi[0] + 1, hi[1] + 1)}
    for name, r in rects.items():
        best_f = best_p = 9.0
        for _ in range(5):
            t = time.perf_counter()
            a, ns = marquee_fast(seg, pid, box, start, count, r)
            best_f = min(best_f, time.perf_counter() - t)
            t = time.perf_counter()
            b = P.marquee_touch(seg, pid, r)
            best_p = min(best_p, time.perf_counter() - t)
        print(f"{name}: fast {best_f * 1e3:.0f} ms ({a.size:,} paths, {ns:,} straddlers), plain {best_p * 1e3:.0f} ms ({b.size:,}); equal {np.array_equal(a, b)}")
