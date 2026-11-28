from __future__ import annotations

import pytest
from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from controller.thumbnail_coordinator import ThumbnailCoordinator
from src.render_worker.process_client import DocSource, JobOutcome


class Backend(QObject):
    job_done = Signal(str, object)
    image_revoked = Signal(str)

    def __init__(self):
        super().__init__()
        self.jobs = []
        self.metrics = {'fallbacks': 0}

    def submit(self, job):
        self.jobs.append(job)

    def cancel(self, token):
        self.job_done.emit(token, JobOutcome('cancelled'))


def make(qapp):
    backend = Backend()
    images, failures = [], []
    coordinator = ThumbnailCoordinator(
        source_resolver=lambda request: pytest.fail('healthy process must not use file thread'),
        live_renderer=lambda *args: pytest.fail('healthy process must not raster in App'),
        batch_consumer=lambda start, values: images.append((start, values)),
        identity_matches=lambda *args: True,
        backend=backend, owner='owner',
        process_source_resolver=lambda request: DocSource('s@1', None, lambda: b'pdf'),
        process_failure_consumer=lambda *args: failures.append(args),
    )
    return coordinator, backend, images, failures


def test_source_revision_change_drops_buffered_tail_and_returns_each_credit(qapp):
    c, backend, images, _failures = make(qapp)
    backend.thumbnail_window = 2
    current = [True]
    original = c._process_source_resolver
    c._process_source_resolver = lambda request: replace(original(request), is_current=lambda: current[0])
    credits = []
    backend.result_consumed = credits.append
    c.request('s', 1, 0, 2, 'srgb')
    assert len(backend.jobs) == 2
    first, tail = backend.jobs
    image = QImage(2, 2, QImage.Format_RGB888)
    backend.job_done.emit(tail.job_id, JobOutcome('image', image))
    assert not images and not credits
    current[0] = False
    backend.job_done.emit(first.job_id, JobOutcome('image', image))
    qapp.processEvents()
    assert not images and not c.has_active_job
    assert sorted(credits) == sorted([first.job_id, tail.job_id])


def test_process_thumbnails_yield_and_keep_one_job_in_flight(qapp):
    c, backend, images, _failures = make(qapp)
    c.request('s', 1, 2, 4, 'srgb')
    assert len(backend.jobs) == 1
    first = backend.jobs[0]
    assert (first.kind, first.lane, first.page_index) == ('thumb', 'thumb', 2)
    image = QImage(3, 4, QImage.Format_RGB888)
    backend.job_done.emit(first.job_id, JobOutcome('image', image))
    assert images == [(2, [image])]
    assert len(backend.jobs) == 1
    qapp.processEvents()
    second = backend.jobs[-1]
    assert second.page_index == 3
    backend.job_done.emit(second.job_id, JobOutcome('image', image))
    qapp.processEvents()
    assert not c.has_active_job


def test_process_cancel_drops_old_reply_and_never_paints_old_tab(qapp):
    c, backend, images, _failures = make(qapp)
    c.request('s', 1, 0, 3, 'srgb')
    old = backend.jobs[-1].job_id
    c.cancel()
    backend.job_done.emit(old, JobOutcome('image', QImage(2, 2, QImage.Format_RGB888)))
    qapp.processEvents()
    assert not images and not c.has_active_job and len(backend.jobs) == 1


@pytest.mark.parametrize('status', ['transport_lost', 'timeout'])
def test_native_failure_never_retries_the_same_page_in_App(qapp, status):
    c, backend, images, failures = make(qapp)
    c.request('s', 1, 0, 1, 'srgb')
    backend.job_done.emit(backend.jobs[-1].job_id, JobOutcome(status))
    qapp.processEvents()
    assert failures == [('s', 0, status)]
    assert len(images) == 1
    assert not c.has_active_job


def test_startup_job_is_submitted_without_ready_predicate(qapp):
    c, backend, _images, _failures = make(qapp)
    c.request('s', 1, 0, 1, 'srgb')
    assert len(backend.jobs) == 1 and c.has_active_job
    c.cancel()


def test_two_slot_window_preserves_order_and_bounds_completed_images(qapp):
    c, backend, images, _failures = make(qapp)
    backend.thumbnail_window = 2
    c.request('s', 1, 0, 4, 'srgb')
    assert [job.page_index for job in backend.jobs] == [0, 1]
    image = QImage(3, 4, QImage.Format_RGB888)
    backend.job_done.emit(backend.jobs[1].job_id, JobOutcome('image', image))
    qapp.processEvents()
    assert images == []
    # A slow prefix must not allow an unbounded completed-image tail.
    assert len(backend.jobs) == 2
    backend.job_done.emit(backend.jobs[0].job_id, JobOutcome('image', image))
    qapp.processEvents()
    assert [start for start, _ in images] == [0, 1]
    assert [job.page_index for job in backend.jobs] == [0, 1, 2, 3]
    backend.job_done.emit(backend.jobs[3].job_id, JobOutcome('image', image))
    backend.job_done.emit(backend.jobs[2].job_id, JobOutcome('image', image))
    qapp.processEvents()
    assert [start for start, _ in images] == [0, 1, 2, 3]
    assert not c.has_active_job


def test_two_slot_cancel_rejects_both_late_results(qapp):
    c, backend, images, _failures = make(qapp)
    backend.thumbnail_window = 2
    c.request('s', 1, 0, 4, 'srgb')
    jobs = list(backend.jobs)
    assert len(jobs) == 2
    c.cancel()
    for job in jobs:
        backend.job_done.emit(job.job_id, JobOutcome('image', QImage()))
    qapp.processEvents()
    assert images == [] and not c.has_active_job
    assert len(backend.jobs) == 2


def test_reentrant_consumer_cancel_drops_buffered_second_page(qapp):
    c, backend, images, _failures = make(qapp)
    backend.thumbnail_window = 2
    original = c._batch_consumer

    def consume(start, values):
        original(start, values)
        c.cancel()

    c._batch_consumer = consume
    c.request('s', 1, 0, 4, 'srgb')
    assert len(backend.jobs) == 2
    image = QImage(3, 4, QImage.Format_RGB888)
    backend.job_done.emit(backend.jobs[1].job_id, JobOutcome('image', image))
    backend.job_done.emit(backend.jobs[0].job_id, JobOutcome('image', image))
    qapp.processEvents()
    assert [start for start, _ in images] == [0]
    assert not c.has_active_job and len(backend.jobs) == 2


def test_failure_callback_replacement_cannot_inject_old_image(qapp):
    c, backend, images, _failures = make(qapp)
    backend.thumbnail_window = 2
    c.request('s', 1, 0, 2, 'srgb')
    old = list(backend.jobs)
    c._process_failure_consumer = lambda *args: c.request('new', 2, 0, 2, 'srgb')
    backend.job_done.emit(old[0].job_id, JobOutcome('timeout'))
    assert c._process_images == {}
    assert images == []
    c.cancel()


def test_buffered_image_credit_returns_only_after_apply_or_cancel(qapp):
    c, backend, images, _failures = make(qapp)
    backend.thumbnail_window = 2
    consumed = []
    backend.result_consumed = consumed.append
    c.request('s', 1, 0, 3, 'srgb')
    first, second = backend.jobs
    backend.job_done.emit(second.job_id, JobOutcome('image', QImage()))
    assert consumed == [] and images == []
    c.cancel()
    assert consumed == [second.job_id]
    assert first.job_id != second.job_id


def test_capacity_defers_thumbnail_without_gui_raster(qapp):
    from PySide6.QtTest import QTest

    c, backend, images, _failures = make(qapp)
    c.request('s', 1, 0, 1, 'srgb')
    backend.job_done.emit(backend.jobs[-1].job_id, JobOutcome('capacity'))
    assert not images and backend.metrics['fallbacks'] == 0
    # The retry is a 100 ms timer. On Windows it fires 100-131 ms after it is armed (two 15.6 ms timer ticks),
    # so a fixed 130 ms wait missed it about one run in ten. Check it is deferred, then wait for it.
    QTest.qWait(50)
    assert len(backend.jobs) == 1
    for _ in range(200):  # up to 2 s
        if len(backend.jobs) == 2:
            break
        QTest.qWait(10)
    assert len(backend.jobs) == 2
    assert backend.jobs[-1].page_index == 0
    c.cancel()


def test_revoked_buffered_tail_is_discarded_and_retried(qapp):
    c, backend, images, _failures = make(qapp)
    backend.thumbnail_window = 2
    consumed = []
    backend.result_consumed = consumed.append
    c.request('s', 1, 0, 3, 'srgb')
    first, tail = backend.jobs
    backend.job_done.emit(tail.job_id, JobOutcome('image', QImage()))
    backend.image_revoked.emit(tail.job_id)
    qapp.processEvents()
    assert [job.page_index for job in backend.jobs] == [0, 1, 1]
    assert images == [] and consumed == [tail.job_id]
    assert backend.jobs[-1].job_id != tail.job_id
    backend.job_done.emit(first.job_id, JobOutcome('image', QImage()))
    assert [start for start, _ in images] == [0]
    c.cancel()


def test_permanently_unavailable_backend_uses_the_file_thread_not_a_process_round_trip(qapp):
    c, backend, images, _failures = make(qapp)
    backend.unavailable = True
    started = []
    c._source_resolver = lambda request: 'file-source'
    c._process_source_resolver = lambda request: pytest.fail('unavailable backend must not be asked')
    c._start_worker = lambda request, source: started.append(source)
    c.request('s', 1, 0, 2, 'srgb')
    assert started == ['file-source']
    assert not backend.jobs


def test_thumbnail_fallback_is_counted_by_reason(qapp):
    c, backend, images, _failures = make(qapp)
    c._live_renderer = lambda page, profile: QImage(2, 2, QImage.Format_RGB888)
    c.request('s', 1, 0, 1, 'srgb')
    backend.job_done.emit(backend.jobs[-1].job_id, JobOutcome('unavailable', reason='setup_failed'))
    assert backend.metrics['fallbacks'] == 1
    assert backend.metrics['fallback_reasons'] == {'setup_failed': 1}


def test_window_is_clamped_to_three(qapp):
    c, backend, _images, _failures = make(qapp)
    backend.thumbnail_window = 5
    c.request('s', 1, 0, 10, 'srgb')
    assert len(backend.jobs) == 3


def test_window_follows_the_per_document_capacity_when_the_backend_reports_it(qapp):
    c, backend, _images, _failures = make(qapp)
    backend.thumbnail_window = 3
    backend.window_for = lambda doc: 1
    c.request('s', 1, 0, 10, 'srgb')
    assert len(backend.jobs) == 1
