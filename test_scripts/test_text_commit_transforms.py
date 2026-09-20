"""T16-4X S0 F7(b): the page-visual-frame fail-closed adapter has one home.

``page_visual_frame_or_none`` is the single chokepoint every geometry
consumer must go through to turn :func:`page_visual_frame`'s
``UnsupportedPageGeometryError`` into ``None`` -- previously duplicated as
``inspect._page_visual_frame_or_none``,
``scripts.audit_tier_coverage._page_frame_or_none`` and an inline
try/except in ``scripts/measure_tier_funnel.py`` (docs/PITFALLS.md: "an
audit that mirrors a gate goes stale the day the gate moves").
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.transforms import (  # noqa: E402
    PageVisualFrame,
    page_visual_frame_or_none,
)

HELLO = "Hello"


def _plain_doc() -> fitz.Document:
    """One ordinary page: no ``/CropBox``, no ``/UserUnit`` override."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 72 700 Td (" + HELLO.encode() + b") Tj ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _user_unit_zero_doc() -> fitz.Document:
    """Same page, but ``/UserUnit`` is ``0`` --
    :func:`~model.text_commit.transforms.page_visual_frame` refuses this
    shape (``UnsupportedPageGeometryError``: "/UserUnit is not a usable
    positive scale"), so the page's visual frame can never be proven.
    """
    doc = _plain_doc()
    doc.xref_set_key(doc[0].xref, "UserUnit", "0")
    return doc


def test_page_visual_frame_or_none_returns_none_when_unprovable():
    doc = _user_unit_zero_doc()
    try:
        assert page_visual_frame_or_none(doc[0]) is None
    finally:
        doc.close()


def test_page_visual_frame_or_none_returns_frame_for_a_plain_page():
    doc = _plain_doc()
    try:
        frame = page_visual_frame_or_none(doc[0])
        assert isinstance(frame, PageVisualFrame)
    finally:
        doc.close()
