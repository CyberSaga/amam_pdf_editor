"""Astra A4 and A7: the writers never act on a scan field or an occurrence number they have not checked.

A4: a record's ``cm_span`` / ``do_span`` come from the child; the parent verifies the bytes before it
mutates.  Every forged scan field either leaves the document byte-for-byte unchanged (refusal) or
produces exactly the intended edit (checked after an in-memory save and reopen).
A7: an object id obtained under a partial discovery (a failed long stream skipped) never resolves to
another image at mutation.
"""

from __future__ import annotations

import dataclasses

import fitz
import pytest

from model import content_scan, pdf_content_ops
from model.content_scan import content_key
from model.object_requests import DeleteObjectRequest, MoveObjectRequest
from model.pdf_model import PDFModel
from test_scripts.test_native_image_probe import _png, _two_stream_pdf

DEST = fitz.Rect(150, 100, 250, 170)


def _single_image_model(tmp_path) -> PDFModel:
    content_scan.clear_scan_cache()
    with fitz.open() as doc:
        page = doc.new_page(width=320, height=240)
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png())
        name = str(page.get_images(full=True)[0][7])
        x = int(page.get_contents()[0])
        doc.update_stream(x, f"0.5 w 1 1 m 2 2 l S\nq 100 0 0 70 20 150 cm /{name} Do Q\n0.5 w 3 3 m 4 4 l S\n".encode())
        path = tmp_path / "one.pdf"
        doc.save(path)
    m = PDFModel()
    m.open_pdf(str(path))
    return m


def _dump(doc: fitz.Document) -> list[tuple[int, str, bytes]]:
    out = []
    for xref in range(1, doc.xref_length()):
        stream = doc.xref_stream_raw(xref) if doc.xref_is_stream(xref) else b""
        out.append((xref, doc.xref_object(xref, compressed=True), bytes(stream or b"")))
    return out


def _stream(m: PDFModel) -> bytes:
    return m.doc.xref_stream(int(m.doc[0].get_contents()[0]))


def _forge(m: PDFModel, **changes) -> None:
    """Replace the cached scan of the page's stream by one whose first Do record carries ``changes``."""
    stream = _stream(m)
    scan = content_scan.scan_stream(stream)
    length = changes.pop("length", scan.length)
    record = dataclasses.replace(scan.dos[0], **changes)
    forged = dataclasses.replace(scan, length=length, dos=(record,) + scan.dos[1:])
    content_scan.clear_scan_cache()
    content_scan.store_scan(content_key(stream), forged)


def _images(data: bytes) -> list[fitz.Rect]:
    with fitz.open("pdf", data) as doc:
        return [fitz.Rect(info["bbox"]) for info in doc[0].get_image_info()]


def _span_variants(m: PDFModel) -> dict[str, dict]:
    scan = content_scan.scan_stream(_stream(m))
    rec = scan.dos[0]
    a, b = rec.cm_span
    d0, d1 = rec.do_span
    n = scan.length
    return {
        "start-1": {"cm_span": (a - 1, b)},
        "start+1": {"cm_span": (a + 1, b)},
        "start+3": {"cm_span": (a + 3, b)},
        "end-1": {"cm_span": (a, b - 1)},
        "end+1": {"cm_span": (a, b + 1)},
        "end+3": {"cm_span": (a, b + 3)},
        "through-do": {"cm_span": (a, d1)},
        "through-q": {"cm_span": (a, rec.q_span[1])},
        "from-zero": {"cm_span": (0, b)},
        "empty": {"cm_span": (a, a)},
        "inverted": {"cm_span": (b, a)},
        "negative": {"cm_span": (-5, b)},
        "past-end": {"cm_span": (a, n + 50)},
        "on-do": {"cm_span": (d0, d1)},
        "length": {"length": n + 10},
        "cm-index": {"cm_operator_index": rec.cm_operator_index + 1},
    }


def _variant_names() -> list[str]:
    return [
        "start-1", "start+1", "start+3", "end-1", "end+1", "end+3", "through-do", "through-q", "from-zero",
        "empty", "inverted", "negative", "past-end", "on-do", "length", "cm-index",
    ]


@pytest.mark.parametrize("name", _variant_names())
def test_a_forged_cm_span_is_refused_or_exactly_the_intended_edit(tmp_path, name):
    m = _single_image_model(tmp_path)
    try:
        before = _dump(m.doc)
        original_images = _images(m.doc.tobytes())
        _forge(m, **_span_variants(m)[name])
        moved = m.move_object(MoveObjectRequest("native_image:1:0", "native_image", 1, 1, fitz.Rect(DEST)))
        if not moved:
            assert _dump(m.doc) == before, "a refusal must leave the document unchanged"
            return
        images = _images(m.doc.tobytes())  # in-memory save, reopen
        assert len(images) == 1, "the move must not delete or duplicate the image"
        assert abs(images[0].x0 - DEST.x0) < 1.0 and abs(images[0].y0 - DEST.y0) < 1.0
        assert images != original_images
        with fitz.open("pdf", m.doc.tobytes()) as doc:
            assert "Do" in doc.xref_stream(int(doc[0].get_contents()[0])).decode("latin-1")
    finally:
        m.close()
        content_scan.clear_scan_cache()


def test_a_forged_extension_through_do_never_deletes_the_image(tmp_path):
    m = _single_image_model(tmp_path)
    try:
        rec = content_scan.scan_stream(_stream(m)).dos[0]
        _forge(m, cm_span=(rec.cm_span[0], rec.do_span[1]))
        before = _dump(m.doc)
        assert not m.move_object(MoveObjectRequest("native_image:1:0", "native_image", 1, 1, fitz.Rect(DEST)))
        assert _dump(m.doc) == before
        assert len(_images(m.doc.tobytes())) == 1
    finally:
        m.close()
        content_scan.clear_scan_cache()


def test_the_honest_scan_still_moves_the_image(tmp_path):
    m = _single_image_model(tmp_path)
    try:
        assert m.move_object(MoveObjectRequest("native_image:1:0", "native_image", 1, 1, fitz.Rect(DEST)))
        (image,) = _images(m.doc.tobytes())
        assert abs(image.x0 - DEST.x0) < 1.0 and abs(image.y0 - DEST.y0) < 1.0
    finally:
        m.close()
        content_scan.clear_scan_cache()


@pytest.mark.parametrize("name", ["do-start+1", "do-end+3", "do-from-zero", "do-past-end", "do-through-text"])
def test_a_forged_do_span_never_deletes_other_content(tmp_path, name):
    m = _single_image_model(tmp_path)
    try:
        stream = _stream(m)
        rec = content_scan.scan_stream(stream).dos[0]
        d0, d1 = rec.do_span
        spans = {
            "do-start+1": (d0 + 1, d1),
            "do-end+3": (d0, d1 + 3),
            "do-from-zero": (0, d1),
            "do-past-end": (d0, len(stream) + 9),
            "do-through-text": (d0, len(stream) - 2),
        }
        # the q window must not rescue a forged Do span: forge the q span away too
        _forge(m, do_span=spans[name], q_span=None, q_operator_index=None, q_end_operator_index=None, q_do_count=0)
        before = _dump(m.doc)
        deleted = m.delete_object(DeleteObjectRequest("native_image:1:0", "native_image", 1))
        if not deleted:
            assert _dump(m.doc) == before
            return
        assert b"S" in _stream(m) and _stream(m).count(b" l S") == 2, "only the Do may go"
    finally:
        m.close()
        content_scan.clear_scan_cache()


# ---- A7 ----------------------------------------------------------------------------------------


def _bboxes(model: PDFModel) -> list[fitz.Rect]:
    return _images(model.doc.tobytes())


def test_an_id_from_a_partial_discovery_never_edits_the_other_image(tmp_path):
    """Two images, the first stream over the skip threshold: with it skipped image B is occurrence 0."""
    content_scan.clear_scan_cache()
    path = _two_stream_pdf(tmp_path / "two.pdf", long_flags=(True, False))
    m = PDFModel()
    m.open_pdf(path)
    try:
        skip = m.image_scan_input(1).skip_keys  # the streams the child was asked for (the long one)
        partial = pdf_content_ops.discover_native_image_invocations(m.doc, 1, skip)
        assert len(partial) == 1 and partial[0].xobject_name != ""
        image_b = partial[0]
        object_id = f"native_image:1:{image_b.occurrence_index}"
        full = pdf_content_ops.discover_native_image_invocations(m.doc, 1)
        assert len(full) == 2
        by_name = {inv.xobject_name: inv for inv in full}
        original = _bboxes(m)
        before = _dump(m.doc)
        moved = m.move_object(MoveObjectRequest(object_id, "native_image", 1, 1, fitz.Rect(30, 150, 130, 220)))
        if not moved:
            assert _dump(m.doc) == before
            return
        after = _bboxes(m)
        # the image that moved is B (the one the id named, at x 150), never A (at x 20)
        assert by_name[image_b.xobject_name].bbox.x0 > 100
        assert len(after) == 2 and len(original) == 2
        assert any(abs(r.x0 - 20) < 1 for r in after), "image A must stay where it was"
        assert any(abs(r.x0 - 30) < 1 for r in after), "image B must be where it was moved"
        assert not any(abs(r.x0 - 150) < 1 for r in after)
    finally:
        m.close()
        content_scan.clear_scan_cache()


def test_partial_ids_do_not_alias_the_full_numbering(tmp_path):
    content_scan.clear_scan_cache()
    path = _two_stream_pdf(tmp_path / "two.pdf", long_flags=(True, False))
    m = PDFModel()
    m.open_pdf(path)
    try:
        partial = pdf_content_ops.discover_native_image_invocations(m.doc, 1, m.image_scan_input(1).skip_keys)
        full = pdf_content_ops.discover_native_image_invocations(m.doc, 1)
        assert partial[0].occurrence_index not in {i.occurrence_index for i in full}
    finally:
        m.close()
        content_scan.clear_scan_cache()
