"""In-place outline (bookmark) edits: the single writer of the document outline.

F16-NAV-1: the outline must never be regenerated from ``get_toc()`` rows.
``Document.set_toc`` rebuilds every outline item as a GoTo to the page top, so a
round trip through it drops each item's ``/XYZ`` target, zoom, ``/C`` colour,
``/F`` bold/italic flags and collapse state, and turns URI/Launch/other action
items (``get_toc`` page ``-1``) into "go to page 1".  Every outline change
therefore goes through this module, which edits the existing outline objects
(``set_toc([])``, which rebuilds nothing, is only used to clear an outline):

* Outline items reference page *objects*, so insert/move/import of pages needs
  no outline write at all; only items whose target page was deleted (PyMuPDF
  strips their ``/Dest``/``/A`` and greys ``/C`` to 0.8) are retargeted, one key
  at a time, and their colour is restored (:func:`follow_page_targets`).
* Bookmark-panel edits address items by outline xref: a rename writes
  ``/Title`` only, a page change rewrites only that item's destination, and
  add/delete/reorder relinks the tree pointers (``/First``, ``/Last``,
  ``/Next``, ``/Prev``, ``/Parent``, ``/Count``) of the existing objects
  (:func:`apply_outline_rows`).  Every other key of an item is left untouched.

Qt-free (model layer).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from utils.pdf_object_source import xref_set_key_exact

logger = logging.getLogger(__name__)

_NULL = ("null", "null")


@dataclass(frozen=True)
class OutlineItem:
    """One outline item as read from the document, in ``get_toc`` order."""

    xref: int
    level: int
    title: str
    page: int  # 1-based; -1 when the item has no page target (URI, Launch, ...)
    color: str | None  # raw ``/C`` value, ``None`` when absent


@dataclass(frozen=True)
class OutlineRow:
    """One requested outline row; ``xref`` is ``None`` for a new bookmark."""

    level: int
    title: str
    page: int
    xref: int | None


def outline_items(doc: fitz.Document) -> list[OutlineItem] | None:
    """Outline items paired with their object xrefs, or ``None`` if unpairable.

    ``get_toc`` and ``get_outline_xrefs`` walk the same ``/First``/``/Next``
    chain (PyMuPDF's own ``delete_pages`` pairs them the same way); a malformed
    outline where the two walks disagree has no reliable identity.
    """
    toc = doc.get_toc(simple=True)
    if not toc:
        return []
    try:
        xrefs = [int(xref) for xref in doc.get_outline_xrefs()]
    except Exception as exc:  # malformed outline tree
        logger.warning("outline xrefs unreadable: %s", exc)
        return None
    if len(xrefs) != len(toc):
        logger.warning("outline walk mismatch: %d toc rows, %d xrefs", len(toc), len(xrefs))
        return None
    items: list[OutlineItem] = []
    for (level, title, page, *_rest), xref in zip(toc, xrefs):
        color_type, color_value = doc.xref_get_key(xref, "C")
        items.append(
            OutlineItem(
                xref=xref,
                level=int(level),
                title=str(title),
                page=int(page),
                color=None if color_type == "null" else color_value,
            )
        )
    return items


def _set_key(doc: fitz.Document, xref: int, key: str, value: str) -> None:
    """Write ``key`` only when it changes (``"null"`` clears it)."""
    current = doc.xref_get_key(xref, key)
    if value == "null":
        if current == _NULL:
            return
    elif current[1] == value:
        return
    xref_set_key_exact(doc, xref, key, value)


def _page_dest(doc: fitz.Document, page_index: int) -> str:
    # /Fit is valid on every page geometry (rotation, CropBox origin, UserUnit).
    return f"[{doc.page_xref(page_index)} 0 R/Fit]"


def retarget_item(doc: fitz.Document, xref: int, page_index: int) -> None:
    """Point one outline item at ``page_index`` (0-based), keeping its other keys."""
    dest = _page_dest(doc, page_index)
    if doc.xref_get_key(xref, "Dest") != _NULL:
        xref_set_key_exact(doc, xref, "Dest", dest)
        return
    if doc.xref_get_key(xref, "A")[0] == "dict" and doc.xref_get_key(xref, "A/S") == (
        "name",
        "/GoTo",
    ):
        xref_set_key_exact(doc, xref, "A/D", dest)  # keeps /Next chains and other action keys
        return
    xref_set_key_exact(doc, xref, "A", f"<</S/GoTo/D{dest}>>")


def named_target(doc: fitz.Document, xref: int) -> bytes | None:
    """The destination name an outline item uses (``/Dest`` or ``/A /D``), else ``None``.

    ``get_toc`` does not resolve such an item to a page, so a page operation
    cannot see that its target moved or died; callers resolve the name
    themselves.  Only names that read back as plain text can be matched.
    """
    for key in ("Dest", "A/D"):
        kind, value = doc.xref_get_key(xref, key)
        if kind == "string":
            return value.encode("latin-1", "replace")
        if kind == "name":
            return value.lstrip("/").encode("latin-1", "replace")
    return None


def follow_dropped_names(
    doc: fitz.Document,
    name_pages: dict[bytes, int],
    mapper: Callable[[int], int],
) -> int:
    """Retarget the items that used a destination name which was removed.

    ``name_pages`` maps a removed name to the 1-based page it named before the
    operation and ``mapper`` maps that page to its final 1-based page, as for
    :func:`follow_page_targets`.  Such an item has no page in ``get_toc`` (the
    name is not resolved there), so PyMuPDF neither strips nor reports it.
    Returns the number of retargeted items.
    """
    if not name_pages:
        return 0
    items = outline_items(doc)
    if not items:
        return 0
    page_count = len(doc)
    moved = 0
    for item in items:
        key = named_target(doc, item.xref)
        old_page = name_pages.get(key) if key is not None else None
        if old_page is None:
            continue
        retarget_item(doc, item.xref, min(max(1, int(mapper(old_page))), page_count) - 1)
        moved += 1
    if moved:
        doc.init_doc()  # refresh PyMuPDF's cached outline
    return moved


def move_targets_to_page(doc: fitz.Document, from_index: int, to_index: int) -> int:
    """Point every item targeting page ``from_index`` at ``to_index`` (0-based).

    For a page that is replaced by a same-size copy and then deleted (page
    straighten): call it after inserting the replacement and before deleting
    the old page, so PyMuPDF's delete finds no item to strip.  An explicit
    destination array keeps its view (``/XYZ`` position, zoom, fit type) with
    only the page reference swapped (in the action object when the action is
    one, so every item sharing it moves with the first); any other
    destination becomes a whole-page view of ``to_index``.  Returns the number
    of items moved.
    """
    items = outline_items(doc)
    if not items:
        return 0
    old_ref = re.compile(rf"^\[\s*{doc.page_xref(from_index)}\s+0\s+R")
    moved_ref = re.compile(rf"^\[\s*{doc.page_xref(to_index)}\s+0\s+R")
    new_ref = f"[{doc.page_xref(to_index)} 0 R"
    moved = 0
    for item in items:
        if item.page != from_index + 1:
            continue
        for key in ("Dest", "A/D"):
            kind, value = doc.xref_get_key(item.xref, key)
            if kind == "array" and old_ref.match(value):
                xref_set_key_exact(doc, item.xref, key, old_ref.sub(new_ref, value, count=1))
                break
            if kind == "array" and moved_ref.match(value):
                break  # its action is shared with an item moved before
        else:
            retarget_item(doc, item.xref, to_index)
        moved += 1
    if moved:
        doc.init_doc()  # refresh PyMuPDF's cached outline
    return moved


def follow_page_targets(
    doc: fitz.Document,
    before: list[OutlineItem] | None,
    mapper: Callable[[int], int],
) -> int:
    """Repair the outline after a structural page operation.

    ``before`` is :func:`outline_items` captured before the operation and
    ``mapper`` maps a pre-operation 1-based page to its final 1-based page.
    Items that already resolve to their expected page (every item, after an
    insert or move) are not touched.  Items that do not (their page was
    deleted, or a non-standard integer page destination) are retargeted and
    their pre-operation ``/C`` is restored.  Items without a page target are
    never touched.  Returns the number of retargeted items.
    """
    if not before:
        return 0
    after = outline_items(doc)
    if after is None:
        logger.warning("outline not repaired after a page operation: unpairable outline")
        return 0
    page_count = len(doc)
    after_pages = {item.xref: item.page for item in after}
    retargeted = 0
    for item in before:
        if item.page < 1 or item.xref not in after_pages:
            continue
        expected = min(max(1, int(mapper(item.page))), page_count)
        if after_pages[item.xref] == expected:
            continue
        retarget_item(doc, item.xref, expected - 1)
        _set_key(doc, item.xref, "C", item.color if item.color is not None else "null")
        retargeted += 1
    if retargeted:
        doc.init_doc()  # refresh PyMuPDF's cached outline
    return retargeted


def _outline_root(doc: fitz.Document) -> int:
    catalog = doc.pdf_catalog()
    kind, value = doc.xref_get_key(catalog, "Outlines")
    if kind == "xref":
        return int(value.split()[0])
    root = doc.get_new_xref()
    doc.update_object(root, "<</Type/Outlines>>")
    xref_set_key_exact(doc, catalog, "Outlines", f"{root} 0 R")
    return root


def _new_item(doc: fitz.Document, title: str, page: int) -> int:
    xref = doc.get_new_xref()
    doc.update_object(
        xref,
        f"<</Title{fitz.get_pdf_str(title)}/A<</S/GoTo/D{_page_dest(doc, page - 1)}>>>>",
    )
    return xref


def _closed_items(doc: fitz.Document, items: list[OutlineItem]) -> set[int]:
    """The xrefs of the items a viewer shows collapsed (a negative ``/Count``)."""
    closed: set[int] = set()
    for item in items:
        kind, value = doc.xref_get_key(item.xref, "Count")
        if kind == "int" and int(value) < 0:
            closed.add(item.xref)
    return closed


def _relink(doc: fitz.Document, structure: list[tuple[int, int]], closed: set[int]) -> None:
    """Rebuild the tree pointers of ``structure`` = [(level, xref)] in order."""
    root = _outline_root(doc)
    children: dict[int, list[int]] = {root: []}
    parent_of: dict[int, int] = {}
    index_of: dict[int, int] = {}  # position among the siblings
    stack: list[tuple[int, int]] = [(0, root)]
    for level, xref in structure:
        while stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        parent_of[xref] = parent
        index_of[xref] = len(children[parent])
        children[parent].append(xref)
        children[xref] = []
        stack.append((level, xref))

    # visible[node]: descendants shown while ``node`` itself is open.
    visible: dict[int, int] = {}

    def count_visible(node: int) -> int:
        total = 0
        for child in children[node]:
            below = count_visible(child)
            total += 1 + (0 if child in closed else below)
        visible[node] = total
        return total

    count_visible(root)
    for node in [root, *[xref for _level, xref in structure]]:
        kids = children[node]
        _set_key(doc, node, "First", f"{kids[0]} 0 R" if kids else "null")
        _set_key(doc, node, "Last", f"{kids[-1]} 0 R" if kids else "null")
        if node == root:
            _set_key(doc, node, "Count", str(visible[node]) if kids else "null")
            continue
        if kids:
            # /Count of a closed item is minus the descendants shown when opened.
            _set_key(doc, node, "Count", str(-visible[node] if node in closed else visible[node]))
        else:
            _set_key(doc, node, "Count", "null")
        parent = parent_of[node]
        siblings = children[parent]
        index = index_of[node]
        _set_key(doc, node, "Parent", f"{parent} 0 R")
        _set_key(doc, node, "Prev", f"{siblings[index - 1]} 0 R" if index > 0 else "null")
        _set_key(
            doc,
            node,
            "Next",
            f"{siblings[index + 1]} 0 R" if index + 1 < len(siblings) else "null",
        )


def apply_outline_rows(
    doc: fitz.Document,
    rows: list[OutlineRow],
    current: list[OutlineItem],
) -> bool:
    """Make the outline match ``rows`` by editing the existing objects in place.

    Rows carrying the xref of a ``current`` item keep that object: only a
    changed title (``/Title``) or a changed page (its destination) is written.
    Rows without an xref, or with one that is not a ``current`` item, become
    new items; current items missing from ``rows`` are unlinked.  The tree
    pointers are rewritten only when the order or nesting changed.  Returns
    whether the document changed.
    """
    if not rows:
        if current:
            # An empty set_toc rebuilds no item, so it cannot drop a destination (F16-NAV-1).
            doc.set_toc([])
            return True
        return False
    by_xref = {item.xref: item for item in current}
    changed = False
    structure: list[tuple[int, int]] = []
    for row in rows:
        item = by_xref.get(row.xref) if row.xref is not None else None
        if item is None:
            xref = _new_item(doc, row.title, row.page)
            changed = True
        else:
            xref = item.xref
            if row.title != item.title.strip():
                xref_set_key_exact(doc, xref, "Title", fitz.get_pdf_str(row.title))
                changed = True
            if row.page >= 1 and row.page != item.page:
                retarget_item(doc, xref, row.page - 1)
                changed = True
        structure.append((row.level, xref))
    if structure != [(item.level, item.xref) for item in current]:
        _relink(doc, structure, _closed_items(doc, current))
        changed = True
    if changed:
        doc.init_doc()  # refresh PyMuPDF's cached outline
    return changed


@dataclass(frozen=True)
class ImportedItem:
    """One bookmark carried over from another document (F16-NAV-3).

    ``page_xref`` is the page *object* of the target in ``doc`` and ``view`` the
    rest of its destination array (``/XYZ 0 400 null``, ``/Fit`` ...), both
    already translated to ``doc``.  ``uri`` is a ready PDF string for a URI
    action; an item with neither target is a plain heading.  ``color`` and
    ``flags`` are the raw ``/C`` array and ``/F`` integer text.
    """

    level: int
    title: str
    page_xref: int | None
    view: str
    uri: str | None
    color: str | None
    flags: str | None
    closed: bool


def _imported_body(item: ImportedItem) -> str:
    parts = [f"/Title{fitz.get_pdf_str(item.title)}"]
    if item.page_xref is not None:
        view = f" {item.view}" if item.view else ""
        parts.append(f"/A<</S/GoTo/D[{item.page_xref} 0 R{view}]>>")
    elif item.uri is not None:
        parts.append(f"/A<</S/URI/URI{item.uri}>>")
    if item.color:
        parts.append(f"/C{item.color}")
    if item.flags:
        parts.append(f"/F {item.flags}")
    return "<<" + "".join(parts) + ">>"


def append_items(doc: fitz.Document, items: list[ImportedItem]) -> int:
    """Append ``items`` after the existing outline of ``doc`` (new objects).

    Levels are clamped to at most one deeper than the previous item (a bookmark
    whose parent was not carried over hangs under the nearest earlier item one
    level up, or at the top level), the tree pointers of the whole outline are
    relinked, and closed items stay closed.  Returns the number of appended
    items.
    """
    if not items:
        return 0
    current = outline_items(doc)
    if current is None:
        logger.warning("outline items not appended: unpairable outline")
        return 0
    structure = [(item.level, item.xref) for item in current]
    closed = _closed_items(doc, current)
    previous = structure[-1][0] if structure else 0
    for item in items:
        level = max(1, min(item.level, previous + 1))
        xref = doc.get_new_xref()
        doc.update_object(xref, _imported_body(item))
        structure.append((level, xref))
        if item.closed:
            closed.add(xref)
        previous = level
    _relink(doc, structure, closed)
    doc.init_doc()  # refresh PyMuPDF's cached outline
    return len(items)
