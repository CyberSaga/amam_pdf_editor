"""S0-P13: level-wise vectorised CTM for any q depth, same arithmetic order as the Python loop (bit-equal).
Usage: python p13_ctm_levels.py <pdf> <page-index> [workers]"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import fitz
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import p1_path_stage as P  # noqa: E402

RANK_CAP = 64


def compose(m, cur):
    """m then cur, written exactly as ctm_loop does."""
    a, b, c, d, e, f = (m[:, k] for k in range(6))
    A, B, C, D, E, F = (cur[:, k] for k in range(6))
    return np.stack([a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F], axis=1)


def ctm_levels(ops, vals, nb, cnt):
    st = np.flatnonzero((ops == P.OP["q"]) | (ops == P.OP["Q"]) | (ops == P.OP["cm"]))
    kinds = ops[st]
    q, Q, cm = kinds == P.OP["q"], kinds == P.OP["Q"], kinds == P.OP["cm"]
    d = np.cumsum(q.astype(np.int64) - Q)
    n = st.size
    if n and d.min() < 0:
        return None  # Q underflow: the reference loop decides
    pos = np.arange(n)
    mats = np.zeros((n, 6))
    ident = np.array([1.0, 0.0, 0.0, 1.0, 0.0, 0.0])
    base = nb[st] - cnt[st]
    loops = 0
    for lev in range(int(d.max()) + 1 if n else 0):
        opener = np.maximum.accumulate(np.where(q & (d == lev), pos, -1)) if lev else np.full(n, -1)

        def init(idx):
            o = opener[idx]
            out = np.tile(ident, (idx.size, 1))
            ok = o >= 0
            out[ok] = mats[o[ok]]
            return out

        c = np.flatnonzero(cm & (d == lev))
        if c.size:
            m = np.stack([vals[base[c] + k] for k in range(6)], axis=1)
            sid = opener[c]
            newrun = np.concatenate([[True], sid[1:] != sid[:-1]])
            first = np.maximum.accumulate(np.where(newrun, np.arange(c.size), 0))
            rank = np.arange(c.size) - first
            rmax = int(rank.max())
            if rmax <= RANK_CAP:
                res = np.empty((c.size, 6))
                sel = np.flatnonzero(rank == 0)
                res[sel] = compose(m[sel], init(c[sel]))
                for r in range(1, rmax + 1):
                    sel = np.flatnonzero(rank == r)
                    res[sel] = compose(m[sel], res[sel - 1])
                mats[c] = res
            else:  # long cumulative run: plain loop over this level's cm only
                loops += c.size
                i0 = init(c[newrun])
                starts = np.flatnonzero(newrun)
                run_of = np.cumsum(newrun) - 1
                cur = None
                for j in range(c.size):
                    if newrun[j]:
                        cur = tuple(i0[run_of[j]])
                    a, bb, cc, dd, e, f = m[j]
                    A, B, C, D, E, F = cur
                    cur = (a * A + bb * C, a * B + bb * D, cc * A + dd * C, cc * B + dd * D, e * A + f * C + E, e * B + f * D + F)
                    mats[c[j]] = cur
                del starts
        # readers of this level: Q that returns to it, q that copies it
        rd = np.flatnonzero((Q & (d == lev)) | (q & (d == lev + 1)))
        if rd.size:
            lastcm = np.maximum.accumulate(np.where(cm & (d == lev), pos, -1))[rd]
            # opener of the level-lev scope the reader sits in
            o = opener[rd]
            out = init(rd)
            ok = lastcm > o
            out[ok] = mats[lastcm[ok]]
            mats[rd] = out
    return st, mats, loops


if __name__ == "__main__":
    doc = fitz.open(sys.argv[1])
    data = doc[int(sys.argv[2])].read_contents()
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    vals, ops, nb = P.tokenize_all(data, workers)
    cnt = nb - np.concatenate([[0], nb[:-1]])
    t = time.perf_counter()
    st, mats, loops = ctm_levels(ops, vals, nb, cnt)
    t_lv = time.perf_counter() - t
    t = time.perf_counter()
    st2, ref = P.ctm_loop(ops, vals, nb, cnt)
    t_loop = time.perf_counter() - t
    print(f"{len(data) / 1e6:.1f} MB, structural ops {st.size:,}; levels {t_lv:.3f}s (looped cm {loops:,}), reference loop {t_loop:.2f}s")
    print("bit-equal:", bool(np.array_equal(st, st2) and np.array_equal(mats, ref)))
