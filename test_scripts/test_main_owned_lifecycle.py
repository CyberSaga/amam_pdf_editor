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

        def __init__(self, parent):
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
