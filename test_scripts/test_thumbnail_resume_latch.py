"""Thumbnails must not stay as bare page numbers (docs/to_Update.md line 6).

A visible page render pauses the thumbnail pass by putting the session in
``_thumbnail_resume_pending_by_session``; only the render batch's own end
resumes it.  A batch cancelled through ``_cancel_page_render_for_session``
(every render-visible edit bumps the render revision, which cancels) cleared
the batch's pending flag but left the pause latch set, so every later
``_schedule_thumbnail_batch`` returned early: after a page operation reset the
list to placeholders, the rows kept only their "頁N" labels until some later
scroll happened to start and finish another render batch.
"""
from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view, leaked_gui_since, snapshot_visible_gui
from view.pdf_view import PDFView


def _pump_until(predicate, timeout_ms: int = 5000) -> bool:
    app = QApplication.instance()
    assert app is not None
    end = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


@pytest.fixture(autouse=True)
def _no_stray_gui_state():
    before = snapshot_visible_gui()
    yield
    leaked = leaked_gui_since(before)
    assert not leaked, "this test left GUI state behind for the next test: " + "; ".join(leaked)


@pytest.fixture
def mvc(monkeypatch, qapp):
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    try:
        yield model, view, controller
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "thumbs-12p.pdf"
    with fitz.open() as doc:
        for number in range(12):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {number + 1}", fontsize=24, fontname="helv")
        doc.save(path)
    return path


def _all_icons(view) -> bool:
    tl = view.thumbnail_list
    return tl.count() > 0 and all(not tl.item(i).icon().isNull() for i in range(tl.count()))


def _open_settled(mvc, path: Path):
    model, view, controller = mvc
    view.resize(1200, 800)
    view.show()
    controller.open_pdf(str(path))
    assert _pump_until(lambda: _all_icons(view), 8000)
    sid = model.get_active_session_id()
    assert _pump_until(lambda: not controller._render_batch_pending_by_session.get(sid), 5000)
    return model, view, controller, sid


def test_a_cancelled_render_batch_releases_the_thumbnail_pause(mvc, pdf_path):
    model, view, controller, sid = _open_settled(mvc, pdf_path)
    controller._schedule_visible_render(sid)
    assert sid in controller._thumbnail_resume_pending_by_session

    # A render-visible edit cancels the in-flight batch.
    controller._bump_render_revision(sid)

    assert sid not in controller._thumbnail_resume_pending_by_session


def test_thumbnails_return_after_a_cancelled_render_and_a_placeholder_reset(mvc, pdf_path):
    model, view, controller, sid = _open_settled(mvc, pdf_path)
    controller._schedule_visible_render(sid)
    controller._bump_render_revision(sid)

    # Structural refresh: every row back to a "頁N" placeholder, no scrolling after.
    controller._invalidate_thumbnails()
    assert not _all_icons(view)

    assert _pump_until(lambda: _all_icons(view), 8000), [
        view.thumbnail_list.item(i).text()
        for i in range(view.thumbnail_list.count())
        if view.thumbnail_list.item(i).icon().isNull()
    ]
