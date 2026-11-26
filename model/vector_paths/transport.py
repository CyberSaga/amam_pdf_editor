"""One-file transport of a ``VectorIndex`` between the ``vector-scan`` child and the GUI process (H21).

The index is six structured arrays plus a few scalars.  The child writes ONE ``numpy.save`` file
(``allow_pickle=False``) holding a flat ``uint8`` array::

    [8-byte little-endian length N][N bytes of UTF-8 JSON metadata][paths][cubics][segments][blocks][streams][dots]

The metadata carries the row counts, ``indexed_end``, ``stopped_at_inline_image``, the frame, the hex
stream digests, ``nbytes``, the per-block resource pairs (hex) and the scanner that produced the tables.

The file comes from a child that may be damaged or hostile, so ``load_index`` never lets the file size
the allocation: it opens the file ONCE, requires a regular file, parses the NPY header itself
(``numpy.lib.format``, header size bounded), and checks flat ``uint8``, the payload budget
(``MAX_PAYLOAD_BYTES``), the exact physical size (no byte before the header's claim is missing, none is
left over after it) and the metadata budget (``MAX_META_BYTES``) BEFORE any array is allocated or any
JSON is parsed.  The tables are then read straight into preallocated arrays (no second copy), and the
structure is validated (counts, references between tables, offsets) before the index is returned.  Any
truncated, padded, forged or inconsistent file is a ``ValueError``.  No Qt (importing ``scan`` pulls
PyMuPDF in through ``model.pdf_content_ops``).
"""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from io import BufferedReader

import numpy as np

from model.vector_paths.scan import (
    _BLOCK_DT,
    _CUBIC_DT,
    _PATH_DT,
    _DOT_DT,
    _SEG_DT,
    _STREAM_DT,
    VectorIndex,
)

_TABLES = (
    ("paths", _PATH_DT),
    ("cubics", _CUBIC_DT),
    ("segments", _SEG_DT),
    ("blocks", _BLOCK_DT),
    ("streams", _STREAM_DT),
    ("dots", _DOT_DT),
)
#: the largest flat ``uint8`` payload the GUI process agrees to read from a child (all five tables + metadata)
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
#: the largest JSON metadata block (digests and block resources) the GUI process parses
MAX_META_BYTES = 64 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_READ_CHUNK = 64 * 1024 * 1024


def save_index(index: VectorIndex, path: str | Path) -> None:
    """Write ``index`` to ``path`` as one ``.npy`` file (the caller owns the file's lifetime)."""
    meta = {
        "counts": {name: int(len(getattr(index, name))) for name, _ in _TABLES},
        "indexed_end": int(index.indexed_end),
        "stopped": bool(index.stopped_at_inline_image),
        "frame": [float(v) for v in index.frame],
        "digests": [d.hex() for d in index.stream_digests],
        "nbytes": int(index.nbytes),
        "block_resources": [[[op.hex(), name.hex()] for op, name in block] for block in index.block_resources],
        "scanner": str(index.scanner),
        "accelerated": bool(index.accelerated),
    }
    head = json.dumps(meta).encode("utf-8")
    parts = [np.frombuffer(len(head).to_bytes(8, "little") + head, dtype=np.uint8)]
    for name, dtype in _TABLES:
        table = np.ascontiguousarray(getattr(index, name), dtype=dtype)
        parts.append(table.view(np.uint8).reshape(-1))
    with open(path, "wb") as handle:
        np.save(handle, np.concatenate(parts), allow_pickle=False)


def load_index(path: str | Path) -> VectorIndex:
    """Read a file written by ``save_index``.  ``OSError`` when it cannot be read, ``ValueError`` when
    its content is not exactly a ``save_index`` file.  The returned arrays own their memory."""
    before = os.lstat(path)
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError("an index file is a regular file, not a link or a directory")
    with open(path, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (before.st_ino and not os.path.samestat(before, opened)):
            raise ValueError("the index file changed while it was opened")
        try:
            return _read(handle, int(opened.st_size))
        except (ValueError, OSError, MemoryError):
            raise
        except Exception as exc:
            raise ValueError(f"malformed index file: {type(exc).__name__}") from None


def _read_exact(handle: BufferedReader, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("index file ends early")
    return data


def _npy_payload_length(handle: BufferedReader, file_size: int) -> int:
    """Parse the NPY header; return the claimed payload length after checking it against the file."""
    try:
        # Version 1.0 only (what ``np.save`` writes for a flat uint8 array): its header length is a 16-bit
        # field, so the header is bounded by the format itself on every numpy the project supports.
        if np.lib.format.read_magic(handle) != (1, 0):
            raise ValueError("unsupported NPY version")
        shape, _fortran, dtype = np.lib.format.read_array_header_1_0(handle)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"not an index file: {type(exc).__name__}") from None
    if dtype != np.dtype(np.uint8) or len(shape) != 1:
        raise ValueError("an index file holds one flat uint8 array")
    payload = int(shape[0])
    if payload < 8:
        raise ValueError("index file too short")
    if payload > MAX_PAYLOAD_BYTES:
        raise ValueError("index file payload is over the budget")
    if file_size != handle.tell() + payload:  # a short file, and bytes after the record, are both corrupt
        raise ValueError("index file size does not match its header")
    return payload


def _read_into(handle: BufferedReader, array: np.ndarray) -> None:
    view = array.view(np.uint8).reshape(-1)
    done = 0
    while done < len(view):
        got = handle.readinto(view[done : done + _READ_CHUNK])  # type: ignore[arg-type]  # ndarray exports a buffer
        if not got:
            raise ValueError("index file ends early")
        done += got


def _read(handle: BufferedReader, file_size: int) -> VectorIndex:
    payload = _npy_payload_length(handle, file_size)
    meta_len = int.from_bytes(_read_exact(handle, 8), "little")
    if meta_len <= 0 or meta_len > MAX_META_BYTES or 8 + meta_len > payload:
        raise ValueError("bad metadata length")
    meta = json.loads(_read_exact(handle, meta_len))
    if not isinstance(meta, dict):
        raise ValueError("bad metadata")
    counts = meta["counts"]
    if not isinstance(counts, dict) or set(counts) != {name for name, _ in _TABLES}:
        raise ValueError("bad counts")
    expected = 8 + meta_len
    for name, dtype in _TABLES:
        count = counts[name]
        if type(count) is not int or count < 0:
            raise ValueError("bad count")
        expected += count * dtype.itemsize
    if expected != payload:
        raise ValueError("table sizes do not match the file")
    indexed_end, stopped, nbytes = meta["indexed_end"], meta["stopped"], meta["nbytes"]
    if type(indexed_end) is not int or type(nbytes) is not int or type(stopped) is not bool:
        raise ValueError("bad scalars")
    scanner, accelerated = meta["scanner"], meta["accelerated"]
    if type(scanner) is not str or type(accelerated) is not bool:
        raise ValueError("bad scanner record")
    frame = meta["frame"]
    if not isinstance(frame, list) or len(frame) != 6 or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in frame
    ):
        raise ValueError("bad frame")
    digest_hex = meta["digests"]
    if not isinstance(digest_hex, list) or len(digest_hex) != counts["streams"]:
        raise ValueError("digest count does not match the stream count")
    digests = tuple(bytes.fromhex(d) for d in digest_hex)
    if not all(len(d) == 32 for d in digests):
        raise ValueError("bad digest")
    resources_raw = meta["block_resources"]
    if not isinstance(resources_raw, list) or len(resources_raw) != counts["blocks"]:
        raise ValueError("bad block resources")
    resources = tuple(
        tuple((bytes.fromhex(op), bytes.fromhex(name)) for op, name in block) for block in resources_raw
    )
    # Everything that can be checked without the tables has passed: only now is memory allocated, one
    # table at a time, read straight from the file.
    tables: dict[str, np.ndarray] = {}
    for name, dtype in _TABLES:
        table = np.empty(counts[name], dtype=dtype)
        _read_into(handle, table)
        tables[name] = table
    _validate(tables, indexed_end, nbytes, len(digests))
    return VectorIndex(
        tables["paths"], tables["cubics"], tables["segments"], tables["blocks"], tables["streams"],
        indexed_end, stopped, tuple(float(v) for v in frame), digests, nbytes, resources,  # type: ignore[arg-type]
        scanner, accelerated, tables["dots"],
    )


def _validate(tables: dict[str, np.ndarray], indexed_end: int, nbytes: int, digest_count: int) -> None:
    """The structure a scan produces: derived values recomputed, references inside their tables, offsets
    monotonic.  Raises ``ValueError``; nothing is returned (the tables are not touched)."""
    paths, cubics, segments = tables["paths"], tables["cubics"], tables["segments"]
    blocks, streams = tables["blocks"], tables["streams"]
    dots = tables["dots"]
    if nbytes != sum(int(table.nbytes) for table in tables.values()):
        raise ValueError("nbytes does not match the tables")
    if digest_count != len(streams):
        raise ValueError("digest count does not match the stream count")

    total = 0
    if len(streams):
        starts = streams["global_start"].astype(np.int64)
        lengths = streams["length"].astype(np.int64)
        if bool((lengths < 0).any()) or int(starts[0]) != 0:
            raise ValueError("bad stream table")
        ends = starts + lengths
        if bool((starts[1:] != ends[:-1]).any()) or bool((ends < starts).any()):
            raise ValueError("stream offsets are not contiguous")
        total = int(ends[-1])
    if not 0 <= indexed_end <= total:
        raise ValueError("indexed_end is outside the streams")

    n_paths, n_segments, n_blocks = len(paths), len(segments), len(blocks)

    def seg_range(table: np.ndarray) -> None:
        first = table["seg_start"].astype(np.int64)
        count = table["seg_count"].astype(np.int64)
        if len(table) and (
            bool((first < 0).any()) or bool((count < 0).any()) or bool((first + count > n_segments).any())
        ):
            raise ValueError("segment range outside the segments table")

    seg_range(paths)
    seg_range(cubics)
    if n_paths:
        block = paths["block"]
        if bool((block < -1).any()) or bool((block >= n_blocks).any()):
            raise ValueError("path block reference outside the blocks table")
        p_start = paths["path_start"].astype(np.int64)
        p_end = paths["paint_end"].astype(np.int64)
        if bool((p_start < 0).any()) or bool((p_end < p_start).any()) or bool((p_end > total).any()):
            raise ValueError("path offsets outside the streams")
        if bool((p_start[1:] < p_start[:-1]).any()):
            raise ValueError("path offsets are not monotonic")
    for table, label in ((segments, "segment"), (cubics, "cubic")):
        if len(table):
            owner = table["path"]
            if bool((owner < 0).any()) or bool((owner >= n_paths).any()):
                raise ValueError(f"{label} path reference outside the paths table")
    if n_segments and bool((segments["subpath"] < 0).any()):
        raise ValueError("negative subpath index")
    if len(dots):
        owner, ordinal = dots["path"].astype(np.int64), dots["subpath"].astype(np.int64)
        if bool((owner < 0).any()) or bool((owner >= n_paths).any()) or bool((ordinal < 0).any()):
            raise ValueError("dot path or ordinal outside its table")
        if not (np.isfinite(dots["x"]).all() and np.isfinite(dots["y"]).all()):
            raise ValueError("a dot coordinate is not finite")
        first = np.searchsorted(owner, owner, side="left")  # meaningful only when owner is non-decreasing
        if bool((owner[1:] < owner[:-1]).any()) or not np.array_equal(ordinal, np.arange(len(owner)) - first):
            raise ValueError("the dot table is not sorted by (path, subpath)")
    if n_blocks:
        q_start = blocks["q_start"].astype(np.int64)
        q_end = blocks["q_end"].astype(np.int64)
        if bool((q_start < 0).any()) or bool((q_end < q_start).any()) or bool((q_end > total).any()):
            raise ValueError("block offsets outside the streams")
        if bool((blocks["n_paints"] < 0).any()) or bool((blocks["n_cm"] < 0).any()):
            raise ValueError("negative block counts")
        if bool((blocks["cm_operand_start"] < -1).any()) or bool((blocks["cm_operand_end"] < -1).any()):
            raise ValueError("bad cm operand offsets")
