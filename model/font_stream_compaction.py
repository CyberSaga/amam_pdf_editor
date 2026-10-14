"""Per-operation compaction of the font streams ``insert_htmlbox`` embeds.

MuPDF's Story device embeds every font a rebuild or an add-text box uses as a
raw, unfiltered stream (a CJK ``@font-face`` TTF is ``/Length1 5181580 /Length
5181580`` with no ``/Filter``; the built-in Droid fallback is 3.5 MB) together
with an unfiltered ``/ToUnicode`` CMap, and it embeds a *fresh copy* on every
call: one legacy rebuild with a vertical retry, strategy A/B/C and a push-down
of N blocks inserts up to N+1 copies.  That is what turned a 222 KB file into
5.9 MB.

This module fixes it at creation time, once per OPERATION rather than once per
call:

* ``font_compaction_scope(doc)`` takes the xref watermark when an operation
  starts.  On a *normal* exit it (1) re-points duplicate new
  ``/FontFile``/``/FontFile2``/``/FontFile3`` and ``/ToUnicode`` streams to the
  first identical copy (decoded-bytes hash; only objects at or above the
  watermark, never an object an earlier command could own) and (2) Flate
  compresses each surviving unfiltered stream exactly once.  On an exception it
  does nothing extra -- the caller's rollback runs on an unmodified graph.
* ``insert_htmlbox_tracked`` is the single model-side chokepoint for
  ``Page.insert_htmlbox``: outside a scope it raises, unless the caller says the
  document is a throwaway (``scratch=True``).  ``test_font_stream_compaction``
  carries an AST guard that no other ``.insert_htmlbox(`` call exists under
  ``model/``.  (``view/text_editing.py`` builds a throwaway preview document and
  is deliberately outside that guard.)  It is also where CJK Ext-B characters
  (U+20000 and up, which htmlbox has no font for) get their own spans and an
  in-memory subset of a Windows Ext-B font (``utils.cjk_ext_b_font``,
  EXTB-SUBSET), so every insert and every scratch reference render of the same
  markup draws them identically.

The scope must close BEFORE the command's after-snapshot is captured so redo
restores the compacted bytes.  Compression is lossless and compress-only: the
fonts htmlbox embeds are not subset here (that would take glyphs away from
later true-text edits of rebuilt text; ``fontTools`` is now a pinned runtime
dependency, but only the Ext-B fonts, which are never embedded whole, are
subset -- before the insert, by ``utils.cjk_ext_b_font``).  Original-file
objects are never touched.  Duplicates left behind are unreachable; the
save-time pruning in ``model.save_compaction`` frees them.

No Qt.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import fitz

from model.text_commit.transforms import shift_rect_for_pymupdf_writers
from utils.cjk_ext_b_font import htmlbox_args_with_ext_b

logger = logging.getLogger(__name__)

# Stream-bearing keys: the font programs and the CMap, each its own dedupe
# family (a FontFile3 program is never equal to a ToUnicode CMap, but the
# family keeps the intent explicit).
_TO_UNICODE_KEY = "ToUnicode"
_STREAM_KEYS = ("FontFile", "FontFile2", "FontFile3", _TO_UNICODE_KEY)
_LENGTH_KEYS = ("Length1", "Length2", "Length3")
# ``/Length`` (any value, direct or indirect) -- stripped before comparing two
# stream dictionaries, everything else (``/Length1``, ``/Subtype``) stays.
_RE_PLAIN_LENGTH = re.compile(r"/Length(?![0-9A-Za-z])\s*\d+(?:\s+\d+\s+R)?")
# The value of an ``xref_get_key`` entry of kind ``"xref"`` (``"N G R"``).
_RE_REF_VALUE = re.compile(r"\s*(\d+)\s+\d+\s+R")

# id(doc) -> nesting depth of active scopes.  Keyed by id(): a scope's exit always
# pops its own entry, so a stale id can only collide if a document is closed AND a new
# one allocated at the same address inside one open scope; no current path does that
# (the textbox repair retry swaps the live handle but opens one scope per attempt).
_ACTIVE_SCOPES: dict[int, int] = {}


class FontCompactionScopeError(RuntimeError):
    """``insert_htmlbox_tracked`` was called outside a ``font_compaction_scope``."""


def scope_active(doc: fitz.Document) -> bool:
    """Whether a ``font_compaction_scope`` is currently open on ``doc``."""
    return _ACTIVE_SCOPES.get(id(doc), 0) > 0


@contextmanager
def font_compaction_scope(doc: fitz.Document) -> Iterator[None]:
    """Compact the font streams every ``insert_htmlbox`` inside the block embeds.

    Reentrant: only the outermost scope on a document does the work, so a
    helper that opens its own scope inside a larger operation never compacts
    mid-operation.  Nothing is done when the block raises.
    """
    key = id(doc)
    depth = _ACTIVE_SCOPES.get(key, 0)
    _ACTIVE_SCOPES[key] = depth + 1
    start = int(doc.xref_length()) if depth == 0 else 0
    try:
        yield
    finally:
        if depth == 0:
            _ACTIVE_SCOPES.pop(key, None)
        else:
            _ACTIVE_SCOPES[key] = depth
    if depth == 0:
        try:
            compact_new_font_streams(doc, start)
        except Exception:
            # Compaction is an optimisation of a document that is already
            # valid; a failure must never fail the edit that produced it.
            logger.warning("font stream compaction failed; fonts left as embedded", exc_info=True)


def insert_htmlbox_tracked(
    page: fitz.Page,
    rect: fitz.Rect,
    html: str,
    *,
    scratch: bool = False,
    **kwargs: Any,
) -> tuple[float, float]:
    """``page.insert_htmlbox(rect, html, **kwargs)`` through the one chokepoint.

    Raises ``FontCompactionScopeError`` when no ``font_compaction_scope`` is
    open on ``page.parent`` -- unless ``scratch=True`` (a throwaway measurement
    document that is never saved).  ``TypeError`` for a non-``fitz.Page``.

    CJK Ext-B characters in ``html``'s text nodes are wrapped in their own
    spans and drawn from an in-memory subset of a Windows Ext-B font passed
    through ``archive`` (EXTB-SUBSET); without an installed Ext-B font the
    markup is unchanged and htmlbox draws .notdef, which the rebuild
    verification refuses.
    """
    if not isinstance(page, fitz.Page):
        raise TypeError(f"insert_htmlbox_tracked needs a fitz.Page, got {type(page).__name__}")
    if not scratch and not scope_active(page.parent):
        raise FontCompactionScopeError(
            "insert_htmlbox_tracked outside font_compaction_scope: wrap the "
            "operation in font_compaction_scope(doc) (or pass scratch=True for "
            "a throwaway document)"
        )
    if isinstance(html, str):
        html, kwargs = htmlbox_args_with_ext_b(html, kwargs)
    # F15-G4: `rect` is TRUE unrotated page space; PyMuPDF's htmlbox places it
    # through a page matrix that loses the CropBox/MediaBox origin on /Rotate pages.
    placed = shift_rect_for_pymupdf_writers(page, rect)
    scaled = abs(placed.width - rect.width) > 1e-6 * max(1.0, rect.width) or abs(
        placed.height - rect.height
    ) > 1e-6 * max(1.0, rect.height)
    # Rotated /UserUnit page (F15-G1-UU-ROT): lay out in `rect`, draw into `placed`.
    with _placement_redirect(page, placed if scaled else None):
        return page.insert_htmlbox(rect if scaled else placed, html, **kwargs)


@contextmanager
def _placement_redirect(page: fitz.Page, placed_rect: fitz.Rect | None) -> Iterator[None]:
    """Make ``page.insert_htmlbox`` DRAW into ``placed_rect`` while it lays out in its own rect.

    F15-G1-UU-ROT: on a rotated ``/UserUnit u`` page the placement rect is the
    layout rect scaled by ``1 / u`` (``pymupdf_writer_matrix``), because
    ``show_pdf_page`` reads it through ``~page.transformation_matrix``, which has
    no ``/UserUnit``.  ``insert_htmlbox`` uses ONE rect for both jobs: handing it
    the placement rect would lay the text out in a ``1 / u`` box at its full
    point size (wrong wrapping, wrong fit, glyphs ``u`` times too large once the
    page scales them).  So it is given the layout rect and its single
    ``show_pdf_page`` call (the only place the rect is a position) is redirected
    to the placement rect for the duration of the call; the story is then scaled
    ``placed / layout`` into it, i.e. drawn at the requested point size.  The
    returned ``(spare_height, scale)`` stay in layout (page) units.  Link
    re-insertion inside ``insert_htmlbox`` uses the layout rect, so an ``<a>``
    would land wrong on such a page; no model caller emits one.

    ``None`` is a no-op (every other page).
    """
    if placed_rect is None:
        yield
        return
    original = page.show_pdf_page

    def show_pdf_page_at_placement(_layout: fitz.Rect, *args: Any, **kw: Any) -> int:
        return int(original(placed_rect, *args, **kw))

    page.show_pdf_page = show_pdf_page_at_placement  # type: ignore[method-assign]
    try:
        yield
    finally:
        vars(page).pop("show_pdf_page", None)


def _stream_target(doc: fitz.Document, owner: int, key: str) -> int | None:
    """The xref ``owner``'s ``key`` entry points at, or ``None``."""
    try:
        kind, value = doc.xref_get_key(owner, key)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    if kind != "xref":
        return None
    match = _RE_REF_VALUE.match(value)
    return int(match.group(1)) if match else None


def _is_unfiltered_stream(doc: fitz.Document, xref: int) -> bool:
    try:
        if not doc.xref_is_stream(xref):
            return False
        return doc.xref_get_key(xref, "Filter")[0] == "null"
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return False


def _dict_signature(doc: fitz.Document, xref: int) -> str:
    return _RE_PLAIN_LENGTH.sub("", " ".join(doc.xref_object(xref).split()))


def compact_new_font_streams(doc: fitz.Document, start_xref: int) -> list[int]:
    """Dedupe then Flate-compress the new font streams at ``xref >= start_xref``.

    Returns the xrefs that were compressed (empty when nothing qualified).  Only
    objects at or above ``start_xref`` -- both the owning dictionary and the
    stream -- are ever read for dedupe or written.
    """
    length = int(doc.xref_length())
    start = max(1, int(start_xref))
    if start >= length:
        return []

    # (owner, key, stream xref) for every new FontDescriptor / Font entry.
    entries: list[tuple[int, str, int]] = []
    for owner in range(start, length):
        for key in _STREAM_KEYS:
            target = _stream_target(doc, owner, key)
            if target is not None and target >= start:
                entries.append((owner, key, target))
    if not entries:
        return []

    # 1. Re-point duplicates to the first identical copy.
    first_by_digest: dict[tuple[str, str, str], int] = {}
    survivors: list[int] = []
    for owner, key, target in entries:
        family = _TO_UNICODE_KEY if key == _TO_UNICODE_KEY else "program"
        try:
            digest = hashlib.sha256(doc.xref_stream(target) or b"").hexdigest()
            signature = _dict_signature(doc, target)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            logger.debug("font compaction: stream %s unreadable; skipped", target, exc_info=True)
            continue
        ident = (family, digest, signature)
        first = first_by_digest.setdefault(ident, target)
        if first != target:
            doc.xref_set_key(owner, key, f"{first} 0 R")
        elif target not in survivors:
            survivors.append(target)

    # 2. Compress each surviving unfiltered stream once.
    compressed: list[int] = []
    for xref in survivors:
        if not _is_unfiltered_stream(doc, xref):
            continue
        before = {k: doc.xref_get_key(xref, k) for k in _LENGTH_KEYS}
        decoded = doc.xref_stream(xref) or b""
        doc.update_stream(xref, decoded, compress=True)
        for k, (kind, value) in before.items():
            if kind != "null" and doc.xref_get_key(xref, k) != (kind, value):
                doc.xref_set_key(xref, k, value)
        compressed.append(xref)
    logger.debug(
        "font compaction: %d entries, %d unique streams, %d compressed (xref >= %d)",
        len(entries),
        len(survivors),
        len(compressed),
        start,
    )
    return compressed
