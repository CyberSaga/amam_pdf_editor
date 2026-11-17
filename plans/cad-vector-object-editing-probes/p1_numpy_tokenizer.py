"""S0-P1: prototype chunked numpy tokenizer (accelerator F, tokens + numbers + operator codes only).
Ignores strings/comments/inline images (probe only). Usage: python p1_numpy_tokenizer.py <sample.pdf> [chunk_mb]"""
from __future__ import annotations

import sys
import time
import tracemalloc

import fitz
import numpy as np

WS = b" \t\r\n\x0c\x00"
DELIM = b"()<>[]{}/%"
cls = np.ones(256, dtype=np.uint8)  # 1 = regular
for b in WS + DELIM:
    cls[b] = 0
POW10 = 10.0 ** np.arange(0, 40)


def tokenize(buf: np.ndarray):
    """Return (values float64 for numeric tokens, op codes for alpha tokens) in stream order, plus counts."""
    reg = cls[buf].astype(bool)
    prev = np.empty_like(reg)
    prev[0] = False
    prev[1:] = reg[:-1]
    nxt = np.empty_like(reg)
    nxt[-1] = False
    nxt[:-1] = reg[1:]
    starts = np.flatnonzero(reg & ~prev)
    ends = np.flatnonzero(reg & ~nxt) + 1
    first = buf[starts]
    alpha = ((first | 32) >= 97) & ((first | 32) <= 122) | (first == 39) | (first == 34) | (first == 42)
    # operator code: up to 3 bytes packed
    numbefore = np.cumsum(~alpha)[alpha]
    ops_s = starts[alpha]
    ops_len = (ends - starts)[alpha]
    b0 = buf[ops_s].astype(np.uint32)
    b1 = np.where(ops_len > 1, buf[np.minimum(ops_s + 1, buf.size - 1)], 0).astype(np.uint32)
    b2 = np.where(ops_len > 2, buf[np.minimum(ops_s + 2, buf.size - 1)], 0).astype(np.uint32)
    opcode = b0 | (b1 << 8) | (b2 << 16)
    # numbers
    ns = starts[~alpha]
    ne = ends[~alpha]
    if ns.size == 0:
        return np.empty(0), opcode, numbefore
    # byte-level view of numeric tokens only
    lens = ne - ns
    tot = int(lens.sum())
    tok_of = np.repeat(np.arange(ns.size), lens)
    off = np.arange(tot) - np.repeat(np.cumsum(lens) - lens, lens)
    byts = buf[np.repeat(ns, lens) + off]
    isd = (byts >= 48) & (byts <= 57)
    isdot = byts == 46
    neg = byts[np.cumsum(lens) - lens] == 45
    dv = np.where(isd, byts.astype(np.int64) - 48, 0)
    cd = np.cumsum(isd)
    tstart = np.cumsum(lens) - lens
    base = np.where(tstart > 0, cd[tstart - 1], 0)
    td = np.add.reduceat(isd.astype(np.int64), tstart)
    r = cd - base[tok_of] - 1  # rank from start among digits (valid at digit bytes)
    exp = td[tok_of] - 1 - r
    contrib = np.where(isd, dv * POW10[np.clip(exp, 0, 39)], 0.0)
    ival = np.add.reduceat(contrib, tstart)
    cdot = np.cumsum(isdot)
    dbase = np.where(tstart > 0, cdot[tstart - 1], 0)
    hasdot = (cdot - dbase[tok_of]) > 0
    after = np.where(isd & hasdot, 1, 0)
    fd = np.add.reduceat(after, tstart)
    val = ival / POW10[fd]
    return np.where(neg, -val, val), opcode, numbefore


def run(data: bytes, chunk: int):
    buf_all = np.frombuffer(data, dtype=np.uint8)
    pos = 0
    nnum = nop = 0
    t_nums = []
    while pos < buf_all.size:
        end = min(pos + chunk, buf_all.size)
        if end < buf_all.size:
            while end > pos and cls[buf_all[end]] == 1:  # cut at a non-regular byte
                end -= 1
        vals, ops, _ = tokenize(buf_all[pos:end])
        nnum += vals.size
        nop += ops.size
        t_nums.append(vals[:3])
        pos = end
    return nnum, nop


if __name__ == "__main__":
    doc = fitz.open(sys.argv[1])
    data = b"".join(doc.xref_stream(x) for x in doc[0].get_contents())
    mb = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    # correctness on a slice
    sample = data[1000:5000]
    sample = sample[sample.index(b"\n") :]
    vals, _, _ = tokenize(np.frombuffer(sample, dtype=np.uint8))
    ref = [float(t) for t in sample.split() if t[:1] in b"-+.0123456789"]
    ok = len(ref) == vals.size and np.allclose(vals, ref, rtol=0, atol=1e-9)
    print("correct on slice:", ok, vals.size, len(ref))
    if len(sys.argv) < 4:
        tracemalloc.start()
    t = time.perf_counter()
    n, o = run(data, int(mb * 1e6))
    dt = time.perf_counter() - t
    peak = tracemalloc.get_traced_memory()[1] if tracemalloc.is_tracing() else 0
    print(f"chunk {mb} MB: {n:,} numbers, {o:,} operator tokens in {dt:.2f}s, peak traced {peak/1e6:.0f} MB")
