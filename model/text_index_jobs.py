"""Routing and bookkeeping for the page text index built in the contained child (card A6, D-A6-4/5).

Pure and Qt-free.  Routing is a cost guess, never admission: a page whose content is small is
indexed in-process (the build is short), a larger one goes to the child.  Whether an answer may
be installed is decided by the page's bytes key (``table_objects.key_is_current``), never by a
revision (H3, F1).
"""
from __future__ import annotations

import logging
import re
import weakref
from collections import OrderedDict
from typing import TYPE_CHECKING, Literal

from model import table_objects
from utils import object_probe_platform

if TYPE_CHECKING:
    import fitz

    from model.pdf_model import PDFModel
    from model.text_block import PageIndexEntry

logger = logging.getLogger(__name__)

#: pages whose raw content (page streams plus reachable Form XObjects) is at most this big are
#: indexed in-process (M5: the limit separates a 7.5 KB page from the 1.4 MB+ ones)
TEXT_INLINE_LIMIT_BYTES = 65_536
#: forms visited before the page counts as over the limit
MAX_FORMS_WALKED = 256
MAX_FAILED_KEYS = 256
#: an in-process build slower than this marks the page's bytes key as slow
SLOW_INLINE_BUILD_SECONDS = 0.060

_REF_TEXT = re.compile(r"(\d+)\s+\d+\s+R")

InstallResult = Literal["installed", "already_clean", "stale"]


def _refs(text: str) -> list[int]:
    return [int(num) for num in _REF_TEXT.findall(text)]


def _xobject_refs(doc: fitz.Document, owner: int, *, inherit: bool) -> list[int]:
    """Object numbers in ``/Resources /XObject`` of ``owner`` (a page: through its /Parent chain).
    An inheritance chain deeper than 16 levels is unreadable (``ValueError``), never "no resources"."""
    holder = owner
    for _ in range(16):
        kind, _value = doc.xref_get_key(holder, "Resources")
        if kind != "null":
            break
        if not inherit:
            return []
        parent_kind, parent = doc.xref_get_key(holder, "Parent")
        if parent_kind != "xref":
            return []
        holder = int(parent.split()[0])
    else:
        raise ValueError("resource inheritance is too deep")
    kind, value = doc.xref_get_key(holder, "Resources/XObject")
    if kind == "dict":
        return _refs(value)
    if kind == "xref":
        return _refs(doc.xref_object(int(value.split()[0]), compressed=True))
    return []


def _decoded_length(doc: fitz.Document, xref: int, room: int) -> int:
    """Decoded length of a stream; a stream whose raw bytes already exceed ``room`` is over
    without being decoded.  Unreadable raises."""
    raw = doc.xref_stream_raw(xref)
    if len(raw) > room:
        return len(raw)
    decoded = doc.xref_stream(xref)
    if decoded is None:
        raise ValueError(f"stream {xref} is unreadable")
    return len(decoded)


def text_index_cost_bytes(doc: fitz.Document, page_num: int, limit: int | None = None) -> int:
    """DECODED stream bytes the page's text interpretation reads: its /Contents plus every Form
    XObject reachable from its /Resources (each once; forms are followed through their own
    /Resources; images do not count).  Raw length does not predict the build (a compressed page of
    repeated labels is small raw and slow to interpret).  The walk stops at the first stream that
    takes the sum over ``limit`` and past ``MAX_FORMS_WALKED`` forms, so then the result is only a
    lower bound that is over ``limit``.  An encrypted, unreadable or too deeply inheriting page
    counts as over the limit."""
    if limit is None:
        limit = TEXT_INLINE_LIMIT_BYTES
    over = limit + 1
    try:
        if doc.is_encrypted or (doc.metadata or {}).get("encryption"):
            return over
        page = doc[page_num - 1]
        total = 0
        for xref in page.get_contents():
            total += _decoded_length(doc, xref, limit - total)
            if total > limit:
                return total
        if not page.xref:
            return over  # a direct page dictionary: its resources cannot be read by number
        seen: set[int] = set()
        forms = 0
        pending = _xobject_refs(doc, page.xref, inherit=True)
        while pending:
            xref = pending.pop()
            if xref in seen:
                continue
            seen.add(xref)
            if doc.xref_get_key(xref, "Subtype")[1] != "/Form":
                continue  # an image or a non-form: not interpreted as text
            forms += 1
            if forms > MAX_FORMS_WALKED:
                return max(total, over)
            if not doc.xref_is_stream(xref):
                return over
            total += _decoded_length(doc, xref, limit - total)
            if total > limit:
                return total
            pending.extend(_xobject_refs(doc, xref, inherit=False))
        return total
    except Exception as exc:  # unreadable: the child (or the failed-key path) deals with it
        logger.debug("text index cost of page %s unreadable: %s", page_num, exc)
        return over


#: keys whose child build failed (LRU; the values are unused)
_FAILED: weakref.WeakKeyDictionary[PDFModel, OrderedDict] = weakref.WeakKeyDictionary()


def _failed_keys(model: PDFModel) -> OrderedDict:
    failed = _FAILED.get(model)
    if failed is None:
        failed = OrderedDict()
        _FAILED[model] = failed
    return failed


def mark_failed(model: PDFModel, key: tuple) -> None:
    failed = _failed_keys(model)
    failed[key] = None
    failed.move_to_end(key)
    while len(failed) > MAX_FAILED_KEYS:
        failed.popitem(last=False)


def is_failed(model: PDFModel, key: tuple) -> bool:
    failed = _failed_keys(model)
    if key not in failed:
        return False
    failed.move_to_end(key)
    return True


#: keys whose in-process build was measured slow: routed to the child from then on (outcome
#: feedback: the cost estimate is a guess, so a mis-estimated page is slow at most once)
_SLOW: weakref.WeakKeyDictionary[PDFModel, OrderedDict] = weakref.WeakKeyDictionary()


def _slow_keys(model: PDFModel) -> OrderedDict:
    slow = _SLOW.get(model)
    if slow is None:
        slow = OrderedDict()
        _SLOW[model] = slow
    return slow


def mark_slow(model: PDFModel, key: tuple) -> None:
    slow = _slow_keys(model)
    slow[key] = None
    slow.move_to_end(key)
    while len(slow) > MAX_FAILED_KEYS:
        slow.popitem(last=False)


def is_slow(model: PDFModel, key: tuple) -> bool:
    slow = _slow_keys(model)
    if key not in slow:
        return False
    slow.move_to_end(key)
    return True


def route_reason(
    model: PDFModel, page_num: int, page_input: table_objects.PageInput | None = None
) -> Literal["under_limit", "unsupported", "failed", "child"]:
    """Why a page goes where it goes; ``child`` is the only reason to start a job.  The page's
    scratch copy is built (once, in ``page_input``) only when the key must be looked up: for a big
    page, or for a small one only while some build of this model was measured slow."""
    doc = model.doc
    if not doc or not 1 <= page_num <= len(doc):
        return "under_limit"
    big = text_index_cost_bytes(doc, page_num, TEXT_INLINE_LIMIT_BYTES) > TEXT_INLINE_LIMIT_BYTES
    if not big and not _slow_keys(model):
        return "under_limit"
    if not object_probe_platform.contained_probe_supported():
        return "unsupported"
    key = table_objects._key_or_none(table_objects.page_input_for(model, page_num, page_input))
    if key is None:
        return "failed" if big else "under_limit"
    if not big and not is_slow(model, key):
        return "under_limit"
    return "failed" if is_failed(model, key) else "child"


def route_for_page(
    model: PDFModel, page_num: int, page_input: table_objects.PageInput | None = None
) -> Literal["inline", "child"]:
    """``"inline"`` when the page is small, no contained child exists here, or its key is marked
    failed (or its copy cannot be built); else ``"child"``.  Routing only, never admission."""
    return "child" if route_reason(model, page_num, page_input) == "child" else "inline"


def install_text_index(
    model: PDFModel, job_key: tuple, entry: PageIndexEntry, current: table_objects.PageInput | None = None
) -> InstallResult:
    """Install a child's ``entry`` for the page named by ``job_key`` (D-A6-5).

    ``stale``: the page's bytes are no longer the ones the entry was computed from (nothing is
    written).  ``already_clean``: the index is already clean, so it is kept.  ``installed``: the
    entry was written.  ``ValueError`` from the installer propagates (the caller marks the key
    failed)."""
    if not table_objects.key_is_current(model, job_key, current):
        return "stale"
    page_idx = int(job_key[0]) - 1
    if model.block_manager.page_state(page_idx) == "clean":
        return "already_clean"
    model.block_manager.install_page_entry(page_idx, entry)
    return "installed"
