from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from model import table_objects

logger = logging.getLogger(__name__)

_FAILURE_STATUSES = frozenset({"resource_limited", "analysis_failed", "containment_failed"})


@dataclass
class Job:
    kind: str
    page_num: int
    key: tuple
    payloads: tuple[bytes, ...]
    attempt: int = 1


class ObjectProbeCoordinator(QObject):
    """Per-controller logic over the App-wide ``ObjectProbeRunner`` (H14, H15, H16, H24).

    ``__init__`` is cheap: the runner is fetched on the first request.  An answer is applied only
    if the handle and page frame it was computed for are still current (H3, D1); a stale answer
    of any status, a crash included, is dropped silently and never retried.  Only a ``complete`` answer is cached (an empty list is a real "no tables").  A typed
    failure (``resource_limited``, ``analysis_failed``, ``containment_failed``) is not retried; the
    page is marked failed.  A runner failure (a crash) is retried once, then marked ``crashed``.
    ``no_headroom`` marks nothing, so the next request starts a job.  A failure never caches ``[]``.
    """

    tables_ready = Signal(int)
    probe_failed = Signal(str, int, str)

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

    def _on_finished(self, job_id: int, answer) -> None:
        job = self._jobs.pop(job_id, None)
        if job is None:
            if self._submitting:
                self._early[job_id] = (self._on_finished, (answer,))
            return
        now = self._current_input(job)
        if self._is_stale(job, now):
            return
        status = answer.get("status") if isinstance(answer, dict) else None
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
        elif status == "no_headroom":
            self.probe_failed.emit(job.kind, job.page_num, "no_headroom")
        else:
            logger.warning("object probe answer has no known status for page %s", job.page_num)
            self._retry_or_give_up(job, now)

    def _on_failed(self, job_id: int) -> None:
        job = self._jobs.pop(job_id, None)
        if job is None:
            if self._submitting:
                self._early[job_id] = (self._on_failed, ())
            return
        now = self._current_input(job)
        if self._is_stale(job, now):
            return
        self._retry_or_give_up(job, now)

    def _current_input(self, job: Job) -> table_objects.PageInput | None:
        """The page of a tables job as it is NOW (one new copy, built on first use), never the job's
        own input: an answer arrives at another time."""
        if job.kind != "tables":
            return None
        return table_objects.PageInput(self._model, job.page_num)

    def _is_stale(self, job: Job, now: table_objects.PageInput | None = None) -> bool:
        # A tables job belongs to one page state, keyed on the bytes detection reads (H3, D1):
        # once that is gone, every answer (complete, failure, crash) is dropped silently, with no
        # retry.  A page that cannot be read now is stale too.
        if job.kind != "tables":
            return False
        if self._model.doc is None:
            return True
        return not table_objects.key_is_current(self._model, job.key, now)

    def _retry_or_give_up(self, job: Job, now: table_objects.PageInput | None = None) -> None:
        if job.attempt == 1:
            self._submit(Job(job.kind, job.page_num, job.key, job.payloads, attempt=2))
            return
        table_objects.mark_table_analysis_failed(self._model, job.key, current=now)
        self.probe_failed.emit(job.kind, job.page_num, "crashed")
