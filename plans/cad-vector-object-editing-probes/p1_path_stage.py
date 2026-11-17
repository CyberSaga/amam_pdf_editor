"""S0-P1/P5: prototype path stage after the numpy tokenizer, plus click and marquee query timing.
Probe only: no strings/comments/inline images, no clip, no dash, no colour state. Usage: python p1_path_stage.py <sample.pdf> [workers]"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_numpy_tokenizer as T  # noqa: E402


def code(s: bytes) -> int:
    return int.from_bytes(s.ljust(3, b"\0"), "little")


OP = {n: code(n.encode()) for n in "m l c v y h re S s f F f* B B* b b* n q Q cm".split()}
PAINT_CODES = np.array([OP[n] for n in "S s f F f* B B* b b* n".split()], dtype=np.uint32)


def tokenize_all(data: bytes, workers: int, chunk: int = 1_000_000):
    buf = np.frombuffer(data, dtype=np.uint8)
    cuts = [0]
    p = chunk
    while p < buf.size:
        while p > cuts[-1] and T.cls[buf[p]] == 1:
            p -= 1
        cuts.append(p)
        p += chunk
    cuts.append(buf.size)
    spans = list(zip(cuts[:-1], cuts[1:]))
    if workers > 1:
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(lambda ab: T.tokenize(buf[ab[0] : ab[1]]), spans))
    else:
        res = [T.tokenize(buf[a:b]) for a, b in spans]
    vals = np.concatenate([r[0] for r in res])
    ops = np.concatenate([r[1] for r in res])
    off = np.cumsum([0] + [r[0].size for r in res[:-1]])
    nb = np.concatenate([r[2] + o for r, o in zip(res, off)])
    return vals, ops, nb


def ctm_loop(ops, vals, nb, cnt):
    """Reference: CTM after every q/Q/cm op by a Python loop. Returns (positions, matrices)."""
    st = np.flatnonzero((ops == OP["q"]) | (ops == OP["Q"]) | (ops == OP["cm"]))
    mats = np.empty((st.size, 6))
    cur = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack = []
    kinds = ops[st]
    for k in range(st.size):
        kd = kinds[k]
        if kd == OP["q"]:
            stack.append(cur)
        elif kd == OP["Q"]:
            if stack:
                cur = stack.pop()
        else:
            i = st[k]
            b = nb[i] - cnt[i]
            a, bb, c, d, e, f = vals[b : b + 6]
            A, B, C, D, E, F = cur
            cur = (a * A + bb * C, a * B + bb * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)
        mats[k] = cur
    return st, mats


def ctm_fast(ops, vals, nb, cnt):
    """Vectorised when depth <= 1 and every cm directly follows a q (CAD pattern); else None."""
    st = np.flatnonzero((ops == OP["q"]) | (ops == OP["Q"]) | (ops == OP["cm"]))
    kinds = ops[st]
    isq, isQ, iscm = kinds == OP["q"], kinds == OP["Q"], kinds == OP["cm"]
    depth = np.cumsum(isq.astype(np.int64) - isQ)
    if depth.size and (depth.max() > 1 or depth.min() < 0):
        return None
    prev_is_q = np.concatenate([[False], isq[:-1]])
    if np.any(iscm & ~prev_is_q):
        return None
    mats = np.zeros((st.size, 6))
    mats[:, 0] = 1.0
    mats[:, 3] = 1.0
    ci = np.flatnonzero(iscm)
    base = nb[st[ci]] - cnt[st[ci]]
    for k in range(6):
        mats[ci, k] = vals[base + k]
    # a q after the cm's own q: matrix of an entry stays identity unless it is a cm; Q/q entries identity
    # but entries after cm inside the block keep the cm matrix until Q: propagate cm matrix over following non-Q entries
    owner = np.where(iscm, np.arange(st.size), -1)
    owner = np.maximum.accumulate(owner)
    # reset at Q (and at q): an entry whose last cm is before the latest Q/q is identity
    resetpos = np.where(isq | isQ, np.arange(st.size), -1)
    resetpos = np.maximum.accumulate(resetpos)
    valid = owner > resetpos
    out = np.zeros((st.size, 6))
    out[:, 0] = 1.0
    out[:, 3] = 1.0
    out[valid] = mats[owner[valid]]
    return st, out


def build(vals, ops, nb, fast=True):
    prev_nb = np.concatenate([[0], nb[:-1]])
    cnt = nb - prev_nb
    t0 = time.perf_counter()
    r = ctm_fast(ops, vals, nb, cnt) if fast else None
    how = "fast"
    if r is None:
        r = ctm_loop(ops, vals, nb, cnt)
        how = "loop"
    st, mats = r
    t_ctm = time.perf_counter() - t0

    t0 = time.perf_counter()
    cons_mask = np.isin(ops, [OP[k] for k in ("m", "l", "c", "v", "y", "h", "re")])
    cons = np.flatnonzero(cons_mask)
    paint = np.flatnonzero(np.isin(ops, PAINT_CODES))
    kind = ops[cons]
    base = nb[cons] - cnt[cons]
    nc = cnt[cons]

    def arg(k):
        ok = nc > k
        out = np.full(cons.size, np.nan)
        out[ok] = vals[base[ok] + k]
        return out

    a = [arg(k) for k in range(6)]
    ex = np.where(kind == OP["c"], a[4], np.where((kind == OP["v"]) | (kind == OP["y"]), a[2], a[0]))
    ey = np.where(kind == OP["c"], a[5], np.where((kind == OP["v"]) | (kind == OP["y"]), a[3], a[1]))
    start_flag = (kind == OP["m"]) | (kind == OP["re"])
    sidx = np.maximum.accumulate(np.where(start_flag, np.arange(cons.size), -1))
    sx, sy = ex[sidx], ey[sidx]
    is_h = kind == OP["h"]
    ex = np.where(is_h, sx, ex)
    ey = np.where(is_h, sy, ey)
    px = np.concatenate([[0.0], ex[:-1]])
    py = np.concatenate([[0.0], ey[:-1]])
    pid_of_op = np.searchsorted(paint, cons)  # paints before => path id

    xs0, ys0, xs1, ys1, pids = [], [], [], [], []

    def add(ax, ay, bx_, by_, pp):
        xs0.append(ax)
        ys0.append(ay)
        xs1.append(bx_)
        ys1.append(by_)
        pids.append(pp)

    m = (kind == OP["l"]) | is_h & ((px != sx) | (py != sy))
    add(px[m], py[m], ex[m], ey[m], pid_of_op[m])
    m = kind == OP["re"]
    x, y, w, h = a[0][m], a[1][m], a[2][m], a[3][m]
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        add(p0[0], p0[1], p1[0], p1[1], pid_of_op[m])
    # curves
    cm_ = (kind == OP["c"]) | (kind == OP["v"]) | (kind == OP["y"])
    ci = np.flatnonzero(cm_)
    if ci.size:
        k = kind[ci]
        P0x, P0y = px[ci], py[ci]
        P1x = np.where(k == OP["c"], a[0][ci], np.where(k == OP["v"], P0x, a[0][ci]))
        P1y = np.where(k == OP["c"], a[1][ci], np.where(k == OP["v"], P0y, a[1][ci]))
        P2x = np.where(k == OP["c"], a[2][ci], np.where(k == OP["v"], a[0][ci], a[2][ci]))
        P2y = np.where(k == OP["c"], a[3][ci], np.where(k == OP["v"], a[1][ci], a[3][ci]))
        P3x, P3y = ex[ci], ey[ci]
        dd = np.maximum(np.hypot(P0x - 2 * P1x + P2x, P0y - 2 * P1y + P2y), np.hypot(P1x - 2 * P2x + P3x, P1y - 2 * P2y + P3y))
        nseg = np.clip(np.ceil(np.sqrt(0.75 * dd / 0.01)).astype(np.int64), 1, 256)
        cpid = pid_of_op[ci]
        for n in np.unique(nseg):
            sel = nseg == n
            tt = np.linspace(0.0, 1.0, int(n) + 1)[:, None]
            u = 1 - tt
            bx = u**3 * P0x[sel] + 3 * u**2 * tt * P1x[sel] + 3 * u * tt**2 * P2x[sel] + tt**3 * P3x[sel]
            by = u**3 * P0y[sel] + 3 * u**2 * tt * P1y[sel] + 3 * u * tt**2 * P2y[sel] + tt**3 * P3y[sel]
            add(bx[:-1].ravel(), by[:-1].ravel(), bx[1:].ravel(), by[1:].ravel(), np.broadcast_to(cpid[sel], bx[:-1].shape).ravel())
    X0, Y0, X1, Y1, PID = (np.concatenate(v) for v in (xs0, ys0, xs1, ys1, pids))
    # CTM per segment through its path's first construction op position
    # matrix per path: state entry preceding the path's first construction op
    first_cons = np.full(paint.size + 1, -1, dtype=np.int64)
    first_cons[pid_of_op[::-1]] = cons[::-1]
    has = first_cons >= 0
    ent = np.searchsorted(st, np.where(has, first_cons, 0)) - 1
    M = np.zeros((paint.size + 1, 6))
    M[:, 0] = 1.0
    M[:, 3] = 1.0
    ok = has & (ent >= 0)
    M[ok] = mats[ent[ok]]
    Ms = M[PID]
    x0 = Ms[:, 0] * X0 + Ms[:, 2] * Y0 + Ms[:, 4]
    y0 = Ms[:, 1] * X0 + Ms[:, 3] * Y0 + Ms[:, 5]
    x1 = Ms[:, 0] * X1 + Ms[:, 2] * Y1 + Ms[:, 4]
    y1 = Ms[:, 1] * X1 + Ms[:, 3] * Y1 + Ms[:, 5]
    order = np.argsort(PID, kind="stable")
    seg = np.stack([x0, y0, x1, y1], axis=1)[order]
    PID = PID[order]
    t_geom = time.perf_counter() - t0
    return seg, PID, paint.size, how, t_ctm, t_geom


def click_query(seg, pid, npaths, x, y, tol):
    """Paths whose nearest segment is within tol of (x, y)."""
    xmin = np.minimum(seg[:, 0], seg[:, 2]) - tol
    xmax = np.maximum(seg[:, 0], seg[:, 2]) + tol
    ymin = np.minimum(seg[:, 1], seg[:, 3]) - tol
    ymax = np.maximum(seg[:, 1], seg[:, 3]) + tol
    cand = np.flatnonzero((xmin <= x) & (x <= xmax) & (ymin <= y) & (y <= ymax))
    s = seg[cand]
    dx, dy = s[:, 2] - s[:, 0], s[:, 3] - s[:, 1]
    L = dx * dx + dy * dy
    t = np.where(L > 0, ((x - s[:, 0]) * dx + (y - s[:, 1]) * dy) / np.where(L > 0, L, 1), 0.0)
    t = np.clip(t, 0, 1)
    d = np.hypot(s[:, 0] + t * dx - x, s[:, 1] + t * dy - y)
    return np.unique(pid[cand[d <= tol]])


def marquee_touch(seg, pid, rect):
    x0, y0, x1, y1 = rect
    xmin = np.minimum(seg[:, 0], seg[:, 2])
    xmax = np.maximum(seg[:, 0], seg[:, 2])
    ymin = np.minimum(seg[:, 1], seg[:, 3])
    ymax = np.maximum(seg[:, 1], seg[:, 3])
    cand = np.flatnonzero((xmax >= x0) & (xmin <= x1) & (ymax >= y0) & (ymin <= y1))
    s = seg[cand]
    # Liang-Barsky
    dx, dy = s[:, 2] - s[:, 0], s[:, 3] - s[:, 1]
    t0 = np.zeros(cand.size)
    t1 = np.ones(cand.size)
    alive = np.ones(cand.size, dtype=bool)
    for p, q in ((-dx, s[:, 0] - x0), (dx, x1 - s[:, 0]), (-dy, s[:, 1] - y0), (dy, y1 - s[:, 1])):
        par = p == 0
        alive &= ~(par & (q < 0))
        with np.errstate(divide="ignore", invalid="ignore"):
            r = q / p
        t0 = np.where(~par & (p < 0), np.maximum(t0, r), t0)
        t1 = np.where(~par & (p > 0), np.minimum(t1, r), t1)
    alive &= t0 <= t1
    return np.unique(pid[cand[alive]])


def timed(label, fn, reps=5):
    best = 1e9
    for _ in range(reps):
        t = time.perf_counter()
        r = fn()
        best = min(best, time.perf_counter() - t)
    print(f"  {label}: {best*1000:.1f} ms (result {len(r)})")
    return r


if __name__ == "__main__":
    doc = fitz.open(sys.argv[1])
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    data = b"".join(doc.xref_stream(x) for x in doc[0].get_contents())
    t = time.perf_counter()
    vals, ops, nb = tokenize_all(data, workers)
    t_tok = time.perf_counter() - t
    seg, pid, npaths, how, t_ctm, t_geom = build(vals, ops, nb)
    print(f"workers {workers}: tokenize {t_tok:.2f}s, ctm({how}) {t_ctm:.2f}s, geometry {t_geom:.2f}s, total {t_tok+t_ctm+t_geom:.2f}s")
    print(f"paints {npaths:,}, segments {seg.shape[0]:,}, seg array {seg.nbytes/1e6:.0f} MB")
    t = time.perf_counter()
    r2 = build(vals, ops, nb, fast=False)
    print(f"loop CTM reference: {r2[4]:.2f}s; segments equal: {np.allclose(r2[0], seg)}")
    cx, cy = float(np.median(seg[:, 0])), float(np.median(seg[:, 1]))
    print("click / marquee query timing (page-wide candidates):")
    timed("click", lambda: click_query(seg, pid, npaths, cx, cy, 1.5))
    timed("touch marquee 100x100", lambda: marquee_touch(seg, pid, (cx - 50, cy - 50, cx + 50, cy + 50)))
    xs = seg[:, [0, 2]]
    ys = seg[:, [1, 3]]
    big = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
    timed("touch marquee whole page", lambda: marquee_touch(seg, pid, big), reps=2)
    print("bbox of drawing:", [round(v, 1) for v in big])
