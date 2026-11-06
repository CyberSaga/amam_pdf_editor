from __future__ import annotations

import contextlib
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
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from src.render_worker.protocol import MAX_IMAGE_BYTES, MAX_LOAD_BYTES, FrameDecoder, ProtocolError, encode_prefix
from src.render_worker.memory import peak_working_set_mb
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

    def __init__(self, parent=None, *, process_factory=QProcess,
                 python_executable=None, monotonic=time.monotonic):
        super().__init__(parent)
        self._factory = process_factory
        self._python = python_executable or sys.executable
        self._venv_launcher = None
        if python_executable is None and sys.platform == 'win32' and sys.prefix != sys.base_prefix:
            # CPython's Windows venv executable is a redirector: QProcess.kill
            # would end only that launcher. Use the same interpreter directly,
            # with CPython's launcher hint preserving the venv path discovery.
            self._venv_launcher = sys.executable
            self._python = sys._base_executable
        self._clock = monotonic
        self._memory_reader = peak_working_set_mb
        self._process = None
        self._worker_pid = 0
        self._ready = False
        self._disabled = False
        self._closing = False
        self._owners: set[str] = set()
        self._queue: list[RenderJob] = []
        self._active: RenderJob | None = None
        self.loaded_key: str | None = None
        self._loaded_owner: str | None = None
        self._loading = False
        self._path_loading = False
        self._deadline = 0.
        self._decoder = FrameDecoder(max_body=MAX_IMAGE_BYTES)
        self._writes: deque[memoryview] = deque()
        self._crashes: deque[float] = deque()
        self._held = 0
        self._deferred: list[tuple[str, JobOutcome]] = []
        self._stderr_window = self._clock()
        self._stderr_count = 0
        self.metrics = {'doc_loads': 0, 'ipc_bytes': 0, 'images': 0,
                        'frame_gui_ms': [], 'starts': 0, 'fallbacks': 0,
                        'child_peak_mb': None}
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._check_deadline)

    @property
    def ready(self):
        return self._ready and not self._disabled and not self._closing

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
            self.cancel(self._active.job_id)
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
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.bytesWritten.connect(self._flush_writes)
        process.finished.connect(self._exited)
        process.errorOccurred.connect(self._process_error)
        self._deadline = self._clock() + 120
        self._timer.start()
        self.metrics['starts'] += 1
        process.start(self._python, ['-m', 'src.render_worker.worker_main'])

    def submit(self, job):
        if job.owner not in self._owners:
            self._report(job.job_id, JobOutcome('owner_released'), deferred=True)
        elif not self.ready:
            self._report(job.job_id, JobOutcome('unavailable'), deferred=True)
        else:
            self._queue.append(job)
            self._pump()

    def cancel(self, job_id, status='cancelled'):
        for job in list(self._queue):
            if job.job_id == job_id:
                self._queue.remove(job)
                self._report(job_id, JobOutcome(status), deferred=True)
                return
        if self._active and self._active.job_id == job_id:
            self._dispose()
            self._finish(JobOutcome(status))
            self.start()

    def _send(self, header, body=b''):
        self._writes.append(memoryview(encode_prefix(header, len(body))))
        if body:
            self._writes.append(memoryview(body))
        self._flush_writes()

    @Slot()
    def _flush_writes(self, *_args):
        process = self._process
        if process is None:
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
        self._deadline = self._clock() + 120
        if not job.doc.is_current():
            self._finish(JobOutcome('stale'))
            return
        if self.loaded_key == job.doc.doc_key:
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
        self._send({'type': 'render', 'job': job.job_id, 'doc_key': job.doc.doc_key,
                    'page': job.page_index, 'scale': job.scale,
                    'profile': job.color_profile, 'kind': job.kind})

    @Slot()
    def _read_stdout(self):
        process = self._process
        if process is None:
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
                        self.loaded_key = header['doc_key']
                        self._loaded_owner = self._active.owner
                        self._render()
                    else:
                        self._finish(JobOutcome('unavailable'))
                elif kind in {'image', 'error'}:
                    if not self._active or header['job'] != self._active.job_id:
                        raise ProtocolError('unexpected job reply')
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
        active, self._active = self._active, None
        self._loading = self._path_loading = False
        self._deadline = 0
        if active:
            self._report(active.job_id, outcome)
        self._pump()

    @Slot()
    def _check_deadline(self):
        self.sample_memory()
        if self._deadline and self._clock() >= self._deadline:
            self._dispose()
            self._finish(JobOutcome('timeout'))
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
        self._crashes.append(self._clock())
        while self._crashes and self._clock() - self._crashes[0] > 120:
            self._crashes.popleft()
        if len(self._crashes) >= 3:
            self._disabled = True
        self._dispose()
        self._finish(JobOutcome('transport_lost'))
        if self._disabled:
            self._drain_unavailable()
        else:
            self.start()

    def _drain_unavailable(self):
        pending, self._queue = self._queue, []
        for job in pending:
            self._report(job.job_id, JobOutcome('unavailable'), deferred=True)

    def _dispose(self):
        self.sample_memory()
        process, self._process = self._process, None
        self._worker_pid = 0
        self._ready = False
        self.loaded_key = None
        self._loaded_owner = None
        self._writes.clear()
        if process:
            for signal in (process.readyReadStandardOutput, process.readyReadStandardError,
                           process.bytesWritten, process.finished, process.errorOccurred):
                signal.disconnect()
            if process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(500)
            process.deleteLater()

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
        pending, self._queue = self._queue, []
        if self._active:
            pending.insert(0, self._active)
            self._active = None
        for job in pending:
            self._report(job.job_id, JobOutcome('owner_released'))
        process = self._process
        if process and process.state() != QProcess.NotRunning:
            if self._ready:
                self._send({'type': 'quit'})
            process.closeWriteChannel()
            process.waitForFinished(500)
        self._dispose()
