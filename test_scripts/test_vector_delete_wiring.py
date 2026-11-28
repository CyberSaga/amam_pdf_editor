"""Card B7, last step: the View/Controller wiring of the internal vector delete (Del key and the right-click
entry).  A real window (main.run).  The feature stays behind PDF_EDITOR_VECTOR_EDIT until the activation list is
done (WatermarkTool.on_session_open and the pdf_object_ops free functions still take no lease).  Red first."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import fitz
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main  # noqa: E402
from controller.vector_edit_coordinator import VectorEditCoordinator  # noqa: E402

BODY = b"0 0 0 RG 1 w 20 370 m 120 370 l S 1 0 0 rg 150 160 40 40 re f"
RECT_VISUAL = fitz.Rect(150, 200, 190, 240)  # the filled square, visual (top-left origin) page coordinates
LINE_VISUAL = fitz.Point(70, 30)


def _make_pdf(path: Path) -> str:
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((5, 5), " ")
    doc.update_stream(page.get_contents()[0], BODY)
    doc.save(path)
    doc.close()
    return str(path)


def _pump(qapp, rounds: int = 40) -> None:
    for _ in range(rounds):
        qapp.processEvents()
        QTest.qWait(5)


def _wait(qapp, predicate, ms: int = 6000) -> bool:
    waited = 0
    while waited < ms:
        qapp.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
        waited += 10
    return predicate()


def _start(qapp, monkeypatch, tmp_path, enabled: bool = True):
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    if enabled:
        monkeypatch.setenv("PDF_EDITOR_VECTOR_EDIT", "1")
    else:
        monkeypatch.delenv("PDF_EDITOR_VECTOR_EDIT", raising=False)
    startup = main.run(argv=[_make_pdf(tmp_path / "a.pdf")], start_event_loop=False)
    controller, view, model = startup["controller"], startup["view"], startup["model"]
    view.show()
    _pump(qapp)
    controller._vector_edit_coordinator = VectorEditCoordinator(controller, in_process=True)  # no child process in a test
    return controller, view, model


def _click_visual(qapp, view, point: fitz.Point) -> None:
    scene = view._doc_rect_to_scene_rect(0, fitz.Rect(point.x, point.y, point.x + 1, point.y + 1)).center()
    pos = view.graphics_view.mapFromScene(QPointF(scene))
    QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
    qapp.processEvents()


def _selected_token(view):
    return view._ensure_vector_selection_manager().token


def _stream(model) -> bytes:
    return b"".join(model.doc.xref_stream(x) for x in model.doc[0].get_contents())


def _press_delete(view) -> QKeyEvent:
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
    view.keyPressEvent(event)
    return event


def _close(view, model, qapp) -> None:
    model.command_manager.mark_saved()
    model.edit_count = 0
    model.secure_save_required = False
    view.close()
    _pump(qapp, 10)
    qapp.setStyleSheet("")


def test_the_vector_mode_does_not_exist_while_the_flag_is_off(qapp, monkeypatch, tmp_path):
    controller, view, model = _start(qapp, monkeypatch, tmp_path, enabled=False)
    try:
        view.set_mode("vector")
        assert view.current_mode == "browse"
        assert "vector" not in view._mode_actions
        before = _stream(model)
        controller._on_vector_delete(1)  # a stray signal: refused before it reads or writes anything
        assert _stream(model) == before and model.command_manager.undo_count == 0
    finally:
        _close(view, model, qapp)


def test_click_selects_the_path_and_del_deletes_it_through_one_transaction_with_undo_and_redo(qapp, monkeypatch, tmp_path):
    controller, view, model = _start(qapp, monkeypatch, tmp_path)
    leases: list = []
    real_commit = model.commit_vector_plan

    def spy(plan, token, *, on_yield=None, lease=None):
        leases.append((lease, lease is not None and model.write_gate.holds(lease)))
        return real_commit(plan, token, on_yield=on_yield, lease=lease)

    monkeypatch.setattr(model, "commit_vector_plan", spy)
    try:
        view.set_mode("vector")
        assert view.current_mode == "vector"
        _click_visual(qapp, view, fitz.Point(170, 220))
        assert _wait(qapp, lambda: _selected_token(view) is not None)
        event = _press_delete(view)
        assert event.isAccepted()
        assert _wait(qapp, lambda: b"150 160 40 40 re f" not in _stream(model))
        assert b"20 370 m 120 370 l S" in _stream(model)  # the other path survives
        assert leases and leases[0][0] is not None and leases[0][1] is True  # the controller's own transaction lease
        assert model.command_manager.undo_count == 1
        controller.undo()
        _pump(qapp, 10)
        assert b"150 160 40 40 re f" in _stream(model)
        controller.redo()
        _pump(qapp, 10)
        assert b"150 160 40 40 re f" not in _stream(model) and b"20 370 m 120 370 l S" in _stream(model)
    finally:
        _close(view, model, qapp)


def test_the_context_menu_entry_deletes_the_selection_it_was_opened_on(qapp, monkeypatch, tmp_path):
    controller, view, model = _start(qapp, monkeypatch, tmp_path)
    try:
        view.set_mode("vector")
        _click_visual(qapp, view, fitz.Point(170, 220))
        assert _wait(qapp, lambda: _selected_token(view) is not None)
        menu = view._ensure_vector_selection_manager().build_menu()
        labels = [a.text() for a in menu.actions() if a.text()]
        assert "刪除" in labels
        next(a for a in menu.actions() if a.text() == "刪除").trigger()
        assert _wait(qapp, lambda: b"150 160 40 40 re f" not in _stream(model))
        assert model.command_manager.undo_count == 1
    finally:
        _close(view, model, qapp)


def test_a_menu_opened_on_an_older_selection_is_refused_and_keeps_the_newer_one(qapp, monkeypatch, tmp_path):
    controller, view, model = _start(qapp, monkeypatch, tmp_path)
    try:
        view.set_mode("vector")
        _click_visual(qapp, view, fitz.Point(170, 220))
        assert _wait(qapp, lambda: _selected_token(view) is not None)
        old_menu = view._ensure_vector_selection_manager().build_menu()
        first = _selected_token(view)
        _click_visual(qapp, view, LINE_VISUAL)  # a newer selection (the line)
        assert _wait(qapp, lambda: _selected_token(view) not in (None, first))
        newer = _selected_token(view)
        before = _stream(model)
        next(a for a in old_menu.actions() if a.text() == "刪除").trigger()
        _pump(qapp, 20)
        assert _stream(model) == before and model.command_manager.undo_count == 0  # nothing written
        assert _selected_token(view) == newer  # and the newer selection is still the displayed one
    finally:
        _close(view, model, qapp)


def test_del_while_the_gate_is_held_is_consumed_and_writes_nothing(qapp, monkeypatch, tmp_path):
    controller, view, model = _start(qapp, monkeypatch, tmp_path)
    try:
        view.set_mode("vector")
        _click_visual(qapp, view, fitz.Point(170, 220))
        assert _wait(qapp, lambda: _selected_token(view) is not None)
        before = _stream(model)
        lease = model.write_gate.begin("vector_delete", model.get_active_session_id())
        try:
            event = _press_delete(view)
            _pump(qapp, 10)
        finally:
            lease.release()
        assert event.isAccepted()  # it must not fall through to the object delete
        assert _stream(model) == before and model.command_manager.undo_count == 0
    finally:
        _close(view, model, qapp)


def test_del_with_no_vector_selection_is_not_consumed_by_the_vector_mode(qapp, monkeypatch, tmp_path):
    controller, view, model = _start(qapp, monkeypatch, tmp_path)
    try:
        view.set_mode("vector")
        assert _selected_token(view) is None
        assert view._ensure_vector_selection_manager().delete_pressed() is False
    finally:
        _close(view, model, qapp)


def test_the_controller_never_commits_a_vector_plan_without_a_lease():
    """Owner 11-27 (option A): commit_vector_plan without a lease stays a low-level model API, and the controller
    layer may only call it with lease=."""
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "controller").glob("*.py")) + [REPO_ROOT / "main.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "commit_vector_plan":
                if not any(k.arg == "lease" for k in node.keywords):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "commit_vector_plan"
        for n in ast.walk(ast.parse((REPO_ROOT / "controller" / "pdf_controller.py").read_text(encoding="utf-8")))
    ), "the controller has no vector delete flow"
