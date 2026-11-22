"""Background verification of long streams (owner-approved design change 2026-11-22).

A writer never uses an offset a child reported (A4 class), so it lexes the decoded content stream
itself.  For a long stream that lex costs about 150 ms per MB, so it runs in a worker thread, off the
GUI thread, and the result is kept as a *verified scan* keyed by the decoded bytes.  An edit finds the
verified scan and lexes nothing; a long stream without one is refused with the document unchanged
and a distinct status; a short one (up to 256 KiB) is still lexed inline.

Outcome checks: calling-thread time of the edits, which thread ran ``scan_stream``, what the document
holds after a refusal, and the longest GUI heartbeat gap while a 7 MB verification runs.
"""
from __future__ import annotations

import threading
import time

import fitz
import pytest

from controller.object_probe_coordinator import Job, ObjectProbeCoordinator
from model import content_scan, pdf_content_ops, pdf_object_ops
from model.content_scan import content_key
from model.object_op_refusal import ObjectOpRefusal
from model.object_requests import DeleteObjectRequest, MoveObjectRequest
from model.pdf_model import PDFModel
from test_scripts.gui_stall_probe import run_gesture
from test_scripts.test_gui_stall import _path_stream

# Without the lex the calling thread still decodes the 7 MB stream, hashes it (content key, about 6 ms
# per MB, a few times) and Flate-encodes the result (zlib level 1, about 50 ms): measured 2026-11-22
# on the development machine, move 107-143 ms and delete 170-189 ms (cProfile of the delete: decode
# 3 x 17 ms, zlib 51 ms, hashes 23 ms, lex 0).  The lex it replaces cost about 1,055 ms.  The bounds
# are guards against the lex coming back (that alone adds about 1 s), not the 100 ms GUI standard,
# which the remaining decode/hash/encode work still exceeds on a 7 MB stream (reported to the owner).
MOVE_LIMIT_MS = 250.0
DELETE_LIMIT_MS = 400.0
# Measured 2026-11-22 (three runs): longest heartbeat gap 62-65 ms over the whole request, the
# 7 MB lex in the worker and the GUI-thread arrival step (page set-key walk) included.
HEARTBEAT_GAP_LIMIT_MS = 100.0
DEST = fitz.Rect(150, 100, 250, 170)


def _build(path, paths: int) -> None:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
        pix.clear_with(120)
        page.insert_image(fitz.Rect(300, 400, 400, 470), pixmap=pix)
        name = str(page.get_images(full=True)[0][7])
        xrefs = [int(x) for x in page.get_contents()]
        doc.update_stream(
            xrefs[0],
            _path_stream(paths) + f"\nq 100 0 0 70 300 372 cm /{name} Do Q\n".encode("ascii"),
        )
        for extra in xrefs[1:]:
            doc.update_stream(extra, b" ")
        doc.save(path)


@pytest.fixture(scope="module")
def seven_mb_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("verify7") / "seven.pdf"
    _build(path, 330_000)
    return path


@pytest.fixture(scope="module")
def one_mb_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("verify1") / "one.pdf"
    _build(path, 48_000)
    return path


@pytest.fixture(scope="module")
def two_hundred_kib_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("verify02") / "small.pdf"
    _build(path, 7_000)
    return path


def _open(path) -> PDFModel:
    content_scan.clear_scan_cache()
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def _stream(model: PDFModel) -> bytes:
    return model.doc.xref_stream(int(model.doc[0].get_contents()[0]))


def _pump_until(app, predicate, timeout_s: float = 120.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


class _ScanSpy:
    """Counts ``scan_stream`` calls per thread id (the calling thread's are the ones that matter)."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list[int] = []
        real = content_scan.scan_stream

        def spy(stream, *args, **kwargs):
            self.calls.append(threading.get_ident())
            return real(stream, *args, **kwargs)

        for module in (content_scan, pdf_content_ops, pdf_object_ops):
            monkeypatch.setattr(module, "scan_stream", spy, raising=False)

    def on_this_thread(self) -> int:
        return sum(1 for ident in self.calls if ident == threading.get_ident())


def _child_answer_cached(model: PDFModel) -> tuple[bytes, bytes]:
    """What the child's scan answer leaves behind: the answer in the child-answer cache (not
    verified).  Returns ``(key, decoded stream)``."""
    stream = _stream(model)
    key = content_key(stream)
    content_scan.store_scan(key, content_scan.scan_stream(stream))
    return key, stream


def _install_scan_answer(model: PDFModel, coordinator: ObjectProbeCoordinator) -> list[bytes]:
    """Feed the coordinator the answer the child would give for the page's long streams."""
    wanted = model.image_scan_jobs(1)
    assert wanted, "the page must have a long stream awaiting the child"
    key = tuple(k for k, _s in wanted)
    answer = {"status": "complete", "scans": [content_scan.to_json(content_scan.scan_stream(s)) for _k, s in wanted]}
    job = Job(
        "scan", 1, key, tuple(s for _k, s in wanted),
        frame=(1, model.image_scan_set_key(1)), generation=model.handle_generation,
    )
    coordinator._on_scan_answer(job, answer, "complete")
    return list(key)


def _move(model: PDFModel) -> bool:
    return bool(model.move_object(MoveObjectRequest("native_image:1:0", "native_image", 1, 1, fitz.Rect(DEST))))


def _delete(model: PDFModel) -> bool:
    return bool(model.delete_object(DeleteObjectRequest("native_image:1:0", "native_image", 1)))


def test_verified_page_edits_take_no_lex_on_the_calling_thread(qapp, seven_mb_pdf, monkeypatch):
    model = _open(seven_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        keys = _install_scan_answer(model, coordinator)  # real lexing here, before the spy
        assert _pump_until(qapp, lambda: all(content_scan.verified_scan(k) is not None for k in keys))
        assert not coordinator.scan_verifier.is_busy()
        spy = _ScanSpy(monkeypatch)
        before = _stream(model)
        started = time.perf_counter()
        assert _move(model), model.last_object_op_refusal
        move_ms = (time.perf_counter() - started) * 1000.0
        assert _stream(model) != before
        started = time.perf_counter()
        assert _delete(model), model.last_object_op_refusal
        delete_ms = (time.perf_counter() - started) * 1000.0
        print(f"VERIFIED 7 MB page: move {move_ms:.0f} ms, delete {delete_ms:.0f} ms on the calling thread")
        assert spy.on_this_thread() == 0
        assert move_ms < MOVE_LIMIT_MS, move_ms
        assert delete_ms < DELETE_LIMIT_MS, delete_ms
    finally:
        model.close()


def test_unverified_long_stream_is_refused_unchanged_then_succeeds_after_verification(qapp, seven_mb_pdf, monkeypatch):
    model = _open(seven_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        key, stream = _child_answer_cached(model)  # an answer is cached, no verified scan yet
        spy = _ScanSpy(monkeypatch)
        for op in (_move, _delete):
            assert op(model) is False
            assert _stream(model) == stream  # the document is unchanged
            refusal = model.last_object_op_refusal
            assert refusal is not None and refusal.reason is ObjectOpRefusal.ANALYSING
        assert spy.on_this_thread() == 0  # never lexed on the calling thread
        assert content_scan.verified_scan(key) is None
        # the controller's refusal path hands the remembered request to the verifier
        coordinator.request_pending_verifications()
        assert coordinator.scan_verifier.is_busy()
        assert _pump_until(qapp, lambda: content_scan.verified_scan(key) is not None)
        assert _move(model), model.last_object_op_refusal
        assert _stream(model) != stream
        assert spy.on_this_thread() == 0
    finally:
        model.close()


def test_a_short_stream_up_to_256_kib_is_lexed_inline(qapp, two_hundred_kib_pdf, monkeypatch):
    model = _open(two_hundred_kib_pdf)
    try:
        stream = _stream(model)
        assert content_scan.MUTATION_INLINE_SCAN_LIMIT_BYTES // 2 < len(stream) <= content_scan.MUTATION_INLINE_SCAN_LIMIT_BYTES
        spy = _ScanSpy(monkeypatch)
        assert _move(model), model.last_object_op_refusal
        assert spy.on_this_thread() >= 1  # inline lex, no verification needed
        assert content_scan.verified_scan(content_key(stream)) is not None  # and kept
    finally:
        model.close()


def test_a_result_for_a_changed_stream_is_dropped(qapp, one_mb_pdf):
    model = _open(one_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        stream = _stream(model)
        key = content_key(stream)
        coordinator.request_verification(1, key, stream)
        assert coordinator.scan_verifier.is_busy()
        model.doc.update_stream(int(model.doc[0].get_contents()[0]), stream + b"\n0 0 m 1 1 l S\n")  # edit between schedule and arrival
        assert _pump_until(qapp, lambda: not coordinator.scan_verifier.is_busy())
        assert content_scan.verified_scan(key) is None
    finally:
        model.close()


def test_a_failed_verification_records_nothing_and_a_later_request_runs(qapp, one_mb_pdf, monkeypatch):
    model = _open(one_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        stream = _stream(model)
        key = content_key(stream)
        real = content_scan.scan_stream

        def broken(_stream_bytes, *_args, **_kwargs):
            raise MemoryError("simulated")

        monkeypatch.setattr(content_scan, "scan_stream", broken)
        coordinator.request_verification(1, key, stream)
        assert _pump_until(qapp, lambda: not coordinator.scan_verifier.is_busy())
        assert content_scan.verified_scan(key) is None
        monkeypatch.setattr(content_scan, "scan_stream", real)
        coordinator.request_verification(1, key, stream)
        assert _pump_until(qapp, lambda: content_scan.verified_scan(key) is not None)
    finally:
        model.close()


def test_cancelled_verification_records_nothing(qapp, one_mb_pdf):
    model = _open(one_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        stream = _stream(model)
        key = content_key(stream)
        coordinator.request_verification(1, key, stream)
        coordinator.cancel_all()
        assert _pump_until(qapp, lambda: not coordinator.scan_verifier.is_busy())
        assert content_scan.verified_scan(key) is None
    finally:
        model.close()


def test_gui_heartbeat_gap_while_a_7_mb_verification_runs(qapp, seven_mb_pdf):
    model = _open(seven_mb_pdf)
    coordinator = ObjectProbeCoordinator(model)
    try:
        stream = _stream(model)
        key = content_key(stream)
        finished_flag = {"done": False}
        coordinator.scan_verifier.idle.connect(lambda: finished_flag.__setitem__("done", True))
        gap, finished = run_gesture(
            qapp,
            lambda: coordinator.request_verification(1, key, stream),
            lambda: finished_flag["done"],
        )
        print(f"HEARTBEAT 7 MB verification: longest gap {gap:.1f} ms, finished={finished}")
        assert finished
        assert content_scan.verified_scan(key) is not None
        assert gap < HEARTBEAT_GAP_LIMIT_MS, gap
    finally:
        model.close()
