"""Card A3 (plans/cad-vector-object-editing-handoff.md): the table probe leaves the GUI thread.

Model non-blocking lookup (H15), coordinator (H14, H16), pending click as data (H4), controller
and view wiring.  The runner is a stub; the real child is tested in test_object_probe_child.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtCore import QObject, QPointF, Qt, Signal

import view.pdf_view as pdf_view
from model import table_objects
from model.object_requests import (
    OBJECT_LOOKUP_PENDING,
    DeleteObjectRequest,
    ObjectHitInfo,
    ObjectLookupPending,
)
from model.pdf_model import PDFModel
from test_scripts.test_object_multi_select import _FakeEvent, _make_object_hit, _make_view

TABLE_RECT = [100.0, 200.0, 460.0, 320.0]


def _complete(rects) -> dict:
    return {"v": 2, "status": "complete", "rects": rects}


def _draw_table(page: fitz.Page) -> None:
    for r in range(4):
        for c in range(3):
            cell = fitz.Rect(100 + c * 120, 200 + r * 30, 100 + (c + 1) * 120, 200 + (r + 1) * 30)
            page.draw_rect(cell, color=(0, 0, 0), width=1)
            page.insert_text((cell.x0 + 5, cell.y0 + 20), f"R{r}C{c}", fontsize=11)


def _table_pdf(path, pages: int = 3):
    with fitz.open() as doc:
        for _ in range(pages):
            _draw_table(doc.new_page(width=595, height=842))
        doc.save(path)
    return str(path)


@pytest.fixture
def model(tmp_path):
    m = PDFModel()
    m.open_pdf(_table_pdf(tmp_path / "t.pdf"))
    yield m
    m.close()


class StubRunner(QObject):
    finished = Signal(int, object)
    failed = Signal(int)

    def __init__(self):
        super().__init__()
        self.jobs: dict[int, tuple] = {}
        self.order: list[int] = []
        self.running: int | None = None
        self.cancelled: list[int] = []
        self.owner_cancels: list[object] = []
        self._next = 1

    def submit(self, owner, kind, payloads):
        job = self._next
        self._next += 1
        self.jobs[job] = (owner, kind, payloads)
        self.order.append(job)
        if self.running is None:
            self.running = job
        return job

    def is_waiting(self, job):
        return job in self.jobs and job != self.running

    def cancel(self, job):
        self.cancelled.append(job)
        self.jobs.pop(job, None)
        if self.running == job:
            self.running = None

    def cancel_owner(self, owner):
        self.owner_cancels.append(owner)
        self.jobs.clear()
        self.running = None

    def complete(self, job, answer):
        self.jobs.pop(job, None)
        if self.running == job:
            self.running = None
        self.finished.emit(job, answer)

    def fail(self, job):
        self.jobs.pop(job, None)
        if self.running == job:
            self.running = None
        self.failed.emit(job)


# --------------------------------------------------------------------------- model


def test_pending_sentinel_is_a_singleton_with_a_fixed_repr():
    assert isinstance(OBJECT_LOOKUP_PENDING, ObjectLookupPending)
    assert repr(OBJECT_LOOKUP_PENDING) == repr(ObjectLookupPending())


def test_non_blocking_lookup_on_a_cold_page_is_pending_and_does_no_detection(model, monkeypatch):
    def boom(page):
        raise AssertionError("find_table_rects must not run on a non-blocking lookup")

    monkeypatch.setattr(table_objects, "find_table_rects", boom)
    info = model.get_object_info_at_point(1, fitz.Point(170, 245), blocking=False)
    assert info is OBJECT_LOOKUP_PENDING


def test_non_blocking_lookup_with_a_warm_cache_answers_like_the_blocking_one(model):
    blocking = model.get_object_info_at_point(1, fitz.Point(170, 245))
    assert blocking is not None and blocking.object_kind == "table"
    warm = model.get_object_info_at_point(1, fitz.Point(170, 245), blocking=False)
    assert warm == blocking
    assert model.get_object_info_at_point(1, fitz.Point(5, 5), blocking=False) is None


def test_non_blocking_lookup_finds_annotation_objects_before_it_is_pending(model):
    from model.pdf_object_ops import get_object_info_at_point

    assert get_object_info_at_point(model, 1, fitz.Point(5, 5), blocking=False) is OBJECT_LOOKUP_PENDING
    assert get_object_info_at_point(model, 1, fitz.Point(5, 5)) is None  # default still blocks


# --------------------------------------------------------------------------- coordinator


def _coordinator(model, runner):
    from controller.object_probe_coordinator import ObjectProbeCoordinator

    return ObjectProbeCoordinator(model, runner=runner)


def test_cold_request_submits_one_tables_job_with_a_pdf_payload(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_tables(1)
    assert len(runner.jobs) == 1
    owner, kind, payloads = next(iter(runner.jobs.values()))
    assert owner is coord and kind == "tables"
    assert len(payloads) == 1 and payloads[0].startswith(b"%PDF")
    coord.request_tables(1)  # same key already in flight
    assert len(runner.jobs) == 1


def test_cached_page_submits_nothing(model):
    table_objects.table_rects(model, 1)
    runner = StubRunner()
    _coordinator(model, runner).request_tables(1)
    assert runner.jobs == {}


def test_answer_is_stored_and_announced(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(2)
    runner.complete(runner.order[0], _complete([TABLE_RECT]))
    assert ready == [2]
    assert table_objects.cached_table_rects(model, 2) == [fitz.Rect(*TABLE_RECT)]


def test_answer_for_a_changed_page_frame_is_dropped_silently(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)
    model.doc[0].set_rotation(90)  # the frame key changes
    runner.complete(runner.order[0], _complete([TABLE_RECT]))
    assert ready == []
    assert table_objects.cached_table_rects(model, 1) is None


def test_newer_request_replaces_a_waiting_job_and_leaves_the_running_one(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_tables(1)  # runs
    coord.request_tables(2)  # waits
    coord.request_tables(3)  # replaces the waiting one
    first, second, third = runner.order
    assert runner.cancelled == [second]
    assert runner.running == first and third in runner.jobs


def test_failed_child_is_retried_once_then_crashed_and_the_page_is_marked(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_tables(1)
    first = runner.order[0]
    payload = runner.jobs[first][2]
    runner.fail(first)
    assert len(runner.order) == 2
    assert runner.jobs[runner.order[1]][2] == payload
    assert failures == []
    runner.fail(runner.order[1])
    assert failures == [("tables", 1, "crashed")]
    assert table_objects.cached_table_rects(model, 1) is None  # a failure never caches []
    assert table_objects.table_analysis_failed(model, 1) is True
    assert len(runner.order) == 2


def test_complete_with_no_tables_is_stored_as_a_real_empty_list(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)
    runner.complete(runner.order[0], _complete([]))
    assert ready == [1]
    assert table_objects.cached_table_rects(model, 1) == []
    assert table_objects.table_analysis_failed(model, 1) is False


@pytest.mark.parametrize("status", ["resource_limited", "analysis_failed", "containment_failed"])
def test_typed_failures_do_not_retry_store_nothing_and_mark_the_page(model, status):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_tables(1)
    runner.complete(runner.order[0], {"v": 2, "status": status})
    assert len(runner.order) == 1  # no retry
    assert failures == [("tables", 1, status)]
    assert table_objects.cached_table_rects(model, 1) is None
    assert table_objects.table_analysis_failed(model, 1) is True


def test_no_headroom_marks_nothing_so_the_next_request_starts_a_job(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_tables(1)
    runner.complete(runner.order[0], {"v": 2, "status": "no_headroom"})
    assert failures == [("tables", 1, "no_headroom")]
    assert table_objects.cached_table_rects(model, 1) is None
    assert table_objects.table_analysis_failed(model, 1) is False
    coord.request_tables(1)
    assert len(runner.order) == 2


def test_malformed_complete_is_treated_as_a_runner_failure(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_tables(1)
    runner.complete(runner.order[0], {"v": 2, "status": "complete", "rects": "oops"})
    assert len(runner.order) == 2  # one retry
    runner.complete(runner.order[1], {"v": 2, "status": "complete", "rects": "oops"})
    assert failures == [("tables", 1, "crashed")]
    assert table_objects.cached_table_rects(model, 1) is None


def test_marked_page_gets_no_new_job_and_a_non_pending_lookup(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_tables(1)
    runner.complete(runner.order[0], {"v": 2, "status": "analysis_failed"})
    coord.request_tables(1)
    assert len(runner.order) == 1
    info = model.get_object_info_at_point(1, fitz.Point(170, 245), blocking=False)
    assert info is not OBJECT_LOOKUP_PENDING and info is None


def test_a_changed_frame_probes_a_marked_page_again(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    coord.request_tables(1)
    runner.complete(runner.order[0], {"v": 2, "status": "analysis_failed"})
    model.doc[0].set_rotation(90)
    assert table_objects.table_analysis_failed(model, 1) is False
    coord.request_tables(1)
    assert len(runner.order) == 2


def test_an_answer_emitted_inside_submit_is_still_delivered(model):
    class EagerRunner(StubRunner):
        def submit(self, owner, kind, payloads):
            job = super().submit(owner, kind, payloads)
            self.finished.emit(job, {"v": 2, "status": "no_headroom"})
            return job

    runner = EagerRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_tables(1)
    assert failures == [("tables", 1, "no_headroom")]


def _restore_with_changed_page_bytes(model) -> None:
    changed = fitz.open(stream=model.doc.tobytes(), filetype="pdf")
    changed[0].insert_text((50, 60), "changed", fontsize=11)
    model._restore_doc_from_snapshot(changed.tobytes())
    changed.close()


def test_old_answer_after_snapshot_replacement_that_changes_the_bytes_is_dropped(model, monkeypatch):
    # Same id() for every handle: the deterministic form of address reuse (D1).
    monkeypatch.setattr(table_objects, "id", lambda _obj: 42, raising=False)
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)
    _restore_with_changed_page_bytes(model)
    runner.complete(runner.order[0], _complete([TABLE_RECT]))
    assert ready == []
    assert table_objects.cached_table_rects(model, 1) is None


def test_answer_after_a_same_bytes_replacement_is_accepted(model):
    # F1: a new handle over the same page bytes keeps the answer; the bytes are the identity.
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)
    model._restore_doc_from_snapshot(model.doc.tobytes())
    runner.complete(runner.order[0], _complete([TABLE_RECT]))
    assert ready == [1]
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(*TABLE_RECT)]


@pytest.mark.parametrize("outcome", ["analysis_failed", "resource_limited", "no_headroom", "crash"])
def test_late_failure_for_bytes_the_page_no_longer_has_is_dropped_silently(model, monkeypatch, outcome):
    # D1: no message and no retry may reach a page whose bytes changed since the request.
    monkeypatch.setattr(table_objects, "id", lambda _obj: 42, raising=False)
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_tables(1)
    _restore_with_changed_page_bytes(model)
    job = runner.order[0]
    if outcome == "crash":
        runner.fail(job)
    else:
        runner.complete(job, {"v": 2, "status": outcome})
    assert failures == []
    assert runner.order == [job]
    assert table_objects.table_analysis_failed(model, 1) is False


def test_stale_key_is_not_marked(model):
    key = table_objects.frame_key(model, 1)
    model.doc[0].set_rotation(90)
    table_objects.mark_table_analysis_failed(model, key)
    assert table_objects.table_analysis_failed(model, 1) is False


def test_storing_rects_clears_the_failed_mark(model):
    key = table_objects.frame_key(model, 1)
    table_objects.mark_table_analysis_failed(model, key)
    assert table_objects.table_analysis_failed(model, 1) is True
    assert table_objects.store_table_rects(model, key, [TABLE_RECT]) is True
    assert table_objects.table_analysis_failed(model, 1) is False


def test_cancel_all_cancels_the_owner_and_forgets_jobs(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)
    job = runner.order[0]
    coord.cancel_all()
    assert runner.owner_cancels == [coord]
    runner.finished.emit(job, _complete([TABLE_RECT]))  # a late answer
    assert ready == []


def test_answers_for_other_owners_are_ignored(model):
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)
    runner.finished.emit(999, _complete([TABLE_RECT]))
    assert ready == []


# --------------------------------------------------------------------------- view: pending click


def _pending_view(monkeypatch, answers):
    view = _make_view()
    calls = []

    def lookup(page_num, point):
        calls.append((page_num, point))
        return answers[0]

    view.controller.lookup_object_at_point = lookup
    view._calls = calls
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **k: None)
    return view


def test_cold_click_stores_the_click_as_data_and_selects_nothing(monkeypatch):
    view = _pending_view(monkeypatch, [OBJECT_LOOKUP_PENDING])
    event = _FakeEvent(10, 10, modifiers=Qt.ShiftModifier)
    pdf_view.PDFView._mouse_press(view, event)
    mgr = view._ensure_object_selection_manager()
    pending = mgr._pending_object_click
    assert pending is not None
    assert (pending.page_num, pending.x, pending.y) == (1, 10.0, 10.0)
    assert pending.additive is True and pending.mode == "objects"
    assert pending.generation == mgr._object_click_generation
    assert event.accepted is True
    assert view._selected_object_info is None and view._object_drag_pending is False


def test_the_answer_selects_the_object_without_arming_a_drag(monkeypatch):
    answers = [OBJECT_LOOKUP_PENDING]
    view = _pending_view(monkeypatch, answers)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    hit = _make_object_hit("a", kind="rect", page_num=1)
    answers[0] = hit
    view.resolve_pending_object_click(1)
    assert view._selected_object_info == hit
    assert view._object_drag_pending is False
    assert view._ensure_object_selection_manager()._pending_object_click is None
    assert view._calls[-1][0] == 1


def test_resolve_for_another_page_does_nothing(monkeypatch):
    answers = [OBJECT_LOOKUP_PENDING]
    view = _pending_view(monkeypatch, answers)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    answers[0] = _make_object_hit("a")
    n = len(view._calls)
    view.resolve_pending_object_click(2)
    assert len(view._calls) == n and view._selected_object_info is None
    assert view._ensure_object_selection_manager()._pending_object_click is not None


def test_resolve_that_is_pending_again_keeps_waiting_and_none_clears(monkeypatch):
    answers = [OBJECT_LOOKUP_PENDING]
    view = _pending_view(monkeypatch, answers)
    mgr = view._ensure_object_selection_manager()
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    view.resolve_pending_object_click(1)
    assert mgr._pending_object_click is not None
    answers[0] = None
    view.resolve_pending_object_click(1)
    assert mgr._pending_object_click is None and view._selected_object_info is None


def test_a_newer_press_makes_the_old_pending_click_stale(monkeypatch):
    answers = [OBJECT_LOOKUP_PENDING]
    view = _pending_view(monkeypatch, answers)
    mgr = view._ensure_object_selection_manager()
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    old = mgr._pending_object_click
    answers[0] = None
    pdf_view.PDFView._mouse_press(view, _FakeEvent(60, 60))  # a miss
    assert mgr._object_click_generation != old.generation
    answers[0] = _make_object_hit("a")
    view.resolve_pending_object_click(1)
    assert view._selected_object_info is None


@pytest.mark.parametrize("how", ["clear", "select"])
def test_clearing_or_selecting_drops_the_pending_click(monkeypatch, how):
    answers = [OBJECT_LOOKUP_PENDING]
    view = _pending_view(monkeypatch, answers)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    if how == "clear":
        view._clear_object_selection()  # what a tab change reaches
    else:
        view._select_object(_make_object_hit("z"))
        view._selected_object_info = None
    answers[0] = _make_object_hit("a")
    view.resolve_pending_object_click(1)
    assert view._selected_object_info is None


def test_drop_pending_object_click_clears_it(monkeypatch):
    view = _pending_view(monkeypatch, [OBJECT_LOOKUP_PENDING])
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    view.drop_pending_object_click()
    assert view._ensure_object_selection_manager()._pending_object_click is None


def _real_view_with_pending_click(hit):
    view = pdf_view.PDFView()
    view.current_mode = "objects"
    view.controller = SimpleNamespace(
        lookup_object_at_point=lambda page, point: hit[0],
        has_unsaved_changes=lambda: False,
    )
    mgr = view._ensure_object_selection_manager()
    mgr._store_pending_object_click(1, 5.0, 5.0, False)
    return view, mgr


def test_pending_click_survives_continuous_zoom(qapp):
    """D3: a scene rebuild for zoom clears the visual selection but not the click."""
    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        before = mgr._pending_object_click
        generation = mgr._object_click_generation
        view.initialize_continuous_placeholders([(595.0, 842.0)], 1.5, 0, keep_pending_object_click=True)
        assert mgr._pending_object_click is before
        assert mgr._object_click_generation == generation
        hit[0] = _make_object_hit("a", kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert view._selected_object_info == hit[0]
    finally:
        view.close()


@pytest.mark.parametrize("second", ["b", "a"])
def test_a_shift_click_pending_across_a_zoom_keeps_the_selection_it_was_based_on(qapp, second):
    """D3 review: select A, Shift-click B (cold), zoom, the reply applies: A and B are selected
    (Shift-click on A again: nothing is); the zoom must not turn the toggle into a fresh select."""
    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        first = _make_object_hit("a", kind="rect", page_num=1)
        assert mgr._apply_object_hit(0, first, False) is True
        assert set(view._selected_object_infos) == {"a"}
        mgr._store_pending_object_click(1, 5.0, 5.0, True)  # the Shift-click on the cold page
        view.initialize_continuous_placeholders([(595.0, 842.0)], 1.5, 0, keep_pending_object_click=True)
        hit[0] = _make_object_hit(second, kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert set(view._selected_object_infos) == ({"a", "b"} if second == "b" else set())
    finally:
        view.close()


def test_a_shift_click_pending_across_two_zooms_keeps_the_first_captured_selection(qapp):
    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        assert mgr._apply_object_hit(0, _make_object_hit("a", kind="rect", page_num=1), False) is True
        mgr._store_pending_object_click(1, 5.0, 5.0, True)
        for scale in (1.5, 2.0):  # the second rebuild finds the live set already empty
            view.initialize_continuous_placeholders([(595.0, 842.0)], scale, 0, keep_pending_object_click=True)
        hit[0] = _make_object_hit("b", kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert set(view._selected_object_infos) == {"a", "b"}
    finally:
        view.close()


def test_a_selection_updated_while_a_shift_click_waits_is_not_reverted_by_the_reply(qapp):
    """A rotate or resize of the selected object (it rebases the selection, no generation bump)
    between the press and the reply: the reply must toggle against the UPDATED set."""
    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        assert mgr._apply_object_hit(0, _make_object_hit("a", kind="rect", page_num=1), False) is True
        mgr._store_pending_object_click(1, 5.0, 5.0, True)
        moved = fitz.Rect(200, 300, 260, 360)
        mgr._rebase_object_selection_to_bboxes({"a": moved})
        hit[0] = _make_object_hit("b", kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert set(view._selected_object_infos) == {"a", "b"}
        assert fitz.Rect(view._selected_object_infos["a"].bbox) == moved
    finally:
        view.close()


def test_a_plain_pending_click_across_a_zoom_replaces_the_selection(qapp):
    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        assert mgr._apply_object_hit(0, _make_object_hit("a", kind="rect", page_num=1), False) is True
        mgr._store_pending_object_click(1, 5.0, 5.0, False)
        view.initialize_continuous_placeholders([(595.0, 842.0)], 1.5, 0, keep_pending_object_click=True)
        hit[0] = _make_object_hit("b", kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert set(view._selected_object_infos) == {"b"}
    finally:
        view.close()


def test_pending_click_survives_single_page_zoom(qapp):
    from PySide6.QtGui import QPixmap

    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        view.continuous_pages = False
        pix = QPixmap(40, 40)
        view.display_page(0, pix)  # what change_scale does in single-page mode
        assert mgr._pending_object_click is not None
        hit[0] = _make_object_hit("a", kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert view._selected_object_info == hit[0]
    finally:
        view.close()


def test_structural_scene_rebuild_still_cancels_the_pending_click(qapp):
    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        view.initialize_continuous_placeholders([(595.0, 842.0)], 1.0, 0)
        assert mgr._pending_object_click is None
        hit[0] = _make_object_hit("a", kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert view._selected_object_info is None
    finally:
        view.close()


def test_zoom_keeps_the_click_but_a_newer_press_after_it_still_wins(qapp):
    hit = [OBJECT_LOOKUP_PENDING]
    view, mgr = _real_view_with_pending_click(hit)
    try:
        view.initialize_continuous_placeholders([(595.0, 842.0)], 1.5, 0, keep_pending_object_click=True)
        old = mgr._pending_object_click
        mgr.bump_object_click_generation()  # a newer press / selection change
        hit[0] = _make_object_hit("a", kind="rect", page_num=1)
        view.resolve_pending_object_click(1)
        assert old is not None and view._selected_object_info is None
    finally:
        view.close()


def test_controller_zoom_in_continuous_mode_asks_the_view_to_keep_the_pending_click(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, _stub, _log = _controller(qapp, model, monkeypatch)
    try:
        calls = []
        monkeypatch.setattr(
            view, "initialize_continuous_placeholders", lambda *a, **k: calls.append(k)
        )
        controller._schedule_visible_render = lambda *a, **k: None
        controller._cancel_page_render_for_session = lambda *a, **k: None
        view.continuous_pages = True
        sid = model.get_active_session_id()
        controller._page_sizes_by_session[sid] = [(595.0, 842.0)] * 3
        controller._rebuild_continuous_scene(0, reload_toc=False, keep_pending_object_click=True)
        controller._rebuild_continuous_scene(0)
        assert [bool(k.get("keep_pending_object_click")) for k in calls] == [True, False]
    finally:
        dispose_pdf_view(view, controller, model)


def test_mode_change_drops_the_pending_click(qapp):
    view = pdf_view.PDFView()
    try:
        mgr = view._ensure_object_selection_manager()
        view.current_mode = "objects"
        view.controller = SimpleNamespace(
            lookup_object_at_point=lambda page, point: _make_object_hit("a"),
            has_unsaved_changes=lambda: False,
        )
        mgr._store_pending_object_click(1, 5.0, 5.0, False)
        assert mgr._pending_object_click is not None
        view.set_mode("browse")
        view.current_mode = "objects"
        view.resolve_pending_object_click(1)
        assert view._selected_object_info is None
    finally:
        view.close()


def test_press_on_a_resize_handle_does_no_lookup(monkeypatch):
    view = _pending_view(monkeypatch, [OBJECT_LOOKUP_PENDING])
    view._selected_object_info = _make_object_hit("a")
    view._hit_object_resize_handle_index = lambda scene_pos: 2
    view._object_resize_pending = False
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    assert view._calls == []


def test_press_on_the_rotate_handle_does_no_lookup(monkeypatch):
    view = _pending_view(monkeypatch, [OBJECT_LOOKUP_PENDING])
    view._selected_object_info = _make_object_hit("a", kind="textbox")
    view._hit_object_resize_handle_index = lambda scene_pos: -1
    view._point_hits_object_rotate_handle = lambda scene_pos: True
    view._supports_free_rotate = lambda info: True
    view._center = None
    view._object_center_scene = lambda info: QPointF(0.0, 0.0)
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    assert view._calls == []


def test_delete_on_a_cold_page_is_refused_by_the_view_and_keeps_the_selection(monkeypatch):
    view = _pending_view(monkeypatch, [_make_object_hit("t", kind="table", page_num=1)])
    asked = []
    view.controller.object_op_ready = lambda pages, kinds: asked.append((list(pages), list(kinds))) or False
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    assert view._selected_object_info is not None
    assert pdf_view.PDFView._delete_selected_object(view) is False
    assert asked == [([1], ["table"])]
    assert view.sig_delete_object.emitted == []
    assert view._selected_object_info is not None


def test_delete_goes_ahead_when_the_controller_says_ready(monkeypatch):
    view = _pending_view(monkeypatch, [_make_object_hit("t", kind="table", page_num=1)])
    view.controller.object_op_ready = lambda pages, kinds: True
    pdf_view.PDFView._mouse_press(view, _FakeEvent(10, 10))
    assert pdf_view.PDFView._delete_selected_object(view) is True
    assert len(view.sig_delete_object.emitted) == 1


# --------------------------------------------------------------------------- view: context menu


def test_context_menu_pending_lookup_shows_one_disabled_entry_and_selects_nothing(qapp, monkeypatch):
    view = pdf_view.PDFView()
    try:
        view.current_mode = "browse"
        view.controller = SimpleNamespace(lookup_object_at_point=lambda page, point: OBJECT_LOOKUP_PENDING)
        view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(1, 1))
        view._resolve_text_info_for_context_menu_pos = lambda pos: None
        assert view._resolve_object_info_for_context_menu_pos(view.graphics_view.rect().center()) == "pending"
        shown = []
        monkeypatch.setattr(
            pdf_view.QMenu, "exec_",
            lambda self, *a, **k: shown.extend((x.text(), x.isEnabled()) for x in self.actions()),
        )
        view._show_context_menu(view.graphics_view.rect().center())
        assert ("正在分析此頁物件…", False) in shown
        assert "Delete Object" not in [text for text, _ in shown]
        assert view._selected_object_info is None
    finally:
        view.close()


def test_context_menu_pending_lookup_hides_object_actions_of_an_older_selection(qapp, monkeypatch):
    """D6: a right-click on a cold spot while another object is selected offers no
    Delete/Rotate Object (they would act on the old selection), keeps the selection, and
    the answer arriving later does not reopen the menu."""
    view = pdf_view.PDFView()
    try:
        view.current_mode = "objects"
        old = _make_object_hit("old", kind="textbox", page_num=1)  # supports delete and rotate
        view._selected_object_info = old
        view.controller = SimpleNamespace(lookup_object_at_point=lambda page, point: OBJECT_LOOKUP_PENDING)
        view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(1, 1))
        view._resolve_text_info_for_context_menu_pos = lambda pos: None
        shown = []
        opened = []

        def fake_exec(self, *a, **k):
            opened.append(True)
            shown.extend((x.text(), x.isEnabled()) for x in self.actions())

        monkeypatch.setattr(pdf_view.QMenu, "exec_", fake_exec)
        view._show_context_menu(view.graphics_view.rect().center())
        texts = [text for text, _ in shown]
        assert ("正在分析此頁物件…", False) in shown
        assert "Delete Object" not in texts and "Rotate Object" not in texts
        assert view._selected_object_info is old
        view.resolve_pending_object_click(1)
        assert len(opened) == 1
    finally:
        view.close()


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
    log = SimpleNamespace(status=[], resolved=[], dropped=[])
    view.set_status_bar_override_message = log.status.append
    view.resolve_pending_object_click = log.resolved.append
    view.drop_pending_object_click = lambda page=None: log.dropped.append(True)
    return view, controller, stub, log


def test_controller_construction_starts_no_process(qapp):
    from controller.pdf_controller import PDFController
    from test_scripts.qt_teardown import dispose_pdf_view

    qapp._pdf_object_probe = None
    m = PDFModel()
    view = pdf_view.PDFView()
    controller = PDFController(m, view)
    try:
        assert getattr(qapp, "_pdf_object_probe", None) is None
        assert controller._object_probe._runner is None
    finally:
        dispose_pdf_view(view, controller, m)


def test_cold_lookup_is_pending_starts_a_job_and_says_so(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        info = controller.lookup_object_at_point(1, fitz.Point(170, 245))
        assert info is OBJECT_LOOKUP_PENDING
        assert len(stub.jobs) == 1
        assert log.status == ["正在背景分析此頁的表格，完成後會自動選取…"]
    finally:
        dispose_pdf_view(view, controller, model)


UNSUPPORTED_TEXT = "此平台尚未支援受記憶體限制保護的物件分析，此功能目前無法使用。"


@pytest.fixture
def unsupported(monkeypatch):
    from utils import object_probe_platform

    monkeypatch.setattr(object_probe_platform, "contained_probe_supported", lambda: False)


def test_unsupported_platform_tables_say_so_start_no_job_and_leave_no_pending_click(
    qapp, model, monkeypatch, unsupported
):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        info = controller.lookup_object_at_point(1, fitz.Point(170, 245))
        assert info is None  # never PENDING: the view stores no click
        assert stub.jobs == {}
        assert log.status == [UNSUPPORTED_TEXT]
        assert "稍後" not in UNSUPPORTED_TEXT
        assert table_objects.cached_table_rects(model, 1) is None  # no empty result cached
        assert not table_objects.table_analysis_failed(model, 1)
        assert controller.object_op_ready([1], ["table"]) is False
        assert log.status[-1] == UNSUPPORTED_TEXT
        assert stub.jobs == {}
        assert controller.object_op_ready([1], ["rect"]) is True
    finally:
        dispose_pdf_view(view, controller, model)


def test_unsupported_platform_coordinator_submits_nothing(model, unsupported):
    runner = StubRunner()
    _coordinator(model, runner).request_tables(1)
    assert runner.jobs == {}


def test_unsupported_platform_answer_reports_its_own_reason(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        stub.complete(stub.order[0], {"v": 2, "status": "unsupported_platform"})
        assert log.status[-1] == UNSUPPORTED_TEXT
        assert log.dropped == [True]
        assert table_objects.cached_table_rects(model, 1) is None
        assert not table_objects.table_analysis_failed(model, 1)
    finally:
        dispose_pdf_view(view, controller, model)


def test_answer_clears_the_message_and_resolves_the_pending_click(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        stub.complete(stub.order[0], _complete([TABLE_RECT]))
        assert log.status[-1] is None
        assert log.resolved == [1]
        info = controller.lookup_object_at_point(1, fitz.Point(170, 245))
        assert isinstance(info, ObjectHitInfo) and info.object_kind == "table"
    finally:
        dispose_pdf_view(view, controller, model)


def test_failed_probe_reports_the_page_and_drops_the_click(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(2, fitz.Point(170, 245))
        stub.fail(stub.order[0])
        stub.fail(stub.order[1])
        assert log.status[-1] == "此頁的物件分析未完成（第 2 頁）"
        assert log.dropped == [True]
    finally:
        dispose_pdf_view(view, controller, model)


def _controller_with_the_real_pending_click(qapp, model, monkeypatch):
    """``_controller`` without the pending-click doubles: the view's own click bookkeeping runs."""
    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    del view.drop_pending_object_click, view.resolve_pending_object_click
    view.current_mode = "objects"
    return view, controller, stub, log, view._ensure_object_selection_manager()


def test_a_late_failure_for_an_old_page_keeps_the_newer_pages_pending_click(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log, mgr = _controller_with_the_real_pending_click(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))  # page 1's job runs
        controller.lookup_object_at_point(2, fitz.Point(170, 245))  # page 2's job waits
        mgr._store_pending_object_click(2, 170.0, 245.0, False)  # the click now waiting is page 2's
        page_one, page_two = stub.order
        stub.complete(page_one, {"v": 2, "status": "analysis_failed"})  # page 1 ends late
        assert mgr._pending_object_click is not None and mgr._pending_object_click.page_num == 2
        stub.complete(page_two, {"v": 2, "status": "analysis_failed"})
        assert mgr._pending_object_click is None
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_failure_for_the_page_of_the_pending_click_still_drops_it(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log, mgr = _controller_with_the_real_pending_click(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        mgr._store_pending_object_click(1, 170.0, 245.0, False)
        stub.complete(stub.order[0], {"v": 2, "status": "resource_limited"})
        assert mgr._pending_object_click is None
        assert log.status[-1].startswith("此頁圖形過多")
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize(
    "answer,text",
    [
        (
            {"v": 2, "status": "resource_limited"},
            "此頁圖形過多，表格分析超出記憶體上限而未完成；此頁的表格目前無法選取或刪除（線條等其他物件不受影響）",
        ),
        ({"v": 2, "status": "no_headroom"}, "目前可用記憶體不足，暫時無法分析此頁的表格，請稍後再操作一次"),
        ({"v": 2, "status": "analysis_failed"}, "此頁的物件分析未完成（第 1 頁）"),
        ({"v": 2, "status": "containment_failed"}, "此頁的物件分析未完成（第 1 頁）"),
    ],
)
def test_status_text_depends_on_the_reason_and_the_click_is_dropped(qapp, model, monkeypatch, answer, text):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        stub.complete(stub.order[0], answer)
        assert log.status[-1] == text
        assert log.dropped == [True]
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("status", ["analysis_failed", "containment_failed"])
def test_analysis_failed_message_does_not_claim_cause(qapp, model, monkeypatch, status):
    """D2: an untyped failure says only that the page's analysis did not complete."""
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        stub.complete(stub.order[0], {"v": 2, "status": status})
        message = log.status[-1]
        assert "未完成" in message
        assert "失敗" not in message and "記憶體" not in message
    finally:
        dispose_pdf_view(view, controller, model)


def test_object_op_ready_refuses_a_table_on_a_failed_page_and_requests_nothing(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        stub.complete(stub.order[0], {"v": 2, "status": "analysis_failed"})
        jobs_before = len(stub.order)
        assert controller.object_op_ready([1], ["table"]) is False
        assert log.status[-1] == "此頁的表格分析未完成，無法操作表格"
        assert len(stub.order) == jobs_before
        assert controller.object_op_ready([1], ["rect"]) is True
    finally:
        dispose_pdf_view(view, controller, model)


def test_object_op_ready_is_false_for_a_cold_table_and_true_otherwise(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        assert controller.object_op_ready([1], ["rect"]) is True
        assert stub.jobs == {}
        assert controller.object_op_ready([1], ["table"]) is False
        assert len(stub.jobs) == 1
        assert log.status[-1] == "正在分析此頁的表格，完成後請再操作一次"
        stub.complete(stub.order[0], _complete([TABLE_RECT]))
        assert controller.object_op_ready([1], ["table"]) is True
    finally:
        dispose_pdf_view(view, controller, model)


def test_delete_of_a_table_on_a_cold_page_is_refused_without_dialog_or_change(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    errors = []
    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: errors.append(a))
    try:
        text_before = model.doc[0].get_text()
        request = DeleteObjectRequest(
            object_id=table_objects.table_object_id(1, fitz.Rect(*TABLE_RECT)), object_kind="table", page_num=1
        )
        controller.delete_object(request)
        assert errors == []
        assert model.doc[0].get_text() == text_before
        assert len(stub.jobs) == 1
        stub.complete(stub.order[0], _complete([TABLE_RECT]))
        controller.delete_object(request)  # the repeated gesture
        assert "R1C1" not in model.doc[0].get_text()
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("hook", ["release_render_owner", "on_tab_changed", "on_tab_close_requested"])
def test_tab_and_owner_hooks_cancel_the_probe_jobs(qapp, model, monkeypatch, hook):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        cancelled = []
        controller._object_probe.cancel_all = lambda: cancelled.append(True)
        args = () if hook == "release_render_owner" else (0,)
        try:
            getattr(controller, hook)(*args)
        except Exception:
            pass  # only the cancel call matters here
        assert cancelled
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- card D12: stale answers (C)

LOOKUP_MSG = "正在背景分析此頁的表格，完成後會自動選取…"
REFUSED_MSG = "正在分析此頁的表格，完成後請再操作一次"


def _start_pending_tables(controller, origin: str) -> str:
    if origin == "lookup":
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        return LOOKUP_MSG
    assert controller.object_op_ready([1], ["table"]) is False
    return REFUSED_MSG


@pytest.mark.parametrize("origin", ["lookup", "op"])
@pytest.mark.parametrize(
    "outcome", ["complete", "analysis_failed", "resource_limited", "containment_failed", "no_headroom", "crash"]
)
def test_stale_tables_answer_clears_pending_status_when_no_tables_job_pending(
    qapp, model, monkeypatch, origin, outcome
):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        text = _start_pending_tables(controller, origin)
        assert log.status[-1] == text
        model.doc[0].set_rotation(90)  # the page frame changes: the answer is stale
        job = stub.order[0]
        if outcome == "crash":
            stub.fail(job)
        elif outcome == "complete":
            stub.complete(job, _complete([TABLE_RECT]))
        else:
            stub.complete(job, {"v": 2, "status": outcome})
        assert log.status[-1] is None
        assert log.dropped == [True]
        assert stub.order == [job]  # no retry
    finally:
        dispose_pdf_view(view, controller, model)


def test_keeps_status_while_a_newer_tables_job_is_pending(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        controller.lookup_object_at_point(2, fitz.Point(170, 245))  # the newer job waits
        assert log.status[-1] == LOOKUP_MSG
        model.doc[0].set_rotation(90)
        stub.complete(stub.order[0], _complete([TABLE_RECT]))  # page 1: stale
        assert log.status[-1] == LOOKUP_MSG
        assert log.dropped == []
        stub.complete(stub.order[1], _complete([TABLE_RECT]))
        assert log.status[-1] is None and log.resolved == [2]
    finally:
        dispose_pdf_view(view, controller, model)


def test_never_clears_a_non_pending_status(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, fitz.Point(170, 245))
        controller._set_object_status("此頁的物件分析未完成（第 2 頁）")
        model.doc[0].set_rotation(90)
        stub.complete(stub.order[0], _complete([TABLE_RECT]))
        assert log.status[-1] == "此頁的物件分析未完成（第 2 頁）"
        assert log.dropped == []
    finally:
        dispose_pdf_view(view, controller, model)
