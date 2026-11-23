"""Vector path editing, controller side (card B3: the index worker only).

``VectorEditCoordinator.ensure_index(page_num)`` reads the page's decoded streams and frame from the
model on the GUI thread (``PDFModel.vector_page_source``) and has them scanned on bytes alone, so the
live document is never touched off the GUI thread.

Default path (H21, rule 2): the scan runs in the one-shot ``object-probe`` child, kind ``vector-scan``,
through the application-wide ``ObjectProbeRunner`` (admission, the resource ledger, the quit gate's
service list and ``start_owned_child`` all apply there).  The parent makes a private directory in the
application temp, hands the streams (one concatenated payload plus a manifest of their lengths), the
frame and that directory in, the child writes ONE ``numpy.save`` file ``index.npy`` and prints its name.
The parent then loads and validates it (``model.vector_paths.transport``) on a registry-owned
``QThread`` (never on the GUI thread; a generation check drops the answer of a superseded request) and
the directory is deleted on every terminal path: by the loading worker, on cancel, and when the runner
reports the job retired (``ObjectProbeRunner.retired``: also at shutdown and after a killed child has
exited, where a held file is retried).  The child path has no progress events.  The scanner and numpy are
imported by the worker/child only; this module and ``PDFModel.vector_page_source`` do not load them.

``in_process=True`` keeps the earlier path (a ``QThread`` registered with ``WorkerRegistry``, running
``scan_page`` in this process) for tests and for a host without a contained child.  A generation
counter discards the answer of a superseded or cancelled request.  No UI hook-up here: the signals are
for the card that wires a view (B7).
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QThread, Signal, Slot

from controller.worker_registry import get_registry
from model.vector_paths import limits

if TYPE_CHECKING:
    from controller.pdf_controller import PDFController

logger = logging.getLogger(__name__)

_CHILD_KIND = "vector-scan"
_INDEX_FILE_NAME = "index.npy"  # the only name the child may print (it is also the only name it writes)
_REFUSAL_CODES = frozenset({"NO_FRAME", "TOO_LARGE", "SCAN_ERROR", "CHORD_CAP"})


class _IndexWorker(QThread):
    """In-process scan (``scan_page``); never reads a document.

    Every signal carries the generation of the request, so a late queued emission from a cancelled
    one can be dropped.  A cancelled scan emits nothing."""

    progress = Signal(int, int, int)  # done, total, generation
    done = Signal(object, int)  # VectorIndex, generation
    refused = Signal(str, int)  # VectorPageRefused.code, generation

    def __init__(self, streams: tuple[bytes, ...], frame: tuple[float, ...], generation: int) -> None:
        super().__init__()
        self._streams: tuple[bytes, ...] | None = streams
        self._frame = frame
        self._generation = int(generation)
        self._cancelled = False

    def request_cancel(self) -> None:
        """Non-blocking and idempotent: the scanner polls the flag every few thousand tokens."""
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled

    def _report(self, done: int, total: int) -> None:
        self.progress.emit(int(done), int(total), self._generation)

    def run(self) -> None:
        from model.vector_paths.scan import VectorPageRefused, VectorScanCancelled, scan_page

        streams, self._streams = self._streams, None  # the scan owns the only reference
        try:
            index = scan_page(
                streams or (), self._frame, cancel=self._is_cancelled, progress=self._report  # type: ignore[arg-type]
            )
        except VectorScanCancelled:
            return
        except VectorPageRefused as exc:
            logger.info("vector index refused: %s", exc)
            if not self._cancelled:
                self.refused.emit(exc.code, self._generation)
            return
        except Exception:
            logger.exception("vector index worker failed")
            if not self._cancelled:
                self.refused.emit("SCAN_ERROR", self._generation)
            return
        finally:
            streams = None
        if not self._cancelled:
            self.done.emit(index, self._generation)


class _LoadWorker(QThread):
    """Reads and validates the child's index file off the GUI thread, then deletes the job directory.

    The directory is removed by this thread right after the read (before the answer is emitted), so it
    is gone whatever the event loop does afterwards; a deletion the OS refuses is retried by the
    coordinator (``_on_load_finished``)."""

    done = Signal(object, int, int, float)  # VectorIndex, page_num, generation, load seconds
    failed = Signal(int, int)  # page_num, generation

    def __init__(self, directory: Path, page_num: int, generation: int) -> None:
        super().__init__()
        self.directory = directory
        self.page_num = int(page_num)
        self._generation = int(generation)

    def request_cancel(self) -> None:
        """The read is bounded by the payload budget and cannot be interrupted; the answer is dropped by
        the generation check instead."""

    def run(self) -> None:
        from model.vector_paths import transport

        index = None
        started = time.perf_counter()
        try:
            index = transport.load_index(self.directory / _INDEX_FILE_NAME)
        except Exception:
            logger.warning("vector-scan index file could not be loaded", exc_info=True)
        finally:
            shutil.rmtree(self.directory, ignore_errors=True)
        if index is None:
            self.failed.emit(self.page_num, self._generation)
        else:
            self.done.emit(index, self.page_num, self._generation, time.perf_counter() - started)


@dataclass
class _ChildJob:
    page_num: int
    directory: Path


class VectorEditCoordinator(QObject):
    """Owns the index request of one controller (``SearchCoordinator`` shape; B7 adds the rest)."""

    index_progress = Signal(int, int)  # done, total (in-process path only)
    index_done = Signal(int, object)  # page_num, VectorIndex
    index_refused = Signal(int, str)  # page_num, code (NO_FRAME | TOO_LARGE | SCAN_ERROR | CHORD_CAP)

    def __init__(self, controller: PDFController | Any, *, runner: Any = None, in_process: bool = False) -> None:
        super().__init__()
        self._c = controller
        self._generation = 0
        self._in_process = bool(in_process)
        self._page_num = 0
        # in-process path: every worker that has not finished (a superseded one counts until it exits)
        self._live: set[_IndexWorker] = set()
        # child path
        self._runner: Any = runner
        self._runner_connected = False
        self._jobs: dict[int, _ChildJob] = {}
        self._submitting = False
        # answers and retirements that arrived inside ``submit``: (kind, job id, answer)
        self._early: list[tuple[str, int, object]] = []
        self._retiring: set[int] = set()  # cancelled jobs the runner has not retired yet, by job id
        self._loaders: set[_LoadWorker] = set()  # index files being read (a superseded one counts until it exits)
        self._leftovers: list[Path] = []  # job directories that could not be removed yet
        self.last_load_seconds: float | None = None  # file load + validation of the last delivered index

    @property
    def busy(self) -> bool:
        """Something of this coordinator has not finished yet (cancelled work counts until it exits)."""
        return bool(self._live or self._jobs or self._loaders or self._retiring)

    # ------------------------------------------------------------------ requests

    def ensure_index(self, page_num: int) -> bool:
        """Start indexing ``page_num`` (1-based), superseding any earlier request.

        ``True``: a request runs and ``index_done`` or ``index_refused`` follows.  ``False``: nothing
        runs; a refusal of the model is announced through ``index_refused`` before returning, a
        refused admission (shutdown) is silent and reads nothing.  GUI thread only."""
        self.cancel()
        self._sweep()
        if get_registry().admission_closed:
            return False
        generation = self._generation
        try:
            streams, frame = self._c.model.vector_page_source(page_num)
        except Exception as exc:
            code = getattr(exc, "code", None)
            if not isinstance(code, str):
                logger.exception("vector_page_source failed for page %s", page_num)
                code = "SCAN_ERROR"
            self.index_refused.emit(int(page_num), code)
            return False
        self._page_num = int(page_num)
        if self._in_process:
            return self._start_in_process(streams, frame, generation)
        return self._start_child(int(page_num), streams, frame)

    def cancel(self) -> None:
        """Drop the answer of the running request and ask its worker or child to stop (never waits)."""
        self._generation += 1
        for worker in tuple(self._live):
            worker.request_cancel()
        for job_id, job in tuple(self._jobs.items()):
            del self._jobs[job_id]
            runner = self._runner
            if runner is not None:
                # Busy until the runner retires THIS job: a queued job is retired by ``cancel`` itself
                # (before it returns), a running one when its killed child has exited.
                self._retiring.add(job_id)
                try:
                    runner.cancel(job_id)
                except Exception:
                    logger.exception("vector-scan cancel failed")
                    self._retiring.discard(job_id)
            self._discard(job.directory)

    # ------------------------------------------------------------- in-process path

    def _start_in_process(self, streams: tuple[bytes, ...], frame: tuple[float, ...], generation: int) -> bool:
        worker = _IndexWorker(streams, frame, generation)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.refused.connect(self._on_refused)
        worker.finished.connect(self._on_worker_finished)
        self._live.add(worker)
        # The registry, not this object, answers application quit; it deletes the thread once it exited.
        if not get_registry().start_owned(worker, worker.request_cancel, dispose=True):
            self._live.discard(worker)
            return False
        return True

    @Slot(int, int, int)
    def _on_progress(self, done: int, total: int, generation: int) -> None:
        if generation == self._generation:
            self.index_progress.emit(done, total)

    @Slot(object, int)
    def _on_done(self, index: object, generation: int) -> None:
        if generation == self._generation:
            self.index_done.emit(self._page_num, index)

    @Slot(str, int)
    def _on_refused(self, code: str, generation: int) -> None:
        if generation == self._generation:
            self.index_refused.emit(self._page_num, code)

    @Slot()
    def _on_worker_finished(self) -> None:
        # Queued to the GUI thread; ``sender()`` is the worker that finished (not the newest one).  The
        # registry still holds the QThread until it has exited, so dropping our reference is safe.
        worker = self.sender()
        if isinstance(worker, _IndexWorker) and worker.isFinished():
            self._live.discard(worker)

    # ------------------------------------------------------------------ child path

    def _child_runner(self) -> Any:
        """The App-wide runner, or ``None`` without a ``QApplication`` (nothing to run a child on)."""
        if self._runner is None:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return None
            from controller.object_probe_runner import ObjectProbeRunner

            self._runner = ObjectProbeRunner.for_app(app)
        return self._runner

    def _adopt_runner(self, runner: Any) -> None:
        if not self._runner_connected:
            runner.finished.connect(self._on_runner_finished)
            runner.failed.connect(self._on_runner_failed)
            retired = getattr(runner, "retired", None)
            if retired is not None:
                retired.connect(self._on_runner_retired)
            self._runner_connected = True

    def _start_child(self, page_num: int, streams: tuple[bytes, ...], frame: tuple[float, ...] | None) -> bool:
        if len(streams) > limits.MAX_STREAMS:
            # The manifest of stream lengths is bounded: refuse typed, before a job or a directory exists.
            logger.info("vector-scan refused: %d content streams (cap %d)", len(streams), limits.MAX_STREAMS)
            self.index_refused.emit(page_num, "TOO_LARGE")
            return False
        runner = self._child_runner()
        if runner is None:
            self.index_refused.emit(page_num, "SCAN_ERROR")
            return False
        try:
            directory = Path(tempfile.mkdtemp(prefix="pdfed_vscan_"))
        except OSError:
            logger.exception("vector-scan temp directory could not be made")
            self.index_refused.emit(page_num, "SCAN_ERROR")
            return False
        head = json.dumps(
            {
                "frame": list(frame) if frame is not None else None,
                "dir": str(directory),
                "lengths": [len(s) for s in streams],
            }
        )
        # ONE stream payload and a manifest: the runner's wire header lists one size per payload, and the
        # child reads at most 64 KiB of it, so a page of many small streams must not widen it.
        payloads = (head.encode("ascii"), b"".join(streams))
        self._adopt_runner(runner)
        self._submitting = True
        self._early = []
        try:
            job_id = runner.submit(self, _CHILD_KIND, payloads, front=True)
        except Exception:
            logger.exception("vector-scan submit failed")
            self._submitting = False
            self._early = []
            self._discard(directory)
            self.index_refused.emit(page_num, "SCAN_ERROR")
            return False
        self._jobs[job_id] = _ChildJob(page_num, directory)
        early, self._early, self._submitting = self._early, [], False
        for kind, early_id, answer in early:
            if kind == "retired":
                self._retire(early_id)
            elif early_id == job_id:
                self._finish_child(job_id, answer)
        return True

    @Slot(int, object)
    def _on_runner_finished(self, job_id: int, answer: object) -> None:
        if self._submitting:
            self._early.append(("answer", job_id, answer))
            return
        if job_id in self._jobs:
            self._finish_child(job_id, answer)

    @Slot(int)
    def _on_runner_failed(self, job_id: int) -> None:
        if self._submitting:
            self._early.append(("answer", job_id, None))
            return
        if job_id in self._jobs:
            self._finish_child(job_id, None)

    @Slot(int)
    def _on_runner_retired(self, job_id: int) -> None:
        if self._submitting:
            self._early.append(("retired", job_id, None))
            return
        self._retire(job_id)

    def _retire(self, job_id: int) -> None:
        """The runner is done with ``job_id`` (answered, cancelled, killed child exited, or shutdown).

        A job of ours that never got an answer (shutdown) is dropped here with its directory, silently;
        every retirement retries the deletions the OS refused earlier (a killed child held a file)."""
        self._retiring.discard(job_id)
        job = self._jobs.pop(job_id, None)
        if job is not None:
            self._discard(job.directory)
        self._sweep()

    def _finish_child(self, job_id: int, answer: object) -> None:
        job = self._jobs.pop(job_id, None)
        if job is None:
            return
        code = "SCAN_ERROR"
        if isinstance(answer, dict):
            status = answer.get("status")
            if status == "complete":
                if answer.get("scan_file") == _INDEX_FILE_NAME:
                    self._start_load(job)  # delivers (or refuses) from the worker's signals
                    return
            elif status == "refused":
                wanted = answer.get("code")
                code = wanted if wanted in _REFUSAL_CODES else "SCAN_ERROR"
            elif status == "resource_limited":
                code = "TOO_LARGE"
        self._discard(job.directory)
        self.index_refused.emit(job.page_num, code)

    def _start_load(self, job: _ChildJob) -> None:
        """Read and validate the child's file on a registry-owned worker, which also deletes the directory.

        Admission closed (shutdown): nothing starts, the directory is deleted and nothing is announced."""
        worker = _LoadWorker(job.directory, job.page_num, self._generation)
        worker.done.connect(self._on_load_done)
        worker.failed.connect(self._on_load_failed)
        worker.finished.connect(self._on_load_finished)
        self._loaders.add(worker)
        if not get_registry().start_owned(worker, worker.request_cancel, dispose=True):
            self._loaders.discard(worker)
            self._discard(job.directory)

    @Slot(object, int, int, float)
    def _on_load_done(self, index: object, page_num: int, generation: int, seconds: float) -> None:
        if generation == self._generation:
            self.last_load_seconds = float(seconds)
            self.index_done.emit(page_num, index)

    @Slot(int, int)
    def _on_load_failed(self, page_num: int, generation: int) -> None:
        if generation == self._generation:
            self.index_refused.emit(page_num, "SCAN_ERROR")

    @Slot()
    def _on_load_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, _LoadWorker) and worker.isFinished():
            self._loaders.discard(worker)
            if worker.directory.exists():  # the worker's own deletion was refused (a scanner still holds it)
                self._leftovers.append(worker.directory)
            self._sweep()

    def _discard(self, directory: Path) -> None:
        """Delete a job directory; one the OS still holds (a killed child) is retried by ``_sweep``."""
        shutil.rmtree(directory, ignore_errors=True)
        if directory.exists():
            self._leftovers.append(directory)

    def _sweep(self) -> None:
        pending, self._leftovers = self._leftovers, []
        for directory in pending:
            self._discard(directory)
