from __future__ import annotations

import fitz
import pytest
import time
import ast
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from controller.page_render_coordinator import PageRenderCoordinator
from src.render_worker.process_client import DocSource, JobOutcome
from src.render_worker.outcomes import RenderTimedOut, RenderTransportLost
from controller.pdf_controller import PDFController


class Backend(QObject):
    job_done = Signal(str, object)
    ready = True

    def __init__(self):
        super().__init__()
        self.jobs = []
        self.metrics = {'fallbacks': 0}

    def submit(self, job):
        self.jobs.append(job)

    def cancel(self, key):
        self.job_done.emit(key, JobOutcome('cancelled'))


def snapshot():
    with fitz.open() as doc:
        doc.new_page(width=50, height=50)
        return doc.tobytes()


def request(coordinator, **extra):
    return coordinator.request(session_id='s', generation=1, revision=1, page_index=0,
                               quality='high', rendered_scale=1., target_scale=1.,
                               color_profile='srgb', device_pixel_ratio=1.,
                               document=DocSource('s@1', None, snapshot), **extra)


@pytest.mark.parametrize('quality,expected', [('low', False), ('high', True)])
def test_only_required_high_quality_is_promotion_eligible(qapp, quality, expected):
    backend = Backend()
    coordinator = PageRenderCoordinator(result_consumer=lambda *args: None,
        failure_consumer=lambda *args: None, identity_matches=lambda identity: True,
        backend=backend, owner='owner')
    coordinator.request(session_id='s', generation=5, revision=1, page_index=0,
                        quality=quality, rendered_scale=1., target_scale=1.,
                        color_profile='srgb', device_pixel_ratio=1.,
                        document=DocSource('s@1', None, snapshot))
    assert backend.jobs[-1].promotion_allowed is expected
    assert backend.jobs[-1].foreground_intent == '5'
    coordinator.cancel()


def test_latest_pending_process_and_stale_result(qapp):
    backend = Backend()
    results = []
    coordinator = PageRenderCoordinator(result_consumer=lambda *args: results.append(args),
        failure_consumer=lambda *args: None, identity_matches=lambda ident: True,
        backend=backend, owner='owner')
    old = request(coordinator)
    current = request(coordinator)
    assert coordinator.active_token == current
    backend.job_done.emit(old, JobOutcome('image', QImage(1, 1, QImage.Format_RGB888)))
    assert not results
    backend.job_done.emit(current, JobOutcome('image', QImage(1, 1, QImage.Format_RGB888)))
    assert len(results) == 1
    assert not coordinator.has_active_job


def test_page_image_credit_is_returned_after_consumer(qapp):
    backend = Backend()
    order = []
    backend.result_consumed = lambda token: order.append(('consumed', token))
    coordinator = PageRenderCoordinator(
        result_consumer=lambda identity, image: order.append(('applied', identity.token)),
        failure_consumer=lambda *args: None, identity_matches=lambda ident: True,
        backend=backend, owner='owner')
    token = request(coordinator)
    backend.job_done.emit(token, JobOutcome('image', QImage()))
    assert order == [('applied', token), ('consumed', token)]


def test_capacity_defers_page_without_selecting_thread(qapp):
    from PySide6.QtTest import QTest

    backend = Backend()
    coordinator = PageRenderCoordinator(
        result_consumer=lambda *args: pytest.fail('not rendered yet'),
        failure_consumer=lambda *args: pytest.fail('capacity is not a native error'),
        identity_matches=lambda ident: True, backend=backend, owner='owner')
    token = request(coordinator)
    backend.job_done.emit(token, JobOutcome('capacity'))
    QTest.qWait(130)
    assert [job.job_id for job in backend.jobs] == [token, token]
    assert backend.metrics['fallbacks'] == 0
    coordinator.cancel()


def test_stale_batch_callback_cannot_clear_new_generation_pending(qapp):
    with fitz.open() as document:
        document.new_page()
        controller = SimpleNamespace(
            model=SimpleNamespace(get_active_session_id=lambda: 'session', doc=document),
            view=SimpleNamespace(continuous_pages=True),
            _render_gen_by_session={'session': 2},
            _render_batch_pending_by_session={'session': True},
        )
        PDFController._process_visible_render_batch(controller, 'session', 1)
        assert controller._render_batch_pending_by_session['session'] is True


def test_starting_backend_queues_without_gui_thread_fallback(qapp, monkeypatch):
    backend = Backend()
    backend.ready = False
    coordinator = PageRenderCoordinator(result_consumer=lambda *args: None,
        failure_consumer=lambda *args: None, identity_matches=lambda ident: True,
        backend=backend, owner='owner')
    monkeypatch.setattr(coordinator, '_start_thread',
                        lambda request: pytest.fail('startup must queue, not raster in App'))
    token = request(coordinator)
    assert [item.job_id for item in backend.jobs] == [token]
    backend.job_done.emit(token, JobOutcome('cancelled'))


def test_process_immediate_low_miss_never_rasterizes_in_App(qapp):
    controller = PDFController.__new__(PDFController)
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller.model = SimpleNamespace(doc=doc, get_active_session_id=lambda: 's',
            get_page_pixmap=lambda *a, **k: pytest.fail('low miss belongs in process'))
        controller.view = SimpleNamespace(scale=1., continuous_pages=True)
        controller._render_client = object()
        controller._raster_quarantined = lambda *args: False
        controller._color_profile_for_session = lambda sid: 'srgb'
        controller._page_quality_map = lambda *args: {}
        controller._get_cached_render = lambda *args: None
        controller.get_watermarks = lambda: []
        controller._render_batch_pending_by_session = {}
        controller._next_render_gen = lambda sid: 1
        controller._pause_thumbnails_for_visible_render = lambda sid: None
        controller._process_visible_render_batch = lambda *args: None
        controller._schedule_visible_render('s', immediate_page_idx=0)
        assert controller._render_batch_pending_by_session['s']
        qapp.processEvents()


@pytest.mark.parametrize('status', ['unavailable', 'oversize', 'error'])
def test_fallback_captures_once_and_completes(qapp, status):
    backend = Backend()
    results = []
    coordinator = PageRenderCoordinator(result_consumer=lambda *args: results.append(args),
        failure_consumer=lambda *args: None, identity_matches=lambda ident: True,
        backend=backend, owner='owner')
    token = request(coordinator)
    backend.job_done.emit(token, JobOutcome(status))
    deadline = time.monotonic() + 3
    while coordinator.has_active_job and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.001)
    assert not coordinator.has_active_job
    assert len(results) == 1
    assert backend.metrics['fallbacks'] == 1
    coordinator.wait_for_done()


def test_clean_document_lazy_source_and_revision_guard():
    controller = PDFController.__new__(PDFController)
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller.model = SimpleNamespace(doc=doc, password='secret',
            get_active_session_id=lambda: 's', session_has_unsaved_changes=lambda sid: False,
            get_session_meta=lambda sid: {'path': str(Path(__file__))})
        controller._render_revision_by_session = {'s': 1}
        captures = []
        controller.capture_worker_snapshot_bytes = lambda: captures.append('capture') or snapshot()
        source = controller._render_document_source('s')
        assert source.file is not None and not captures
        assert source.is_current()
        controller._render_revision_by_session['s'] = 2
        assert not source.is_current()
        assert source.snapshot_provider() is None and not captures


@pytest.mark.parametrize('error,quarantine', [(RenderTransportLost(), True), (RenderTimedOut(), False)])
def test_crash_quarantine_persists_but_timeout_only_skips(qapp, error, quarantine):
    controller = PDFController.__new__(PDFController)
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller.model = SimpleNamespace(doc=doc)
        controller.view = SimpleNamespace(scale=1.)
        controller._raster_quarantine = set()
        controller._render_skips = set()
        controller._render_revision_by_session = {'s': 1}
        controller._page_render_identity_matches = lambda identity: True
        controller._process_visible_render_batch = lambda *args: None
        identity = SimpleNamespace(session_id='s', generation=1, page_index=0, quality='high')
        controller._on_page_render_failed(identity, error)
        controller._render_revision_by_session['s'] = 2
        assert controller._raster_quarantined('s', 0) is quarantine
        assert bool(controller._render_skips) is not quarantine
        qapp.processEvents()


def test_all_gui_raster_sites_have_quarantine_guard():
    source = Path('controller/pdf_controller.py').read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = ast.get_source_segment(source, node)
            if 'self.model.get_page_pixmap(' in body or 'self.model.get_thumbnail(' in body:
                sites.append(node.name)
                assert '_raster_quarantined(' in body, node.name
    assert len(sites) == 5


def test_accepted_close_releases_owner_before_view_destruction():
    controller = PDFController.__new__(PDFController)
    released = []
    controller._render_client = SimpleNamespace(release_owner=lambda owner: released.append(owner))
    controller._render_owner = 'window'
    controller._page_render_coordinator = SimpleNamespace(cancel=lambda: None)
    controller._end_text_edit_plan_preview_session = lambda: None
    event = SimpleNamespace(accept=lambda: released.append('accepted'))
    controller._accept_app_close(event)
    assert released == ['window', 'accepted']


def test_owner_release_never_starts_pending_thread_during_shutdown(qapp):
    backend = Backend()
    coordinator = PageRenderCoordinator(result_consumer=lambda *args: None,
        failure_consumer=lambda *args: None, identity_matches=lambda ident: True,
        backend=backend, owner='window')
    token = request(coordinator)
    coordinator._pending = coordinator._active
    backend.job_done.emit(token, JobOutcome('owner_released'))
    assert not coordinator.has_active_job


def test_session_departure_sites_release_renderer_document():
    tree = ast.parse(Path('controller/pdf_controller.py').read_text(encoding='utf-8-sig'))
    sites = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            text = ast.unparse(node)
            if 'self.model.close_session(' in text:
                sites += 1
                assert 'self._release_render_session(' in text, node.name
    assert sites == 2
