"""Page-object-graph snapshots, restored IN PLACE by xref.

A page snapshot used to be a one-page PDF built with ``insert_pdf`` and
restored with another ``insert_pdf`` + ``delete_page``.  ``insert_pdf`` grafts
COPIES of every indirect object the page references, so every shared,
document-level object (the page object itself, OCGs listed in
``/OCProperties``, fonts, ``/Annots``, ...) lost its identity on each undo or
redo: after one undo the page's ``/Properties`` pointed at duplicated OCGs that
the catalog does not list, and every marked-content wrapper classified
``props_unresolved`` (see docs/PITFALLS.md, "page snapshot restore via
insert_pdf grafts copies").

This module is the single chokepoint that replaces it:

* :func:`capture_page_graph` records the page object plus every object
  reachable from it (never up through ``/Parent`` or a structure ``/P``, and
  never into other pages / the page tree / the catalog) as
  ``(xref, object text, raw stream bytes)`` triples;
* :func:`restore_page_graph` writes those objects back at the SAME xrefs.
  There is no graft fallback anywhere: when an in-place restore is impossible
  (the live document was renumbered since the capture) it raises
  :class:`PageSnapshotStale` BEFORE any write, the same zero-mutation contract
  as a stale Tier 0 patch.

The xref numbering identity is tracked by the model's ``xref_epoch`` (see
``PDFModel.xref_epoch``): a snapshot only restores under the epoch it was
captured in.

Model layer: no Qt.
"""

from __future__ import annotations

import logging
import re
import struct

import fitz

from model.text_commit.cid_fonts import PdfRef, parse_pdf_value
from utils.pymupdf_refs import sync_open_pages

logger = logging.getLogger(__name__)

PAGE_SNAPSHOT_MAX_OBJECTS = 100_000
# Sanity cap on how far a restore may grow the xref table (a corrupt snapshot).
PAGE_SNAPSHOT_MAX_XREF_GROWTH = 4_000_000
_STRUCTURAL_TYPES = frozenset({"/Page", "/Pages", "/Catalog"})

_MAGIC = b"PGSNAP1\x00"
_HEADER = struct.Struct("<qII")
_RECORD = struct.Struct("<IIq")

_RE_PARENT = re.compile(r"/Parent\s+\d+\s+\d+\s+R")
_RE_P = re.compile(r"/P\s+\d+\s+\d+\s+R")
_RE_REF = re.compile(r"(\d+)\s+\d+\s+R(?![A-Za-z0-9])")
_RE_STRUCT_TYPE = re.compile(r"/Type\s*/(Page|Pages|Catalog)\b")
_RE_PARENT_VALUE = re.compile(r"/Parent\s+(\d+)\s+\d+\s+R")


class PageSnapshotError(RuntimeError):
    """Capture failed (budget, unreadable object, ...)."""


class PageSnapshotStale(RuntimeError):
    """Restore is impossible; guaranteed zero mutation."""


class PageSnapshot(bytes):
    """Plain bytes (so ``len`` / ``_byte_size`` / content dedup keep working)
    holding a page's object graph.

    Layout: ``MAGIC`` + ``<qII xref_epoch page_xref n_records`` then per record
    ``<IIq xref len(obj) raw_len|-1`` + obj (utf-8, surrogatepass) + raw.
    Everything lives in the bytes: no instance attributes.
    """

    __slots__ = ()

    @classmethod
    def build(
        cls,
        page_xref: int,
        xref_epoch: int,
        records: list[tuple[int, str, bytes | None]],
    ) -> PageSnapshot:
        parts: list[bytes] = [
            _MAGIC,
            _HEADER.pack(int(xref_epoch), int(page_xref), len(records)),
        ]
        for xref, obj, raw in records:
            obj_b = obj.encode("utf-8", "surrogatepass")
            parts.append(_RECORD.pack(int(xref), len(obj_b), -1 if raw is None else len(raw)))
            parts.append(obj_b)
            if raw is not None:
                parts.append(raw)
        return cls(b"".join(parts))

    def _header(self) -> tuple[int, int, int]:
        if len(self) < len(_MAGIC) + _HEADER.size or self[: len(_MAGIC)] != _MAGIC:
            raise PageSnapshotError("not a page snapshot")
        return _HEADER.unpack_from(self, len(_MAGIC))

    @property
    def xref_epoch(self) -> int:
        return self._header()[0]

    @property
    def page_xref(self) -> int:
        return self._header()[1]

    def records(self) -> tuple[tuple[int, str, bytes | None], ...]:
        _epoch, _page, count = self._header()
        pos = len(_MAGIC) + _HEADER.size
        out: list[tuple[int, str, bytes | None]] = []
        for _ in range(count):
            xref, obj_len, raw_len = _RECORD.unpack_from(self, pos)
            pos += _RECORD.size
            obj = bytes(self[pos : pos + obj_len]).decode("utf-8", "surrogatepass")
            pos += obj_len
            raw: bytes | None = None
            if raw_len >= 0:
                raw = bytes(self[pos : pos + raw_len])
                pos += raw_len
            out.append((xref, obj, raw))
        return tuple(out)


# ---------------------------------------------------------------------- capture


def _collect_refs(value: object, out: list[int]) -> None:
    """Every PdfRef under ``value`` except ``/Parent`` values and ``/P`` refs."""
    if isinstance(value, PdfRef):
        out.append(value.xref)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "Parent":
                continue
            if key == "P" and isinstance(item, PdfRef):
                continue
            _collect_refs(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_refs(item, out)


def capture_page_graph(doc: fitz.Document, page_index: int, *, xref_epoch: int) -> PageSnapshot:
    """Snapshot the page object and everything reachable from it."""
    try:
        root = int(doc.page_xref(page_index))
        length = int(doc.xref_length())
        records: list[tuple[int, str, bytes | None]] = []
        seen: set[int] = {root}
        stack: list[int] = [root]
        while stack:
            xref = stack.pop()
            obj = doc.xref_object(xref)
            if obj.strip() == "null":
                continue
            is_stream = bool(doc.xref_is_stream(xref))
            head = obj[: obj.rfind(">>") + 2] if is_stream else obj
            refs: list[int] = []
            structural = False
            try:
                parsed = parse_pdf_value(head)
            except Exception:
                cleaned = _RE_P.sub("", _RE_PARENT.sub("", head))
                refs = [int(m) for m in _RE_REF.findall(cleaned)]
                structural = bool(_RE_STRUCT_TYPE.search(head))
            else:
                if isinstance(parsed, dict) and parsed.get("Type") in _STRUCTURAL_TYPES:
                    structural = True
                _collect_refs(parsed, refs)
            if xref != root and structural:
                continue
            raw = doc.xref_stream_raw(xref) if is_stream else None
            records.append((xref, obj, raw))
            if len(records) > PAGE_SNAPSHOT_MAX_OBJECTS:
                raise PageSnapshotError("budget")
            # Reverse so the first ref is visited first (stable capture order).
            for ref in reversed(refs):
                if 0 < ref < length and ref not in seen:
                    seen.add(ref)
                    stack.append(ref)
        return PageSnapshot.build(root, xref_epoch, records)
    except PageSnapshotError:
        raise
    except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase) as exc:
        raise PageSnapshotError(f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------- restore


def _snapshot_parent_xref(obj: str) -> int | None:
    try:
        parsed = parse_pdf_value(obj)
    except Exception:
        match = _RE_PARENT_VALUE.search(obj)
        return int(match.group(1)) if match else None
    if isinstance(parsed, dict):
        parent = parsed.get("Parent")
        if isinstance(parent, PdfRef):
            return parent.xref
    return None


def _live_parent_xref(doc: fitz.Document, page_xref: int) -> int | None:
    kind, value = doc.xref_get_key(page_xref, "Parent")
    if kind != "xref":
        return None
    match = re.match(r"\s*(\d+)\s+\d+\s+R", value)
    return int(match.group(1)) if match else None


def _write_record(doc: fitz.Document, xref: int, obj: str, raw: bytes | None) -> None:
    if raw is not None:
        if (
            doc.xref_is_stream(xref)
            and doc.xref_stream_raw(xref) == raw
            and doc.xref_object(xref) == obj
        ):
            return
        if not doc.xref_is_stream(xref):
            # Resurrects a freed / null slot as a (stream-capable) dict.
            doc.update_object(xref, "<<>>")
        # Raw bytes first, then the dict (PITFALLS "Restore stream bytes
        # before restoring the stream dictionary").
        doc.update_stream(xref, raw, compress=False)
        doc.update_object(xref, obj)
        if doc.xref_stream_raw(xref) != raw or doc.xref_object(xref) != obj:
            raise RuntimeError(f"stream restore verification failed xref={xref}")
        return
    if doc.xref_object(xref) != obj:
        doc.update_object(xref, obj)


def restore_page_graph(
    doc: fitz.Document,
    page_index: int,
    snapshot: PageSnapshot,
    *,
    xref_epoch: int,
) -> int:
    """Write the snapshot back at the same xrefs; returns objects written.

    Raises :class:`PageSnapshotStale` before any write when the live document
    no longer matches the snapshot's numbering.

    Every exit that wrote resyncs the loaded pages (``sync_open_pages``): the
    writes go round MuPDF's annotation API, and a ``fitz.Page`` still alive
    across them shares its MuPDF page -- with the annotation / link lists of
    the pre-restore graph -- with every later ``doc[n]`` (F11-ANN-2).
    """
    try:
        records = snapshot.records()
        snap_epoch = snapshot.xref_epoch
        snap_page = snapshot.page_xref
    except (PageSnapshotError, struct.error, UnicodeError) as exc:
        raise PageSnapshotStale(f"unreadable page snapshot: {exc}") from exc
    if snap_epoch != xref_epoch:
        raise PageSnapshotStale("xref numbering changed since the snapshot")
    if page_index < 0 or page_index >= doc.page_count:
        raise PageSnapshotStale("page index out of range")
    if int(doc.page_xref(page_index)) != snap_page:
        raise PageSnapshotStale("page object changed since the snapshot")
    length = int(doc.xref_length())
    max_xref = max((xref for xref, _obj, _raw in records), default=0)
    if max_xref - length > PAGE_SNAPSHOT_MAX_XREF_GROWTH:
        raise PageSnapshotStale("snapshot objects lie outside the document")
    root_record = next((rec for rec in records if rec[0] == snap_page), None)
    if root_record is None:
        raise PageSnapshotStale("snapshot has no page record")
    snap_parent = _snapshot_parent_xref(root_record[1])
    if snap_parent != _live_parent_xref(doc, snap_page):
        raise PageSnapshotStale("page tree parent changed since the snapshot")
    for xref, _obj, raw in records:
        if xref >= length or doc.xref_object(xref).strip() == "null":
            continue
        live_stream = bool(doc.xref_is_stream(xref))
        if live_stream != (raw is not None):
            raise PageSnapshotStale(f"object kind changed since the snapshot xref={xref}")

    # A record beyond the live table is a slot that is free in this lineage: a
    # whole-document snapshot command redone BEFORE this one reopened the doc
    # from bytes taken while the table was shorter (same epoch, same numbering).
    # Treat it as null for the rollback and grow the table below.
    prior: list[tuple[int, str, bytes | None]] = [
        (xref, "null", None)
        if xref >= length
        else (
            xref,
            doc.xref_object(xref),
            doc.xref_stream_raw(xref) if doc.xref_is_stream(xref) else None,
        )
        for xref, _obj, _raw in records
    ]
    while int(doc.xref_length()) <= max_xref:
        doc.get_new_xref()
    ordered = [rec for rec in records if rec[0] != snap_page] + [root_record]
    written = 0
    try:
        for xref, obj, raw in ordered:
            _write_record(doc, xref, obj, raw)
            written += 1
    except Exception as exc:
        for xref, obj, raw in prior:
            if obj.strip() == "null":
                continue
            try:
                _write_record(doc, xref, obj, raw)
            except Exception:  # best effort: keep putting the rest back
                logger.exception("page snapshot rollback failed xref=%s", xref)
        logger.error("page snapshot restore failed (%s); page put back", type(exc).__name__)
        raise RuntimeError("page snapshot restore failed; page put back") from exc
    finally:
        sync_open_pages(doc)
    return written
