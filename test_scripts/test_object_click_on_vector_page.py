"""Card A1: image discovery returns at once on a page that holds no image."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

import model.pdf_content_ops as content_ops
from model.pdf_content_ops import discover_native_image_invocations

REPO_ROOT = Path(__file__).resolve().parents[1]
AWARENESS = REPO_ROOT / "test_files" / "Awareness.pdf"


def _vector_page_doc(path_count: int) -> fitz.Document:
    doc = fitz.open()
    doc.new_page(width=600, height=800)
    stream = b"0 0 0 RG 1 w\n" + b"".join(f"{i % 500} {i % 700} m {i % 500 + 5} {i % 700 + 5} l S\n".encode() for i in range(path_count))
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, stream)
    doc[0].set_contents(xref)
    return doc


def _image_doc() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), False)
    pix.clear_with(200)
    page.insert_image(fitz.Rect(100, 100, 300, 250), pixmap=pix)
    return doc


def _fields(invocations: list) -> list[tuple]:
    return [
        (
            i.page_num,
            i.occurrence_index,
            i.stream_xref,
            i.xobject_name,
            i.xref,
            tuple(round(v, 3) for v in fitz.Rect(i.bbox)),
            round(i.rotation, 3),
            i.cm_operator_index,
            i.do_operator_index,
            i.q_operator_index,
            i.q_end_operator_index,
            i.q_image_invocation_count,
            i.resource_owner_xref,
            i.is_form_nested,
        )
        for i in invocations
    ]


def test_image_free_page_returns_empty_without_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _vector_page_doc(20000)

    def boom(*_a, **_k):
        raise AssertionError("parse_operators must not run on an image-free page")

    monkeypatch.setattr(content_ops, "parse_operators", boom)
    try:
        assert discover_native_image_invocations(doc, 1) == []
    finally:
        doc.close()


def test_page_with_one_image_unchanged() -> None:
    doc = _image_doc()
    try:
        result = _fields(discover_native_image_invocations(doc, 1))
    finally:
        doc.close()
    # Every field, as recorded from the pre-A1 code on 2026-11-17.
    assert result == [(1, 0, 8, "fzImg0", 5, (100.0, 100.0, 300.0, 250.0), 0.0, 1, 2, 0, 3, 1, 4, False)]


@pytest.mark.skipif(not AWARENESS.exists(), reason="Awareness.pdf fixture missing")
def test_form_nested_image_unchanged() -> None:
    doc = fitz.open(str(AWARENESS))
    try:
        result = _fields(discover_native_image_invocations(doc, 1))
    finally:
        doc.close()
    # Every field, as recorded from the pre-A1 code on 2026-11-17.
    assert result == [(1, 0, 5, "Im0", 50, (356.147, 142.729, 665.707, 519.377), 0.0, 819, 820, 818, 821, 1, 5, True)]
