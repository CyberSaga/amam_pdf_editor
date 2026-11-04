"""Saving a PDF that carries attachments keeps the author's Catalog ``/PageMode`` (TODOS item).

PyMuPDF's save prelude ``JM_embedded_clean`` (run by every ``save`` / ``saveIncr`` /
``tobytes`` / ``write``) puts ``/PageMode /UseAttachments`` on the Catalog whenever
``/Names/EmbeddedFiles/Names`` exists, overwriting the author's value (round 12
issue8844: the structure phase saw the Catalog change on a clean text commit; viewers
open the attachment pane).  ``model.doc_bytes`` installs one replacement prelude that
never writes ``/PageMode``, so the key keeps its value, and stays absent when it was.

Model only, no Qt.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import fitz
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEXT = "Hello world body"

# Every /PageMode value of ISO 32000-1 Table 28, then the key absent (None).
PAGE_MODES = ["/UseNone", "/UseOutlines", "/UseThumbs", "/FullScreen", "/UseOC", "/UseAttachments", None]


def _expected(mode: str | None) -> tuple[str, str]:
    return ("null", "null") if mode is None else ("name", mode)


def _build(mode: str | None, *, attach: bool = True) -> fitz.Document:
    """A one-page in-memory PDF, optionally with one embedded file, then ``mode`` set."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), TEXT, fontsize=12.0)
    if attach:
        doc.embfile_add("note.txt", b"attached bytes")
    catalog = doc.pdf_catalog()
    doc.xref_set_key(catalog, "PageMode", "null" if mode is None else mode)
    assert doc.xref_get_key(catalog, "PageMode") == _expected(mode)
    return doc


def _write_without_prelude(doc: fitz.Document, path: Path) -> Path:
    """Write ``doc`` to ``path`` through MuPDF directly, so no save prelude runs.

    The on-disk fixture must hold the author's key whatever the prelude does.
    """
    pdf = pymupdf._as_pdf_document(doc)
    fitz.mupdf.pdf_save_document(pdf, str(path), fitz.mupdf.PdfWriteOptions())
    return path


def _catalog(doc: fitz.Document) -> str:
    return doc.xref_object(doc.pdf_catalog(), compressed=True)


def _page_mode_of(data: bytes) -> tuple[str, str]:
    reopened = fitz.open("pdf", data)
    try:
        return reopened.xref_get_key(reopened.pdf_catalog(), "PageMode")
    finally:
        reopened.close()


# ---------------------------------------------------------------- the snapshot funnel


@pytest.mark.parametrize("attach", [True, False], ids=["attachments", "no_attachments"])
@pytest.mark.parametrize("mode", PAGE_MODES, ids=lambda m: "absent" if m is None else m[1:])
def test_doc_bytes_sinks_keep_page_mode(tmp_path, mode, attach) -> None:
    from model.doc_bytes import serialize_doc, serialize_in_memory, serialize_via_file

    doc = _build(mode, attach=attach)
    try:
        before = _catalog(doc)
        outputs = {
            "file": serialize_via_file(doc, tmp_path, encryption=fitz.PDF_ENCRYPT_KEEP, no_new_id=1),
            "memory": serialize_in_memory(doc, encryption=fitz.PDF_ENCRYPT_KEEP, no_new_id=1),
            "funnel": serialize_doc(doc, encryption=fitz.PDF_ENCRYPT_KEEP, in_memory=True),
        }
        assert {name: _page_mode_of(data) for name, data in outputs.items()} == {
            name: _expected(mode) for name in outputs
        }
        assert outputs["file"] == outputs["memory"], "both sinks still write the same bytes"
        assert _catalog(doc) == before, "a snapshot never changes the live Catalog"
    finally:
        doc.close()


@pytest.mark.parametrize("attach", [True, False], ids=["attachments", "no_attachments"])
@pytest.mark.parametrize("mode", PAGE_MODES, ids=lambda m: "absent" if m is None else m[1:])
def test_engine_prepare_leaves_the_live_catalog_unchanged(mode, attach) -> None:
    """The engine's default serializer runs inside ``prepare()`` (scratch proof)."""
    from model.text_commit.engine import TieredCommitEngine
    from model.text_commit.plan import PreparedEdit

    doc = _build(mode, attach=attach)
    try:
        before = _catalog(doc)
        engine = TieredCommitEngine(doc)
        calls: list[bytes] = []
        default = engine._serialize

        def _spy(live: fitz.Document) -> bytes:
            data = default(live)
            calls.append(data)
            return data

        engine._serialize = _spy
        result = engine.prepare(
            doc[0], target_text=TEXT, replacement_text=TEXT + "s", expected_origin=None
        )
        assert isinstance(result, PreparedEdit), result
        assert calls, "prepare() reached the default snapshot serializer"
        assert [_page_mode_of(data) for data in calls] == [_expected(mode)] * len(calls)
        assert _catalog(doc) == before
    finally:
        doc.close()


# ---------------------------------------------------------------- the bug class


@pytest.mark.parametrize("mode", PAGE_MODES, ids=lambda m: "absent" if m is None else m[1:])
def test_every_pymupdf_save_path_keeps_page_mode(tmp_path, mode) -> None:
    """``tobytes`` / ``write`` / ``save`` / ``ez_save`` with no doc_bytes in between."""
    import model.doc_bytes  # noqa: F401  (importing it installs the prelude)

    doc = _build(mode)
    try:
        before = _catalog(doc)
        assert _page_mode_of(doc.tobytes()) == _expected(mode)
        assert _page_mode_of(doc.write(garbage=3, deflate=True)) == _expected(mode)
        doc.save(str(tmp_path / "saved.pdf"))
        doc.ez_save(str(tmp_path / "ez.pdf"))
        assert _catalog(doc) == before
    finally:
        doc.close()
    for name in ("saved.pdf", "ez.pdf"):
        assert _page_mode_of((tmp_path / name).read_bytes()) == _expected(mode), name


@pytest.mark.parametrize("mode", PAGE_MODES, ids=lambda m: "absent" if m is None else m[1:])
def test_a_no_change_incremental_save_appends_nothing(tmp_path, mode) -> None:
    """The structure phase diffs a ``saveIncr``: the Catalog must not be re-emitted.

    Writing the old value back after the original prelude would still mark the
    Catalog dirty, and ``saveIncr`` would append it (measured 2026-11-04).
    """
    import model.doc_bytes  # noqa: F401

    doc = _build(mode)
    path = _write_without_prelude(doc, tmp_path / "authored.pdf")
    doc.close()
    original = path.read_bytes()
    doc = fitz.open(str(path))
    try:
        doc.saveIncr()
    finally:
        doc.close()
    assert path.read_bytes() == original
    assert _page_mode_of(original) == _expected(mode)


def test_an_edited_incremental_save_keeps_the_catalog_out_of_the_update(tmp_path) -> None:
    import model.doc_bytes  # noqa: F401

    doc = _build("/UseOutlines")
    path = _write_without_prelude(doc, tmp_path / "authored.pdf")
    catalog_xref = doc.pdf_catalog()
    doc.close()
    size = path.stat().st_size
    doc = fitz.open(str(path))
    try:
        doc[0].add_highlight_annot(fitz.Rect(72, 88, 200, 104))
        doc.saveIncr()
    finally:
        doc.close()
    appended = path.read_bytes()[size:]
    assert appended, "the annotation was written"
    assert f"\n{catalog_xref} 0 obj".encode() not in appended
    assert _page_mode_of(path.read_bytes()) == ("name", "/UseOutlines")


def test_the_prelude_keeps_removing_an_empty_collection() -> None:
    """Parity with PyMuPDF's prelude for everything except ``/PageMode``."""
    import model.doc_bytes  # noqa: F401

    doc = _build("/UseOutlines")
    try:
        doc.xref_set_key(doc.pdf_catalog(), "Collection", "<<>>")
        reopened = fitz.open("pdf", doc.tobytes())
        try:
            assert reopened.xref_get_key(reopened.pdf_catalog(), "Collection") == ("null", "null")
            assert reopened.xref_get_key(reopened.pdf_catalog(), "PageMode") == ("name", "/UseOutlines")
        finally:
            reopened.close()
    finally:
        doc.close()


def test_the_prelude_install_is_live_for_document_save() -> None:
    """A PyMuPDF bump that renames or inlines the prelude must fail here, not silently."""
    import model.pdf_model  # noqa: F401  (the product's import path installs it)
    from model import doc_bytes

    prelude = getattr(doc_bytes, "embedded_clean_keeping_page_mode", None)
    assert prelude is not None
    assert "JM_embedded_clean(pdf)" in inspect.getsource(pymupdf.Document.save)
    assert pymupdf.Document.save.__globals__["JM_embedded_clean"] is prelude
    assert fitz.JM_embedded_clean is prelude


def test_the_replaced_prelude_still_matches_the_stock_one() -> None:
    """A patch release inside the pin that adds cleanup to ``JM_embedded_clean`` must fail here.

    ``embedded_clean_keeping_page_mode`` re-implements the 1.27.1 prelude minus its
    ``/PageMode`` write; ``doc_bytes`` keeps the stock function it replaced so the
    reimplementation can be checked against it.  If this hash moves, diff the new
    prelude, port any new step into ``embedded_clean_keeping_page_mode`` (still
    without the ``/PageMode`` write), then update the hash.
    """
    import hashlib

    from model import doc_bytes

    stock = getattr(doc_bytes, "STOCK_SAVE_PRELUDE", None)
    assert stock is not None, "doc_bytes keeps the PyMuPDF prelude it replaced"
    assert stock is not doc_bytes.embedded_clean_keeping_page_mode
    assert stock.__module__ == "pymupdf"
    digest = hashlib.sha256(inspect.getsource(stock).encode()).hexdigest()
    assert digest == "c05f01453c36265d0ae591c14e6e3060231ce091bb26bec55b0f900d564a867c"


# ---------------------------------------------------------------- the model's own save


@pytest.mark.parametrize("mode", ["/UseOutlines", None], ids=["UseOutlines", "absent"])
def test_model_save_as_keeps_page_mode(tmp_path, mode) -> None:
    from model.pdf_model import PDFModel

    doc = _build(mode)
    source = _write_without_prelude(doc, tmp_path / "authored.pdf")
    doc.close()
    model = PDFModel()
    model.open_pdf(str(source))
    try:
        model.doc[0].add_highlight_annot(fitz.Rect(72, 88, 200, 104))
        out = tmp_path / "out.pdf"
        model.save_as(str(out))
        model.save_as(str(source))
    finally:
        model.close()
    assert _page_mode_of(out.read_bytes()) == _expected(mode)
    assert _page_mode_of(source.read_bytes()) == _expected(mode)
