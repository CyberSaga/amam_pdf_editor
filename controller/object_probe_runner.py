from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, Signal, Slot
from src.object_probe.limits import TEXT_ANSWER_MAX_BYTES
from src.render_worker.admission import object_probe_memory_limit
from src.render_worker.memory import read_system_memory
from utils import object_probe_platform
from utils.native_handle_inheritance import prepare_owned_qprocess_start

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 2
#: front jobs that may go ahead of one waiting job before it runs next (no starvation)
MAX_FRONT_JUMPS = 3
_STATUSES = frozenset({"complete", "resource_limited", "analysis_failed", "containment_failed"})
# The result key each kind's complete answer carries, and the type it must have.  Any other kind's
# key, a null, or a wrong type makes the answer malformed (the usual failure path).
_RESULT_KEYS = {"tables": ("rects", list), "scan": ("scans", list), "text": ("entry", dict)}
# Advisory text a library prints on stdout may share the stream with the answer line.
_STDOUT_SLACK_BYTES = 64 * 1024


@dataclass
class _Job:
    job_id: int
    owner: object
    kind: str
    payloads: tuple[bytes, ...]
    mem: int = 0
    #: front jobs that were queued ahead of this waiting job (bounded: ``MAX_FRONT_JUMPS``)
    jumped: int = 0


class ObjectProbeRunner(QObject):
    """One App-wide one-shot ``object-probe`` child at a time (H2, H16).

    Knows nothing about PDFs: a job is ``(owner, kind, payload bytes)`` and the answer is the
    parsed JSON dict.  Jobs wait in a FIFO; a cancelled running job is killed and stays silent.
    No size cap and no timer: a slow analysis is a long wait with a live window, not a failure.
    The service-loop contract of ``main.py`` (``_process``, ``shutdown()``, ``stopped``) is the
    one ``RecentFileProbe`` has.
    """

    finished = Signal(int, object)
    failed = Signal(int)
    stopped = Signal()

    def __init__(self, parent=None, *, ledger=None, process_factory=QProcess):
        super().__init__(parent)
        self._ledger = ledger
        self._process_factory = process_factory
        self._lease = None
        self._process = None
        self._running: _Job | None = None
        self._cancelled = False
        self._oversize = False
        self._closing = False
        self._queue: deque[_Job] = deque()
        self._buffer = bytearray()
        self._next_id = 1

    @property
    def idle(self) -> bool:
        return self._process is None and not self._queue

    @classmethod
    def for_app(cls, app, *, ledger=None):
        runner = getattr(app, "_pdf_object_probe", None)
        if runner is None or runner._closing:
            runner = cls(app, ledger=ledger)
            app._pdf_object_probe = runner
        elif ledger is not None and runner._ledger is None:
            runner._ledger = ledger
        return runner

    def is_waiting(self, job_id: int) -> bool:
        return any(job.job_id == job_id for job in self._queue)

    def submit(self, owner: object, kind: str, payloads: tuple[bytes, ...], *, front: bool = False) -> int:
        """Queue a job.  ``front`` puts it before every waiting job (a gesture is waiting on it);
        the running job is never killed for it."""
        job = _Job(self._next_id, owner, kind, tuple(payloads))
        self._next_id += 1
        if self._closing:
            return job.job_id
        if front:
            self._insert_front(job)
        else:
            self._queue.append(job)
        if self._process is None:
            self._start_next()
        return job.job_id

    def _insert_front(self, job: _Job) -> None:
        """Queue ``job`` ahead of the waiting jobs, except those already jumped ``MAX_FRONT_JUMPS``
        times: such a job is not starved, it runs before any further front job."""
        waiting = list(self._queue)
        index = 0
        for position, other in enumerate(waiting):
            if other.jumped >= MAX_FRONT_JUMPS:
                index = position + 1
        for other in waiting[index:]:
            other.jumped += 1
        waiting.insert(index, job)
        self._queue = deque(waiting)

    def promote(self, job_id: int) -> None:
        """Move a WAITING job to the front (a gesture now waits on it); the running job is untouched."""
        for job in self._queue:
            if job.job_id == job_id:
                self._queue = deque(other for other in self._queue if other is not job)
                self._insert_front(job)
                return

    def cancel(self, job_id: int) -> None:
        self._queue = deque(job for job in self._queue if job.job_id != job_id)
        if self._running is not None and self._running.job_id == job_id:
            self._kill_running()

    def cancel_owner(self, owner: object) -> None:
        self._queue = deque(job for job in self._queue if job.owner is not owner)
        if self._running is not None and self._running.owner is owner:
            self._kill_running()

    def _kill_running(self) -> None:
        self._cancelled = True
        if self._process is not None:
            self._process.kill()

    def _release_lease(self) -> None:
        lease, self._lease = self._lease, None
        if lease is not None:
            self._ledger.retire_process(lease)
            self._ledger.process_exited(lease)

    def _start_next(self) -> None:
        while self._queue and self._process is None and not self._closing:
            job = self._queue.popleft()
            if not object_probe_platform.contained_probe_supported():
                # Not a transient shortage: no contained child exists here, and an uncontained one
                # is never launched. Decided before admission reads any memory.
                logger.info("Object probe not started: unsupported platform")
                self.finished.emit(job.job_id, {"v": PROTOCOL_VERSION, "status": "unsupported_platform"})
                continue
            limit = object_probe_memory_limit(read_system_memory())
            if limit is None:
                logger.info("Object probe not started: no memory headroom")
                self.finished.emit(job.job_id, {"v": PROTOCOL_VERSION, "status": "no_headroom"})
                continue
            job.mem = limit
            if self._ledger is not None:
                # Required, as the metadata probe. The ledger only keeps accounts: the Job Object
                # cap the child applies to itself is the safety mechanism (H24).
                self._lease = self._ledger.try_reserve("object-probe", "process", limit, required=True)
                if self._lease is None:
                    logger.info("Object probe deferred: resource ledger refused the charge")
                    self.failed.emit(job.job_id)
                    continue
            process = self._process_factory(self)
            from src.render_worker.launch import child_launch

            program, args = child_launch("object-probe")
            process.setProgram(program)
            process.setArguments(args)
            process.started.connect(self._started)
            process.readyReadStandardOutput.connect(self._read)
            process.finished.connect(self._finished)
            process.errorOccurred.connect(self._error)
            try:
                prepare_owned_qprocess_start()
            except (OSError, RuntimeError):
                logger.warning("Object probe not started: native reader inheritance guard failed", exc_info=True)
                self._release_lease()
                process.deleteLater()
                self.failed.emit(job.job_id)
                continue
            self._process = process
            self._running = job
            self._cancelled = False
            self._oversize = False
            self._buffer.clear()
            process.start()

    @Slot()
    def _started(self) -> None:
        job = self._running
        if self._process is None or job is None:
            return
        header = json.dumps(
            {"v": PROTOCOL_VERSION, "kind": job.kind, "sizes": [len(p) for p in job.payloads], "mem": job.mem}
        ).encode("utf-8")
        self._process.write(header + b"\n" + b"".join(job.payloads))
        self._process.closeWriteChannel()

    @Slot()
    def _read(self) -> None:
        if self._process is not None:
            self._buffer.extend(bytes(self._process.readAllStandardOutput()))
            job = self._running
            if (
                job is not None
                and job.kind == "text"
                and not self._oversize
                and len(self._buffer) > TEXT_ANSWER_MAX_BYTES + _STDOUT_SLACK_BYTES
            ):
                # The GUI never parses more than the cap: stop the child, answer resource_limited.
                self._oversize = True
                self._buffer.clear()
                self._process.kill()

    @Slot()
    def _error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finished(-1)

    @staticmethod
    def _parse(buffer: bytes, kind: str | None = None) -> dict | None:
        # The library may print advisory text on stdout (even at exit): the answer is the line that
        # parses as a versioned JSON object, wherever it sits.
        for line in buffer.splitlines():
            if kind == "text" and len(line) > TEXT_ANSWER_MAX_BYTES:
                # Whitespace padding must not slip a long line past the stdout cap.
                continue
            try:
                answer = ObjectProbeRunner._answer_of(line, kind)
            except Exception:  # RecursionError, TypeError, OverflowError ...: not an answer line
                logger.warning("Object probe output line rejected")
                continue
            if answer is not None:
                return answer
        return None

    @staticmethod
    def _answer_of(line: bytes, kind: str | None) -> dict | None:
        answer = json.loads(line)
        if not isinstance(answer, dict) or answer.get("v") != PROTOCOL_VERSION:
            return None
        status = answer.get("status")
        if type(status) is not str or status not in _STATUSES:
            return None
        # A complete answer carries its kind's result (``rects`` / ``scans`` / ``entry``) with
        # the right type and no other kind's key; any other status carries none.
        result_keys = [key for key, _ in _RESULT_KEYS.values() if key in answer]
        if status != "complete":
            return None if result_keys else answer
        if kind in _RESULT_KEYS:
            key, want = _RESULT_KEYS[kind]
            ok = result_keys == [key] and isinstance(answer[key], want)
        else:
            ok = len(result_keys) == 1
        return answer if ok else None

    @Slot()
    def _finished(self, exit_code: int = 0, _status=None) -> None:
        self._read()
        process, self._process = self._process, None
        job, self._running = self._running, None
        cancelled, self._cancelled = self._cancelled, False
        oversize, self._oversize = self._oversize, False
        if process is not None:
            self._release_lease()
            process.deleteLater()
        if job is not None and not cancelled and not self._closing:
            if oversize:
                answer = {"v": PROTOCOL_VERSION, "status": "resource_limited"}
            else:
                try:
                    answer = self._parse(bytes(self._buffer), job.kind) if exit_code == 0 else None
                except Exception:  # never leave the queue stalled on a hostile answer
                    logger.warning("Object probe answer could not be parsed")
                    answer = None
            if answer is None:
                self.failed.emit(job.job_id)
            else:
                self.finished.emit(job.job_id, answer)
        self._buffer.clear()
        if self._closing:
            self.stopped.emit()
        else:
            self._start_next()

    @Slot()
    def shutdown(self) -> None:
        self._closing = True
        self._queue.clear()
        if self._process is None:
            self.stopped.emit()
        else:
            self._kill_running()
