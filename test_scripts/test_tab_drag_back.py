"""Drag a detached window's tab back into another window (docs/to_Update.md line 25).

M3.8 only detached: releasing a dragged tab anywhere outside its own tab bar
always opened a NEW window, so a tab could never return to the window it came
from.  A release over another editor window now moves the tab into that window;
a secondary window left without tabs closes (the primary keeps its empty shell,
as with Ctrl+W).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as main_module  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from controller.session_transfer import SessionTransferPayload  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from test_scripts.qt_teardown import dispose_pdf_view  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402


def _pump(ms: int = 200) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def _make_pdf(path: Path, text: str, pages: int = 2) -> Path:
    with fitz.open() as doc:
        for number in range(pages):
            page = doc.new_page(width=300, height=400)
            page.insert_text((36, 72), f"{text} {number + 1}", fontsize=14, fontname="helv")
        doc.save(path)
    return path


def _payload(path: Path, *, dirty: bool = False) -> tuple[PDFModel, SessionTransferPayload]:
    source = PDFModel()
    source.open_pdf(str(path))
    if dirty:
        source.doc[0].insert_text((36, 120), "DIRTY")
        source.edit_count += 1
    payload = SessionTransferPayload.from_model(
        source,
        source.get_active_session_id(),
        current_page=1,
        scale=1.0,
        color_profile="srgb",
    )
    return source, payload


@pytest.fixture
def target(monkeypatch, qapp):
    errors: list[str] = []
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda _parent, msg, *a, **k: errors.append(msg))
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    try:
        yield model, view, controller, errors
    finally:
        dispose_pdf_view(view, controller, model)


def test_adopted_tab_joins_the_window_as_the_active_tab(target, tmp_path):
    model, view, controller, errors = target
    controller.open_pdf(str(_make_pdf(tmp_path / "a.pdf", "A")))
    source, payload = _payload(_make_pdf(tmp_path / "b.pdf", "B", pages=3), dirty=True)
    try:
        assert controller.adopt_transferred_session(payload) is True
    finally:
        source.close()
    _pump()

    assert len(model.session_ids) == 2
    sid = model.get_active_session_id()
    assert model.get_session_meta(sid)["display_name"] == "b.pdf"
    assert model.session_has_unsaved_changes(sid) is True
    assert "DIRTY" in model.doc[0].get_text()
    assert view.document_tab_bar.count() == 2
    assert view.total_pages == 3
    assert errors == []


def test_adopting_a_file_already_open_here_is_refused(target, tmp_path):
    model, view, controller, errors = target
    path = _make_pdf(tmp_path / "same.pdf", "S")
    controller.open_pdf(str(path))
    before = list(model.session_ids)
    source, payload = _payload(path)
    try:
        assert controller.adopt_transferred_session(payload) is False
    finally:
        source.close()

    assert model.session_ids == before
    assert errors and "已在此視窗開啟" in errors[0]


def _close_startup(startup: dict) -> None:
    for ctx in list(startup["secondary_windows"]):
        ctx["view"].close()
        ctx["model"].close()
    startup["view"].close()
    if startup.get("model") is not None:
        startup["model"].close()
    _pump(100)


def test_dragging_a_detached_tab_onto_the_first_window_moves_it_back(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    a = _make_pdf(tmp_path / "a.pdf", "A")
    b = _make_pdf(tmp_path / "b.pdf", "B")
    startup = main_module.run(argv=[str(a), str(b)], start_event_loop=False)
    primary_view = startup["view"]
    primary_model = startup["model"]
    try:
        primary_view.resize(1000, 700)
        primary_view.move(40, 40)
        _pump(800)
        assert len(primary_model.session_ids) == 2
        sid_b = primary_model.get_active_session_id()

        # Detach b well away from the primary window: a new window opens.
        primary_rect = primary_view.frameGeometry()
        far = QPoint(primary_rect.right() + 400, primary_rect.top() + 50)
        startup["controller"].detach_document_session(sid_b, far)
        _pump(800)
        assert len(startup["secondary_windows"]) == 1
        secondary = startup["secondary_windows"][0]
        secondary_view = secondary["view"]
        assert len(primary_model.session_ids) == 1
        secondary_view.move(primary_rect.right() + 60, primary_rect.top())
        _pump(300)

        # Drag it back: release over the primary window's document tab bar
        # (the user's release point is over a visible window: bring it up).
        primary_view.raise_()
        primary_view.activateWindow()
        _pump(300)
        bar = primary_view.document_tab_bar
        drop = bar.mapToGlobal(QPoint(bar.width() // 2, bar.height() // 2))
        assert QApplication.widgetAt(drop) is not None
        assert QApplication.widgetAt(drop).window() is primary_view
        sid_in_secondary = secondary["model"].get_active_session_id()
        secondary["controller"].detach_document_session(sid_in_secondary, drop)
        _pump(800)

        assert len(primary_model.session_ids) == 2
        names = {primary_model.get_session_meta(s)["display_name"] for s in primary_model.session_ids}
        assert names == {"a.pdf", "b.pdf"}
        assert primary_model.get_session_meta(primary_model.get_active_session_id())["display_name"] == "b.pdf"
        assert not secondary_view.isVisible()
        # Views lack WA_DeleteOnClose (`destroyed` never fires); the accepted close's
        # `closed` signal releases the secondary context (worker lifetime W3).
        assert startup["secondary_windows"] == []
        assert not secondary["model"].session_ids
    finally:
        _close_startup(startup)
