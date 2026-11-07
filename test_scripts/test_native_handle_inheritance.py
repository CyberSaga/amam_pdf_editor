from __future__ import annotations

import sys
import time
import os

import fitz
import pytest

from controller.recent_file_probe import RecentFileProbe
from model.pdf_model import PDFModel
from utils import file_share_lock


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native handle inheritance')
def test_metadata_child_does_not_inherit_native_pdf_reader(qapp, tmp_path):
    path = tmp_path / 'not-a-metadata-reader.pdf'
    with fitz.open() as document:
        document.new_page()
        document.save(path)
    model = PDFModel()
    probe = RecentFileProbe(qapp)
    try:
        model.open_pdf(str(path))
        probe.request([str(path)])
        assert not probe.idle
        process = probe._process
        process.started.disconnect(probe._started)
        assert process.waitForStarted(2000)
        # Deliberately do not pump the event loop: the child's stdin is not yet
        # delivered and the live child cannot have opened the file itself.
        model.close()
        assert not file_share_lock.is_locked(str(path))
        path.unlink()
        assert not path.exists()
        assert process.state() == process.ProcessState.Running
    finally:
        model.close()
        probe.shutdown()
        deadline = time.monotonic() + 5
        while not probe.idle and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(.005)
        assert probe.idle


def test_guard_changes_disk_handles_only_and_keeps_changes_permanent():
    from utils.native_handle_inheritance import _prepare_disk_handles

    handles = {3: 30, 5: 50, 7: 70}
    inherited = {30: True, 50: True, 70: False}
    changed = []

    def lookup(fd):
        if fd not in handles:
            raise OSError('descriptor hole')
        return handles[fd]

    def mark(handle, value):
        changed.append((handle, value))
        inherited[handle] = value

    result = _prepare_disk_handles(lookup, lambda handle: 3 if handle == 50 else 1,
                                   inherited.__getitem__, mark)
    assert result == 1
    assert changed == [(30, False)]
    assert inherited == {30: False, 50: True, 70: False}


def test_guard_failure_does_not_claim_safe_launch():
    from utils.native_handle_inheritance import _prepare_disk_handles

    def lookup(fd):
        if fd == 3:
            return 30
        raise OSError('hole')

    def refuse(handle, value):
        raise PermissionError('cannot change inherited disk handle')

    with pytest.raises(PermissionError, match='cannot change'):
        _prepare_disk_handles(lookup, lambda handle: 1, lambda handle: True, refuse)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native descriptor table')
def test_guard_covers_lowio_descriptor_above_stdio_limit(tmp_path):
    import msvcrt
    from utils.native_handle_inheritance import prepare_owned_qprocess_start

    try:
        msvcrt.get_osfhandle(1024)
    except OSError:
        pass
    else:
        pytest.skip('descriptor already in use; do not overwrite it')
    source = os.open(tmp_path / 'high-descriptor.bin', os.O_CREAT | os.O_RDWR)
    try:
        os.dup2(source, 1024, inheritable=True)
        assert os.get_handle_inheritable(msvcrt.get_osfhandle(1024))
        prepare_owned_qprocess_start()
        assert not os.get_handle_inheritable(msvcrt.get_osfhandle(1024))
    finally:
        os.close(source)
        os.close(1024)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native handle inheritance')
@pytest.mark.parametrize('owner', ['render', 'printing'])
def test_other_owned_children_do_not_retain_two_open_pdf_readers(qapp, tmp_path, owner):
    from PySide6.QtCore import QProcess
    from src.render_worker.process_client import RenderProcessClient
    from src.printing.base_driver import PrintJobOptions
    from src.printing.helper_protocol import PrintHelperJob
    from src.printing.subprocess_runner import PrintSubprocessRunner

    paths = [tmp_path / f'reader-{number}.pdf' for number in range(2)]
    model = PDFModel()
    client = None
    runner = None
    process = None
    for path in paths:
        with fitz.open() as doc:
            doc.new_page()
            doc.save(path)
        model.open_pdf(str(path))
    try:
        if owner == 'render':
            client = RenderProcessClient()
            client.start()
            process = client._process
        else:
            class WaitingPrinter(QProcess):
                def start(self, *args):
                    # Mock the external printer boundary, not process creation,
                    # handle inheritance, the real PDF or pipe transport.
                    super().start(getattr(sys, '_base_executable', sys.executable),
                                  ['-I', '-S', '-c', 'import sys; sys.stdin.buffer.read()'])

            job = PrintHelperJob(job_id='inheritance', input_pdf_path='', watermarks=[],
                                 options=PrintJobOptions(printer_name='no-physical-print'))
            runner = PrintSubprocessRunner(job, process_factory=WaitingPrinter)
            runner.start()
            process = runner._process
        assert process is not None and process.waitForStarted(2000)
        model.close()
        for path in paths:
            assert not file_share_lock.is_locked(str(path))
            path.unlink()
        assert process.state() == QProcess.ProcessState.Running
    finally:
        model.close()
        if client is not None:
            client.shutdown()
        elif process is not None:
            process.closeWriteChannel()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            qapp.processEvents()
            if ((client is not None and client._process is None)
                    or (runner is not None and runner._process is None)):
                break
            time.sleep(.005)
        assert (client._process if client is not None else runner._process) is None


@pytest.mark.parametrize('owner', ['metadata', 'render', 'printing'])
def test_guard_failure_leaves_no_started_helper_or_live_work(qapp, tmp_path, monkeypatch, owner):
    from PySide6.QtCore import QProcess
    import controller.recent_file_probe as recent
    import utils.native_handle_inheritance as guard
    from src.render_worker.process_client import RenderProcessClient
    from src.printing.base_driver import PrintJobOptions
    from src.printing.helper_protocol import PrintHelperJob
    from src.printing.subprocess_runner import PrintSubprocessRunner

    starts = []

    class Process(QProcess):
        def start(self, *args):
            starts.append(args)
            pytest.fail('unsafe child must not start')

    def refuse():
        raise PermissionError('injected unsafe inherited reader')

    monkeypatch.setattr(guard, 'prepare_owned_qprocess_start', refuse)
    monkeypatch.setattr(recent, 'prepare_owned_qprocess_start', refuse)
    if owner == 'metadata':
        monkeypatch.setattr(recent, 'QProcess', Process)
        target = RecentFileProbe(qapp)
        results = []
        target.result.connect(lambda *args: results.append(args))
        target.request([str(tmp_path / 'unknown.pdf')])
        assert target.idle and results == []
        target.shutdown()
    elif owner == 'render':
        target = RenderProcessClient(process_factory=Process)
        target.start()
        assert target._disabled
        assert target.metrics['starts'] == 0
        target.shutdown()
    else:
        job = PrintHelperJob(job_id='refused', input_pdf_path='', watermarks=[],
                             options=PrintJobOptions(printer_name='no-physical-print'))
        target = PrintSubprocessRunner(job, process_factory=Process)
        errors, finished = [], []
        target.failed.connect(errors.append)
        target.finished.connect(lambda: finished.append(True))
        target.start()
        assert len(errors) == 1 and finished == [True]
        assert target._pdf_bytes is None and target._helper_password is None
    assert target._process is None
    assert starts == []
