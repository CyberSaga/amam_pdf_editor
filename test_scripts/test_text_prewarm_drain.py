"""A6.6: Edit Text prewarm, the stale drain and undo/redo never build a child-routed page on the GUI thread.

Prewarm asks ``controller.request_page_index`` for one visible page per event-loop slot; the stale
drain handles one inline-routed page per slot and never starts a child job; a snapshot restore
leaves child-routed pages for the gesture / prewarm path to request.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTimer

from model import text_index_jobs
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view
from test_scripts.test_object_probe import _controller
from test_scripts.test_text_index_gate import FrontStub, _answer_for, _text_pdf
from utils import object_probe_platform

PAGES = 3


@pytest.fixture
def model(tmp_path):
    m = PDFModel()
    m.open_pdf(_text_pdf(tmp_path / "t.pdf", pages=PAGES))
    m.block_manager.clear()  # cold
    yield m
    m.close()


@pytest.fixture(autouse=True)
def _contained(monkeypatch):
    monkeypatch.setattr(object_probe_platform, "contained_probe_supported", lambda: True)


@pytest.fixture
def slots(monkeypatch):
    """Capture ``QTimer.singleShot`` callbacks so a test runs one event-loop slot at a time."""
    captured: list = []
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, fn: captured.append(fn)))
    # the view defers through utils.qt_deferred.call_later (a context-free singleShot is banned in view/)
    monkeypatch.setattr("view.pdf_view.call_later", lambda owner, ms, fn: captured.append(fn))
    return captured


def _count_builds(model, monkeypatch) -> list[int]:
    """Page numbers built through the model on this thread (ensure_page_index_built / build)."""
    built: list[int] = []
    manager_cls = type(model.block_manager)
    real_build = manager_cls._build_page_index

    def build(self, page_num, page):
        built.append(int(page_num))
        return real_build(self, page_num, page)

    monkeypatch.setattr(manager_cls, "_build_page_index", build)
    return built


def _rig(qapp, model, monkeypatch):
    view, controller, _stub, _log = _controller(qapp, model, monkeypatch)
    stub = FrontStub()
    controller._object_probe._runner = stub
    view.current_mode = "edit_text"
    view.total_pages = len(model.doc)
    view.visible_page_range = lambda prefetch=0: (0, len(model.doc) - 1)
    return view, controller, stub


def _run_slots(slots, limit: int = 40) -> int:
    ran = 0
    while slots and ran < limit:
        slots.pop(0)()
        ran += 1
    return ran


def _text_jobs(stub) -> list[int]:
    return [j for j in stub.order if stub.jobs[j][1] == "text"]


def test_edit_text_on_a_child_routed_document_builds_nothing_inline(qapp, model, monkeypatch, slots):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    built = _count_builds(model, monkeypatch)
    try:
        view._draw_all_block_outlines()
        _run_slots(slots)
        assert built == []
        jobs = _text_jobs(stub)
        assert len(jobs) == PAGES
        assert not any(stub.front[j] for j in jobs)
    finally:
        dispose_pdf_view(view, controller, model)


def test_text_index_ready_redraws_the_outlines(qapp, model, monkeypatch, slots):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    try:
        view._draw_all_block_outlines()
        _run_slots(slots)
        draws: list[int] = []
        view._draw_all_block_outlines = lambda *a: draws.append(1)
        job = _text_jobs(stub)[0]
        stub.complete(job, _answer_for(stub.jobs[job][2], 0))
        _run_slots(slots)
        assert len(draws) == 1, "a visible page's text_index_ready redraws the outlines, once per slot"
    finally:
        dispose_pdf_view(view, controller, model)


def test_prewarm_of_inline_pages_builds_at_most_one_page_per_slot(qapp, model, monkeypatch, slots):
    view, controller, stub = _rig(qapp, model, monkeypatch)
    built = _count_builds(model, monkeypatch)
    try:
        view._draw_all_block_outlines()
        assert built == []  # nothing in the event that entered the mode
        total = 0
        while slots and total < 20:
            before = len(built)
            slots.pop(0)()
            total += 1
            assert len(built) - before <= 1
        assert sorted(built) == [0, 1, 2]
        assert stub.jobs == {}
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_newer_prewarm_cancels_the_older_chain(qapp, model, monkeypatch, slots):
    view, controller, stub = _rig(qapp, model, monkeypatch)
    built = _count_builds(model, monkeypatch)
    try:
        view._draw_all_block_outlines()
        stale_slots = list(slots)
        slots.clear()
        view._draw_all_block_outlines()
        for fn in stale_slots:
            fn()
        assert built == []
    finally:
        dispose_pdf_view(view, controller, model)


def _mark_all_stale(model) -> None:
    model.block_manager.clear()
    for idx in range(len(model.doc)):
        model.block_manager._page_state[idx] = "stale"


def test_drain_starts_no_child_and_builds_nothing_for_child_routed_pages(qapp, model, monkeypatch, slots):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    monkeypatch.setattr(text_index_jobs, "TEXT_RESTORE_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    built = _count_builds(model, monkeypatch)
    try:
        _mark_all_stale(model)
        controller._schedule_stale_index_drain()
        _run_slots(slots)
        assert built == []
        assert stub.jobs == {}
        assert model.block_manager.list_stale_pages() == [0, 1, 2]
    finally:
        dispose_pdf_view(view, controller, model)


def test_drain_builds_one_inline_page_per_slot_and_skips_child_pages(qapp, model, monkeypatch, slots):
    real_route = text_index_jobs.restore_builds_inline
    monkeypatch.setattr(
        text_index_jobs, "restore_builds_inline", lambda m, p: p != 1 and real_route(m, p)
    )
    view, controller, stub = _rig(qapp, model, monkeypatch)
    built = _count_builds(model, monkeypatch)
    try:
        _mark_all_stale(model)
        controller._schedule_stale_index_drain()
        total = 0
        while slots and total < 20:
            before = len(built)
            slots.pop(0)()
            total += 1
            assert len(built) - before <= 1
        assert sorted(built) == [1, 2]  # 0-based pages 1 and 2; page 1 (index 0) is child-routed
        assert model.block_manager.list_stale_pages() == [0]
        assert stub.jobs == {}
    finally:
        dispose_pdf_view(view, controller, model)


def test_snapshot_restore_leaves_child_routed_pages_unbuilt(model, monkeypatch):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    monkeypatch.setattr(text_index_jobs, "TEXT_RESTORE_INLINE_LIMIT_BYTES", 0)
    built = _count_builds(model, monkeypatch)
    model.refresh_structural_indexes([1, 2])
    assert built == []
    assert model.block_manager.page_state(0) != "clean"


def _scratch_counter(monkeypatch) -> list[int]:
    from model import table_objects

    calls: list[int] = []
    real = table_objects.scratch_page_bytes

    def counted(doc, page_num):
        calls.append(page_num)
        return real(doc, page_num)

    monkeypatch.setattr(table_objects, "scratch_page_bytes", counted)
    return calls


def _answer_pending(stub, ok: bool = True) -> None:
    """Answer every text job still waiting (the page index of job n is the n-th page)."""
    for job in [j for j in stub.order if stub.jobs.get(j, (None, None))[1] == "text"]:
        payload = (
            _answer_for(stub.jobs[job][2], stub.order.index(job) % PAGES)
            if ok
            else {"v": 2, "status": "analysis_failed"}
        )
        stub.complete(job, payload)


def test_drain_and_restore_make_no_scratch_copy(qapp, model, monkeypatch, slots):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    monkeypatch.setattr(text_index_jobs, "TEXT_RESTORE_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    calls = _scratch_counter(monkeypatch)
    try:
        _mark_all_stale(model)
        controller._schedule_stale_index_drain()
        _run_slots(slots)
        model.refresh_structural_indexes([1, 2, 3])
        assert calls == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_snapshot_restore_still_rebuilds_small_hot_pages(model, monkeypatch):
    built = _count_builds(model, monkeypatch)
    model.refresh_structural_indexes([1, 2])
    assert sorted(built) == [0, 1]
    assert model.block_manager.page_state(0) == "clean"


def test_paragraph_mode_builds_nothing_inline_and_takes_one_page_per_slot(qapp, model, monkeypatch, slots):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    model.text_target_mode = "paragraph"
    built = _count_builds(model, monkeypatch)
    calls = _scratch_counter(monkeypatch)
    requests: list[int] = []
    real_request = controller.request_page_index
    controller.request_page_index = lambda page: requests.append(page) or real_request(page)
    try:
        view._draw_all_block_outlines()
        assert requests == [] and calls == [] and stub.jobs == {}  # the entry event itself does nothing
        ran = 0
        while slots and ran < 20:
            before = len(requests)
            slots.pop(0)()
            ran += 1
            assert len(requests) - before <= 1
        assert built == []
        assert len(_text_jobs(stub)) == PAGES
        assert not any(stub.front[j] for j in _text_jobs(stub))
    finally:
        dispose_pdf_view(view, controller, model)


def test_paragraph_ready_pages_draw_outlines_page_by_page(qapp, model, monkeypatch, slots):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    model.text_target_mode = "paragraph"
    try:
        view._draw_all_block_outlines()
        _run_slots(slots)
        _answer_pending(stub)
        _run_slots(slots)
        assert {key[0] for key in view._block_outline_items} == {0, 1, 2}
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_late_ready_in_browse_leaves_no_outline(qapp, model, monkeypatch, slots):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    model.text_target_mode = "paragraph"
    try:
        view._draw_all_block_outlines()
        _run_slots(slots)
        view.set_mode("browse")
        slots.clear()
        _answer_pending(stub)
        _run_slots(slots)
        assert view._block_outline_items == {}
    finally:
        dispose_pdf_view(view, controller, model)


def test_queued_prewarm_slots_do_not_request_after_a_tab_change_zoom_or_handle_change(
    qapp, model, monkeypatch, slots
):
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    try:
        view._draw_all_block_outlines()
        queued = list(slots)
        slots.clear()
        view.cancel_text_prewarm()  # what a tab change / zoom does
        for fn in queued:
            fn()
        assert stub.jobs == {}
        view._draw_all_block_outlines()  # a stamp change (another document handle) also ends a chain
        queued = list(slots)
        slots.clear()
        view._prewarm_stamp = ("another handle", -1)
        for fn in queued:
            fn()
        assert stub.jobs == {}
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_failed_prewarm_is_not_retried_and_the_page_stays_non_clean(qapp, model, monkeypatch, slots):
    """Accepted outcome (prewarm owns no click): the page stays non-clean until a gesture
    requests it; there is no retry."""
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    built = _count_builds(model, monkeypatch)
    try:
        view._draw_all_block_outlines()
        _run_slots(slots)
        jobs = len(_text_jobs(stub))
        _answer_pending(stub, ok=False)
        _run_slots(slots)
        assert built == []
        assert len(stub.order) == jobs  # no retry
        assert all(model.block_manager.page_state(i) != "clean" for i in range(PAGES))
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("target_mode", ["run", "paragraph"])
def test_event_loop_acceptance_across_undo_zoom_mode_exit_and_failure(qapp, model, monkeypatch, slots, target_mode):
    """Class check: at quiescence every visible Edit Text page is clean or has an explicit failure
    outcome, Browse keeps no edit outlines, every request belongs to the current handle, and no
    recorded callback exceeds a small budget on the stub."""
    import time

    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    monkeypatch.setattr(text_index_jobs, "TEXT_RESTORE_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, model, monkeypatch)
    model.text_target_mode = target_mode
    requests: list[tuple[int, tuple]] = []
    real_request = controller.request_page_index

    def request(page):
        requests.append((page, view._prewarm_stamp_now()))
        return real_request(page)

    controller.request_page_index = request
    durations: list[float] = []

    def settle():
        ran = 0
        while slots and ran < 80:
            fn = slots.pop(0)
            started = time.perf_counter()
            fn()
            durations.append(time.perf_counter() - started)
            ran += 1

    def clean_pages() -> list[str]:
        return [model.block_manager.page_state(i) for i in range(PAGES)]

    try:
        view._draw_all_block_outlines()
        settle()
        view.cancel_text_prewarm()  # a zoom / tab change while jobs run
        view._draw_all_block_outlines()
        settle()
        _answer_pending(stub)
        settle()
        assert clean_pages() == ["clean"] * PAGES
        assert (not view._block_outline_items) == (target_mode == "run")
        # an undo-like restore leaves the big pages unbuilt; the next pass requests them again
        model.refresh_structural_indexes([1, 2, 3])
        assert all(state != "clean" for state in clean_pages())
        view._draw_all_block_outlines()
        settle()
        _answer_pending(stub, ok=False)  # an explicit failure outcome: the pages stay non-clean
        settle()
        assert all(state != "clean" for state in clean_pages())
        # leaving Edit Text: a late answer draws nothing in Browse
        view.set_mode("browse")
        slots.clear()
        _answer_pending(stub)
        settle()
        assert view._block_outline_items == {}
        assert all(stamp == view._prewarm_stamp_now() for _page, stamp in requests)
        assert max(durations, default=0.0) < 0.1
    finally:
        dispose_pdf_view(view, controller, model)


def _distinct_pdf(path, pages: int, lines: int = 1) -> str:
    """Pages whose bytes differ (a key is by bytes) with ``lines`` lines of text each."""
    import fitz

    with fitz.open() as doc:
        for n in range(pages):
            page = doc.new_page(width=595, height=842)
            for row in range(lines):
                page.insert_text((20, 20 + row * 1.2), f"page {n} line {row} hello world", fontsize=1)
        doc.save(path)
    return str(path)


def test_restore_inline_threshold_is_size_only(model):
    assert text_index_jobs.TEXT_RESTORE_INLINE_LIMIT_BYTES == 8_192
    assert text_index_jobs.restore_builds_inline(model, 1)  # a tiny page


def test_prewarm_never_builds_a_failed_key_page_inline(qapp, tmp_path, monkeypatch, slots):
    """Two large visible pages: page 1's child fails, page 2's succeeds.  The ready redraw restarts
    prewarm, which must not build page 1 inline; only a gesture does."""
    m = PDFModel()
    m.open_pdf(_distinct_pdf(tmp_path / "d.pdf", 2))
    m.block_manager.clear()
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)
    view, controller, stub = _rig(qapp, m, monkeypatch)
    built = _count_builds(m, monkeypatch)
    try:
        view._draw_all_block_outlines()
        _run_slots(slots)
        first, second = _text_jobs(stub)
        stub.complete(first, {"v": 2, "status": "analysis_failed"})
        stub.complete(second, _answer_for(stub.jobs[second][2], 1))
        _run_slots(slots)  # the ready redraw restarts prewarm over both pages
        assert built == []
        assert m.block_manager.page_state(0) != "clean"
        assert m.block_manager.page_state(1) == "clean"
        assert controller.request_page_index(1) is False
        assert built == []
    finally:
        dispose_pdf_view(view, controller, m)
        m.close()


def test_restore_and_drain_never_build_a_slow_under_limit_page(qapp, tmp_path, monkeypatch, slots):
    """A page over the restore threshold but under the inline limit, its key marked slow: undo
    (snapshot restore) and the stale drain build nothing and make no scratch copy."""
    from model import table_objects

    m = PDFModel()
    m.open_pdf(_distinct_pdf(tmp_path / "s.pdf", 1, lines=500))
    cost = text_index_jobs.text_index_cost_bytes(m.doc, 1, 10**9)
    assert text_index_jobs.TEXT_RESTORE_INLINE_LIMIT_BYTES < cost < text_index_jobs.TEXT_INLINE_LIMIT_BYTES
    text_index_jobs.mark_slow(m, table_objects.PageInput(m, 1).key)
    m.block_manager.clear()
    view, controller, stub = _rig(qapp, m, monkeypatch)
    built = _count_builds(m, monkeypatch)
    calls = _scratch_counter(monkeypatch)
    try:
        m.refresh_structural_indexes([1])
        m.block_manager._page_state[0] = "stale"
        controller._schedule_stale_index_drain()
        _run_slots(slots)
        assert built == [] and calls == [] and stub.jobs == {}
        assert m.block_manager.page_state(0) != "clean"
    finally:
        dispose_pdf_view(view, controller, m)
        m.close()
