"""Card B6, part 1 (design plan Step 5): the delete plan over a VectorIndex.

Pure bytes in, plan out; nothing here reads a document.  D7: cut [path_start, paint_end) and never re-serialise; keep the
whitespace byte before the cut and drop the one after only when both neighbours are whitespace.  D17: remove a whole leaf
q..Q block instead when it is inert and every one of its records is editable and selected.  Adjacent ranges merge.
The derived index is a rescan of the new bytes (an incremental derivation is a later optimisation).
"""

from __future__ import annotations

import hashlib
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from model.vector_paths.scan import PathFlag, VectorIndex, VectorScanCancelled, scan_page

_EDITABLE = int(PathFlag.EDITABLE)
_WS = frozenset(b" \t\r\n\x0c\x00")
_FAST_SCAN_BYTES = 1 << 20


@dataclass
class VectorPlan:
    kind: Literal["delete", "move"]
    frame: tuple[float, float, float, float, float, float]
    source_digests: tuple[bytes, ...]
    ranges: tuple[np.ndarray, ...]  # per stream, (R, 2) int64, local offsets into the source stream
    new_streams: tuple[bytes | None, ...]  # None = untouched
    new_compressed: tuple[bytes | None, ...]  # zlib level 6
    planned_digests: tuple[bytes | None, ...]
    derived: VectorIndex
    selection_digest: bytes = b""  # sha256 of the selection mask this plan was computed from (G3: commit re-checks it)


def selection_digest(mask: np.ndarray) -> bytes:
    """Identity of a selection mask: the plan carries it, the commit compares it with the live selection."""
    return hashlib.sha256(np.ascontiguousarray(mask, dtype=bool).tobytes()).digest()


_WS_TABLE = np.zeros(256, dtype=bool)
_WS_TABLE[list(_WS)] = True


def _merge_np(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Union of half-open ranges; touching or overlapping ranges merge."""
    if starts.size == 0:
        return starts, ends
    order = np.argsort(starts, kind="stable")
    s, e = starts[order], ends[order]
    reach = np.maximum.accumulate(e)
    new_run = np.empty(s.size, dtype=bool)
    new_run[0] = True
    new_run[1:] = s[1:] > reach[:-1]
    first = np.flatnonzero(new_run)
    last = np.concatenate([first[1:] - 1, [s.size - 1]])
    return s[first], reach[last]


def plan_delete(
    index: VectorIndex,
    mask: np.ndarray,
    streams: Sequence[bytes],
    *,
    cancel: Callable[[], bool] | None = None,
) -> VectorPlan:
    if cancel is not None and cancel():
        raise VectorScanCancelled()
    paths = index.paths
    if mask.dtype != np.bool_:
        raise ValueError("the selection mask must be boolean")  # one reading of the mask for the ranges and the digest
    if mask.shape != (len(paths),):
        raise ValueError("mask length does not match the index")
    if len(streams) != len(index.streams):
        raise ValueError("stream count differs from the index")
    source_digests = tuple(hashlib.sha256(s).digest() for s in streams)
    if tuple(index.stream_digests) != source_digests:
        raise ValueError("the streams differ from the ones the index was built from")
    selected = mask & ((paths["flags"].astype(np.int64) & _EDITABLE) != 0)
    if not selected.any():
        raise ValueError("nothing editable is selected")

    gstart = index.streams["global_start"].astype(np.int64)

    def stream_of(g: int) -> int:
        return int(np.searchsorted(gstart, g, side="right")) - 1

    covered: np.ndarray = np.zeros(len(paths), dtype=bool)
    block_sid: np.ndarray = np.zeros(0, dtype=np.int64)
    q0: np.ndarray = np.zeros(0, dtype=np.int64)
    q1: np.ndarray = np.zeros(0, dtype=np.int64)
    blocks = index.blocks
    if len(blocks):
        block_of = paths["block"].astype(np.int64)
        has_block = block_of >= 0
        total = np.bincount(block_of[has_block], minlength=len(blocks))
        chosen = np.bincount(block_of[selected & has_block], minlength=len(blocks))
        whole = np.flatnonzero(blocks["inert"] & (total == chosen) & (total == blocks["n_paints"]) & (total >= 1))
        q0 = blocks["q_start"][whole].astype(np.int64)
        q1 = blocks["q_end"][whole].astype(np.int64)
        block_sid = np.searchsorted(gstart, q0, side="right") - 1
        same = block_sid == np.searchsorted(gstart, q1 - 1, side="right") - 1
        whole_ok = whole[same]
        q0, q1, block_sid = q0[same], q1[same], block_sid[same]
        if whole_ok.size:
            covered = np.isin(block_of, whole_ok)
    rest = np.flatnonzero(selected & ~covered)
    p0 = paths["path_start"][rest].astype(np.int64)
    p1 = paths["paint_end"][rest].astype(np.int64)
    span_sid = np.searchsorted(gstart, p0, side="right") - 1

    ranges: list[np.ndarray] = []
    new_streams: list[bytes | None] = []
    for sid, src in enumerate(streams):
        base = int(gstart[sid])
        a = np.concatenate([q0[block_sid == sid] - base, p0[span_sid == sid] - base])
        b = np.concatenate([q1[block_sid == sid] - base, p1[span_sid == sid] - base])
        if a.size == 0:
            ranges.append(np.zeros((0, 2), dtype=np.int64))
            new_streams.append(None)
            continue
        a, b = _merge_np(a, b)
        buf = np.frombuffer(src, dtype=np.uint8)
        inside = (a > 0) & (b < len(src))
        idx_a = np.where(inside, a - 1, 0)
        idx_b = np.where(inside, b, 0)
        grow = inside & _WS_TABLE[buf[idx_a]] & _WS_TABLE[buf[idx_b]]
        a, b = _merge_np(a, b + grow)
        ranges.append(np.stack([a, b], axis=1).astype(np.int64))
        pieces: list[bytes] = []
        pos = 0
        for lo, hi in zip(a.tolist(), b.tolist(), strict=True):
            pieces.append(src[pos:lo])
            pos = hi
        pieces.append(src[pos:])
        new_streams.append(b"".join(pieces))

    final = [n if n is not None else s for n, s in zip(new_streams, streams, strict=True)]
    derived = scan_page(
        final, index.frame, cancel=cancel, accelerated=sum(len(s) for s in final) > _FAST_SCAN_BYTES
    )
    return VectorPlan(
        kind="delete",
        frame=index.frame,
        source_digests=source_digests,
        ranges=tuple(ranges),
        new_streams=tuple(new_streams),
        new_compressed=tuple(None if n is None else zlib.compress(n, 6) for n in new_streams),
        planned_digests=tuple(None if n is None else hashlib.sha256(n).digest() for n in new_streams),
        derived=derived,
        selection_digest=selection_digest(mask),
    )
