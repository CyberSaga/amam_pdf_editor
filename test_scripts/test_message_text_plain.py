"""CF6: a file name or PDF-derived string shown in a Qt text widget stays text.

Qt's default text format is AutoText: ``Qt::mightBeRichText('report<b>x</b>.pdf')``
is True, so a message box, label or tooltip that interpolates such a name would
render markup (bold, links, ``<img>``).  Every site that shows a file name, a
path, a tab title or an exception text goes through
``view.message_boxes.plain_text``, which leaves a normal string alone and
escapes a markup-looking one.  The tests compare what the widget would SHOW
with the raw string, so they hold whichever way the fix is done.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QTextDocument
from PySide6.QtGui import Qt as QtGuiNamespace  # PySide6 puts mightBeRichText here, not on QtCore.Qt
from PySide6.QtWidgets import QLabel, QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[1]

HOSTILE_NAMES = [
    "report<b>x</b>.pdf",
    'x<img src="file:///c:/a.png">.pdf',
    '<a href="http://e.test/">z</a>.pdf',
    "a&lt;b.pdf",  # Qt treats a leading '&lt;' as a rich-text hint too
]


def _shown(text: str) -> str:
    """The characters a QLabel/QMessageBox/QToolTip would draw for ``text`` in AutoText."""
    if not QtGuiNamespace.mightBeRichText(text):
        return text
    doc = QTextDocument()
    doc.setHtml(text)
    return doc.toPlainText().replace("\u2028", "\n")


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_hostile_names_really_are_rich_text_by_default(qapp, name):
    # Pins the premise: without the fix these names are NOT shown as typed.
    assert QtGuiNamespace.mightBeRichText(name)
    assert _shown(name) != name


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_plain_text_shows_the_raw_string(qapp, name):
    from view.message_boxes import plain_text

    for raw in (name, f"已儲存至：{name}", f"{name}\n第二行", f"  {name}  "):
        assert _shown(plain_text(raw)) == raw


def test_plain_text_leaves_normal_strings_untouched(qapp):
    from view.message_boxes import plain_text

    for raw in (
        "report.pdf",
        "已儲存至：C:\\docs\\a b.pdf",
        "line one\nline <b>two</b>",  # Qt only inspects the first line: plain already
        "1 < 2 and 3 > 2",
        "",
    ):
        assert plain_text(raw) == raw


# --- message boxes -----------------------------------------------------------


def _capture_exec(monkeypatch) -> list[QMessageBox]:
    boxes: list[QMessageBox] = []

    def fake_exec(self, *a, **k):
        boxes.append(self)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return boxes


def _capture_static(monkeypatch, *names: str) -> list[tuple[str, str]]:
    shown: list[tuple[str, str]] = []
    for method in names:
        monkeypatch.setattr(
            QMessageBox,
            method,
            staticmethod(
                lambda _parent, title, text, *a, _m=method, **k: shown.append((_m, text))
                or QMessageBox.StandardButton.Ok
            ),
        )
    return shown


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_show_error_shows_the_raw_message(qapp, monkeypatch, name):
    from view.message_boxes import show_error

    shown = _capture_static(monkeypatch, "critical")
    message = f"無法開啟 {name}: boom"
    show_error(None, message)
    assert [_shown(text) for _m, text in shown] == [message]


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_warning_boxes_show_the_raw_text_and_informative_text(qapp, monkeypatch, name):
    from view import message_boxes

    boxes = _capture_exec(monkeypatch)
    message_boxes.confirm_signature_loss(None, f"檔案 {name} 已簽署", f"{name} 的簽章將失效")
    message_boxes.confirm_place_anyway(None, f"{name} 會蓋到旁邊的文字")
    assert [_shown(b.text()) for b in boxes] == [f"檔案 {name} 已簽署", f"{name} 會蓋到旁邊的文字"]
    assert _shown(boxes[0].informativeText()) == f"{name} 的簽章將失效"


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_degraded_fallback_question_shows_the_raw_text(qapp, monkeypatch, name):
    from view import message_boxes

    shown = _capture_static(monkeypatch, "question")
    message_boxes.confirm_degraded_fallback(None, f"字型 {name} 改用重建文字")
    assert [_shown(text) for _m, text in shown] == [f"字型 {name} 改用重建文字"]


# --- controller sites ---------------------------------------------------------


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_controller_information_boxes_show_the_raw_path(qapp, monkeypatch, name):
    import controller.pdf_controller as controller_module

    shown = _capture_static(monkeypatch, "information")
    fake = SimpleNamespace(
        model=SimpleNamespace(saved_path=name, original_path=None),
        _save_active_document_to=lambda _path, _prefix: True,
        view=None,
    )
    controller_module.PDFController.save(fake)
    lost = [("tab", SimpleNamespace(recovery_path=name))]
    controller_module.PDFController._show_lost_discard_notice(fake, lost)
    assert [_shown(text) for _m, text in shown] == [
        f"已儲存至：{name}",
        f"已放棄此分頁。尚未儲存的編輯仍保留於暫存副本，結束程式後才會刪除：{name}",
    ]


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_controller_close_prompt_shows_the_raw_tab_name(qapp, monkeypatch, name):
    import controller.pdf_controller as controller_module

    boxes = _capture_exec(monkeypatch)
    fake = SimpleNamespace(view=None, _attach_yes_no_shortcuts=lambda *a: None)
    scope = f"分頁「{name}」的文件沒有未儲存的變更。"
    controller_module.PDFController._confirm_discard_refused_input(fake, scope, "reason")
    assert len(boxes) == 1
    assert _shown(boxes[0].informativeText()).startswith(scope)


# --- view sites ---------------------------------------------------------------


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_tab_and_recent_file_tooltips_show_the_raw_path(qapp, name):
    from view.pdf_view import PDFView

    view = PDFView(defer_heavy_panels=True)
    try:
        view.set_document_tabs(
            [{"id": "s1", "display_name": "doc.pdf", "path": f"C:\\x\\{name}", "dirty": False}], 0
        )
        assert _shown(view.document_tab_bar.tabToolTip(0)) == f"C:\\x\\{name}"
        view.set_recent_files(
            [{"path": f"{name}", "display_name": "doc.pdf", "available": True}]
        )
        action = view._recent_files_menu.actions()[0]
        assert _shown(action.toolTip()) == name
    finally:
        view.close()
        qapp.processEvents()


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_lost_session_notice_and_toast_show_the_raw_text(qapp, name):
    from view.pdf_view import PDFView

    view = PDFView(defer_heavy_panels=True)
    try:
        message = f"{name} 的暫存副本：C:\\tmp\\x"
        view.show_lost_session(message, "status")
        label = view._lost_session_proxy.widget()
        assert isinstance(label, QLabel)
        assert _shown(label.text()) == message

        view._show_toast(f"已儲存 {name}")
        # The newest QLabel child of the viewport is the toast.
        toast = view.graphics_view.viewport().findChildren(QLabel)[-1]
        assert _shown(toast.text()) == f"已儲存 {name}"
    finally:
        view.close()
        qapp.processEvents()


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_undo_redo_tooltips_show_the_raw_pdf_text(qapp, name):
    # The undo/redo descriptions embed a preview of the edited PDF text
    # (model/edit_commands.py EditTextCommand.description), so they are
    # attacker-chosen on any OS.
    from view.pdf_view import PDFView

    view = PDFView(defer_heavy_panels=True)
    try:
        undo_tip = f"復原：編輯文字「{name}」（頁面 1）"
        redo_tip = f"重做：新增文字框「{name}」（頁面 2）"
        view.update_undo_redo_tooltips(undo_tip, redo_tip)
        actions = [
            (getattr(view, attr, None), tip)
            for attr, tip in (
                ("_action_undo", undo_tip),
                ("_action_undo_right", undo_tip),
                ("_action_redo", redo_tip),
                ("_action_redo_right", redo_tip),
            )
        ]
        present = [(a, tip) for a, tip in actions if a is not None]
        assert present, "PDFView exposes no undo/redo actions"
        for action, tip in present:
            assert _shown(action.toolTip()) == tip
    finally:
        view.close()
        qapp.processEvents()


# --- guard: no unwrapped interpolation at the known sinks -----------------------

_SINK_FILES = (
    "controller/pdf_controller.py",
    "controller/print_coordinator.py",
    "controller/ocr_coordinator.py",
    "view/pdf_view.py",
    "view/message_boxes.py",
    "src/printing/print_dialog.py",
    "main.py",
)
_STATIC_BOX_METHODS = {"information", "warning", "critical", "question"}
_BOX_TEXT_SETTERS = {"setText", "setInformativeText"}
_BOX_NAMES = {"msg_box", "box"}


def _is_plain_text_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "plain_text"
    )


def _is_constant_text(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.JoinedStr):
        # Literal pieces and ``{len(...)}`` counts cannot carry markup.
        return all(
            isinstance(v, ast.Constant)
            or (
                isinstance(v, ast.FormattedValue)
                and isinstance(v.value, ast.Call)
                and isinstance(v.value.func, ast.Name)
                and v.value.func.id == "len"
            )
            for v in node.values
        )
    return False


def _text_args(call: ast.Call) -> list[ast.AST]:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return []
    # QMessageBox.information(parent, title, text, ...) and friends
    if (
        func.attr in _STATIC_BOX_METHODS
        and isinstance(func.value, ast.Name)
        and func.value.id == "QMessageBox"
        and len(call.args) >= 3
    ):
        return [call.args[2]]
    # msg_box.setText(...) / box.setInformativeText(...)
    if (
        func.attr in _BOX_TEXT_SETTERS
        and isinstance(func.value, ast.Name)
        and func.value.id in _BOX_NAMES
        and call.args
    ):
        return [call.args[0]]
    return []


def test_every_message_box_text_is_constant_or_wrapped():
    offenders: list[str] = []
    for rel in _SINK_FILES:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in _text_args(node):
                if _is_constant_text(arg) or _is_plain_text_call(arg):
                    continue
                offenders.append(f"{rel}:{node.lineno}")
    # message_boxes.py wraps inside its own helpers; those pass plain_text(...) or a
    # parameter that the helper itself wraps, so none may remain unwrapped there either.
    assert offenders == [], f"unwrapped text reaches a QMessageBox: {offenders}"
