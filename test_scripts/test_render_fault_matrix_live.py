from __future__ import annotations

import time

import pytest

from controller.page_render_coordinator import PageRenderCoordinator
from src.render_worker.process_pool import RenderProcessPool

pytest_plugins = ('test_scripts.test_search_jump_highlight',)


def wait(qapp, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.002)
    return predicate()


def _build_live(mvc, pdf_path, qapp, monkeypatch, wait_ready=True, **pool_kwargs):
    model, view, controller = mvc
    controller.open_pdf(str(pdf_path))
    controller._page_render_coordinator.wait_for_done()
    pool = RenderProcessPool(qapp, **pool_kwargs)
    owner = pool.register_owner()
    controller._render_client = pool
    controller._render_owner = owner
    controller._page_render_coordinator = PageRenderCoordinator(
        result_consumer=controller._consume_page_render_image,
        failure_consumer=controller._on_page_render_failed,
        identity_matches=controller._page_render_identity_matches,
        backend=pool, owner=owner, parent=view)
    sid = model.get_active_session_id()
    model.tools.watermark.add_watermark(pages=[1, 2], text='Matrix', opacity=.4)
    controller._bump_render_revision(sid)
    controller._drop_render_cache_for_session(sid)
    notices = []
    monkeypatch.setattr(controller, '_show_notice_feedback', notices.append)
    pool.start()
    if wait_ready:
        assert wait(qapp, lambda: pool.ready)
    return model, view, controller, pool, notices


@pytest.fixture
def live(mvc, pdf_path, qapp, monkeypatch):
    values = _build_live(mvc, pdf_path, qapp, monkeypatch)
    pool = values[3]
    yield values
    pool.shutdown()
    wait(qapp, lambda: not pool.has_live_processes)


@pytest.fixture
def live_clocked(mvc, pdf_path, qapp, monkeypatch):
    """A real child whose job-deadline clock the test controls, so a timeout needs no 120 s wait."""
    from src.render_worker.process_client import RenderProcessClient

    clock = [time.monotonic()]
    values = _build_live(
        mvc, pdf_path, qapp, monkeypatch,
        client_factory=lambda parent, **kw: RenderProcessClient(parent, monotonic=lambda: clock[0], **kw))
    pool = values[3]
    yield (*values, clock)
    pool.shutdown()
    wait(qapp, lambda: not pool.has_live_processes)


def _current_page_job(controller, child):
    active = controller._page_render_coordinator._active
    return bool(active is not None and controller._page_render_coordinator._is_current(active.identity)
                and child._active is not None
                and child._active.job_id == active.identity.token and child._active.kind == 'page')


def _quality(controller, page):
    sid = controller.model.get_active_session_id()
    return controller._page_quality_map(sid).get(page)


def test_live_single_page_child_crash_quarantines_that_page_and_others_still_render(live, qapp, monkeypatch):
    model, view, controller, pool, notices = live
    view.continuous_pages = False
    monkeypatch.setattr(model, 'get_page_pixmap',
                        lambda *a, **k: pytest.fail('GUI raster during fault matrix'))
    controller.show_page(1)
    child = pool.children[0]
    assert wait(qapp, lambda: _current_page_job(controller, child) and child._active.page_index == 1)
    child._process.kill()
    assert wait(qapp, lambda: bool(notices))
    assert '第 2 頁' in notices[0]
    assert controller._raster_quarantined(model.get_active_session_id(), 1)
    controller.show_page(1)
    assert _quality(controller, 1) != 'high'
    controller.show_page(2)
    assert wait(qapp, lambda: _quality(controller, 2) == 'high')


def test_live_close_during_pending_render_never_paints_and_returns_credits(live, qapp):
    model, view, controller, pool, notices = live
    view.continuous_pages = False
    controller.show_page(1)
    controller._release_render_session(model.get_active_session_id())
    wait(qapp, lambda: not controller._page_render_coordinator.has_active_job, timeout=10)
    assert not notices
    assert wait(qapp, lambda: not pool._credits)


def test_live_continuous_child_crash_quarantines_only_the_lost_page(live, qapp, monkeypatch):
    model, view, controller, pool, notices = live
    sid = model.get_active_session_id()
    monkeypatch.setattr(model, 'get_page_pixmap',
                        lambda *a, **k: pytest.fail('GUI raster during fault matrix'))
    child = pool.children[0]
    controller._schedule_visible_render(sid, immediate_page_idx=0)
    assert wait(qapp, lambda: _current_page_job(controller, child))
    lost = child._active.page_index
    child._process.kill()
    assert wait(qapp, lambda: bool(notices))
    assert f'第 {lost + 1} 頁' in notices[0]
    assert controller._raster_quarantined(sid, lost)
    other = next(p for p in range(len(model.doc)) if p != lost and not controller._raster_quarantined(sid, p))
    assert wait(qapp, lambda: not child._disabled and child.ready)
    assert not controller._raster_quarantined(sid, other)
    controller._schedule_visible_render(sid, immediate_page_idx=other)
    assert wait(qapp, lambda: _quality(controller, other) is not None)


def test_live_single_page_timeout_notifies_skips_that_page_and_the_child_recovers(live_clocked, qapp, monkeypatch):
    model, view, controller, pool, notices, clock = live_clocked
    view.continuous_pages = False
    monkeypatch.setattr(model, 'get_page_pixmap',
                        lambda *a, **k: pytest.fail('GUI raster during fault matrix'))
    child = pool.children[0]
    # The real child stays alive but never receives the raster command, so the job is
    # reliably still active when the deadline clock jumps (a tiny page would finish first).
    monkeypatch.setattr(child, '_render', lambda: None)
    controller.show_page(1)
    assert wait(qapp, lambda: _current_page_job(controller, child) and child._active.page_index == 1)
    first_process = child._process
    clock[0] += 121
    assert wait(qapp, lambda: bool(notices))
    del child._render
    assert '第 2 頁' in notices[0] and '逾時' in notices[0]
    assert child.metrics['starts'] >= 1
    assert wait(qapp, lambda: child._process is not first_process and pool.ready)
    controller.show_page(2)
    assert wait(qapp, lambda: _quality(controller, 2) == 'high')
    assert not controller._raster_quarantined(model.get_active_session_id(), 1), 'a timeout is not a crash'


def test_live_child_that_cannot_start_falls_back_with_a_counted_reason_and_the_app_stays_usable(
        mvc, pdf_path, qapp, monkeypatch):
    from src.render_worker.process_client import RenderProcessClient

    model, view, controller, pool, notices = _build_live(
        mvc, pdf_path, qapp, monkeypatch, wait_ready=False,
        client_factory=lambda parent, **kw: RenderProcessClient(
            parent, python_executable='no-such-python-executable', **kw))
    try:
        view.continuous_pages = False
        controller.show_page(1)
        assert wait(qapp, lambda: _quality(controller, 1) == 'high', timeout=30)
        assert pool.unavailable
        assert pool.metrics['fallbacks'] >= 1
        assert set(pool.metrics['fallback_reasons']) <= {'failed_to_start', 'setup_failed', 'disabled_or_closing', 'all_children_disabled'}
        assert not notices, 'a fallback that still renders needs no user notice'
        controller.show_page(2)
        assert wait(qapp, lambda: _quality(controller, 2) == 'high', timeout=30)
    finally:
        pool.shutdown()
        wait(qapp, lambda: not pool.has_live_processes)
