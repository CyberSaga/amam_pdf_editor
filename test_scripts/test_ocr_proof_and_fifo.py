from __future__ import annotations

from types import SimpleNamespace

import fitz
import pytest

from model.object_requests import VectorSelectionQuery
from model.pdf_model import PDFModel
from model.tools import ocr_tool
from model.vector_paths.scan import scan_page
from model.write_gate import Applied, Deferred, Stale
from utils.ocr_types import OcrSpan


@pytest.fixture
def scan(tmp_path):
    path = tmp_path / "scan.pdf"
    with fitz.open() as doc:
        for gray in (40, 90, 130):
            page = doc.new_page(width=300, height=400)
            pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 8, 8), False)
            pix.clear_with(gray)
            page.insert_image(fitz.Rect(0, 0, 80, 80), pixmap=pix)
        page = doc[0]
        page.insert_text((5, 5), " ")
        doc.update_stream(page.get_contents()[-1], b"0 0 0 RG 1 w 20 370 m 120 370 l S 1 0 0 rg 150 160 40 40 re f")
        doc.save(path)
    model = PDFModel()
    model.open_pdf(str(path))
    try:
        yield model
    finally:
        model.close()


def _span(text):
    return OcrSpan(bbox=(12.0, 12.0, 100.0, 28.0), text=text, confidence=0.99)


def _pix(model, page_num):
    return model.doc[page_num - 1].get_pixmap(matrix=fitz.Matrix(2, 2), annots=False)


def test_worker_maps_pixels_using_the_clamped_render_scale(scan, monkeypatch):
    from utils import render_limits

    monkeypatch.setattr(render_limits, "_MAX_PIXMAP_PX", 300 * 400)
    monkeypatch.setattr(ocr_tool, "_check_surya_import", lambda: (True, ""))
    monkeypatch.setattr(ocr_tool, "_empty_torch_cache", lambda _device: None)

    def recognize(image, _languages):
        assert image.size == (300, 400)
        return [((12, 12, 100, 28), "clamped", 0.99)]

    monkeypatch.setattr(ocr_tool, "_create_surya_adapter", lambda _device: SimpleNamespace(ocr=recognize))
    snapshot = scan.capture_worker_snapshot_bytes()
    result = scan.tools.ocr.ocr_pages([1], doc=snapshot)
    assert result[1] == [_span("clamped")]


@pytest.mark.parametrize("queued", [False, True], ids=["direct", "queued"])
def test_decode_only_edit_rejects_result_from_worker_pixels(scan, monkeypatch, queued):
    snapshot = scan.capture_worker_snapshot_bytes()
    proof = scan.ocr_source_keys_from_snapshot(snapshot, [1])[1]
    seen = []

    def recognize(image, _languages):
        seen.append(image.getpixel((20, 20)))
        return [((24, 24, 200, 56), "old pixels", 0.99)]

    monkeypatch.setattr(ocr_tool, "_check_surya_import", lambda: (True, ""))
    monkeypatch.setattr(ocr_tool, "_create_surya_adapter", lambda _device: SimpleNamespace(ocr=recognize))
    monkeypatch.setattr(ocr_tool, "_empty_torch_cache", lambda _device: None)
    spans = scan.tools.ocr.ocr_pages([1], doc=snapshot)[1]
    assert seen == [(40, 40, 40)]
    assert _pix(scan, 1).pixel(20, 20) == (40, 40, 40)

    if queued:
        lease = scan.write_gate.begin("vector_delete", scan.get_active_session_id())
        assert isinstance(scan.submit_ocr_page(1, spans, source=proof), Deferred)
    xref = scan.doc[0].get_images()[0][0]
    original_stream = scan.doc.xref_stream_raw(xref)
    scan.doc.xref_set_key(xref, "Decode", "[1 0]")
    assert scan.doc.xref_stream_raw(xref) == original_stream
    assert _pix(scan, 1).pixel(20, 20) == (215, 215, 215)

    if queued:
        lease.release()
        outcome, = scan.drain_pending_ocr()
    else:
        outcome = scan.submit_ocr_page(1, spans, source=proof)
    assert isinstance(outcome, Stale)
    assert scan.pending_ocr_count == 0
    assert not scan.doc[0].get_text()


def test_proof_fault_retains_fifo_until_vector_success_is_visible(scan, monkeypatch):
    # Exercise the controller entry point with the real model, without a QApplication.
    from controller.pdf_controller import PDFController

    monkeypatch.setenv("PDF_EDITOR_VECTOR_EDIT", "1")
    streams, frame = scan.vector_page_source(1)
    scan.install_vector_index(1, scan_page(list(streams), frame))
    selected = scan.vector_select(VectorSelectionQuery(1, (170, 220, 170, 220), 1.0, "click", "replace"))
    snapshot = scan.capture_worker_snapshot_bytes()
    # Queue results for two unchanged image pages, so the vector edit changes
    # the document revision while both proofs can still match.
    proofs = scan.ocr_source_keys_from_snapshot(snapshot, [2, 3])
    trace = []
    real_commit = scan.commit_vector_plan

    def commit(*args, **kwargs):
        for page, label in ((2, "first"), (3, "second")):
            assert isinstance(scan.submit_ocr_page(page, [_span(label)], source=proofs[page]), Deferred)
        return real_commit(*args, **kwargs)

    real_proof = scan.ocr_source_key
    real_apply = scan.apply_ocr_spans
    fail_once = True

    def prove(page_num):
        nonlocal fail_once
        trace.append("prove")
        if fail_once:
            fail_once = False
            raise RuntimeError("transient OCR proof failure")
        return real_proof(page_num)

    def apply(page_num, spans, **kwargs):
        gray = {2: 90, 3: 130}[page_num]
        assert _pix(scan, page_num).pixel(20, 20) == (gray, gray, gray)
        trace.append(spans[0].text)
        return real_apply(page_num, spans, **kwargs)

    def refreshed(_command):
        trace.append("vector refresh")
        assert scan.command_manager.undo_count == 1
        assert _pix(scan, 1).pixel(340, 440) == (255, 255, 255)

    monkeypatch.setattr(scan, "commit_vector_plan", commit)
    monkeypatch.setattr(scan, "ocr_source_key", prove)
    monkeypatch.setattr(scan, "apply_ocr_spans", apply)
    controller = SimpleNamespace(
        model=scan,
        view=SimpleNamespace(clear_vector_selection=lambda: None),
        _write_busy=lambda: False,
        _vector_pump=lambda *_: None,
        _invalidate_active_render_state=lambda: None,
        _refresh_after_command=refreshed,
        _update_undo_redo_tooltips=lambda: None,
    )

    PDFController._on_vector_delete(controller, selected.token)
    assert trace == ["vector refresh", "prove"]
    assert scan.pending_ocr_count == 2
    assert not scan.doc[1].get_text()
    assert scan.drain_pending_ocr() == [Applied(1), Applied(1)]
    assert trace == ["vector refresh", "prove", "prove", "first", "prove", "second"]
    assert scan.doc[1].get_text().split() == ["first"]
    assert scan.doc[2].get_text().split() == ["second"]
    assert scan.drain_pending_ocr() == []


def test_notification_failure_cannot_reapply_an_acknowledged_head(scan):
    proof = scan.ocr_source_key(2)
    with scan.write_gate.begin("vector_delete", scan.get_active_session_id()):
        for label in ("first", "second"):
            assert isinstance(scan.submit_ocr_page(2, [_span(label)], source=proof), Deferred)

    receipts = []

    def notify():
        receipts.append(scan.doc[1].get_text().split())
        if len(receipts) == 1:
            raise RuntimeError("transient OCR notification failure")

    scan.on_ocr_applied = notify
    scan.drain_pending_ocr()
    scan.drain_pending_ocr()
    assert scan.pending_ocr_count == 0
    assert scan.doc[1].get_text().split() == ["first", "second"]
    assert receipts == [["first"], ["first", "second"]]


@pytest.mark.parametrize("shared_contents", [False, True], ids=["private-contents", "shared-contents"])
def test_apply_fault_after_insertion_retains_head_without_duplicating_text(scan, monkeypatch, shared_contents):
    doc = scan.doc
    if shared_contents:
        array_xref = doc.get_new_xref()
        stream_xref, = doc[1].get_contents()
        doc.update_object(array_xref, f"[{stream_xref} 0 R]")
        for page_idx in (1, 2):
            doc.xref_set_key(doc[page_idx].xref, "Contents", f"{array_xref} 0 R")

    proof = scan.ocr_source_key(2)
    with scan.write_gate.begin("vector_delete", scan.get_active_session_id()):
        assert isinstance(scan.submit_ocr_page(2, [_span("retry me")], source=proof), Deferred)

    before = scan.doc[1].get_contents()
    rebuild = scan.block_manager.rebuild_page

    def fail(_idx, _doc):
        raise RuntimeError("transient OCR index failure")

    monkeypatch.setattr(scan.block_manager, "rebuild_page", fail)
    assert scan.drain_pending_ocr() == []
    assert scan.pending_ocr_count == 1
    assert scan.doc[1].get_contents() == before
    assert not scan.doc[2].get_text()
    assert not scan.doc[1].get_text()
    monkeypatch.setattr(scan.block_manager, "rebuild_page", rebuild)
    assert scan.drain_pending_ocr() == [Applied(1)]
    assert scan.doc[1].get_text().split() == ["retry", "me"]
    assert not scan.doc[2].get_text()
    assert scan.drain_pending_ocr() == []
