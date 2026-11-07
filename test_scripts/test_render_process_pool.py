from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest

from src.render_worker.process_client import DocSource, JobOutcome, RenderJob
from src.render_worker.process_pool import RenderProcessPool


class Client(QObject):
    job_done = Signal(str, object)
    stopped = Signal()

    def __init__(self, parent, **kwargs):
        super().__init__(parent)
        self._active = None
        self._queue = []
        self._process = None
        self.loaded_key = None
        self.pid = 0
        self.metrics = dict(starts=0, images=0, doc_loads=0, fallbacks=0,
                            child_peak_mb=None, ipc_bytes=0, frame_gui_ms=[])
        self.jobs = []
        self.cancelled = []
        self.owners = set()

    def register_owner(self):
        owner = str(len(self.owners))
        self.owners.add(owner)
        return owner

    def release_owner(self, owner):
        self.owners.discard(owner)

    def release_document(self, owner, session):
        pass

    def start(self):
        if self._process is None:
            self._process = object()
            self.metrics['starts'] += 1

    def submit(self, job):
        self.start()
        self.jobs.append(job)
        if self._active is None:
            self._active = job
        else:
            self._queue.append(job)

    def cancel(self, token, status='cancelled', **kwargs):
        self.cancelled.append(token)
        # Logical completion need not mean the native call has stopped.
        self.job_done.emit(token, JobOutcome(status))

    def finish(self, status='image'):
        job, self._active = self._active, None
        if job:
            self.loaded_key = job.doc.doc_key
            self.job_done.emit(job.job_id, JobOutcome(status))
        if self._queue:
            self._active = self._queue.pop(0)

    def sample_memory(self):
        pass

    @contextmanager
    def path_loads_held(self, timeout):
        yield

    def shutdown(self):
        self._process = None
        self._active = None
        self._queue.clear()
        self.stopped.emit()


def make(qapp, **kwargs):
    pool = RenderProcessPool(client_factory=Client, **kwargs)
    owner = pool.register_owner()
    pool.foreground_presented(owner, 's@0')
    replies = []
    pool.job_done.connect(lambda token, outcome: replies.append((token, outcome.status)))
    return pool, owner, replies


def job(owner, token, lane='thumb', doc='s@0'):
    return RenderJob(token, owner, lane, DocSource(doc, None, lambda: b'pdf'),
                     0, 1., 'srgb', lane if lane == 'thumb' else 'page')


def test_unknown_reservation_keeps_one_compute_child(qapp):
    pool, owner, _ = make(qapp)
    pool.submit(job(owner, 'a'))
    pool.submit(job(owner, 'b'))
    assert len(pool.children) == 1
    pool.shutdown()


def test_idle_healthy_secondary_serves_foreground_before_primary_recall(qapp):
    pool, owner, _ = make(qapp, expansion_allowed=lambda: True)
    pool.submit(job(owner, 'old-page', lane='page'))
    pool.submit(job(owner, 'background'))
    pool.children[1].finish()
    pool.result_consumed('background')
    pool.cancel('old-page')
    pool.submit(job(owner, 'new-page', lane='page'))
    assert pool.children[1]._active is not None
    assert pool.children[1]._active.job_id == 'new-page'
    assert not pool.children[0]._queue, 'do not recall a healthy busy child when an idle slot exists'
    pool.shutdown()


def test_admitted_second_worker_is_lazy_and_pool_shared_by_owners(qapp):
    pool, owner, _ = make(qapp, expansion_allowed=lambda: True)
    other = pool.register_owner()
    pool.foreground_presented(other, 's@0')
    pool.start()
    assert len(pool.children) == 1
    pool.submit(job(owner, 'a'))
    pool.submit(job(other, 'b'))
    assert len(pool.children) == 2
    assert sum(child._active is not None for child in pool.children) == 2
    pool.shutdown()


def test_completed_background_does_not_starve_queued_foreground(qapp):
    pool, owner, replies = make(qapp, expansion_allowed=lambda: True)
    for token in ('a', 'b', 'c'):
        pool.submit(job(owner, token))
    pool.submit(job(owner, 'visible', lane='page'))
    # Borrowed foreground slot delegates recall to the existing child client.
    assert any(child._queue and child._queue[0].job_id == 'visible' for child in pool.children)
    assert all(not child._queue or len(child._queue) == 1 for child in pool.children)
    pool.shutdown()
    qapp.processEvents()
    assert len({token for token, _ in replies}) == len(replies)


def test_pending_limit_is_explicit_and_does_not_start_more_children(qapp):
    pool, owner, replies = make(qapp, max_pending=2)
    for token in ('a', 'b', 'c', 'd'):
        pool.submit(job(owner, token))
    qapp.processEvents()
    assert ('d', 'capacity') in replies
    assert len(pool._queue) <= 2 and len(pool.children) == 1
    pool.shutdown()


def test_cancelled_native_work_still_owns_its_slot(qapp):
    pool, owner, replies = make(qapp)
    pool.submit(job(owner, 'a'))
    child = pool.children[0]
    pool.cancel('a')
    pool.submit(job(owner, 'b'))
    assert child._active.job_id == 'a'
    assert not child._queue
    child.finish()
    QTest.qWait(40)
    assert child._active.job_id == 'b'
    assert replies.count(('a', 'cancelled')) == 1
    pool.shutdown()


def test_release_owner_only_cancels_that_windows_work(qapp):
    pool, owner, replies = make(qapp, expansion_allowed=lambda: True)
    other = pool.register_owner()
    pool.submit(job(owner, 'a'))
    pool.submit(job(other, 'b'))
    pool.submit(job(owner, 'c'))
    pool.release_owner(owner)
    qapp.processEvents()
    assert ('a', 'owner_released') in replies and ('c', 'owner_released') in replies
    assert not any(token == 'b' for token, _ in replies)
    pool.shutdown()


def test_pool_shutdown_reaps_children_and_reports_each_job_once(qapp):
    pool, owner, replies = make(qapp, expansion_allowed=lambda: True)
    for token in ('a', 'b', 'c'):
        pool.submit(job(owner, token))
    pool.shutdown()
    qapp.processEvents()
    assert pool._process is None
    assert sorted(token for token, _ in replies) == ['a', 'b', 'c']


def test_pending_document_release_is_scoped_to_revision_session(qapp):
    pool, owner, replies = make(qapp)
    pool.submit(job(owner, 'a', doc='live@0'))
    pool.submit(job(owner, 'b', doc='closed@1'))
    pool.submit(job(owner, 'c', doc='live@1'))
    pool.release_document(owner, 'closed')
    qapp.processEvents()
    assert ('b', 'cancelled') in replies
    assert [item.job_id for item in pool._queue] == ['c']
    pool.shutdown()


def test_admission_alone_does_not_start_second_before_presentation(qapp):
    pool = RenderProcessPool(client_factory=Client, expansion_allowed=lambda: True)
    owner = pool.register_owner()
    pool.submit(job(owner, 'a'))
    pool.submit(job(owner, 'b'))
    assert len(pool.children) == 1
    pool.foreground_presented(owner, 's@0')
    assert len(pool.children) == 2
    pool.shutdown()


def test_unconsumed_images_retain_global_credit(qapp):
    pool, owner, _ = make(qapp, expansion_allowed=lambda: True)
    pool.submit(job(owner, 'a'))
    pool.submit(job(owner, 'b'))
    pool.submit(job(owner, 'c'))
    pool.children[1].finish()
    qapp.processEvents()
    assert len(pool.children[1].jobs) == 1
    pool.result_consumed('b')
    assert len(pool.children[1].jobs) == 2
    pool.shutdown()


def test_closed_owner_returns_its_buffered_credit(qapp):
    pool, owner, _ = make(qapp, expansion_allowed=lambda: True)
    other = pool.register_owner()
    pool.foreground_presented(other, 's@0')
    pool.submit(job(owner, 'a'))
    pool.children[0].finish()
    pool.submit(job(other, 'b'))
    pool.submit(job(other, 'c'))
    assert len(pool.children[0].jobs) == 1
    pool.release_owner(owner)
    assert len(pool.children[0].jobs) == 2
    pool.shutdown()


def test_disabled_primary_does_not_bypass_healthy_worker(qapp):
    pool, owner, replies = make(qapp, expansion_allowed=lambda: True)
    pool.submit(job(owner, 'a'))
    pool.submit(job(owner, 'b'))
    primary, healthy = pool.children
    primary._disabled = True
    primary.finish('transport_lost')
    pool.submit(job(owner, 'visible', lane='page'))
    assert len(primary.jobs) == 1
    assert healthy._queue[0].job_id == 'visible'
    assert not any(token == 'visible' and status == 'unavailable' for token, status in replies)
    pool.shutdown()


def test_cancelled_foreground_activates_real_client_recall(qapp):
    import fitz
    from src.render_worker.process_client import RenderProcessClient
    from test_scripts.test_render_process_client import DelayedExitProcess

    clock = [1.]
    pool = RenderProcessPool(client_factory=lambda parent, **kwargs: RenderProcessClient(
        parent, process_factory=DelayedExitProcess, monotonic=lambda: clock[0], **kwargs))
    owner = pool.register_owner()
    with fitz.open() as document:
        document.new_page()
        data = document.tobytes()
    source = DocSource('s@0', None, lambda: data)
    pool.submit(RenderJob('old', owner, 'page', source, 0, 1., 'srgb'))
    child = pool.children[0]
    process = child._process
    process.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    pool.cancel('old')
    pool.submit(RenderJob('new', owner, 'page', source, 0, 1., 'srgb'))
    try:
        assert child._recall_timer.isActive()
        clock[0] += .151
        child._check_deadline()
        assert process.kill_requested
        assert child._process is process, 'replacement cannot precede actual exit'
    finally:
        pool.shutdown()
        process.exit_now()
        qapp.processEvents()


def test_foreground_reclaims_other_windows_buffered_thumbnail_credit(qapp):
    pool, owner, replies = make(qapp, expansion_allowed=lambda: True)
    other = pool.register_owner()
    revoked = []
    pool.image_revoked.connect(revoked.append)
    pool.submit(job(owner, 'tail'))
    pool.submit(job(owner, 'slow-prefix'))
    pool.children[0].finish()
    qapp.processEvents()  # the tail is now buffered by its consumer
    pool.submit(job(other, 'visible', lane='page'))
    assert revoked == ['tail']
    assert pool.children[0]._active.job_id == 'visible'
    assert replies.count(('tail', 'image')) == 1
    pool.shutdown()


def test_reentrant_recall_replaces_not_yet_delivered_image(qapp):
    pool, owner, replies = make(qapp, expansion_allowed=lambda: True)
    other = pool.register_owner()
    pool.submit(job(owner, 'tail'))
    pool.submit(job(owner, 'prefix'))
    pool.children[1].finish()
    pool.children[0].finish()

    def consume(token, outcome):
        if token == 'prefix':
            pool.submit(job(other, 'visible', lane='page'))

    pool.job_done.connect(consume)
    qapp.processEvents()
    assert ('tail', 'cancelled') in replies
    assert ('tail', 'image') not in replies
    pool.shutdown()


def test_pool_reports_unavailable_only_when_every_child_is_disabled(qapp):
    pool, _owner, _ = make(qapp, expansion_allowed=lambda: True)
    child = pool.children[0]
    assert pool.unavailable is False
    child._disabled = False
    assert pool.unavailable is False
    child._disabled = True
    assert pool.unavailable is True
    pool.shutdown()
