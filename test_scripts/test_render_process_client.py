from __future__ import annotations

import time
import io
import builtins
from dataclasses import replace

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


def test_thumbnail_batch_trim_interval_is_transmitted(qapp):
    client = RenderProcessClient(process_factory=FakeProcess, trim_thumbnail_store=True,
                                 thumbnail_trim_interval=4)
    try:
        client.start()
        client._process.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
        client.submit(job(client, 'batch', lane='thumb'))
        client._process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
        header = client._process.commands[-1].header
        assert header['trim_store'] is True and header['trim_store_interval'] == 4
    finally:
        client.shutdown()


def job(client, name, doc=None, lane='page', *, owner=None):
    return RenderJob(name, owner or client.register_owner(), lane, doc or source(), 0, 1., 'srgb', lane)


def finish_image(client, name):
    client._process.reply({'type': 'image', 'job': name, 'w': 1, 'h': 1,
                           'stride': 3, 'n': 3, 'alpha': False}, b'\xff\xff\xff')


@pytest.mark.parametrize('cancelled', [False, True])
@pytest.mark.parametrize('path', ['build', 'hit'])
@pytest.mark.parametrize('eligible', [False, True])
def test_retention_opt_in_is_sent_and_actual_paths_are_counted(qapp, cancelled, path, eligible):
    client = RenderProcessClient(process_factory=FakeProcess, retain_display_lists=True)
    client.start()
    client._process.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    client.submit(replace(job(client, 'hot'), foreground_intent='viewport:7', promotion_allowed=eligible))
    client._process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    request = client._process.commands[-1].header
    assert request['retain_display_lists'] is True
    assert request['promotion_allowed'] is eligible
    assert request['foreground_intent'] == 'viewport:7'
    if cancelled:
        client.cancel('hot')
    client._process.reply({'type': 'image', 'job': 'hot', 'w': 1, 'h': 1,
                           'stride': 3, 'n': 3, 'alpha': False, 'raster_path': path}, b'\xff\xff\xff')
    assert client.metrics['display_list_builds'] == (1 if path == 'build' else 0)
    assert client.metrics['display_list_hits'] == (1 if path == 'hit' else 0)
    client.shutdown()


def test_scheduler_lazy_load_and_page_priority(qapp):
    client = ready_client(qapp)
    calls = []
    doc = source(calls=calls)
    outcomes = []
    client.job_done.connect(lambda key, result: outcomes.append((key, result.status)))
    owner = client.register_owner()
    client.submit(job(client, 't1', doc, 'thumb', owner=owner))
    client.submit(job(client, 't2', doc, 'thumb', owner=owner))
    client.submit(job(client, 'p1', doc, owner=owner))
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
    assert len(client._crashes) == (0 if failure == 'failed_start' else 1)
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


def test_disabled_reports_after_submit_returns(qapp):
    client = RenderProcessClient(process_factory=FakeProcess)
    client._disabled = True
    results = []
    client.job_done.connect(lambda key, result: results.append(result.status))
    client.submit(job(client, 'early'))
    assert not results
    qapp.processEvents()
    assert results == ['unavailable']
    client.shutdown()


def test_starting_client_retains_work_until_handshake(qapp):
    client = RenderProcessClient(process_factory=FakeProcess)
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome.status))
    client.submit(job(client, 'early'))
    qapp.processEvents()
    assert results == []
    assert client._process is not None
    client._process.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    assert client._active.job_id == 'early'
    client.shutdown()


def test_supersession_reuses_loaded_worker_and_discards_late_image(qapp):
    client = ready_client(qapp)
    clock = [1.]
    client._clock = lambda: clock[0]
    results = []
    client.job_done.connect(lambda key, outcome: results.append((key, outcome.status)))
    doc = source()
    owner = client.register_owner()
    client.submit(job(client, 'old', doc, owner=owner))
    client._process.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    process = client._process
    client.cancel('old')
    client.submit(job(client, 'new', doc, owner=owner))
    qapp.processEvents()
    assert client._process is process
    assert results == [('old', 'cancelled')]
    finish_image(client, 'old')
    assert client._active.job_id == 'new'
    finish_image(client, 'new')
    assert results == [('old', 'cancelled'), ('new', 'image')]
    assert client.metrics['starts'] == 1 and client.metrics['doc_loads'] == 1
    client.shutdown()


class DelayedExitProcess(FakeProcess):
    def kill(self):
        self.kill_requested = True

    def waitForFinished(self, timeout):
        pytest.fail('GUI thread must not wait for process exit')

    def exit_now(self):
        self.running = False
        self.finished.emit(0, QProcess.NormalExit)


def test_resource_lease_survives_recall_and_stale_generation(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    clock = [1.]
    client = RenderProcessClient(process_factory=DelayedExitProcess, monotonic=lambda: clock[0],
                                 resource_ledger=ledger, process_reservation_bytes=100)
    client.start()
    old = client._process
    old.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    client.submit(job(client, 'thumb', lane='thumb'))
    client.submit(job(client, 'visible'))
    clock[0] += .151
    client._check_deadline()
    assert ledger.reserved_bytes == 100 and ledger.retiring_slots == 1
    assert ledger.try_reserve('print', 'process', 1, compute_slots=1) is None
    old.exit_now()
    # The replacement inherits the lease: the charge stays continuous, so a rival
    # cannot take the slot between the confirmed exit and the restart.
    assert ledger.reserved_bytes == 100 and ledger.compute_slots == 1
    assert ledger.retiring_slots == 0
    assert ledger.try_reserve('print', 'process', 1, compute_slots=1) is None
    qapp.processEvents()
    replacement = client._process
    assert replacement is not old and ledger.reserved_bytes == 100
    client._finish_disposal(old)
    assert ledger.reserved_bytes == 100 and ledger.compute_slots == 1
    client.shutdown()
    assert ledger.reserved_bytes == 100 and ledger.retiring_slots == 1
    replacement.exit_now()
    assert ledger.reserved_bytes == 0 and ledger.compute_slots == 0


@pytest.mark.parametrize(('reservation', 'slots'), [(None, 2), (50, 0)])
def test_resource_admission_refuses_before_factory_without_waiting(qapp, reservation, slots):
    from src.render_worker.resource_ledger import ResourceLedger

    def forbidden_factory(parent):
        pytest.fail('no process may be created without a reservation')

    ledger = ResourceLedger(byte_limit=100, slot_limit=slots)
    client = RenderProcessClient(process_factory=forbidden_factory, resource_ledger=ledger,
                                 process_reservation_bytes=reservation)
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome.status))
    client.submit(job(client, 'refused'))
    qapp.processEvents()
    assert results == ['unavailable'] and client._process is None
    assert ledger.reserved_bytes == 0 and ledger.compute_slots == 0
    client.shutdown()


@pytest.mark.parametrize('stage', ['factory', 'setup', 'failed_start'])
def test_resource_reservation_rolls_back_only_when_no_child_survives(qapp, stage):
    from src.render_worker.resource_ledger import ResourceLedger

    class SetupProcess(FakeProcess):
        def setWorkingDirectory(self, path):
            if stage == 'setup':
                raise OSError('fixture setup failure')

    def factory(parent):
        assert ledger.reserved_bytes == 100 and ledger.compute_slots == 1
        if stage == 'factory':
            raise OSError('fixture factory failure')
        return SetupProcess(parent)

    ledger = ResourceLedger(byte_limit=100)
    client = RenderProcessClient(process_factory=factory, resource_ledger=ledger,
                                 process_reservation_bytes=100)
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome.status))
    client.submit(job(client, 'fail'))
    if stage == 'failed_start':
        client._process.running = False
        client._process.errorOccurred.emit(QProcess.FailedToStart)
    qapp.processEvents()
    assert results == ['unavailable']
    assert client._process is None and ledger.reserved_bytes == 0 and ledger.compute_slots == 0
    client.shutdown()


def test_resource_synchronous_start_failure_and_nonterminal_error(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    class SynchronousFailure(FakeProcess):
        def start(self, *args):
            self.running = False
            self.errorOccurred.emit(QProcess.FailedToStart)

    ledger = ResourceLedger(byte_limit=100)
    failed = RenderProcessClient(process_factory=SynchronousFailure, resource_ledger=ledger,
                                 process_reservation_bytes=100)
    failed.start()
    assert failed._process is None and ledger.reserved_bytes == 0
    assert failed._disabled
    failed.shutdown()

    live = RenderProcessClient(process_factory=DelayedExitProcess, resource_ledger=ledger,
                               process_reservation_bytes=100)
    live.start()
    process = live._process
    process.errorOccurred.emit(QProcess.ReadError)
    assert ledger.reserved_bytes == 100 and ledger.retiring_slots == 0
    # Even a direct premature disposal callback cannot free a running child.
    live._finish_disposal(process)
    assert ledger.reserved_bytes == 100 and live._process is process
    live.shutdown()
    assert ledger.reserved_bytes == 100 and ledger.retiring_slots == 1
    process.exit_now()
    assert ledger.reserved_bytes == 0


def test_resource_setup_failure_retains_still_running_child(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    class DelayedSetupFailure(DelayedExitProcess):
        def setWorkingDirectory(self, path):
            raise OSError('fixture setup failure with delayed physical exit')

    ledger = ResourceLedger(byte_limit=100)
    client = RenderProcessClient(process_factory=DelayedSetupFailure, resource_ledger=ledger,
                                 process_reservation_bytes=100)
    client.start()
    process = client._process
    assert client._disabled and process.kill_requested
    assert ledger.reserved_bytes == 100 and ledger.retiring_slots == 1
    client.shutdown()
    assert ledger.reserved_bytes == 100
    process.exit_now()
    client._finish_disposal(process)
    assert client._process is None and ledger.reserved_bytes == 0


def test_recall_waits_for_actual_exit_without_blocking_gui(qapp):
    clock = [1.]
    client = RenderProcessClient(process_factory=DelayedExitProcess, monotonic=lambda: clock[0])
    client.start()
    old = client._process
    old.reply({'type': 'ready', 'pid': 123, 'fitz_version': fitz.VersionBind})
    results = []
    client.job_done.connect(lambda key, outcome: results.append((key, outcome.status)))
    client.submit(job(client, 'thumb', lane='thumb'))
    client.submit(job(client, 'visible'))
    clock[0] += .151
    client._check_deadline()
    assert getattr(old, 'kill_requested', False)
    assert client.metrics['starts'] == 1
    assert client.pid == 123
    old.exit_now()
    qapp.processEvents()
    assert client.metrics['starts'] == 2 and client.pid == 0
    client._process.reply({'type': 'ready', 'pid': 456, 'fitz_version': fitz.VersionBind})
    assert client._active.job_id == 'visible'
    assert results == [('thumb', 'cancelled')]
    client.shutdown()
    assert client.pid == 456
    client._process.exit_now()
    qapp.processEvents()
    assert client._process is None


def test_shutdown_does_not_report_cancelled_active_twice(qapp):
    client = ready_client(qapp)
    results = []
    client.job_done.connect(lambda key, outcome: results.append((key, outcome.status)))
    client.submit(job(client, 'old'))
    client.cancel('old')
    client.shutdown()
    qapp.processEvents()
    assert results == [('old', 'cancelled')]


def test_repeated_startup_timeouts_disable_without_fourth_spawn(qapp):
    clock = [1.]
    client = RenderProcessClient(process_factory=FakeProcess, monotonic=lambda: clock[0])
    client.start()
    for _ in range(3):
        client._deadline = clock[0] - .1
        client._check_deadline()
        clock[0] += 1.
    qapp.processEvents()
    assert client._disabled and client.metrics['starts'] == 3
    client.shutdown()


def test_real_deadline_spacing_still_bounds_startup_retries(qapp):
    clock = [1.]
    client = RenderProcessClient(process_factory=FakeProcess, monotonic=lambda: clock[0])
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome.status))
    client.submit(job(client, 'waiting'))
    for _ in range(3):
        clock[0] = client._deadline + .001
        client._check_deadline()
    qapp.processEvents()
    assert client._disabled and client.metrics['starts'] == 3
    assert results == ['unavailable']
    client.shutdown()


def test_release_document_during_load_cannot_retain_closed_tab(qapp):
    client = ready_client(qapp)
    pending = job(client, 'loading')
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome.status))
    client.submit(pending)
    old = client._process
    client.release_document(pending.owner, 's')
    old.reply({'type': 'doc_ready', 'doc_key': 's@0', 'page_count': 1})
    qapp.processEvents()
    assert client.loaded_key is None
    assert client._active is None
    assert results == ['cancelled']
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


def test_same_document_key_from_another_owner_is_not_reused(qapp):
    client = ready_client(qapp)
    first = job(client, 'first', source('same@0'))
    client.submit(first)
    client._process.reply({'type': 'doc_ready', 'doc_key': 'same@0', 'page_count': 1})
    finish_image(client, 'first')
    second = job(client, 'second', source('same@0'))
    client.submit(second)
    assert client.metrics['doc_loads'] == 2
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


def test_optional_client_refused_by_the_ledger_is_parked_not_unavailable(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    def forbidden_factory(parent):
        pytest.fail('a refused optional child must not create a process')

    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    holder = ledger.try_reserve('first-worker', 'process', 80, compute_slots=1)
    client = RenderProcessClient(process_factory=forbidden_factory, resource_ledger=ledger,
                                 process_reservation_bytes=50, admission='optional')
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome.status))
    client.submit(job(client, 'deferred'))
    qapp.processEvents()
    assert results == ['admission_deferred']
    assert client._parked and not client._disabled and client._process is None
    assert ledger.reserved_bytes == 80
    client.shutdown()
    assert holder is not None


def test_parked_client_starts_only_after_unpark_and_never_on_its_own(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    holder = ledger.try_reserve('first-worker', 'process', 80, compute_slots=1)
    client = RenderProcessClient(process_factory=DelayedExitProcess, resource_ledger=ledger,
                                 process_reservation_bytes=50, admission='optional')
    client.start()
    assert client._parked and client._process is None
    ledger.retire_process(holder)
    ledger.process_exited(holder)
    qapp.processEvents()
    assert client._process is None, 'a parked child does not restart by itself'
    client.unpark()
    assert not client._parked and client._process is not None
    assert ledger.reserved_bytes == 50 and ledger.compute_slots == 1
    client.shutdown()


def test_required_client_starts_over_the_byte_limit_and_counts_the_overcommit(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=10, slot_limit=1)
    client = RenderProcessClient(process_factory=DelayedExitProcess, resource_ledger=ledger,
                                 process_reservation_bytes=100)
    client.start()
    assert client._process is not None and not client._parked
    assert ledger.reserved_bytes == 100 and ledger.stats()['overcommits'] == 1
    client.shutdown()


def test_restart_after_crash_keeps_the_lease_and_a_rival_cannot_take_the_slot(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=200, slot_limit=1)
    client = RenderProcessClient(process_factory=DelayedExitProcess, resource_ledger=ledger,
                                 process_reservation_bytes=100)
    client.start()
    old = client._process
    old.reply({'type': 'ready', 'pid': 321, 'fitz_version': fitz.VersionBind})
    old.exit_now()  # the crash: the exit is already confirmed
    assert ledger.try_reserve('rival', 'process', 1, compute_slots=1) is None
    qapp.processEvents()
    assert client._process is not None and client._process is not old
    assert ledger.reserved_bytes == 100 and ledger.compute_slots == 1
    client.shutdown()


def test_disabled_client_releases_its_lease_instead_of_restarting(qapp):
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=200, slot_limit=1)
    client = RenderProcessClient(process_factory=DelayedExitProcess, resource_ledger=ledger,
                                 process_reservation_bytes=100)
    client.start()
    process = client._process
    client._disabled = True
    client._dispose()
    process.exit_now()
    assert client._process is None
    assert ledger.reserved_bytes == 0 and ledger.compute_slots == 0


def test_unavailable_outcomes_carry_a_reason(qapp):
    results = []

    def refused(parent):
        raise OSError('no process')

    client = RenderProcessClient(process_factory=refused)
    client.job_done.connect(lambda key, outcome: results.append((outcome.status, outcome.reason)))
    client.submit(job(client, 'first'))
    qapp.processEvents()
    assert results and results[0] == ('unavailable', 'setup_failed')
    client.submit(job(client, 'second'))
    qapp.processEvents()
    assert results[-1] == ('unavailable', 'disabled_or_closing')
    client.shutdown()
