"""Open-time compaction of a cross-reference table full of free slots (round 8 LS-3).

Non-secure full saves serialize with ``garbage=1`` (see ``save_compaction``):
unreachable objects are freed but the xref numbering is kept, so page-snapshot
undo survives a save.  A freed object leaves a free (``null``) slot of 20 bytes
in the file, PyMuPDF never reuses a free slot, and nothing in a plain edit ->
undo -> save session runs ``garbage>=2``, so the table grows across sessions
without bound (13 slots per cycle in the round-8 repro; ``xref_length`` 11 ->
206 after 15 cycles).  A ``garbage>=2`` save would renumber the LIVE document
and strand every retained page snapshot, so the slots are reclaimed at the one
moment no history exists: when ``PDFModel.open_pdf`` opens the file (owner
decision, option B).  ``open_compaction_verdict`` decides, ``compact_in_memory``
does the ``garbage=2`` round trip; the file on disk is never touched (the
compact layout reaches it with the next real save), growth within a session is
accepted, and a file that is opened and never saved keeps its slots.

Thresholds (measured 2026-10-10, PyMuPDF 1.27.1):

* ``MIN_FREE_RATIO`` = 0.5 bounds the growth: compaction is warranted once the
  free slots make up at least half of the table, so the waste never exceeds
  about one live table's worth of slots.  Census of the 2936 PDFs under
  ``test_files``: 222 carry any free slot, the highest ratio of a sound file
  is 0.368 (20-slot test-suite files; ``unreadablemetadata.pdf`` 96 of 267),
  and only the deliberately broken ``corrupted.pdf`` (279 of 284) sits above.
* ``MIN_FREE_SLOTS`` = 512 is only a floor so a tiny file is not rewritten
  over a handful of slots: 512 slots are ~10 KB of waste and ~40 edit ->
  undo -> save cycles of the repro; no corpus file has more than 279.
* ``MAX_FILE_BYTES`` = 64 MB bounds the open-time cost: ``tobytes(garbage=2)``
  measured 163 ms on a 47 MB / 402-page file (~3.5 ms/MB, same as the
  ``garbage=1`` repair round trip) and the reopened document holds one
  serialization buffer (~1x the file) in memory; a compacted session is also
  memory-backed, so every later save is a full rewrite instead of an append.
  Above the cap the per-slot waste (20 B against >= 64 MB, 0.0004 % per
  cycle) is noise and the rewrite would cost the most.
* ``MAX_CENSUS_SLOTS`` = 200_000 bounds the walk: ``xref_object`` costs
  ~1.2 us per free slot and ~4.4 us per in-use slot on a fresh handle (the
  same 4.3 us/slot on the ``use_objstms=1`` form of the same 47 MB file), so
  the cap is ~1 s worst case; a sound file of that many objects is far above
  the size cap anyway.  A table that declares more slots than the file has
  bytes (H10-2 class) is never walked.

No Qt.  The walk is bounded by ``doc.xref_length()`` and stops early as soon
as the thresholds can no longer be reached (a healthy table, the common case,
is walked for at most ``1 - MIN_FREE_RATIO`` of its length) or are already met.

Open-time read of every object (round 11 OD-FS1-READALL)
--------------------------------------------------------

A broken xref entry for an object MuPDF does not need at open (``is_repaired``
stays False) is only noticed when something loads that object.  When that is
a save -- incremental or full -- MuPDF rebuilds the table in the middle of it
and the document loses every in-memory edit (the save then fails on the
staging file, or reports success with the edits missing).  Owner decision:
``read_every_object`` loads each object once at open, so the repair happens
before any edit exists and ``PDFModel.open_pdf``'s repair round trip takes the
document over.  The same pass counts the free slots, so the compaction verdict
above reuses it instead of walking a second time (``open_compaction_verdict``'s
``walk`` argument); its bounded early-exit census only runs when the full walk
was skipped or is unusable (repaired mid-walk, failed objects).

Cap (measured 2026-10-10, PyMuPDF 1.27.1, fresh handle, best of 3):

* The cost tracks the number of slots, not the file size (stream data is not
  read): 47 MB / 4 028 slots 17 ms, 36.5 MB / 10 679 slots 44 ms, but a
  15.6 MB synthetic file of 200 000 dictionaries 1.16 s (5.8 us/slot; 2.6 us/
  slot in object-stream form, 0.5 s), 500 000 slots 2.2 s.  Corpus of the
  2 936 readable PDFs under ``test_files``: largest table 40 015 slots
  (118 ms), slowest walk 179 ms (21 647 slots), all of them 0.74 s together;
  none is repaired by the walk alone.  Loaded objects stay cached for the
  document's life (~300 B/slot on the synthetic files, ~0.9 KB/slot on the
  drawings; 63 MB at 200 000 slots); the bounded census already loaded up to
  half of them.
* ``MAX_READ_ALL_SLOTS`` = 200 000 therefore bounds the open-time cost at
  about one second (the same bound as ``MAX_CENSUS_SLOTS``); bigger tables keep
  the old behaviour (a lazily damaged one can still be repaired mid-save).  A
  table that declares more slots than the file has bytes (H10-2 class) is
  never walked.  A file-size cap would not bound the cost: a 47 MB image-heavy
  file walks in 17 ms while a 16 MB file of small objects takes over a second.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from model import doc_bytes
from model.signed_append_save import xref_slots_are_unbacked

logger = logging.getLogger(__name__)

MIN_FREE_SLOTS = 512
MIN_FREE_RATIO = 0.5
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_CENSUS_SLOTS = 200_000
MAX_READ_ALL_SLOTS = 200_000

# The lowest garbage level that renumbers: free slots are dropped, objects are
# neither merged (3) nor stream-compared (4), content streams stay byte-identical.
COMPACTION_GARBAGE_LEVEL = 2


@dataclass(frozen=True)
class CompactionVerdict:
    """Whether an open should compact, and the census it was based on."""

    compact: bool
    reason: str
    free_slots: int = 0
    total_slots: int = 0


@dataclass(frozen=True)
class ObjectWalk:
    """Outcome of ``read_every_object``.

    ``repaired``: MuPDF rebuilt the table during the walk (lazily damaged
    file); the counts then describe the old table and are not a census.
    """

    walked: bool
    reason: str
    free_slots: int = 0
    total_slots: int = 0
    failed_slots: int = 0
    repaired: bool = False

    @property
    def census_usable(self) -> bool:
        """True when ``free_slots`` / ``total_slots`` count the current table exactly."""
        return self.walked and not self.repaired and self.failed_slots == 0


def _repaired_probe(doc: fitz.Document) -> Callable[[], bool]:
    """``lambda: bool(doc.is_repaired)``, resolved once to the C flag the property reads.

    The property rebuilds its ``PdfDocument`` wrapper on every read (~1.4 us,
    as much as the ``xref_object`` load it guards after every slot of
    ``read_every_object``); the low-level binding on a kept wrapper costs
    ~0.2 us.  Falls back to the property when this PyMuPDF lacks the primitives
    or the probe fails (a document that is not a PDF).
    """
    was_repaired = getattr(fitz.mupdf, "ll_pdf_was_repaired", None)
    as_pdf = getattr(fitz, "_as_pdf_document", None)
    if was_repaired is not None and as_pdf is not None:
        try:
            pdf = as_pdf(doc)
            handle = pdf.m_internal
            if handle:

                def probe(_wrapper: object = pdf) -> bool:
                    # ``_wrapper`` keeps the PdfDocument (and its raw pointer) alive.
                    return bool(was_repaired(handle))

                probe()
                return probe
        except Exception:  # noqa: BLE001 - the property is the slow, safe answer
            pass
    return lambda: bool(getattr(doc, "is_repaired", False))


def read_every_object(doc: fitz.Document, file_size: int) -> ObjectWalk:
    """Load every object of the just-opened ``doc`` once (OD-FS1-READALL).

    Any lazy xref damage is then found -- and repaired by MuPDF, which sets
    ``is_repaired`` without raising -- now, before edits exist, instead of in
    the middle of a later save.  The walk stops at the repair (MuPDF rebuilt
    the whole table from a scan of the file) and goes on past an object that
    fails to load.  Bounded by ``MAX_READ_ALL_SLOTS`` and the unbacked-table
    guard; never raises.  Free (``null``) slots are counted for the compaction
    verdict; slot 0 is never read.
    """
    try:
        length = int(doc.xref_length())
    except Exception as exc:  # noqa: BLE001 - never let the walk break an open
        logger.warning("open-time object walk skipped: xref_length failed: %s", str(exc))
        return ObjectWalk(False, "xref_length failed")
    total = length - 1
    if total <= 0:
        return ObjectWalk(True, "empty table")
    if length > MAX_READ_ALL_SLOTS or xref_slots_are_unbacked(length, file_size):
        return ObjectWalk(False, "table too large to walk", total_slots=total)
    repaired = _repaired_probe(doc)
    was_repaired = repaired()
    free = 0
    failed = 0
    first_error = ""
    for xref in range(1, length):
        try:
            if doc.xref_object(xref) == "null":
                free += 1
        except Exception as exc:  # noqa: BLE001 - one bad object must not stop the walk
            failed += 1
            if not first_error:
                # A STRING only: see the caplog / WinError 5 note in the census.
                first_error = f"xref {xref}: {exc}"
        if not was_repaired and repaired():
            return ObjectWalk(True, "repaired during the walk", free, total, failed, repaired=True)
    if failed:
        logger.warning(
            "open-time object walk: %d object(s) failed to load (first: %s)", failed, first_error
        )
    return ObjectWalk(True, "walked", free, total, failed)


def open_compaction_verdict(
    doc: fitz.Document, file_size: int, walk: ObjectWalk | None = None
) -> CompactionVerdict:
    """Decide whether the just-opened ``doc`` (``file_size`` bytes on disk) should be compacted.

    Cheap gates first (size, declared table length), then the free (``null``)
    slot count: taken from ``walk`` (the open-time ``read_every_object`` pass)
    when it counted this exact table, else a bounded census; slot 0 is always
    free and never counted.  Any failure of the walk is a "no" (the open must
    never depend on it).
    """
    if file_size > MAX_FILE_BYTES:
        return CompactionVerdict(False, "file above the size cap")
    try:
        length = int(doc.xref_length())
    except Exception as exc:  # noqa: BLE001 - never let the census break an open
        logger.warning("xref census skipped: xref_length failed: %s", str(exc))
        return CompactionVerdict(False, "xref_length failed")
    total = length - 1
    if total <= 0:
        return CompactionVerdict(False, "empty table", 0, 0)
    if length > MAX_CENSUS_SLOTS or xref_slots_are_unbacked(length, file_size):
        return CompactionVerdict(False, "table too large to walk", 0, total)
    needed = max(MIN_FREE_SLOTS, math.ceil(MIN_FREE_RATIO * total))
    if walk is not None and walk.census_usable and walk.total_slots == total:
        return CompactionVerdict(
            walk.free_slots >= needed, "counted by the open-time walk", walk.free_slots, total
        )
    free = 0
    try:
        for xref in range(1, length):
            remaining = length - xref  # slots not yet probed, this one included
            if free + remaining < needed:
                return CompactionVerdict(False, "below threshold", free, total)
            if doc.xref_object(xref) == "null":
                free += 1
                if free >= needed:
                    return CompactionVerdict(True, "free slots above threshold", free, total)
    except Exception as exc:  # noqa: BLE001 - never let the census break an open
        # Log a STRING, not ``exc`` / ``exc_info``: the exception's traceback
        # holds the failing ``xref_object`` frame whose arguments include the
        # SWIG document, so a handler that keeps records (pytest's caplog, a
        # memory handler) would keep the MuPDF file open past ``doc.close()``
        # and the next ``os.replace`` over the file fails with WinError 5.
        logger.warning("xref census skipped: object walk failed: %s", str(exc))
        return CompactionVerdict(False, "walk failed", free, total)
    return CompactionVerdict(free >= needed, "walked", free, total)


def compact_in_memory(doc: fitz.Document) -> fitz.Document:
    """A NEW in-memory document with ``doc``'s content and a compact table.

    The bytes of ``tobytes(garbage=2)``, written by ``doc_bytes``'s native
    in-memory sink (never a temp file).  The ``garbage=2`` write renumbers the
    SOURCE handle in place as a side effect (PyMuPDF 1.27.1, either sink); the
    caller owns ``doc`` and must close it (or, on failure, replace a file-backed
    handle with a fresh one -- the renumbered handle no longer matches the
    file's table).  Content streams are copied as-is (no ``deflate``), so the
    page content is byte-identical.
    """
    data = doc_bytes.serialize_doc(
        doc, encryption=fitz.PDF_ENCRYPT_KEEP, garbage=COMPACTION_GARBAGE_LEVEL, in_memory=True
    )
    return fitz.open("pdf", data)
