from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from model import content_scan, table_objects
from utils import object_probe_platform

logger = logging.getLogger(__name__)

_FAILURE_STATUSES = frozenset({"resource_limited", "analysis_failed", "containment_failed"})
#: answers that mark and cache nothing: a transient shortage, or a platform without the contained child
_NO_MARK_STATUSES = frozenset({"no_headroom", "unsupported_platform"})


@dataclass
class Job:
    kind: str
    page_num: int
    key: tuple
    payloads: tuple[bytes, ...]
    attempt: int = 1
    #: ``(page number, set key)`` of a scan job: the frame its answer is valid for (D12)
    frame: tuple[int, tuple[bytes, ...]] | None = None


class ObjectProbeCoordinator(QObject):
    """Per-controller logic over the App-wide ``ObjectProbeRunner`` (H14, H15, H16, H24).

    ``__init__`` is cheap: the runner is fetched on the first request.  An answer is applied only
    if the handle and page frame it was computed for are still current (H3, D1); a stale answer
    of any status, a crash included, is dropped and never retried or reported, and ``probe_dropped``
    tells the controller so that a pending status does not stay.  Only a ``complete`` answer is
    cached (an empty list is a real "no tables").  A typed failure (``resource_limited``,
    ``analysis_failed``, ``containment_failed``) is not retried; the page is marked failed.  A
    runner failure (a crash) is retried once, then marked ``crashed``.  ``no_headroom`` marks
    nothing, so the next request starts a job.  A failure never caches ``[]``.

    A scan job's frame is ``(page, set key)`` (D12): the page's scans are admitted as one set; a
    set that does not fit the cache ends the job ``resource_limited`` and marks the frame failed.
    """

    tables_ready = Signal(int)
    image_scan_ready = Signal(int)
    probe_failed = Signal(str, int, str)
    #: ``(kind, page)``: an answer was dropped as stale or superseded (no message, no retry)
    probe_dropped = Signal(str, int)

    def __init__(self, model, parent=None, *, runner=None):
        super().__init__(parent)
        self._model = model
        self._runner = runner
        self._runner_connected = False
        self._jobs: dict[int, Job] = {}
        self._submitting = 0
        self._early: dict[int, tuple] = {}

    def _ensure_runner(self):
        if self._runner is None:
            from PySide6.QtWidgets import QApplication

            from controller.object_probe_runner import ObjectProbeRunner

            self._runner = ObjectProbeRunner.for_app(QApplication.instance())
        if not self._runner_connected:
            self._runner.finished.connect(self._on_finished)
            self._runner.failed.connect(self._on_failed)
            self._runner_connected = True
        return self._runner

    def has_pending(self, kind: str) -> bool:
        """True while a job of ``kind`` is waiting for or running in the child."""
        return any(job.kind == kind for job in self._jobs.values())

    def request_tables(self, page_num: int, page_input: table_objects.PageInput | None = None) -> None:
        """Start a tables job unless the page is cached, failed or already in flight.

        ``page_input`` is the click's one scratch copy: its key names the job and its bytes are the
        worker's input, so nothing is built here when it is given.  A page whose copy cannot be
        built counts as failed (nothing is cached or marked) and starts no job.
        """
        model = self._model
        doc = model.doc
        if not doc or page_num < 1 or page_num > len(doc):
            return
        if not object_probe_platform.contained_probe_supported():
            return  # no contained child here: no job, nothing cached or marked
        page_input = table_objects.page_input_for(model, page_num, page_input)
        if table_objects.cached_table_rects(model, page_num, page_input) is not None:
            return
        if table_objects.table_analysis_failed(model, page_num, page_input):
            return
        key = page_input.key
        if any(job.kind == "tables" and job.key == key for job in self._jobs.values()):
            return
        payload = page_input.payload  # GUI thread: the only reader
        runner = self._ensure_runner()
        for job_id, job in list(self._jobs.items()):
            if job.kind == "tables" and runner.is_waiting(job_id):
                runner.cancel(job_id)
                del self._jobs[job_id]
        self._submit(Job("tables", page_num, key, (payload,)))

    def request_image_scan(self, page_num: int, scan_input=None) -> None:
        """Ask the child to scan the long content streams of an image page (card A5).  The job
        key is the tuple of missing content keys, so the answer is valid whatever happens
        meanwhile (H18); its frame is ``(page, set key)`` (D12).

        ``scan_input`` is the caller's one ``PageScanSet`` of the page (the click's); the jobs and
        the frame both read it, so the page's streams are walked at most once."""
        model = self._model
        doc = model.doc
        if not doc or page_num < 1 or page_num > len(doc):
            return
        if not object_probe_platform.contained_probe_supported():
            return  # the in-process scan serves the page here
        if scan_input is None:
            scan_input = model.image_scan_input(page_num)
        wanted = model.image_scan_jobs(page_num, scan_input)
        if not wanted:
            return
        key = tuple(content_key for content_key, _stream in wanted)
        # Per page: pages that share a long stream each need their own answer announced.
        if any(job.kind == "scan" and job.page_num == page_num and job.key == key for job in self._jobs.values()):
            return
        frame = (page_num, model.image_scan_set_key(page_num, scan_input))
        self._submit(Job("scan", page_num, key, tuple(stream for _key, stream in wanted), frame=frame))

    def _submit(self, job: Job) -> None:
        # The runner may answer inside ``submit`` (no headroom, a refused start): keep such an
        # answer until the job id is registered, then deliver it.
        self._submitting += 1
        try:
            job_id = self._ensure_runner().submit(self, job.kind, job.payloads)
        finally:
            self._submitting -= 1
        self._jobs[job_id] = job
        early = self._early.pop(job_id, None)
        if early is not None:
            handler, args = early
            handler(job_id, *args)

    def cancel_all(self) -> None:
        if self._runner is not None:
            self._runner.cancel_owner(self)
        self._jobs.clear()
        self._early.clear()

    def _drop(self, job: Job) -> None:
        """An answer for a frame that is gone: no cache, no mark, no message; tell the controller."""
        self.probe_dropped.emit(job.kind, job.page_num)

    def _on_finished(self, job_id: int, answer) -> None:
        job = self._jobs.pop(job_id, None)
        if job is None:
            if self._submitting:
                self._early[job_id] = (self._on_finished, (answer,))
            return
        status = answer.get("status") if isinstance(answer, dict) else None
        if job.kind == "scan":
            self._on_scan_answer(job, answer, status)
            return
        now = self._current_input(job)
        if self._is_stale(job, now):
            self._drop(job)
            return
        if status == "complete":
            try:
                rects = [tuple(float(v) for v in rect) for rect in answer["rects"]]
            except (KeyError, TypeError, ValueError):
                logger.warning("object probe answer malformed for page %s", job.page_num)
                self._retry_or_give_up(job, now)
                return
            if table_objects.store_table_rects(self._model, job.key, rects, current=now):
                self.tables_ready.emit(job.page_num)
        elif status in _FAILURE_STATUSES:
            table_objects.mark_table_analysis_failed(self._model, job.key, current=now)
            self.probe_failed.emit(job.kind, job.page_num, status)
        elif status in _NO_MARK_STATUSES:
            self.probe_failed.emit(job.kind, job.page_num, status)
        else:
            logger.warning("object probe answer has no known status for page %s", job.page_num)
            self._retry_or_give_up(job, now)

    def _on_failed(self, job_id: int) -> None:
        job = self._jobs.pop(job_id, None)
        if job is None:
            if self._submitting:
                self._early[job_id] = (self._on_failed, ())
            return
        if job.kind == "scan":
            if not self._scan_frame_current(job):
                self._drop(job)
                return
            self._retry_or_give_up(job)
            return
        now = self._current_input(job)
        if self._is_stale(job, now):
            self._drop(job)
            return
        self._retry_or_give_up(job, now)

    def _current_input(self, job: Job) -> table_objects.PageInput | None:
        """The page of a tables job as it is NOW (one new copy, built on first use), never the job's
        own input: an answer arrives at another time.  ``None`` for a scan job (content keys)."""
        if job.kind != "tables":
            return None
        return table_objects.PageInput(self._model, job.page_num)

    def _is_stale(self, job: Job, now: table_objects.PageInput | None = None) -> bool:
        # A tables job belongs to one handle and one page state, keyed on the bytes detection reads
        # (H3, D1): once that is gone, every answer (complete, failure, crash) is dropped silently,
        # with no retry.  A page that cannot be read now is stale too.  A scan job's frame is
        # checked by ``_scan_frame_current``.
        if job.kind != "tables":
            return False
        if self._model.doc is None:
            return True
        return not table_objects.key_is_current(self._model, job.key, now)

    def _scan_frame_current(self, job: Job, scan_input=None) -> bool:
        """True while the page's scan set is the one the job was requested for (D12).  A caller
        that goes on to use the page's scan set passes its own ``scan_input`` and keeps it."""
        if job.frame is None:
            return True
        page_num, set_key = job.frame
        doc = self._model.doc
        if not doc or page_num < 1 or page_num > len(doc):
            return False
        return self._model.image_scan_set_key(page_num, scan_input) == set_key

    def _on_scan_answer(self, job: Job, answer, status) -> None:
        # One walk of the page's streams serves the frame check and the admission of the set.
        scan_input = None if job.frame is None else self._model.image_scan_input(job.frame[0])
        current = self._scan_frame_current(job, scan_input)
        if status == "complete":
            try:
                scans = [content_scan.from_json(obj) for obj in answer["scans"]]
                if len(scans) != len(job.key):
                    raise ValueError("wrong number of scans")
            except (KeyError, TypeError, ValueError, IndexError):
                logger.warning("object probe scan answer malformed for page %s", job.page_num)
                if current:
                    self._retry_or_give_up(job)
                else:
                    self._drop(job)
                return
            answered = dict(zip(job.key, scans))
            if not current:
                # Valid content for other pages and later states: keep it if it fits, say nothing.
                content_scan.admit_set(answered)
                self._drop(job)
                return
            if self._model.admit_image_scan_set(job.frame, answered, scan_input):
                self.image_scan_ready.emit(job.page_num)
            else:
                self._fail_scan(job, "resource_limited")
            return
        if not current:
            self._drop(job)  # a late failure never reaches a frame that changed (D1 class)
            return
        if status in _FAILURE_STATUSES:
            self._fail_scan(job, status)
        elif status in _NO_MARK_STATUSES:
            self.probe_failed.emit(job.kind, job.page_num, status)
        else:
            logger.warning("object probe answer has no known status for page %s", job.page_num)
            self._retry_or_give_up(job)

    def _fail_scan(self, job: Job, reason: str) -> None:
        """Mark the job's frame failed (no retry, nothing cached) and report ``reason``."""
        self._mark_scan_failed(job, reason)
        self.probe_failed.emit(job.kind, job.page_num, reason)

    def _mark_scan_failed(self, job: Job, reason: str) -> None:
        if job.frame is not None:
            self._model.mark_image_scan_failed(*job.frame, reason)

    def _retry_or_give_up(self, job: Job, now: table_objects.PageInput | None = None) -> None:
        if job.attempt == 1:
            self._submit(Job(job.kind, job.page_num, job.key, job.payloads, attempt=2, frame=job.frame))
            return
        if job.kind == "scan":
            self._mark_scan_failed(job, "crashed")
        else:
            table_objects.mark_table_analysis_failed(self._model, job.key, current=now)
        self.probe_failed.emit(job.kind, job.page_num, "crashed")
