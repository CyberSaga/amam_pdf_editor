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
