from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
import uuid

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from src.render_worker.process_client import JobOutcome, RenderProcessClient


class RenderProcessPool(QObject):
    """One App-wide bounded scheduler over replaceable raster clients.

    ``expansion_allowed`` is a repeatable, side-effect-free eligibility query;
    physical startup must separately acquire any qualified resource lease.
    Sampled peaks or free RAM alone do not qualify that lease. Unknown
    admission retains one child.
    Logical cancellation never releases a client's physical work slot. The
    façade is not an OS memory cap; full helper admission remains separate.
    """

    job_done = Signal(str, object)
    image_revoked = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None, *, client_factory=None,
                 expansion_allowed=None, max_pending=32):
        super().__init__(parent)
        if type(max_pending) is not int or max_pending < 1:
            raise ValueError('max_pending must be a positive integer')
        self._factory = client_factory or RenderProcessClient
        self._expansion_allowed = expansion_allowed
        self._max_pending = max_pending
        self.children = []
        self._owners = {}
        self._jobs = {}
        self._queue = []
        self._credits = {}
        self._completed_jobs = {}
        self._presented = set()
        self._closing = False
        self._pumping = False
        self._last_owner = None
        self._foreground_streak = 0
        self._deferred = []
        self._delivering = set()
        self._stopped_emitted = False
        self._held = 0
        self.metrics = None
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._pump)
        self._add_child()

    def _add_child(self):
        expanding = bool(self.children)
        child = self._factory(self, trim_thumbnail_store=expanding)
        if expanding:
            self.children[0]._trim_thumbnail_store = True
        if self.metrics is None:
            self.metrics = child.metrics
        else:
            child.metrics = self.metrics
        for tokens in self._owners.values():
            tokens.append(child.register_owner())
        child.job_done.connect(self._child_done)
        child.stopped.connect(self._child_stopped)
        self.children.append(child)

    @property
    def thumbnail_window(self):
        return 2 if len(self.children) == 2 or (self._presented and self._admitted()) else 1

    @property
    def _process(self):
        return next((child._process for child in self.children if child._process is not None), None)

    @property
    def unavailable(self):
        """Every child is permanently disabled, so a submit can only report unavailable."""
        return bool(self.children) and all(getattr(child, '_disabled', False) for child in self.children)

    @property
    def has_live_processes(self):
        return self._process is not None

    @property
    def pids(self):
        return tuple(child.pid for child in self.children if child.pid)

    @property
    def pid(self):
        return self.children[0].pid

    @property
    def ready(self):
        return any(getattr(child, 'ready', False) for child in self.children)

    @property
    def _active(self):
        return next((child._active for child in self.children if child._active), None)

    def register_owner(self):
        owner = uuid.uuid4().hex
        self._owners[owner] = [child.register_owner() for child in self.children]
        return owner

    def foreground_presented(self, owner, doc_key):
        if owner in self._owners and not self._closing:
            self._presented = {key for key in self._presented if key[0] != owner}
            self._presented.add((owner, doc_key))
            self._pump()

    def start(self):
        if not self._closing:
            self.children[0].start()

    def submit(self, job):
        if job.job_id in self._jobs or job.job_id in self._credits:
            raise ValueError('duplicate render job identity')
        if self._closing or job.owner not in self._owners:
            self._report(job.job_id, JobOutcome('owner_released'))
            return
        if len(self._queue) >= self._max_pending:
            self._report(job.job_id, JobOutcome('capacity'))
            return
        self._jobs[job.job_id] = (job, None)
        self._queue.append(job)
        self._timer.start()
        self._pump()

    def _report(self, token, outcome):
        self._deferred.append((token, outcome))
        QTimer.singleShot(0, self._deliver)

    @Slot()
    def _deliver(self):
        if self._held:
            return
        # Keep later replies addressable: a reentrant foreground request may
        # revoke an image that has not yet reached its consumer this turn.
        for _ in range(len(self._deferred)):
            if not self._deferred:
                break
            token, outcome = self._deferred.pop(0)
            self._delivering.add(token)
            try:
                self.job_done.emit(token, outcome)
            finally:
                self._delivering.discard(token)
        self._pump()

    def _reclaim_background_image(self, index):
        for token, slot in list(self._credits.items()):
            job = self._completed_jobs[token]
            if slot != index or job.kind != 'thumb' or token in self._delivering:
                continue
            self._credits.pop(token)
            self._completed_jobs.pop(token)
            for position, (pending, outcome) in enumerate(self._deferred):
                if pending == token and outcome.status == 'image':
                    self._deferred[position] = (token, JobOutcome('cancelled'))
                    break
            else:
                self.image_revoked.emit(token)

    def _select(self):
        foreground = [job for job in self._queue if job.lane == 'page']
        background = [job for job in self._queue if job.lane != 'page']
        candidates = (background if self._foreground_streak >= 2 and background
                      else foreground or background)
        return next((job for job in candidates if job.owner != self._last_owner), candidates[0])

    def _admitted(self):
        if self._expansion_allowed is None:
            return False
        try:
            return self._expansion_allowed() is True
        except Exception:
            return False

    @Slot()
    def _pump(self):
        if self._pumping or self._closing or self._held:
            return
        self._pumping = True
        try:
            while self._queue:
                job = self._select()
                if (len(self.children) == 1 and len(self._jobs) > 1
                        and (job.owner, job.doc.doc_key) in self._presented
                        and self._admitted()):
                    self._add_child()
                primary_index = next((index for index, child in enumerate(self.children)
                                      if not getattr(child, '_disabled', False)), 0)
                if job.lane == 'page' and self.children[primary_index]._active is None:
                    self._reclaim_background_image(primary_index)
                available = [index for index, child in enumerate(self.children)
                             if child._active is None and not child._queue
                             and not getattr(child, '_retiring', False)
                             and not getattr(child, '_closing', False)
                             and not getattr(child, '_disabled', False)
                             and index not in self._credits.values()]
                if job.lane == 'page':
                    # Prefer the foreground reservation, but use an already
                    # idle healthy secondary before recalling/reloading a busy
                    # child. A reservation is not a reason to waste capacity.
                    if primary_index in available:
                        available = [primary_index]
                    primary = self.children[primary_index]
                    if (not available and not getattr(primary, '_disabled', False)
                            and not getattr(primary, '_retiring', False)
                            and primary._active is not None
                            and (primary._active.lane != 'page'
                                 or primary._active.job_id not in self._jobs)
                            and not primary._queue
                            and primary_index not in self._credits.values()):
                        available = [primary_index]
                if all(getattr(child, '_disabled', False) for child in self.children):
                    self._queue.remove(job)
                    self._jobs.pop(job.job_id, None)
                    self._report(job.job_id, JobOutcome('unavailable'))
                    continue
                if not available:
                    break
                index = next((index for index in available
                              if self.children[index].loaded_key == job.doc.doc_key
                              and getattr(self.children[index], '_loaded_owner', None)
                              == self._owners[job.owner][index]), available[-1])
                self._queue.remove(job)
                self._jobs[job.job_id] = (job, index)
                self._last_owner = job.owner
                self._foreground_streak = self._foreground_streak + 1 if job.lane == 'page' else 0
                self.children[index].submit(replace(job, owner=self._owners[job.owner][index]))
            if not self._queue and not self._active:
                self._timer.stop()
        finally:
            self._pumping = False

    @Slot(str, object)
    def _child_done(self, token, outcome):
        entry = self._jobs.pop(token, None)
        if entry is None:
            return
        job, index = entry
        if outcome.status == 'image':
            self._credits[token] = index
            self._completed_jobs[token] = job
        self._report(token, outcome)
        self._timer.start()

    def result_consumed(self, token):
        self._credits.pop(token, None)
        self._completed_jobs.pop(token, None)
        self._pump()

    def cancel(self, token, status='cancelled', *, retire=False):
        entry = self._jobs.pop(token, None)
        if entry is None:
            self.result_consumed(token)
            return
        job, index = entry
        if index is None:
            self._queue.remove(job)
        else:
            self.children[index].cancel(token, status, retire=retire)
        self._report(token, JobOutcome(status))
        self._timer.start()

    def release_owner(self, owner):
        tokens = self._owners.pop(owner, None)
        if tokens is None:
            return
        self._presented = {key for key in self._presented if key[0] != owner}
        for token, (job, _) in list(self._jobs.items()):
            if job.owner == owner:
                self.cancel(token, 'owner_released', retire=True)
        for token, job in list(self._completed_jobs.items()):
            if job.owner == owner:
                self.result_consumed(token)
        for child, child_owner in zip(self.children, tokens):
            child.release_owner(child_owner)

    def release_document(self, owner, session_id):
        self._presented = {key for key in self._presented
                           if not (key[0] == owner and key[1].split('@', 1)[0] == session_id)}
        for token, (job, _) in list(self._jobs.items()):
            if job.owner == owner and job.doc.doc_key.split('@', 1)[0] == session_id:
                self.cancel(token, retire=True)
        for token, job in list(self._completed_jobs.items()):
            if job.owner == owner and job.doc.doc_key.split('@', 1)[0] == session_id:
                self.result_consumed(token)
        for child, child_owner in zip(self.children, self._owners.get(owner, ())):
            child.release_document(child_owner, session_id)

    def sample_memory(self):
        for child in self.children:
            child.sample_memory()

    @contextmanager
    def path_loads_held(self, timeout_ms):
        self._held += 1
        try:
            with ExitStack() as stack:
                for child in self.children:
                    stack.enter_context(child.path_loads_held(timeout_ms))
                yield
        finally:
            self._held -= 1
            if not self._held:
                self._deliver()
                self._pump()

    @Slot()
    def shutdown(self):
        self._closing = True
        self._timer.stop()
        for token in list(self._jobs):
            self.cancel(token, 'owner_released')
        self._credits.clear()
        self._completed_jobs.clear()
        for child in self.children:
            child.shutdown()
        self._timer.stop()
        self._child_stopped()

    @Slot()
    def _child_stopped(self):
        if self._closing and not self.has_live_processes and not self._stopped_emitted:
            self._stopped_emitted = True
            self.stopped.emit()
