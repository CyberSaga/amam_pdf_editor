"""Fixtures for F16-NAV-3: documents that carry every kind of navigation data.

``make_nav_pdf`` builds a 6 page document with

* an outline (positioned colour/bold target, URI item, a collapsed chapter with a
  child, a plain page item),
* page labels ``i, ii, 1, 2, 3`` and a prefixed range whose prefix holds a
  parenthesis and CJK characters,
* a named destination ``chap3`` (``/XYZ 0 400 null``) in a ``/Names /Dests`` tree,
* links on page 1: explicit GoTo, URI, a link to ``chap3`` and two explicit
  ``/Fit`` / ``/FitH`` destinations (which PyMuPDF 1.27 reports as ``LINK_NAMED``
  and ``insert_pdf`` therefore drops).

``make_src_pdf`` is a 3 page document with its own outline, a clashing name
``chap3`` (page 2) and a link to it; ``make_plain_pdf`` has no navigation at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz

PREFIX = "附錄("  # two CJK characters and a parenthesis


def _add_link(doc: fitz.Document, page: fitz.Page, rect: str, action: str) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, f"<</Type/Annot/Subtype/Link/Rect[{rect}]/Border[0 0 0]/A{action}>>")
    kind, value = doc.xref_get_key(page.xref, "Annots")
    inner = value.strip()[1:-1] if kind == "array" else ""
    doc.xref_set_key(page.xref, "Annots", f"[{inner} {xref} 0 R]")
    return xref


def make_nav_pdf(path: Path) -> None:
    doc = fitz.open()
    for index in range(6):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"NAVPAGE-{index + 1}", fontsize=20)
    catalog = doc.pdf_catalog()
    names = doc.get_new_xref()
    doc.update_object(names, f"<</Names[(chap3)[{doc[2].xref} 0 R/XYZ 0 400 null]]>>")
    doc.xref_set_key(catalog, "Names", f"<</Dests {names} 0 R>>")
    doc.xref_set_key(
        catalog,
        "PageLabels",
        f"<</Nums[0<</S/r>>2<</S/D>>5<</P{fitz.get_pdf_str(PREFIX)}/S/D/St 7>>]>>",
    )
    doc.set_toc(
        [
            [
                1,
                "Intro",
                2,
                {
                    "kind": fitz.LINK_GOTO,
                    "page": 1,
                    "to": fitz.Point(0, 500),
                    "color": (1, 0, 0),
                    "bold": True,
                },
            ],
            [1, "Website", -1, {"kind": fitz.LINK_URI, "uri": "https://example.com/"}],
            [1, "Chapter 4", 4, {"kind": fitz.LINK_GOTO, "page": 3, "to": fitz.Point(0, 300)}],
            [2, "Section 4.1", 5],
            [1, "Last", 6],
        ]
    )
    first = doc[0]
    first.insert_link(
        {"kind": fitz.LINK_GOTO, "from": fitz.Rect(72, 80, 300, 110), "page": 4, "to": fitz.Point(0, 200)}
    )
    first.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 480, 300, 510), "uri": "https://example.org/"})
    _add_link(doc, first, "72 212 300 242", "<</S/GoTo/D(chap3)>>")
    _add_link(doc, first, "72 150 300 180", f"<</S/GoTo/D[{doc[3].xref} 0 R/Fit]>>")
    _add_link(doc, first, "72 100 300 130", f"<</S/GoTo/D[{doc[4].xref} 0 R/FitH 300]>>")
    doc.save(path)
    doc.close()


def make_src_pdf(path: Path) -> None:
    doc = fitz.open()
    for index in range(3):
        doc.new_page(width=595, height=842).insert_text((72, 100), f"SRCPAGE-{index + 1}", fontsize=20)
    catalog = doc.pdf_catalog()
    names = doc.get_new_xref()
    doc.update_object(names, f"<</Names[(chap3)[{doc[1].xref} 0 R/Fit]]>>")
    doc.xref_set_key(catalog, "Names", f"<</Dests {names} 0 R>>")
    doc[0].insert_link(
        {"kind": fitz.LINK_GOTO, "from": fitz.Rect(72, 80, 300, 110), "page": 2, "to": fitz.Point(0, 100)}
    )
    _add_link(doc, doc[0], "72 212 300 242", "<</S/GoTo/D(chap3)>>")
    doc.set_toc([[1, "Src A", 1], [1, "Src C", 3]])
    doc.save(path)
    doc.close()


def make_rich_src_pdf(path: Path) -> None:
    """4 pages: 3-level outline plus a tail, names ``chap3`` (clashes with the nav document) and
    ``srcname``, labels ``S-1 .. S-4`` and two named links on page 1."""
    doc = fitz.open()
    for index in range(4):
        doc.new_page(width=595, height=842).insert_text((72, 100), f"SRCPAGE-{index + 1}", fontsize=20)
    catalog = doc.pdf_catalog()
    names = doc.get_new_xref()
    doc.update_object(
        names,
        f"<</Names[(chap3)[{doc[1].xref} 0 R/XYZ 0 300 null](srcname)[{doc[2].xref} 0 R/XYZ 0 200 null]]>>",
    )
    doc.xref_set_key(catalog, "Names", f"<</Dests {names} 0 R>>")
    doc.xref_set_key(catalog, "PageLabels", "<</Nums[0<</P(S-)/S/D/St 1>>]>>")
    _add_link(doc, doc[0], "72 212 300 242", "<</S/GoTo/D(chap3)>>")
    _add_link(doc, doc[0], "72 250 300 280", "<</S/GoTo/D(srcname)>>")
    doc.set_toc([[1, "Src Part", 1], [2, "Src Chapter", 2], [3, "Src Section", 3], [1, "Src Tail", 4]])
    doc.save(path)
    doc.close()


def resolved_names(doc: fitz.Document) -> dict[str, int]:
    """Named destination -> 0-based page, read through a fresh handle.

    ``Document.resolve_names`` memoizes per handle, so a document that is still
    being changed must never be asked directly (PITFALLS F16-NAV-3).
    """
    fresh = fitz.open("pdf", doc.tobytes())
    try:
        return {name: info["page"] for name, info in fresh.resolve_names().items()}
    finally:
        fresh.close()


def make_plain_pdf(path: Path, pages: int = 3, tag: str = "PLAIN") -> None:
    doc = fitz.open()
    for index in range(pages):
        doc.new_page(width=595, height=842).insert_text((72, 100), f"{tag}-{index + 1}", fontsize=20)
    doc.save(path)
    doc.close()


def outline_attrs(doc: fitz.Document) -> dict[str, tuple]:
    """Every outline attribute except the page number, keyed by title."""
    attrs: dict[str, tuple] = {}
    for _level, title, _page, dest in doc.get_toc(simple=False):
        to = dest.get("to")
        attrs[title] = (
            dest.get("kind"),
            None if to is None else (round(to.x, 3), round(to.y, 3)),
            dest.get("zoom"),
            dest.get("uri"),
            dest.get("color"),
            bool(dest.get("bold")),
            bool(dest.get("italic")),
            dest.get("collapse"),
        )
    return attrs


def labels(doc: fitz.Document) -> list[str]:
    return [doc[i].get_label() for i in range(len(doc))]


def link_targets(doc: fitz.Document, index: int) -> dict[int, int | str]:
    """Where each non-URI link of page ``index`` points, keyed by the link's top edge.

    An explicit destination is the 0-based target page read from the raw ``/A /D``
    array; a named destination is its name.
    """
    xref_to_index = {doc.page_xref(i): i for i in range(len(doc))}
    out: dict[int, int | str] = {}
    for link in doc[index].get_links():
        if link.get("kind") == fitz.LINK_URI:
            continue
        kind, value = doc.xref_get_key(link["xref"], "A/D")
        top = round(link["from"].y0)
        if kind == "array":
            match = re.match(r"\[\s*(\d+)\s+0\s+R", value)
            assert match is not None
            out[top] = xref_to_index[int(match.group(1))]
        else:
            out[top] = value.lstrip("/")
    return out
