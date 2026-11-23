"""Card B3: ``PDFModel.vector_page_source`` hands the scanner the decoded content streams and the
page frame, through the existing bounded decode, and refuses what the scanner caps refuse."""
from __future__ import annotations

import zlib

import fitz
import pytest

from model.pdf_content_ops import page_user_space_matrix
from model.pdf_model import PDFModel
from model.vector_paths import VectorPageRefused, scan_page
from model.vector_paths import limits as limits_mod

STREAM = b"1 0 0 RG 10 10 m 90 90 l S\n"


def _model(tmp_path, build) -> PDFModel:
    doc = fitz.open()
    build(doc)
    path = tmp_path / "doc.pdf"
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def _one_stream(doc: fitz.Document) -> None:
    page = doc.new_page(width=200, height=300)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, STREAM)
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")


def _two_streams(doc: fitz.Document) -> None:
    page = doc.new_page(width=200, height=300)
    xrefs = []
    for body in (b"q 1 0 0 1 5 5 cm\n", b"10 10 m 90 90 l S Q\n"):
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, body)
        xrefs.append(xref)
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]")


def test_returns_decoded_streams_and_the_page_frame(tmp_path):
    model = _model(tmp_path, _one_stream)
    streams, frame = model.vector_page_source(1)
    assert streams == (STREAM,)
    assert isinstance(streams, tuple) and all(type(s) is bytes for s in streams)
    assert frame == page_user_space_matrix(model.doc[0])
    assert len(frame) == 6


def test_stream_order_and_boundaries_are_kept(tmp_path):
    model = _model(tmp_path, _two_streams)
    streams, _ = model.vector_page_source(1)
    assert streams == (b"q 1 0 0 1 5 5 cm\n", b"10 10 m 90 90 l S Q\n")


def test_a_flate_stream_is_returned_decoded(tmp_path):
    def build(doc):
        page = doc.new_page(width=200, height=300)
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, zlib.compress(STREAM), compress=False)
        doc.xref_set_key(xref, "Filter", "/FlateDecode")
        doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")

    model = _model(tmp_path, build)
    xref = model.doc[0].get_contents()[0]
    assert model.doc.xref_get_key(xref, "Filter")[1] == "/FlateDecode"
    assert model.doc.xref_stream_raw(xref) != STREAM
    streams, _ = model.vector_page_source(1)
    assert streams == (STREAM,)


def test_the_index_scanner_accepts_the_source_unchanged(tmp_path):
    model = _model(tmp_path, _one_stream)
    streams, frame = model.vector_page_source(1)
    assert len(scan_page(streams, frame).paths) == 1


def test_a_page_without_contents_yields_no_streams_and_a_frame(tmp_path):
    model = _model(tmp_path, lambda doc: doc.new_page(width=200, height=300))
    streams, frame = model.vector_page_source(1)
    assert streams == ()
    assert frame == page_user_space_matrix(model.doc[0])


def test_reading_the_source_changes_nothing_in_the_document(tmp_path):
    model = _model(tmp_path, _one_stream)
    def objects():
        return [(x, model.doc.xref_object(x, compressed=True), model.doc.xref_stream_raw(x))
                for x in range(1, model.doc.xref_length())]

    before = objects()
    edit_count = model.edit_count
    model.vector_page_source(1)
    assert objects() == before
    assert model.edit_count == edit_count


def test_no_document_raises_value_error():
    with pytest.raises(ValueError):
        PDFModel().vector_page_source(1)


@pytest.mark.parametrize("page_num", [0, 2, -1])
def test_a_page_number_outside_the_document_raises_index_error(tmp_path, page_num):
    model = _model(tmp_path, _one_stream)
    with pytest.raises(IndexError):
        model.vector_page_source(page_num)


def test_decoded_bytes_over_the_scanner_cap_refuse_too_large(tmp_path, monkeypatch):
    model = _model(tmp_path, _one_stream)
    monkeypatch.setattr(limits_mod, "MAX_DECODED_BYTES", len(STREAM) - 1)
    with pytest.raises(VectorPageRefused) as info:
        model.vector_page_source(1)
    assert info.value.code == "TOO_LARGE"


def test_the_cap_counts_every_stream_of_the_page(tmp_path, monkeypatch):
    model = _model(tmp_path, _two_streams)
    monkeypatch.setattr(limits_mod, "MAX_DECODED_BYTES", 30)  # each stream alone fits, both do not
    with pytest.raises(VectorPageRefused) as info:
        model.vector_page_source(1)
    assert info.value.code == "TOO_LARGE"


def test_a_stream_exactly_at_the_cap_is_accepted(tmp_path, monkeypatch):
    model = _model(tmp_path, _one_stream)
    monkeypatch.setattr(limits_mod, "MAX_DECODED_BYTES", len(STREAM))
    streams, _ = model.vector_page_source(1)
    assert streams == (STREAM,)


def test_a_filter_chain_the_bounded_decode_cannot_size_is_refused_not_decoded(tmp_path):
    def build(doc):
        page = doc.new_page(width=200, height=300)
        xref = doc.get_new_xref()
        hexed = STREAM.hex().encode() + b">"
        doc.update_object(xref, "<</Filter /ASCIIHexDecode>>")
        doc.update_stream(xref, hexed, compress=False)
        doc.xref_set_key(xref, "Filter", "/ASCIIHexDecode")
        doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")

    model = _model(tmp_path, build)
    with pytest.raises(VectorPageRefused) as info:
        model.vector_page_source(1)
    assert info.value.code == "TOO_LARGE"


def test_a_frame_that_cannot_be_proved_refuses_no_frame(tmp_path):
    model = _model(tmp_path, _one_stream)
    model.doc.xref_set_key(model.doc[0].xref, "Rotate", "45")
    assert page_user_space_matrix(model.doc[0]) is None
    with pytest.raises(VectorPageRefused) as info:
        model.vector_page_source(1)
    assert info.value.code == "NO_FRAME"
