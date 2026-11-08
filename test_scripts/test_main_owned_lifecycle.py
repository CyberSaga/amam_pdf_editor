from __future__ import annotations

from PySide6.QtCore import SIGNAL

import main


def test_reusing_application_does_not_accumulate_owned_shutdown_handlers(qapp, monkeypatch):
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKER', 'thread')
    first = main.run(argv=[], start_event_loop=False)
    first_handlers = qapp.receivers(SIGNAL('lastWindowClosed()'))
    first['view'].close()
    qapp.processEvents()
    second = main.run(argv=[], start_event_loop=False)
    try:
        assert qapp.receivers(SIGNAL('lastWindowClosed()')) == first_handlers
    finally:
        second['view'].close()
        qapp.processEvents()
        qapp.setStyleSheet('')


def test_raster_child_start_overlaps_native_window_show(qapp, monkeypatch):
    from src.render_worker import process_pool
    from view.pdf_view import PDFView

    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKER', 'process')
    clients = []
    observed = []

    class Client:
        _process = None

        def __init__(self, parent, **kwargs):
            self.started = False
            clients.append(self)

        def start(self):
            self.started = True

        def shutdown(self):
            pass

    original_show = PDFView.show

    def show(view):
        observed.append(clients[0].started)
        original_show(view)

    monkeypatch.setattr(process_pool, 'RenderProcessPool', Client)
    monkeypatch.setattr(PDFView, 'show', show)
    startup = main.run(argv=[], start_event_loop=False)
    try:
        assert observed == [True]
    finally:
        startup['view'].close()
        qapp.processEvents()
        qapp.setStyleSheet('')


def test_process_entry_owns_one_shared_pool_with_unknown_admission(qapp, monkeypatch, tmp_path):
    import fitz
    from PySide6.QtTest import QTest
    from src.render_worker.process_pool import RenderProcessPool

    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKER', 'process')
    path = tmp_path / 'entry.pdf'
    with fitz.open() as document:
        document.new_page()
        document.save(path)
    startup = main.run(argv=[str(path)], start_event_loop=False)
    try:
        pool = startup['render_client']
        assert isinstance(pool, RenderProcessPool)
        assert len(pool.children) == 1
        assert startup['controller']._render_client is pool
    finally:
        startup['view'].close()
        for service in qapp._pdf_owned_services:
            service.shutdown()
        for _ in range(500):
            if all(service._process is None for service in qapp._pdf_owned_services):
                break
            QTest.qWait(10)
        assert all(service._process is None for service in qapp._pdf_owned_services)
        qapp.setStyleSheet('')


def test_about_to_quit_cannot_reenter_owned_shutdown(qapp, monkeypatch):
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKER', 'thread')
    startup = main.run(argv=[], start_event_loop=False)
    quits = []

    def quit_with_signal():
        quits.append(True)
        if len(quits) < 8:
            qapp.aboutToQuit.emit()

    monkeypatch.setattr(qapp, 'quit', quit_with_signal)
    try:
        qapp._pdf_owned_shutdown()
        assert len(quits) == 1
    finally:
        startup['view'].close()
        qapp.processEvents()
        qapp.setStyleSheet('')


def _process_run(qapp, monkeypatch, tmp_path=None, argv=()):
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKER', 'process')
    return main.run(argv=list(argv), start_event_loop=False)


def _finish(qapp, startup):
    startup['view'].close()
    for service in qapp._pdf_owned_services:
        service.shutdown()
    qapp.processEvents()
    qapp.setStyleSheet('')


def test_thread_mode_builds_no_resource_ledger(qapp, monkeypatch):
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKER', 'thread')
    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    startup = main.run(argv=[], start_event_loop=False)
    try:
        assert 'resource_ledger' not in startup
        assert getattr(qapp, '_pdf_resource_ledger', None) is None
    finally:
        startup['view'].close()
        qapp.processEvents()
        qapp.setStyleSheet('')


def test_process_mode_charges_the_first_renderer_to_one_app_wide_ledger(qapp, monkeypatch):
    from src.render_worker import admission

    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    startup = _process_run(qapp, monkeypatch)
    try:
        ledger = startup['resource_ledger']
        pool = startup['render_client']
        assert qapp._pdf_resource_ledger is ledger
        assert pool.children[0]._resource_ledger is ledger
        assert pool.children[0]._process_reservation_bytes == admission.REQUIRED_RENDER_CHARGE
        assert pool.children[0]._admission == 'required'
        assert ledger.stats()['reserved_bytes'] == admission.REQUIRED_RENDER_CHARGE
        assert ledger.compute_slots == 1
    finally:
        _finish(qapp, startup)


def test_second_run_on_the_same_application_reuses_the_ledger(qapp, monkeypatch):
    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    first = _process_run(qapp, monkeypatch)
    ledger = first['resource_ledger']
    _finish(qapp, first)
    second = _process_run(qapp, monkeypatch)
    try:
        assert second['resource_ledger'] is ledger
    finally:
        _finish(qapp, second)


def test_unknown_os_memory_never_admits_a_second_renderer(qapp, monkeypatch):
    from src.render_worker import memory

    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKERS', '2')
    monkeypatch.setattr(memory, 'read_system_memory', lambda: None)
    startup = _process_run(qapp, monkeypatch)
    try:
        assert startup['resource_ledger'].stats()['byte_limit'] == 0
        assert startup['render_client']._admitted() is False
    finally:
        _finish(qapp, startup)


def test_second_renderer_needs_the_explicit_flag_and_os_headroom(qapp, monkeypatch):
    from src.render_worker import memory

    plentiful = memory.SystemMemory(total_phys=32 << 30, avail_phys=16 << 30, avail_commit=24 << 30)
    monkeypatch.setattr(memory, 'read_system_memory', lambda: plentiful)
    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKERS', '1')
    startup = _process_run(qapp, monkeypatch)
    try:
        assert startup['render_client']._admitted() is False, 'one worker was requested'
    finally:
        _finish(qapp, startup)
    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKERS', '2')
    startup = _process_run(qapp, monkeypatch)
    try:
        assert startup['render_client']._admitted() is True
    finally:
        _finish(qapp, startup)


def test_requested_worker_count_sets_the_ledger_slots_and_pool_size(qapp, monkeypatch):
    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKERS', '3')
    startup = _process_run(qapp, monkeypatch)
    try:
        assert startup['resource_ledger'].stats()['slot_limit'] == 3
        assert startup['render_client']._max_children == 3
    finally:
        _finish(qapp, startup)
