"""Card B7 step 1, controller half: a view slot that arrives while the write gate is held is refused before it
reads or changes anything, with a sentence; read-only slots still run; a WriteGateBusy raised inside a slot is
caught, not leaked into Qt.  Red first."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.write_gate import WriteGateBusy  # noqa: E402


def _controller() -> PDFController:
    ctl = PDFController.__new__(PDFController)
    ctl.model = PDFModel()
    ctl.view = MagicMock()
    ctl._is_lost = lambda session_id=None: False  # type: ignore[method-assign]
    return ctl


def test_a_write_slot_is_refused_while_the_gate_is_held_and_a_read_slot_runs(qapp):
    ctl = _controller()
    calls: list[str] = []

    def delete_pages(pages):
        calls.append("delete_pages")

    def jump_to_result(query):
        calls.append("jump_to_result")

    write, read = ctl._live_only(delete_pages), ctl._live_only(jump_to_result)
    write([1])
    read("x")
    assert calls == ["delete_pages", "jump_to_result"]  # free: both run
    calls.clear()
    with ctl.model.write_gate.begin("vector_delete", None):
        write([1])
        read("x")
    assert calls == ["jump_to_result"]
    assert ctl.view.set_status_bar_override_message.called


def test_the_lost_session_pass_through_slots_are_guarded_too(qapp):
    ctl = _controller()
    calls: list[str] = []

    def save():
        calls.append("save")

    with ctl.model.write_gate.begin("vector_delete", None):
        ctl._live_only(save)()
    assert calls == []


def test_a_busy_error_raised_inside_a_slot_is_caught(qapp):
    ctl = _controller()

    def edit_text(*_a):
        raise WriteGateBusy("document is busy: save")

    assert ctl._live_only(edit_text)(1, 2) is None
    assert ctl.view.set_status_bar_override_message.called


# ---- G1: entries that change the active session or end the window are admitted only when the gate is free ----
def test_a_window_close_is_ignored_before_any_cleanup_while_the_gate_is_held(qapp):
    ctl = _controller()
    ctl._page_render_coordinator = MagicMock()
    ctl._thumbnail_coordinator = MagicMock()
    event = MagicMock()
    with ctl.model.write_gate.begin("vector_delete", None):
        ctl.handle_app_close(event)
    event.ignore.assert_called_once()
    event.accept.assert_not_called()
    ctl._page_render_coordinator.cancel.assert_not_called()  # nothing was cancelled or retired before the refusal
    ctl._thumbnail_coordinator.cancel.assert_not_called()
    assert ctl.view.set_status_bar_override_message.called


def test_a_session_switch_is_refused_without_side_effects_while_the_gate_is_held(qapp, monkeypatch):
    ctl = _controller()
    ctl._finalize_inline_editor_before_session_change = MagicMock()  # type: ignore[method-assign]
    ctl._refresh_document_tabs = MagicMock()  # type: ignore[method-assign]
    switched: list[str] = []
    monkeypatch.setattr(ctl.model, "activate_session", lambda sid: switched.append(sid))
    monkeypatch.setattr(ctl.model, "get_active_session_id", lambda: "A")
    with ctl.model.write_gate.begin("vector_delete", "A"):
        ctl._switch_to_session_id("B")
    assert switched == [] and not ctl._finalize_inline_editor_before_session_change.called


def test_a_forwarded_cli_open_waits_for_the_gate_and_then_runs_once(qapp):
    from PySide6.QtCore import QTimer

    ctl = _controller()
    opened: list[str] = []
    ctl.activate = MagicMock()  # type: ignore[method-assign]
    ctl.open_pdf = lambda path: opened.append(path)  # type: ignore[method-assign]
    ctl._deferred_session_activation_draining = False
    ctl._deferred_session_activation_retry_armed = False
    ctl.view.isMinimized.return_value = False
    lease = ctl.model.write_gate.begin("vector_delete", None)
    ctl.handle_forwarded_cli(["b.pdf"])
    for _ in range(5):
        qapp.processEvents()
    assert opened == []  # the transaction is in flight: no session change inside it
    lease.release()
    loop_done = []
    QTimer.singleShot(1500, lambda: loop_done.append(1))
    while not opened and not loop_done:
        qapp.processEvents()
    assert opened == ["b.pdf"]


def test_adopting_a_transferred_session_is_refused_before_any_teardown_while_the_gate_is_held(qapp):
    ctl = _controller()
    ctl._finalize_inline_editor_before_session_change = MagicMock()  # type: ignore[method-assign]
    ctl._thumbnail_coordinator = MagicMock()
    payload = MagicMock()
    payload.source_path = ""
    with ctl.model.write_gate.begin("vector_delete", None):
        assert ctl.adopt_transferred_session(payload) is False
    assert not ctl._finalize_inline_editor_before_session_change.called
    ctl._thumbnail_coordinator.cancel.assert_not_called()

def test_deferred_activations_keep_arrival_order_and_the_queue_head_while_the_gate_is_held(qapp):
    """F: while a transaction is in flight the drain keeps the head of the FIFO (nothing is popped), arms one
    retry, and a later arrival cannot overtake an earlier one once the gate is free."""
    from PySide6.QtCore import QTimer

    ctl = _controller()
    ctl._deferred_session_activation_draining = False
    ctl._deferred_session_activation_retry_armed = False
    ran: list[str] = []
    lease = ctl.model.write_gate.begin("vector_delete", None)
    ctl._run_when_session_activation_allowed(lambda: ran.append("first"))
    ctl._run_when_session_activation_allowed(lambda: ran.append("second"))
    for _ in range(5):
        qapp.processEvents()
    assert ran == []  # nothing ran inside the transaction
    assert len(ctl._deferred_session_activation_queue()) == 2  # the head was kept, not popped and re-timed
    assert ctl._deferred_session_activation_retry_armed is True  # one shared retry
    ctl._run_when_session_activation_allowed(lambda: ran.append("third"))
    lease.release()
    done: list[int] = []
    QTimer.singleShot(2000, lambda: done.append(1))
    while len(ran) < 3 and not done:
        qapp.processEvents()
    assert ran == ["first", "second", "third"]
