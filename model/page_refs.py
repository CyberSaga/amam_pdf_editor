"""Repoint or drop every reference to a page that stops existing (F16-NAV-1a).

``Document.delete_page`` removes a page from the page tree and, through
``_remove_dest_range``, the *explicit* link annotations that point at it.  It
does not touch anything that reaches the page by name or from the catalog:

* ``/Names /Dests`` entries and the legacy catalog ``/Dests`` dictionary keep the
  dead ``[page /XYZ ...]`` array;
* a link whose ``/A /D`` or ``/Dest`` is a *string* naming such an entry
  survives (PyMuPDF hands the bare name to ``fz_resolve_link``, which wants a
  URI, so the link never resolves to a page and is skipped), and jumps nowhere;
* ``/OpenAction`` keeps pointing at the dead page.

Worse than the dead jump: those references keep the deleted page object, with
its ``/Contents``, reachable, so a ``garbage`` save writes the deleted page's
content into the file.

:func:`repoint_page_references` is the one chokepoint for a page that is
deleted (``mapping[old_xref] = None``: its names, the links that use them and a
matching ``/OpenAction`` are dropped, as PyMuPDF already drops explicit links)
or replaced by another page object (``mapping[old_xref] = new_xref``: straighten
swaps only the page reference, the view and the name stay).  It reads and writes
raw objects through the reader of :mod:`model.navigation_graft` (never
``resolve_names``, which memoizes), edits only the objects that must change, and
leaves every unrelated destination, link and name as it was.

Qt-free (model layer).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import fitz

from model.navigation_graft import (
    _MAX_TREE_DEPTH,
    _read_name_entries,
    _Tok,
    _char_bytes,
    _deref,
    _load,
    _name_bytes,
    _name_key,
    _parse,
    _pdf_bytes,
)
from utils.pdf_object_source import xref_set_key_exact
from utils.pymupdf_refs import sync_open_pages

logger = logging.getLogger(__name__)

_REGULAR_NAME_CHARS = frozenset(
    chr(c) for c in range(33, 127) if chr(c) not in "()<>[]{}/%#"
)


@dataclass
class RepointResult:
    """What :func:`repoint_page_references` changed (counts) and could not read."""

    names_removed: int = 0
    names_swapped: int = 0
    links_removed: int = 0
    links_swapped: int = 0
    open_action_changed: bool = False
    unsupported: tuple[str, ...] = ()
    # Names that no longer exist -> object number of the removed page they named.
    dropped_name_pages: dict[bytes, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(
            self.names_removed
            or self.names_swapped
            or self.links_removed
            or self.links_swapped
            or self.open_action_changed
        )


@dataclass(frozen=True)
class _Verdict:
    kind: str  # keep | drop | swap
    text: str | None = None  # swap: the new text of the destination value
    owner: int | None = None  # swap: object number that holds ``text`` as its whole body


_KEEP = _Verdict("keep")
_DROP = _Verdict("drop")


def _name_literal(name: str) -> str:
    """``name`` as a PDF name object (``#xx`` for anything outside the regular set)."""
    out = ["/"]
    for ch in name:
        if ch in _REGULAR_NAME_CHARS:
            out.append(ch)
        else:
            out.extend(f"#{byte:02X}" for byte in _char_bytes(ch))
    return "".join(out)


def _owner(tok: _Tok | None) -> int | None:
    """The object number an indirect value lives in; ``None`` for a direct value."""
    return int(tok.val) if tok is not None and tok.kind == "ref" else None


def _store(doc: fitz.Document, owner: int | None, holder: int, key: str, body: str) -> None:
    """Write ``body`` where the value lives: its own object, else at ``key`` of ``holder``."""
    if owner is not None:
        doc.update_object(owner, body)
    else:
        xref_set_key_exact(doc, holder, key, body)


def _swap_first_ref(text: str, old: int, new: int) -> str | None:
    """``text`` (a destination array, or a ``<</D [...]>>`` dict) with ``old`` -> ``new``."""
    body = text.lstrip()
    if body.startswith("["):
        pattern = re.compile(rf"^(\[\s*){old}\s+0\s+R(?![^\s()<>\[\]{{}}/%])")
    elif body.startswith("<<"):
        pattern = re.compile(rf"(/D\s*\[\s*){old}\s+0\s+R(?![^\s()<>\[\]{{}}/%])")
    else:
        return None
    swapped, count = pattern.subn(lambda m: f"{m.group(1)}{new} 0 R", body, count=1)
    return swapped if count else None


def _explicit_page(doc: fitz.Document, tok: _Tok | None) -> int | None:
    """Object number of the page an explicit destination (array or ``<</D>>``) names."""
    tok = _deref(doc, tok)
    if tok is not None and tok.kind == "dict":
        tok = _deref(doc, tok.val.get("D"))
    if tok is not None and tok.kind == "arr" and tok.val and tok.val[0].kind == "ref":
        return int(tok.val[0].val)
    return None


class _Context:
    """The mapping plus the names that ended up undefined, shared by every site."""

    def __init__(self, doc: fitz.Document, mapping: Mapping[int, int | None]) -> None:
        self.doc = doc
        self.mapping = mapping
        self.dead_names: set[bytes] = set()
        self.result = RepointResult()
        self.unsupported: list[str] = []

    def forget_name(self, key: bytes, value: _Tok) -> None:
        """Note that the entry ``key`` -> ``value`` is being removed."""
        self.dead_names.add(key)
        page = _explicit_page(self.doc, value)
        if page is not None:
            self.result.dropped_name_pages.setdefault(key, page)

    def judge(self, tok: _Tok | None) -> _Verdict:
        """Verdict for a destination value: explicit array, ``<</D>>``, name or string."""
        resolved = _deref(self.doc, tok)
        if resolved is None:
            return _KEEP
        key = _name_key(resolved)
        if key is not None:
            return _DROP if key in self.dead_names else _KEEP
        page = _explicit_page(self.doc, resolved)
        if page is None or page not in self.mapping:
            return _KEEP
        new = self.mapping[page]
        if new is None:
            return _DROP
        text = _swap_first_ref(resolved.text, page, new)
        if text is None:
            return _KEEP
        return _Verdict("swap", text, _owner(tok))


# ---------------------------------------------------------------------------
# Named destinations
# ---------------------------------------------------------------------------


def _apply_swap(ctx: _Context, verdict: _Verdict, original: _Tok) -> str:
    """The text to keep for a swapped value; an indirect target is edited in place."""
    assert verdict.text is not None
    if verdict.owner is not None:
        ctx.doc.update_object(verdict.owner, verdict.text)
        return original.text
    return verdict.text


def _edit_name_pairs(
    ctx: _Context,
    pairs: list[tuple[_Tok, _Tok]],
    key_of: Callable[[_Tok], bytes | None],
) -> tuple[list[tuple[_Tok, str]], int, int]:
    """Judge ``(key, value)`` pairs; returns the surviving ``(key, value text)``, the drop and the swap count.

    ``key_of`` gives the name a dropped entry is remembered by (``None``: not remembered).
    """
    kept: list[tuple[_Tok, str]] = []
    dropped = swapped = 0
    for key, value in pairs:
        verdict = ctx.judge(value)
        if verdict.kind == "drop":
            dropped += 1
            name = key_of(key)
            if name is not None:
                ctx.forget_name(name, value)
            continue
        text = value.text
        if verdict.kind == "swap":
            text = _apply_swap(ctx, verdict, value)
            swapped += 1
        kept.append((key, text))
    return kept, dropped, swapped


@dataclass
class _Subtree:
    low: bytes | None = None
    high: bytes | None = None
    count: int = 0
    changed: bool = False

    def take(self, key: bytes) -> None:
        self.count += 1
        if self.low is None or key < self.low:
            self.low = key
        if self.high is None or key > self.high:
            self.high = key

    def merge(self, other: _Subtree) -> None:
        self.count += other.count
        self.changed = self.changed or other.changed
        if other.low is not None and (self.low is None or other.low < self.low):
            self.low = other.low
        if other.high is not None and (self.high is None or other.high > self.high):
            self.high = other.high


def _visit_name_node(
    ctx: _Context,
    xref: int,
    depth: int,
    seen: set[int],
) -> _Subtree:
    """Edit one node of the ``/Names /Dests`` tree in place; returns its key range."""
    sub = _Subtree()
    node = _load(ctx.doc, xref)
    if node is None or node.kind != "dict" or depth > _MAX_TREE_DEPTH:
        ctx.unsupported.append(f"name tree node {xref}")
        return sub
    leaf_tok = node.val.get("Names")
    if leaf_tok is not None:
        leaf = _deref(ctx.doc, leaf_tok)
        if leaf is None or leaf.kind != "arr" or len(leaf.val) % 2:
            ctx.unsupported.append(f"name tree leaf {xref}")
        else:
            pairs = list(zip(leaf.val[0::2], leaf.val[1::2]))
            kept, dropped, swapped = _edit_name_pairs(
                ctx, pairs, lambda key: bytes(key.val) if key.kind == "str" else None
            )
            ctx.result.names_removed += dropped
            ctx.result.names_swapped += swapped
            for key, _text in kept:
                if key.kind == "str":
                    sub.take(bytes(key.val))
            sub.changed = bool(dropped)
            if dropped or swapped:
                body = "[" + " ".join(f"{key.text} {text}" for key, text in kept) + "]"
                _store(ctx.doc, _owner(leaf_tok), xref, "Names", body)
    kids_tok = node.val.get("Kids")
    if kids_tok is not None:
        kids = _deref(ctx.doc, kids_tok)
        if kids is None or kids.kind != "arr":
            ctx.unsupported.append(f"name tree kids {xref}")
        else:
            kept_kids: list[str] = []
            for kid in kids.val:
                if kid.kind != "ref" or kid.val in seen:
                    kept_kids.append(kid.text)
                    continue
                seen.add(int(kid.val))
                child = _visit_name_node(ctx, int(kid.val), depth + 1, seen)
                sub.merge(child)
                if child.changed and child.count == 0:
                    continue  # an emptied subtree leaves the tree
                kept_kids.append(kid.text)
            if len(kept_kids) != len(kids.val):
                _store(ctx.doc, _owner(kids_tok), xref, "Kids", "[" + " ".join(kept_kids) + "]")
    if sub.changed and "Limits" in node.val and sub.low is not None and sub.high is not None:
        xref_set_key_exact(ctx.doc, xref, "Limits", f"[{_pdf_bytes(sub.low)}{_pdf_bytes(sub.high)}]")
    return sub


def _repoint_name_tree(ctx: _Context, catalog: _Tok) -> None:
    """Edit the ``/Names /Dests`` tree in place."""
    names = _deref(ctx.doc, catalog.val.get("Names"))
    root = names.val.get("Dests") if names is not None and names.kind == "dict" else None
    if root is None:
        return
    if root.kind != "ref":
        # A tree written inline in the catalog has no object to edit in place.
        resolved = _deref(ctx.doc, root)
        if resolved is None or resolved.kind != "dict" or _tree_mentions(ctx, resolved):
            ctx.unsupported.append("inline /Names /Dests tree")
        return
    _visit_name_node(ctx, int(root.val), 0, {int(root.val)})


def _tree_mentions(ctx: _Context, tok: _Tok) -> bool:
    """True when an inline tree holds a destination that would be changed, or has ``/Kids``.

    An inline tree has no object to edit in place below its root, so either
    makes the tree unsupported.
    """
    leaf = _deref(ctx.doc, tok.val.get("Names"))
    if leaf is not None and leaf.kind == "arr":
        for value in leaf.val[1::2]:
            if ctx.judge(value).kind != "keep":
                return True
    return tok.val.get("Kids") is not None


def _repoint_legacy_dests(ctx: _Context, catalog: _Tok) -> None:
    """Edit the catalog ``/Dests`` dictionary (PDF 1.1 named destinations)."""
    tok = catalog.val.get("Dests")
    legacy = _deref(ctx.doc, tok)
    if legacy is None or legacy.kind != "dict":
        return
    kept: list[str] = []
    dropped = 0
    swapped = 0
    for name, value in legacy.val.items():
        verdict = ctx.judge(value)
        if verdict.kind == "drop":
            dropped += 1
            ctx.forget_name(_name_bytes(name), value)
            continue
        text = value.text
        if verdict.kind == "swap":
            text = _apply_swap(ctx, verdict, value)
            swapped += 1
        kept.append(f"{_name_literal(name)} {text}")
    ctx.result.names_swapped += swapped
    ctx.result.names_removed += dropped
    if not dropped and not swapped:
        return
    _store(ctx.doc, _owner(tok), ctx.doc.pdf_catalog(), "Dests", "<<" + " ".join(kept) + ">>")


# ---------------------------------------------------------------------------
# Links and actions
# ---------------------------------------------------------------------------


def _goto_slot(
    ctx: _Context,
    holder: int,
    key: str,
    tok: _Tok,
) -> tuple[int, str, _Tok] | None:
    """Where the destination of an action-or-destination value ``tok`` lives.

    Returns ``(object number, key path, destination token)`` so that a changed
    destination can be written back (see :func:`_write_dest`); ``None`` for an action
    that is not a GoTo.  ``tok`` is the value stored at ``key`` of ``holder``.
    """
    if tok.kind == "ref":
        action = _load(ctx.doc, int(tok.val))
        owner, path = int(tok.val), "D"
    else:
        action, owner, path = tok, holder, f"{key}/D"  # an inline action dictionary
    if action is None or action.kind != "dict" or "S" not in action.val:
        return holder, key, tok  # a destination (array, name, string or <</D>>) itself
    if action.val["S"].val != "GoTo" or "D" not in action.val:
        return None
    return owner, path, action.val["D"]


def _write_dest(ctx: _Context, slot: tuple[int, str, _Tok], verdict: _Verdict) -> None:
    """Store a swapped destination in the ``slot`` :func:`_goto_slot` found."""
    assert verdict.text is not None
    _store(ctx.doc, verdict.owner, slot[0], slot[1], verdict.text)


def _annot_refs(doc: fitz.Document, page_xref: int) -> tuple[list[_Tok], int | None] | None:
    """The tokens of a page's ``/Annots`` array and the holder object (``None`` if inline)."""
    kind, value = doc.xref_get_key(page_xref, "Annots")
    holder: int | None = None
    try:
        if kind == "xref":
            holder = int(value.split()[0])
            tok = _load(doc, holder)
        elif kind == "array":
            tok = _parse(value)[0]
        else:
            return None
    except (ValueError, RuntimeError):
        return None
    if tok is None or tok.kind != "arr":
        return None
    return list(tok.val), holder


def _repoint_links(ctx: _Context) -> bool:
    """Drop or repoint the GoTo links of every page.

    True when a link, widget action or destination was changed (open pages
    need a sync), not only when a page's ``/Annots`` array was rewritten.
    """
    doc = ctx.doc
    touched = False
    for index in range(len(doc)):
        page_xref = doc.page_xref(index)
        listed = _annot_refs(doc, page_xref)
        if listed is None:
            continue
        tokens, holder = listed
        kept: list[str] = []
        dropped = 0
        for tok in tokens:
            if tok.kind != "ref":
                kept.append(tok.text)
                continue
            xref = int(tok.val)
            is_link = doc.xref_get_key(xref, "Subtype")[1] == "/Link"
            if not is_link and doc.xref_get_key(xref, "A")[0] == "null":
                kept.append(tok.text)  # no action to repoint: skip the parse (big documents)
                continue
            annot = _load(doc, xref)
            if annot is None or annot.kind != "dict":
                kept.append(tok.text)
                continue
            verdict, slot = _judge_annotation(ctx, xref, annot, is_link)
            if verdict.kind == "drop":
                if is_link:
                    dropped += 1
                    ctx.result.links_removed += 1
                    continue
                xref_set_key_exact(doc, xref, "A", "null")  # a widget keeps working, minus its jump
                ctx.result.links_removed += 1
                touched = True
            elif verdict.kind == "swap" and slot is not None:
                _write_dest(ctx, slot, verdict)
                ctx.result.links_swapped += 1
                touched = True
            kept.append(tok.text)
        if dropped:
            _store(doc, holder, page_xref, "Annots", "[" + " ".join(kept) + "]")
            touched = True
    return touched


def _judge_annotation(
    ctx: _Context,
    xref: int,
    annot: _Tok,
    is_link: bool,
) -> tuple[_Verdict, tuple[int, str, _Tok] | None]:
    """Verdict and write slot of the GoTo destination an annotation carries."""
    action = annot.val.get("A")
    if action is not None:
        slot = _goto_slot(ctx, xref, "A", action)
        if slot is not None:
            return ctx.judge(slot[2]), slot
        return _KEEP, None  # URI / Launch / JavaScript ... never touched
    dest = annot.val.get("Dest")
    if dest is not None and is_link:
        return ctx.judge(dest), (xref, "Dest", dest)
    return _KEEP, None


def _repoint_open_action(ctx: _Context, catalog: _Tok) -> None:
    tok = catalog.val.get("OpenAction")
    if tok is None:
        return
    catalog_xref = ctx.doc.pdf_catalog()
    slot = _goto_slot(ctx, catalog_xref, "OpenAction", tok)
    if slot is None:
        return
    verdict = ctx.judge(slot[2])
    if verdict.kind == "drop":
        xref_set_key_exact(ctx.doc, catalog_xref, "OpenAction", "null")
        ctx.result.open_action_changed = True
    elif verdict.kind == "swap":
        _write_dest(ctx, slot, verdict)
        ctx.result.open_action_changed = True


def repoint_page_references(
    doc: fitz.Document,
    mapping: Mapping[int, int | None],
) -> RepointResult:
    """Drop (``None``) or repoint (new page object number) references to pages.

    ``mapping`` is keyed by the object number of the page that goes away.  Call
    it while that page object still exists in the page tree or right after
    ``delete_page`` (it only compares object numbers).  Best effort per site:
    an unreadable tree is reported in ``unsupported`` and left alone.
    """
    ctx = _Context(doc, mapping)
    if not mapping:
        return ctx.result
    catalog = _load(doc, doc.pdf_catalog())
    if catalog is None or catalog.kind != "dict":
        ctx.result.unsupported = ("catalog",)
        return ctx.result

    def run(label: str, step: Callable[[], object]) -> object:
        """One best-effort step: a failure is logged and reported in ``unsupported``."""
        try:
            return step()
        except Exception:
            logger.warning("page references in the %s not repointed", label, exc_info=True)
            ctx.unsupported.append(label)
            return None

    run("name tree", lambda: _repoint_name_tree(ctx, catalog))
    run("legacy destinations", lambda: _repoint_legacy_dests(ctx, catalog))
    # Both name sources are edited now; judge named links against what is gone
    # (a name the other source still defines keeps its links).  Nothing dropped:
    # nothing to re-read.
    if ctx.dead_names:
        remaining = _surviving_names(ctx)
        for key in ctx.dead_names & remaining:
            ctx.result.dropped_name_pages.pop(key, None)
        ctx.dead_names -= remaining
    touched = bool(run("links", lambda: _repoint_links(ctx)))  # open pages need a sync
    run("open action", lambda: _repoint_open_action(ctx, catalog))
    ctx.result.unsupported = tuple(ctx.unsupported)
    if ctx.result.changed:
        doc.init_doc()  # refresh PyMuPDF's cached outline and name data
        if touched:
            sync_open_pages(doc)
    return ctx.result


def _surviving_names(ctx: _Context) -> set[bytes]:
    """Every name still defined in either name source (so a clash keeps its links)."""
    read = _read_name_entries(ctx.doc)
    return set() if read is None else read[1]  # ``taken``: the tree's keys plus the legacy ones
