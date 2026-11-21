"""A6.5: the view's text sites while a child-routed page's text index is still being built.

The view asks the controller's non-blocking twins; ``TEXT_LOOKUP_PENDING`` is a miss everywhere
except the text-edit press, which is kept as data (``PendingTextClick``) and answered when the
controller says ``text_index_ready``, if nothing newer happened (generation).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtWidgets import QApplication

from model import text_index_jobs
from model.object_requests import TEXT_LOOKUP_PENDING
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view
from test_scripts.test_object_probe import _controller
from test_scripts.test_text_index_gate import (
    PENDING_TEXT,
    FrontStub,
    _answer_for,
    _state,
    _text_pdf,
)
from utils import object_probe_platform
from view import pdf_view

POINT = fitz.Point(80, 70)
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def model(tmp_path):
    m = PDFModel()
    m.open_pdf(_text_pdf(tmp_path / "t.pdf"))
    m.block_manager.clear()  # cold: no page has an index yet
    yield m
    m.close()


@pytest.fixture(autouse=True)
def _child_routed(monkeypatch):
    monkeypatch.setattr(object_probe_platform, "contained_probe_supported", lambda: True)
    monkeypatch.setattr(text_index_jobs, "TEXT_INLINE_LIMIT_BYTES", 0)


def _rig(qapp, model, monkeypatch, mode: str):
    view, controller, _stub, log = _controller(qapp, model, monkeypatch)
    stub = FrontStub()
    controller._object_probe._runner = stub
    # the real pending-click bookkeeping of the view runs (no doubles)
    del view.drop_pending_object_click, view.resolve_pending_object_click
    view.current_mode = mode
    view.total_pages = len(model.doc)
    view._scene_pos_to_page_and_doc_point = lambda scene_pos: (0, fitz.Point(POINT))
    view._event_scene_pos = lambda event: event.position()
    monkeypatch.setattr(pdf_view.QGraphicsView, "mousePressEvent", lambda *a, **k: None)
    opened = []
    view._create_text_editor = lambda *a, **k: opened.append(a)
    return view, controller, stub, log, opened


def _text_job(stub) -> int:
    jobs = [j for j in stub.order if stub.jobs.get(j, (None, None))[1] == "text"]
    assert len(jobs) == 1
    return jobs[0]


def _answer(stub, job: int) -> None:
    stub.complete(job, _answer_for(stub.jobs[job][2]))


def _press(view, button=Qt.LeftButton, pos=(10, 10), release: bool = False):
    """A REAL mouse press (and optionally its release) on the graphics viewport, through the
    application's event path, so the view's event filters see it."""
    from PySide6.QtTest import QTest

    viewport = view.graphics_view.viewport()
    QTest.mousePress(viewport, button, Qt.NoModifier, QPoint(*pos))
    if release:
        QTest.mouseRelease(viewport, button, Qt.NoModifier, QPoint(*pos))


def _capture_menu(monkeypatch):
    shown = []
    monkeypatch.setattr(
        pdf_view.QMenu,
        "exec_",
        lambda self, *a, **k: shown.extend((x.text(), x.isEnabled()) for x in self.actions()),
    )
    return shown


# --------------------------------------------------------------------------- context menu


def test_menu_shows_a_disabled_text_entry_and_no_edit_text(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        shown = _capture_menu(monkeypatch)
        view._show_context_menu(view.graphics_view.rect().center())
        assert ("正在分析此頁文字…", False) in shown
        assert "Edit Text" not in [text for text, _ in shown]
        assert stub.jobs[stub.order[0]][1] == "text"  # the text job queued first
        assert sum(1 for j in stub.order if stub.jobs[j][1] == "text") == 1
        # the menu is not reopened when the answer arrives
        count = len(shown)
        _answer(stub, _text_job(stub))
        assert len(shown) == count
    finally:
        dispose_pdf_view(view, controller, model)


def test_menu_offers_edit_text_once_the_page_is_ready(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        shown = _capture_menu(monkeypatch)
        view._show_context_menu(view.graphics_view.rect().center())
        _answer(stub, _text_job(stub))
        shown.clear()
        view._show_context_menu(view.graphics_view.rect().center())
        assert "Edit Text" in [text for text, _ in shown]
        assert ("正在分析此頁文字…", False) not in shown
    finally:
        dispose_pdf_view(view, controller, model)


def test_menu_resolves_both_hits_with_one_page_input_text_first(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        order = []
        real_text = controller.lookup_text_at_point
        real_obj = controller.lookup_object_at_point
        inputs = []

        def text(page, point, **kw):
            order.append("text")
            inputs.append(kw.get("page_input"))
            return real_text(page, point, **kw)

        def obj(page, point, page_input=None):
            order.append("object")
            inputs.append(page_input)
            return real_obj(page, point, page_input=page_input)

        controller.lookup_text_at_point = text
        controller.lookup_object_at_point = obj
        _capture_menu(monkeypatch)
        view._show_context_menu(view.graphics_view.rect().center())
        assert order == ["text", "object"]
        assert inputs[0] is not None and inputs[0] is inputs[1]
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- text-edit press


def test_a_pending_text_edit_press_opens_the_editor_when_the_index_is_ready(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        pending = view._pending_text_click
        assert pending is not None and (pending.page_num, pending.mode) == (1, "edit_text")
        assert opened == []
        assert log.status[-1] == PENDING_TEXT
        _answer(stub, _text_job(stub))
        assert len(opened) == 1 and "hello" in opened[0][1]
        assert view._pending_text_click is None
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_newer_press_replaces_the_pending_text_click(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        first = view._pending_text_click
        _press(view, pos=(20, 20))
        second = view._pending_text_click
        assert second is not None and second.generation != first.generation
        _answer(stub, _text_job(stub))
        assert len(opened) == 1  # the newer press only
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_stale_generation_is_never_replayed(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        view._text_click_generation += 1  # anything newer happened, the pending object is still held
        _answer(stub, _text_job(stub))
        assert opened == []
        assert view._pending_text_click is None
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("change", ["set_mode", "tab", "finalize", "drop"])
def test_mode_tab_finalize_and_drop_make_a_pending_text_click_stale(qapp, model, monkeypatch, change):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        assert view._pending_text_click is not None
        if change == "set_mode":
            view.set_mode("browse")
        elif change == "tab":
            view._on_document_tab_changed(0)
        elif change == "finalize":
            view._finalize_text_edit()
        else:
            view.drop_pending_text_click(1)
        assert view._pending_text_click is None
        if change != "tab":  # a tab change also cancels the controller's jobs: nothing answers
            _answer(stub, _text_job(stub))
        assert opened == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_dropping_another_pages_click_keeps_the_pending_one(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        view.drop_pending_text_click(2)
        assert view._pending_text_click is not None
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- browse and hover


def test_a_browse_press_on_a_pending_page_is_a_miss_and_never_replays(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        _press(view)
        assert view._pending_text_click is None
        assert view._text_selection_active is False and view._text_selection_rect_item is None
        _answer(stub, _text_job(stub))
        assert view._text_selection_active is False and view._text_selection_rect_item is None
        assert opened == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_browse_hover_on_a_pending_page_keeps_the_default_cursor(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        view._update_browse_hover_cursor(QPointF(10, 10))
        assert view._browse_text_cursor_active is False
        assert view.graphics_view.viewport().cursor().shape() == Qt.ArrowCursor
        _answer(stub, _text_job(stub))
        assert view._browse_text_cursor_active is False  # nothing replays a hover
    finally:
        dispose_pdf_view(view, controller, model)


def test_edit_text_hover_on_a_pending_page_draws_no_highlight(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        view._update_hover_highlight(QPointF(10, 10))
        assert view._hover_highlight_item is None
        _answer(stub, _text_job(stub))
        assert view._hover_highlight_item is None
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- status-only sites


def test_select_all_on_a_pending_page_selects_nothing_and_says_so(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        view.current_page = 0
        assert view._select_all_text_on_current_page() is False
        assert view._selected_text_cached == "" and view._selected_text_rect_doc is None
        assert view._text_selection_rect_item is None
        assert log.status[-1] == PENDING_TEXT
    finally:
        dispose_pdf_view(view, controller, model)


def test_char_context_on_a_pending_page_selects_nothing(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        assert view._ensure_text_selection_manager()._select_numeric_token_at_scene_pos(QPointF(1, 1)) is False
        assert view._selected_text_cached == "" and view._text_selection_rect_item is None
        assert log.status[-1] == PENDING_TEXT
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_doc_rect_lookup_on_a_pending_page_is_a_miss(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        assert view._resolve_text_info_for_doc_rect(0, fitz.Rect(70, 60, 120, 80)) is None
    finally:
        dispose_pdf_view(view, controller, model)


def test_selection_lines_on_a_pending_page_draw_nothing(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        mgr = view._ensure_text_selection_manager()
        mgr._text_selection_active = True
        mgr._text_selection_page_idx = 0
        mgr._text_selection_start_scene_pos = QPointF(0, 0)
        mgr._text_selection_start_span_id = "s"
        mgr._text_selection_rect_item = view.scene.addRect(0, 0, 1, 1)
        mgr._text_selection_rect_item.setVisible(False)
        view._clamp_scene_point_to_page = lambda pos, idx: pos
        view._update_text_selection(QPointF(50, 50), force=True)
        assert mgr._text_selection_live_text == "" and mgr._text_selection_rect_item.isVisible() is False
        assert log.status[-1] == PENDING_TEXT
    finally:
        dispose_pdf_view(view, controller, model)


def test_starting_a_selection_on_a_pending_page_starts_nothing(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        view._clamp_scene_point_to_page = lambda pos, idx: pos
        view._start_text_selection(QPointF(10, 10), 0)
        assert view._text_selection_active is False and view._text_selection_rect_item is None
    finally:
        dispose_pdf_view(view, controller, model)


def test_copy_on_a_pending_page_copies_nothing(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        mgr = view._ensure_text_selection_manager()
        mgr._selected_text_rect_doc = fitz.Rect(70, 60, 120, 80)
        mgr._selected_text_page_idx = 0
        assert view._copy_selected_text_to_clipboard() is False
    finally:
        dispose_pdf_view(view, controller, model)


def test_the_per_hit_menu_resolver_says_pending(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "browse")
    try:
        assert view._resolve_text_info_for_context_menu_pos(view.graphics_view.rect().center()) == "pending"
    finally:
        dispose_pdf_view(view, controller, model)


def test_outline_targets_on_a_pending_page_are_empty_and_build_nothing(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        assert view._iter_outline_targets(0) == []
        assert _state(model) != "clean"
    finally:
        dispose_pdf_view(view, controller, model)


def test_draw_all_block_outlines_skips_a_pending_page(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        model.text_target_mode = "paragraph"  # paragraph mode draws outlines (run mode only prewarms)
        monkeypatch.setattr(view, "visible_page_range", lambda prefetch=0: (0, 0))
        view._draw_all_block_outlines()
        for _ in range(5):  # the page is drawn in its own slot of the prewarm chain
            qapp.processEvents()
        assert view._block_outline_items == {}
        assert _state(model) != "clean"
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- moment of the press (outcomes)


def _replace_run(model, new_text: str) -> None:
    """Page 1 now has ``new_text`` at the clicked coordinates (other bytes, same spot)."""
    page = model.doc[0]
    page.add_redact_annot(fitz.Rect(60, 55, 220, 80))
    page.apply_redactions()
    page.insert_text((72, 72), new_text, fontsize=12)
    model.edit_count = model.edit_count


def test_a_press_of_bytes_a_never_opens_bytes_b_after_a_hover(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        job_a = _text_job(stub)
        answer_a = _answer_for(stub.jobs[job_a][2])
        _replace_run(model, "SECOND run")
        view._update_hover_highlight(QPointF(10, 10))  # a hover on bytes B queues B, takes no ownership
        job_b = stub.order[-1]
        assert job_b != job_a
        stub.complete(job_a, answer_a)
        stub.complete(job_b, _answer_for(stub.jobs[job_b][2]))
        assert _state(model) == "clean" and opened == []
        _press(view)  # a fresh press opens B
        assert len(opened) == 1 and "SECOND" in opened[0][1]
    finally:
        dispose_pdf_view(view, controller, model)


@pytest.mark.parametrize("button", [Qt.MiddleButton, Qt.RightButton])
def test_a_newer_middle_or_right_press_ends_the_held_press(qapp, model, monkeypatch, button):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _capture_menu(monkeypatch)
        _press(view)
        job = _text_job(stub)
        _press(view, button)
        _answer(stub, job)
        assert opened == [] and view._pending_text_click is None
        if button == Qt.MiddleButton:
            view._exit_autopan()
    finally:
        dispose_pdf_view(view, controller, model)


def test_navigating_the_single_page_view_ends_the_held_press(qapp, model, monkeypatch):
    from PySide6.QtGui import QPixmap

    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        view.continuous_pages = False
        _press(view)
        job = _text_job(stub)
        view.display_page(2, QPixmap(50, 50))
        _answer(stub, job)
        assert opened == []
    finally:
        dispose_pdf_view(view, controller, model)


def _ctrl_wheel(view) -> None:
    from PySide6.QtGui import QWheelEvent

    event = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(view.graphics_view.viewport(), event)


def test_ctrl_wheel_zoom_through_the_debounce_keeps_the_held_press(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        view.continuous_pages = True
        view.initialize_continuous_placeholders([(595.0, 842.0), (595.0, 842.0)], 1.0)
        _press(view)
        job = _text_job(stub)
        _ctrl_wheel(view)  # the real wheel handler; it only starts the debounce
        assert view._pending_text_click is not None
        view._zoom_debounce_timer.stop()
        view._on_zoom_debounce()  # the debounce fires: controller._on_request_rerender rebuilds the scene
        view.graphics_view.verticalScrollBar().setValue(40)  # scroll
        _answer(stub, job)
        assert len(opened) == 1 and "hello" in opened[0][1]
        assert view._editing_page_idx == 0
    finally:
        dispose_pdf_view(view, controller, model)


def test_ready_during_an_active_editor_leaves_it_alone(qapp, model, monkeypatch):
    from types import SimpleNamespace

    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    editor = SimpleNamespace(marker="mine")
    try:
        _press(view)
        job = _text_job(stub)
        view.text_editor = editor  # an editor became active without a press (e.g. a ribbon action)
        view._editing_page_idx = 7
        _answer(stub, job)
        assert opened == [] and view.text_editor is editor and view._editing_page_idx == 7
    finally:
        view.text_editor = None
        dispose_pdf_view(view, controller, model)


def test_hover_requests_still_dedup_and_never_replay(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        view._update_hover_highlight(QPointF(10, 10))
        view._update_hover_highlight(QPointF(10, 10))
        assert len(stub.order) == 1
        assert not controller._replay_owners
        _answer(stub, _text_job(stub))
        assert opened == [] and view._pending_text_click is None
    finally:
        dispose_pdf_view(view, controller, model)


def test_the_text_status_resumes_when_an_object_status_ends(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        assert log.status[-1] == PENDING_TEXT
        controller._set_object_status("object busy")
        assert log.status[-1] == "object busy"
        controller._set_object_status(None)
        assert log.status[-1] == PENDING_TEXT and controller._text_status_message == PENDING_TEXT
        _answer(stub, _text_job(stub))
        assert log.status[-1] is None
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_thumbnail_click_on_another_page_ends_the_held_press(qapp, model, monkeypatch):
    from PySide6.QtTest import QTest

    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        view.continuous_pages = True
        view.initialize_continuous_placeholders([(595.0, 842.0), (595.0, 842.0)], 1.0)
        _press(view)
        job = _text_job(stub)
        QTest.mouseClick(view.thumbnail_list.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        _answer(stub, job)
        assert opened == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_thumbnail_right_click_menu_ends_the_held_press(qapp, model, monkeypatch):
    from PySide6.QtTest import QTest

    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _capture_menu(monkeypatch)
        _press(view)
        job = _text_job(stub)
        QTest.mouseClick(view.thumbnail_list.viewport(), Qt.RightButton, Qt.NoModifier, QPoint(5, 5))
        _answer(stub, job)
        assert opened == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_keyboard_navigation_ends_the_held_press(qapp, model, monkeypatch):
    from PySide6.QtTest import QTest

    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        job = _text_job(stub)
        QTest.keyClick(view.graphics_view.viewport(), Qt.Key_PageDown)
        _answer(stub, job)
        assert opened == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_save_as_rebind_with_identical_bytes_never_replays(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        job = _text_job(stub)
        answer = _answer_for(stub.jobs[job][2])
        model._restore_doc_from_snapshot(model.doc.tobytes())  # a new handle, the same page bytes
        stub.complete(job, answer)
        assert opened == []
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_ready_of_another_job_pops_nothing_of_the_page_gesture(qapp, model, monkeypatch):
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _press(view)
        pending = view._pending_text_click
        controller._text_clicks[1] = ("job B",)  # the page's gesture now waits on B
        controller._object_probe.text_index_ready.emit(1)  # ready(A): not B's event
        assert controller._text_clicks[1] == ("job B",)
        assert view._pending_text_click is pending and opened == []
        assert controller._text_status_message == PENDING_TEXT
    finally:
        dispose_pdf_view(view, controller, model)


def _send_events(view, name: str) -> None:
    """Send one synthetic input event of the named kind to the view's window."""
    from PySide6.QtCore import QEvent, QTimerEvent
    from PySide6.QtGui import (
        QContextMenuEvent,
        QFocusEvent,
        QKeyEvent,
        QKeySequence,
        QMouseEvent,
        QPaintEvent,
        QRegion,
        QShortcutEvent,
        QWheelEvent,
    )
    from PySide6.QtTest import QTest

    viewport = view.graphics_view.viewport()
    thumbs = view.thumbnail_list.viewport()
    pos = QPointF(10, 10)
    send = QApplication.sendEvent
    if name == "press_other_widget":
        QTest.mousePress(thumbs, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
    elif name == "double_click":
        send(viewport, QMouseEvent(QEvent.MouseButtonDblClick, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    elif name == "key_press":
        send(viewport, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a"))
    elif name == "context_menu":
        send(viewport, QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10)))
    elif name == "wheel_without_ctrl":
        send(viewport, QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    elif name == "focus_in_other":
        send(view.thumbnail_list, QFocusEvent(QEvent.FocusIn))
    elif name == "focus_out_other":
        send(view.thumbnail_list, QFocusEvent(QEvent.FocusOut))
    elif name == "shortcut":
        send(view.thumbnail_list, QShortcutEvent(QKeySequence("Ctrl+F"), 1))
    elif name == "shortcut_override":
        send(view.thumbnail_list, QKeyEvent(QEvent.ShortcutOverride, Qt.Key_F, Qt.ControlModifier, "f"))
    elif name == "hover_move":
        send(viewport, QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    elif name == "release_of_the_press":
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
    elif name == "paint":
        send(viewport, QPaintEvent(QRegion(0, 0, 5, 5)))
    elif name == "timer":
        send(viewport, QTimerEvent(987654))
    elif name == "ctrl_wheel":
        _ctrl_wheel(view)
    else:  # pragma: no cover
        raise AssertionError(name)


_BUMPING = [
    "press_other_widget", "double_click", "key_press", "context_menu", "wheel_without_ctrl",
    "focus_in_other", "focus_out_other", "shortcut", "shortcut_override",
]
_NOT_BUMPING = ["hover_move", "release_of_the_press", "paint", "timer", "ctrl_wheel"]


@pytest.mark.parametrize("name", _BUMPING + _NOT_BUMPING)
def test_every_input_event_but_the_listed_ones_ends_the_held_press(qapp, model, monkeypatch, name):
    """The one generic outcome check of the epoch chokepoint: after a pending press, an event of any
    input kind makes the replay count 0, except hover move, the release of the same press, paint,
    timers and Ctrl+wheel, where it stays exactly 1."""
    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        _capture_menu(monkeypatch)
        _press(view)
        job = _text_job(stub)
        _send_events(view, name)
        _answer(stub, job)
        assert len(opened) == (0 if name in _BUMPING else 1), name
    finally:
        dispose_pdf_view(view, controller, model)


# --------------------------------------------------------------------------- guard

_BLOCKING = (
    "get_text_info_at_point",
    "get_char_context_at_point",
    "get_text_selection_lines",
    "get_text_in_rect",
    "iter_text_targets",
    "ensure_page_index_built",
)
_TWINS = (
    "lookup_text_at_point",
    "lookup_char_context_at_point",
    "lookup_text_selection_lines",
    "lookup_text_in_rect",
    "lookup_text_targets",
)

# (file, enclosing function, twin) -> the test of this file that covers the site's pending behaviour
_PDF = "view/pdf_view.py"
_SEL = "view/text_selection.py"
_TWIN_SITES: dict[tuple[str, str, str], str] = {
    (_PDF, "_iter_outline_targets", "lookup_text_targets"): "test_outline_targets_on_a_pending_page_are_empty_and_build_nothing",
    (_PDF, "_draw_page_outlines", "lookup_text_targets"): "test_draw_all_block_outlines_skips_a_pending_page",
    # one browse (a miss) and one text-edit (kept as data) site
    (_PDF, "_mouse_press", "lookup_text_at_point"): "test_a_browse_press_on_a_pending_page_is_a_miss_and_never_replays",
    (_PDF, "_update_browse_hover_cursor", "lookup_text_at_point"): "test_browse_hover_on_a_pending_page_keeps_the_default_cursor",
    (_PDF, "resolve_pending_text_click", "lookup_text_at_point"): "test_a_pending_text_edit_press_opens_the_editor_when_the_index_is_ready",
    (_PDF, "_update_hover_highlight", "lookup_text_at_point"): "test_edit_text_hover_on_a_pending_page_draws_no_highlight",
    # the numeric-token site: the context lookup answers pending first (the second lookup follows
    # a real context answer on the same ready page, so it cannot be pending)
    (_SEL, "_select_numeric_token_at_scene_pos", "lookup_char_context_at_point"): "test_char_context_on_a_pending_page_selects_nothing",
    (_SEL, "_select_numeric_token_at_scene_pos", "lookup_text_at_point"): "test_char_context_on_a_pending_page_selects_nothing",
    (_SEL, "_start_text_selection", "lookup_text_at_point"): "test_starting_a_selection_on_a_pending_page_starts_nothing",
    (_SEL, "_update_text_selection", "lookup_text_selection_lines"): "test_selection_lines_on_a_pending_page_draw_nothing",
    (_SEL, "_resolve_text_info_for_doc_rect", "lookup_text_at_point"): "test_a_doc_rect_lookup_on_a_pending_page_is_a_miss",
    (_SEL, "_resolve_text_info_for_context_menu_pos", "lookup_text_at_point"): "test_the_per_hit_menu_resolver_says_pending",
    (_SEL, "_select_all_text_on_current_page", "lookup_text_in_rect"): "test_select_all_on_a_pending_page_selects_nothing_and_says_so",
    (_SEL, "_copy_selected_text_to_clipboard", "lookup_text_in_rect"): "test_copy_on_a_pending_page_copies_nothing",
}

# No blocking call is left in the view (the prewarm pass uses request_page_index, A6.6).
_BLOCKING_ALLOWED: dict[tuple[str, str, str], str] = {}


def _call_sites(names: tuple[str, ...]) -> dict[tuple[str, str, str], int]:
    """(file, enclosing function, name) -> number of ``<obj>.<name>(`` calls under view/."""
    found: dict[tuple[str, str, str], int] = {}

    def visit(node: ast.AST, rel: str, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in names:
                key = (rel, inner, child.func.attr)
                found[key] = found.get(key, 0) + 1
            visit(child, rel, inner)

    for path in sorted((REPO_ROOT / "view").rglob("*.py")):
        visit(ast.parse(path.read_text(encoding="utf-8-sig")), path.relative_to(REPO_ROOT).as_posix(), "")
    return found


def test_no_view_site_calls_a_blocking_text_entry():
    assert set(_call_sites(_BLOCKING)) == set(_BLOCKING_ALLOWED)
    # a bare-name or reference use is a call site the AST walk above could miss: scan the text too
    for path in sorted((REPO_ROOT / "view").rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        for name in _BLOCKING:
            rel = path.relative_to(REPO_ROOT).as_posix()
            assert not re.search(rf"\b{name}\(", source), f"{rel}: {name}("


_TWIN_CALL_COUNTS = {(_PDF, "_mouse_press", "lookup_text_at_point"): 2}  # browse press, text-edit press


def test_every_twin_site_is_allowlisted_with_its_pending_test():
    found = _call_sites(_TWINS)
    assert set(found) == set(_TWIN_SITES)
    assert found == {key: _TWIN_CALL_COUNTS.get(key, 1) for key in _TWIN_SITES}
    own = Path(__file__).read_text(encoding="utf-8")
    for test in set(_TWIN_SITES.values()):
        assert f"def {test}(" in own, test


def test_the_pending_sentinel_is_the_model_singleton():
    assert TEXT_LOOKUP_PENDING is not None


def test_a_bare_ctrl_press_before_the_zoom_wheel_keeps_the_held_press(qapp, model, monkeypatch):
    from PySide6.QtTest import QTest

    view, controller, stub, log, opened = _rig(qapp, model, monkeypatch, "edit_text")
    try:
        view.continuous_pages = True
        view.initialize_continuous_placeholders([(595.0, 842.0), (595.0, 842.0)], 1.0)
        _press(view)
        job = _text_job(stub)
        QTest.keyPress(view.graphics_view.viewport(), Qt.Key_Control)  # Ctrl goes down before the wheel
        assert view._pending_text_click is not None
        _ctrl_wheel(view)
        view._zoom_debounce_timer.stop()
        view._on_zoom_debounce()
        _answer(stub, job)
        assert len(opened) == 1
        # a real key (not a modifier) still ends the held press
    finally:
        dispose_pdf_view(view, controller, model)
