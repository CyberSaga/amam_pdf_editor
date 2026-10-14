from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import fitz
import pytest

from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication

import view.pdf_view as pdf_view
from model.edit_commands import CommandManager, EditCommand
from model.pdf_model import PDFModel
from model.text_commit.dto import TextCommitSettings


def _accept_rebuild(_chain: tuple[str, ...]) -> bool:
    """UI step 7 (no silent legacy): explicit rebuild consent stub.  The
    tests that use it exercise the rebuild (legacy redact+reinsert) path, which
    a tiered refusal now reaches only with ``allow_rebuild=True`` plus an
    accepting confirm -- the same path they ran before, now consented."""
    return True


class _NamedCommand(EditCommand):
    def __init__(self, name: str) -> None:
        self.name = name
        self.executed = 0
        self.undone = 0

    @property
    def description(self) -> str:
        return self.name

    def execute(self) -> None:
        self.executed += 1

    def undo(self) -> None:
        self.undone += 1


class _UndoBoomCommand(_NamedCommand):
    def undo(self) -> None:
        raise RuntimeError("undo boom")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Rollback target", fontsize=12, fontname="helv")
    doc.save(path, garbage=0)
    doc.close()


def _find_block(model: PDFModel, page_idx: int, probe: str):
    model.ensure_page_index_built(page_idx + 1)
    for block in model.block_manager.get_blocks(page_idx):
        if probe in (block.text or ""):
            return block
    return None


def test_inline_text_editor_emits_focus_out_signal_without_monkeypatch(qapp: QApplication) -> None:
    editor_cls = getattr(pdf_view, "InlineTextEditor", None)
    assert editor_cls is not None

    editor = editor_cls("hello")
    observed: list[str] = []
    editor.focus_out_requested.connect(lambda: observed.append("focus-out"))
    original_handler = editor.focusOutEvent

    editor.focusOutEvent(QFocusEvent(QFocusEvent.FocusOut))

    assert observed == ["focus-out"]
    assert editor.focusOutEvent == original_handler


def test_command_manager_undo_keeps_command_on_failure() -> None:
    manager = CommandManager()
    cmd = _UndoBoomCommand("boom")
    manager.record(cmd)

    with pytest.raises(RuntimeError, match="undo boom"):
        manager.undo()

    assert manager.undo_count == 1
    assert manager.redo_count == 0
    assert manager._undo_stack[-1] is cmd


def test_command_manager_evicts_oldest_entries_at_max_limit() -> None:
    manager = CommandManager()

    for i in range(105):
        manager.record(_NamedCommand(f"cmd-{i}"))

    assert manager.undo_count == 100
    assert manager._undo_stack[0].description == "cmd-5"
    assert manager._undo_stack[-1].description == "cmd-104"


def test_edit_text_reports_rollback_failures(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rollback.pdf"
        _make_pdf(path)

        # Subject: the consented legacy rebuild's rollback reporting, reached
        # only after a tiered refusal; critique step 12 made Tier 1 (which
        # commits this edit itself) the default, so pin Tier 0.
        model = PDFModel(text_commit_settings=TextCommitSettings(max_tier=0))
        try:
            model.open_pdf(str(path))
            target = _find_block(model, 0, "Rollback target")
            assert target is not None

            monkeypatch.setattr(model, "_convert_text_to_html", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("primary failure")))
            monkeypatch.setattr(model, "_restore_page_from_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("rollback failure")))

            with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="rollback failure"):
                model.edit_text(
                    page_num=1,
                    rect=fitz.Rect(target.layout_rect),
                    new_text="Edited text",
                    font=target.font,
                    size=max(8, int(round(target.size))),
                    color=target.color,
                    original_text=target.text,
                    allow_rebuild=True,
                    confirm_fallback=_accept_rebuild,
                )

            assert "rollback failure" in caplog.text.lower()
            assert "primary failure" in caplog.text.lower()
        finally:
            model.close()


# The two ``_restore_page_from_snapshot`` graft-order tests (insert_pdf before
# delete_page, with fake docs) are retired: the restore is now an in-place write
# by xref with no insert_pdf/delete_page at all.  Its atomicity and type
# contracts are pinned in test_page_snapshot_identity.py
# (test_restore_rejects_plain_bytes, test_failed_write_mid_restore_puts_the_page_back,
# test_stale_gate_raises_before_any_write).
