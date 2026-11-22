"""Rule B at run time: the object digest table and the permitted-write comparison (H8, D23).

The only module of the package that reads a document.  ``digest_table`` hashes every object of
the whole document (H22: "one pass"); ``undeclared`` compares two tables against the write set a
commit declared.  The same two functions are what the test oracle calls, so the runtime check and
the oracle cannot drift.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import fitz

from utils.pdf_object_source import xref_object_exact

logger = logging.getLogger(__name__)

TRAILER_KEY = -1  # ``xref_object(-1)`` is the trailer
_LENGTH_TOKEN_RE = re.compile(r"/Length(?![^\s/<>\[\](){}%])\s*\d+(?:\s+\d+\s+R)?")
_CONTAINER_TYPES = frozenset({"/ObjStm", "/XRef"})


@dataclass(frozen=True)
class DigestTable:
    """Digests of one document state.

    ``entries``: per xref (page objects and file containers excluded), 16-byte BLAKE2b of the
    object text (``/Length`` removed) plus the raw stream bytes.  ``pages``: per page object two
    hashes, ``/Contents`` and everything else.  ``containers``: the ``/ObjStm`` and ``/XRef``
    xrefs, kept as one class (a save changes them without changing the document).  ``trailer``:
    the trailer keys other than ``/ID`` and ``/Size``.  ``dangling``: ``(source xref, target xref)``
    for every indirect reference, in the digested objects, to an object that does not exist (D23).
    """

    entries: dict[int, bytes]
    pages: dict[int, tuple[bytes, bytes]]
    trailer: bytes
    containers: frozenset[int]
    xref_length: int
    dangling: frozenset[tuple[int, int]] = frozenset()
    elapsed_ms: float = field(default=0.0, compare=False)


@dataclass(frozen=True)
class WriteSet:
    """What a commit declares it will write: the edited page's ``/Contents`` entry only."""

    page_xref: int
    stream_xrefs: frozenset[int]
    new_xrefs: frozenset[int]


def _h(*parts: bytes) -> bytes:
    h = hashlib.blake2b(digest_size=16)
    for part in parts:
        h.update(len(part).to_bytes(8, "little"))
        h.update(part)
    return h.digest()


def _strip_top_level_length(text: str) -> str:
    """Remove ``/Length ...`` from the outermost dictionary only (not from strings or nested ones)."""
    out: list[str] = []
    stack: list[str] = []  # open containers: 'd' dictionary, 'a' array
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "(":  # literal string, nested parentheses and escapes
            level, j = 0, i
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "(":
                    level += 1
                elif text[j] == ")":
                    level -= 1
                    if level == 0:
                        break
                j += 1
            out.append(text[i : j + 1])
            i = j + 1
            continue
        if text.startswith("<<", i):
            stack.append("d")
            out.append("<<")
            i += 2
            continue
        if text.startswith(">>", i):
            if stack:
                stack.pop()
            out.append(">>")
            i += 2
            continue
        if c == "[":
            stack.append("a")
        elif c == "]":
            if stack:
                stack.pop()
        if c == "<":  # hex string
            j = text.find(">", i)
            j = n - 1 if j < 0 else j
            out.append(text[i : j + 1])
            i = j + 1
            continue
        if c == "%":
            j = text.find("\n", i)
            j = n - 1 if j < 0 else j
            out.append(text[i : j + 1])
            i = j + 1
            continue
        if stack == ["d"] and c == "/":
            m = _LENGTH_TOKEN_RE.match(text, i)
            if m:
                i = m.end()
                continue
        out.append(c)
        i += 1
    return "".join(out)


_WS = " \t\r\n\f\0"
_DELIMS = "()<>[]{}/%"
_REF_TAIL = re.compile(r"\s+\d+\s+R(?![^\s/<>\[\](){}%])")


def _skip_string(text: str, i: int) -> int:
    level = 0
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "(":
            level += 1
        elif text[i] == ")":
            level -= 1
            if level == 0:
                return i + 1
        i += 1
    return n


def _skip_object(text: str, i: int) -> int:
    """End offset of the PDF object that starts at ``i`` (an indirect reference counts as one)."""
    n = len(text)
    c = text[i]
    if text.startswith("<<", i) or c == "[":
        depth = 0
        while i < n:
            if text[i] == "(":
                i = _skip_string(text, i)
                continue
            if text.startswith("<<", i):
                depth += 1
                i += 2
            elif text.startswith(">>", i):
                depth -= 1
                i += 2
            elif text[i] == "[":
                depth += 1
                i += 1
            elif text[i] == "]":
                depth -= 1
                i += 1
            elif text[i] == "<":
                i = text.find(">", i) + 1 or n
            else:
                i += 1
            if depth == 0:
                return i
        return n
    if c == "(":
        return _skip_string(text, i)
    if c == "<":
        return text.find(">", i) + 1 or n
    j = i + 1
    while j < n and text[j] not in _WS and text[j] not in _DELIMS:
        j += 1
    if c != "/" and text[i:j].isdigit():
        m = _REF_TAIL.match(text, j)
        if m:
            return m.end()
    return j


def exact_dict_items(text: str) -> list[tuple[str, str]] | None:
    """Top-level ``(key, value)`` pairs of a printed dictionary, byte-exact: names keep their ``#xx``
    escapes, strings and hex strings are verbatim.  ``None`` when ``text`` is not a dictionary."""
    t = text.strip()
    if not (t.startswith("<<") and t.endswith(">>")):
        return None
    i, end = 2, len(t) - 2
    out: list[tuple[str, str]] = []
    while True:
        while i < end and t[i] in _WS:
            i += 1
        if i >= end:
            return out
        if t[i] != "/":
            return None
        k_end = _skip_object(t, i)
        key = t[i:k_end]
        i = k_end
        while i < end and t[i] in _WS:
            i += 1
        if i >= end:
            return None
        v_end = _skip_object(t, i)
        out.append((key, t[i:v_end]))
        i = v_end


_REF_TOKEN = re.compile(r"(?<![\d.])(\d+)\s+\d+\s+R(?![^\s/<>\[\](){}%])")


def _note_dangling(
    source: int, text: str, limit: int, refs: set[tuple[int, int]], out: set[tuple[int, int]]
) -> None:
    """Collect ``(source, target)`` for each reference in ``text`` (target 0 is a null by rule).  A target
    beyond the table is dangling at once; the others go to ``refs`` and are judged once every slot's
    null status is known (``_resolve_dangling``): no second read of an object."""
    if " R" not in text:
        return
    for m in _REF_TOKEN.finditer(text):
        target = int(m.group(1))
        if target == 0:
            continue
        (out if target >= limit else refs).add((source, target))


def _resolve_dangling(refs: set[tuple[int, int]], nulls: set[int], out: set[tuple[int, int]]) -> None:
    out.update(pair for pair in refs if pair[1] in nulls)


def _object_digest(doc: fitz.Document, xref: int, text: str | None = None) -> bytes:
    if text is None:
        text = xref_object_exact(doc, xref)
    if doc.xref_is_stream(xref):
        text = _strip_top_level_length(text)
        stream = doc.xref_stream_raw(xref) or b""
    else:
        stream = b""
    return _h(text.encode("utf-8", "replace"), stream)


def _key_digest(doc: fitz.Document, xref: int, skip: frozenset[str]) -> bytes:
    """Digest of a dictionary's keys with byte-exact printed values (escaped names and hex strings
    are not decoded), key order ignored."""
    text = xref_object_exact(doc, xref)
    items = exact_dict_items(text)
    if items is None:
        return _h(text.encode("utf-8", "replace"))
    skipped = {"/" + k for k in skip}
    return _h(*(f"{k}\x1f{v}".encode("utf-8", "replace") for k, v in sorted(items) if k not in skipped))


def digest_table(
    doc: fitz.Document,
    *,
    on_yield: Callable[[int, int], None] | None = None,
    yield_every_ms: int = 50,
) -> DigestTable:
    """One pass over every object of ``doc``.

    With ``on_yield`` the pass runs in slices: ``on_yield(done, total)`` is called every
    ``yield_every_ms`` of work (H22).  ``elapsed_ms`` is the work time, without the callbacks.
    """
    total = doc.xref_length()
    steps = total  # xrefs 1..total-1, then the trailer: everything is inside the timed, yielded loop
    entries: dict[int, bytes] = {}
    pages: dict[int, tuple[bytes, bytes]] = {}
    containers: set[int] = set()
    dangling: set[tuple[int, int]] = set()
    refs: set[tuple[int, int]] = set()
    nulls: set[int] = set()  # slots whose object text is ``null`` (a free or deleted object)
    trailer = b""
    work = 0.0
    slice_start = time.perf_counter()
    page_xrefs: set[int] | None = None
    for step in range(1, steps + 1):
        if page_xrefs is None:
            page_xrefs = {doc.page_xref(i) for i in range(len(doc))}
        if step == steps:
            trailer = _key_digest(doc, TRAILER_KEY, frozenset({"ID", "Size"}))
            _note_dangling(TRAILER_KEY, xref_object_exact(doc, TRAILER_KEY), total, refs, dangling)
        else:
            xref = step
            if xref in page_xrefs:
                page_text = xref_object_exact(doc, xref)
                _note_dangling(xref, page_text, total, refs, dangling)
                contents = dict(exact_dict_items(page_text) or []).get("/Contents", "")
                pages[xref] = (
                    _h(contents.encode("utf-8", "replace")),
                    _key_digest(doc, xref, frozenset({"Contents"})),
                )
            else:
                type_kind, type_value = doc.xref_get_key(xref, "Type")
                # a container is a real stream whose /Type is a NAME; a string or a plain dictionary is not
                if type_kind == "name" and type_value in _CONTAINER_TYPES and doc.xref_is_stream(xref):
                    containers.add(xref)
                else:
                    text = xref_object_exact(doc, xref)
                    _note_dangling(xref, text, total, refs, dangling)
                    if text.strip() == "null":
                        nulls.add(xref)
                    entries[xref] = _object_digest(doc, xref, text)
        if on_yield is not None and step < steps and (time.perf_counter() - slice_start) * 1000.0 >= yield_every_ms:
            now = time.perf_counter()
            work += now - slice_start
            on_yield(step, steps)
            slice_start = time.perf_counter()
    _resolve_dangling(refs, nulls, dangling)
    work += time.perf_counter() - slice_start
    if on_yield is not None:
        on_yield(steps, steps)
    return DigestTable(entries, pages, trailer, frozenset(containers), total, frozenset(dangling), max(work * 1000.0, 1e-6))


def undeclared(before: DigestTable, after: DigestTable, write_set: WriteSet) -> list[int]:
    """Xrefs that differ between two tables and are not declared; ``-1`` is the trailer.

    Allowed to differ: the streams in ``write_set.stream_xrefs``, the xrefs in
    ``new_xrefs``, and the ``/Contents`` half of the page object ``write_set.page_xref``.
    """
    bad: set[int] = set()
    for xref in set(before.entries) | set(after.entries):
        a, b = before.entries.get(xref), after.entries.get(xref)
        if a == b:
            continue
        if xref in write_set.stream_xrefs and a is not None and b is not None:
            continue
        if xref in write_set.new_xrefs and a is None:
            continue
        bad.add(xref)
    for xref in set(before.pages) | set(after.pages):
        a2, b2 = before.pages.get(xref), after.pages.get(xref)
        if a2 == b2:
            continue
        if a2 is None or b2 is None:
            bad.add(xref)
        elif a2[1] != b2[1] or (xref != write_set.page_xref and a2[0] != b2[0]):
            bad.add(xref)
    for xref in before.containers ^ after.containers:
        if not (xref in write_set.new_xrefs and xref not in before.containers):
            bad.add(xref)
    low, high = sorted((before.xref_length, after.xref_length))
    for xref in range(low, high):
        if xref not in write_set.new_xrefs:
            bad.add(xref)
    bad.update(source for source, _target in before.dangling ^ after.dangling)  # D23
    if before.trailer != after.trailer:
        bad.add(TRAILER_KEY)
    return sorted(bad)

