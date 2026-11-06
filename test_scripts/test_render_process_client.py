from __future__ import annotations

import time
import io
import builtins

import fitz
import pytest
from PySide6.QtCore import QObject, QProcess, Signal

from src.render_worker.process_client import DocSource, FileRef, RenderJob, RenderProcessClient
from src.render_worker.protocol import Frame, FrameDecoder, encode_prefix


class FakeProcess(QObject):
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    bytesWritten = Signal(int)
    finished = Signal(int, object)
    errorOccurred = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.output = bytearray()
        self.commands = []
        self.decoder = FrameDecoder()
        self.running = True

    def setProcessEnvironment(self, env):
        self.env = env

    def setWorkingDirectory(self, path):
        pass

    def start(self, *args):
        self.args = args

    def state(self):
        return QProcess.Running if self.running else QProcess.NotRunning

    def write(self, data):
        self.commands.extend(self.decoder.feed(bytes(data)))
        return len(data)

    def bytesToWrite(self):
        return 0

    def bytesAvailable(self):
        return len(self.output)

    def read(self, size):
        chunk = bytes(self.output[:size])
        del self.output[:size]
        return chunk

    def readAllStandardError(self):
        return b''

    def reply(self, header, body=b''):
        self.output.extend(encode_prefix(header, len(body)) + body)
        self.readyReadStandardOutput.emit()

    def kill(self):
        self.running = False

    def waitForFinished(self, timeout):
        self.running = False
        return True

    def closeWriteChannel(self):
        pass

    def waitForReadyRead(self, timeout):
        return False


def source(key='s@0', calls=None):
    def snapshot():
        if calls is not None:
            calls.append(key)
        doc = fitz.open()
        doc.new_page(width=80, height=80)
        data = doc.tobytes()
        doc.close()
        return data
    return DocSource(key, None, snapshot)


def ready_client(qapp):
    client = RenderProcessClient(process_factory=FakeProcess)
    client.start()
    client._process.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    return client


def job(client, name, doc=None, lane='page'):
    return RenderJob(name, client.register_owner(), lane, doc or source(), 0, 1., 'srgb', lane)


def finish_image(client, name):
    client._process.reply({'type': 'image', 'job': name, 'w': 1, 'h': 1,
                           'stride': 3, 'n': 3, 'alpha': False}, b'\xff\xff\xff')


def test_scheduler_lazy_load_and_page_priority(qapp):
    client = ready_client(qapp)
    calls = []
    doc = source(calls=calls)
    outcomes = []
    client.job_done.connect(lambda key, result: outcomes.append((key, result.status)))
    client.submit(job(client, 't1', doc, 'thumb'))
    client.submit(job(client, 't2', doc, 'thumb'))
    client.submit(job(client, 'p1', doc))
    assert calls == ['s@0']
    client._process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    finish_image(client, 't1')
    assert client._active.job_id == 'p1'
    finish_image(client, 'p1')
    finish_image(client, 't2')
    assert outcomes == [('t1', 'image'), ('p1', 'image'), ('t2', 'image')]
    assert calls == ['s@0']
    client.shutdown()


def test_queued_cancel_deferred_and_owner_release(qapp):
    client = ready_client(qapp)
    outcomes = []
    client.job_done.connect(lambda key, result: outcomes.append((key, result.status)))
    first, second = job(client, 'first'), job(client, 'second')
    client.submit(first)
    client.submit(second)
    client.cancel('second')
    assert outcomes == []
    qapp.processEvents()
    assert outcomes == [('second', 'cancelled')]
    client.release_owner(first.owner)
    qapp.processEvents()
    assert outcomes[-1] == ('first', 'owner_released')
    assert client._active is None
    client.shutdown()


@pytest.mark.parametrize('failure', ['crash', 'timeout', 'failed_start'])
def test_terminal_failure_once(qapp, failure):
    client = ready_client(qapp)
    outcomes = []
    client.job_done.connect(lambda key, result: outcomes.append((key, result.status)))
    client.submit(job(client, 'one'))
    if failure == 'crash':
        client._process.finished.emit(1, QProcess.CrashExit)
    elif failure == 'timeout':
        client._deadline = time.monotonic() - 1
        client._check_deadline()
    else:
        client._process.errorOccurred.emit(QProcess.FailedToStart)
    qapp.processEvents()
    assert len(outcomes) == 1
    assert outcomes[0][1] == {'crash': 'transport_lost', 'timeout': 'timeout',
                               'failed_start': 'unavailable'}[failure]
    assert client._active is None
    assert len(client._crashes) == (1 if failure == 'crash' else 0)
    client.shutdown()


def test_save_hold_defers_result_delivery(qapp):
    client = ready_client(qapp)
    outcomes = []
    client.job_done.connect(lambda key, result: outcomes.append(key))
    client.submit(job(client, 'one'))
    client._process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    with client.path_loads_held(10):
        finish_image(client, 'one')
        assert not outcomes
    qapp.processEvents()
    assert outcomes == ['one']
    client.shutdown()


def test_shutdown_finishes_all_jobs_exactly_once(qapp):
    client = ready_client(qapp)
    results = []
    client.job_done.connect(lambda key, result: results.append((key, result.status)))
    client.submit(job(client, 'active'))
    client.submit(job(client, 'queued'))
    client.shutdown()
    qapp.processEvents()
    assert sorted(results) == [('active', 'owner_released'), ('queued', 'owner_released')]


def test_three_crashes_disable_and_old_process_cannot_deliver(qapp):
    client = ready_client(qapp)
    for index in range(3):
        old = client._process
        client.submit(job(client, str(index)))
        old.finished.emit(1, QProcess.CrashExit)
        old.readyReadStandardOutput.emit()
        if index < 2:
            client._process.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    assert client._disabled and client._process is None
    client.shutdown()


def test_stale_provider_not_called(qapp):
    client = ready_client(qapp)
    calls = []
    doc = DocSource('stale', None, lambda: calls.append('wrong'), lambda: False)
    results = []
    client.job_done.connect(lambda key, result: results.append(result.status))
    client.submit(job(client, 'stale', doc))
    assert results == ['stale'] and not calls
    client.shutdown()


def test_clean_path_load_and_password_body(qapp):
    client = ready_client(qapp)
    doc = DocSource('path@1', FileRef('document.pdf', 100, 123, 's3cret'),
                    lambda: pytest.fail('clean path must not snapshot'))
    client.submit(job(client, 'path', doc))
    frame = client._process.commands[-1]
    assert frame.header['type'] == 'load_path'
    assert b's3cret' == frame.body
    assert 's3cret' not in repr(frame.header) + repr(doc)
    assert client._process.env.value('PYTHONUTF8') == '1'
    assert client._process.env.value('PYTHONIOENCODING') == 'utf-8'
    client.shutdown()


def test_load_limit_rejected_before_send(qapp, monkeypatch):
    client = ready_client(qapp)
    monkeypatch.setattr('src.render_worker.process_client.MAX_LOAD_BYTES', 10)
    results = []
    client.job_done.connect(lambda key, result: results.append(result.status))
    client.submit(job(client, 'large', DocSource('large', FileRef('large.pdf', 11, 1), lambda: None)))
    assert results == ['oversize']
    assert not client._process.commands
    client.shutdown()


def test_unavailable_reports_after_submit_returns(qapp):
    client = RenderProcessClient(process_factory=FakeProcess)
    results = []
    client.job_done.connect(lambda key, result: results.append(result.status))
    client.submit(job(client, 'early'))
    assert not results
    qapp.processEvents()
    assert results == ['unavailable']
    client.shutdown()


def test_partial_writes_deliver_one_complete_frame(qapp):
    client = ready_client(qapp)
    original = client._process.write
    client._process.write = lambda data: original(data[:7])
    client.submit(job(client, 'partial'))
    assert len(client._process.commands) == 1
    assert client._process.commands[0].header['type'] == 'load_bytes'
    client.shutdown()


def test_owner_release_drops_its_loaded_document_even_with_other_owner(qapp):
    client = ready_client(qapp)
    active = job(client, 'loaded')
    client.register_owner()
    client.submit(active)
    client._process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    finish_image(client, 'loaded')
    client.release_owner(active.owner)
    assert client.loaded_key is None
    assert client._process.commands[-1].header['type'] == 'drop_doc'
    client.shutdown()


def test_path_hold_timeout_is_deliberate_and_does_not_crash(qapp):
    client = ready_client(qapp)
    results = []
    client.job_done.connect(lambda key, result: results.append(result.status))
    client.submit(job(client, 'loading', DocSource('file', FileRef('file.pdf', 1, 1), lambda: None)))
    with client.path_loads_held(10):
        assert client._process is None
        assert not results
    qapp.processEvents()
    assert results == ['unavailable'] and not client._crashes
    client.shutdown()


def test_respawn_pid_zero_until_new_handshake(qapp):
    client = ready_client(qapp)
    assert client.pid == 123
    client._process.finished.emit(1, QProcess.CrashExit)
    assert client.pid == 0
    client.shutdown()


def test_path_load_reads_file_size_not_transport_limit(tmp_path, monkeypatch):
    from src.render_worker.worker_main import Worker

    path = tmp_path / 'small.pdf'
    path.write_bytes(source().snapshot_provider())
    stat = path.stat()
    original = builtins.open
    requested = []

    class Reader:
        def __enter__(self):
            self.file = original(path, 'rb')
            return self

        def __exit__(self, *args):
            self.file.close()

        def fileno(self):
            return self.file.fileno()

        def read(self, size):
            requested.append(size)
            return self.file.read(size)

    monkeypatch.setattr(builtins, 'open', lambda *args, **kwargs: Reader())
    worker = Worker(io.BytesIO())
    try:
        worker.load(Frame({'type': 'load_path', 'doc_key': 'small', 'path': str(path),
                           'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}, bytearray()))
        assert worker.doc is not None
        assert requested == [stat.st_size + 1]
    finally:
        worker.drop()


def test_frame_timing_uses_high_resolution_independently_of_deadline_clock(qapp):
    client = ready_client(qapp)
    client._clock = lambda: 1.
    client._process.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    assert client.metrics['frame_gui_ms'][-1] > 0
    client.shutdown()


def test_closed_tab_drops_only_its_document_without_releasing_window(qapp):
    client = ready_client(qapp)
    active = job(client, 'tab')
    client.submit(active)
    client._process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    finish_image(client, 'tab')
    client.release_document(active.owner, 'other')
    assert client.loaded_key == 's@0'
    client.release_document(active.owner, 's')
    assert client.loaded_key is None
    assert active.owner in client._owners
    assert client._process.commands[-1].header['type'] == 'drop_doc'
    client.shutdown()


def test_observed_child_peak_survives_respawn(qapp):
    client = ready_client(qapp)
    client._memory_reader = lambda pid: 100.
    client._process.finished.emit(1, QProcess.CrashExit)
    client._memory_reader = lambda pid: 10.
    client._process.reply({'type': 'ready', 'pid': 456, 'fitz_version': fitz.VersionBind})
    client._check_deadline()
    assert client.metrics['child_peak_mb'] == 100.
    client.shutdown()
