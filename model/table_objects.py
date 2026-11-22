"""Ruled tables as page objects (docs/to_Update.md line 34, owner decision 2026-11-05).

A table found by PyMuPDF's ``Page.find_tables`` is one OBJECT for select and
delete in 操作物件 mode; its cell text stays ordinary text for the edit-text tool.
Tables are not movable or resizable (that would rewrite every cell).

* ``find_tables`` reports bboxes in the VISUAL (rotated) page frame (measured,
  PyMuPDF 1.27); deletion works in the unrotated frame through
  ``page.derotation_matrix``.
* A grid that covers most of the page (a CAD sheet frame, an ECC/HVAC title
  border) is never a table object: one click must not select, and one Delete
  must not wipe, a whole drawing.
* Detection costs 10-300 ms per page, so results are cached per page.  The cache key is the
  page's own analysis input: ``PageInput`` builds the one-page scratch copy that detection reads
  (in the GUI process or in the probe child) and the key ends with the SHA-256 of those bytes, so
  anything detection can see, a Form XObject reached through ``N 1 R`` included, changes the key
  by construction and no revision counter or hand-kept list stands in for it (owner decision,
  CAD handoff 2026-11-19).  The key is ``(page, sha256(copy))`` and nothing else (owner decision
  2026-11-19, review F1): the copy already carries /Rotate and the boxes, and detection reads
  nothing but its bytes, so a save, Save As or snapshot restore (a new handle, the same bytes)
  keeps every answer.
* Entries do not name handles.  Memory is bounded by an LRU cap of ``MAX_CACHED_PAGES`` entries
  per model for the answers and again for the failed marks (a hit moves an entry to the end, the
  oldest is evicted past the cap); two tabs may hold the same page number with other bytes.
  ``retire_dead_handles`` only clears both stores once no handle is live.

Qt-free (Model layer).
"""
from __future__ import annotations

import hashlib
import logging
import re
import weakref
from collections import OrderedDict
from typing import TYPE_CHECKING

import fitz

from utils.pdf_object_source import exact_set_key, xref_object_exact, xref_set_key_exact

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)

TABLE_OBJECT_KIND = "table"
#: A detected grid larger than this share of the page is a sheet frame, not a table.
MAX_TABLE_PAGE_FRACTION = 0.6
#: Ruling strokes extend past the cell bbox by half their width; the redaction for
#: line art grows by this much so the outer border counts as "covered".
TABLE_STROKE_MARGIN_PT = 2.0
_MIN_ROWS = 2
_MIN_COLS = 2


#: Per model and per store (answers, failed marks): the most recently used pages kept.
MAX_CACHED_PAGES = 256

_CACHES: weakref.WeakKeyDictionary[PDFModel, OrderedDict] = weakref.WeakKeyDictionary()


def _cache(model: PDFModel) -> OrderedDict:
    cache = _CACHES.get(model)
    if cache is None:
        cache = OrderedDict()
        _CACHES[model] = cache
    return cache


_REF = re.compile(r"(\d+) (\d+) R")
_LENGTH = re.compile(r"/Length \d+(?: \d+ R)?")


def _rewrite_refs(text: str, fn) -> str:
    """``text`` with each indirect reference ``N G R`` replaced by ``fn(N)``.

    Strings (``(..)`` with escapes and nesting, ``<hex>``) and comments are skipped, so a name or a
    label that reads like a reference is not one; any generation number counts.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "(":
            depth, j = 1, i + 1
            while j < n and depth:
                if text[j] == "\\":
                    j += 1
                elif text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                j += 1
            out.append(text[i:j])
            i = j
        elif c == "<":
            if text[i : i + 2] == "<<":
                out.append("<<")
                i += 2
            else:
                j = text.find(">", i)
                j = n if j < 0 else j + 1
                out.append(text[i:j])
                i = j
        elif c == "%":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(text[i:j])
            i = j
        elif c.isdigit() and (i == 0 or text[i - 1] in " \t\r\n[]<>/()"):
            m = _REF.match(text, i)
            if m:
                out.append(fn(int(m.group(1))))
                i = m.end()
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _scan_pdf_text(text: str) -> tuple[str, list[int]]:
    """(``text`` with every reference replaced by ``R``, the referenced numbers in order)."""
    refs: list[int] = []

    def note(num: int) -> str:
        refs.append(num)
        return "R"

    return _rewrite_refs(text, note), refs


class _Pairing:
    """Source object number <-> copy object number, one to one (a collapse or a split is a mismatch)."""

    def __init__(self, src: fitz.Document, dst: fitz.Document) -> None:
        self.src, self.dst = src, dst
        self.forward: dict[int, int] = {}
        self.backward: dict[int, int] = {}

    def pair_refs(self, stext: str, dtext: str, what: str) -> None:
        # a stream's /Length (direct or indirect) is the stored length: encryption and the writer
        # change it, the page does not
        sskel, srefs = _scan_pdf_text(_LENGTH.sub("/Length", stext))
        dskel, drefs = _scan_pdf_text(_LENGTH.sub("/Length", dtext))
        if sskel != dskel or len(srefs) != len(drefs):
            raise ValueError(f"scratch copy does not mirror the source at {what}")
        for a, b in zip(srefs, drefs):
            self.pair(a, b, what)

    def pair(self, a: int, b: int, what: str) -> None:
        if self.forward.get(a, b) != b or self.backward.get(b, a) != a:
            raise ValueError(f"scratch copy pairs two objects with one at {what}")
        if a in self.forward:
            return
        self.forward[a], self.backward[b] = b, a
        self.pair_refs(
            xref_object_exact(self.src, a, compressed=True), xref_object_exact(self.dst, b, compressed=True), f"{a}/{b}"
        )


def _effective_resources(doc: fitz.Document, page_xref: int) -> tuple[str, str]:
    """(kind, value) of the page's /Resources, inherited from a /Pages ancestor when the page has none."""
    node = page_xref
    for _ in range(64):
        kind, value = doc.xref_get_key(node, "Resources")
        if kind != "null":
            return kind, value
        parent = doc.xref_get_key(node, "Parent")
        if parent[0] != "xref":
            break
        node = int(parent[1].split()[0])
    return "null", ""


# Bounds on the pieces of the optional-content configuration inlined into one scratch copy.
_OC_INLINE_PIECES = 512
_OC_INLINE_CHARS = 262_144


def _carry_ocproperties(src: fitz.Document, page_num: int, data: bytes) -> bytes:
    """``data`` with the source catalog's default optional-content configuration for the page's groups.

    ``insert_pdf`` copies the groups but not the catalog /OCProperties, so a group that is OFF in
    the source would be ON in the copy (A6.0 M6).  The page's /Resources (own or inherited) and /OC
    are walked in both documents in lockstep (``insert_pdf`` rewrites only reference numbers) to pair
    each source group with its copy, one to one; never by object text, two groups can read the same.
    The source's default configuration /D is rewritten with the paired numbers (BaseState, ON, OFF,
    /AS, /Order, /RBGroups); groups the page does not reach are dropped from its arrays.  A copy
    that does not mirror the source raises.  A page without optional content returns ``data``.
    """
    cat = src.pdf_catalog()
    kind, ocp = src.xref_get_key(cat, "OCProperties")
    if kind == "null":
        return data
    ocp_text = xref_object_exact(src, int(ocp.split()[0]), compressed=True) if kind == "xref" else ocp
    dst = fitz.open("pdf", data)
    try:
        pairing = _Pairing(src, dst)
        spage, dpage = src[page_num - 1].xref, dst[0].xref
        sk, sv = _effective_resources(src, spage)
        dk, dv = dst.xref_get_key(dpage, "Resources")
        if sk != dk:
            if sk == "null" and dk == "null":
                pass
            else:
                raise ValueError("scratch copy does not mirror the source page /Resources")
        if sk == "xref":
            pairing.pair(int(sv.split()[0]), int(dv.split()[0]), "/Resources")
        elif sk == "dict":
            pairing.pair_refs(sv, dv, "/Resources")
        okind, oval = src.xref_get_key(spage, "OC")
        dokind, doval = dst.xref_get_key(dpage, "OC")
        if okind != dokind:
            raise ValueError("scratch copy does not mirror the source page /OC")
        if okind == "xref":
            pairing.pair(int(oval.split()[0]), int(doval.split()[0]), "/OC")
        ocg_numbers = set(src.get_ocgs())
        mapped = {x: pairing.forward[x] for x in ocg_numbers if x in pairing.forward}
        if not mapped:
            return data
        # The configuration text, its references renumbered; a reference to a group the page does
        # not reach is dropped (arrays stay valid), any other reference makes the page unreadable.

        budget = {"pieces": _OC_INLINE_PIECES, "chars": _OC_INLINE_CHARS}

        def renumber(num: int, depth: int = 0) -> str:
            if num in mapped:
                return f"{mapped[num]} 0 R"
            if num in ocg_numbers:
                return ""  # a group of another page
            if depth > 8 or src.xref_is_stream(num):
                raise ValueError("optional-content configuration references an unreadable object")
            # an indirect piece of the configuration (a /D or /Configs dictionary kept apart):
            # inlined, so the copy needs no object of its own for it
            # shared references are inlined once per mention: a budget bounds the pieces and the text, so
            # a small graph with wide fan-out cannot grow into billions of references (H23 finding 8)
            budget["pieces"] -= 1
            if budget["pieces"] < 0:
                raise ValueError("optional-content configuration is too large to carry")
            piece = _rewrite_refs(xref_object_exact(src, num, compressed=True), lambda n: renumber(n, depth + 1))
            budget["chars"] -= len(piece)
            if budget["chars"] < 0:
                raise ValueError("optional-content configuration is too large to carry")
            return piece

        xref_set_key_exact(dst, dst.pdf_catalog(), "OCProperties", _rewrite_refs(ocp_text, renumber))
        return dst.tobytes(no_new_id=True)
    finally:
        dst.close()


def scratch_page_bytes(doc: fitz.Document, page_num: int) -> bytes:
    """One-page PDF copy of 1-based ``page_num``; the source is never touched (H1).

    ``annots``, ``links`` and ``widgets`` must all be off: with any of them on,
    ``insert_pdf`` changes objects of the source document (measured).  ``no_new_id=True`` makes the
    bytes of an unchanged page identical from one build to the next (measured, PyMuPDF 1.27), which
    is what lets ``PageInput.key`` hash them.
    """
    scratch = fitz.open()
    try:
        scratch.insert_pdf(
            doc,
            from_page=page_num - 1,
            to_page=page_num - 1,
            annots=False,
            links=False,
            widgets=False,
        )
        data = scratch.tobytes(no_new_id=True)
    finally:
        scratch.close()
    return _carry_ocproperties(doc, page_num, data)


class PageInput:
    """Lazy holder of the one-page scratch copy of 1-based ``page_num`` of ``model``'s document.

    The copy is built once, on the first use of ``payload`` or ``key``: ``payload`` is the exact
    bytes table detection reads (the worker gets these), and ``key`` is the cache key built from
    them: ``(page_num, sha256(payload))``.  The copy carries /Rotate and the boxes, so the digest
    follows everything detection reads by construction (H3); the handle is not part of the key (F1).

    A failed build (the copy raises, no document, a page out of range) makes ``key`` and
    ``payload`` raise.  A build failure is logged once and remembered, so the build is not retried
    inside the holder.  Callers treat it as "analysis failed for now": nothing is cached as "no
    tables" and nothing is stored under any key.

    One holder is one moment: do not keep it across a document change.  An answer that arrives
    later is compared with a holder built at that time, never with the one of the request.
    """

    def __init__(self, model: PDFModel, page_num: int) -> None:
        self.model = model
        self.page_num = int(page_num)
        self._built: tuple[bytes, tuple] | None = None
        self._error: Exception | None = None

    def _ensure(self) -> tuple[bytes, tuple]:
        if self._built is not None:
            return self._built
        if self._error is not None:
            raise self._error
        doc = self.model.doc
        if doc is None:
            raise ValueError("no document is open")
        if not 1 <= self.page_num <= len(doc):
            raise ValueError(f"page {self.page_num} is out of range")
        try:
            payload = scratch_page_bytes(doc, self.page_num)
            key = (self.page_num, hashlib.sha256(payload).digest())
        except Exception as exc:
            logger.warning("table page input failed on page %s: %s", self.page_num, exc)
            self._error = exc
            raise
        self._built = (payload, key)
        return self._built

    @property
    def payload(self) -> bytes:
        return self._ensure()[0]

    @property
    def key(self) -> tuple:
        return self._ensure()[1]


def frame_key(model: PDFModel, page_num: int) -> tuple:
    """Cache key of the page's analysis input (H3): ``PageInput(model, page_num).key``.

    ``(page_num, sha256(one-page scratch copy))``: no handle generation and no ``id(doc)`` (CPython
    reuses the address of a closed document, D1, but two documents with other page bytes have other
    keys, and with the same bytes the answer is the same).  A writer that skips every revision tick
    cannot leave a stale answer current.  Raises when the copy cannot be built.
    """
    return PageInput(model, page_num).key


def page_input_for(model: PDFModel, page_num: int, page_input: PageInput | None) -> PageInput:
    """``page_input`` when it is for this model and page, else a new (still unbuilt) one."""
    if page_input is not None and page_input.model is model and page_input.page_num == int(page_num):
        return page_input
    return PageInput(model, page_num)


def _key_or_none(page_input: PageInput) -> tuple | None:
    try:
        return page_input.key
    except Exception:  # logged by PageInput; "analysis failed for now"
        return None


class TableDetectionFailed(Exception):
    """``find_tables`` reported failure (returned ``None``); never the same as "no tables"."""


def page_has_table_text(page: fitz.Page) -> bool:
    """Repeat ``find_tables``' own text step: does any table box have non-whitespace text?

    ``cells_to_tables`` drops every table whose box holds only whitespace, so a page with no
    text can have no table.  ``page`` is a scratch page, never the live one.  Every global and
    page property touched is restored in ``finally``.
    """
    import pymupdf.table as pytable

    old_small = bool(fitz.TOOLS.set_small_glyph_heights())
    fitz.TOOLS.set_small_glyph_heights(True)
    rotated: tuple | None = None
    try:
        if page.rotation != 0:
            cropbox = fitz.Rect(page.cropbox)
            page, xref, rot, mediabox = pytable.page_rotation_set0(page)
            rotated = (xref, rot, mediabox, cropbox)
        try:
            page.get_layout()
            if page.layout_information:
                return True  # the layout path is never short-cut
            textpage = page.get_textpage(flags=pytable.FLAGS)
            return not pytable.white_spaces.issuperset(textpage.extractText())
        finally:
            if rotated is not None:
                # The library's reset restores /Rotate and the MediaBox but not the CropBox.
                page = pytable.page_rotation_reset(page, *rotated[:3])
                with exact_set_key(page.parent):
                    page.set_cropbox(rotated[3])
    finally:
        fitz.TOOLS.set_small_glyph_heights(old_small)


def find_table_rects(page: fitz.Page) -> list[tuple[float, float, float, float]]:
    """Table bboxes found on ``page`` (the caller passes a scratch page).

    No ``try``: a library failure raises (``TableDetectionFailed`` for a ``None`` result) so the
    caller can tell "no tables" from "analysis failed".
    """
    if not page_has_table_text(page):
        return []
    finder = page.find_tables()
    if finder is None:
        raise TableDetectionFailed("find_tables returned None")
    rects: list[tuple[float, float, float, float]] = []
    page_area = max(1.0, float(page.rect.width) * float(page.rect.height))
    for table in finder.tables:
        if table.row_count < _MIN_ROWS or table.col_count < _MIN_COLS:
            continue
        rect = fitz.Rect(table.bbox)
        if rect.is_empty or rect.width * rect.height > MAX_TABLE_PAGE_FRACTION * page_area:
            continue
        rects.append(tuple(rect))
    return rects


def cached_table_rects(
    model: PDFModel, page_num: int, page_input: PageInput | None = None
) -> list[fitz.Rect] | None:
    """Cached rectangles for the page as it is now; ``None`` on a miss (no detection).

    Looking up builds the page's scratch copy (or reuses ``page_input``'s).  ``None`` also when the
    copy cannot be built: that is never an answer.
    """
    doc = model.doc
    if not doc or page_num < 1 or page_num > len(doc):
        return None
    key = _key_or_none(page_input_for(model, page_num, page_input))
    if key is None:
        return None
    cache = _cache(model)
    cached = cache.get(key)
    if cached is None:
        return None
    cache.move_to_end(key)
    return [fitz.Rect(r) for r in cached]


#: keys whose analysis failed (LRU; the values are unused)
_FAILED: weakref.WeakKeyDictionary[PDFModel, OrderedDict] = weakref.WeakKeyDictionary()


def _failed_keys(model: PDFModel) -> OrderedDict:
    failed = _FAILED.get(model)
    if failed is None:
        failed = OrderedDict()
        _FAILED[model] = failed
    return failed


def key_is_current(model: PDFModel, key: tuple, current: PageInput | None = None) -> bool:
    """True while ``key`` is the key of its page as it is now (H3, D1).

    An answer arrives at another time, so ``key`` is compared with a freshly built copy of the page
    (one new copy), never with the key of the request.  ``current`` is such a copy, built by the
    caller at answer time, so that one answer builds one copy.  A page that cannot be read now is
    not current.
    """
    return _key_is_current(model, key, current)


def _key_is_current(model: PDFModel, key: tuple, current: PageInput | None = None) -> bool:
    doc = model.doc
    page_num = key[0]
    if not doc or not 1 <= page_num <= len(doc):
        return False
    return key == _key_or_none(page_input_for(model, page_num, current))


def _trim(store: OrderedDict) -> None:
    """Evict the least recently used entries past ``MAX_CACHED_PAGES``."""
    while len(store) > MAX_CACHED_PAGES:
        store.popitem(last=False)


def retire_dead_handles(model: PDFModel) -> None:
    """Clear both stores when no handle is live any more; otherwise do nothing (D1, F1).

    Entries do not name handles: the key is the page bytes, so a replaced handle with the same
    bytes keeps its answers.  Memory is bounded by the LRU cap ``MAX_CACHED_PAGES`` per store, not
    by retirement.  The model calls this when it replaces or closes a handle.
    """
    if not model.live_handle_generations():
        _cache(model).clear()
        _failed_keys(model).clear()


def _put(model: PDFModel, key: tuple, rects) -> None:
    cache = _cache(model)
    cache[key] = [tuple(r) for r in rects]
    cache.move_to_end(key)
    _trim(cache)
    _failed_keys(model).pop(key, None)


def mark_table_analysis_failed(model: PDFModel, key: tuple, current: PageInput | None = None) -> None:
    """Remember that analysis failed for ``key``; a stale key is dropped (as ``store_table_rects``)."""
    if _key_is_current(model, key, current):
        failed = _failed_keys(model)
        failed[key] = None
        failed.move_to_end(key)
        _trim(failed)


def table_analysis_failed(model: PDFModel, page_num: int, page_input: PageInput | None = None) -> bool:
    """True when the page as it is now is marked as failed, or its copy cannot be built.

    A copy that cannot be built is "analysis failed for now": nothing is stored for it (no key to
    store under), and the next call tries again.
    """
    doc = model.doc
    if not doc or page_num < 1 or page_num > len(doc):
        return False
    key = _key_or_none(page_input_for(model, page_num, page_input))
    if key is None:
        return True
    failed = _failed_keys(model)
    if key not in failed:
        return False
    failed.move_to_end(key)
    return True


def store_table_rects(model: PDFModel, key: tuple, rects, current: PageInput | None = None) -> bool:
    """Store ``rects`` under ``key``; ``True`` only if ``key`` is still the page's key now.

    ``current`` as in ``key_is_current``.
    """
    if not _key_is_current(model, key, current):
        return False
    _put(model, key, rects)
    return True


def table_rects(model: PDFModel, page_num: int, page_input: PageInput | None = None) -> list[fitz.Rect]:
    """Visual-frame bboxes of the table objects on 1-based ``page_num``."""
    doc = model.doc
    if not doc or page_num < 1 or page_num > len(doc):
        return []
    page_input = page_input_for(model, page_num, page_input)
    cached = cached_table_rects(model, page_num, page_input)
    if cached is not None:
        return cached
    # Never on the live page: find_tables resets /Rotate and the MediaBox of a
    # rotated page while it works and does not restore a CropBox exactly
    # (measured, PyMuPDF 1.27.1), so a hit-test click would edit the document.
    # A one-page scratch copy keeps rotation and boxes, hence the same frame.
    # Detection runs on ``page_input.payload``, the bytes the key was hashed from.
    rects: list[tuple[float, float, float, float]] = []
    try:
        key = page_input.key
        with fitz.open(stream=page_input.payload, filetype="pdf") as scratch:
            rects = find_table_rects(scratch[0])
    except Exception as exc:  # a failure is never cached as "no tables"
        logger.debug("table detection failed on page %s: %s", page_num, exc)
        return []
    # Synchronous: nothing could change the page since the key was built, so no second check.
    _put(model, key, rects)
    return [fitz.Rect(r) for r in rects]


def table_object_id(page_num: int, rect: fitz.Rect) -> str:
    return f"table:{int(page_num)}:{rect.x0:.2f},{rect.y0:.2f},{rect.x1:.2f},{rect.y1:.2f}"


def parse_table_object_id(object_id: str) -> tuple[int, fitz.Rect] | None:
    try:
        prefix, page, coords = str(object_id).split(":", 2)
        if prefix != TABLE_OBJECT_KIND:
            return None
        x0, y0, x1, y1 = (float(v) for v in coords.split(","))
        return int(page), fitz.Rect(x0, y0, x1, y1)
    except (ValueError, TypeError):
        return None


def table_at_point(
    model: PDFModel, page_num: int, point: fitz.Point, page_input: PageInput | None = None
) -> fitz.Rect | None:
    """The smallest table object containing visual ``point``, if any."""
    hits = [r for r in table_rects(model, page_num, page_input) if fitz.Point(point) in r]
    if not hits:
        return None
    return min(hits, key=lambda r: r.width * r.height)


def matching_table(model: PDFModel, page_num: int, rect: fitz.Rect, tolerance: float = 1.0) -> fitz.Rect | None:
    """The table object on the page that is still where ``rect`` says, if any."""
    for found in table_rects(model, page_num):
        if all(abs(a - b) <= tolerance for a, b in zip(found, rect)):
            return found
    return None


def erase_table(page: fitz.Page, visual_rect: fitz.Rect) -> fitz.Rect:
    """Remove the text and ruling lines inside the table; returns the unrotated rect.

    Text: characters overlapping the table rect.  Line art: only paths fully
    covered by the rect grown by ``TABLE_STROKE_MARGIN_PT`` (neighbouring rules
    and drawings that merely touch it stay).  Images are kept.
    """
    unrotated = fitz.Rect(visual_rect) * page.derotation_matrix
    unrotated.normalize()
    text_rect = fitz.Rect(unrotated)
    art_rect = fitz.Rect(unrotated) + (
        -TABLE_STROKE_MARGIN_PT,
        -TABLE_STROKE_MARGIN_PT,
        TABLE_STROKE_MARGIN_PT,
        TABLE_STROKE_MARGIN_PT,
    )
    # Two passes so text and line art each get their own extent: the grown rect
    # is for strokes only and must not take characters just outside the table.
    # add_*_annot geometry is UNROTATED page space (PITFALLS, rotated annotations).
    page.add_redact_annot(text_rect, fill=False, cross_out=False)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )
    page.add_redact_annot(art_rect, fill=False, cross_out=False)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
        text=fitz.PDF_REDACT_TEXT_NONE,
    )
    return unrotated
