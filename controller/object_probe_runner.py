from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, Signal, Slot
from src.render_worker.admission import object_probe_memory_limit
from src.render_worker.memory import read_system_memory
from utils import object_probe_platform
from utils.native_handle_inheritance import prepare_owned_qprocess_start

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 2
_STATUSES = frozenset({"complete", "resource_limited", "analysis_failed", "containment_failed"})


@dataclass
class _Job:
    job_id: int
    owner: object
    kind: str
    payloads: tuple[bytes, ...]
    mem: int = 0


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

    def submit(self, owner: object, kind: str, payloads: tuple[bytes, ...]) -> int:
        job = _Job(self._next_id, owner, kind, tuple(payloads))
        self._next_id += 1
        if self._closing:
            return job.job_id
        self._queue.append(job)
        if self._process is None:
            self._start_next()
        return job.job_id

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

    @Slot()
    def _error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finished(-1)

    @staticmethod
    def _parse(buffer: bytes) -> dict | None:
        # The library may print advisory text on stdout (even at exit): the answer is the line that
        # parses as a versioned JSON object, wherever it sits.
        for line in buffer.splitlines():
            try:
                answer = json.loads(line)
            except ValueError:
                continue
            if not isinstance(answer, dict) or answer.get("v") != PROTOCOL_VERSION:
                continue
            status = answer.get("status")
            # A complete answer carries its kind's result: ``rects`` (tables) or ``scans`` (scan).
            if status not in _STATUSES or ("rects" in answer or "scans" in answer) != (status == "complete"):
                continue
            return answer
        return None

    @Slot()
    def _finished(self, exit_code: int = 0, _status=None) -> None:
        self._read()
        process, self._process = self._process, None
        job, self._running = self._running, None
        cancelled, self._cancelled = self._cancelled, False
        if process is not None:
            self._release_lease()
            process.deleteLater()
        if job is not None and not cancelled and not self._closing:
            answer = self._parse(bytes(self._buffer)) if exit_code == 0 else None
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
