"""Copy pages between PDFs together with their navigation data (F16-NAV-3).

``fitz.Document.insert_pdf`` copies page content, explicit GoTo/URI/GoToR/Launch
links and annotations, and nothing else that makes a document navigable:

* the outline (bookmarks), the page labels (``i, ii, 1, 2``) and the named
  destinations (``/Names /Dests`` and the legacy catalog ``/Dests``) are
  document level and are never copied;
* every link whose destination PyMuPDF reports as ``LINK_NAMED`` is dropped.
  In PyMuPDF 1.27 that is not only a named destination: an explicit
  ``[page /Fit]``, ``/FitH``, ``/XYZ null null 0`` destination (what LaTeX and
  Word emit) is reported the same way, so those links vanish too.

A merge, a page export and a page import that go through ``insert_pdf`` alone
therefore silently delete the bookmarks, labels and cross references of every
source (the current document included).  :class:`NavigationGraft` is the one
place that performs the copy and carries the navigation across:

* **outline** - item objects are rebuilt from the source's raw keys (target view,
  ``/C``, ``/F``, collapse state, URI actions) through ``outline_ops`` (the only
  outline writer; never ``set_toc``, see F16-NAV-1);
* **links** - the dropped links are re-created from their raw ``/Rect`` and
  destination, page references re-pointed at the copies;
* **named destinations** - written as one flat sorted ``/Names /Dests`` leaf in
  the target; a name that is already taken by an earlier source is renamed
  (``name.2``) for the later source and the links of that source follow it;
* **page labels** - the per page label of each copied page is re-expressed as
  ``/PageLabels`` rules, so a source without labels placed after a labelled one
  counts ``1, 2, ...`` again instead of continuing the previous range.

Pages that are not copied (page export, import of a page range) are dropped
from all four: no dangling bookmark, link or name to a page the target lacks.

Two kinds of target are supported.  A fresh container (merge, page export,
headless merge) receives everything the sources carry.  An existing document
(``into_existing=True``, Insert pages from file, S17-INSERT-NAV) keeps its own
navigation and receives the source's on top: the source bookmarks are appended
after the document's own, the source's names are merged into the document's name
tree (the document's name wins a clash, the source's is renamed), and the page
labels of the whole document are rebuilt so that every label stays on its page
and the inserted range carries the source's labels.
Navigation is best effort: a malformed outline or name tree is logged and
skipped, it never fails the page copy itself.

Qt-free (model layer).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import fitz

from model import outline_ops

logger = logging.getLogger(__name__)

_WS = frozenset(" \t\r\n\f\0")
_DELIM = frozenset("()<>[]{}/%")
_REF = re.compile(r"(\d+)\s+(\d+)\s+R(?![^\s()<>\[\]{}/%])")
_MAX_DEPTH = 64
_MAX_TREE_DEPTH = 32
_LINK_EXTRA_KEYS = ("Border", "BS", "C", "H", "F")


# ---------------------------------------------------------------------------
# A small reader for the object text PyMuPDF prints (``Document.xref_object``).
# Raw string bytes matter here (a name tree key is compared byte for byte), and
# ``xref_get_key`` returns decoded text, so the objects are parsed directly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tok:
    kind: str  # arr | dict | str | name | ref | atom
    val: Any
    text: str


def _skip_ws(s: str, i: int) -> int:
    n = len(s)
    while i < n and s[i] in _WS:
        i += 1
    return i


def _unescape_name(raw: str) -> str:
    return re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), raw)


_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}


def _parse_literal(s: str, i: int) -> tuple[_Tok, int]:
    start = i
    n = len(s)
    i += 1
    level = 1
    out = bytearray()
    while i < n:
        ch = s[i]
        if ch == "\\":
            i += 1
            if i >= n:
                break
            ch = s[i]
            if ch in _ESCAPES:
                out.append(ord(_ESCAPES[ch]))
            elif ch in "01234567":
                j = i
                while j < n and j < i + 3 and s[j] in "01234567":
                    j += 1
                out.append(int(s[i:j], 8) & 0xFF)
                i = j - 1
            elif ch == "\r":
                if i + 1 < n and s[i + 1] == "\n":
                    i += 1
            elif ch == "\n":
                pass
            else:
                out += ch.encode("latin-1", "replace") if ord(ch) < 256 else ch.encode("utf-8")
        elif ch == "(":
            level += 1
            out.append(ord("("))
        elif ch == ")":
            level -= 1
            if level == 0:
                return _Tok("str", bytes(out), s[start : i + 1]), i + 1
            out.append(ord(")"))
        else:
            out += ch.encode("latin-1") if ord(ch) < 256 else ch.encode("utf-8")
        i += 1
    raise ValueError("unterminated string")


def _parse(s: str, i: int = 0, depth: int = 0) -> tuple[_Tok, int]:
    if depth > _MAX_DEPTH:
        raise ValueError("object nested too deeply")
    n = len(s)
    i = _skip_ws(s, i)
    if i >= n:
        raise ValueError("unexpected end of object")
    start = i
    c = s[i]
    if c == "[":
        i += 1
        items: list[_Tok] = []
        while True:
            i = _skip_ws(s, i)
            if i >= n:
                raise ValueError("unterminated array")
            if s[i] == "]":
                return _Tok("arr", items, s[start : i + 1]), i + 1
            tok, i = _parse(s, i, depth + 1)
            items.append(tok)
    if c == "<":
        if s.startswith("<<", i):
            i += 2
            entries: dict[str, _Tok] = {}
            while True:
                i = _skip_ws(s, i)
                if i >= n:
                    raise ValueError("unterminated dictionary")
                if s.startswith(">>", i):
                    return _Tok("dict", entries, s[start : i + 2]), i + 2
                key, i = _parse(s, i, depth + 1)
                if key.kind != "name":
                    raise ValueError("dictionary key is not a name")
                value, i = _parse(s, i, depth + 1)
                entries[key.val] = value
        end = s.find(">", i)
        if end < 0:
            raise ValueError("unterminated hex string")
        digits = re.sub(r"\s+", "", s[i + 1 : end])
        if len(digits) % 2:
            digits += "0"
        return _Tok("str", bytes.fromhex(digits), s[start : end + 1]), end + 1
    if c == "(":
        return _parse_literal(s, i)
    if c == "/":
        j = i + 1
        while j < n and s[j] not in _WS and s[j] not in _DELIM:
            j += 1
        return _Tok("name", _unescape_name(s[i + 1 : j]), s[start:j]), j
    if c in ")>]{}":
        raise ValueError(f"unexpected {c!r}")
    ref = _REF.match(s, i)
    if ref:
        return _Tok("ref", int(ref.group(1)), ref.group(0)), ref.end()
    j = i
    while j < n and s[j] not in _WS and s[j] not in _DELIM:
        j += 1
    if j == i:
        raise ValueError("empty token")
    return _Tok("atom", s[i:j], s[i:j]), j


def _load(doc: fitz.Document, xref: int) -> _Tok | None:
    try:
        return _parse(doc.xref_object(xref, compressed=True))[0]
    except (ValueError, RuntimeError, fitz.mupdf.FzErrorBase) as exc:
        logger.debug("object %s unreadable: %s", xref, exc)
        return None


def _deref(doc: fitz.Document, tok: _Tok | None) -> _Tok | None:
    for _ in range(8):
        if tok is None or tok.kind != "ref":
            return tok
        tok = _load(doc, tok.val)
    return None


def _has_ref(tok: _Tok) -> bool:
    if tok.kind == "ref":
        return True
    if tok.kind == "arr":
        return any(_has_ref(item) for item in tok.val)
    if tok.kind == "dict":
        return any(_has_ref(item) for item in tok.val.values())
    return False


def _pdf_bytes(raw: bytes) -> str:
    """A PDF string object holding exactly ``raw``."""
    if all(32 <= b < 127 for b in raw):
        text = raw.decode("ascii")
        return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"
    return "<" + raw.hex().upper() + ">"


# ---------------------------------------------------------------------------
# Captured navigation of one copy_pages() call (plain data: the source may be
# closed as soon as the call returns).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Dest:
    page: int  # source page index
    rest: str  # array text after the page reference, e.g. "/XYZ 0 400 null"


@dataclass(frozen=True)
class _NameRef:
    key: bytes


@dataclass(frozen=True)
class _LinkSpec:
    rect: str
    extras: str
    dest: _Dest | _NameRef


@dataclass(frozen=True)
class _OutlineSpec:
    level: int
    title: str
    dest: _Dest | None
    fallback_page: int  # 1-based page get_toc reported, -1 without page target
    uri: str | None
    color: str | None
    flags: str | None
    closed: bool


@dataclass(frozen=True)
class _LabelRow:
    prefix: str
    style: str
    number: int


@dataclass
class _Capture:
    first_copy: dict[int, int] = field(default_factory=dict)  # source page -> target page xref
    copies: list[tuple[int, int]] = field(default_factory=list)  # (source page, target page xref)
    names: dict[bytes, _Dest] = field(default_factory=dict)
    links: dict[int, list[_LinkSpec]] = field(default_factory=dict)
    outline: list[_OutlineSpec] = field(default_factory=list)
    labels: list[_LabelRow] = field(default_factory=list)
    has_labels: bool = False


def _dest_of(
    doc: fitz.Document,
    tok: _Tok | None,
    page_of: dict[int, int],
) -> _Dest | _NameRef | None:
    """A destination value (array, name, string or ``<</D ...>>``) as data."""
    tok = _deref(doc, tok)
    if tok is None:
        return None
    if tok.kind == "dict":
        return _dest_of(doc, tok.val.get("D"), page_of)
    if tok.kind == "arr":
        if not tok.val or tok.val[0].kind != "ref":
            return None
        index = page_of.get(tok.val[0].val)
        if index is None:
            return None
        return _Dest(index, " ".join(item.text for item in tok.val[1:]))
    if tok.kind == "str":
        return _NameRef(tok.val)
    if tok.kind == "name":
        return _NameRef(tok.val.encode("latin-1", "replace"))
    return None


def _read_named_dests(doc: fitz.Document, page_of: dict[int, int]) -> dict[bytes, _Dest]:
    """Every named destination of ``doc`` (catalog ``/Dests`` and ``/Names /Dests``)."""
    found: dict[bytes, _Dest] = {}
    catalog = _load(doc, doc.pdf_catalog())
    if catalog is None or catalog.kind != "dict":
        return found

    legacy = _deref(doc, catalog.val.get("Dests"))
    if legacy is not None and legacy.kind == "dict":
        for name, value in legacy.val.items():
            dest = _dest_of(doc, value, page_of)
            if isinstance(dest, _Dest):
                found[name.encode("latin-1", "replace")] = dest

    names = _deref(doc, catalog.val.get("Names"))
    root = _deref(doc, names.val.get("Dests")) if names is not None and names.kind == "dict" else None
    seen: set[int] = set()

    def walk(node: _Tok | None, depth: int) -> None:
        if node is None or node.kind != "dict" or depth > _MAX_TREE_DEPTH:
            return
        leaf = _deref(doc, node.val.get("Names"))
        if leaf is not None and leaf.kind == "arr":
            for key, value in zip(leaf.val[0::2], leaf.val[1::2]):
                if key.kind != "str":
                    continue
                dest = _dest_of(doc, value, page_of)
                if isinstance(dest, _Dest):
                    found[key.val] = dest
        kids = _deref(doc, node.val.get("Kids"))
        if kids is None or kids.kind != "arr":
            return
        for kid in kids.val:
            if kid.kind == "ref":
                if kid.val in seen:
                    continue
                seen.add(kid.val)
            walk(_deref(doc, kid), depth + 1)

    walk(root, 0)
    return found


def _read_name_entries(doc: fitz.Document) -> tuple[dict[bytes, str], set[bytes]] | None:
    """The raw entries of ``doc``'s ``/Names /Dests`` tree and every name it already uses.

    Returns ``(entries, taken)``: ``entries`` maps a key to the raw value text
    (verbatim, so it can be written back unchanged next to new entries) and
    ``taken`` adds the keys of the legacy catalog ``/Dests`` dictionary.  ``None``
    when the tree cannot be read completely: re-writing a partially read tree
    would lose names.
    """
    catalog = _load(doc, doc.pdf_catalog())
    if catalog is None or catalog.kind != "dict":
        return None
    entries: dict[bytes, str] = {}
    taken: set[bytes] = set()
    legacy = _deref(doc, catalog.val.get("Dests"))
    if legacy is not None and legacy.kind == "dict":
        taken.update(name.encode("latin-1", "replace") for name in legacy.val)
    names_tok = catalog.val.get("Names")
    names = _deref(doc, names_tok)
    if names_tok is not None and names is not None and names.kind != "dict":
        return None
    root = names.val.get("Dests") if names is not None else None
    if root is None:
        return entries, taken
    complete = True
    seen: set[int] = set()

    def walk(tok: _Tok, depth: int) -> None:
        nonlocal complete
        node = _deref(doc, tok)
        if node is None or node.kind != "dict" or depth > _MAX_TREE_DEPTH:
            complete = False
            return
        leaf_tok = node.val.get("Names")
        if leaf_tok is not None:
            leaf = _deref(doc, leaf_tok)
            if leaf is None or leaf.kind != "arr" or len(leaf.val) % 2:
                complete = False
            else:
                for key, value in zip(leaf.val[0::2], leaf.val[1::2]):
                    if key.kind != "str":
                        complete = False
                        continue
                    entries.setdefault(key.val, value.text)
        kids_tok = node.val.get("Kids")
        if kids_tok is None:
            return
        kids = _deref(doc, kids_tok)
        if kids is None or kids.kind != "arr":
            complete = False
            return
        for kid in kids.val:
            if kid.kind == "ref":
                if kid.val in seen:
                    continue
                seen.add(kid.val)
            walk(kid, depth + 1)

    walk(root, 0)
    if not complete:
        return None
    taken.update(entries)
    return entries, taken


def _read_links(
    doc: fitz.Document,
    index: int,
    page_of: dict[int, int],
    run_of: dict[int, int],
) -> list[_LinkSpec]:
    """The links of page ``index`` that ``insert_pdf`` does not copy.

    That is every ``LINK_NAMED`` link, and an explicit GoTo whose target page was
    copied by a different ``insert_pdf`` call than the link's own page
    (``_do_links`` only keeps targets inside the call's page range).
    """
    specs: list[_LinkSpec] = []
    for link in doc[index].get_links():
        kind = link.get("kind")
        if kind == fitz.LINK_GOTO:
            target_page = link.get("page", -1)
            if target_page not in run_of or run_of[target_page] == run_of.get(index):
                continue
        elif kind != fitz.LINK_NAMED:
            continue
        if not link.get("xref"):
            continue
        obj = _load(doc, int(link["xref"]))
        if obj is None or obj.kind != "dict":
            continue
        rect = obj.val.get("Rect")
        if rect is None or rect.kind != "arr" or _has_ref(rect):
            continue
        action = _deref(doc, obj.val.get("A"))
        if action is not None and action.kind == "dict":
            subtype = action.val.get("S")
            if subtype is None or subtype.val != "GoTo":
                continue
            target = action.val.get("D")
        else:
            target = obj.val.get("Dest")
        dest = _dest_of(doc, target, page_of)
        if dest is None:
            continue
        extras = "".join(
            f"/{key} {tok.text}"
            for key in _LINK_EXTRA_KEYS
            if (tok := obj.val.get(key)) is not None and not _has_ref(tok)
        )
        specs.append(_LinkSpec(rect.text, extras, dest))
    return specs


def _read_outline(
    doc: fitz.Document,
    page_of: dict[int, int],
    names: dict[bytes, _Dest],
) -> list[_OutlineSpec]:
    items = outline_ops.outline_items(doc)
    if items is None:
        logger.warning("outline not carried: unpairable outline")
        return []
    specs: list[_OutlineSpec] = []
    for item in items:
        obj = _load(doc, item.xref)
        if obj is None or obj.kind != "dict":
            continue
        dest: _Dest | _NameRef | None = None
        uri: str | None = None
        action = _deref(doc, obj.val.get("A"))
        if action is not None and action.kind == "dict":
            subtype = action.val.get("S")
            kind = subtype.val if subtype is not None else ""
            if kind == "GoTo":
                dest = _dest_of(doc, action.val.get("D"), page_of)
            elif kind == "URI":
                target = _deref(doc, action.val.get("URI"))
                if target is not None and target.kind == "str":
                    uri = target.text
        else:
            dest = _dest_of(doc, obj.val.get("Dest"), page_of)
        resolved = names.get(dest.key) if isinstance(dest, _NameRef) else dest
        color = obj.val.get("C")
        flags = obj.val.get("F")
        count = obj.val.get("Count")
        specs.append(
            _OutlineSpec(
                level=item.level,
                title=item.title,
                dest=resolved,
                fallback_page=item.page,
                uri=uri,
                color=color.text if color is not None and color.kind == "arr" and not _has_ref(color) else None,
                flags=flags.text if flags is not None and flags.kind == "atom" else None,
                closed=count is not None and count.kind == "atom" and count.text.startswith("-"),
            )
        )
    return specs


def _text_string(raw: bytes) -> str:
    """Decode a PDF text string (UTF-16BE/LE or UTF-8 with BOM, else Latin-1)."""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", "replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", "replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    return raw.decode("latin-1")


def _read_label_rules(doc: fitz.Document) -> list[tuple[int, str, str, int]]:
    """``/PageLabels`` rules as (start page, prefix, style, first number), sorted.

    Read from the raw number tree: ``Document.get_page_labels`` returns a prefix
    written as a UTF-16 hex string undecoded, which would be written back wrong.
    """
    catalog = _load(doc, doc.pdf_catalog())
    if catalog is None or catalog.kind != "dict":
        return []
    root = _deref(doc, catalog.val.get("PageLabels"))
    rules: list[tuple[int, str, str, int]] = []
    seen: set[int] = set()

    def walk(node: _Tok | None, depth: int) -> None:
        if node is None or node.kind != "dict" or depth > _MAX_TREE_DEPTH:
            return
        nums = _deref(doc, node.val.get("Nums"))
        if nums is not None and nums.kind == "arr":
            for key, value in zip(nums.val[0::2], nums.val[1::2]):
                rule = _deref(doc, value)
                if key.kind != "atom" or rule is None or rule.kind != "dict":
                    continue
                try:
                    start = int(key.text)
                except ValueError:
                    continue
                prefix = rule.val.get("P")
                style = rule.val.get("S")
                first = rule.val.get("St")
                try:
                    number = int(first.text) if first is not None and first.kind == "atom" else 1
                except ValueError:
                    number = 1
                rules.append(
                    (
                        start,
                        _text_string(prefix.val) if prefix is not None and prefix.kind == "str" else "",
                        style.val if style is not None and style.kind == "name" else "",
                        number,
                    )
                )
        kids = _deref(doc, node.val.get("Kids"))
        if kids is None or kids.kind != "arr":
            return
        for kid in kids.val:
            if kid.kind == "ref":
                if kid.val in seen:
                    continue
                seen.add(kid.val)
            walk(_deref(doc, kid), depth + 1)

    walk(root, 0)
    return sorted(rules, key=lambda rule: rule[0])


def _read_labels(doc: fitz.Document, count: int) -> tuple[list[_LabelRow], bool]:
    """Per page label rows of ``doc`` and whether it defines labels at all."""
    rules = _read_label_rules(doc)
    rows: list[_LabelRow] = []
    for index in range(count):
        rule = None
        for candidate in rules:
            if candidate[0] <= index:
                rule = candidate
        if rule is not None:
            start, prefix, style, first = rule
            rows.append(_LabelRow(prefix, style, first + index - start))
        elif rules:
            rows.append(_LabelRow("", "", 1))  # before the first rule: no label
        else:
            rows.append(_LabelRow("", "D", index + 1))  # no labels: physical numbering
    return rows, bool(rules)


def _runs(pages: Sequence[int]) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    for page in pages:
        if runs and page == runs[-1][1] + 1:
            runs[-1][1] = page
        else:
            runs.append([page, page])
    return [(first, last) for first, last in runs]


class NavigationGraft:
    """Copy pages into ``dst`` and carry their navigation data (see module doc).

    ``copy_pages`` may be called once per source; ``finish`` writes the outline,
    labels, names and links once all pages are in.  ``keep_names=False`` turns a
    link to a named destination into an explicit destination instead of writing a
    name tree.  ``dst`` is expected to be a fresh container for the default
    flags: they replace its page labels and write the name tree as one flat leaf.

    ``into_existing=True`` is for a ``dst`` that already has navigation of its own
    (Insert pages from file): its name tree and legacy ``/Dests`` names are read
    before the first page is inserted, a source name that clashes is renamed
    (``name.2``) and the document's entries are written back verbatim beside the
    new ones; the page labels of the whole document are rebuilt from the labels
    each page had before the insert (a page that had none keeps the number it
    showed).  A navigation tree the graft cannot read completely is left alone
    (``keep_names`` falls back to explicit destinations, labels are not rewritten).
    """

    def __init__(
        self,
        dst: fitz.Document,
        *,
        keep_names: bool = True,
        outline: bool = True,
        labels: bool = True,
        into_existing: bool = False,
    ) -> None:
        self._dst = dst
        self._keep_names = keep_names
        self._outline = outline
        self._labels = labels
        self._into_existing = into_existing
        self._captures: list[_Capture] = []
        self._snapshotted = False
        self._existing_names: dict[bytes, str] = {}
        self._taken_names: set[bytes] = set()
        self._existing_rows: dict[int, _LabelRow] = {}
        self._existing_has_labels = False

    def _snapshot_existing(self) -> None:
        """Read the navigation ``dst`` already has, before the first page is inserted."""
        self._snapshotted = True
        if self._keep_names:
            try:
                read = _read_name_entries(self._dst)
                kind = self._dst.xref_get_key(self._dst.pdf_catalog(), "Names")[0]
            except Exception:
                logger.warning("named destinations of the document unreadable", exc_info=True)
                read, kind = None, ""
            if read is None or kind not in ("null", "dict"):
                logger.warning("named destinations not imported: the document's name tree is unsupported")
                self._keep_names = False
            else:
                self._existing_names, self._taken_names = read
        if self._labels:
            try:
                rows, self._existing_has_labels = _read_labels(self._dst, len(self._dst))
                self._existing_rows = {self._dst.page_xref(i): row for i, row in enumerate(rows)}
            except Exception:
                logger.warning("page labels of the document unreadable; left unchanged", exc_info=True)
                self._labels = False

    def copy_pages(
        self,
        src: fitz.Document,
        pages: Sequence[int] | None = None,
        start_at: int | None = None,
    ) -> list[int]:
        """Insert ``pages`` (0-based, in the order given; all when ``None``).

        Returns the 0-based target indices of the inserted pages.
        """
        wanted = list(range(len(src))) if pages is None else list(pages)
        if not wanted:
            return []
        if self._into_existing and not self._snapshotted:
            self._snapshot_existing()
        position = len(self._dst) if start_at is None else start_at
        first_target = position
        run_of: dict[int, int] = {}
        for number, (first, last) in enumerate(_runs(wanted)):
            self._dst.insert_pdf(src, from_page=first, to_page=last, start_at=position)
            logger.debug("inserted source pages %d-%d at position %d", first + 1, last + 1, position + 1)
            position += last - first + 1
            for page in range(first, last + 1):
                run_of.setdefault(page, number)
        targets = list(range(first_target, first_target + len(wanted)))
        try:
            self._captures.append(self._capture(src, wanted, targets, run_of))
        except Exception:  # navigation is best effort; the pages are already in
            logger.warning("navigation of a copied source could not be read", exc_info=True)
        return targets

    def _capture(
        self,
        src: fitz.Document,
        wanted: list[int],
        targets: list[int],
        run_of: dict[int, int],
    ) -> _Capture:
        capture = _Capture()
        for source_index, target_index in zip(wanted, targets):
            xref = self._dst.page_xref(target_index)
            capture.copies.append((source_index, xref))
            capture.first_copy.setdefault(source_index, xref)
        page_of = {src.page_xref(i): i for i in range(len(src))}
        for source_index in capture.first_copy:
            try:
                links = _read_links(src, source_index, page_of, run_of)
            except Exception:
                logger.warning("links of page %d not carried", source_index + 1, exc_info=True)
                continue
            if links:
                capture.links[source_index] = links
        # The name table is only needed to carry names, or to resolve a named link:
        # an import into a document that keeps its own names skips reading the tree.
        needs_names = self._keep_names or self._outline or any(
            isinstance(spec.dest, _NameRef) for specs in capture.links.values() for spec in specs
        )
        if needs_names:
            try:
                capture.names = _read_named_dests(src, page_of)
            except Exception:
                logger.warning("named destinations not carried", exc_info=True)
        if self._outline:
            try:
                capture.outline = _read_outline(src, page_of, capture.names)
            except Exception:
                logger.warning("outline not carried", exc_info=True)
        if self._labels:
            try:
                rows, capture.has_labels = _read_labels(src, len(src))
                capture.labels = [rows[source_index] for source_index, _xref in capture.copies]
            except Exception:
                logger.warning("page labels not carried", exc_info=True)
        return capture

    # -- writing -----------------------------------------------------------

    def finish(self) -> None:
        """Write the captured navigation into ``dst`` (call once, after the last copy)."""
        renames = self._rename_maps()
        steps = [("links", lambda: self._write_links(renames))]
        if self._keep_names:
            steps.append(("named destinations", lambda: self._write_names(renames)))
        if self._outline:
            steps.append(("outline", self._write_outline))
        if self._labels:
            steps.append(("page labels", self._write_labels))
        for label, step in steps:
            try:
                step()
            except Exception:
                logger.warning("%s not written", label, exc_info=True)

    def _rename_maps(self) -> list[dict[bytes, bytes]]:
        """Per capture: source name -> unique name in the target (first source wins)."""
        taken: set[bytes] = set(self._taken_names)
        maps: list[dict[bytes, bytes]] = []
        for capture in self._captures:
            mapping: dict[bytes, bytes] = {}
            for key, dest in capture.names.items():
                if dest.page not in capture.first_copy:
                    continue
                final = key
                counter = 2
                while final in taken:
                    final = key + b"." + str(counter).encode("ascii")
                    counter += 1
                taken.add(final)
                mapping[key] = final
            maps.append(mapping)
        return maps

    @staticmethod
    def _array(page_xref: int, rest: str) -> str:
        return f"[{page_xref} 0 R{' ' + rest if rest else ''}]"

    def _write_names(self, renames: list[dict[bytes, bytes]]) -> None:
        entries: list[tuple[bytes, str]] = []
        for capture, mapping in zip(self._captures, renames):
            for key, final in mapping.items():
                dest = capture.names[key]
                entries.append((final, self._array(capture.first_copy[dest.page], dest.rest)))
        if not entries:
            return
        entries.extend(self._existing_names.items())
        catalog = self._dst.pdf_catalog()
        existing = self._dst.xref_get_key(catalog, "Names")
        if existing[0] not in ("null", "dict"):
            logger.warning("named destinations not written: unsupported /Names object")
            return
        entries.sort(key=lambda entry: entry[0])
        leaf = self._dst.get_new_xref()
        body = "".join(f"{_pdf_bytes(key)}{value}" for key, value in entries)
        self._dst.update_object(leaf, f"<</Names[{body}]>>")
        if existing[0] == "null":
            self._dst.xref_set_key(catalog, "Names", f"<</Dests {leaf} 0 R>>")
        else:
            self._dst.xref_set_key(catalog, "Names/Dests", f"{leaf} 0 R")

    def _link_destination(
        self,
        capture: _Capture,
        mapping: dict[bytes, bytes],
        dest: _Dest | _NameRef,
    ) -> str | None:
        if isinstance(dest, _Dest):
            target = capture.first_copy.get(dest.page)
            return None if target is None else self._array(target, dest.rest)
        named = capture.names.get(dest.key)
        if named is not None and named.page not in capture.first_copy:
            return None  # the destination page was not copied
        if named is None and self._into_existing:
            return None  # a name the source does not define must not bind to the document's own
        if self._keep_names:
            return _pdf_bytes(mapping.get(dest.key, dest.key))
        if named is None:
            return None
        return self._array(capture.first_copy[named.page], named.rest)

    def _write_links(self, renames: list[dict[bytes, bytes]]) -> None:
        added: dict[int, list[int]] = {}
        for capture, mapping in zip(self._captures, renames):
            for source_index, page_xref in capture.copies:
                for spec in capture.links.get(source_index, []):
                    target = self._link_destination(capture, mapping, spec.dest)
                    if target is None:
                        continue
                    border = "" if ("/Border" in spec.extras or "/BS" in spec.extras) else "/Border[0 0 0]"
                    annot = self._dst.get_new_xref()
                    self._dst.update_object(
                        annot,
                        f"<</Type/Annot/Subtype/Link{border}/Rect{spec.rect}{spec.extras}"
                        f"/A<</S/GoTo/D{target}>>>>",
                    )
                    added.setdefault(page_xref, []).append(annot)
        for page_xref, annots in added.items():
            self._append_annots(page_xref, annots)

    def _append_annots(self, page_xref: int, annots: list[int]) -> None:
        refs = " ".join(f"{xref} 0 R" for xref in annots)
        kind, value = self._dst.xref_get_key(page_xref, "Annots")
        if kind == "array":
            inner = value.strip()[1:-1].strip()
            self._dst.xref_set_key(page_xref, "Annots", f"[{inner} {refs}]")
        elif kind == "xref":
            holder = int(value.split()[0])
            text = self._dst.xref_object(holder, compressed=True).strip()
            if text.startswith("[") and text.endswith("]"):
                self._dst.update_object(holder, f"[{text[1:-1].strip()} {refs}]")
            else:
                self._dst.update_object(holder, f"[{refs}]")
        else:
            self._dst.xref_set_key(page_xref, "Annots", f"[{refs}]")

    def _write_outline(self) -> None:
        items: list[outline_ops.ImportedItem] = []
        for capture in self._captures:
            for spec in capture.outline:
                dest = spec.dest
                if dest is None and spec.fallback_page >= 1 and spec.uri is None:
                    dest = _Dest(spec.fallback_page - 1, "/Fit")
                page_xref = None
                view = ""
                if dest is not None:
                    page_xref = capture.first_copy.get(dest.page)
                    if page_xref is None:
                        continue  # bookmark to a page that was not copied
                    view = dest.rest
                items.append(
                    outline_ops.ImportedItem(
                        level=spec.level,
                        title=spec.title,
                        page_xref=page_xref,
                        view=view,
                        uri=spec.uri,
                        color=spec.color,
                        flags=spec.flags,
                        closed=spec.closed,
                    )
                )
        outline_ops.append_items(self._dst, items)

    def _label_rows(self) -> list[tuple[int, _LabelRow]]:
        """(page index, label row) of every page whose label is written."""
        index_of = {self._dst.page_xref(i): i for i in range(len(self._dst))}
        inserted = {
            xref: row
            for capture in self._captures
            for (_source, xref), row in zip(capture.copies, capture.labels)
        }
        if not self._into_existing:
            return sorted(((index_of[xref], row) for xref, row in inserted.items()), key=lambda pair: pair[0])
        rows: list[tuple[int, _LabelRow]] = []
        for index in range(len(self._dst)):
            xref = self._dst.page_xref(index)
            row = inserted.get(xref) or self._existing_rows.get(xref) or _LabelRow("", "D", index + 1)
            rows.append((index, row))
        return rows

    def _write_labels(self) -> None:
        if not (self._existing_has_labels or any(capture.has_labels for capture in self._captures)):
            return
        rules: list[tuple[int, str]] = []
        previous: _LabelRow | None = None
        for index, row in self._label_rows():
            continues = (
                previous is not None
                and (previous.prefix, previous.style) == (row.prefix, row.style)
                and row.number == previous.number + 1
            )
            previous = row
            if continues:
                continue
            parts = []
            if row.prefix:
                parts.append(f"/P{fitz.get_pdf_str(row.prefix)}")
            if row.style:
                parts.append(f"/S/{row.style}")
            if row.number > 1:
                parts.append(f"/St {row.number}")
            rules.append((index, f"<<{''.join(parts)}>>"))
        nums = " ".join(f"{index}{body}" for index, body in rules)
        self._dst.xref_set_key(self._dst.pdf_catalog(), "PageLabels", f"<</Nums[{nums}]>>")
