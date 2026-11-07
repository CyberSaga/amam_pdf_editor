from __future__ import annotations

import fitz
import pytest
from PySide6.QtGui import QImage

from controller.page_render_coordinator import PageRenderCoordinator
from src.render_worker.process_client import JobOutcome
from test_scripts.test_page_render_process import Backend

pytest_plugins = ('test_scripts.test_search_jump_highlight',)


@pytest.fixture
def single(mvc, pdf_path, monkeypatch):
    model, view, controller = mvc
    controller.open_pdf(str(pdf_path))
    controller._page_render_coordinator.wait_for_done()
    view.continuous_pages = False
    backend = Backend()
    controller._render_client = backend
    controller._render_owner = 'test-owner'
    backend.release_owner = lambda owner: None
    backend.release_document = lambda *args: None
    controller._page_render_coordinator = PageRenderCoordinator(
        result_consumer=controller._consume_page_render_image,
        failure_consumer=controller._on_page_render_failed,
        identity_matches=controller._page_render_identity_matches,
        backend=backend, owner='test-owner', parent=view)

    def forbidden(*args, **kwargs):
        pytest.fail('single-page process navigation must not rasterize on GUI')

    monkeypatch.setattr(model, 'get_page_pixmap', forbidden)
    controller._drop_render_cache_for_session(model.get_active_session_id())
    return model, view, controller, backend


@pytest.mark.parametrize('operation', ['navigate', 'search', 'zoom'])
def test_single_page_operations_schedule_current_high_quality(single, operation):
    model, view, controller, backend = single
    if operation == 'search':
        controller.jump_to_result(2, fitz.Rect(20, 30, 50, 60))
    elif operation == 'zoom':
        controller.change_scale(1, 1.25)
    else:
        controller.show_page(1)
    assert len(backend.jobs) == 1
    assert backend.jobs[0].page_index == 1
    assert backend.jobs[0].kind == 'page'
    assert view.current_page == 1
    assert controller._get_ui_state(model.get_active_session_id()).current_page == 1
    image = QImage(100, 150, QImage.Format.Format_RGB888)
    image.fill(0xFFFFFF)
    backend.job_done.emit(backend.jobs[-1].job_id, JobOutcome('image', image))
    assert not controller._page_render_coordinator.has_active_job
    assert controller._page_quality_map(model.get_active_session_id())[1] == 'high'
    assert any(item.pixmap().width() == 100 for item in view.scene.items() if hasattr(item, 'pixmap'))


def test_single_page_superseded_and_wrong_revision_results_never_paint(single):
    model, view, controller, backend = single
    controller.show_page(1)
    old = backend.jobs[-1]
    controller.show_page(2)
    current = backend.jobs[-1]
    image = QImage(100, 150, QImage.Format.Format_RGB888)
    image.fill(0xFFFFFF)
    backend.job_done.emit(old.job_id, JobOutcome('image', image))
    assert not any(hasattr(item, 'pixmap') for item in view.scene.items())
    controller._bump_render_revision(model.get_active_session_id())
    backend.job_done.emit(current.job_id, JobOutcome('image', image))
    assert not any(hasattr(item, 'pixmap') for item in view.scene.items())


def test_single_page_request_keeps_watermark_snapshot(single):
    model, view, controller, backend = single
    model.tools.watermark.add_watermark(pages=[2], text='Frozen single', opacity=.4)
    controller._bump_render_revision(model.get_active_session_id())
    controller.show_page(1)
    source = backend.jobs[-1].doc
    assert source.file is None
    assert b'Frozen single' in source.watermarks_json
    assert source.snapshot_provider()


def test_single_page_cached_high_quality_avoids_duplicate_job(single):
    model, view, controller, backend = single
    controller.show_page(1)
    image = QImage(100, 150, QImage.Format.Format_RGB888)
    image.fill(0xFFFFFF)
    backend.job_done.emit(backend.jobs[-1].job_id, JobOutcome('image', image))
    controller.show_page(1)
    assert len(backend.jobs) == 1
    assert view.current_page == 1


def test_single_page_search_draws_highlight_after_async_result(single):
    from test_scripts.test_search_jump_highlight import _search_highlights

    model, view, controller, backend = single
    controller.jump_to_result(2, fitz.Rect(20, 30, 50, 60))
    assert not _search_highlights(view)
    image = QImage(100, 150, QImage.Format.Format_RGB888)
    image.fill(0xFFFFFF)
    backend.job_done.emit(backend.jobs[-1].job_id, JobOutcome('image', image))
    assert len(_search_highlights(view)) == 1


def test_single_page_save_restarts_invalidated_render_without_more_input(single, qapp):
    model, view, controller, backend = single
    controller.show_page(1)
    old = backend.jobs[-1]
    controller._save_with_signature_consent(lambda: None)
    qapp.processEvents()
    assert len(backend.jobs) == 2
    assert backend.jobs[-1].doc.doc_key != old.doc.doc_key
    assert backend.jobs[-1].page_index == 1


def _deliver(backend):
    image = QImage(100, 150, QImage.Format.Format_RGB888)
    image.fill(0xFFFFFF)
    backend.job_done.emit(backend.jobs[-1].job_id, JobOutcome('image', image))


def test_same_page_refresh_preserves_pixels_and_unapplied_editor(single, monkeypatch, qapp):
    import shiboken6
    from PySide6.QtWidgets import QTextEdit

    model, view, controller, backend = single
    controller.show_page(1)
    _deliver(backend)
    original = next(item for item in view.scene.items() if hasattr(item, 'pixmap'))
    editor = QTextEdit('unapplied input')
    proxy = view.scene.addWidget(editor)
    view.text_editor = proxy
    finalized = []
    monkeypatch.setattr(view, '_finalize_text_edit', lambda reason: finalized.append(reason))
    controller._save_with_signature_consent(lambda: None)
    qapp.processEvents()
    assert not finalized
    assert shiboken6.isValid(original) and original.scene() is view.scene
    _deliver(backend)
    assert not finalized
    assert shiboken6.isValid(proxy) and proxy.scene() is view.scene
    assert editor.toPlainText() == 'unapplied input'
    assert view.text_editor is proxy
    view.text_editor = None


def test_preparation_reentry_cannot_submit_an_obsolete_generation(single, monkeypatch):
    model, view, controller, backend = single
    original = view.prepare_single_page_render
    entered = False

    def prepare(page):
        nonlocal entered
        if not entered:
            entered = True
            controller._bump_render_revision(model.get_active_session_id())
            controller.show_page(page)
        original(page)

    monkeypatch.setattr(view, 'prepare_single_page_render', prepare)
    controller.show_page(1)
    _deliver(backend)
    assert not controller._page_render_coordinator.has_active_job
    assert controller._page_quality_map(model.get_active_session_id())[1] == 'high'
    assert any(hasattr(item, 'pixmap') for item in view.scene.items())


def test_same_page_zoom_keeps_scaled_preview_until_new_pixels(single):
    import shiboken6

    model, view, controller, backend = single
    controller.show_page(1)
    _deliver(backend)
    original = next(item for item in view.scene.items() if hasattr(item, 'pixmap'))
    controller.change_scale(1, 1.25)
    assert shiboken6.isValid(original) and original.scene() is view.scene
    assert original.transform().m11() == pytest.approx(1.25)
    assert view._doc_rect_to_scene_rect(1, fitz.Rect(20, 30, 50, 60)).x() == pytest.approx(25)
    _deliver(backend)
    assert shiboken6.isValid(original) and original.scene() is view.scene
    assert original.transform().m11() == pytest.approx(1.0)


def test_first_delivery_keeps_editor_opened_while_render_was_pending(single, monkeypatch):
    import shiboken6
    from PySide6.QtWidgets import QTextEdit

    model, view, controller, backend = single
    controller.show_page(1)
    editor = QTextEdit('input while waiting')
    proxy = view.scene.addWidget(editor)
    view.text_editor = proxy
    finalized = []
    monkeypatch.setattr(view, '_finalize_text_edit', lambda reason: finalized.append(reason))
    _deliver(backend)
    assert not finalized
    assert shiboken6.isValid(proxy) and editor.toPlainText() == 'input while waiting'
    view.text_editor = None


def test_save_before_first_delivery_preserves_pending_editor(single, monkeypatch, qapp):
    import shiboken6
    from PySide6.QtWidgets import QTextEdit

    model, view, controller, backend = single
    controller.show_page(1)
    edit = QTextEdit('pending input')
    proxy = view.scene.addWidget(edit)
    view.text_editor = proxy
    finalized = []
    monkeypatch.setattr(view, '_finalize_text_edit', lambda reason: finalized.append(reason))
    controller._save_with_signature_consent(lambda: None)
    qapp.processEvents()
    assert not finalized
    _deliver(backend)
    assert shiboken6.isValid(proxy) and edit.toPlainText() == 'pending input'
    view.text_editor = None


def test_dpr_change_requeues_pending_single_page_and_drops_old_image(single, monkeypatch, qapp):
    from PySide6.QtCore import QEvent

    model, view, controller, backend = single
    dpr = [1.0]
    monkeypatch.setattr(controller, '_render_device_pixel_ratio', lambda: dpr[0])
    controller.show_page(1)
    old = backend.jobs[-1]
    dpr[0] = 1.5
    qapp.sendEvent(view.graphics_view, QEvent(QEvent.Type.DevicePixelRatioChange))
    assert len(backend.jobs) == 2
    image = QImage(100, 150, QImage.Format.Format_RGB888)
    image.fill(0xFFFFFF)
    backend.job_done.emit(old.job_id, JobOutcome('image', image))
    assert not any(hasattr(item, 'pixmap') for item in view.scene.items())
    _deliver(backend)
    assert controller._page_quality_map(model.get_active_session_id())[1] == 'high'


@pytest.mark.parametrize('pending', [False, True])
def test_continuous_dpr_change_replaces_high_or_pending_pixels(single, monkeypatch, qapp, pending):
    from PySide6.QtCore import QEvent

    model, view, controller, backend = single
    view.continuous_pages = True  # existing real continuous placeholders
    sid = model.get_active_session_id()
    controller._cancel_page_render_for_session(sid)
    monkeypatch.setattr(controller, '_visible_render_targets', lambda: ([0], [0]))
    dpr = [1.0]
    monkeypatch.setattr(controller, '_render_device_pixel_ratio', lambda: dpr[0])
    controller._page_quality_map(sid)[0] = 'high'
    old = None
    if pending:
        controller._page_quality_map(sid)[0] = 'low'
        controller._schedule_visible_render(sid)
        qapp.processEvents()
        old = backend.jobs[-1]
    before = len(backend.jobs)
    dpr[0] = 1.5
    qapp.sendEvent(view.graphics_view, QEvent(QEvent.Type.DevicePixelRatioChange))
    qapp.processEvents()
    assert len(backend.jobs) == before + 1
    assert backend.jobs[-1].scale == pytest.approx(1.5 * view.scale)
    if old is not None:
        image = QImage(100, 150, QImage.Format.Format_RGB888)
        backend.job_done.emit(old.job_id, JobOutcome('image', image))
        assert controller._page_quality_map(sid)[0] != 'high'
    _deliver(backend)
    assert controller._page_quality_map(sid)[0] == 'high'


def test_single_page_high_paint_notifies_pool_only_after_current_pixels(single):
    model, view, controller, backend = single
    presented = []
    backend.foreground_presented = lambda *args: presented.append(args)
    controller.show_page(1)
    controller._on_canvas_painted()
    assert presented == []
    _deliver(backend)
    controller._on_canvas_painted()
    assert presented == [('test-owner', f'{model.get_active_session_id()}@{controller._render_revision(model.get_active_session_id())}')]
