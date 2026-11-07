from __future__ import annotations

import time

import pytest


def wait_for(qapp, condition, seconds=4):
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(.001)
    assert condition()


def test_recent_probe_returns_existing_and_missing_without_gui_stat(qapp, tmp_path):
    from controller.recent_file_probe import RecentFileProbe

    existing = tmp_path / 'existing.pdf'
    existing.write_bytes(b'%PDF-1.4\n')
    paths = [str(existing), str(tmp_path / 'missing.pdf')]
    probe = RecentFileProbe(qapp)
    results = []
    probe.result.connect(lambda key, available: results.append((key, available)))
    try:
        probe.request(paths)
        wait_for(qapp, lambda: len(results) == 2 and probe.idle)
        assert dict(results) == {paths[0]: True, paths[1]: False}
    finally:
        probe.shutdown()
        wait_for(qapp, lambda: probe.idle)


def test_recent_probe_latest_request_discards_old_entries(qapp, tmp_path):
    from controller.recent_file_probe import RecentFileProbe

    probe = RecentFileProbe(qapp)
    results = []
    probe.result.connect(lambda key, available: results.append(key))
    try:
        probe.request([str(tmp_path / 'old.pdf')])
        probe.request([str(tmp_path / 'new.pdf')])
        wait_for(qapp, lambda: probe.idle and bool(results))
        assert results == [str(tmp_path / 'new.pdf')]
    finally:
        probe.shutdown()
        wait_for(qapp, lambda: probe.idle)


def test_recent_probe_timeout_reaps_without_claiming_missing(qapp, tmp_path):
    from controller.recent_file_probe import RecentFileProbe

    probe = RecentFileProbe(qapp)
    results = []
    probe.result.connect(lambda *result: results.append(result))
    probe.request([str(tmp_path / 'unknown.pdf')])
    probe._timeout()
    wait_for(qapp, lambda: probe.idle)
    assert results == []
    assert probe._cache == {}
    probe.shutdown()


def test_stalled_first_entry_does_not_starve_later_local_file(qapp, tmp_path):
    from controller.recent_file_probe import RecentFileProbe

    class BlockedProcess:
        def kill(self):
            pass

        def readAllStandardOutput(self):
            return b''

        def deleteLater(self):
            pass

    local = tmp_path / 'local.pdf'
    local.write_bytes(b'%PDF-1.4\n')
    probe = RecentFileProbe(qapp)
    probe._paths = ('unresponsive-history-entry', str(local))
    probe._process = BlockedProcess()
    results = []
    probe.result.connect(lambda path, available: results.append((path, available)))
    probe._timeout()
    probe._finished()
    try:
        wait_for(qapp, lambda: probe.idle and bool(results))
        assert results == [(str(local), True)]
    finally:
        probe.shutdown()
        wait_for(qapp, lambda: probe.idle)


def test_replacement_from_result_callback_discards_buffered_old_results(qapp):
    from controller.recent_file_probe import RecentFileProbe

    class Process:
        def readAllStandardOutput(self):
            return b'[0, true]\n[1, true]\n'

        def kill(self):
            pass

    probe = RecentFileProbe(qapp)
    probe._process = Process()
    probe._paths = ('old-first', 'old-second')
    results = []

    def receive(path, available):
        results.append(path)
        probe.request(['new'])

    probe.result.connect(receive)
    probe._read()
    assert results == ['old-first']
    probe._process = None
    probe.shutdown()


def test_recent_refresh_does_not_probe_on_gui_thread(qapp, monkeypatch):
    from pathlib import Path
    from controller.pdf_controller import PDFController

    class Preferences:
        def get_recent_files(self):
            return ['missing.pdf']

    class Probe:
        def request(self, paths):
            self.paths = paths

    class View:
        def set_recent_files(self, entries):
            self.entries = entries

    def forbidden(*args):
        pytest.fail('recent menu did synchronous filesystem I/O')

    controller = PDFController.__new__(PDFController)
    controller._prefs = Preferences()
    controller._recent_probe = Probe()
    controller._recent_availability = {}
    controller.view = View()
    monkeypatch.setattr(Path, 'is_file', forbidden)
    controller._refresh_recent_files()
    assert controller._recent_probe.paths == ['missing.pdf']
    assert controller.view.entries[0]['available'] is None
