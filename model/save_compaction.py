"""Save-time pruning helpers: find the objects a save would only carry as garbage.

Undo leaves the objects a command created in the live document
(``page_snapshot.restore_page_graph`` writes only the snapshot's own records
back), and a legacy rebuild leaves its Redact annotation, old content stream
and font resources unreachable even when it is kept.  Writing them out is what
turned a 222 KB file into 5.9 MB.  ``PDFModel`` therefore saves non-secure full
rewrites with ``garbage=1`` (frees unreachable objects, keeps the numbering,
never touches the live document) and uses this module to decide whether an
*incremental* save would append such objects (see
``PDFModel._session_orphans_block_incremental``).

Reachability deliberately over-approximates (every ``N G R`` anywhere in an
object's dictionary counts, strings included): a false "reachable" only keeps an
object, a false "unreachable" would be the dangerous direction.

No Qt.  The scan is bounded by ``doc.xref_length()`` -- never by the trailer
``/Size``, which the in-memory trailer keeps stale after objects are added.
"""

from __future__ import annotations

import logging
import re

import fitz

logger = logging.getLogger(__name__)

# An incremental save falls back to the pruned full save only when the objects
# the session created and left unreachable carry at least this many raw stream
# bytes.  Smaller orphans (e.g. the content stream ``clean_contents`` replaces
# at save time) are not worth giving up the append-only revision.
ORPHAN_FALLBACK_MIN_BYTES = 64 * 1024

_RE_REF = re.compile(r"(\d+)\s+\d+\s+R(?![A-Za-z0-9])")
# Containers a reference-only walk can never reach but a writer needs.
_RE_NEVER_ORPHAN = re.compile(r"/Type\s*/(?:ObjStm|XRef)\b|/Linearized\b")


def _object_text(doc: fitz.Document, xref: int) -> str:
    """The object's source (a stream's dictionary only); ``"null"`` when unreadable."""
    try:
        return doc.xref_object(xref)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return "null"


def reachable_xrefs(doc: fitz.Document) -> set[int]:
    """Every xref reachable from the trailer (``/Root``, ``/Info``, ``/Encrypt``, ...)."""
    length = int(doc.xref_length())
    seen: set[int] = set()
    stack = [int(m) for m in _RE_REF.findall(doc.pdf_trailer())]
    while stack:
        xref = stack.pop()
        if xref in seen or not 0 < xref < length:
            continue
        seen.add(xref)
        stack.extend(int(m) for m in _RE_REF.findall(_object_text(doc, xref)))
    return seen


def unreachable_xrefs(doc: fitz.Document, *, from_xref: int = 1) -> list[int]:
    """Live, non-container xrefs in ``[from_xref, xref_length)`` nothing refers to."""
    length = int(doc.xref_length())
    start = max(1, int(from_xref))
    if start >= length:
        return []
    reachable = reachable_xrefs(doc)
    out: list[int] = []
    for xref in range(start, length):
        if xref in reachable:
            continue
        text = _object_text(doc, xref)
        if text.strip() == "null" or _RE_NEVER_ORPHAN.search(text):
            continue
        out.append(xref)
    return out


def orphan_stream_bytes(doc: fitz.Document, xrefs: list[int]) -> int:
    """Total raw stream bytes held by ``xrefs`` (non-streams count as zero)."""
    total = 0
    for xref in xrefs:
        try:
            if doc.xref_is_stream(xref):
                total += len(doc.xref_stream_raw(xref) or b"")
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            continue
    return total


def session_orphan_stream_bytes(doc: fitz.Document, base_xref: int) -> int:
    """Raw stream bytes of the unreachable objects created since ``base_xref``."""
    orphans = unreachable_xrefs(doc, from_xref=base_xref)
    total = orphan_stream_bytes(doc, orphans)
    if orphans:
        logger.debug(
            "save compaction: %d session orphan(s) at xref >= %d carry %d stream bytes",
            len(orphans),
            base_xref,
            total,
        )
    return total
