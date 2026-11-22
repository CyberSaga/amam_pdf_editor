"""Astra H1: the optional-content carry charges every emitted piece, the root and mapped references included."""

from __future__ import annotations

import time

import fitz
import pytest

from model import table_objects


def _oversized(indirect_root: bool, mentions: int, refs_per_piece: int) -> bytes:
    """Compact file: the root names one piece `mentions` times; the piece is `refs_per_piece` mapped groups."""
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        a = d.add_ocg("A", on=False)
        pg.insert_text((20, 50), "off", oc=a)
        piece = d.get_new_xref()
        d.update_object(piece, "[" + f" {a} 0 R" * refs_per_piece + " ]")
        order = "[" + f" {piece} 0 R" * mentions + " ]"
        body = f"<< /OCGs [{a} 0 R] /D << /Order {order} /BaseState /ON /OFF [{a} 0 R] >> >>"
        if indirect_root:
            root = d.get_new_xref()
            d.update_object(root, body)
            d.xref_set_key(d.pdf_catalog(), "OCProperties", f"{root} 0 R")
        else:
            d.xref_set_key(d.pdf_catalog(), "OCProperties", body)
        return d.tobytes()


@pytest.mark.parametrize("indirect_root", [False, True])
@pytest.mark.parametrize("mentions, refs", [(500, 400), (60_000, 1), (4, 40_000)])
def test_compact_oversized_configuration_is_refused_in_bounded_time(indirect_root, mentions, refs):
    data = _oversized(indirect_root, mentions, refs)
    start = time.perf_counter()
    with fitz.open("pdf", data) as doc:
        with pytest.raises(ValueError):
            table_objects.scratch_page_bytes(doc, 1)
    assert time.perf_counter() - start < 3.0


def test_an_oversized_root_alone_is_refused():
    """No inlined piece at all: the root's own mapped references exceed the budget."""
    data = _oversized(False, 1, 1)
    with fitz.open("pdf", data) as doc:
        a = next(iter(doc.get_ocgs()))
        doc.xref_set_key(
            doc.pdf_catalog(),
            "OCProperties",
            f"<< /OCGs [{a} 0 R] /D << /BaseState /ON /OFF [" + f" {a} 0 R" * 60_000 + " ] >> >>",
        )
        with pytest.raises(ValueError):
            table_objects.scratch_page_bytes(doc, 1)
