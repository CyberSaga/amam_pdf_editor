from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from model import content_scan, table_objects, text_index_jobs
from model.text_block import page_entry_from_json
from utils import object_probe_platform

from controller.scan_verifier import ScanVerifier

logger = logging.getLogger(__name__)

_FAILURE_STATUSES = frozenset({"resource_limited", "analysis_failed", "containment_failed"})
#: answers that mark and cache nothing: a transient shortage, or a platform without the contained child
_NO_MARK_STATUSES = frozenset({"no_headroom", "unsupported_platform"})


def _parse_table_rects(raw) -> list[tuple[float, float, float, float]]:
    """The child's ``rects`` as validated floats: a list of 4-number, finite, non-inverted rects.
    Anything else raises ``ValueError``/``TypeError``/``OverflowError`` (a malformed answer)."""
    if not isinstance(raw, list):
        raise TypeError("rects is not a list")
    rects = []
    for rect in raw:
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError("a rect is not four numbers")
        values = []
        for v in rect:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TypeError("a rect coordinate is not a number")
            f = float(v)  # OverflowError for a huge int
            if not math.isfinite(f):
                raise ValueError("a rect coordinate is not finite")
            values.append(f)
        if values[2] < values[0] or values[3] < values[1]:
            raise ValueError("a rect is inverted")
        rects.append((values[0], values[1], values[2], values[3]))
    return rects


@dataclass
class Job:
    kind: str
    page_num: int
    key: tuple
    payloads: tuple[bytes, ...]
    attempt: int = 1
    #: ``(page number, set key)`` of a scan job: the frame its answer is valid for (D12)
    frame: tuple[int, tuple[bytes, ...]] | None = None
    #: handle generation the scan job was requested on: with the frame it is the job's identity (P1)
    generation: int = 0
    #: a text job a gesture waits on: queued before every waiting job, also on its retry
    front: bool = False
    #: ``(handle generation, content revision, page)`` a text job was requested at: it only dedups
    #: requests while the job is in flight, it never admits an answer (H3, F1)
    flight: tuple[int, int, int] | None = None
    #: submission order (kept on retry): the newest text job of a page owns the gesture waiting on it
    seq: int = 0


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
    #: the page's long stream was lexed in the background: an edit that was refused can be retried
    scan_verified = Signal(int)
    #: the page's text index is clean (installed from the child, or already clean)
    text_index_ready = Signal(int)
    probe_failed = Signal(str, int, str)
    #: ``(kind, page)``: an answer was dropped as stale or superseded (no message, no retry)
    probe_dropped = Signal(str, int)
    #: ``cancel_all`` ended: every job is gone, nothing will answer
    all_cancelled = Signal()

    def __init__(self, model, parent=None, *, runner=None):
        super().__init__(parent)
        self._model = model
        self._runner = runner
        self._runner_connected = False
        self._jobs: dict[int, Job] = {}
        self._submitting = 0
        # page -> (input, content revision) of a delivery being emitted; consumed once (A6.2)
        self._deliveries: dict[int, tuple[table_objects.PageInput, object]] = {}
        self._early: dict[int, tuple] = {}
        self._seq = 0
        #: key of the job whose terminal event is being emitted (``None`` outside an emit): the
        #: controller matches the event to its click by this identity, never by page alone
        self.terminal_key: tuple | None = None
        #: bytes key of the job the last ``request_text_index`` queued or matched: the job whose
        #: answer fits the page as it is now (the one a gesture must wait on)
        self.last_request_key: tuple | None = None
        #: background lex of long streams (the writers' parent-side scan, off the GUI thread)
        self.scan_verifier = ScanVerifier(model, self)
        self.scan_verifier.verified.connect(self.scan_verified)

    def request_verification(self, page_num: int, key: bytes, stream: bytes) -> bool:
        """Queue the background lex of one decoded stream of ``page_num`` for the writers."""
        return self.scan_verifier.request(self._model.handle_generation, page_num, key, stream)

    def request_pending_verifications(self) -> None:
        """Queue the long streams an edit was just refused for (``ObjectOpRefusal.ANALYSING``)."""
        for page_num, key, stream in self._model.take_verification_requests():
            self.request_verification(page_num, key, stream)

    def _request_verification_of_answered(self, job: Job) -> None:
        """After a scan answer is installed: lex each long stream of the job in the background, so
        the first edit of the page finds a verified scan."""
        for key, stream in zip(job.key, job.payloads, strict=False):
            if len(stream) > content_scan.MUTATION_INLINE_SCAN_LIMIT_BYTES:
                self.scan_verifier.request(job.generation, job.page_num, key, stream)

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

    def has_pending(self, kind: str, other_than_page: int | None = None) -> bool:
        """True while a job of ``kind`` is waiting for or running in the child (with
        ``other_than_page``: one of another page)."""
        return any(job.kind == kind and job.page_num != other_than_page for job in self._jobs.values())

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

    def _flight(self, page_num: int) -> tuple[int, int, int]:
        return (self._model.handle_generation, self._model.content_revision, int(page_num))

    def text_in_flight(self, page_num: int) -> bool:
        """True while a text job of this page, handle generation and content revision waits or runs."""
        flight = self._flight(page_num)
        return any(job.kind == "text" and job.flight == flight for job in self._jobs.values())

    def has_pending_text(self, page_num: int) -> bool:
        """True while a text job of this page (any bytes) waits or runs."""
        return any(job.kind == "text" and job.page_num == int(page_num) for job in self._jobs.values())

    def newest_text_key(self, page_num: int) -> tuple | None:
        """Bytes key of the newest text job of the page that waits or runs (the gesture's)."""
        jobs = [job for job in self._jobs.values() if job.kind == "text" and job.page_num == int(page_num)]
        return max(jobs, key=lambda job: job.seq).key if jobs else None

    def in_flight_text_key(self, page_num: int) -> tuple | None:
        """Key of the newest text job of the page's current (generation, revision, page) flight."""
        flight = self._flight(page_num)
        jobs = [job for job in self._jobs.values() if job.kind == "text" and job.flight == flight]
        return max(jobs, key=lambda job: job.seq).key if jobs else None

    def _emit_terminal(self, job: Job, signal, *args) -> None:
        self.terminal_key = job.key
        try:
            signal.emit(*args)
        finally:
            self.terminal_key = None

    def promote_text(self, page_num: int) -> None:
        """A gesture now waits on the page's waiting text job(s): move them to the front."""
        runner = self._runner
        promote = getattr(runner, "promote", None)
        if promote is None:
            return
        for job_id, job in self._jobs.items():
            if job.kind == "text" and job.page_num == int(page_num) and runner.is_waiting(job_id):
                job.front = True
                promote(job_id)

    def request_text_index(
        self, page_num: int, page_input: table_objects.PageInput | None = None, *, front: bool = True
    ) -> str:
        """Start a text-index job for the page.  Returns what happened:

        ``"queued"`` a job was submitted; ``"duplicate"`` a job of this (generation, revision,
        page) or of the same bytes key is already in flight (it is promoted when ``front``, and the
        caller waits for it); ``"inline"`` no contained child here, nothing queued (the in-process
        build serves the page); ``"failed"`` the page is out of range or its copy cannot be built.

        ``page_input`` is the gesture's one scratch copy; the in-flight check runs before it is
        built, so a repeated hover builds nothing.  Text is never refused: that is the caller's
        inline path."""
        model = self._model
        doc = model.doc
        if not doc or page_num < 1 or page_num > len(doc):
            return "failed"
        if not object_probe_platform.contained_probe_supported():
            return "inline"
        self.last_request_key = None
        if self.text_in_flight(page_num):
            if front:
                self.promote_text(page_num)
            self.last_request_key = self.in_flight_text_key(page_num)
            return "duplicate"
        page_input = table_objects.page_input_for(model, page_num, page_input)
        try:
            key = page_input.key
            payload = page_input.payload  # GUI thread: the only reader
        except Exception:  # logged by PageInput: no copy, no job; the caller builds inline
            return "failed"
        if any(job.kind == "text" and job.key == key for job in self._jobs.values()):
            if front:
                self.promote_text(page_num)
            self.last_request_key = key  # the job of THESE bytes, not the newest job of the page
            return "duplicate"
        self._seq += 1
        self._submit(
            Job(
                "text",
                int(page_num),
                key,
                (payload, str(int(page_num) - 1).encode("ascii")),
                front=front,
                flight=self._flight(page_num),
                seq=self._seq,
            )
        )
        self.last_request_key = key
        return "queued"

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
        frame = (page_num, model.image_scan_set_key(page_num, scan_input))
        generation = model.handle_generation
        # A job is one (handle generation, page, set key): the same missing long streams on another
        # handle or after a short stream changed are another frame and need their own answer (P1).
        if any(
            job.kind == "scan" and job.frame == frame and job.generation == generation and job.key == key
            for job in self._jobs.values()
        ):
            return
        self._submit(
            Job("scan", page_num, key, tuple(stream for _key, stream in wanted), frame=frame, generation=generation)
        )

    def _submit(self, job: Job) -> None:
        # The runner may answer inside ``submit`` (no headroom, a refused start): keep such an
        # answer until the job id is registered, then deliver it.
        self._submitting += 1
        try:
            runner = self._ensure_runner()
            if job.front:
                job_id = runner.submit(self, job.kind, job.payloads, front=True)
            else:
                job_id = runner.submit(self, job.kind, job.payloads)
        finally:
            self._submitting -= 1
        self._jobs[job_id] = job
        early = self._early.pop(job_id, None)
        if early is not None:
            handler, args = early
            handler(job_id, *args)

    def retire(self) -> None:
        """Non-blocking, for a window going away: cancel and stop accepting; the verification worker
        stays in the application's worker registry until it has finished.  (The child process is the
        runner's own shutdown.)"""
        self.scan_verifier.retire()

    def cancel_all(self) -> None:
        text_jobs = sorted((job for job in self._jobs.values() if job.kind == "text"), key=lambda job: job.seq)
        if self._runner is not None:
            self._runner.cancel_owner(self)
        self.scan_verifier.cancel_all()
        self._jobs.clear()
        self._early.clear()
        # A cancelled text job never answers: tell the controller, or its status and the gesture
        # waiting on it would stay (the next gesture then requests again).
        for job in text_jobs:
            self._emit_terminal(job, self.probe_dropped, "text", job.page_num)
        self.all_cancelled.emit()

    def _drop(self, job: Job) -> None:
        """An answer for a frame that is gone: no cache, no mark, no message; tell the controller."""
        self._emit_terminal(job, self.probe_dropped, job.kind, job.page_num)

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
        if job.kind == "text":
            self._on_text_answer(job, answer, status, now)
            return
        if status == "complete":
            try:
                rects = _parse_table_rects(answer["rects"])
            except (KeyError, TypeError, ValueError, OverflowError):
                logger.warning("object probe answer malformed for page %s", job.page_num)
                self._retry_or_give_up(job, now)
                return
            if table_objects.store_table_rects(self._model, job.key, rects, current=now):
                # The slot of this delivery reuses ``now`` (one scratch copy, not two); it is held
                # only while the signal is emitted, never across a later change.
                entry = (now, self._model.content_revision)
                self._deliveries[job.page_num] = entry
                try:
                    self.tables_ready.emit(job.page_num)
                finally:
                    if self._deliveries.get(job.page_num) is entry:
                        del self._deliveries[job.page_num]
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

    def take_delivery_input(self, page_num: int) -> tuple[table_objects.PageInput, object] | None:
        """The input of the page's delivery being emitted, handed out ONCE (it is cleared), only for
        the same page and model and only if the model's content revision has not moved since (a
        slot that ran earlier and edited the page).  Returns ``(input, revision)``, the revision the
        input was built at, so the user can recheck it at use; ``None``: build your own."""
        entry = self._deliveries.pop(int(page_num), None)
        if entry is None:
            return None
        held, revision = entry
        if held.page_num != int(page_num) or held.model is not self._model:
            return None
        if self._model.doc is None or self._model.content_revision != revision:
            return None
        return held, revision

    def _current_input(self, job: Job) -> table_objects.PageInput | None:
        """The page of a tables job as it is NOW (one new copy, built on first use), never the job's
        own input: an answer arrives at another time.  ``None`` for a scan job (content keys)."""
        if job.kind not in ("tables", "text"):
            return None
        return table_objects.PageInput(self._model, job.page_num)

    def _is_stale(self, job: Job, now: table_objects.PageInput | None = None) -> bool:
        # A tables job belongs to one handle and one page state, keyed on the bytes detection reads
        # (H3, D1): once that is gone, every answer (complete, failure, crash) is dropped silently,
        # with no retry.  A page that cannot be read now is stale too.  A scan job's frame is
        # checked by ``_scan_frame_current``.
        if job.kind not in ("tables", "text"):
            return False
        if self._model.doc is None:
            return True
        return not table_objects.key_is_current(self._model, job.key, now)

    def _scan_frame_current(self, job: Job, scan_input=None) -> bool:
        """True while the page's scan set is the one the job was requested for (D12).  A caller
        that goes on to use the page's scan set passes its own ``scan_input`` and keeps it."""
        if job.frame is None:
            return True
        if job.generation != self._model.handle_generation:
            return False  # another handle (Save As, a closed tab): its failure is no fact about this one
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
                rows = answer["scans"]
                if type(rows) is not list or len(rows) != len(job.key):
                    raise ValueError("wrong number of scans")
                # the admission limit is checked on the raw rows, before any record is built (A6)
                if any(type(obj) is not dict or type(obj["dos"]) is not list for obj in rows):
                    raise ValueError("malformed scan row")
                records = sum(max(1, len(obj["dos"])) for obj in rows)
            except Exception:
                logger.warning("object probe scan answer malformed for page %s", job.page_num)
                if current:
                    self._retry_or_give_up(job)
                else:
                    self._drop(job)
                return
            if records > content_scan.SCAN_CACHE_MAX_RECORDS:
                logger.warning("object probe scan answer over the record limit for page %s", job.page_num)
                if current:
                    self._fail_scan(job, "resource_limited")
                else:
                    self._drop(job)
                return
            try:
                scans = [content_scan.from_json(obj) for obj in rows]
            except Exception:  # an answer is untrusted: any failure to read it is one malformed answer
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
                self.image_scan_ready.emit(job.page_num)  # the click it resolves runs before the worker starts
                self._request_verification_of_answered(job)
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

    def _on_text_answer(self, job: Job, answer, status, now: table_objects.PageInput | None) -> None:
        """A text answer for a page whose bytes still match the job's key (the caller checked).
        ``now`` is the one current copy: the decoder, the installer and the key check share it."""
        if status == "complete":
            try:
                entry = page_entry_from_json(answer["entry"])
                result = text_index_jobs.install_text_index(self._model, job.key, entry, now)
            except Exception as exc:  # a bad answer, or an installer that failed: one terminal outcome
                logger.warning("text index answer refused for page %s: %s", job.page_num, exc)
                text_index_jobs.mark_failed(self._model, job.key)
                self._emit_text_failed(job, "analysis_failed")
                return
            if result == "stale":
                self._drop(job)
            else:  # installed, or the page was clean already and keeps its index
                self._emit_terminal(job, self.text_index_ready, job.page_num)
        elif status in _FAILURE_STATUSES:
            text_index_jobs.mark_failed(self._model, job.key)
            self._emit_text_failed(job, status)
        elif status in _NO_MARK_STATUSES:
            self._emit_text_failed(job, status)
        else:
            logger.warning("object probe answer has no known status for page %s", job.page_num)
            self._retry_or_give_up(job, now)

    def _emit_text_failed(self, job: Job, reason: str) -> None:
        """A failure of a job of an older handle says nothing about this handle's gesture (the key
        is bytes, so its mark stands): it reaches the controller as a drop, never as a failure."""
        if job.flight is not None and job.flight[0] != self._model.handle_generation:
            self._emit_terminal(job, self.probe_dropped, job.kind, job.page_num)
        else:
            self._emit_terminal(job, self.probe_failed, job.kind, job.page_num, reason)

    def _fail_scan(self, job: Job, reason: str) -> None:
        """Mark the job's frame failed (no retry, nothing cached) and report ``reason``."""
        self._mark_scan_failed(job, reason)
        self.probe_failed.emit(job.kind, job.page_num, reason)

    def _mark_scan_failed(self, job: Job, reason: str) -> None:
        if job.frame is not None:
            self._model.mark_image_scan_failed(*job.frame, reason)

    def _retry_or_give_up(self, job: Job, now: table_objects.PageInput | None = None) -> None:
        if job.attempt == 1:
            self._submit(
                Job(
                    job.kind,
                    job.page_num,
                    job.key,
                    job.payloads,
                    attempt=2,
                    frame=job.frame,
                    generation=job.generation,
                    front=job.front,
                    flight=job.flight,
                    seq=job.seq,
                )
            )
            return
        if job.kind == "scan":
            self._mark_scan_failed(job, "crashed")
        elif job.kind == "text":
            text_index_jobs.mark_failed(self._model, job.key)
            self._emit_text_failed(job, "crashed")
            return
        else:
            table_objects.mark_table_analysis_failed(self._model, job.key, current=now)
        self.probe_failed.emit(job.kind, job.page_num, "crashed")
