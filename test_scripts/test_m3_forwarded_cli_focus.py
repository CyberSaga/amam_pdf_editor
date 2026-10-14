"""Tests: handle_forwarded_cli sets focus on graphics_view after activation."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest
from PySide6.QtCore import Qt


class TestForwardedCliFocus:
    """When a PDF is forwarded via CLI to an existing instance, the graphics_view
    must receive keyboard focus so PgUp/PgDn navigation works immediately."""

    def test_handle_forwarded_cli_focuses_graphics_view(self):
        from controller.pdf_controller import PDFController

        mock_model = MagicMock()
        mock_model.doc = None
        mock_view = MagicMock()
        mock_view.isMinimized.return_value = False

        with patch.object(PDFController, "__init__", lambda self, *a, **kw: None):
            ctrl = PDFController.__new__(PDFController)

        ctrl.model = mock_model
        ctrl.view = mock_view
        ctrl.activate = MagicMock()
        ctrl.open_pdf = MagicMock()

        ctrl.handle_forwarded_cli(["/tmp/test.pdf"])

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        app.processEvents()

        mock_view.raise_.assert_called()
        mock_view.activateWindow.assert_called()
        mock_view.graphics_view.setFocus.assert_called_with(
            Qt.FocusReason.ActiveWindowFocusReason
        )

    def test_focus_is_set_after_open_pdf_so_document_loading_cannot_steal_it(self):
        """setFocus must run after the forwarded-files open_pdf loop, otherwise
        opening a document (which can rebuild focus-stealing widgets) could
        clobber the focus we just set."""
        from controller.pdf_controller import PDFController

        mock_model = MagicMock()
        mock_model.doc = None
        mock_view = MagicMock()
        mock_view.isMinimized.return_value = False

        manager = MagicMock()
        manager.attach_mock(mock_view.graphics_view.setFocus, "setFocus")

        with patch.object(PDFController, "__init__", lambda self, *a, **kw: None):
            ctrl = PDFController.__new__(PDFController)

        ctrl.model = mock_model
        ctrl.view = mock_view
        ctrl.activate = MagicMock()

        def _fake_open_pdf(path):
            return None

        ctrl.open_pdf = MagicMock(side_effect=_fake_open_pdf)
        manager.attach_mock(ctrl.open_pdf, "open_pdf")

        ctrl.handle_forwarded_cli(["/tmp/test.pdf", "/tmp/test2.pdf"])

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        app.processEvents()

        call_names = [call[0] for call in manager.mock_calls]
        assert call_names.count("open_pdf") == 2
        last_open_pdf_index = max(
            idx for idx, name in enumerate(call_names) if name == "open_pdf"
        )
        set_focus_index = call_names.index("setFocus")
        assert set_focus_index > last_open_pdf_index


# ---------------------------------------------------------------------------
# F11-1: a hand-off that arrives while a modal dialog is open must not switch
# the active tab under the dialog.  A nested exec() loop dispatches timers, so
# the forwarded open used to run inside the dialog and the dialog's result
# (Save As target, merge list, optimize options...) landed on the new tab.
# ---------------------------------------------------------------------------

def _make_pdf(path: Path, label: str) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 100), f"{label} page 1", fontsize=14, fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


def _pdf_text(path: Path) -> str:
    doc = fitz.open(str(path))
    try:
        return " | ".join(page.get_text().strip() for page in doc)
    finally:
        doc.close()


def _pump_events(ms: int = 150) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _active_name(model) -> str:
    sid = model.get_active_session_id()
    return model.get_session_meta(sid)["display_name"] if sid else ""


def _run_modal(parent, during_ms: int, action, close_ms: int, probe=None) -> None:
    """Run a genuine QDialog.exec() (stand-in for a native dialog's loop):
    ``action`` fires inside the modal loop, ``probe`` just before it closes."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    dialog = QDialog(parent)
    QTimer.singleShot(during_ms, action)
    if probe is not None:
        QTimer.singleShot(close_ms - 50, probe)
    QTimer.singleShot(close_ms, dialog.accept)
    dialog.exec()


@pytest.fixture()
def real_mvc(monkeypatch, qapp):
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None)
    )
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)

    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    yield model, view, controller
    model.close()
    view.close()
    _pump_events(50)


class TestForwardedCliWaitsForModal:
    def test_forwarded_open_during_save_as_dialog_saves_the_dialogs_document(
        self, real_mvc, monkeypatch, tmp_path
    ):
        from PySide6.QtWidgets import QFileDialog

        model, view, controller = real_mvc
        a = _make_pdf(tmp_path / "A.pdf", "AAAA")
        b = _make_pdf(tmp_path / "B.pdf", "BBBB")
        target = tmp_path / "A_copy.pdf"
        controller.open_pdf(str(a))
        _pump_events()
        sid_a = model.get_active_session_id()
        seen: dict[str, object] = {}

        def fake_get_save(*_args, **_kwargs):
            _run_modal(
                view,
                50,
                lambda: controller.handle_forwarded_cli([str(b)]),
                500,
                probe=lambda: seen.update(
                    active=_active_name(model), sessions=len(model.session_ids)
                ),
            )
            return str(target), "PDF (*.pdf)"

        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_get_save))
        view._save_as()

        # Nothing switched under the dialog...
        assert seen == {"active": "A.pdf", "sessions": 1}
        # ...so the file the user named for A holds A, and A is bound to it.
        assert _pdf_text(target) == "AAAA page 1"
        assert Path(model.get_session_meta(sid_a)["saved_path"]) == target
        # The hand-off is not lost: it opens (and activates) once the dialog is gone.
        _pump_events(600)
        assert len(model.session_ids) == 2
        assert _active_name(model) == "B.pdf"
        assert _pdf_text(b) == "BBBB page 1"

    def test_forwarded_opens_wait_for_the_modal_and_keep_their_order(self, real_mvc, tmp_path):
        model, view, controller = real_mvc
        a = _make_pdf(tmp_path / "A.pdf", "AAAA")
        b = _make_pdf(tmp_path / "B.pdf", "BBBB")
        c = _make_pdf(tmp_path / "C.pdf", "CCCC")
        controller.open_pdf(str(a))
        _pump_events()
        seen: dict[str, object] = {}

        def forward_two() -> None:
            controller.handle_forwarded_cli([str(b)])
            controller.handle_forwarded_cli([str(c)])

        _run_modal(
            view,
            50,
            forward_two,
            500,
            probe=lambda: seen.update(active=_active_name(model), sessions=len(model.session_ids)),
        )
        assert seen == {"active": "A.pdf", "sessions": 1}
        assert len(model.session_ids) == 1

        _pump_events(600)
        names = [model.get_session_meta(sid)["display_name"] for sid in model.session_ids]
        assert names == ["A.pdf", "B.pdf", "C.pdf"]
        assert _active_name(model) == "C.pdf"

    def test_forwarded_open_without_a_modal_still_opens_on_next_turn(self, real_mvc, tmp_path):
        model, _view, controller = real_mvc
        a = _make_pdf(tmp_path / "A.pdf", "AAAA")
        controller.handle_forwarded_cli([str(a)])
        assert len(model.session_ids) == 0
        _pump_events(100)
        assert _active_name(model) == "A.pdf"
