"""Card A5: a path-heavy page that holds an image is scanned in the object-probe child (H14 to H18)."""
from __future__ import annotations

import os
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace

import fitz
import pymupdf
import pytest

import view.pdf_view as pdf_view
from model import content_scan, pdf_content_ops, pdf_object_ops
from model.content_scan import clear_scan_cache, content_key, scan_stream
from model.object_requests import (
    OBJECT_LOOKUP_PENDING,
    BatchDeleteObjectsRequest,
    BatchMoveObjectsRequest,
    DeleteObjectRequest,
    InsertImageObjectRequest,
    MoveObjectRequest,
    ObjectRef,
    ResizeObjectRequest,
    RotateObjectRequest,
)
from model.pdf_content_ops import INLINE_SCAN_LIMIT_BYTES
from model.pdf_model import PDFModel
from src.object_probe import helper_main
from test_scripts.test_object_probe import StubRunner, _coordinator
from test_scripts.test_object_probe_child import MEM, _answer, _stdin
from utils.object_probe_platform import contained_probe_supported
from utils.pdf_object_source import xref_object_exact, xref_set_key_exact

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_POINT = fitz.Point(70, 55)
needs_child = pytest.mark.skipif(
    not contained_probe_supported(), reason="the in-process refusal and the child's failures exist only with the contained child"
)
SCAN_MSG = "正在背景分析此頁的影像，完成後會自動選取…"
REFUSED_MSG = "正在分析此頁的影像（此頁內容較多），完成後請再操作一次"
READY_MSG = "此頁影像分析完成，可以操作了"


SCAN_LIMITED_MSG = "此頁內容過多，影像分析超出上限而未完成；此頁的影像目前無法編輯，較長內容中的影像也無法選取（其他物件不受影響）"
SCAN_HEADROOM_MSG = "目前可用記憶體不足，暫時無法分析此頁的影像，請稍後再操作一次"
IMAGE2_POINT = fitz.Point(200, 55)


def _png(shade: int = 200) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    pix.clear_with(shade)
    return pix.tobytes("png")


def _two_stream_pdf(path, *, long_flags: tuple[bool, bool] = (True, True), with_other_page: bool = False) -> str:
    """Page 1 has two content streams, each with one image ``Do`` (image 1 at visual x 20..120,
    image 2 at x 150..250); a stream is longer than INLINE_SCAN_LIMIT_BYTES where its flag is True.
    ``with_other_page`` adds page 2: one long stream (distinct content) and one image."""
    with fitz.open() as doc:
        page = doc.new_page(width=320, height=240)
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png(200))
        page.insert_image(fitz.Rect(150, 20, 250, 90), stream=_png(90))
        names = [str(row[7]) for row in page.get_images(full=True)]
        assert len(names) == 2
        xrefs = [int(x) for x in page.get_contents()]
        pads = [b"0.2 w 10 10 m 12 14 l S\n" * (6000 + i) if flag else b"0 0 m 1 1 l S\n" for i, flag in enumerate(long_flags)]
        bodies = [
            pads[0] + f"q 100 0 0 70 20 150 cm /{names[0]} Do Q\n".encode("ascii"),
            pads[1] + f"q 100 0 0 70 150 150 cm /{names[1]} Do Q\n".encode("ascii"),
        ]
        doc.update_stream(xrefs[0], bodies[0])
        second = doc.get_new_xref()
        doc.update_object(second, "<< >>")
        doc.update_stream(second, bodies[1])
        doc.xref_set_key(page.xref, "Contents", f"[{xrefs[0]} 0 R {second} 0 R]")
        if with_other_page:
            other = doc.new_page(width=320, height=240)
            other.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png(50))
            name = str(other.get_images(full=True)[0][7])
            ox = [int(x) for x in other.get_contents()]
            doc.update_stream(ox[0], b"0.2 w 10 10 m 12 14 l S\n" * 7000 + f"q 100 0 0 70 20 150 cm /{name} Do Q\n".encode("ascii"))
            for extra in ox[1:]:
                doc.update_stream(extra, b" ")
        doc.save(path)
    return str(path)


def _long_image_pdf(path, pages: int = 1) -> str:
    """Each page: > INLINE_SCAN_LIMIT_BYTES of path operators, then one image at visual y 20..90."""
    with fitz.open() as doc:
        for index in range(pages):
            page = doc.new_page(width=320, height=240)
            page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png())
            name = str(page.get_images(full=True)[0][7])
            xrefs = [int(x) for x in page.get_contents()]
            pad = b"0.2 w 10 10 m 12 14 l S\n" * (6000 + index)  # distinct content per page: scans are keyed by content
            assert len(pad) > INLINE_SCAN_LIMIT_BYTES
            doc.update_stream(xrefs[0], pad + f"q 100 0 0 70 20 150 cm /{name} Do Q\n".encode("ascii"))
            for extra in xrefs[1:]:
                doc.update_stream(extra, b" ")
        doc.save(path)
    return str(path)


@pytest.fixture
def model(tmp_path):
    clear_scan_cache()
    m = PDFModel()
    m.open_pdf(_long_image_pdf(tmp_path / "long.pdf", pages=2))
    yield m
    m.close()
    clear_scan_cache()


def _stream(model: PDFModel, page: int = 1) -> bytes:
    return model.doc.xref_stream(int(model.doc[page - 1].get_contents()[0]))


def _scan_answer(model: PDFModel, page: int = 1) -> dict:
    return {"v": 2, "status": "complete", "scans": [content_scan.to_json(scan_stream(_stream(model, page)))]}


# --------------------------------------------------------------------------- model


def test_short_stream_page_has_no_scan_jobs(tmp_path):
    clear_scan_cache()
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png())
        doc.save(tmp_path / "s.pdf")
    m = PDFModel()
    try:
        m.open_pdf(str(tmp_path / "s.pdf"))
        assert m.image_scan_jobs(1) == []
        assert m.get_object_info_at_point(1, IMAGE_POINT, blocking=False) is not OBJECT_LOOKUP_PENDING
    finally:
        m.close()


def test_long_stream_page_lists_one_job_keyed_by_content(model):
    jobs = model.image_scan_jobs(1)
    assert jobs == [(content_key(_stream(model)), _stream(model))]


def test_non_blocking_lookup_is_pending_until_the_scan_is_stored(model):
    assert model.get_object_info_at_point(1, IMAGE_POINT, blocking=False) is OBJECT_LOOKUP_PENDING
    (key, stream), = model.image_scan_jobs(1)
    content_scan.store_scan(key, scan_stream(stream))
    assert model.image_scan_jobs(1) == []
    info = model.get_object_info_at_point(1, IMAGE_POINT, blocking=False)
    assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "native_image"


def test_blocking_lookup_scans_in_process_and_does_not_wait(model):
    info = model.get_object_info_at_point(1, IMAGE_POINT)
    assert info is not None and info.object_kind == "native_image"
    assert model.image_scan_jobs(1) == []


def _frame_failed(model, page: int = 1) -> bool:
    return model.image_scan_failed(page)


def test_a_failed_frame_lists_no_job_and_the_page_reports_no_native_image(model):
    model.mark_image_scan_failed(1, model.image_scan_set_key(1))
    assert model.image_scan_jobs(1) == []
    assert model.get_object_info_at_point(1, IMAGE_POINT) is None
    assert len(model.image_scan_jobs(2)) == 1  # the other page is not covered


# --------------------------------------------------------------------------- child


def test_scan_kind_answers_the_json_of_each_scan():
    streams = [b"q 1 0 0 1 0 0 cm /A Do Q", b"/B Do"]
    answer = helper_main._KINDS["scan"](streams)
    assert answer["v"] == 2 and answer["status"] == "complete"
    assert [content_scan.from_json(s) for s in answer["scans"]] == [scan_stream(s) for s in streams]


@pytest.mark.skipif(
    not contained_probe_supported(), reason="the contained child cannot run on this platform"
)
def test_real_child_scan_needs_neither_qt_nor_fitz(tmp_path):
    stub_root = tmp_path / "stubs"
    for name in ("PySide6", "fitz"):
        (stub_root / name).mkdir(parents=True)
        (stub_root / name / "__init__.py").write_text(f"raise ImportError('{name} must not load')", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(stub_root) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    import sys

    streams = [b"q 1 0 0 1 0 0 cm /A Do Q 0 0 m 1 1 l S", b"/B Do"]
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--object-probe"],
        input=_stdin("scan", *streams, mem=MEM), capture_output=True, timeout=120, cwd=REPO_ROOT, env=env,
    )
    assert result.returncode == 0, result.stderr
    answer = _answer(result.stdout)
    assert answer["status"] == "complete"
    assert [content_scan.from_json(s) for s in answer["scans"]] == [scan_stream(s) for s in streams]


# --------------------------------------------------------------------------- coordinator


def test_request_image_scan_submits_the_decoded_streams_once(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_image_scan(1)
    coord.request_image_scan(1)  # same content keys: running, not asked again
    assert len(runner.order) == 1
    owner, kind, payloads = runner.jobs[runner.order[0]]
    assert (owner, kind, payloads) == (coord, "scan", (_stream(model),))


def test_page_without_jobs_submits_nothing(tmp_path):
    clear_scan_cache()
    with fitz.open() as doc:
        doc.new_page()
        doc.save(tmp_path / "e.pdf")
    m = PDFModel()
    try:
        m.open_pdf(str(tmp_path / "e.pdf"))
        runner = StubRunner()
        _coordinator(m, runner).request_image_scan(1)
        assert runner.order == []
    finally:
        m.close()


def test_answer_stores_the_scans_and_announces_the_page(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    seen = []
    coord.image_scan_ready.connect(seen.append)
    coord.request_image_scan(1)
    runner.complete(runner.order[0], _scan_answer(model))
    assert seen == [1]
    assert content_scan.cached_scan(content_key(_stream(model))) == scan_stream(_stream(model))
    assert model.image_scan_jobs(1) == []


def test_crash_is_retried_once_then_the_key_is_remembered_and_reported(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda *a: failures.append(a))
    coord.request_image_scan(1)
    runner.fail(runner.order[0])
    assert len(runner.order) == 2  # the retry
    runner.fail(runner.order[1])
    assert failures == [("scan", 1, "crashed")]
    assert _frame_failed(model)
    assert model.image_scan_jobs(1) == []


@pytest.mark.parametrize("status", ["resource_limited", "analysis_failed", "containment_failed"])
def test_typed_failure_is_not_retried_and_marks_the_frame(model, status):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda *a: failures.append(a))
    coord.request_image_scan(1)
    runner.complete(runner.order[0], {"v": 2, "status": status})
    assert len(runner.order) == 1
    assert failures == [("scan", 1, status)]
    assert _frame_failed(model)
    assert not _frame_failed(model, 2)


def test_no_headroom_marks_nothing(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_image_scan(1)
    runner.complete(runner.order[0], {"v": 2, "status": "no_headroom"})
    assert not _frame_failed(model)
    assert content_scan._failed_sets == {}
    assert len(model.image_scan_jobs(1)) == 1


def test_malformed_complete_answer_is_a_runner_failure(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_image_scan(1)
    runner.complete(runner.order[0], {"v": 2, "status": "complete", "scans": [{"junk": 1}]})
    assert len(runner.order) == 2


# --------------------------------------------------------------------------- controller


def _controller(qapp, model, monkeypatch):
    from controller.pdf_controller import PDFController

    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    view = pdf_view.PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    stub = StubRunner()
    controller._object_probe._runner = stub
    log = SimpleNamespace(status=[], resolved=[], dropped=[], refused=[])
    view.set_status_bar_override_message = log.status.append
    view.resolve_pending_object_click = log.resolved.append
    view.drop_pending_object_click = lambda page=None: log.dropped.append(True)
    view.note_object_op_refused = log.refused.append
    return view, controller, stub, log


def _native_id(page: int = 1) -> str:
    return f"native_image:{page}:0"


def test_cold_lookup_asks_for_the_scan_and_says_so(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        assert controller.lookup_object_at_point(1, IMAGE_POINT) is OBJECT_LOOKUP_PENDING
        assert [stub.jobs[j][1] for j in stub.order] == ["scan"]
        assert log.status == [SCAN_MSG]
    finally:
        dispose_pdf_view(view, controller, model)


def test_scan_answer_resolves_the_pending_click_and_shows_ready(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, IMAGE_POINT)
        stub.complete(stub.order[0], _scan_answer(model))
        assert log.resolved == [1]
        assert log.status[-1] == READY_MSG
        info = controller.lookup_object_at_point(1, IMAGE_POINT)
        assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "native_image"
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.fixture
def unsupported(monkeypatch):
    from utils import object_probe_platform

    monkeypatch.setattr(object_probe_platform, "contained_probe_supported", lambda: False)


def test_unsupported_platform_lists_no_scan_job_and_the_lookup_is_never_pending(model, unsupported):
    assert model.image_scan_jobs(1) == []
    info = model.get_object_info_at_point(1, IMAGE_POINT, blocking=False)
    assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "native_image"


def test_unsupported_platform_click_selects_in_process_without_a_job(qapp, model, monkeypatch, unsupported):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        info = controller.lookup_object_at_point(1, IMAGE_POINT)
        assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "native_image"
        assert stub.jobs == {}
        assert log.status == []
        assert controller.object_op_ready([1], ["native_image"]) is True  # not refused as "analysing"
        assert controller.object_op_ready([1], ["image"]) is True
        assert stub.jobs == {} and log.status == []
        controller._object_probe.request_image_scan(1)
        assert stub.jobs == {}
    finally:
        dispose_pdf_view(view, controller, model)


def test_the_ready_message_goes_away_after_four_seconds(qapp, model, monkeypatch):
    from PySide6.QtCore import QTimer

    from test_scripts.qt_teardown import dispose_pdf_view

    delays = []
    real = QTimer.singleShot
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, cb, *a: (delays.append(ms), real(0, cb))[1]))
    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, IMAGE_POINT)
        stub.complete(stub.order[0], _scan_answer(model))
        assert 4000 in delays
        qapp.processEvents()
        assert log.status[-1] is None
    finally:
        dispose_pdf_view(view, controller, model)


def test_failed_scan_reports_the_page_and_drops_the_click(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, IMAGE_POINT)
        stub.complete(stub.order[0], {"v": 2, "status": "analysis_failed"})
        assert log.status[-1] == "此頁的物件分析未完成（第 1 頁）"
        assert log.dropped == [True]
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("kind", ["native_image", "image"])
def test_object_op_ready_is_false_for_an_image_on_a_cold_page(qapp, model, monkeypatch, kind):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        assert controller.object_op_ready([1], ["rect"]) is True
        assert stub.jobs == {}
        assert controller.object_op_ready([1], [kind]) is False
        assert [stub.jobs[j][1] for j in stub.order] == ["scan"]
        assert log.status[-1] == REFUSED_MSG
        stub.complete(stub.order[0], _scan_answer(model))
        assert controller.object_op_ready([1], [kind]) is True
    finally:
        dispose_pdf_view(view, controller, model)


def _verbs(model):
    rect = fitz.Rect(30, 40, 130, 110)
    return {
        "move": lambda c: c.move_object(MoveObjectRequest(_native_id(), "native_image", 1, 1, rect)),
        "resize": lambda c: c.resize_object(ResizeObjectRequest(_native_id(), "native_image", 1, rect)),
        "rotate": lambda c: c.rotate_object(RotateObjectRequest(_native_id(), "native_image", 1, 90)),
        "delete": lambda c: c.delete_object(DeleteObjectRequest(_native_id(), "native_image", 1)),
        "add": lambda c: c.add_image_object(InsertImageObjectRequest(1, rect, _png())),
    }


@pytest.mark.parametrize("verb", ["move", "resize", "rotate", "delete", "add"])
def test_edit_on_a_cold_image_page_is_refused_without_dialog_or_change(qapp, model, monkeypatch, verb):
    from test_scripts.qt_teardown import dispose_pdf_view

    errors = []
    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: errors.append(a))
    try:
        stream_before = _stream(model)
        undo_before = len(model.command_manager._undo_stack) if hasattr(model.command_manager, "_undo_stack") else None
        _verbs(model)[verb](controller)
        assert errors == []
        assert _stream(model) == stream_before
        assert [stub.jobs[j][1] for j in stub.order] == ["scan"]
        assert log.status[-1] == REFUSED_MSG
        if verb in ("move", "resize", "rotate"):
            assert log.refused == [[_native_id()]]
        if undo_before is not None:
            assert len(model.command_manager._undo_stack) == undo_before
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("verb", ["move", "resize", "rotate", "delete"])
def test_the_repeated_gesture_succeeds_once_the_scan_is_stored(qapp, model, monkeypatch, verb):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        stream_before = _stream(model)
        _verbs(model)[verb](controller)
        stub.complete(stub.order[0], _scan_answer(model))
        _verbs(model)[verb](controller)
        assert _stream(model) != stream_before
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_batch_checks_every_member_before_any_is_executed(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        # Page 2 is warm (its scan stored), page 1 is cold: nothing may run for either.
        (key, stream), = model.image_scan_jobs(2)
        content_scan.store_scan(key, scan_stream(stream))
        stream1, stream2 = _stream(model, 1), _stream(model, 2)
        rect = fitz.Rect(30, 40, 130, 110)
        controller.move_object(
            BatchMoveObjectsRequest(
                [
                    MoveObjectRequest(_native_id(2), "native_image", 2, 2, rect),
                    MoveObjectRequest(_native_id(1), "native_image", 1, 1, rect),
                ]
            )
        )
        controller.delete_object(
            BatchDeleteObjectsRequest(
                [ObjectRef(_native_id(2), "native_image", 2), ObjectRef(_native_id(1), "native_image", 1)]
            )
        )
        assert (_stream(model, 1), _stream(model, 2)) == (stream1, stream2)
        assert log.status[-1] == REFUSED_MSG
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- card D12: sets and scopes


def _open(tmp_path, name: str = "two.pdf", **kwargs) -> PDFModel:
    clear_scan_cache()
    m = PDFModel()
    m.open_pdf(_two_stream_pdf(tmp_path / name, **kwargs))
    return m


@pytest.fixture
def two_model(tmp_path):
    m = _open(tmp_path, with_other_page=True)
    yield m
    m.close()
    clear_scan_cache()


def _page_streams(model: PDFModel, page: int = 1) -> list[bytes]:
    return [model.doc.xref_stream(int(x)) for x in model.doc[page - 1].get_contents()]


def _set_answer(model: PDFModel, page: int = 1) -> dict:
    scans = [content_scan.to_json(scan_stream(s)) for s in _page_streams(model, page)]
    return {"v": 2, "status": "complete", "scans": scans}


def test_over_cap_set_stores_nothing_and_ends_resource_limited(two_model, monkeypatch):
    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
    (other_key, other_stream), = two_model.image_scan_jobs(2)
    other = scan_stream(other_stream)
    content_scan.store_scan(other_key, other)
    assert content_scan.cached_scan(other_key) == other
    runner = StubRunner()
    coord = _coordinator(two_model, runner)
    ready, failures = [], []
    coord.image_scan_ready.connect(ready.append)
    coord.probe_failed.connect(lambda *a: failures.append(a))
    coord.request_image_scan(1)
    runner.complete(runner.order[0], _set_answer(two_model))
    assert ready == []
    assert failures == [("scan", 1, "resource_limited")]
    assert len(runner.order) == 1  # no retry
    for stream in _page_streams(two_model):
        assert content_scan.cached_scan(content_key(stream)) is None
    assert content_scan.cached_scan(other_key) == other  # the other page's entry still hits
    assert two_model.image_scan_jobs(1) == []
    coord.request_image_scan(1)
    assert len(runner.order) == 1  # the failed frame starts no second job


def test_answered_click_on_over_cap_page_starts_no_second_job(qapp, two_model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
    view, controller, stub, log = _controller(qapp, two_model, monkeypatch)
    try:
        assert controller.lookup_object_at_point(1, IMAGE_POINT) is OBJECT_LOOKUP_PENDING
        stub.complete(stub.order[0], _set_answer(two_model))
        assert len(stub.order) == 1
        assert log.status[-1] == SCAN_LIMITED_MSG
        assert READY_MSG not in log.status
        assert log.dropped == [True]
        assert log.resolved == []
    finally:
        dispose_pdf_view(view, controller, two_model)


def test_fitting_set_is_admitted_and_announced(two_model):
    runner = StubRunner()
    coord = _coordinator(two_model, runner)
    ready = []
    coord.image_scan_ready.connect(ready.append)
    coord.request_image_scan(1)
    runner.complete(runner.order[0], _set_answer(two_model))
    assert ready == [1]
    assert two_model.image_scan_jobs(1) == []


def test_short_inline_store_never_evicts_a_long_sibling(tmp_path, monkeypatch):
    m = _open(tmp_path, long_flags=(False, True), with_other_page=True)
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 2)
        (long_key, long_stream), = m.image_scan_jobs(1)  # only the long stream is awaited
        (other_key, other_stream), = m.image_scan_jobs(2)
        long_scan = scan_stream(long_stream)
        content_scan.store_scan(long_key, long_scan)  # the oldest entry
        content_scan.store_scan(other_key, scan_stream(other_stream))  # no lookup in between: keep the order
        scanned: list[int] = []
        real_scan = pdf_content_ops.scan_stream
        monkeypatch.setattr(pdf_content_ops, "scan_stream", lambda s: scanned.append(len(s)) or real_scan(s))
        info = m.get_object_info_at_point(1, IMAGE_POINT)  # blocking: scans the short stream inline
        assert info is not None and info.object_kind == "native_image"
        assert scanned == [len(_page_streams(m)[0])]  # only the short stream: the long one stayed cached
        assert content_scan.cached_scan(long_key) == long_scan
        assert content_scan.cached_scan(other_key) is None  # the other page's entry went instead
    finally:
        m.close()
        clear_scan_cache()


def test_derived_store_after_edit_never_evicts_a_sibling(tmp_path, monkeypatch):
    m = _open(tmp_path)
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 2)
        first, second = _page_streams(m)
        content_scan.store_scan(content_key(first), scan_stream(first))
        content_scan.store_scan(content_key(second), scan_stream(second))
        assert content_scan.cached_scan(content_key(first)) is not None
        hit = m.get_object_info_at_point(1, IMAGE2_POINT)
        assert hit is not None and hit.object_kind == "native_image"
        rect = fitz.Rect(160, 40, 260, 110)
        assert m.move_object(MoveObjectRequest(hit.object_id, hit.object_kind, 1, 1, rect)) is True
        edited = _page_streams(m)[1]
        assert edited != second
        assert content_scan.cached_scan(content_key(first)) is not None  # the sibling stayed
        assert content_scan.cached_scan(content_key(edited)) == scan_stream(edited)
        assert content_scan.cached_scan(content_key(second)) is None  # the replaced bytes went
    finally:
        m.close()
        clear_scan_cache()


def test_failure_is_scoped_to_the_handle_not_to_the_bytes(model, tmp_path):
    """D12 literal: the key includes the handle generation; a transient failure (child MemoryError,
    ledger refusal, crash) is no fact about the bytes, so the same bytes in document B are retried."""
    model.mark_image_scan_failed(1, model.image_scan_set_key(1))
    first = model._active_session_id
    model.open_pdf(_long_image_pdf(tmp_path / "b.pdf", pages=2), append=True)
    assert len(model.image_scan_jobs(1)) == 1  # document B: same bytes, not failed
    runner = StubRunner()
    _coordinator(model, runner).request_image_scan(1)
    assert len(runner.order) == 1
    assert model.close_session(first) is True
    assert len(model.image_scan_jobs(1)) == 1


def test_save_as_retries_a_failed_scan_once_on_the_new_generation(model, tmp_path):
    model.mark_image_scan_failed(1, model.image_scan_set_key(1))
    model.save_as(str(tmp_path / "copy.pdf"))
    assert len(model.image_scan_jobs(1)) == 1
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_image_scan(1)
    assert len(runner.order) == 1
    runner.fail(runner.order[0])
    runner.fail(runner.order[1])  # the retry; now failed under the new generation
    assert model.image_scan_jobs(1) == []
    coord.request_image_scan(1)
    assert len(runner.order) == 2  # no third job


def test_changed_page_content_is_not_covered_by_the_failure(model):
    model.mark_image_scan_failed(1, model.image_scan_set_key(1))
    xref = int(model.doc[0].get_contents()[0])
    model.doc.update_stream(xref, _stream(model) + b" ")
    assert len(model.image_scan_jobs(1)) == 1


def _answer_failed(runner, job):
    runner.complete(job, {"v": 2, "status": "analysis_failed"})


def test_save_as_during_a_scan_requests_a_job_for_the_new_handle(model, tmp_path):
    """P1 (Astra review of A5): a request on the new handle must not be swallowed by the old
    handle's job; the job identity is (handle generation, page, set key)."""
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_image_scan(1)
    model.save_as(str(tmp_path / "copy.pdf"))  # same bytes, new handle generation
    coord.request_image_scan(1)
    assert len(runner.order) == 2


def test_old_handle_failure_after_save_as_is_not_recorded_on_the_new_handle(model, tmp_path):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures, dropped = [], []
    coord.probe_failed.connect(lambda *a: failures.append(a))
    coord.probe_dropped.connect(lambda *a: dropped.append(a))
    coord.request_image_scan(1)
    old_job = runner.order[0]
    model.save_as(str(tmp_path / "copy.pdf"))
    _answer_failed(runner, old_job)  # the old handle's answer arrives after the switch
    assert model.image_scan_failed(1) is False
    assert content_scan._failed_sets == {}
    assert failures == []
    assert dropped == [("scan", 1)]
    assert len(model.image_scan_jobs(1)) == 1  # the new handle's page is still retried


def test_new_handle_scan_completes_after_the_old_handle_failure(model, tmp_path):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.image_scan_ready.connect(ready.append)
    coord.request_image_scan(1)
    old_job = runner.order[0]
    model.save_as(str(tmp_path / "copy.pdf"))
    coord.request_image_scan(1)
    _answer_failed(runner, old_job)
    runner.complete(runner.order[1], _scan_answer(model))
    assert ready == [1]
    assert model.image_scan_jobs(1) == []


def test_short_stream_change_during_a_scan_requests_a_job_for_the_new_set(tmp_path):
    """P1: the long stream (the job's missing keys) is unchanged but the page's set key is not;
    the second request is a different frame and must not be deduplicated into the stale job."""
    m = _open(tmp_path, long_flags=(False, True))
    try:
        runner = StubRunner()
        coord = _coordinator(m, runner)
        ready = []
        coord.image_scan_ready.connect(ready.append)
        coord.request_image_scan(1)
        short_xref = int(m.doc[0].get_contents()[0])
        m.doc.update_stream(short_xref, m.doc.xref_stream(short_xref) + b" ")
        coord.request_image_scan(1)
        assert len(runner.order) == 2
        (long_key, long_stream), = m.image_scan_jobs(1)
        answer = {"v": 2, "status": "complete", "scans": [content_scan.to_json(scan_stream(long_stream))]}
        runner.complete(runner.order[0], answer)  # the old frame: dropped, not announced
        assert ready == []
        runner.complete(runner.order[1], answer)
        assert ready == [1]
    finally:
        m.close()
        clear_scan_cache()


def test_the_last_close_empties_the_failed_sets(model):
    model.mark_image_scan_failed(1, model.image_scan_set_key(1))
    assert content_scan._failed_sets
    assert model.close_session(model._active_session_id) is True
    assert not model.live_handle_generations()
    assert content_scan._failed_sets == {}


def _change_page_one(model: PDFModel) -> None:
    xref = int(model.doc[0].get_contents()[0])
    model.doc.update_stream(xref, _stream(model) + b" ")


@pytest.mark.parametrize("outcome", ["analysis_failed", "resource_limited", "no_headroom", "crash", "crash_twice"])
def test_late_failure_for_a_changed_frame_is_dropped(model, outcome):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures, dropped = [], []
    coord.probe_failed.connect(lambda *a: failures.append(a))
    coord.probe_dropped.connect(lambda *a: dropped.append(a))
    coord.request_image_scan(1)
    job = runner.order[0]
    if outcome == "crash_twice":
        runner.fail(job)
        assert len(runner.order) == 2  # the frame was still current: retried
        job = runner.order[1]
    _change_page_one(model)
    if outcome.startswith("crash"):
        runner.fail(job)
    else:
        runner.complete(job, {"v": 2, "status": outcome})
    assert failures == []
    assert dropped == [("scan", 1)]
    assert len(runner.order) == (2 if outcome == "crash_twice" else 1)
    assert content_scan._failed_sets == {}


def test_complete_answer_for_a_changed_frame_is_admitted_as_its_own_set_but_not_announced(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready, failures, dropped = [], [], []
    coord.image_scan_ready.connect(ready.append)
    coord.probe_failed.connect(lambda *a: failures.append(a))
    coord.probe_dropped.connect(lambda *a: dropped.append(a))
    coord.request_image_scan(1)
    answer = _scan_answer(model)
    original = _stream(model)
    _change_page_one(model)
    runner.complete(runner.order[0], answer)
    assert ready == [] and failures == []
    assert dropped == [("scan", 1)]
    assert content_scan.cached_scan(content_key(original)) == scan_stream(original)
    assert content_scan._failed_sets == {}


@pytest.mark.parametrize("kind", ["native_image", "image"])
def test_op_on_failed_image_page_is_refused_with_the_scan_message(qapp, model, monkeypatch, kind):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        model.mark_image_scan_failed(1, model.image_scan_set_key(1), "resource_limited")
        before = _stream(model)
        assert controller.object_op_ready([1], [kind]) is False
        assert log.status[-1] == SCAN_LIMITED_MSG
        assert stub.jobs == {}
        assert controller.object_op_ready([1], ["rect"]) is True
        _verbs(model)["delete"](controller)
        assert _stream(model) == before
        assert stub.jobs == {}
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize(
    "reason,text", [("resource_limited", SCAN_LIMITED_MSG), ("no_headroom", SCAN_HEADROOM_MSG)]
)
def test_scan_messages_name_images(qapp, model, monkeypatch, reason, text):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller._on_object_probe_failed("scan", 1, reason)
        assert log.status[-1] == text
        assert "影像" in text and "表格" not in text
        assert log.dropped == [True]
    finally:
        dispose_pdf_view(view, controller, model)


NEUTRAL_SCAN_MSG = "此頁的物件分析未完成（第 1 頁）"
TABLES_HEADROOM_MSG = "目前可用記憶體不足，暫時無法分析此頁的表格，請稍後再操作一次"


@pytest.mark.parametrize(
    "status,text",
    [
        ("resource_limited", SCAN_LIMITED_MSG),
        ("analysis_failed", NEUTRAL_SCAN_MSG),
        ("containment_failed", NEUTRAL_SCAN_MSG),
        ("crashed", NEUTRAL_SCAN_MSG),  # also the ledger refusal: a runner failure twice
    ],
)
@pytest.mark.parametrize("kind", ["native_image", "image"])
def test_refusal_on_a_failed_page_claims_no_cause_the_status_does_not_record(qapp, model, monkeypatch, status, text, kind):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, IMAGE_POINT)
        if status == "crashed":
            stub.fail(stub.order[0])
            stub.fail(stub.order[1])
        else:
            stub.complete(stub.order[0], {"v": 2, "status": status})
        assert model.image_scan_failed(1)
        assert controller.object_op_ready([1], [kind]) is False
        assert log.status[-1] == text
    finally:
        dispose_pdf_view(view, controller, model)


class _EarlyRunner(StubRunner):
    """Answers a submit inside ``submit`` as the real runner does (no headroom; a refused start)."""

    def __init__(self, kinds: tuple[str, ...], mode: str):
        super().__init__()
        self.kinds = kinds
        self.mode = mode

    def submit(self, owner, kind, payloads):
        job = super().submit(owner, kind, payloads)
        if kind in self.kinds:
            if self.mode == "headroom":
                self.complete(job, {"v": 2, "status": "no_headroom"})
            else:  # the ledger refusal: failed inside submit
                self.jobs.pop(job, None)
                self.running = None
                self.failed.emit(job)
        return job


def _pending_texts(kind: str) -> frozenset[str]:
    from controller.pdf_controller import _PENDING_TEXTS

    return _PENDING_TEXTS[kind]


@pytest.mark.parametrize("mode", ["headroom", "ledger"])
@pytest.mark.parametrize("gesture", ["click", "move"])
def test_no_scan_pending_text_stays_when_the_request_answered_synchronously(qapp, model, monkeypatch, mode, gesture):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        early = _EarlyRunner(("scan",), mode)
        controller._object_probe._runner = early
        if gesture == "click":
            # P2: no job of this click is left, so the view must not store a pending click
            assert controller.lookup_object_at_point(1, IMAGE_POINT) is not OBJECT_LOOKUP_PENDING
            assert log.dropped == [True]
        else:
            rect = fitz.Rect(150, 20, 250, 90)
            controller.move_object(MoveObjectRequest(_native_id(), "native_image", 1, 1, rect))
        assert not controller._object_probe.has_pending("scan")
        assert controller._object_status_message not in _pending_texts("scan")
        assert log.status[-1] == (SCAN_HEADROOM_MSG if mode == "headroom" else NEUTRAL_SCAN_MSG)
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("mode", ["headroom", "ledger"])
def test_no_tables_pending_text_stays_when_the_request_answered_synchronously(qapp, model, monkeypatch, mode):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller._object_probe._runner = _EarlyRunner(("tables",), mode)
        model.get_object_info_at_point(1, IMAGE_POINT)  # in-process scan: the page is warm for images
        assert controller.lookup_object_at_point(1, fitz.Point(250, 200)) is not OBJECT_LOOKUP_PENDING
        assert not controller._object_probe.has_pending("tables")
        assert controller._object_status_message not in _pending_texts("tables")
        assert log.status[-1] == (TABLES_HEADROOM_MSG if mode == "headroom" else NEUTRAL_SCAN_MSG)
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("headroom", [False, True])
def test_the_ready_text_never_overwrites_what_the_resolved_click_set(qapp, model, monkeypatch, headroom):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        point = fitz.Point(250, 200)  # not on the image: the resolved click asks for tables
        early = _EarlyRunner(("tables",), "headroom")
        early.kinds = ("tables",) if headroom else ()
        controller._object_probe._runner = early
        view.resolve_pending_object_click = lambda page: controller.lookup_object_at_point(page, point)
        assert controller.lookup_object_at_point(1, point) is OBJECT_LOOKUP_PENDING
        early.complete(early.order[0], _scan_answer(model))
        assert early.jobs.get(early.order[0]) is None
        assert controller._object_status_message != READY_MSG
        if headroom:
            assert controller._object_status_message == TABLES_HEADROOM_MSG
        else:
            assert controller._object_status_message == "正在背景分析此頁的表格，完成後會自動選取…"
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("mode", ["headroom", "ledger"])
def test_view_stores_no_pending_click_after_a_synchronous_scan_refusal(qapp, model, monkeypatch, mode):
    """P2: the refusal callback ran inside the request, so the click has no job; the real view's
    press logic stores a pending click only for an OBJECT_LOOKUP_PENDING answer."""
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller._object_probe._runner = _EarlyRunner(("scan",), mode)
        manager = view._ensure_object_selection_manager()
        info = manager._lookup_object(1, IMAGE_POINT)
        assert info is not OBJECT_LOOKUP_PENDING
        assert manager._pending_object_click is None
        assert log.status[-1] == (SCAN_HEADROOM_MSG if mode == "headroom" else NEUTRAL_SCAN_MSG)
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_click_whose_job_is_running_still_answers_pending(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        assert controller.lookup_object_at_point(1, IMAGE_POINT) is OBJECT_LOOKUP_PENDING
        assert controller._object_probe.has_pending("scan")
        assert log.dropped == []
    finally:
        dispose_pdf_view(view, controller, model)


@needs_child
def test_over_budget_short_stream_page_is_refused_once_and_not_rescanned(tmp_path, monkeypatch):
    """P3: discovery used to ignore ``admit_set() == False``: nothing was cached or recorded, so
    every click re-scanned every short stream (D12: the set is refused, recorded resource_limited)."""
    m = _open(tmp_path, long_flags=(False, False))
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)  # two streams, one record each
        scanned: list[int] = []
        real_scan = pdf_content_ops.scan_stream
        monkeypatch.setattr(pdf_content_ops, "scan_stream", lambda s: scanned.append(len(s)) or real_scan(s))
        m.get_object_info_at_point(1, IMAGE_POINT)
        assert m.image_scan_failure_reason(1) == content_scan.INLINE_REFUSED
        assert content_scan.cached_scan(content_key(_page_streams(m)[0])) is None  # nothing was admitted
        first = len(scanned)
        assert first > 0
        assert m.get_object_info_at_point(1, IMAGE_POINT) is None  # the page's images are unavailable
        assert len(scanned) == first  # the second click scans nothing
    finally:
        m.close()
        clear_scan_cache()


@needs_child
def test_over_budget_short_stream_page_refuses_image_ops_but_keeps_other_objects(qapp, tmp_path, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    m = _open(tmp_path, long_flags=(False, False))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
        controller.lookup_object_at_point(1, IMAGE_POINT)
        assert controller.object_op_ready([1], ["native_image"]) is False
        assert log.status[-1] == SCAN_LIMITED_MSG
        assert controller.object_op_ready([1], ["rect"]) is True
        assert not controller._object_probe.has_pending("scan")  # a tables job for the click is fine
    finally:
        dispose_pdf_view(view, controller, m)


@needs_child
def test_child_failure_hides_only_the_long_stream_images(tmp_path):
    """F2: a child failure of the page's scan set skips its long streams; a short-stream image on
    the same page stays selectable.  Only an in-process refusal (P3) hides what it refused."""
    m = _open(tmp_path, long_flags=(True, False))  # stream 1 long (image 1), stream 2 short (image 2)
    try:
        runner = StubRunner()
        coord = _coordinator(m, runner)
        coord.request_image_scan(1)
        runner.complete(runner.order[0], {"v": 2, "status": "resource_limited"})
        assert m.image_scan_failure_reason(1) == "resource_limited"
        assert m.get_object_info_at_point(1, IMAGE_POINT) is None
        hit = m.get_object_info_at_point(1, IMAGE2_POINT)
        assert hit is not None and hit.object_kind == "native_image"
    finally:
        m.close()
        clear_scan_cache()


@needs_child
def test_the_first_click_on_a_refused_page_says_why(qapp, tmp_path, monkeypatch):
    """F3: the in-process refusal is announced at the click, not only when an edit is refused."""
    from test_scripts.qt_teardown import dispose_pdf_view

    m = _open(tmp_path, long_flags=(False, False))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
        controller.lookup_object_at_point(1, IMAGE_POINT)
        assert log.status[-1] == SCAN_LIMITED_MSG
        controller.lookup_object_at_point(1, IMAGE_POINT)  # and on every later click of the page
        assert log.status[-1] == SCAN_LIMITED_MSG
    finally:
        dispose_pdf_view(view, controller, m)


def test_off_windows_an_over_budget_page_keeps_its_images_and_edits(qapp, tmp_path, monkeypatch, unsupported):
    """F4: without the contained child nothing is recorded, hidden or refused (ruling 2026-11-20:
    off Windows the edits are not refused), and a click walks no extra scan set."""
    from test_scripts.qt_teardown import dispose_pdf_view

    m = _open(tmp_path, long_flags=(True, False))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
        walks: list[int] = []
        real_walk = pdf_content_ops._scan_set_walk
        monkeypatch.setattr(pdf_content_ops, "_scan_set_walk", lambda *a, **k: walks.append(1) or real_walk(*a, **k))
        info = controller.lookup_object_at_point(1, IMAGE_POINT)
        assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "native_image"
        assert controller.object_op_ready([1], ["native_image"]) is True
        assert m.image_scan_failure_reason(1) is None
        assert SCAN_LIMITED_MSG not in log.status
        assert walks == []
    finally:
        dispose_pdf_view(view, controller, m)


def _shared_image_pdf(path) -> str:
    """One image drawn twice: stream 1 (long) places it with a ``cm``; stream 2 (short) draws it
    with no ``cm`` of its own, so its bbox is MuPDF's n-th placement of the xref."""
    with fitz.open() as doc:
        page = doc.new_page(width=320, height=240)
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png())
        name = str(page.get_images(full=True)[0][7])
        xrefs = [int(x) for x in page.get_contents()]
        doc.update_stream(xrefs[0], b"0.2 w 10 10 m 12 14 l S\n" * 6000 + f"q 100 0 0 70 20 150 cm /{name} Do Q\n".encode("ascii"))
        second = doc.get_new_xref()
        doc.update_object(second, "<< >>")
        doc.update_stream(second, f"q /{name} Do Q\n".encode("ascii"))
        doc.xref_set_key(page.xref, "Contents", f"[{xrefs[0]} 0 R {second} 0 R]")
        doc.save(path)
    return str(path)


def test_a_skipped_stream_does_not_shift_the_placements_of_a_shared_image(tmp_path):
    """F2 (Astra r2 #1): skipping a failed long stream must not hand its MuPDF placement to a
    short stream that draws the same image xref without a cm of its own."""
    clear_scan_cache()
    path = _shared_image_pdf(tmp_path / "shared.pdf")
    with fitz.open(path) as doc:
        page = doc[0]
        long_xref = int(page.get_contents()[0])
        failed_box = fitz.Rect(20, 20, 120, 90)
        skip = frozenset({content_key(doc.xref_stream(long_xref))})
        found = pdf_content_ops.discover_native_image_invocations(doc, 1, skip)
    assert all(abs(inv.bbox.x0 - failed_box.x0) > 1 or abs(inv.bbox.y0 - failed_box.y0) > 1 for inv in found)
    clear_scan_cache()


def test_a_skipped_form_does_not_shift_the_placements_of_a_page_level_draw(tmp_path):
    """Astra r3 #1 (the class: MuPDF's placement list counts draws the walk skipped): a failed long
    Form that draws an image must not hand its placement to the page stream's no-cm draw of it,
    while a cm-bearing draw of the page stays reported."""
    clear_scan_cache()
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=200)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), False)
        pix.clear_with(100)
        image = page.insert_image(fitz.Rect(10, 10, 30, 30), pixmap=pix)
        name = str(page.get_images()[0][7])
        form = doc.get_new_xref()
        doc.update_object(form, f"<< /Type /XObject /Subtype /Form /BBox [0 0 200 200] /Resources << /XObject << /Inner {image} 0 R >> >> >>")
        raw = b"0 w\n" * (INLINE_SCAN_LIMIT_BYTES // 4 + 10) + b"q 20 0 0 20 10 150 cm /Inner Do Q"
        doc.update_stream(form, raw)
        resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
        doc.xref_set_key(resources, "XObject/Fm", f"{form} 0 R")
        doc.update_stream(
            page.get_contents()[0], f"/Fm Do q /{name} Do Q q 20 0 0 20 100 100 cm /{name} Do Q".encode("ascii")
        )
        found = pdf_content_ops.discover_native_image_invocations(doc, 1, frozenset({content_key(raw)}))
    boxes = [tuple(round(v) for v in inv.bbox) for inv in found]
    assert (10, 30, 30, 50) not in boxes  # the skipped form's placement
    assert (100, 80, 120, 100) in boxes  # the page's own cm draw stays
    clear_scan_cache()


@needs_child
def test_a_child_failure_does_not_overwrite_an_inline_refusal(tmp_path):
    """Astra r2 #4: a pending child job and a blocking lookup can share a frame; the child's later
    failure must not replace the refusal, or the next click would expose the refused set's images."""
    m = _open(tmp_path, long_flags=(True, False))
    try:
        runner = StubRunner()
        coord = _coordinator(m, runner)
        coord.request_image_scan(1)
        m.mark_image_scan_failed(1, m.image_scan_set_key(1), content_scan.INLINE_REFUSED)
        runner.complete(runner.order[0], {"v": 2, "status": "resource_limited"})
        assert m.image_scan_failure_reason(1) == content_scan.INLINE_REFUSED
        assert m.get_object_info_at_point(1, IMAGE2_POINT) is None
    finally:
        m.close()
        clear_scan_cache()


@needs_child
def test_the_limit_text_ends_with_the_click_that_no_longer_needs_it(qapp, tmp_path, monkeypatch):
    """Astra r2 #3: a later click that the refusal does not touch clears the limit text, and
    another page's table answer never clears a text that is not the tables' own."""
    from test_scripts.qt_teardown import dispose_pdf_view

    m = _open(tmp_path, long_flags=(False, False))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
        controller.lookup_object_at_point(1, IMAGE_POINT)
        assert log.status[-1] == SCAN_LIMITED_MSG
        controller._on_object_tables_ready(2)  # another page's table answer
        assert log.status[-1] == SCAN_LIMITED_MSG
        content_scan._failed_sets.clear()
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 200_000)
        controller.lookup_object_at_point(1, IMAGE_POINT)  # no longer refused: the stale text goes
        assert log.status[-1] is None
    finally:
        dispose_pdf_view(view, controller, m)


@needs_child
def test_the_limit_text_never_replaces_a_synchronous_failure_text(qapp, tmp_path, monkeypatch):
    """Astra r3 #3: a table request that failed inside the click set its own text; keep it."""
    from test_scripts.qt_teardown import dispose_pdf_view

    m = _open(tmp_path, long_flags=(False, False))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
        controller.lookup_object_at_point(1, IMAGE_POINT)  # recorded INLINE_REFUSED
        monkeypatch.setattr(
            controller, "_lookup_object_at_point", lambda *a: controller._set_object_status(TABLES_HEADROOM_MSG)
        )
        assert controller.lookup_object_at_point(1, IMAGE_POINT) is None
        assert log.status[-1] == TABLES_HEADROOM_MSG
        controller._set_object_status(TABLES_HEADROOM_MSG)  # an earlier click's failure is not this lookup's
        monkeypatch.undo()
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
        controller.lookup_object_at_point(1, IMAGE_POINT)
        assert log.status[-1] == SCAN_LIMITED_MSG
    finally:
        dispose_pdf_view(view, controller, m)


def test_tables_ready_keeps_the_pending_text_of_another_pages_job(qapp, tmp_path, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view
    from controller import pdf_controller

    m = _open(tmp_path, long_flags=(False, False))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        controller._set_object_status(pdf_controller._TABLES_LOOKUP_TEXT)
        controller._object_probe._jobs = {"k": SimpleNamespace(kind="tables", page_num=2)}
        controller._on_object_tables_ready(1)
        assert log.status[-1] == pdf_controller._TABLES_LOOKUP_TEXT
        controller._object_probe._jobs = {}
        controller._on_object_tables_ready(2)
        assert log.status[-1] is None
    finally:
        controller._object_probe._jobs = {}
        dispose_pdf_view(view, controller, m)


@needs_child
def test_the_click_on_an_app_image_of_a_refused_page_says_why(qapp, tmp_path, monkeypatch):
    """Astra r2 #2: the app-inserted image stays selectable, but its edit will be refused: say so at the click."""
    from test_scripts.qt_teardown import dispose_pdf_view

    m = _open(tmp_path, long_flags=(False, False))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        rect = fitz.Rect(10, 150, 60, 200)
        controller.add_image_object(InsertImageObjectRequest(1, rect, _png()))
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)
        controller.lookup_object_at_point(1, IMAGE_POINT)  # the refusal is recorded
        log.status.clear()
        info = controller.lookup_object_at_point(1, fitz.Point(30, 175))
        assert info is not None and info.object_kind == "image"
        assert log.status[-1] == SCAN_LIMITED_MSG
    finally:
        dispose_pdf_view(view, controller, m)


def _shared_stream_pdf(path) -> str:
    """Two pages whose /Contents and /Resources are one shared object: one long stream, two pages."""
    with fitz.open() as doc:
        page = doc.new_page(width=320, height=240)
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png())
        name = str(page.get_images(full=True)[0][7])
        xrefs = [int(x) for x in page.get_contents()]
        doc.update_stream(xrefs[0], b"0.2 w 10 10 m 12 14 l S\n" * 6000 + f"q 100 0 0 70 20 150 cm /{name} Do Q\n".encode("ascii"))
        for extra in xrefs[1:]:
            doc.update_stream(extra, b" ")
        first_xref = page.xref
        second = doc.new_page(width=320, height=240)
        doc.xref_set_key(second.xref, "Contents", doc.xref_get_key(first_xref, "Contents")[1])
        doc.xref_set_key(second.xref, "Resources", doc.xref_get_key(first_xref, "Resources")[1])
        doc.save(path)
    return str(path)


def test_two_pages_sharing_a_long_stream_both_get_their_answer(tmp_path):
    clear_scan_cache()
    m = PDFModel()
    try:
        m.open_pdf(_shared_stream_pdf(tmp_path / "shared.pdf"))
        assert len(m.image_scan_jobs(1)) == 1 and len(m.image_scan_jobs(2)) == 1
        runner = StubRunner()
        coord = _coordinator(m, runner)
        ready = []
        coord.image_scan_ready.connect(ready.append)
        coord.request_image_scan(1)
        coord.request_image_scan(2)
        answer = {"v": 2, "status": "complete", "scans": [content_scan.to_json(scan_stream(_stream(m)))]}
        for job in list(runner.order):
            runner.complete(job, answer)
        assert sorted(ready) == [1, 2]
        assert not coord.has_pending("scan")
    finally:
        m.close()
        clear_scan_cache()


# --------------------------------------------------------------------------- owner decision D9: the splice writer

SPLICE_STORAGES = ["unfiltered", "flate_predictor", "indirect_keys"]
SPLICE_VERBS = ["move", "resize", "rotate", "delete"]
PREDICTOR_COLUMNS = 16
OBJECT_ID = "native_image:1:0"


def _forbidden_compressor(*args, **kwargs):
    raise AssertionError("PyMuPDF's default compressor (FZ_DEFLATE_BEST) was reached")


def _marked_png() -> bytes:
    """An 8 x 8 image with two odd corners, so a quarter turn changes the rendered page."""
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    pix.clear_with(200)
    pix.set_pixel(0, 0, (255, 0, 0))
    pix.set_pixel(7, 0, (0, 0, 255))
    return pix.tobytes("png")


def _storage_pdf(path, storage: str) -> str:
    """One image page whose content stream is stored ``storage``-ly (D9 fixtures).

    ``flate_predictor``: Flate with a PNG predictor, so a stale ``/DecodeParms`` left on the new
    bytes would corrupt every row.  ``indirect_keys``: Flate plus an indirect-valued key and a
    string key whose escape PyMuPDF's ``xref_set_key`` would re-print decoded."""
    with fitz.open() as doc:
        page = doc.new_page(width=320, height=240)
        page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_marked_png())
        name = str(page.get_images(full=True)[0][7])
        xrefs = [int(x) for x in page.get_contents()]
        for extra in xrefs[1:]:
            doc.update_stream(extra, b" ")
        content = f"q 100 0 0 70 20 150 cm /{name} Do Q\n".encode("ascii")
        xref = xrefs[0]
        if storage == "unfiltered":
            doc.update_stream(xref, content, compress=0)
        elif storage == "flate_predictor":
            padded = content + b" " * (-len(content) % PREDICTOR_COLUMNS)
            rows = b"".join(
                b"\x00" + padded[i : i + PREDICTOR_COLUMNS] for i in range(0, len(padded), PREDICTOR_COLUMNS)
            )
            doc.update_stream(xref, zlib.compress(rows, 9), compress=0)
            xref_set_key_exact(doc, xref, "Filter", "/FlateDecode")
            xref_set_key_exact(doc, xref, "DecodeParms", f"<< /Predictor 12 /Columns {PREDICTOR_COLUMNS} >>")
        else:
            doc.update_stream(xref, content)
            side = doc.get_new_xref()
            doc.update_object(side, "<< /Marker (kept) >>")
            xref_set_key_exact(doc, xref, "Extra", f"{side} 0 R")
            xref_set_key_exact(doc, xref, "Meta", r"(a\(b)")
        doc.save(path)
    return str(path)


@pytest.fixture
def storage_model(tmp_path, request):
    clear_scan_cache()
    m = PDFModel()
    m.open_pdf(_storage_pdf(tmp_path / "storage.pdf", request.param))
    yield m
    m.close()
    clear_scan_cache()


def _run_verb(model: PDFModel, verb: str) -> bool:
    if verb == "move":
        return model.move_object(MoveObjectRequest(OBJECT_ID, "native_image", 1, 1, fitz.Rect(160, 40, 260, 110)))
    if verb == "resize":
        return model.resize_object(ResizeObjectRequest(OBJECT_ID, "native_image", 1, fitz.Rect(30, 40, 150, 110)))
    if verb == "rotate":
        return model.rotate_object(RotateObjectRequest(OBJECT_ID, "native_image", 1, 90))
    return model.delete_object(DeleteObjectRequest(OBJECT_ID, "native_image", 1))


def _render(doc: fitz.Document) -> bytes:
    """Page 1 drawn at 36 dpi, as raw samples."""
    return bytes(doc[0].get_pixmap(dpi=36).samples)


def _storage_state(doc: fitz.Document, xref: int) -> dict:
    """Everything the splice writer may touch, read back from the live document."""
    return {
        "decoded": doc.xref_stream(xref),
        "raw": doc.xref_stream_raw(xref),
        "filter": doc.xref_get_key(xref, "Filter"),
        "parms": doc.xref_get_key(xref, "DecodeParms"),
    }


def _unrelated_keys(doc: fitz.Document, xref: int) -> dict[str, tuple[str, str]]:
    """The stream dictionary's keys the writer does not own, as ``xref_get_key`` reads them."""
    return {
        key: doc.xref_get_key(xref, key)
        for key in doc.xref_get_keys(xref)
        if key not in ("Length", "Filter", "DecodeParms")
    }


def _assert_extra_keys_intact(doc: fitz.Document, xref: int, unrelated: dict[str, tuple[str, str]]) -> None:
    """The keys ``indirect_keys`` adds are still there byte for byte (no decoded re-print)."""
    if "Extra" in unrelated:
        text = xref_object_exact(doc, xref)
        assert r"/Meta (a\(b)" in text
        assert f"/Extra {unrelated['Extra'][1]}" in text


@pytest.mark.parametrize("storage_model", SPLICE_STORAGES, indirect=True)
@pytest.mark.parametrize("verb", SPLICE_VERBS)
def test_splice_uses_bounded_compression_and_preserves_decode(storage_model, tmp_path, monkeypatch, verb):
    model = storage_model
    doc = model.doc
    xref = int(doc[0].get_contents()[0])
    before = doc.xref_stream(xref)
    record = scan_stream(before).dos[0]
    unrelated_before = _unrelated_keys(doc, xref)
    picture_before = _render(doc)
    # The same verb through a raw, unencoded write: the decoded splice and the picture must be
    # identical, only the stored encoding differs.  (Not the old default write: its compressed branch
    # keeps a stale /DecodeParms, so on the predictor page it decoded to garbage.)
    twin = PDFModel()
    twin.open_pdf(str(tmp_path / "storage.pdf"))
    try:
        with monkeypatch.context() as old:
            old.setattr(
                pdf_object_ops,
                "_write_flate_stream",
                lambda target, target_xref, data, model=None: target.update_stream(target_xref, data, compress=0),
            )
            assert _run_verb(twin, verb) is True
        twin_decoded, twin_picture = twin.doc.xref_stream(xref), _render(twin.doc)
    finally:
        twin.close()
    calls: list[tuple[int, bool]] = []
    real_update = fitz.Document.update_stream

    def spy(self, xref=0, stream=None, new=1, compress=1):
        calls.append((int(xref), bool(compress)))
        return real_update(self, xref, stream, new, compress)

    monkeypatch.setattr(fitz.Document, "update_stream", spy)
    monkeypatch.setattr(pymupdf, "JM_compress_buffer", _forbidden_compressor)
    assert _run_verb(model, verb) is True
    doc = model.doc
    after, raw = doc.xref_stream(xref), doc.xref_stream_raw(xref)
    assert after != before
    # Only the span the verb owns changed (H17): the cm operands, or the whole q..Q block.
    start, end = record.q_span if verb == "delete" else record.cm_span
    assert after.startswith(before[:start]) and after.endswith(before[end:])
    # One write of already-encoded bytes (never a second compression pass), at zlib level 1.
    assert [flag for call_xref, flag in calls if call_xref == xref] == [False]
    assert raw == zlib.compress(after, 1)
    assert doc.xref_get_key(xref, "Filter") == ("name", "/FlateDecode")
    assert doc.xref_get_key(xref, "DecodeParms")[0] == "null"
    assert "DecodeParms" not in xref_object_exact(doc, xref)  # absent, not a literal null
    assert doc.xref_get_key(xref, "Length") == ("int", str(len(raw)))
    assert _unrelated_keys(doc, xref) == unrelated_before
    _assert_extra_keys_intact(doc, xref, unrelated_before)
    assert int(doc[0].get_contents()[0]) == xref
    assert after == twin_decoded
    picture = _render(doc)
    assert picture == twin_picture
    assert picture != picture_before  # the check can tell an edited page from an untouched one
    reopened = fitz.open(stream=model.serialize_document_bytes(doc), filetype="pdf")
    try:
        assert reopened.xref_stream(xref) == after
    finally:
        reopened.close()
    # The user's save path: Save As, reopen, and the page draws the same as before the save.  (Not
    # byte equality: a save normalises the content stream, e.g. trailing whitespace.)
    model.save_as(str(tmp_path / "saved.pdf"))
    doc = model.doc  # Save As reopens the document: the old handle is closed
    with fitz.open(tmp_path / "saved.pdf") as saved:
        assert _render(saved) == picture
    found = pdf_content_ops.discover_native_image_invocations(doc, 1)
    if verb == "delete":
        assert found == []
    elif verb == "rotate":
        assert abs(found[0].rotation - 90.0) < 0.5
    else:
        want = fitz.Rect(160, 40, 260, 110) if verb == "move" else fitz.Rect(30, 40, 150, 110)
        assert all(abs(a - b) < 0.5 for a, b in zip(found[0].bbox, want))


@pytest.mark.parametrize("storage_model", SPLICE_STORAGES, indirect=True)
@pytest.mark.parametrize("verb", SPLICE_VERBS)
def test_failure_between_bytes_and_filter_leaves_the_stream_as_it_was(storage_model, monkeypatch, verb):
    model = storage_model
    xref = int(model.doc[0].get_contents()[0])
    before = _storage_state(model.doc, xref)
    unrelated_before = _unrelated_keys(model.doc, xref)
    edit_count = model.edit_count
    armed = _fail_the_next_filter_write(monkeypatch)
    with pytest.raises(RuntimeError, match="injected"):
        _run_verb(model, verb)
    assert armed == [False]  # the failure point was reached
    doc = model.doc  # a delete's rollback reopens the document: read the live handle
    assert _storage_state(doc, xref) == before
    assert doc.xref_get_key(xref, "Length") == ("int", str(len(before["raw"])))
    assert _unrelated_keys(doc, xref) == unrelated_before
    _assert_extra_keys_intact(doc, xref, unrelated_before)
    assert model.edit_count == edit_count


def _fail_the_next_filter_write(monkeypatch) -> list[bool]:
    """Make the writer's ``/Filter`` write raise once (after its bytes are written); the returned
    one-item list turns ``False`` when it has."""
    real = pdf_object_ops.xref_set_key_exact
    armed = [True]

    def failing(doc, target, key, value):
        if armed[0] and key == "Filter":
            armed[0] = False
            raise RuntimeError("injected between the bytes and the Filter")
        return real(doc, target, key, value)

    monkeypatch.setattr(pdf_object_ops, "xref_set_key_exact", failing)
    return armed


def _open_encrypted(tmp_path) -> PDFModel:
    """The ``flate_predictor`` page saved AES-256 and opened with its user password."""
    clear_scan_cache()
    plain = _storage_pdf(tmp_path / "plain.pdf", "flate_predictor")
    encrypted = str(tmp_path / "encrypted.pdf")
    with fitz.open(plain) as source:
        source.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="user-pw", owner_pw="owner-pw")
    model = PDFModel()
    model.open_pdf(encrypted, password="user-pw")
    return model


@pytest.mark.parametrize("verb", SPLICE_VERBS)
def test_failure_between_bytes_and_filter_on_an_encrypted_document_restores_the_stream(tmp_path, monkeypatch, verb):
    model = _open_encrypted(tmp_path)
    try:
        xref = int(model.doc[0].get_contents()[0])
        before = _storage_state(model.doc, xref)
        armed = _fail_the_next_filter_write(monkeypatch)
        with pytest.raises(RuntimeError, match="injected"):
            _run_verb(model, verb)
        assert armed == [False]
        assert _storage_state(model.doc, xref) == before  # raw is read decrypted and written back as such
        with fitz.open(stream=model.serialize_document_bytes(model.doc), filetype="pdf") as reopened:
            assert reopened.authenticate("user-pw")
            assert reopened.xref_stream(xref) == before["decoded"]
    finally:
        model.close()
        clear_scan_cache()


@pytest.mark.parametrize("verb", SPLICE_VERBS)
def test_splice_on_an_encrypted_document_saves_and_reopens_with_the_same_decode(tmp_path, verb):
    model = _open_encrypted(tmp_path)
    try:
        xref = int(model.doc[0].get_contents()[0])
        before = model.doc.xref_stream(xref)
        assert _run_verb(model, verb) is True
        after = model.doc.xref_stream(xref)
        assert after != before
        saved = model.serialize_document_bytes(model.doc)
        with fitz.open(stream=saved, filetype="pdf") as reopened:
            assert reopened.is_encrypted and reopened.authenticate("user-pw")
            assert reopened.xref_stream(xref) == after
            assert reopened.xref_get_key(xref, "Filter") == ("name", "/FlateDecode")
    finally:
        model.close()
        clear_scan_cache()


def _text_stream_doc(stored: bytes | None = None) -> tuple[fitz.Document, int]:
    doc = fitz.open()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<< >>")
    doc.update_stream(xref, stored if stored is not None else b"q 1 0 0 1 0 0 cm Q\n" * 20, compress=0)
    return doc, xref


def test_writer_round_trips_an_empty_stream():
    doc, xref = _text_stream_doc()
    try:
        pdf_object_ops._write_flate_stream(doc, xref, b"")
        assert (doc.xref_stream(xref) or b"") == b""
        assert zlib.decompress(doc.xref_stream_raw(xref)) == b""
        assert doc.xref_get_key(xref, "Filter") == ("name", "/FlateDecode")
    finally:
        doc.close()


def test_writer_refuses_a_non_bytes_payload_before_writing_anything():
    doc, xref = _text_stream_doc()
    try:
        before = _storage_state(doc, xref)
        with pytest.raises(TypeError):
            pdf_object_ops._write_flate_stream(doc, xref, "not bytes")
        assert _storage_state(doc, xref) == before
    finally:
        doc.close()


@pytest.mark.parametrize("xref", [0, 9999])
def test_writer_refuses_a_bad_xref_without_touching_the_document(xref):
    doc, good = _text_stream_doc()
    try:
        before = _storage_state(doc, good)
        with pytest.raises(ValueError):
            pdf_object_ops._write_flate_stream(doc, xref, b"q Q\n")
        assert _storage_state(doc, good) == before
    finally:
        doc.close()


def test_writer_restores_the_previous_storage_when_the_write_itself_raises(monkeypatch):
    doc, xref = _text_stream_doc()
    try:
        before = _storage_state(doc, xref)
        real = fitz.Document.update_stream
        armed = [True]

        def write_then_raise(self, xref=0, stream=None, new=1, compress=1):
            real(self, xref, stream, new, compress)
            if armed[0]:
                armed[0] = False
                raise RuntimeError("raised after the write")  # update_stream can write and then raise

        monkeypatch.setattr(fitz.Document, "update_stream", write_then_raise)
        with pytest.raises(RuntimeError, match="after the write"):
            pdf_object_ops._write_flate_stream(doc, xref, b"q Q\n")
        assert _storage_state(doc, xref) == before
    finally:
        doc.close()


# --------------------------------------------------------------------------- owner decision D10: lazy placements


def _eager_discover(doc: fitz.Document, page_num: int) -> list:
    """The discovery as it was before D10: ``get_image_rects`` for every image up front.

    A verbatim copy of the old bodies of ``discover_native_image_invocations`` and
    ``_discover_form_nested_invocations`` on the module's own helpers, so only the
    placement loading differs; the scan cache admission is left out."""
    ops = pdf_content_ops
    page = doc[page_num - 1]
    if not page.get_images(full=True):
        return []
    members: dict = {}
    user_to_page = ops.page_user_space_matrix(page)
    image_name_to_xref = {str(image[7]): int(image[0]) for image in page.get_images(full=True)}
    placements_by_xref: dict = {}
    placement_offsets: dict[int, int] = {}
    for xref in set(image_name_to_xref.values()):
        placements = list(page.get_image_rects(xref, transform=True))
        placements_by_xref[xref] = [(fitz.Rect(rect), matrix) for rect, matrix in placements]
        placement_offsets[xref] = 0
    invocations: list = []
    occurrence_index = 0
    for stream_xref in [int(xref) for xref in page.get_contents() if int(xref) > 0]:
        scan = ops._scan_for_discovery(doc, stream_xref, members)
        if scan is None:
            continue
        for record in scan.dos:
            image_name = record.name
            if image_name not in image_name_to_xref:
                continue
            xref = image_name_to_xref[image_name]
            placements = placements_by_xref.get(xref, [])
            placement_index = placement_offsets.get(xref, 0)
            cm_values = record.cm_values
            bbox = None
            rotation = 0.0
            if cm_values is not None:
                if user_to_page is not None:
                    bbox = ops._bbox_from_stream_cm(cm_values, user_to_page)
                elif placement_index < len(placements):
                    bbox = fitz.Rect(placements[placement_index][0])
                else:
                    continue
                rotation = ops._rotation_from_cm(cm_values[0], cm_values[1], cm_values[2], cm_values[3])
                if placement_index < len(placements):
                    placement_offsets[xref] = placement_index + 1
            elif placement_index < len(placements):
                bbox, transform = placements[placement_index]
                placement_offsets[xref] = placement_index + 1
                rotation = ops._rotation_from_cm(transform.a, transform.b, transform.c, transform.d)
            else:
                continue
            invocations.append(
                ops.NativeImageInvocation(
                    page_num=page_num,
                    occurrence_index=occurrence_index,
                    stream_xref=stream_xref,
                    xobject_name=image_name,
                    xref=xref,
                    bbox=fitz.Rect(bbox),
                    rotation=rotation,
                    cm_operator_index=record.cm_operator_index,
                    do_operator_index=record.do_operator_index,
                    q_operator_index=record.q_operator_index,
                    q_end_operator_index=record.q_end_operator_index,
                    q_image_invocation_count=record.q_do_count,
                    resource_owner_xref=int(page.xref),
                    is_form_nested=False,
                    do_span=record.do_span,
                    cm_span=record.cm_span,
                    q_span=record.q_span,
                )
            )
            occurrence_index += 1
    images_by_referencer: dict[int, dict[str, int]] = {}
    for row in page.get_images(full=True):
        images_by_referencer.setdefault(int(row[9]), {})[str(row[7])] = int(row[0])
    processed_forms: set[int] = set()
    for xobj in page.get_xobjects():
        form_xref = int(xobj[0])
        if form_xref in processed_forms:
            continue
        processed_forms.add(form_xref)
        subtype = doc.xref_get_key(form_xref, "Subtype")
        if not (isinstance(subtype, tuple) and subtype[1] == "/Form"):
            continue
        form_images = images_by_referencer.get(form_xref)
        if not form_images:
            continue
        scan = ops._scan_for_discovery(doc, form_xref, members)
        if scan is None:
            continue
        for record in scan.dos:
            image_name = record.name
            if image_name not in form_images:
                continue
            xref = form_images[image_name]
            placements = placements_by_xref.get(xref, [])
            placement_index = placement_offsets.get(xref, 0)
            if placement_index >= len(placements):
                continue
            bbox, transform = placements[placement_index]
            placement_offsets[xref] = placement_index + 1
            rotation = ops._rotation_from_cm(transform.a, transform.b, transform.c, transform.d)
            invocations.append(
                ops.NativeImageInvocation(
                    page_num=page_num,
                    occurrence_index=occurrence_index,
                    stream_xref=form_xref,
                    xobject_name=image_name,
                    xref=xref,
                    bbox=fitz.Rect(bbox),
                    rotation=rotation,
                    cm_operator_index=record.cm_operator_index,
                    do_operator_index=record.do_operator_index,
                    q_operator_index=record.q_operator_index,
                    q_end_operator_index=record.q_end_operator_index,
                    q_image_invocation_count=record.q_do_count,
                    resource_owner_xref=form_xref,
                    is_form_nested=True,
                    do_span=record.do_span,
                    cm_span=record.cm_span,
                    q_span=record.q_span,
                )
            )
            occurrence_index += 1
    return invocations


@pytest.fixture(scope="module")
def fast_path_pdfs(tmp_path_factory):
    """The two A5 fixtures whose invocations are all direct ``cm`` records in a proven page frame."""
    from test_scripts.test_gui_stall import build_image_page
    from test_scripts.test_native_image_ops_stall import _build as build_heavy_page

    folder = tmp_path_factory.mktemp("d10")
    build_image_page(folder / "images.pdf")
    build_heavy_page(folder / "heavy.pdf")
    return {"images": (folder / "images.pdf", 3), "heavy": (folder / "heavy.pdf", 1)}


@pytest.mark.parametrize("fixture", ["images", "heavy"])
def test_direct_image_discovery_never_hashes_pixmaps(fast_path_pdfs, monkeypatch, fixture):
    path, count = fast_path_pdfs[fixture]
    with fitz.open(path) as doc:
        clear_scan_cache()
        reference = _eager_discover(doc, 1)
        assert len(reference) == count and not any(inv.is_form_nested for inv in reference)

        def forbidden(self, *args, **kwargs):
            raise AssertionError("get_image_rects hashes the pixmap of every image on the page")

        monkeypatch.setattr(fitz.Page, "get_image_rects", forbidden)
        clear_scan_cache()
        assert pdf_content_ops.discover_native_image_invocations(doc, 1) == reference


def _scene(shade: int = 200):
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png(shade))
    row = page.get_images(full=True)[0]
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    return doc, page, str(row[7]), int(row[0]), resources


def _write_scene(path, doc, page, content: str) -> str:
    xrefs = [int(x) for x in page.get_contents()]
    doc.update_stream(xrefs[0], content.encode("latin-1"))
    for extra in xrefs[1:]:
        doc.update_stream(extra, b" ")
    doc.save(path)
    doc.close()
    return str(path)


def _twin_image(doc: fitz.Document, image_xref: int) -> int:
    """A second image object with the same pixels, so MuPDF reports one set of placements for both."""
    twin = doc.get_new_xref()
    doc.update_object(twin, doc.xref_object(image_xref, compressed=False))
    doc.update_stream(twin, doc.xref_stream_raw(image_xref), compress=0)
    return twin


def _form(doc: fitz.Document, body: str, image_names: dict[str, int]) -> int:
    xobjects = " ".join(f"/{name} {xref} 0 R" for name, xref in image_names.items())
    form = doc.get_new_xref()
    doc.update_object(
        form, f"<< /Type /XObject /Subtype /Form /BBox [0 0 320 240] /Resources << /XObject << {xobjects} >> >> >>"
    )
    doc.update_stream(form, body.encode("ascii"))
    return form


def _sc_direct_nested(path):
    doc, page, name, _ix, _res = _scene()
    return _write_scene(path, doc, page, f"q 1 0 0 1 10 10 cm q 100 0 0 70 20 150 cm /{name} Do Q Q\n")


def _sc_crop_rotation_user_unit(path):
    doc, page, name, _ix, _res = _scene()
    xref_set_key_exact(doc, page.xref, "Rotate", "90")
    xref_set_key_exact(doc, page.xref, "UserUnit", "2")
    xref_set_key_exact(doc, page.xref, "CropBox", "[10 20 200 200]")
    return _write_scene(path, doc, page, f"q 100 0 0 70 20 150 cm /{name} Do Q\n")


def _sc_clipped_and_zero_cm(path):
    doc, page, name, _ix, _res = _scene()
    content = (
        f"q 0 0 1 1 re W n q 100 0 0 70 20 150 cm /{name} Do Q Q\n"
        f"q 100 0 0 70 150 150 cm /{name} Do Q\n"
        f"q 0 0 0 0 0 0 cm /{name} Do Q\n"
    )
    return _write_scene(path, doc, page, content)


def _sc_inline_image(path):
    doc, page, name, _ix, _res = _scene()
    content = (
        f"q 100 0 0 70 20 150 cm /{name} Do Q\n"
        "BI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI\n"
        f"q 100 0 0 70 150 150 cm /{name} Do Q\n"
    )
    return _write_scene(path, doc, page, content)


def _sc_missing_cm(path):
    doc, page, name, _ix, _res = _scene()
    return _write_scene(path, doc, page, f"q 100 0 0 70 20 150 cm /{name} Do Q\n/{name} Do\n")


def _sc_unprovable_frame(path):
    doc, page, name, _ix, _res = _scene()
    xref_set_key_exact(doc, page.xref, "Rotate", "45")  # not a quarter turn: the frame cannot be proven
    content = f"q 100 0 0 70 20 150 cm /{name} Do Q\nq 100 0 0 70 150 150 cm /{name} Do Q\n"
    return _write_scene(path, doc, page, content)


def _sc_direct_and_form_share_an_xref(path):
    doc, page, name, ix, res = _scene()
    form = _form(doc, f"q 50 0 0 30 160 40 cm /{name} Do Q\n", {name: ix})
    xref_set_key_exact(doc, res, "XObject", f"<< /{name} {ix} 0 R /Fm0 {form} 0 R >>")
    return _write_scene(path, doc, page, f"q 100 0 0 70 20 150 cm /{name} Do Q /Fm0 Do\n")


def _sc_page_and_form_reuse_a_name(path):
    doc, page, name, ix, res = _scene()
    other = _twin_image(doc, ix)
    form = _form(doc, f"q 50 0 0 30 160 40 cm /{name} Do Q\n", {name: other})
    xref_set_key_exact(doc, res, "XObject", f"<< /{name} {ix} 0 R /Fm0 {form} 0 R >>")
    return _write_scene(path, doc, page, f"q 100 0 0 70 20 150 cm /{name} Do Q /Fm0 Do\n")


def _sc_two_forms_reuse_a_name(path):
    """The page-wide name table keeps one xref per name, so the first form's image has no placements."""
    doc, page, _name, ix, res = _scene(200)
    page.insert_image(fitz.Rect(150, 20, 250, 90), stream=_png(90))
    second = [int(row[0]) for row in page.get_images(full=True) if int(row[0]) != ix][0]
    first_form = _form(doc, "q 50 0 0 30 160 40 cm /Im0 Do Q\n", {"Im0": ix})
    second_form = _form(doc, "q 60 0 0 40 20 100 cm /Im0 Do Q\n", {"Im0": second})
    xref_set_key_exact(doc, res, "XObject", f"<< /Fm1 {first_form} 0 R /Fm2 {second_form} 0 R >>")
    return _write_scene(path, doc, page, "/Fm1 Do /Fm2 Do\n")


def _sc_twin_pixels_distinct_xrefs(path):
    doc, page, _name, ix, res = _scene()
    twin = _twin_image(doc, ix)
    xref_set_key_exact(doc, res, "XObject", f"<< /A {ix} 0 R /B {twin} 0 R >>")
    return _write_scene(path, doc, page, "q 100 0 0 70 20 150 cm /A Do Q q 100 0 0 70 150 150 cm /B Do Q /B Do /A Do\n")


def _sc_more_direct_records_than_placements(path):
    """Two direct records sit in a hidden layer MuPDF does not draw: 3 direct cm records, 2 placements."""
    doc, page, name, _ix, res = _scene()
    layer = doc.add_ocg("hidden layer", on=False)
    xref_set_key_exact(doc, res, "Properties", f"<< /oc1 {layer} 0 R >>")
    content = (
        f"/OC /oc1 BDC q 100 0 0 70 20 150 cm /{name} Do Q EMC\n"
        f"/OC /oc1 BDC q 100 0 0 70 150 150 cm /{name} Do Q EMC\n"
        f"q 100 0 0 70 150 10 cm /{name} Do Q\n"
        f"/{name} Do\n"
    )
    return _write_scene(path, doc, page, content)


# name -> (builder, does any branch consume MuPDF placements?)
PLACEMENT_SCENARIOS = {
    "direct_nested_cm": (_sc_direct_nested, False),
    "crop_rotation_user_unit": (_sc_crop_rotation_user_unit, False),
    "clipped_and_zero_cm": (_sc_clipped_and_zero_cm, False),
    "inline_image": (_sc_inline_image, False),
    "missing_cm": (_sc_missing_cm, True),
    "unprovable_frame": (_sc_unprovable_frame, True),
    "direct_and_form_share_an_xref": (_sc_direct_and_form_share_an_xref, True),
    "page_and_form_reuse_a_name": (_sc_page_and_form_reuse_a_name, True),
    "two_forms_reuse_a_name": (_sc_two_forms_reuse_a_name, True),
    "twin_pixels_distinct_xrefs": (_sc_twin_pixels_distinct_xrefs, True),
    "more_direct_records_than_placements": (_sc_more_direct_records_than_placements, True),
}


@pytest.mark.parametrize("scenario", sorted(PLACEMENT_SCENARIOS))
def test_lazy_discovery_matches_the_eager_reference_and_loads_each_xref_once(tmp_path, monkeypatch, scenario):
    build, consumes_placements = PLACEMENT_SCENARIOS[scenario]
    path = build(tmp_path / f"{scenario}.pdf")
    with fitz.open(path) as doc:
        clear_scan_cache()
        reference = _eager_discover(doc, 1)
        assert reference, "the scenario must hold at least one invocation"
        calls: dict[int, int] = {}
        real = fitz.Page.get_image_rects

        def counting(self, name, *args, **kwargs):
            calls[int(name)] = calls.get(int(name), 0) + 1
            return real(self, name, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "get_image_rects", counting)
        clear_scan_cache()
        assert pdf_content_ops.discover_native_image_invocations(doc, 1) == reference
        assert all(count == 1 for count in calls.values()), calls
        assert bool(calls) == consumes_placements, calls


# --------------------------------------------------------------------------- A5 review: D4 on images


@pytest.fixture
def batch_model(tmp_path):
    """Page 1 holds two different images in two short content streams (occurrence 0, then 1)."""
    m = _open(tmp_path, "batch.pdf", long_flags=(False, False))
    yield m
    m.close()
    clear_scan_cache()


def _placements(model: PDFModel) -> list[tuple[int, tuple[int, ...]]]:
    return [
        (invocation.xref, tuple(round(v) for v in invocation.bbox))
        for invocation in pdf_content_ops.discover_native_image_invocations(model.doc, 1)
    ]


def _delete_native(index: int, page: int = 1) -> DeleteObjectRequest:
    return DeleteObjectRequest(f"native_image:{page}:{index}", "native_image", page)


def test_a_repeated_native_image_id_deletes_that_image_once(batch_model):
    first, second = _placements(batch_model)
    assert first[0] != second[0]
    assert batch_model.delete_objects_atomic([_delete_native(0), _delete_native(0)]) is True
    # The second delete used to re-find occurrence 0, which is now the OTHER image.
    assert _placements(batch_model) == [second]


def test_a_batch_that_repeats_every_id_deletes_each_image_once(batch_model):
    batch = [_delete_native(1), _delete_native(0), _delete_native(1), _delete_native(0)]
    assert batch_model.delete_objects_atomic(batch) is True
    assert _placements(batch_model) == []


@pytest.mark.parametrize("bad", ["native_image:1:abc", "native_image:1:-1", "native_image:2:0"])
def test_an_unresolvable_native_image_id_rejects_the_whole_batch_before_any_write(batch_model, bad):
    handle = batch_model.doc
    streams = _page_streams(batch_model)
    placements = _placements(batch_model)
    edits = batch_model.edit_count
    # The valid member sorts first, so the old code wrote it and then rolled back.
    batch = [_delete_native(1), DeleteObjectRequest(bad, "native_image", 1)]
    assert batch_model.delete_objects_atomic(batch) is False
    assert batch_model.doc is handle  # a rollback would have reopened the document from its snapshot
    assert _page_streams(batch_model) == streams
    assert _placements(batch_model) == placements
    assert batch_model.edit_count == edits
    assert batch_model.last_object_op_refusal is not None


def test_a_native_image_batch_with_a_repeat_is_one_undo_step_that_restores_every_stream(
    qapp, batch_model, monkeypatch
):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, batch_model, monkeypatch)
    controller.show_page = lambda *a, **k: None
    try:
        streams = _page_streams(batch_model)
        images = batch_model.doc[0].get_images(full=True)
        placements = _placements(batch_model)
        depth = len(batch_model.command_manager._undo_stack)
        ids = [f"native_image:1:{i}" for i in (1, 0, 1)]
        controller.delete_object(BatchDeleteObjectsRequest([ObjectRef(i, "native_image", 1) for i in ids]))
        assert _placements(batch_model) == []
        assert len(batch_model.command_manager._undo_stack) == depth + 1
        controller.undo()
        assert len(batch_model.command_manager._undo_stack) == depth
        assert _page_streams(batch_model) == streams
        assert batch_model.doc[0].get_images(full=True) == images
        assert _placements(batch_model) == placements
    finally:
        dispose_pdf_view(view, controller, batch_model)


# --------------------------------------------------------------------------- A5 review: D12 short streams in the set


def test_an_uncached_short_stream_counts_against_the_set_budget(tmp_path, monkeypatch):
    m = _open(tmp_path, long_flags=(True, False))
    try:
        monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 1)  # one record each: the pair does not fit
        (long_key, long_stream), = m.image_scan_jobs(1)  # only the long stream goes to the child
        short_key = content_key(_page_streams(m)[1])
        assert content_scan.cached_scan(long_key) is None and content_scan.cached_scan(short_key) is None
        runner = StubRunner()
        coord = _coordinator(m, runner)
        ready, failures = [], []
        coord.image_scan_ready.connect(ready.append)
        coord.probe_failed.connect(lambda *a: failures.append(a))
        coord.request_image_scan(1)
        answer = {"v": 2, "status": "complete", "scans": [content_scan.to_json(scan_stream(long_stream))]}
        decodes = _spy_content_decodes(monkeypatch, int(m.doc[0].get_contents()[0]))
        runner.complete(runner.order[0], answer)
        assert len(decodes) == 1  # the frame check and the admission share one walk of the page
        assert ready == []
        assert failures == [("scan", 1, "resource_limited")]
        assert len(runner.order) == 1  # no retry
        assert content_scan.cached_scan(long_key) is None and content_scan.cached_scan(short_key) is None
        assert m.image_scan_failed(1) is True
        assert m.get_object_info_at_point(1, IMAGE_POINT) is None  # image 1 lives in the long stream
    finally:
        m.close()
        clear_scan_cache()


# --------------------------------------------------------------------------- A5 review: one page scan set per click


def _spy_content_decodes(monkeypatch, xref: int) -> list[int]:
    """Count the decodes of stream ``xref`` (the heavy click's cost: decode, then hash)."""
    real = fitz.Document.xref_stream
    calls: list[int] = []

    def counting(self, number):
        if int(number) == xref:
            calls.append(int(number))
        return real(self, number)

    monkeypatch.setattr(fitz.Document, "xref_stream", counting)
    return calls


def test_a_cold_click_decodes_the_pages_content_stream_once(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        calls = _spy_content_decodes(monkeypatch, int(model.doc[0].get_contents()[0]))
        assert controller.lookup_object_at_point(1, IMAGE_POINT) is OBJECT_LOOKUP_PENDING
        assert [stub.jobs[j][1] for j in stub.order] == ["scan"]  # the job was requested all the same
        assert len(calls) == 1
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_refused_edit_on_a_cold_page_decodes_the_content_stream_once(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        calls = _spy_content_decodes(monkeypatch, int(model.doc[0].get_contents()[0]))
        assert controller.object_op_ready([1], ["native_image"]) is False
        assert [stub.jobs[j][1] for j in stub.order] == ["scan"]
        assert len(calls) == 1
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- A5 review: D9 double fault


def _fail_the_filter_write_then_the_restore(monkeypatch) -> dict[str, int]:
    """Make the splice's ``/Filter`` write raise, then the restore's own ``update_stream`` raise."""
    real_set = pdf_object_ops.xref_set_key_exact
    real_update = fitz.Document.update_stream
    state = {"writes": 0}

    def failing_set(doc, target, key, value):
        if key == "Filter":
            raise RuntimeError("injected Filter write failure")
        return real_set(doc, target, key, value)

    def update(self, xref=0, stream=None, new=1, compress=1):
        state["writes"] += 1
        if state["writes"] == 2:  # the restore's write
            raise RuntimeError("injected restore failure")
        return real_update(self, xref, stream, new, compress)

    monkeypatch.setattr(pdf_object_ops, "xref_set_key_exact", failing_set)
    monkeypatch.setattr(fitz.Document, "update_stream", update)
    return state


@pytest.mark.parametrize("storage_model", ["unfiltered"], indirect=True)
@pytest.mark.parametrize("verb", SPLICE_VERBS)
def test_a_failed_restore_after_a_failed_splice_latches_the_session_damaged(storage_model, monkeypatch, verb):
    from model.pdf_model import DamagedSessionSaveError

    model = storage_model
    original = model.doc.name
    on_disk = open(original, "rb").read()
    assert model.session_damaged is False
    state = _fail_the_filter_write_then_the_restore(monkeypatch)
    with pytest.raises(RuntimeError, match="injected"):
        _run_verb(model, verb)
    assert state["writes"] == 2  # both failure points were reached
    assert model.session_damaged is True
    with pytest.raises(DamagedSessionSaveError):
        model.save_as(original)
    assert open(original, "rb").read() == on_disk


@pytest.mark.parametrize("storage_model", ["unfiltered"], indirect=True)
@pytest.mark.parametrize("verb", SPLICE_VERBS)
def test_a_restore_that_succeeds_leaves_the_session_undamaged(storage_model, monkeypatch, verb):
    _fail_the_next_filter_write(monkeypatch)
    with pytest.raises(RuntimeError, match="injected"):
        _run_verb(storage_model, verb)
    assert storage_model.session_damaged is False
