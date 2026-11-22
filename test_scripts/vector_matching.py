"""Record matching with a tolerance, without greed (handoff H7, design plan D23 "one tolerance function").

Two coordinates match when they differ by at most ``max(1e-3 pt, 8 * ulp_float32(|x|))``.  Records are
``(tag, coordinates)``: tags (type, colours, ...) must be equal, coordinates match pairwise.

Algorithm: quantise every coordinate to a grid of its tolerance.  A record none of whose coordinates
lies within two tolerances of a cell edge can only match records of its own cell, so its cell is
settled by comparing counts (the multiset comparison).  Every other record goes to component
matching: candidate pairs form a bipartite graph, and each connected component needs a perfect
maximum matching (Hopcroft-Karp).  A component over ``MAX_COMPONENT_EDGES`` candidate edges raises
:class:`AmbiguousFixture`.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Hashable, Sequence
from itertools import product

import numpy as np

K_ULP = 8
BASE_TOLERANCE = 1e-3
MAX_COMPONENT_EDGES = 5000
BUCKET_DIMS = 2  # coordinates that form the grid key

Record = tuple[Hashable, tuple[float, ...]]


class AmbiguousFixture(AssertionError):
    """A component of candidate pairs is too large to be a meaningful fixture."""


def tolerance(x: float) -> float:
    """The one tolerance function: ``max(1e-3, k * ulp_float32(|x|))``, ``k = 8``."""
    ulp = float(np.spacing(np.float32(abs(x))))
    return max(BASE_TOLERANCE, K_ULP * ulp)


def coordinates_match(x: float, y: float) -> bool:
    return abs(x - y) <= max(tolerance(x), tolerance(y))


def records_equal(a: Record, b: Record) -> bool:
    return a[0] == b[0] and len(a[1]) == len(b[1]) and all(coordinates_match(x, y) for x, y in zip(a[1], b[1], strict=True))


def _bucket(rec: Record, width: float) -> tuple[Hashable, tuple[int, ...]]:
    return (rec[0], tuple(math.floor(x / width) for x in rec[1][:BUCKET_DIMS]))


def match_multisets(a: Sequence[Record], b: Sequence[Record]) -> bool:
    """``True`` when the two record lists pair up one to one within the tolerance.

    Candidate pairs come from a grid whose cell is at least the largest tolerance present, searched
    in the neighbouring cells on both sides, so a pair that straddles a cell edge, or a float32
    exponent boundary where the tolerance itself changes, is still a candidate.  Edges are counted
    per component while they are discovered and the cap aborts the search before the graph exists.
    """
    if len(a) != len(b):
        return False
    if not a:
        return True
    width = max(tolerance(x) for rec in (*a, *b) for x in rec[1][:BUCKET_DIMS]) if any(r[1] for r in (*a, *b)) else BASE_TOLERANCE
    index: dict[tuple[Hashable, tuple[int, ...]], list[int]] = defaultdict(list)
    for j, rec in enumerate(b):
        index[_bucket(rec, width)].append(j)
    n_a = len(a)
    parent = list(range(n_a + len(b)))
    edges_of: dict[int, int] = defaultdict(int)  # component root -> candidate edges

    def find(n: int) -> int:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    adj: dict[int, list[int]] = {}
    for i, rec in enumerate(a):
        tag, cell = _bucket(rec, width)
        cand: list[int] = []
        for delta in product((-1, 0, 1), repeat=len(cell)):
            for j in index.get((tag, tuple(c + d for c, d in zip(cell, delta, strict=True))), ()):
                if records_equal(rec, b[j]):
                    cand.append(j)
                    ra, rb = find(i), find(n_a + j)
                    if ra != rb:
                        parent[ra] = rb
                        edges_of[rb] += edges_of.pop(ra, 0)
                    edges_of[rb] += 1
                    if edges_of[rb] > MAX_COMPONENT_EDGES:
                        raise AmbiguousFixture(
                            f"ambiguous fixture: a component has over {MAX_COMPONENT_EDGES} candidate edges"
                        )
        if not cand:
            return False
        adj[i] = cand
    comps: dict[int, tuple[list[int], set[int]]] = {}
    for i, js in adj.items():
        left, right = comps.setdefault(find(i), ([], set()))
        left.append(i)
        right.update(js)
    for left, right in comps.values():
        if len(left) > len(right):
            return False
    # every B record must be matched too: counts are equal, so a perfect matching of A suffices
    return all(_hopcroft_karp(left, {i: adj[i] for i in left}) == len(left) for left, _r in comps.values())


def _hopcroft_karp(left: list[int], adj: dict[int, list[int]]) -> int:
    return len(_max_matching(left, adj))


def unmatched(a: Sequence[Record], b: Sequence[Record], base: float = BASE_TOLERANCE) -> list[Record]:
    """The records of ``a`` left without a partner by a MAXIMUM one-to-one matching against ``b``.

    The same one tolerance function as :func:`match_multisets` with the floor raised to ``base`` (D23: one
    non-greedy matcher; the vendor leg uses 0.3 pt).  Two coordinates match when they differ by at most
    ``max(base, tolerance(x), tolerance(y))``; tags must be equal.  A greedy walk can leave a record
    unmatched although a perfect matching exists (a=[0, 0.55], b=[0.28, 0.05], base 0.3): this cannot.
    Which of several equally large sets of unmatched records is returned is not defined, only their number
    (``|a|`` minus the maximum matching)."""
    if not a:
        return []

    def near(x: float, y: float) -> bool:
        return abs(x - y) <= max(base, tolerance(x), tolerance(y))

    width = max([base, *(tolerance(x) for rec in (*a, *b) for x in rec[1][:BUCKET_DIMS])])
    index: dict[tuple[Hashable, tuple[int, ...]], list[int]] = defaultdict(list)
    for j, rec in enumerate(b):
        index[_bucket(rec, width)].append(j)
    adj: dict[int, list[int]] = {}
    for i, rec in enumerate(a):
        tag, cell = _bucket(rec, width)
        adj[i] = [
            j
            for delta in product((-1, 0, 1), repeat=len(cell))
            for j in index.get((tag, tuple(c + d for c, d in zip(cell, delta, strict=True))), ())
            if len(b[j][1]) == len(rec[1]) and all(near(x, y) for x, y in zip(rec[1], b[j][1], strict=True))
        ]
    matched = _max_matching([i for i in adj if adj[i]], adj)
    return [rec for i, rec in enumerate(a) if i not in matched]


def _max_matching(left: list[int], adj: dict[int, list[int]]) -> dict[int, int]:
    pair_l: dict[int, int] = {}
    pair_r: dict[int, int] = {}
    while True:
        dist: dict[int, int] = {}
        queue: deque[int] = deque()
        for u in left:
            if u not in pair_l:
                dist[u] = 0
                queue.append(u)
        found = False
        while queue:
            u = queue.popleft()
            for v in adj[u]:
                w = pair_r.get(v)
                if w is None:
                    found = True
                elif w not in dist:
                    dist[w] = dist[u] + 1
                    queue.append(w)
        if not found:
            return pair_l
        it = {u: 0 for u in left}
        for u in left:
            if u not in pair_l:
                _augment(u, adj, dist, pair_l, pair_r, it)


def _augment(
    root: int,
    adj: dict[int, list[int]],
    dist: dict[int, int],
    pair_l: dict[int, int],
    pair_r: dict[int, int],
    it: dict[int, int],
) -> bool:
    """Iterative DFS along the layered graph (a recursion would hit the limit on long paths)."""
    nodes = [root]
    while nodes:
        u = nodes[-1]
        advanced = False
        while it[u] < len(adj[u]):
            v = adj[u][it[u]]
            it[u] += 1
            w = pair_r.get(v)
            if w is None:
                for node in reversed(nodes):  # each node's last tried edge is its edge on the path
                    chosen = adj[node][it[node] - 1]
                    pair_l[node] = chosen
                    pair_r[chosen] = node
                return True
            if dist.get(w, -1) == dist[u] + 1:
                nodes.append(w)
                advanced = True
                break
        if not advanced:
            dist[u] = -1
            nodes.pop()
    return False
