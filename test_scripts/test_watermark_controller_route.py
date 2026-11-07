from __future__ import annotations

import json
import time
from types import SimpleNamespace

import fitz
import pytest

from controller.pdf_controller import PDFController
from controller.page_render_coordinator import PageRenderCoordinator
from model.page_raster import rasterize_page
from src.render_worker.process_client import DocSource, JobOutcome
from test_scripts.test_page_render_process import Backend, snapshot
from test_scripts.test_watermark_worker_route import recipe
from utils.helpers import qimage_from_samples


def controller_for(doc):
    controller = PDFController.__new__(PDFController)
    overlay = json.loads(recipe())
    controller.model = SimpleNamespace(doc=doc, password='', get_active_session_id=lambda: 's',
        session_has_unsaved_changes=lambda sid: False,
        get_session_meta=lambda sid: {'path': __file__},
        get_print_watermarks=lambda: overlay)
    controller.get_watermarks = lambda: overlay
    data = snapshot()
    controller.capture_worker_snapshot_bytes = lambda: data
    controller._render_revision_by_session = {'s': 1}
    controller._render_client = object()
    return controller


def test_watermarked_clean_source_is_unbaked_snapshot_not_file():
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller = controller_for(doc)
        source = controller._render_document_source('s')
        assert source.file is None
        assert json.loads(source.watermarks_json) == json.loads(recipe())
        assert source.snapshot_provider() == controller.capture_worker_snapshot_bytes()
        controller._render_revision_by_session['s'] = 2
        assert not source.is_current() and source.snapshot_provider() is None


def test_watermarked_thumbnail_source_is_eligible():
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller = controller_for(doc)
        controller._thumbnail_identity_matches = lambda *args: True
        request = SimpleNamespace(session_id='s', generation=1)
        assert controller._thumbnail_process_source(request) is not None


def test_overlay_process_failure_thread_uses_same_frozen_pair(qapp):
    overlay = recipe().encode()
    data = snapshot()
    document = DocSource('s@1', None, lambda: data, watermarks_json=overlay)
    backend = Backend()
    images, errors = [], []
    coordinator = PageRenderCoordinator(result_consumer=lambda identity, image: images.append(image),
        failure_consumer=lambda identity, error: errors.append(error), identity_matches=lambda identity: True,
        backend=backend, owner='owner')
    try:
        token = coordinator.request(session_id='s', generation=1, revision=1, page_index=0,
            quality='high', rendered_scale=1.25, target_scale=1.25, color_profile='srgb',
            device_pixel_ratio=1., document=document)
        backend.job_done.emit(token, JobOutcome('unavailable'))
        deadline = time.monotonic() + 3
        while coordinator.has_active_job and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(.001)
        assert not coordinator.has_active_job and not errors
        with fitz.open(stream=data, filetype='pdf') as expected_doc:
            expected = rasterize_page(expected_doc, 0, 1.25, 'srgb', watermarks_json=overlay)
        assert images == [qimage_from_samples(expected.samples, expected.width, expected.height,
                                              expected.stride, expected.alpha)]
    finally:
        coordinator.wait_for_done()


def test_current_recipe_alone_cannot_force_gui_immediate_raster(qapp):
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller = controller_for(doc)
        controller.view = SimpleNamespace(continuous_pages=True)
        controller._color_profile_for_session = lambda sid: 'srgb'
        controller._page_quality_map = lambda *args: {}
        choices = []
        controller._render_page_into_scene = lambda *args, **kwargs: choices.append(kwargs['allow_raster'])
        controller._render_batch_pending_by_session = {'s': True}
        controller._schedule_visible_render('s', immediate_page_idx=0)
        assert choices == [False]


@pytest.mark.parametrize('failure', [False, True])
def test_save_attempt_invalidates_old_frozen_source_even_after_failure(failure):
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller = controller_for(doc)
        controller._worker_snapshot_cache = ('s', 1, b'cached')
        controller._page_render_quality_by_session = {'s': {0: 'high'}}
        controller._cancel_page_render_for_session = lambda *args, **kwargs: None
        controller._drop_render_cache_for_session = lambda *args: None
        controller._invalidate_inline_editor_preview = lambda: None
        controller.view = SimpleNamespace(continuous_pages=True)
        controller._page_render_coordinator = object()
        scheduled = []
        controller._schedule_visible_render = scheduled.append
        old = controller._render_document_source('s')

        def save():
            if failure:
                raise RuntimeError('save failed after maintenance')

        if failure:
            with pytest.raises(RuntimeError):
                controller._save_with_signature_consent(save)
        else:
            assert controller._save_with_signature_consent(save)
        assert not old.is_current()
        assert old.snapshot_provider() is None
        assert controller._worker_snapshot_cache is None
        assert controller._render_revision('s') == 2
        assert scheduled == ['s'], 'save invalidation must restart visible high-quality rendering'


def test_rejected_overlay_process_recipe_cannot_fall_back_to_bare_disk_thumbnail():
    with fitz.open(stream=snapshot(), filetype='pdf') as doc:
        controller = controller_for(doc)
        controller.model.get_print_watermarks = lambda: json.loads(recipe()) * 129
        controller._thumbnail_identity_matches = lambda *args: True
        request = SimpleNamespace(session_id='s', generation=1)
        assert controller._thumbnail_process_source(request) is None
        assert controller._resolve_thumbnail_file_source(request) is None
