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


def test_probe_charges_the_ledger_for_its_process_lifetime(qapp, tmp_path):
    from controller.recent_file_probe import RecentFileProbe
    from src.render_worker import admission
    from src.render_worker.resource_ledger import ResourceLedger

    existing = tmp_path / 'existing.pdf'
    existing.write_bytes(b'%PDF-1.4\n')
    ledger = ResourceLedger(byte_limit=admission.PROBE_CHARGE, slot_limit=2)
    probe = RecentFileProbe(qapp, ledger=ledger)
    results = []
    probe.result.connect(lambda key, available: results.append(available))
    try:
        probe.request([str(existing)])
        assert ledger.reserved_bytes == admission.PROBE_CHARGE
        assert ledger.compute_slots == 0
        wait_for(qapp, lambda: results == [True] and probe.idle)
        assert ledger.reserved_bytes == 0, 'the lease is released at confirmed exit'
    finally:
        probe.shutdown()
        wait_for(qapp, lambda: probe.idle)


def test_probe_is_never_refused_by_bytes_even_when_the_renderers_fill_the_budget(qapp, tmp_path):
    from controller.recent_file_probe import RecentFileProbe
    from src.render_worker import admission
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=admission.REQUIRED_RENDER_CHARGE + admission.OPTIONAL_ALLOWANCE,
                            slot_limit=2)
    ledger.try_reserve('first', 'process', admission.REQUIRED_RENDER_CHARGE, compute_slots=1, required=True)
    ledger.try_reserve('second', 'process', admission.OPTIONAL_RENDER_CHARGE, compute_slots=1)
    existing = tmp_path / 'existing.pdf'
    existing.write_bytes(b'%PDF-1.4\n')
    probe = RecentFileProbe(qapp, ledger=ledger)
    results = []
    probe.result.connect(lambda key, available: results.append(available))
    try:
        probe.request([str(existing)])
        assert probe._process is not None, 'a refused probe would leave history unverified all session'
        wait_for(qapp, lambda: results == [True] and probe.idle)
        assert ledger.stats()['overcommits'] == 1 and ledger.stats()['refusals'] == {}
    finally:
        probe.shutdown()
        wait_for(qapp, lambda: probe.idle)


def test_probe_lease_survives_cancel_until_the_old_child_exits(qapp, tmp_path):
    from controller.recent_file_probe import RecentFileProbe
    from src.render_worker import admission
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = ResourceLedger(byte_limit=admission.PROBE_CHARGE, slot_limit=2)
    probe = RecentFileProbe(qapp, ledger=ledger)
    results = []
    probe.result.connect(lambda key, available: results.append(key))
    try:
        probe.request([str(tmp_path / 'old.pdf')])
        probe.request([str(tmp_path / 'new.pdf')])
        assert ledger.reserved_bytes == admission.PROBE_CHARGE, 'the cancelled child still counts'
        wait_for(qapp, lambda: probe.idle and bool(results))
        assert results == [str(tmp_path / 'new.pdf')]
        assert ledger.reserved_bytes == 0 and ledger.stats()['refusals'] == {}
    finally:
        probe.shutdown()
        wait_for(qapp, lambda: probe.idle)


def test_for_app_hands_the_ledger_to_the_shared_probe(qapp):
    from controller.recent_file_probe import RecentFileProbe
    from src.render_worker.resource_ledger import ResourceLedger

    qapp._pdf_recent_probe = None
    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    probe = RecentFileProbe.for_app(qapp, ledger=ledger)
    try:
        assert probe._ledger is ledger
        assert RecentFileProbe.for_app(qapp) is probe
    finally:
        probe.shutdown()
        qapp._pdf_recent_probe = None


# --- cold open: one metadata child per open, not one per activate() plus one per open ----------


class _MemoryStore:
    def __init__(self) -> None:
        self._data: dict = {}

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
        return self._data.get(key, default)

    def setValue(self, key, value) -> None:
        self._data[key] = value

    def remove(self, key) -> None:
        self._data.pop(key, None)

    def contains(self, key) -> bool:
        return key in self._data

    def sync(self) -> None:
        return None


@pytest.fixture
def cold_open(qapp, tmp_path, monkeypatch):
    """A real controller over a seeded history with a fake child process.

    The fake records every ``start()`` and, like a real QProcess, delivers ``finished`` on
    ``kill()`` (that is what makes a replaced request relaunch).  Nothing is spawned.
    """
    import fitz
    from PySide6.QtCore import QProcess

    import controller.recent_file_probe as recent
    import utils.preferences as preferences
    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    store = _MemoryStore()
    older = str(tmp_path / "older.pdf")
    store.setValue("files/recent", [older])
    monkeypatch.setattr(preferences, "_make_default_store", lambda: store)
    # The history refuses temp-dir files (so tests never fill it); the memory store cannot leak.
    monkeypatch.setattr(preferences.UserPreferences, "_is_temporary_path", classmethod(lambda cls, path: False))
    starts: list[tuple[str, list[str]]] = []

    class FakeProcess(QProcess):
        def start(self, *args):
            starts.append((self.program(), list(self.arguments())))

        def kill(self):
            self.finished.emit(0, QProcess.ExitStatus.NormalExit)

    monkeypatch.setattr(recent, "QProcess", FakeProcess)
    qapp._pdf_recent_probe = None
    pdf = tmp_path / "cold.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(pdf))

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    try:
        yield qapp, controller, str(pdf), starts
    finally:
        controller.release_render_owner()
        probe = getattr(qapp, "_pdf_recent_probe", None)
        if probe is not None:
            probe.shutdown()
        qapp.processEvents()
        model.close()
        view.close()
        qapp.processEvents()
        qapp._pdf_recent_probe = None


def _pump(qapp, rounds: int = 5) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def test_cold_open_launches_exactly_one_probe(cold_open):
    from src.render_worker.launch import child_launch

    qapp, controller, pdf, starts = cold_open
    controller.activate()
    controller.open_pdf(pdf)
    _pump(qapp)
    assert len(starts) == 1, "activate() plus the open's own refresh must share one child"
    assert starts[0] == child_launch("recent-probe")
    assert controller._prefs.get_recent_files()[0] == pdf


def test_activate_alone_does_not_spawn_before_the_loop_runs(cold_open):
    _qapp, controller, _pdf, starts = cold_open
    controller.activate()
    assert starts == [], "an open may be imminent: the child is requested after it, or on the next loop turn"


def test_activate_without_an_open_still_requests_one_probe(cold_open):
    qapp, controller, _pdf, starts = cold_open
    controller.activate()
    assert starts == []
    _pump(qapp)
    assert len(starts) == 1
    _pump(qapp)
    assert len(starts) == 1


def test_failed_open_does_not_lose_the_deferred_probe(cold_open, monkeypatch, tmp_path):
    import controller.pdf_controller as controller_module

    qapp, controller, _pdf, starts = cold_open
    monkeypatch.setattr(controller_module, "show_error", lambda *args, **kwargs: None)
    controller.activate()
    controller.open_pdf(str(tmp_path / "does-not-exist.pdf"))
    assert controller._prefs.get_recent_files() == [str(tmp_path / "older.pdf")]
    _pump(qapp)
    assert len(starts) == 1
