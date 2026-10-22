"""Append the live document's state to a digitally signed source file (R7-1).

A signature's ``/ByteRange`` covers the exact bytes of the revision that was
signed, so a full rewrite silently invalidates it.  PyMuPDF only appends
(``incremental=True``) from a handle opened on the file itself, and every
SnapshotCommand undo/redo (and the other whole-document restores) installs an
*in-memory* handle, which cannot.

This module therefore does the append on a file-backed copy of the signed
source: it replays the live document's objects onto that copy and saves it
incrementally.  The result is the source file byte-for-byte followed by one new
revision, whichever handle the session happens to hold.

Replay is lineage-agnostic by construction: EVERY xref of the live document is
made identical (object text and raw stream bytes) to the live one before the
save, and the finished file is reopened and checked object by object again.
Anything that cannot be proven identical answers ``False`` and the caller keeps
its existing (full rewrite) path -- this module never degrades a save, it only
declines to improve it.

"Every xref" is computed without reading every declared slot (H10-2): the
candidates are the union of the slots either side holds an object for, as
MuPDF itself reports them (``_in_use_xrefs``: one C call per slot, no object
loaded).  A slot outside both sets is free, never written or an ``/Index`` gap
on both sides, so ``_source`` reads ``"null"`` for it on both sides and the
full walk skips it at its null/null shortcut -- the result is the same list,
only without the Python cost per declared slot (a 28 KB file can declare 4M).

The appended revision's xref stream takes a NEW object number in the file, above
the live table.  ``PDFModel`` therefore reserves every number below the written
file's ``xref_length()`` in the live document (``reserved_xref_length``, applied
by the ``doc`` setter), or the next new object would land on that container and
the following append would decline (R8-SIG-B).

No Qt.
"""

from __future__ import annotations

import itertools
import logging
import re
import traceback
from pathlib import Path

import fitz

from model.page_snapshot import _write_record as write_xref_record
from model.text_commit.cid_fonts import PdfParseError, PdfRef, parse_pdf_value
from model.text_commit.inspect import document_has_a_signed_signature
from utils.pdf_object_source import xref_object_exact

logger = logging.getLogger(__name__)

_RE_REF = re.compile(r"\s*(\d+)\s+\d+\s+R")
_RE_CONTAINER = re.compile(r"/Type\s*/(?:ObjStm|XRef)\b")
_NULL_RECORD: tuple[str, bytes | None] = ("null", None)

# An xref stream can declare millions of free slots in a few KB (a 28 KB file with
# ``/Size 4000000`` opens in 0.09 s; MuPDF's own cap is 8,388,607).  A walk over
# every declared slot in Python costs ~3 us per free slot, ~9 us before the
# null/null shortcut.  The signed append no longer walks them (the ``_in_use_xrefs``
# census, H10-2); these two constants bound what still would: the census-less
# fallback walk here (a PyMuPDF without the census primitive) and the open-time
# xref compaction (LS-3, ``model/xref_compaction.py``).  A table may always have
# this many slots (small files with padding, a session that added many objects) ...
MAX_UNBACKED_XREF_SLOTS = 100_000
# ... and beyond that the source file must be at least one byte long per declared
# slot.  A real file needs far more (a classic table row alone is 20 bytes, an
# in-use compressed row plus its object several), so only a table that claims more
# slots than the file has bytes is refused, and what a file can unlock grows with
# its size, like the cost of reading it.
XREF_SLOTS_PER_SOURCE_BYTE = 1
# The replay pads the base with ``get_new_xref`` up to the state's length, ~12 us a
# call.  The growth is the objects this session created plus the reserved floor (a
# floor only comes from a file this module wrote, which becomes the next base), so
# it is small; a state that grew past this is declined rather than padded (~1.2 s).
MAX_APPEND_GROWTH_SLOTS = 100_000


class _Declined(Exception):
    """The replay is not provably safe; the caller keeps its own save path.

    ``reason`` is one of ``DECLINE_REASONS`` (SIG-DIALOG): the caller turns it
    into ``SignatureWouldBreakError`` instead of a silent full rewrite.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Why ``try_append_state_onto_source`` declined (SIG-DIALOG).  Stable codes: the
# controller maps them to one plain Traditional Chinese line each, the log keeps
# the detail.
DECLINE_REASONS = frozenset(
    {
        "unsigned_source",  # the source carries no signed signature
        "encryption_mismatch",  # a user password, or the two sides' /Encrypt differ
        "repaired_source",  # MuPDF cannot append to the source as it is (repaired xref)
        "catalog_mismatch",  # the live document has another catalog / info object
        "object_limit",  # unbacked xref table or the growth cap (H10-2)
        "verify_failed",  # census, container lineage, prefix or object-by-object check
        "append_error",  # an unexpected error during the replay
    }
)


def _in_use_xrefs(doc: fitz.Document) -> frozenset[int] | None:
    """Every xref (>= 1) MuPDF holds an object for -- entry type ``n`` or ``o`` -- without loading any.

    One C call per declared slot (~0.19 us: 0.76 s for a 4M-slot table, against
    ~1.1 us for ``xref_object``).  Free, never-written (``get_new_xref`` padding)
    and ``/Index``-gap slots are absent; ``xref_object`` RAISES on a gap slot.  An
    unsaved new object is present.  No side effect on the handle.

    ``None`` when this PyMuPDF lacks the private primitives (pinned by
    ``test_in_use_census_semantics``) or the census fails; callers then fall back
    to the full walk and its size guard.
    """
    exists = getattr(fitz.mupdf, "ll_pdf_object_exists", None)
    as_pdf = getattr(fitz, "_as_pdf_document", None)
    if exists is None or as_pdf is None:
        logger.debug(
            "xref census unavailable: PyMuPDF lacks %s",
            "fitz.mupdf.ll_pdf_object_exists" if exists is None else "fitz._as_pdf_document",
        )
        return None
    try:
        pdf = as_pdf(doc)  # the local keeps the wrapper (and its raw pointer) alive
        handle = pdf.m_internal
        length = int(doc.xref_length())
        return frozenset(
            itertools.compress(
                range(1, length), map(exists, itertools.repeat(handle), range(1, length))
            )
        )
    except (RuntimeError, ValueError, TypeError, AttributeError, fitz.mupdf.FzErrorBase) as exc:
        # str(exc), never exc_info: a kept traceback holds the frame whose locals
        # include the SWIG document and keeps its file open past close() (LS-3).
        logger.debug("xref census failed: %s", str(exc))
        return None


def _source(doc: fitz.Document, xref: int, length: int, *, exact: bool = False) -> str:
    """The object source of ``xref`` (``"null"`` beyond ``length`` or when unreadable).

    The comparisons read ``xref_object``: it is three times cheaper per object
    on these whole-table walks, and its decoded text differs from the source
    only for a name that holds a literal backslash-u escape, so it can miss
    only a change between such names that decode alike (``/F\\u0031`` and
    ``/F1``; two escapes that decode to the same replacement character or, in
    ``_same_object_text``, to characters outside Latin-1), which nothing in
    the app produces except that decode itself.  The replay writes the text
    back and passes ``exact``: ``xref_object`` text would rename such a name in
    the signed file, or raise on a lone surrogate (W1B-DICT-RT).
    """
    if xref >= length:
        return "null"
    try:
        return xref_object_exact(doc, xref) if exact else doc.xref_object(xref)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return "null"


def _record(doc: fitz.Document, xref: int, source: str) -> tuple[str, bytes | None]:
    """The object source and (for a stream) its raw bytes; ``("null", None)`` when absent.

    ``source`` is ``_source(doc, xref, ...)``, already read by every caller, so
    the object text is never read twice.
    """
    try:
        raw = doc.xref_stream_raw(xref) if doc.xref_is_stream(xref) else None
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return _NULL_RECORD
    return source, raw


def xref_slots_are_unbacked(declared_slots: int, source_size: int) -> bool:
    """``True`` when a table declares more slots than ``source_size`` bytes can hold (H10-2)."""
    allowed = max(MAX_UNBACKED_XREF_SLOTS, source_size * XREF_SLOTS_PER_SOURCE_BYTE)
    return declared_slots > allowed


def _tree(value: object) -> object:
    """``value`` as a comparable tree: dict keys unordered, everything else exact.

    Reals compare by their exact value (no rounding), arrays keep their order,
    and a name, a string, an integer and a reference can never equal each other.
    """
    if isinstance(value, dict):
        return ("d", frozenset((key, _tree(item)) for key, item in value.items()))
    if isinstance(value, list):
        return ("a", tuple(_tree(item) for item in value))
    if isinstance(value, PdfRef):
        return ("r", value.xref)
    if isinstance(value, bool):
        return ("b", value)
    if isinstance(value, bytes):
        return ("s", value)
    if isinstance(value, float):
        return ("f", repr(value))
    if isinstance(value, int):
        return ("i", value)
    if isinstance(value, str):
        return ("n", value)
    return ("0", value)


def _same_object_text(wanted: str, current: str, *, ignore_length: bool = False) -> bool:
    """``True`` when two serialized objects are the same PDF object.

    ``xref_object()`` prints a dictionary's keys in the order the handle holds
    them: the live document keeps the order of the last edit, a reopened file
    the order MuPDF wrote.  The key order of a PDF dictionary carries no
    meaning, so a difference in order alone must not count (EXT-2: the
    ``__pdf_editor_watermarks`` Filespec printed ``/Type`` last live and first
    after a reopen, declined every signed append of such a file and fully
    rewrote it).  Text that the bounded parser cannot read is compared as text.

    ``ignore_length`` drops the top-level ``/Length`` entry of both sides (H10-1,
    see ``_same_record``).
    """
    if wanted == current:
        return True
    try:
        left, right = parse_pdf_value(wanted), parse_pdf_value(current)
        if ignore_length and isinstance(left, dict) and isinstance(right, dict):
            left = {key: item for key, item in left.items() if key != "Length"}
            right = {key: item for key, item in right.items() if key != "Length"}
        return _tree(left) == _tree(right)
    except (PdfParseError, ValueError, RecursionError):
        return False


def _same_record(wanted: tuple[str, bytes | None], current: tuple[str, bytes | None]) -> bool:
    """Same object text and same raw stream bytes.

    A stream's ``/Length`` is derived from its bytes, not content.  On an encrypted
    file it also differs by construction: a stream created in the live, unsaved
    handle prints its plaintext length, the same stream read back from the
    appended revision prints the ciphertext length (IV + padding).  Declining over
    it fully rewrote every owner-password-only AES/RC4 signed file whose edit
    added or changed a stream and dropped the signature (H10-1).  So when both
    sides are streams with equal raw bytes, ``/Length`` is not compared.
    """
    if wanted[1] != current[1]:
        return False
    return _same_object_text(wanted[0], current[0], ignore_length=wanted[1] is not None)


def _trailer_ref(doc: fitz.Document, key: str) -> int | None:
    kind, value = doc.xref_get_key(-1, key)
    if kind != "xref":
        return None
    match = _RE_REF.match(value)
    return int(match.group(1)) if match else None


def _replay_decline(state: fitz.Document, base: fitz.Document) -> str | None:
    """The decline code for replaying ``state`` onto ``base``; ``None`` when it may go ahead.

    The replay may go ahead when neither document needs a user password, they
    share one encryption setup (or none), and they share catalog and info
    objects.

    ``state`` is the LIVE document, usually already authenticated, and
    ``needs_pass`` must never be read on such a handle: in PyMuPDF 1.27 the read
    re-runs the empty-password check and overwrites the handle's crypt key, after
    which every object not decoded yet decrypts to garbage (R9 M9-1: the live
    text went blank and the declined append fell back to a full save that wrote
    that garbage over the user's file).  ``base`` is a freshly opened copy of the
    source file and never authenticated, so its flags are safe and decide whether
    a user password is needed; ``state`` is compared through its trailer
    ``/Encrypt`` entry instead, which (same dictionary, same ``/U``) means it
    needs a password exactly when ``base`` does.
    """
    if not (state.is_pdf and base.is_pdf):
        return "catalog_mismatch"
    if state.is_encrypted or base.needs_pass or base.is_encrypted:
        return "encryption_mismatch"
    if state.xref_get_key(-1, "Encrypt") != base.xref_get_key(-1, "Encrypt"):
        return "encryption_mismatch"
    if not base.can_save_incrementally():
        return "repaired_source"
    if state.pdf_catalog() != base.pdf_catalog():
        return "catalog_mismatch"
    if _trailer_ref(state, "Info") != _trailer_ref(base, "Info"):
        return "catalog_mismatch"
    return None


def _differing_xrefs(
    state: fitz.Document, base: fitz.Document, state_in_use: frozenset[int] | None = None
) -> list[int]:
    """Xrefs whose object or raw stream differ between ``state`` and ``base``.

    ``state_in_use`` is ``_in_use_xrefs(state)``: with it, only the slots in use on
    either side are compared (see the module docstring for why that is the same
    result); without it every slot is walked, which is only bounded because the
    caller ran the unbacked-table guard first.  So once the state census exists, a
    failed census of ``base`` declines instead of walking an unbounded table.

    An object-stream or xref-stream container in ``base`` is file structure,
    not document content, and is never replayed: nulling it would orphan every
    member still stored inside, and overwriting it would corrupt the file's own
    cross-reference data.  ``state`` may hold nothing at that number (a
    ``garbage=0`` serialization) or a container of its own: a file-backed live
    handle keeps the file's xref-stream object, whose trailer entries MuPDF
    regenerates after an edit (``/ID``), so it differs from ``base`` although
    nothing in the document does.  Both are skipped; every member is compared
    by its resolved object, so the content is still replayed object by object.
    A real (non-container) object in a container's place is a different
    lineage and declines the replay, as does a container landing on a number
    that is not a container in ``base``.
    """
    differing: list[int] = []
    state_length = int(state.xref_length())
    base_length = int(base.xref_length())
    candidates: range | list[int]
    if state_in_use is None:
        candidates = range(1, state_length)
    else:
        base_in_use = _in_use_xrefs(base)
        if base_in_use is None:
            raise _Declined("verify_failed")
        candidates = sorted(x for x in state_in_use | base_in_use if x < state_length)
    for xref in candidates:
        wanted_source = _source(state, xref, state_length)
        current_source = _source(base, xref, base_length)
        if wanted_source == "null" and current_source == "null":
            # Free or absent on both sides (an object's source is never the bare
            # word ``null``, a stream's is its dictionary): nothing to compare, and
            # no stream flag to read -- the bulk of a table with a long free run.
            continue
        wanted = _record(state, xref, wanted_source)
        current = _record(base, xref, current_source)
        if _same_record(wanted, current):
            continue
        if _RE_CONTAINER.search(current[0]):
            if wanted == _NULL_RECORD or _RE_CONTAINER.search(wanted[0]):
                continue
            raise _Declined("verify_failed")
        if _RE_CONTAINER.search(wanted[0]):
            raise _Declined("verify_failed")
        differing.append(xref)
    return differing


def _identical(
    state: fitz.Document, other: fitz.Document, state_in_use: frozenset[int] | None = None
) -> bool:
    return len(state) == len(other) and not _differing_xrefs(state, other, state_in_use)


def _file_starts_with(path: Path, prefix: bytes, chunk: int = 1 << 20) -> bool:
    """``path``'s first ``len(prefix)`` bytes equal ``prefix`` (``False`` on a short file).

    Compared a chunk at a time: ``prefix`` is the whole signed source, already in
    memory, and reading it back in one piece held a second copy of it at the peak.
    """
    view = memoryview(prefix)
    with path.open("rb") as handle:
        for start in range(0, len(prefix), chunk):
            expected = view[start : start + chunk]
            if handle.read(len(expected)) != expected:
                return False
    return True


def append_state_onto_source(
    state: fitz.Document,
    source_path: str | Path,
    stage_path: str | Path,
    *,
    source_bytes: bytes | None = None,
) -> bool:
    """``True`` when ``try_append_state_onto_source`` wrote ``stage_path``."""
    return try_append_state_onto_source(state, source_path, stage_path, source_bytes=source_bytes) is None


def try_append_state_onto_source(
    state: fitz.Document,
    source_path: str | Path,
    stage_path: str | Path,
    *,
    source_bytes: bytes | None = None,
) -> str | None:
    """Write ``source_path`` + one appended revision holding ``state`` to ``stage_path``.

    ``source_bytes`` replaces the read of ``source_path`` as the signed prefix: a
    caller that knows which part of the file is the revision the session opened
    (F11-FS-1: a foreign program may have appended since) passes exactly that.

    Returns ``None`` when ``stage_path`` holds a file that starts with the exact
    bytes of ``source_path`` and whose every object equals ``state``'s.  Returns
    the decline reason (one of ``DECLINE_REASONS``) and leaves no file at
    ``stage_path`` whenever that cannot be proven: an unsigned source,
    encryption, a different catalog/info object, an unreadable file, or any
    replay/verification failure.
    """
    stage = Path(stage_path)
    try:
        if source_bytes is None:
            source_bytes = Path(source_path).read_bytes()
        stage.write_bytes(source_bytes)
        base = fitz.open(str(stage))
        try:
            reason = _replay_decline(state, base)
            if reason is not None:
                raise _Declined(reason)
            if not document_has_a_signed_signature(base):
                raise _Declined("unsigned_source")
            # The state is not touched between replay and verification, so one
            # census serves both: three censuses per save (state, base, check).
            state_in_use = _in_use_xrefs(state)
            state_length = int(state.xref_length())
            base_length = int(base.xref_length())
            if state_in_use is None:
                declared = max(state_length, base_length)
                if xref_slots_are_unbacked(declared, len(source_bytes)):
                    logger.warning(
                        "signed append save declined for %s: the xref table declares %d slots "
                        "but the file has only %d bytes to back them",
                        source_path,
                        declared,
                        len(source_bytes),
                    )
                    raise _Declined("object_limit")
            growth = state_length - base_length
            if growth > MAX_APPEND_GROWTH_SLOTS:
                logger.warning(
                    "signed append save declined for %s: the document grew by %d xref slots "
                    "(cap %d)",
                    source_path,
                    growth,
                    MAX_APPEND_GROWTH_SLOTS,
                )
                raise _Declined("object_limit")
            while int(base.xref_length()) < state_length:
                base.get_new_xref()
            for xref in _differing_xrefs(state, base, state_in_use):
                obj, raw = _record(state, xref, _source(state, xref, state_length, exact=True))
                write_xref_record(base, xref, obj, raw)
            base.save(str(stage), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        finally:
            base.close()
        if not _file_starts_with(stage, source_bytes):
            raise _Declined("verify_failed")
        check = fitz.open(str(stage))
        try:
            if not _identical(state, check, state_in_use):
                raise _Declined("verify_failed")
        finally:
            check.close()
        return None
    except _Declined as declined:
        logger.debug("signed append save declined for %s: %s", source_path, declined.reason)
        outcome = declined.reason
    except Exception:
        # The traceback as text, never exc_info: its frames hold ``state`` (the
        # live document) and PyMuPDF locals of ``base`` / ``check``; a kept record
        # would keep them, and the staged file, open (LS-3, see ``_in_use_xrefs``).
        # Its last newline is dropped, as logging does for exc_info, so the
        # console shows the same text.
        logger.warning(
            "signed append save failed for %s\n%s",
            source_path,
            traceback.format_exc().removesuffix("\n"),
        )
        outcome = "append_error"
    try:
        stage.unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove staged file %s", stage)
    return outcome
