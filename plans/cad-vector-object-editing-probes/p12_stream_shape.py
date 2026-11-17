"""S0-P12: (a) F admission: per path-heavy page, which special bytes occur; (b) q/cm/Q stack shape of one page.
Usage: python p12_stream_shape.py admit <pdf>...   |   python p12_stream_shape.py stack <pdf> <page-index>"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import p1_path_stage as P  # noqa: E402

PAINT = re.compile(rb"(?<![^\s\]])(?:S|s|f\*?|F|B\*?|b\*?)(?=[\s]|$)")


def admit(paths: list[str]) -> None:
    tot = heavy = clean = 0
    why: dict[str, int] = {}
    for fp in paths:
        doc = fitz.open(fp)
        for pn in range(len(doc)):
            buf = doc[pn].read_contents()
            tot += 1
            n = len(PAINT.findall(buf))
            if n < 5000:
                continue
            heavy += 1
            has = [ch for ch in "(<%{}" if ch.encode() in buf]
            if b"BT" in buf:
                has.append("BT")
            if b"BI" in buf:
                has.append("BI")
            if not has:
                clean += 1
            key = " ".join(has) or "clean"
            why[key] = why.get(key, 0) + 1
            if n > 300000:
                print(f"  big: {Path(fp).name} p{pn + 1} {len(buf) / 1e6:.1f} MB {n:,} paints: {key}"[:200])
        doc.close()
    print(f"pages {tot}, with >=5000 paints {heavy}, admitted by the byte-class test {clean}")
    for k, v in sorted(why.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>5}  {k}")


def stack(fp: str, pn: int) -> None:
    doc = fitz.open(fp)
    data = doc[pn].read_contents()
    vals, ops, nb = P.tokenize_all(data, 4)
    isq, isQ, iscm = ops == P.OP["q"], ops == P.OP["Q"], ops == P.OP["cm"]
    st = np.flatnonzero(isq | isQ | iscm)
    k = ops[st]
    q, Q, cm = k == P.OP["q"], k == P.OP["Q"], k == P.OP["cm"]
    depth = np.cumsum(q.astype(np.int64) - Q)
    print(f"ops {ops.size:,}; q {q.sum():,} Q {Q.sum():,} cm {cm.sum():,}; depth max {depth.max()} min {depth.min()}")
    d_at_q = depth[q]
    print("q by depth after:", dict(zip(*[a.tolist() for a in np.unique(d_at_q, return_counts=True)])))
    # leaf block: a q whose next structural q/Q is a Q
    qQ = np.flatnonzero(q | Q)
    leaf_q = q[qQ][:-1] & Q[qQ][1:]
    print(f"leaf q..Q blocks {int(leaf_q.sum()):,} of {int(q.sum()):,} q")
    # cm inside leaf blocks: cm whose previous q/Q is a leaf q
    last_qQ = np.maximum.accumulate(np.where(q | Q, np.arange(k.size), -1))
    leaf_idx = np.zeros(k.size, dtype=bool)
    leaf_idx[qQ[:-1][leaf_q]] = True
    cm_pos = np.flatnonzero(cm)
    prev = last_qQ[cm_pos]
    in_leaf = (prev >= 0) & leaf_idx[np.maximum(prev, 0)]
    print(f"cm inside a leaf block {int(in_leaf.sum()):,} of {cm_pos.size:,}; structural ops left for a loop: {int(k.size - 2 * leaf_q.sum() - in_leaf.sum()):,}")
    # cm per leaf block
    owner = prev[in_leaf]
    if owner.size:
        _, c = np.unique(owner, return_counts=True)
        print("cm per leaf block (count: blocks):", dict(zip(*[a.tolist() for a in np.unique(c, return_counts=True)])))
    for ch in "(<%{}[":
        print(f"  byte {ch!r}: {data.count(ch.encode()):,}", end="")
    n_bt = len(re.findall(rb"(?<![^\s])BT(?=\s)", data))
    print(f"\n  BT {n_bt:,}; decoded {len(data) / 1e6:.1f} MB; paints {len(PAINT.findall(data)):,}")
    for m in list(re.finditer(rb"<", data))[:3]:
        print("  '<' context:", data[max(m.start() - 40, 0) : m.start() + 40])


if __name__ == "__main__":
    if sys.argv[1] == "admit":
        admit(sys.argv[2:])
    else:
        stack(sys.argv[2], int(sys.argv[3]))
