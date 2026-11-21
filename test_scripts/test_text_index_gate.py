"""Card A6.4 (plans/cad-a6-text-offload-design.md): the text index built in the child, its routing,
the controller gate and the non-blocking text twins.  The runner is a stub (the real child is in
test_object_probe_child_text.py).

Class check (outcome, not a list of causes): after ANY operation that can change the page, a text
answer that is delivered afterwards either installs an index equal to ``extract_page_entry`` of the
LIVE page or is dropped; the page is never left clean with an index of other bytes.
"""
from __future__ import annotations

from types import SimpleNamespace

import fitz
import pytest

from controller.object_probe_coordinator import ObjectProbeCoordinator
from model import table_objects, text_index_jobs
from model.object_requests import TEXT_LOOKUP_PENDING
from model.pdf_model import PDFModel
from model.text_block import extract_page_entry, page_entry_to_json
from test_scripts.qt_teardown import dispose_pdf_view
from test_scripts.test_frame_key_revision import (  # noqa: F401  (the fixtures are used by name)
    _OPS,
    _ocr_with_failing_rebuild,
    _overwrite_form_stream,
    form_model,
    grid_model,
    table_model,
)
from test_scripts.test_object_probe import StubRunner, _controller, _controller_with_the_real_pending_click
from test_scripts.test_table_page_input import _raw_pdf, _stream
from utils import object_probe_platform

PENDING_TEXT = "正在分析此頁文字…"
FOREGROUND_TEXT = "正在分析此頁文字（前景）…"
POINT = fitz.Point(80, 70)


class FrontStub(StubRunner):
    """``StubRunner`` that knows ``front`` and records it per job."""

    def __init__(self):
        super().__init__()
        self.front: dict[int, bool] = {}

        self.promoted: list[int] = []

    def submit(self, owner, kind, payloads, *, front=False):
        job = super().submit(owner, kind, payloads)
        self.front[job] = front
        return job

    def promote(self, job_id):
        self.promoted.append(job_id)
        self.front[job_id] = True


def _text_pdf(path, pages: int = 2) -> str:
    with fitz.open() as doc:
        for _ in range(pages):
            page = doc.new_page(width=595, height=842)
            page.insert_text((72, 72), "hello world", fontsize=12)
        doc.save(path)
    return str(path)


@pytest.fixture
def model(tmp_path):
    m = PDFModel()
    m.open_pdf(_text_pdf(tmp_path / "t.pdf"))
    m.block_manager.clear()  # cold: no page has an index yet
    yield m
    m.close()


@pytest.fixture(autouse=True)
def _contained_child(monkeypatch):
    """The tests do not depend on the host: a contained child exists unless a test says otherwise."""
    monkeypatch.setattr(object_probe_platform, "contained_probe_supported", lambda: True)


@pytest.fixture
def child_routed(monkeypatch):
    """Every page counts as big: it goes to the child."""
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)


def _answer_for(job_payloads, page_idx: int = 0) -> dict:
    """What the child answers for ``job_payloads``: extract on the scratch copy, as JSON."""
    with fitz.open(stream=job_payloads[0], filetype="pdf") as scratch:
        entry = extract_page_entry(page_idx, scratch[0])
    return {"v": 2, "status": "complete", "entry": page_entry_to_json(entry)}


def _coord(model, runner=None):
    runner = runner or FrontStub()
    return ObjectProbeCoordinator(model, runner=runner), runner


def _state(model, page_idx=0):
    return model.block_manager.page_state(page_idx)


def _signals(coord):
    log = SimpleNamespace(ready=[], failed=[], dropped=[])
    coord.text_index_ready.connect(log.ready.append)
    coord.probe_failed.connect(lambda k, p, r: log.failed.append((k, p, r)))
    coord.probe_dropped.connect(lambda k, p: log.dropped.append((k, p)))
    return log


# --------------------------------------------------------------------------- cost routing


def _cost_pdf(
    forms: dict[int, bytes],
    contents: bytes,
    *,
    form_refs: dict[int, list[int]] | None = None,
    page_forms: list[int] | None = None,
) -> bytes:
    """Page 1 with ``contents``; its resources name ``page_forms`` (default: every form) out of
    ``forms`` (number -> stream data); a form lists ``form_refs[number]`` in its own /Resources."""
    form_refs = form_refs or {}
    page_x = b" ".join(b"/F%d %d 0 R" % (n, n) for n in (forms if page_forms is None else page_forms))
    objects = {
        1: (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
        2: (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        3: (
            0,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R"
            b" /Resources << /XObject << " + page_x + b" >> >> >>",
        ),
        4: (0, _stream(contents)),
    }
    for number, data in forms.items():
        inner = b" ".join(b"/F%d %d 0 R" % (n, n) for n in form_refs.get(number, []))
        objects[number] = (
            0,
            _stream(data, b"/Type /XObject /Subtype /Form /BBox [0 0 9 9] /Resources << /XObject << " + inner + b" >> >> "),
        )
    return _raw_pdf(objects)


def _open(data: bytes) -> fitz.Document:
    return fitz.open(stream=data, filetype="pdf")


def test_cost_is_the_raw_contents_length_when_no_form_is_reachable():
    with _open(_cost_pdf({}, b"q Q " * 10)) as doc:
        assert text_index_jobs.text_index_cost_bytes(doc, 1, 10_000) == 40


def test_cost_adds_nested_forms_and_survives_a_cycle():
    # page -> F5 -> F6 -> F5 (cycle); F7 is not reachable from the page
    pdf = _cost_pdf({5: b"a" * 100, 6: b"b" * 50}, b"c" * 10, form_refs={5: [6], 6: [5]}, page_forms=[5])
    with _open(pdf) as doc:
        assert text_index_jobs.text_index_cost_bytes(doc, 1, 10_000) == 10 + 100 + 50


def test_cost_stops_early_once_over_the_limit():
    pdf = _cost_pdf({5: b"a" * 100, 6: b"b" * 100, 7: b"c" * 100}, b"")
    with _open(pdf) as doc:
        cost = text_index_jobs.text_index_cost_bytes(doc, 1, 150)
    assert 150 < cost < 300


def test_cost_counts_past_256_forms_as_over_the_limit():
    forms = {10 + i: b"x" for i in range(300)}
    with _open(_cost_pdf(forms, b"")) as doc:
        assert text_index_jobs.text_index_cost_bytes(doc, 1, 1_000_000) > 1_000_000


def test_cost_of_an_encrypted_document_is_over_the_limit(tmp_path):
    path = tmp_path / "enc.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), "x")
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with fitz.open(str(path)) as doc:
        assert doc.authenticate("u")
        assert text_index_jobs.text_index_cost_bytes(doc, 1, 10**9) > 10**9


def test_failed_keys_are_a_lru_of_256(model):
    for i in range(300):
        text_index_jobs.mark_failed(model, (1, i.to_bytes(4, "big")))
    assert not text_index_jobs.is_failed(model, (1, (0).to_bytes(4, "big")))
    assert text_index_jobs.is_failed(model, (1, (299).to_bytes(4, "big")))
    assert len(text_index_jobs._failed_keys(model)) == 256


def test_route_is_inline_under_the_limit_and_child_over_it(model, monkeypatch):
    assert text_index_jobs.route_for_page(model, 1) == "inline"
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    assert text_index_jobs.route_for_page(model, 1) == "child"
    text_index_jobs.mark_failed(model, table_objects.frame_key(model, 1))
    assert text_index_jobs.route_for_page(model, 1) == "inline"
    assert text_index_jobs.route_for_page(model, 2) == "child"


def test_route_is_inline_without_a_contained_child(model, child_routed, monkeypatch):
    monkeypatch.setattr(text_index_jobs.object_probe_platform, "contained_probe_supported", lambda: False)
    assert text_index_jobs.route_for_page(model, 1) == "inline"


# --------------------------------------------------------------------------- runner priority


def test_runner_front_jumps_the_waiting_jobs_and_never_the_running_one(qapp, monkeypatch):
    from controller.object_probe_runner import ObjectProbeRunner
    from test_scripts.test_object_probe_runner import OK_MEMORY, FakeProcess

    FakeProcess.instances = []
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: OK_MEMORY)
    runner = ObjectProbeRunner(qapp, process_factory=FakeProcess)
    owner = object()
    started = []
    runner.finished.connect(lambda i, ans: started.append(i))
    a = runner.submit(owner, "tables", (b"a",))
    b = runner.submit(owner, "tables", (b"b",))
    c = runner.submit(owner, "text", (b"c", b"0"), front=True)
    assert not FakeProcess.instances[0].killed  # the running job is never killed
    assert [job.job_id for job in runner._queue] == [c, b]
    FakeProcess.instances[0].started.emit()
    FakeProcess.instances[0].answer({"v": 2, "status": "complete", "rects": []})
    assert started == [a]
    assert runner._running is not None and runner._running.job_id == c
    FakeProcess.instances = []


# --------------------------------------------------------------------------- coordinator


def test_request_queues_one_front_job_with_the_copy_and_page_index(model, child_routed):
    coord, runner = _coord(model)
    coord.request_text_index(2)
    (job_id,) = runner.jobs
    owner, kind, payloads = runner.jobs[job_id]
    assert kind == "text" and owner is coord
    assert payloads[1] == b"1"
    assert payloads[0] == table_objects.scratch_page_bytes(model.doc, 2)
    assert runner.front == {job_id: True}


def test_retry_keeps_front(model, child_routed):
    coord, runner = _coord(model)
    coord.request_text_index(1)
    runner.fail(runner.order[0])
    assert len(runner.order) == 2
    assert runner.front[runner.order[1]] is True


def test_second_request_for_the_same_triple_makes_no_copy_and_no_job(model, child_routed, monkeypatch):
    coord, runner = _coord(model)
    coord.request_text_index(1)
    calls = []
    real = table_objects.scratch_page_bytes
    monkeypatch.setattr(table_objects, "scratch_page_bytes", lambda *a, **k: calls.append(1) or real(*a, **k))
    coord.request_text_index(1)
    assert calls == []
    assert len(runner.order) == 1


def test_off_windows_a_request_starts_no_job(model, child_routed, monkeypatch):
    monkeypatch.setattr(text_index_jobs.object_probe_platform, "contained_probe_supported", lambda: False)
    monkeypatch.setattr("controller.object_probe_coordinator.object_probe_platform.contained_probe_supported", lambda: False)
    coord, runner = _coord(model)
    coord.request_text_index(1)
    assert runner.order == []


def test_ready_installs_the_entry_and_leaves_the_page_clean(model, child_routed):
    coord, runner = _coord(model)
    log = _signals(coord)
    coord.request_text_index(1)
    runner.complete(runner.order[0], _answer_for(runner.jobs[runner.order[0]][2]))
    assert log.ready == [1] and log.failed == [] and log.dropped == []
    assert _state(model) == "clean"
    assert model.block_manager.get_blocks(0) == list(extract_page_entry(0, model.doc[0]).blocks)


def test_already_clean_keeps_the_existing_index_and_still_says_ready(model, child_routed):
    coord, runner = _coord(model)
    log = _signals(coord)
    coord.request_text_index(1)
    model.ensure_page_index_built(1)
    kept = model.block_manager.get_blocks(0)
    runner.complete(runner.order[0], _answer_for(runner.jobs[runner.order[0]][2]))
    assert log.ready == [1]
    assert model.block_manager.get_blocks(0) is kept


def test_a_changed_page_drops_the_answer(model, child_routed):
    coord, runner = _coord(model)
    log = _signals(coord)
    coord.request_text_index(1)
    answer = _answer_for(runner.jobs[runner.order[0]][2])
    model.doc[0].insert_text((72, 200), "changed", fontsize=12)
    runner.complete(runner.order[0], answer)
    assert log.dropped == [("text", 1)] and log.ready == []
    assert _state(model) != "clean"


@pytest.mark.parametrize("status", ["resource_limited", "analysis_failed", "containment_failed"])
def test_failure_statuses_mark_the_key(model, child_routed, status):
    coord, runner = _coord(model)
    log = _signals(coord)
    key = table_objects.frame_key(model, 1)
    coord.request_text_index(1)
    runner.complete(runner.order[0], {"v": 2, "status": status})
    assert text_index_jobs.is_failed(model, key)
    assert log.failed == [("text", 1, status)]


@pytest.mark.parametrize("status", ["no_headroom", "unsupported_platform"])
def test_no_mark_statuses_mark_nothing(model, child_routed, status):
    coord, runner = _coord(model)
    log = _signals(coord)
    key = table_objects.frame_key(model, 1)
    coord.request_text_index(1)
    runner.complete(runner.order[0], {"v": 2, "status": status})
    assert not text_index_jobs.is_failed(model, key)
    assert log.failed == [("text", 1, status)]


def test_two_crashes_mark_the_key(model, child_routed):
    coord, runner = _coord(model)
    log = _signals(coord)
    key = table_objects.frame_key(model, 1)
    coord.request_text_index(1)
    runner.fail(runner.order[0])
    assert not text_index_jobs.is_failed(model, key)
    runner.fail(runner.order[1])
    assert text_index_jobs.is_failed(model, key)
    assert log.failed == [("text", 1, "crashed")]


def test_a_decoder_value_error_marks_the_key_failed(model, child_routed):
    coord, runner = _coord(model)
    log = _signals(coord)
    key = table_objects.frame_key(model, 1)
    coord.request_text_index(1)
    runner.complete(runner.order[0], {"v": 2, "status": "complete", "entry": {"blocks": "nonsense"}})
    assert text_index_jobs.is_failed(model, key)
    assert [f[:2] for f in log.failed] == [("text", 1)]
    assert log.ready == [] and _state(model) != "clean"


def test_an_installer_value_error_marks_the_key_failed(model, child_routed):
    coord, runner = _coord(model)
    log = _signals(coord)
    key = table_objects.frame_key(model, 1)
    coord.request_text_index(1)
    # an entry computed for page index 5: the installer refuses it for page 0
    answer = _answer_for(runner.jobs[runner.order[0]][2], page_idx=5)
    runner.complete(runner.order[0], answer)
    assert text_index_jobs.is_failed(model, key)
    assert [f[:2] for f in log.failed] == [("text", 1)]
    assert _state(model) != "clean"


# --------------------------------------------------------------------------- controller gate


def _gate_controller(qapp, model, monkeypatch):
    view, controller, _stub, log = _controller(qapp, model, monkeypatch)
    stub = FrontStub()
    controller._object_probe._runner = stub
    return view, controller, stub, log


def test_cold_child_routed_page_is_pending_and_queues_one_front_job(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        info = controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        assert info is TEXT_LOOKUP_PENDING
        assert len(stub.order) == 1 and stub.front[stub.order[0]] is True
        assert log.status[-1] == PENDING_TEXT
        assert _state(model) != "clean"
    finally:
        dispose_pdf_view(view, controller, model)


def test_second_hover_makes_no_copy_and_no_job(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        calls = []
        real = table_objects.scratch_page_bytes
        monkeypatch.setattr(table_objects, "scratch_page_bytes", lambda *a, **k: calls.append(1) or real(*a, **k))
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        assert calls == [] and len(stub.order) == 1
    finally:
        dispose_pdf_view(view, controller, model)


def test_ready_answer_installs_and_the_next_lookup_answers(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        stub.complete(stub.order[0], _answer_for(stub.jobs[stub.order[0]][2]))
        assert _state(model) == "clean"
        assert log.status[-1] is None
        info = controller.lookup_text_at_point(1, fitz.Point(75, 66), allow_fallback=False)
        assert info is not TEXT_LOOKUP_PENDING
        assert len(stub.order) == 1
    finally:
        dispose_pdf_view(view, controller, model)


def test_failure_marks_the_key_then_the_next_gesture_builds_inline(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        stub.complete(stub.order[0], {"v": 2, "status": "resource_limited"})
        assert log.status[-1] is None  # the pending text is gone
        assert _state(model) != "clean"
        info = controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        assert info is not TEXT_LOOKUP_PENDING
        assert _state(model) == "clean"
        assert len(stub.order) == 1  # no second job
        assert FOREGROUND_TEXT in log.status
    finally:
        dispose_pdf_view(view, controller, model)


def test_no_headroom_builds_inline_and_marks_nothing(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        key = table_objects.frame_key(model, 1)
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        stub.complete(stub.order[0], {"v": 2, "status": "no_headroom"})
        assert not text_index_jobs.is_failed(model, key)
        info = controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        assert info is not TEXT_LOOKUP_PENDING
        assert _state(model) == "clean" and len(stub.order) == 1
    finally:
        dispose_pdf_view(view, controller, model)


def test_off_windows_builds_inline_and_starts_no_job(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        monkeypatch.setattr(text_index_jobs.object_probe_platform, "contained_probe_supported", lambda: False)
        info = controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        assert info is not TEXT_LOOKUP_PENDING
        assert _state(model) == "clean" and stub.order == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_under_limit_page_builds_inline_and_starts_no_job(qapp, model, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        info = controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        assert info is not TEXT_LOOKUP_PENDING
        assert _state(model) == "clean" and stub.order == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_every_twin_is_pending_on_a_cold_child_routed_page(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        for call in (
            lambda: controller.lookup_text_at_point(1, POINT, allow_fallback=False),
            lambda: controller.lookup_char_context_at_point(1, POINT),
            lambda: controller.lookup_text_selection_lines(1, "s", POINT),
            lambda: controller.lookup_text_in_rect(1, fitz.Rect(0, 0, 200, 200)),
            lambda: controller.lookup_text_targets(0, "run", blocks_fallback=True),
        ):
            assert call() is TEXT_LOOKUP_PENDING
        assert len(stub.order) == 1  # one job, deduped
        assert _state(model) != "clean"
    finally:
        dispose_pdf_view(view, controller, model)


def test_request_page_index_never_builds_a_child_routed_page_inline(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        assert controller.request_page_index(1) is False
        assert _state(model) != "clean" and len(stub.order) == 1
        monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 10**9)
        assert controller.request_page_index(2) is True  # small page: built now
        assert _state(model, 1) == "clean"
        assert controller.request_page_index(2) is True
    finally:
        dispose_pdf_view(view, controller, model)


def test_blocking_originals_still_build_inline(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        assert controller.get_text_info_at_point(1, POINT) is not TEXT_LOOKUP_PENDING
        assert _state(model) == "clean" and stub.order == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_text_end_clears_only_its_own_status(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        assert controller._text_status_message == PENDING_TEXT
        stub.complete(stub.order[0], {"v": 2, "status": "no_headroom"})
        assert controller._text_status_message is None
        assert log.dropped == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_no_text_status_while_an_object_status_shows(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller._set_object_status("object pending")
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        assert log.status == ["object pending"]
        assert len(stub.order) == 1
    finally:
        dispose_pdf_view(view, controller, model)


def test_controller_construction_starts_nothing(qapp):
    from controller.pdf_controller import PDFController
    from view.pdf_view import PDFView

    qapp._pdf_object_probe = None
    m = PDFModel()
    view = PDFView()
    controller = PDFController(m, view)
    try:
        assert getattr(qapp, "_pdf_object_probe", None) is None
        assert controller._object_probe._runner is None
    finally:
        dispose_pdf_view(view, controller, m)


# --------------------------------------------------------------------------- class check


_NO_CHANGE_OPS = [
    ("nothing", lambda m: None),
    ("a revision tick only", lambda m: setattr(m, "edit_count", m.edit_count)),
]


def _installed_equals_live(model) -> bool:
    live = extract_page_entry(0, model.doc[0])
    bm = model.block_manager
    return (
        tuple(bm.get_blocks(0)) == live.blocks
        and tuple(bm.get_spans(0)) == live.spans
        and tuple(bm.get_paragraphs(0)) == live.paragraphs
        and bm._run_to_paragraph.get(0) == live.run_map
        and tuple(bm._page_plain_lines.get(0, ())) == live.plain_lines
        and tuple(bm.get_fallback_rows(0)) == live.fallback_rows
    )


def _terminal_after(model, coord, runner, log, op) -> tuple[str, str]:
    """Request, operate, deliver; returns (event, expected event).  The expectation comes from the
    bytes key (an independent oracle): the answer may install iff the page's bytes are unchanged."""
    model.block_manager.clear()
    key_before = table_objects.frame_key(model, 1)
    coord.request_text_index(1, table_objects.PageInput(model, 1))
    job_id = runner.order[-1]
    answer = _answer_for(runner.jobs[job_id][2])
    op(model)
    expected = "ready" if table_objects.frame_key(model, 1) == key_before else "dropped"
    ready0, dropped0, failed0 = len(log.ready), len(log.dropped), len(log.failed)
    runner.complete(job_id, answer)
    assert len(log.failed) == failed0
    event = "ready" if len(log.ready) > ready0 else "dropped" if len(log.dropped) > dropped0 else "none"
    if event == "ready":
        assert _state(model) == "clean" and _installed_equals_live(model)
    else:
        assert _state(model) != "clean" or _installed_equals_live(model)
    return event, expected


def _run_class_check(model, ops) -> list[str]:
    coord, runner = _coord(model)
    log = _signals(coord)
    events = []
    for name, op in ops:
        event, expected = _terminal_after(model, coord, runner, log, op)
        assert event == expected, f"{name}: {event} != {expected}"
        events.append(event)
    return events


def test_every_operation_ends_in_its_expected_terminal_event(tmp_path):
    """Request, operate (the frame-key class check's operation list, undo and redo included),
    deliver: a changed page drops the answer, an unchanged one installs the live page's entry."""
    path = tmp_path / "ops.pdf"
    with fitz.open() as doc:
        doc.new_page(width=595, height=842).insert_text((72, 72), "hello", fontsize=12)
        doc.save(path)
    model = PDFModel()
    model.open_pdf(str(path))
    try:
        ops = [*_OPS, *_NO_CHANGE_OPS]
        events = _run_class_check(model, ops)
        assert events[-2:] == ["ready", "ready"]
        assert events[0] == "dropped" and events[4] == "dropped"  # add textbox, rotate
    finally:
        model.close()


def test_a_form_stream_overwrite_drops_the_answer(form_model):  # noqa: F811
    assert _run_class_check(form_model, [("form overwrite", _overwrite_form_stream)]) == ["dropped"]


def test_a_failed_ocr_write_drops_the_answer(grid_model):  # noqa: F811
    assert _run_class_check(grid_model, [("ocr, index rebuild fails", _ocr_with_failing_rebuild)]) == ["dropped"]


def test_undo_after_a_save_drops_the_answer(table_model, tmp_path):  # noqa: F811
    from test_scripts.test_frame_key_revision import _add_textbox

    _add_textbox(table_model)
    table_model.save_as(str(tmp_path / "saved.pdf"))
    assert _run_class_check(table_model, [("undo after save", lambda m: m.command_manager.undo())]) == ["dropped"]


# --------------------------------------------------------------------------- A6.4 review fixes


def _compressed_labels_pdf(repeats: int = 6000) -> bytes:
    import zlib

    data = b"BT /F1 9 Tf 10 10 Td (label) Tj ET\n" * repeats
    packed = zlib.compress(data)
    return _raw_pdf(
        {
            1: (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
            2: (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
            3: (0, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << >> >>"),
            4: (0, _stream(packed, b"/Filter /FlateDecode ")),
        }
    )


def test_cost_is_the_decoded_length_of_a_compressed_stream():
    with _open(_compressed_labels_pdf()) as doc:
        raw = len(doc.xref_stream_raw(4))
        assert raw < text_index_jobs.TEXT_INLINE_LIMIT_BYTES  # the raw size would say "small"
        assert text_index_jobs.text_index_cost_bytes(doc, 1) > text_index_jobs.TEXT_INLINE_LIMIT_BYTES


def test_a_compressed_repeated_label_page_routes_to_the_child(tmp_path):
    path = tmp_path / "c.pdf"
    path.write_bytes(_compressed_labels_pdf())
    m = PDFModel()
    m.open_pdf(str(path))
    try:
        assert text_index_jobs.route_for_page(m, 1) == "child"
    finally:
        m.close()


def test_images_do_not_count_toward_the_form_cap():
    objects = {
        1: (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
        2: (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        3: (
            0,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /XObject << "
            + b" ".join(b"/I%d %d 0 R" % (n, n) for n in range(10, 310))
            + b" >> >> >>",
        ),
        4: (0, _stream(b"q Q")),
    }
    for n in range(10, 310):
        objects[n] = (0, _stream(b"\x00", b"/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 "))
    with _open(_raw_pdf(objects)) as doc:
        assert text_index_jobs.text_index_cost_bytes(doc, 1, 1_000_000) < 1_000_000


def test_a_too_deep_resource_inheritance_is_over_the_limit():
    objects = {
        1: (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
        2: (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        3: (0, b"<< /Type /Page /Parent 5 0 R /MediaBox [0 0 300 300] /Contents 4 0 R >>"),
        4: (0, _stream(b"q Q")),
    }
    for n in range(5, 40):  # 35 ancestors, none has /Resources
        objects[n] = (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 /Parent %d 0 R >>" % (n + 1))
    objects[40] = (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    with _open(_raw_pdf(objects)) as doc:
        assert text_index_jobs.text_index_cost_bytes(doc, 1, 1_000_000) > 1_000_000


def test_a_slow_inline_build_routes_the_page_to_the_child_next_time(qapp, model, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        monkeypatch.setattr(text_index_jobs, "SLOW_INLINE_BUILD_SECONDS", 0.0)
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is not TEXT_LOOKUP_PENDING
        assert stub.order == [] and _state(model) == "clean"
        model.block_manager.clear()  # cold again, same bytes
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        assert len(stub.order) == 1
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_fast_inline_build_stays_inline(qapp, model, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        monkeypatch.setattr(text_index_jobs, "SLOW_INLINE_BUILD_SECONDS", 1e9)
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        model.block_manager.clear()
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is not TEXT_LOOKUP_PENDING
        assert stub.order == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_revision_only_change_keeps_one_job_and_builds_nothing_inline(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        builds = []
        real = model.ensure_page_index_built
        monkeypatch.setattr(model, "ensure_page_index_built", lambda p: builds.append(p) or real(p))
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        model.edit_count = model.edit_count  # a revision tick, the page keeps its bytes
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        assert len(stub.order) == 1 and builds == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_request_text_index_says_what_it_did(model, child_routed, monkeypatch):
    coord, runner = _coord(model)
    assert coord.request_text_index(1) == "queued"
    assert coord.request_text_index(1) == "duplicate"
    model.edit_count = model.edit_count
    assert coord.request_text_index(1) == "duplicate"  # same bytes key
    assert coord.request_text_index(99) == "failed"
    monkeypatch.setattr(object_probe_platform, "contained_probe_supported", lambda: False)
    assert coord.request_text_index(2) == "inline"


def test_a_late_event_of_an_older_job_keeps_the_newer_jobs_click(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        drops, resolved = [], []
        view.drop_pending_text_click = drops.append
        view.resolve_pending_text_click = resolved.append
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        job_a = stub.order[0]
        answer_a = _answer_for(stub.jobs[job_a][2])
        model.doc[0].insert_text((72, 300), "newer bytes", fontsize=12)
        model.edit_count = model.edit_count  # the revision moves with the write (a new request)
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        job_b = stub.order[1]
        stub.complete(job_a, answer_a)  # A ends late: stale, dropped
        assert drops == [] and controller._text_status_message == PENDING_TEXT
        stub.complete(job_b, _answer_for(stub.jobs[job_b][2]))
        assert resolved == [1] and drops == []
        assert _state(model) == "clean"
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_failure_of_an_old_handles_job_is_a_drop_and_stamps_no_route(model, child_routed):
    coord, runner = _coord(model)
    log = _signals(coord)
    coord.request_text_index(1)
    for job in coord._jobs.values():
        job.flight = (job.flight[0] - 1, job.flight[1], job.flight[2])
    runner.complete(runner.order[0], {"v": 2, "status": "analysis_failed"})
    assert log.failed == [] and log.dropped == [("text", 1)]


def test_cancel_all_clears_the_text_status_and_the_next_gesture_requests_again(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        drops = []
        view.drop_pending_text_click = drops.append
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        controller._object_probe.cancel_all()
        assert controller._text_status_message is None and log.status[-1] is None
        assert drops == [1]
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        assert len(stub.order) == 2
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_gesture_promotes_the_waiting_prewarm_job(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        assert controller.request_page_index(2) is False  # prewarm: queued, not at the front
        assert controller.request_page_index(1) is False
        job_prewarm = stub.order[1]
        assert stub.front[job_prewarm] is False
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        assert stub.promoted == [job_prewarm] and len(stub.order) == 2
    finally:
        dispose_pdf_view(view, controller, model)


def _fake_runner(qapp, monkeypatch):
    from controller.object_probe_runner import ObjectProbeRunner
    from test_scripts.test_object_probe_runner import OK_MEMORY, FakeProcess

    FakeProcess.instances = []
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: OK_MEMORY)
    return ObjectProbeRunner(qapp, process_factory=FakeProcess)


def test_runner_promote_moves_a_waiting_job_to_the_front(qapp, monkeypatch):
    runner = _fake_runner(qapp, monkeypatch)
    owner = object()
    runner.submit(owner, "tables", (b"a",))
    b = runner.submit(owner, "tables", (b"b",))
    c = runner.submit(owner, "text", (b"c", b"0"))
    runner.promote(c)
    assert [job.job_id for job in runner._queue] == [c, b]


def test_front_jumps_over_a_waiting_tables_job_are_bounded(qapp, monkeypatch):
    runner = _fake_runner(qapp, monkeypatch)
    owner = object()
    runner.submit(owner, "tables", (b"running",))
    tables = runner.submit(owner, "tables", (b"waiting",))
    texts = [runner.submit(owner, "text", (b"t", b"0"), front=True) for _ in range(5)]
    order = [job.job_id for job in runner._queue]
    assert order.index(tables) == 3  # three front texts went ahead of it, the rest come after
    assert order[:3] == [texts[2], texts[1], texts[0]]


def test_one_ready_signal_invokes_the_resolver_once(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        resolved = []
        view.resolve_pending_text_click = resolved.append
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        stub.complete(stub.order[0], _answer_for(stub.jobs[stub.order[0]][2]))
        assert resolved == [1]
    finally:
        dispose_pdf_view(view, controller, model)


def test_prewarm_neither_uses_nor_consumes_a_gestures_route(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller._add_inline_route(1, table_objects.frame_key(model, 1))
        assert controller.request_page_index(1) is False  # child-routed: a job, no inline build
        assert len(stub.order) == 1 and _state(model) != "clean"
        assert {r[1] for r in controller._text_inline_routes} == {1}  # still the gesture's
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_route_dies_with_the_bytes_it_was_armed_for(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller._add_inline_route(1, table_objects.frame_key(model, 1))
        model.doc[0].insert_text((72, 300), "edited", fontsize=12)
        model.edit_count = model.edit_count
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING  # not inline
        assert not controller._text_inline_routes
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_route_is_used_by_one_inline_build_only(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller.lookup_text_at_point(1, POINT, allow_fallback=True)
        stub.complete(stub.order[0], {"v": 2, "status": "no_headroom"})
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is not TEXT_LOOKUP_PENDING
        model.block_manager.clear()  # invalidated, same bytes: the route is spent
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
    finally:
        dispose_pdf_view(view, controller, model)


def test_routes_of_retired_generations_are_dropped(qapp, model, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        controller._text_inline_routes = {(model.handle_generation - 1, 1, (1, b"k"))}
        controller._add_inline_route(2, (2, b"k"))
        assert controller._text_inline_routes == {(model.handle_generation, 2, (2, b"k"))}
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_current_jobs_failure_is_not_swallowed_by_an_older_waiting_job(qapp, model, child_routed, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        drops = []
        view.drop_pending_text_click = drops.append
        assert controller.request_page_index(1) is False  # prewarm job A (old bytes)
        job_a = stub.order[0]
        model.doc[0].insert_text((72, 300), "newer", fontsize=12)
        model.edit_count = model.edit_count
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING  # B
        job_b = stub.order[1]
        stub.complete(job_b, {"v": 2, "status": "no_headroom"})
        assert drops == [1] and controller._text_status_message is None and controller._text_inline_routes
        stub.complete(job_a, _answer_for(stub.jobs[job_a][2]))  # A ends: nobody's click
        assert drops == [1]
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is not TEXT_LOOKUP_PENDING
        assert len(stub.order) == 2  # B's route built inline, nothing was queued again
    finally:
        dispose_pdf_view(view, controller, model)


def test_an_unexpected_installer_error_becomes_the_failed_outcome(model, child_routed, monkeypatch):
    coord, runner = _coord(model)
    log = _signals(coord)
    key = table_objects.frame_key(model, 1)
    coord.request_text_index(1)
    answer = _answer_for(runner.jobs[runner.order[0]][2])

    def boom(*_a, **_k):
        raise RuntimeError("installer blew up")

    monkeypatch.setattr(text_index_jobs, "install_text_index", boom)
    runner.complete(runner.order[0], answer)
    assert text_index_jobs.is_failed(model, key)
    assert [f[:2] for f in log.failed] == [("text", 1)]


@pytest.mark.parametrize("event", ["failed", "dropped"])
def test_a_text_end_leaves_the_object_click_and_status_alone(qapp, model, child_routed, monkeypatch, event):
    view, controller, _old, log, mgr = _controller_with_the_real_pending_click(qapp, model, monkeypatch)
    stub = FrontStub()
    controller._object_probe._runner = stub
    try:
        mgr._store_pending_object_click(1, 170.0, 245.0, False)  # a real pending object click
        controller._set_object_status("object pending")
        before = list(log.status)
        assert controller.lookup_text_at_point(1, POINT, allow_fallback=True) is TEXT_LOOKUP_PENDING
        job = stub.order[0]
        if event == "failed":
            stub.complete(job, {"v": 2, "status": "resource_limited"})
        else:
            answer = _answer_for(stub.jobs[job][2])
            model.doc[0].insert_text((72, 300), "changed", fontsize=12)
            stub.complete(job, answer)
        assert mgr._pending_object_click is not None and mgr._pending_object_click.page_num == 1
        assert controller._object_status_message == "object pending"
        assert log.status == before
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_slow_prewarm_build_records_the_slow_key_too(qapp, model, monkeypatch):
    view, controller, stub, log = _gate_controller(qapp, model, monkeypatch)
    try:
        monkeypatch.setattr(text_index_jobs, "SLOW_INLINE_BUILD_SECONDS", 0.0)
        assert controller.request_page_index(1) is True  # small page: built here, measured slow
        model.block_manager.clear()  # invalidated, bytes unchanged
        assert controller.request_page_index(1) is False  # the slow key goes to the child
        assert len(stub.order) == 1 and _state(model) != "clean"
    finally:
        dispose_pdf_view(view, controller, model)
