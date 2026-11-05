from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QLineEdit, QPushButton

from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view, leaked_gui_since, snapshot_visible_gui
from view.pdf_view import PDFView


def _pump_events(ms: int = 100) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _no_stray_gui_state():
    before = snapshot_visible_gui()
    yield
    leaked = leaked_gui_since(before)
    assert not leaked, "this test left GUI state behind for the next test: " + "; ".join(leaked)


def _mvc_session(monkeypatch):
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    try:
        yield model, view, controller
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.fixture
def mvc(monkeypatch, qapp):
    yield from _mvc_session(monkeypatch)


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "navigation-23p.pdf"
    with fitz.open() as doc:
        for number in range(23):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {number + 1}", fontsize=12, fontname="helv")
        doc.save(path)
    return path


def _open(mvc, path: Path) -> PDFView:
    _, view, controller = mvc
    controller.open_pdf(str(path))
    view.show()
    _pump_events(300)
    assert view.total_pages == 23
    return view


def test_end_home_via_graphics_view_focus(mvc, pdf_path):
    view = _open(mvc, pdf_path)
    view.graphics_view.setFocus()
    for key, expected in ((Qt.Key_End, 22), (Qt.Key_Home, 0)):
        QTest.keyClick(view.graphics_view, key)
        _pump_events()
        assert view.current_page == expected


def test_end_home_via_ribbon_tab_bar_focus(mvc, pdf_path):
    view = _open(mvc, pdf_path)
    tab_bar = view.toolbar_tabs.tabBar()
    tab_bar.setFocus()
    for key, expected in ((Qt.Key_End, 22), (Qt.Key_Home, 0)):
        QTest.keyClick(tab_bar, key)
        _pump_events()
        assert view.current_page == expected


def test_pgup_pgdn_still_move_one_page(mvc, pdf_path):
    view = _open(mvc, pdf_path)
    view.sig_page_changed.emit(4)
    _pump_events()
    for key, expected in ((Qt.Key_PageDown, 5), (Qt.Key_PageUp, 4)):
        QTest.keyClick(view.graphics_view, key)
        _pump_events()
        assert view.current_page == expected
    for boundary, key in ((0, Qt.Key_PageUp), (22, Qt.Key_PageDown)):
        view.sig_page_changed.emit(boundary)
        _pump_events()
        QTest.keyClick(view.graphics_view, key)
        _pump_events()
        assert view.current_page == boundary


def test_nav_keys_not_stolen_from_text_inputs(mvc, pdf_path):
    view = _open(mvc, pdf_path)
    spy = QSignalSpy(view.sig_page_changed)
    for widget in (view.page_number_input, view.search_input, view.thumbnail_list):
        widget.setFocus()
        QTest.keyClick(widget, Qt.Key_Home)
        QTest.keyClick(widget, Qt.Key_End)
    _pump_events()
    assert spy.count() == 0


@pytest.mark.parametrize("target", ["graphics_view", "ribbon"])
def test_home_end_respect_navigation_guards(mvc, pdf_path, target):
    view = _open(mvc, pdf_path)
    widget = view.graphics_view if target == "graphics_view" else view.toolbar_tabs.tabBar()
    spy = QSignalSpy(view.sig_page_changed)
    for modifier in (Qt.ControlModifier, Qt.AltModifier, Qt.MetaModifier):
        for key in (Qt.Key_Home, Qt.Key_End):
            QTest.keyClick(widget, key, modifier)
    view.current_mode = "edit_text"
    QTest.keyClick(widget, Qt.Key_End)
    view.current_mode = "browse"
    editor = QLineEdit(view)
    view.text_editor = editor
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_Home)
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClick(widget, Qt.Key_End)
    view.text_editor = None
    assert spy.count() == 0


def test_ribbon_tab_follows_document_presence(mvc, pdf_path, tmp_path):
    _, view, controller = mvc
    ribbon = view.toolbar_tabs
    def current():
        return ribbon.tabText(ribbon.currentIndex())
    assert current() == "檔案"
    _open(mvc, pdf_path)
    assert current() == "常用"
    edit_index = next(i for i in range(ribbon.count()) if ribbon.tabText(i) == "編輯")
    ribbon.setCurrentIndex(edit_index)
    other = tmp_path / "second-23p.pdf"
    other.write_bytes(pdf_path.read_bytes())
    controller.open_pdf(str(other))
    assert view.document_tab_bar.count() == 2
    assert current() == "編輯"
    controller.on_tab_close_requested(1)
    assert current() == "編輯"
    controller.on_tab_close_requested(0)
    assert current() == "檔案"
    controller.open_pdf(str(pdf_path))
    assert current() == "常用"


def test_delete_dialog_defaults_to_current_page(mvc, monkeypatch):
    _, view, _ = mvc
    view.total_pages = 6

    def inspect(dialog):
        combo = dialog.findChild(QComboBox)
        assert combo.currentData() == "目前頁"
        assert {combo.itemData(i) for i in range(combo.count())} == {
            "目前頁", "全部", "奇數頁", "偶數頁", "自訂範圍",
        }
        combo.setCurrentIndex(combo.findData("全部"))
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", inspect)
    result = view._prompt_delete_page_scope()
    assert result == ("全部", "")
    assert view._pages_for_scope(*result) == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize("operation", ["delete", "rotate"])
def test_custom_scope_inline_input_validates_before_ok(mvc, monkeypatch, operation):
    _, view, _ = mvc
    view.total_pages = 6

    def forbidden(*args, **kwargs):
        raise AssertionError("custom scope must not open a second dialog")

    monkeypatch.setattr("view.pdf_view.QInputDialog.getText", forbidden)

    def inspect(dialog):
        dialog.show()
        _pump_events()
        combo = next(c for c in dialog.findChildren(QComboBox) if c.findData("自訂範圍") >= 0)
        line = dialog.findChild(QLineEdit)
        ok = next(b for b in dialog.findChildren(QPushButton) if b.text() == "確定")
        assert line is not None, "custom range input must live in the original dialog"
        assert not line.isVisible()
        assert ok.isEnabled()
        assert combo.currentData() == ("目前頁" if operation == "delete" else "全部")
        combo.setCurrentIndex(combo.findData("自訂範圍"))
        _pump_events()
        assert line.isVisible()
        assert line.hasFocus()
        assert not ok.isEnabled()
        for raw in ("", "0", "7", "4-2", "1,,3", "abc"):
            line.setText(raw)
            assert not ok.isEnabled(), raw
            assert any(label.isVisible() and "頁碼" in label.text() for label in dialog.findChildren(QLabel))
        line.setText("1,3-4")
        assert ok.isEnabled()
        combo.setCurrentIndex(combo.findData("全部"))
        assert not line.isVisible()
        assert ok.isEnabled()
        combo.setCurrentIndex(combo.findData("自訂範圍"))
        assert line.isVisible()
        assert ok.isEnabled()
        dialog.hide()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", inspect)
    prompt = view._prompt_delete_page_scope if operation == "delete" else view._prompt_page_rotation_options
    result = prompt()
    scope, text = result if operation == "delete" else result[1:]
    assert view._pages_for_scope(scope, text) == [1, 3, 4]
    # This fixture has not activated Controller; inspect the public View payload.
    signal = view.sig_delete_pages if operation == "delete" else view.sig_rotate_pages
    spy = QSignalSpy(signal)
    if operation == "delete":
        view._delete_pages()
        assert spy.at(0) == [[1, 3, 4]]
    else:
        view._rotate_pages()
        assert spy.at(0) == [[1, 3, 4], 90]
    assert spy.count() == 1


@pytest.mark.parametrize("confirm", ["tab_then_enter", "enter_in_field"])
@pytest.mark.parametrize("operation", ["delete", "rotate"])
def test_custom_scope_keyboard_confirm_accepts(mvc, monkeypatch, operation, confirm):
    """Tab from the range field must reach 確定 before 取消, and Enter must accept."""
    _, view, _ = mvc
    view.total_pages = 6

    def inspect(dialog):
        dialog.show()
        _pump_events()
        combo = next(c for c in dialog.findChildren(QComboBox) if c.findData("自訂範圍") >= 0)
        line = dialog.findChild(QLineEdit)
        ok = next(b for b in dialog.findChildren(QPushButton) if b.text() == "確定")
        combo.setCurrentIndex(combo.findData("自訂範圍"))
        _pump_events()
        assert line.hasFocus()
        line.setText("1,3-4")
        assert ok.isEnabled()
        if confirm == "tab_then_enter":
            QTest.keyClick(line, Qt.Key_Tab)
            _pump_events()
            assert ok.hasFocus(), "Tab from the range field must land on 確定, not 取消"
            QTest.keyClick(ok, Qt.Key_Return)
        else:
            QTest.keyClick(line, Qt.Key_Return)
        _pump_events()
        result = dialog.result()
        dialog.hide()
        return result

    monkeypatch.setattr(QDialog, "exec", inspect)
    prompt = view._prompt_delete_page_scope if operation == "delete" else view._prompt_page_rotation_options
    result = prompt()
    assert result is not None, "keyboard confirmation rejected the dialog"
    scope, text = result if operation == "delete" else result[1:]
    assert (scope, text) == ("自訂範圍", "1,3-4")


@pytest.mark.parametrize("operation", ["delete", "rotate"])
def test_scope_dialog_cancel_emits_nothing(mvc, monkeypatch, operation):
    _, view, _ = mvc
    view.total_pages = 6
    monkeypatch.setattr(QDialog, "exec", lambda dialog: QDialog.Rejected)
    spy = QSignalSpy(view.sig_delete_pages if operation == "delete" else view.sig_rotate_pages)
    (view._delete_pages if operation == "delete" else view._rotate_pages)()
    assert spy.count() == 0
