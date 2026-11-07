from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QImage

from src.render_worker.protocol import MAX_IMAGE_BYTES, MAX_LOAD_BYTES, FrameDecoder, ProtocolError, encode_prefix
from src.render_worker.memory import peak_working_set_mb
from src.render_worker.resource_ledger import ResourceLedger, ResourceLease
from utils.helpers import qimage_from_samples

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileRef:
    path: str
    size: int
    mtime_ns: int
    password: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class DocSource:
    doc_key: str
    file: FileRef | None
    snapshot_provider: Callable[[], bytes | None] = field(repr=False)
    is_current: Callable[[], bool] = field(default=lambda: True, repr=False)
    watermarks_json: bytes = field(default=b'[]', repr=False)

    def __post_init__(self) -> None:
        if type(self.watermarks_json) is not bytes:
            raise ValueError('invalid watermark source')
        if self.watermarks_json != b'[]':
            if self.file is not None:
                raise ValueError('overlay requires an unbaked snapshot')
            from model.watermark_raster import decode_watermark_recipe
            decode_watermark_recipe(self.watermarks_json)


@dataclass(frozen=True)
class RenderJob:
    job_id: str
    owner: str
    lane: str
    doc: DocSource
    page_index: int
    scale: float
    color_profile: str
    kind: str = 'page'
    foreground_intent: str | None = None
    promotion_allowed: bool = True


@dataclass(frozen=True)
class JobOutcome:
    status: str
    image: QImage | None = None


class RenderProcessClient(QObject):
    """GUI-thread scheduler for one optional, replaceable raster process.

    Only bound slots receive process signals. Disconnect before disposing a
    process so a late finished/readyRead cannot affect its replacement.
    """

    job_done = Signal(str, object)
    stopped = Signal()

    def __init__(self, parent=None, *, process_factory=QProcess,
                 python_executable=None, monotonic=time.monotonic,
                 trim_thumbnail_store=False, retain_display_lists=False,
                 resource_ledger: ResourceLedger | None = None,
                 process_reservation_bytes: int | None = None,
                 thumbnail_trim_interval: int = 1):
        super().__init__(parent)
        if type(thumbnail_trim_interval) is not int or not 1 <= thumbnail_trim_interval <= 16:
            raise ValueError('thumbnail trim interval must be an integer in 1..16')
        self._thumbnail_trim_interval = thumbnail_trim_interval
        # Optional adapter only: the App has no qualified native envelope yet.
        # Unknown size refuses startup when a ledger is supplied; never guess.
        self._resource_ledger = resource_ledger
        self._process_reservation_bytes = process_reservation_bytes
        self._process_lease: ResourceLease | None = None
        self._factory = process_factory
        self._retain_display_lists = retain_display_lists
        self._python = python_executable or sys.executable
        self._venv_launcher = None
        if python_executable is None and sys.platform == 'win32' and sys.prefix != sys.base_prefix:
            # CPython's Windows venv executable is a redirector: QProcess.kill
            # would end only that launcher. Use the same interpreter directly,
            # with CPython's launcher hint preserving the venv path discovery.
            self._venv_launcher = sys.executable
            self._python = sys._base_executable
        self._clock = monotonic
        self._trim_thumbnail_store = trim_thumbnail_store
        self._memory_reader = peak_working_set_mb
        self._process = None
        self._process_connections = []
        self._retiring = False
        self._active_cancelled = False
        self._recall_at = 0.
        self._worker_pid = 0
        self._ready = False
        self._disabled = False
        self._closing = False
        self._owners: set[str] = set()
        self._queue: list[RenderJob] = []
        self._active: RenderJob | None = None
        self.loaded_key: str | None = None
        self._loaded_watermarks_json = b'[]'
        self._loaded_owner: str | None = None
        self._loading = False
        self._path_loading = False
        self._deadline = 0.
        self._decoder = FrameDecoder(max_body=MAX_IMAGE_BYTES)
        self._writes: deque[memoryview] = deque()
        self._crashes: deque[float] = deque()
        self._consecutive_failures = 0
        self._held = 0
        self._deferred: list[tuple[str, JobOutcome]] = []
        self._stderr_window = self._clock()
        self._stderr_count = 0
        self.metrics = {'doc_loads': 0, 'ipc_bytes': 0, 'images': 0,
                        'frame_gui_ms': [], 'starts': 0, 'fallbacks': 0,
                        'child_peak_mb': None, 'superseded': 0, 'recalls': 0,
                        'display_list_builds': 0, 'display_list_hits': 0}
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._check_deadline)
        self._recall_timer = QTimer(self)
        self._recall_timer.setSingleShot(True)
        self._recall_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._recall_timer.timeout.connect(self._check_deadline)

    @property
    def ready(self):
        return self._ready and not self._retiring and not self._disabled and not self._closing

    @property
    def pid(self):
        return self._worker_pid if self._process else 0

    def register_owner(self):
        owner = uuid.uuid4().hex
        self._owners.add(owner)
        return owner

    def release_owner(self, owner):
        self._owners.discard(owner)
        for job in list(self._queue):
            if job.owner == owner:
                self.cancel(job.job_id, 'owner_released')
        if self._active and self._active.owner == owner:
            self.cancel(self._active.job_id, 'owner_released')
        if self._loaded_owner == owner and self.loaded_key and self.ready:
            self._send({'type': 'drop_doc', 'doc_key': self.loaded_key})
            self.loaded_key = None
            self._loaded_owner = None

    def release_document(self, owner, session_id):
        def matches(job):
            return job.owner == owner and job.doc.doc_key.split('@', 1)[0] == session_id

        for job in list(self._queue):
            if matches(job):
                self.cancel(job.job_id)
        if self._active and matches(self._active):
            self.cancel(self._active.job_id, retire=True)
        if (self.loaded_key and self._loaded_owner == owner
                and self.loaded_key.split('@', 1)[0] == session_id and self.ready):
            self._send({'type': 'drop_doc', 'doc_key': self.loaded_key})
            self.loaded_key = self._loaded_owner = None

    def sample_memory(self):
        value = self._memory_reader(self.pid)
        if value is not None:
            self.metrics['child_peak_mb'] = max(self.metrics['child_peak_mb'] or 0., value)

    @Slot()
    def start(self):
        if self._process is not None or self._disabled or self._closing:
            return
        if self._resource_ledger is not None:
            self._process_lease = self._resource_ledger.try_reserve(
                'render:' + uuid.uuid4().hex, 'process', self._process_reservation_bytes,
                compute_slots=1)
            if self._process_lease is None:
                self._drain_unavailable()
                return
        try:
            self._start_process()
        except Exception:
            logger.exception('Render worker startup/setup failed')
            self._disabled = True
            if self._process is None:
                self._release_process_lease()
            else:
                self._dispose()
            self._finish(JobOutcome('unavailable'))
            self._drain_unavailable()

    def _start_process(self):
        process = self._factory(self)
        self._process = process
        self._decoder = FrameDecoder(max_body=MAX_IMAGE_BYTES)
        self._writes.clear()
        self._ready = False
        self.loaded_key = None
        self._loaded_owner = None
        env = QProcessEnvironment.systemEnvironment()
        root = str(Path(__file__).resolve().parents[2])
        env.insert('PYTHONPATH', root + os.pathsep + os.environ.get('PYTHONPATH', ''))
        env.insert('PYTHONIOENCODING', 'utf-8')
        env.insert('PYTHONUTF8', '1')
        if self._venv_launcher:
            env.insert('__PYVENV_LAUNCHER__', self._venv_launcher)
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(root)
        for signal, slot in ((process.readyReadStandardOutput, self._read_stdout),
                             (process.readyReadStandardError, self._read_stderr),
                             (process.bytesWritten, self._flush_writes),
                             (process.finished, self._exited),
                             (process.errorOccurred, self._process_error)):
            signal.connect(slot)
            self._process_connections.append((signal, slot))
        from utils.native_handle_inheritance import prepare_owned_qprocess_start

        prepare_owned_qprocess_start()
        self._deadline = self._clock() + 120
        self._timer.start()
        self.metrics['starts'] += 1
        process.start(self._python, ['-m', 'src.render_worker.worker_main'])

    def submit(self, job):
        if job.owner not in self._owners:
            self._report(job.job_id, JobOutcome('owner_released'), deferred=True)
        elif self._disabled or self._closing:
            self._report(job.job_id, JobOutcome('unavailable'), deferred=True)
        else:
            self._queue.append(job)
            self.start()
            self._schedule_recall()
            self._pump()

    def cancel(self, job_id, status='cancelled', *, retire=False):
        for job in list(self._queue):
            if job.job_id == job_id:
                self._queue.remove(job)
                self._report(job_id, JobOutcome(status), deferred=True)
                return
        if self._active and self._active.job_id == job_id:
            if not self._active_cancelled:
                self._active_cancelled = True
                self.metrics['superseded'] += 1
                self._report(job_id, JobOutcome(status), deferred=True)
            if status == 'owner_released' or retire:
                self._dispose()
                self._finish(JobOutcome(status))
                self.start()
            else:
                self._schedule_recall()

    def _schedule_recall(self):
        active = self._active
        foreground = any(job.lane == 'page' for job in self._queue)
        if active and foreground and (self._active_cancelled or active.lane != 'page'):
            if not self._recall_at:
                self._recall_at = self._clock() + .150
                self._recall_timer.start(150)
        else:
            self._recall_at = 0.
            self._recall_timer.stop()

    def _send(self, header, body=b''):
        self._writes.append(memoryview(encode_prefix(header, len(body))))
        if body:
            self._writes.append(memoryview(body))
        self._flush_writes()

    @Slot()
    def _flush_writes(self, *_args):
        process = self._process
        if process is None or self._retiring:
            return
        while self._writes and process.bytesToWrite() < 1024 * 1024:
            part = self._writes[0]
            count = process.write(bytes(part[:256 * 1024]))
            if count < 0:
                self._lost()
                return
            if count == 0:
                return
            self.metrics['ipc_bytes'] += count
            if count == len(part):
                self._writes.popleft()
            else:
                self._writes[0] = part[count:]

    def _pump(self):
        if self._active or not self.ready or not self._queue:
            return
        eligible = [job for job in self._queue if not (self._held and job.doc.file is not None)]
        if not eligible:
            return
        job = next((item for item in eligible if item.lane == 'page'), eligible[0])
        self._queue.remove(job)
        self._active = job
        self._active_cancelled = False
        self._recall_at = 0.
        self._deadline = self._clock() + 120
        if not job.doc.is_current():
            self._finish(JobOutcome('stale'))
            return
        if (self.loaded_key == job.doc.doc_key and self._loaded_owner == job.owner
                and self._loaded_watermarks_json == job.doc.watermarks_json):
            self._render()
            return
        try:
            if self.loaded_key:
                self._send({'type': 'drop_doc', 'doc_key': self.loaded_key})
            self.loaded_key = None
            file = job.doc.file
            if file:
                if file.size > MAX_LOAD_BYTES:
                    self._finish(JobOutcome('oversize'))
                    return
                header = {'type': 'load_path', 'doc_key': job.doc.doc_key,
                          'path': file.path, 'size': file.size, 'mtime_ns': file.mtime_ns}
                body = (file.password or '').encode('utf-8')
                self._path_loading = True
            else:
                body = job.doc.snapshot_provider()
                if body is None:
                    self._finish(JobOutcome('stale'))
                    return
                if len(body) > MAX_LOAD_BYTES:
                    self._finish(JobOutcome('oversize'))
                    return
                header = {'type': 'load_bytes', 'doc_key': job.doc.doc_key}
                if job.doc.watermarks_json != b'[]':
                    header['watermarks_json'] = job.doc.watermarks_json.decode('utf-8')
                    header['overlay_schema'] = 1
            self._loading = True
            self.metrics['doc_loads'] += 1
            self._send(header, body)
        except Exception:
            self._finish(JobOutcome('unavailable'))

    def _render(self):
        job = self._active
        if not job:
            return
        if not job.doc.is_current():
            self._finish(JobOutcome('stale'))
            return
        header = {'type': 'render', 'job': job.job_id, 'doc_key': job.doc.doc_key,
                    'page': job.page_index, 'scale': job.scale,
                    'profile': job.color_profile, 'kind': job.kind,
                    'trim_store': self._trim_thumbnail_store and job.kind == 'thumb',
                    'trim_store_interval': self._thumbnail_trim_interval,
                    'retain_display_lists': self._retain_display_lists,
                    'promotion_allowed': job.promotion_allowed and job.kind == 'page'}
        if job.foreground_intent is not None:
            header['foreground_intent'] = job.foreground_intent
        self._send(header)

    @Slot()
    def _read_stdout(self):
        process = self._process
        if process is None or self._retiring:
            return
        started = time.perf_counter()
        try:
            chunk = bytes(process.read(4 * 1024 * 1024))
            self.metrics['ipc_bytes'] += len(chunk)
            for frame in self._decoder.feed(chunk):
                header = frame.header
                kind = header['type']
                if kind == 'ready':
                    self._worker_pid = header['pid']
                    if header['fitz_version'] != fitz.VersionBind:
                        self._disabled = True
                        self._lost()
                        return
                    self._ready = True
                    self._deadline = 0
                    self._pump()
                elif kind in {'doc_ready', 'doc_failed'}:
                    if not self._active or header['doc_key'] != self._active.doc.doc_key or not self._loading:
                        raise ProtocolError('unexpected document reply')
                    self._loading = self._path_loading = False
                    if kind == 'doc_ready':
                        overlay = self._active.doc.watermarks_json
                        expected = hashlib.sha256(overlay).hexdigest() if overlay != b'[]' else None
                        if header.get('overlay_sha256') != expected:
                            raise ProtocolError('mismatched overlay identity')
                        self.loaded_key = header['doc_key']
                        self._loaded_watermarks_json = overlay
                        self._loaded_owner = self._active.owner
                        if self._active_cancelled:
                            self._finish(JobOutcome('cancelled'))
                        else:
                            self._render()
                    else:
                        self._finish(JobOutcome('unavailable'))
                elif kind in {'image', 'error'}:
                    if not self._active or header['job'] != self._active.job_id:
                        raise ProtocolError('unexpected job reply')
                    # Count completed native replies even if their image is
                    # logically obsolete. Dropping a result does not undo the
                    # child's list work. Killed/unreported work remains unknown.
                    if kind == 'image':
                        if header.get('raster_path') == 'build':
                            self.metrics['display_list_builds'] += 1
                        elif header.get('raster_path') == 'hit':
                            self.metrics['display_list_hits'] += 1
                    if self._active_cancelled:
                        self._finish(JobOutcome('cancelled'))
                        continue
                    if kind == 'image':
                        image = qimage_from_samples(frame.body, header['w'], header['h'],
                                                    header['stride'], header['alpha'])
                        self.metrics['images'] += 1
                        self._finish(JobOutcome('image', image))
                    else:
                        self._finish(JobOutcome('oversize' if header['reason'] == 'oversize' else 'error'))
                else:
                    raise ProtocolError('unexpected response')
            if self._process is process and process.bytesAvailable():
                QTimer.singleShot(0, self._read_stdout)
        except (ProtocolError, ValueError):
            self._lost()
        finally:
            self.sample_memory()
            self.metrics['frame_gui_ms'].append((time.perf_counter() - started) * 1000)
            if len(self.metrics['frame_gui_ms']) > 10000:
                del self.metrics['frame_gui_ms'][:1000]

    @Slot()
    def _read_stderr(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardError())
        now = self._clock()
        if now - self._stderr_window >= 60:
            self._stderr_count = 0
            self._stderr_window = now
        # Native messages can include paths or document text. Log only volume.
        allowed = min(len(data), max(0, 65536 - self._stderr_count))
        if allowed:
            logger.debug('Raster worker diagnostics: %d bytes (content suppressed)', allowed)
            self._stderr_count += allowed

    def _report(self, job_id, outcome, deferred=False):
        if self._held or deferred:
            self._deferred.append((job_id, outcome))
            if not self._held:
                QTimer.singleShot(0, self._deliver)
        else:
            self.job_done.emit(job_id, outcome)

    @Slot()
    def _deliver(self):
        if self._held:
            return
        pending, self._deferred = self._deferred, []
        for job_id, outcome in pending:
            self.job_done.emit(job_id, outcome)

    def _finish(self, outcome):
        if outcome.status == 'image':
            self._consecutive_failures = 0
        active, self._active = self._active, None
        cancelled, self._active_cancelled = self._active_cancelled, False
        self._recall_at = 0.
        self._recall_timer.stop()
        self._loading = self._path_loading = False
        self._deadline = 0
        if active and not cancelled:
            self._report(active.job_id, outcome)
        self._pump()

    @Slot()
    def _check_deadline(self):
        self.sample_memory()
        self._schedule_recall()
        if self._recall_at and self._clock() >= self._recall_at:
            self.metrics['recalls'] += 1
            self._dispose()
            self._finish(JobOutcome('cancelled'))
            self.start()
            return
        if self._deadline and self._clock() >= self._deadline:
            self._record_failure()
            self._dispose()
            self._finish(JobOutcome('timeout'))
            if self._disabled:
                self._drain_unavailable()
            else:
                self.start()

    @Slot(object)
    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._disabled = True
            self._dispose()
            self._finish(JobOutcome('unavailable'))
            self._drain_unavailable()

    @Slot(int, object)
    def _exited(self, *_args):
        if not self._closing:
            self._lost()

    def _lost(self):
        self._record_failure()
        self._dispose()
        self._finish(JobOutcome('transport_lost'))
        if self._disabled:
            self._drain_unavailable()
        else:
            self.start()

    def _record_failure(self):
        self._consecutive_failures += 1
        self._crashes.append(self._clock())
        while self._crashes and self._clock() - self._crashes[0] > 120:
            self._crashes.popleft()
        if len(self._crashes) >= 3 or self._consecutive_failures >= 3:
            self._disabled = True

    def _drain_unavailable(self):
        pending, self._queue = self._queue, []
        for job in pending:
            self._report(job.job_id, JobOutcome('unavailable'), deferred=True)

    def _dispose(self):
        self.sample_memory()
        process = self._process
        self._ready = False
        self._deadline = 0.
        self.loaded_key = None
        self._loaded_owner = None
        self._writes.clear()
        if process and not self._retiring:
            self._retiring = True
            if self._process_lease is not None:
                self._resource_ledger.retire_process(self._process_lease)
            for signal, slot in self._process_connections:
                signal.disconnect(slot)
            self._process_connections.clear()
            process.finished.connect(self._retired)
            if process.state() != QProcess.NotRunning:
                process.kill()
            if process.state() == QProcess.NotRunning:
                self._finish_disposal(process)

    @Slot(int, object)
    def _retired(self, *_args):
        self._finish_disposal(self.sender())

    def _finish_disposal(self, process):
        if process is not self._process or process.state() != QProcess.NotRunning:
            return
        process.finished.disconnect(self._retired)
        self._process = None
        self._release_process_lease()
        self._worker_pid = 0
        self._retiring = False
        process.deleteLater()
        if self._closing:
            self.stopped.emit()
        elif not self._disabled:
            QTimer.singleShot(0, self.start)

    def _release_process_lease(self):
        if self._process_lease is not None:
            self._resource_ledger.process_exited(self._process_lease)
            self._process_lease = None

    @contextlib.contextmanager
    def path_loads_held(self, timeout_ms):
        self._held += 1
        try:
            deadline = self._clock() + timeout_ms / 1000
            while self._path_loading and self._process:
                remaining = max(0, int((deadline - self._clock()) * 1000))
                if not remaining or not self._process.waitForReadyRead(remaining):
                    self._dispose()
                    # Internal save interruption is recoverable, unlike an
                    # owner's cancellation. Deliver after release so the page
                    # coordinator can fallback and finish its visible batch.
                    self._finish(JobOutcome('unavailable'))
                    break
                self._read_stdout()
            yield
        finally:
            self._held -= 1
            if not self._held:
                QTimer.singleShot(0, self._deliver)
                self.start()
                self._pump()

    @Slot()
    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._recall_timer.stop()
        pending, self._queue = self._queue, []
        if self._active and not self._active_cancelled:
            pending.insert(0, self._active)
        self._active = None
        self._active_cancelled = False
        for job in pending:
            self._report(job.job_id, JobOutcome('owner_released'))
        process = self._process
        if process and process.state() != QProcess.NotRunning:
            if self._ready:
                self._send({'type': 'quit'})
            process.closeWriteChannel()
        self._dispose()
        if process is None:
            self.stopped.emit()
