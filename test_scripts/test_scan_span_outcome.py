"""Opus A4 class: a child-supplied span is never trusted by a writer (outcome check).

For EVERY span field of the scan cache entry (cm_span, do_span, q_span; start and end separately) at
EVERY byte position of a small stream (vector ``cm``'s, comments and strings holding fake operators,
an inline image, two images), a move or a delete either refuses leaving the stream bytes unchanged,
or leaves exactly the bytes and placements the honest edit leaves.  Also the five forged repros.
"""

from __future__ import annotations

import dataclasses
import pathlib

import fitz
import pytest

from model import content_scan
from model.content_scan import content_key
from model.object_requests import DeleteObjectRequest, MoveObjectRequest
from model.pdf_model import PDFModel

DEST = fitz.Rect(150, 100, 250, 170)


def _png(shade: int) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    pix.clear_with(shade)
    return pix.tobytes("png")


def _body(a: str, b: str) -> bytes:
    return (
        "q 1 0 0 1 5 5 cm 0.5 w 1 1 m 2 2 l S Q\n"
        f"% 1 0 0 1 0 0 cm /{a} Do\n"
        f"BT (1 0 0 1 0 0 cm /{a} Do) Tj ET\n"
        "q 9 0 0 9 0 0 cm BI /W 1 /H 1 /BPC 8 /CS /G ID x EI Q\n"
        f"q 100 0 0 70 20 150 cm /{a} Do Q\n"
        f"q 100 0 0 70 150 150 cm /{b} Do Q\n"
    ).encode()


def _make(tmp: pathlib.Path, body_fn=None) -> pathlib.Path:
    with fitz.open() as doc:
        page = doc.new_page(width=320, height=240)
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png(200))
        page.insert_image(fitz.Rect(150, 20, 250, 90), stream=_png(60))
        names = [str(r[7]) for r in page.get_images(full=True)]
        body = (body_fn or _body)(*names)
        doc.update_stream(int(page.get_contents()[0]), body if isinstance(body, bytes) else body.encode())
        path = tmp / "t.pdf"
        doc.save(path)
    return path


def _open(path: pathlib.Path) -> PDFModel:
    content_scan.clear_scan_cache()
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def _stream(model: PDFModel) -> bytes:
    return model.doc.xref_stream(int(model.doc[0].get_contents()[0]))


def _placements(model: PDFModel) -> list[tuple[int, int]]:
    with fitz.open("pdf", model.doc.tobytes()) as doc:
        return sorted((round(i["bbox"][0]), round(i["bbox"][1])) for i in doc[0].get_image_info())


def _forge(model: PDFModel, index: int = 0, **changes) -> None:
    stream = _stream(model)
    scan = content_scan.scan_stream(stream)
    dos = list(scan.dos)
    dos[index] = dataclasses.replace(dos[index], **changes)
    content_scan.clear_scan_cache()
    content_scan.store_scan(content_key(stream), dataclasses.replace(scan, dos=tuple(dos)))


def _do(model: PDFModel, op: str) -> bool:
    if op == "move":
        return bool(model.move_object(MoveObjectRequest("native_image:1:0", "native_image", 1, 1, fitz.Rect(DEST))))
    return bool(model.delete_object(DeleteObjectRequest("native_image:1:0", "native_image", 1)))


def _state(model: PDFModel) -> tuple[bytes, list[tuple[int, int]]]:
    return _stream(model), _placements(model)


@pytest.fixture(scope="module")
def pdf_path(tmp_path_factory) -> pathlib.Path:
    return _make(tmp_path_factory.mktemp("spans"))


@pytest.fixture(scope="module")
def reference(pdf_path):
    out = {}
    for op in ("move", "delete"):
        model = _open(pdf_path)
        original = _state(model)
        assert _do(model, op), op
        out[op] = (original, _state(model))
        model.close()
    return out


def _check(pdf_path, reference, op, verified=False, **forged) -> None:
    model = _open(pdf_path)
    try:
        _forge(model, **forged)
        if verified:
            # the background verification's result: the honest lex, kept apart from the forged answer
            stream = _stream(model)
            content_scan.store_verified(content_key(stream), content_scan.scan_stream(stream))
        original, honest = reference[op]
        ok = _do(model, op)
        after = _state(model)
        assert after in (original, honest), (op, forged, after[0][:200])
        assert ok == (after != original), (op, forged, ok)  # the answer agrees with what happened
    finally:
        model.close()


FIELDS = ("cm_span", "do_span", "q_span")


@pytest.mark.parametrize("verified", [False, True], ids=["inline lex", "verified scan"])
@pytest.mark.parametrize("op", ["move", "delete"])
@pytest.mark.parametrize("field", FIELDS)
def test_every_span_position_refuses_or_equals_the_honest_edit(pdf_path, reference, op, field, verified):
    model = _open(pdf_path)
    honest_span = getattr(content_scan.scan_stream(_stream(model)).dos[0], field)
    length = len(_stream(model))
    model.close()
    assert honest_span is not None
    start, end = honest_span
    for position in range(length + 1):
        _check(pdf_path, reference, op, verified, **{field: (position, max(position, end))})
        _check(pdf_path, reference, op, verified, **{field: (min(position, start), position)})


def test_five_forged_scans(tmp_path):
    # 1. cm_span at a vector drawing's real cm
    path = _make(tmp_path / ".", lambda a, b: f"q 1 0 0 1 0 0 cm 0.5 w 1 1 m 2 2 l S Q\nq 100 0 0 70 20 150 cm /{a} Do Q\n")
    model = _open(path)
    stream = _stream(model)
    a = stream.index(b"1 0 0 1 0 0")
    _forge(model, cm_span=(a, a + 11))
    before = _state(model)
    _do(model, "move")
    assert _state(model) in (before, _honest(path, "move"))
    model.close()
    # 2. cm_span inside a comment
    path = _make(tmp_path / ".", lambda a, b: f"% 1 0 0 1 0 0 cm\nq 100 0 0 70 20 150 cm /{a} Do Q\n")
    model = _open(path)
    stream = _stream(model)
    a = stream.index(b"1 0 0 1 0 0")
    _forge(model, cm_span=(a, a + 11))
    before = _state(model)
    _do(model, "move")
    assert _state(model) in (before, _honest(path, "move"))
    model.close()
    # 3. do_span inside a comment (q span removed)
    path = _make(tmp_path / ".", lambda a, b: f"% /{a} Do\nq 100 0 0 70 20 150 cm /{a} Do Q\n")
    model = _open(path)
    stream = _stream(model)
    _forge(
        model,
        do_span=(stream.index(b"/"), stream.index(b"Do") + 2),
        q_span=None, q_operator_index=None, q_end_operator_index=None, q_do_count=0,
    )
    before = _state(model)
    _do(model, "delete")
    assert _state(model) in (before, _honest(path, "delete"))
    model.close()
    # 4. q_span of the OTHER image
    path = _make(tmp_path / ".", lambda a, b: f"q 100 0 0 70 20 150 cm /{a} Do Q\nq 100 0 0 70 150 150 cm /{b} Do Q\n")
    model = _open(path)
    other = content_scan.scan_stream(_stream(model)).dos[1].q_span
    _forge(model, q_span=other)
    before = _state(model)
    _do(model, "delete")
    assert _state(model) in (before, _honest(path, "delete"))
    model.close()
    # 5. do_span of the OTHER image
    path = _make(tmp_path / ".", lambda a, b: f"100 0 0 70 20 150 cm /{a} Do\n1 0 0 1 130 0 cm /{b} Do\n")
    model = _open(path)
    other = content_scan.scan_stream(_stream(model)).dos[1].do_span
    _forge(model, do_span=other)
    before = _state(model)
    _do(model, "delete")
    assert _state(model) in (before, _honest(path, "delete"))
    model.close()


_PLACEMENT_FIELDS = (
    "do_operator_index", "do_span", "cm_operator_index", "cm_span",
    "q_operator_index", "q_end_operator_index", "q_span", "q_do_count",
)


@pytest.mark.parametrize("op", ["move", "delete"])
def test_a_forged_row_naming_another_placement_of_the_same_image_is_refused(tmp_path, op):
    """Identity, not only spans: the second placement's honest indexes and spans with the FIRST
    placement's matrix (so the hit is the first image) must not edit the second."""
    body = lambda a, b: f"q 100 0 0 70 20 150 cm /{a} Do Q\nq 100 0 0 70 150 150 cm /{a} Do Q\n"  # noqa: E731
    path = _make(tmp_path, body)
    model = _open(path)
    honest_state = _honest(path, op)
    rows = content_scan.scan_stream(_stream(model)).dos
    _forge(model, 0, **{f: getattr(rows[1], f) for f in _PLACEMENT_FIELDS})
    before = _state(model)
    ok = _do(model, op)
    after = _state(model)
    assert after in (before, honest_state)
    assert ok == (after != before)
    model.close()


def test_two_honest_edits_in_a_row_equal_the_same_edits_on_cold_caches(tmp_path):
    """The second edit reads a derive_after_* cache entry; it must agree with a fresh lex."""
    path = _make(tmp_path)
    moves = [fitz.Rect(150, 100, 250, 170), fitz.Rect(30, 100, 130, 170)]

    def run(clear_between: bool):
        model = _open(path)
        for rect in moves:
            if clear_between:
                content_scan.clear_scan_cache()
            assert model.move_object(MoveObjectRequest("native_image:1:0", "native_image", 1, 1, rect))
        assert _do(model, "delete")
        state = _state(model)
        model.close()
        return state

    assert run(False) == run(True)


def _honest(path: pathlib.Path, op: str):
    model = _open(path)
    assert _do(model, op)
    state = _state(model)
    model.close()
    return state
