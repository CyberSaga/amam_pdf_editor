"""Part 5 stage B: the ``pending_page_maintenance`` dead end is retired.

A page that carries pending legacy cleanup (add_textbox, a consented
rebuild, an object move) used to refuse every Tier 0/1 true-text edit with
``pending_page_maintenance`` until a save (or the every-5-edits GC) cleaned
it.  The fidelity-protection skip in ``apply_pending_redactions`` makes that
gate redundant: a page the true-text engine commits to is protected and is
never passed through ``clean_contents`` afterwards.  The command that owns
the add also owns its bookkeeping, so undo/redo restores pending entries and
protection membership.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import AddTextboxCommand, EditTextCommand, EditTextResult  # noqa: E402
from model.page_snapshot import PageSnapshotStale  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit import plan  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, TextCommitSettings  # noqa: E402
from test_scripts.test_text_commit_finalize_by_result import (  # noqa: E402
    _EDIT_B,
    _App,
    _author,
)
from test_scripts.type0_fixture_builder import encode_cids  # noqa: E402
from test_text_commit_maintenance import (  # noqa: E402
    REPLACEMENT,
    TARGET,
    _REBUILD_CONSENT,
    _edit,
    _open,
    _spy_clean_contents,
    _write_tier0_pdf,
)
from view.text_edit_reasons import rebuild_offered_for, rejection_reason_text  # noqa: E402

NEW_BOX_RECT = fitz.Rect(300, 300, 420, 340)


def _block(model: PDFModel, probe: str):
    return next(b for b in model.block_manager.get_blocks(0) if probe in (b.text or ""))


def _moved_rect(model: PDFModel, probe: str) -> fitz.Rect:
    """The block's layout rect dragged 120 pt down (a grip move)."""
    return fitz.Rect(_block(model, probe).layout_rect) + (0, 120, 0, 120)


def _add_box(model: PDFModel) -> AddTextboxCommand:
    snapshot = model._capture_page_snapshot_strict(0)
    command = AddTextboxCommand(
        model=model,
        page_num=1,
        visual_rect=NEW_BOX_RECT,
        text="NEW BOX",
        font="helv",
        size=12,
        color=(0.0, 0.0, 0.0),
        before_page_snapshot_bytes=snapshot,
    )
    model.command_manager.execute(command)
    return command


def _edit_cmd(
    model: PDFModel,
    probe: str,
    new_text: str,
    *,
    new_rect: fitz.Rect | None = None,
    rebuild: bool = False,
) -> EditTextCommand:
    """The edit exactly as the controller wraps it: one undoable command."""
    block = _block(model, probe)
    command = EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font=block.font,
        size=block.size,
        color=block.color,
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(0),
        old_block_id=None,
        old_block_text=block.text,
        new_rect=new_rect,
        allow_rebuild=rebuild,
        confirm_fallback=(lambda _chain: True) if rebuild else None,
    )
    model.command_manager.execute(command)
    return command


def _grip_move_rebuild(model: PDFModel, probe: str = "Downstream") -> EditTextCommand:
    """A grip-moved line applied with the user's "rebuild text" consent."""
    command = _edit_cmd(
        model, probe, "Downstream line stays", new_rect=_moved_rect(model, probe), rebuild=True
    )
    assert command.result is EditTextResult.SUCCESS
    return command


def _tiered(tmp_path: Path, max_tier: int = 1) -> PDFModel:
    pdf_path = tmp_path / "tier0.pdf"
    _write_tier0_pdf(pdf_path)
    return _open(pdf_path, TextCommitSettings(engine="tiered", max_tier=max_tier))


def _pending_pages(model: PDFModel) -> list[int]:
    return [e["page_idx"] for e in model.pending_edits]


def _assert_true_text_commit(model: PDFModel, result: EditTextResult) -> None:
    assert result is EditTextResult.SUCCESS
    outcome = model.last_commit_outcome
    assert outcome is not None
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH, outcome
    assert outcome.fallback_chain == (), outcome
    assert 0 in model.fidelity_protected_pages


def test_true_text_edit_after_add_textbox_on_the_same_page_commits(tmp_path):
    model = _tiered(tmp_path)
    try:
        _add_box(model)
        assert _pending_pages(model) == [0]
        # No rebuild consent: a refusal here would be fail-closed, not legacy.
        _assert_true_text_commit(model, _edit(model, TARGET, REPLACEMENT))
        assert "NEW BOX" in model.doc[0].get_text()
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_true_text_edit_after_a_consented_rebuild_on_the_same_page_commits(tmp_path):
    model = _tiered(tmp_path, max_tier=0)
    try:
        # An advance-mismatching replacement is refused by Tier 0 and, with
        # the user's consent, rebuilt by the legacy engine (queues cleanup).
        assert _edit(model, TARGET, "Price 2W24", **_REBUILD_CONSENT) is EditTextResult.SUCCESS
        assert _pending_pages(model) == [0]
        assert 0 not in model.fidelity_protected_pages
        # Another line on the same page is still a true-text edit.
        result = _edit(model, "Downstream", "Downstream line stayz")
        _assert_true_text_commit(model, result)
    finally:
        model.close()


def test_true_text_edit_after_undoing_the_add_commits_and_bookkeeping_is_restored(tmp_path):
    model = _tiered(tmp_path)
    try:
        assert _pending_pages(model) == []
        _add_box(model)
        assert _pending_pages(model) == [0]
        assert model.command_manager.undo()
        # The undo restored the page bytes, so it also owns the cleanup
        # entry the add queued: nothing is left to clean on the page.
        assert _pending_pages(model) == []
        assert "NEW BOX" not in model.doc[0].get_text()
        _assert_true_text_commit(model, _edit(model, TARGET, REPLACEMENT))
    finally:
        model.close()


def test_undo_and_redo_of_the_add_restore_protection_and_pending_membership(tmp_path):
    model = _tiered(tmp_path)
    try:
        _assert_true_text_commit(model, _edit_cmd(model, TARGET, REPLACEMENT).result)
        assert _pending_pages(model) == []
        _add_box(model)  # a legacy rewrite revokes protection, queues cleanup
        assert 0 not in model.fidelity_protected_pages
        assert _pending_pages(model) == [0]

        assert model.command_manager.undo()
        assert 0 in model.fidelity_protected_pages  # the Tier 0 page is back
        assert _pending_pages(model) == []

        assert model.command_manager.redo()
        assert 0 not in model.fidelity_protected_pages
        assert _pending_pages(model) == [0]

        assert model.command_manager.undo()
        assert 0 in model.fidelity_protected_pages
        assert _pending_pages(model) == []
    finally:
        model.close()


def test_save_as_after_undoing_the_add_never_cleans_the_protected_page(tmp_path, monkeypatch):
    model = _tiered(tmp_path)
    try:
        _assert_true_text_commit(model, _edit_cmd(model, TARGET, REPLACEMENT).result)
        _add_box(model)
        assert model.command_manager.undo()
        cleaned = _spy_clean_contents(monkeypatch)
        model.save_as(str(tmp_path / "saved.pdf"))
        assert cleaned == []
    finally:
        model.close()


def test_undo_then_save_then_redo_of_the_true_text_edit_is_stale_with_zero_mutation(tmp_path):
    model = _tiered(tmp_path)
    try:
        _add_box(model)
        command = _edit_cmd(model, TARGET, REPLACEMENT)
        _assert_true_text_commit(model, command.result)
        assert model.command_manager.undo()  # the true-text edit
        # The add's cleanup is still pending and the page is unprotected, so
        # the save cleans the page: the retained forward patch is now stale.
        model.save_as(str(tmp_path / "saved.pdf"))

        def _streams() -> list[bytes]:
            return [model.doc.xref_stream(x) for x in model.doc[0].get_contents()]

        before = _streams()
        assert model.command_manager.redo() is False
        assert _streams() == before
        outcome = model.last_commit_outcome
        assert outcome is not None and outcome.status is CommitStatus.STALE_PLAN
    finally:
        model.close()


def test_undo_and_redo_of_a_consented_rebuild_own_its_cleanup_entry(tmp_path):
    model = _tiered(tmp_path)
    try:
        _grip_move_rebuild(model)
        assert _pending_pages(model) == [0], "the consented rebuild queues a cleanup entry"
        assert 0 not in model.fidelity_protected_pages
        assert model.command_manager.undo()
        # The undo put the page bytes back, so it owns the entry the rebuild
        # queued (HIST-1): nothing is left to clean on the page.
        assert _pending_pages(model) == []
        assert model.command_manager.redo()
        assert _pending_pages(model) == [0]
        assert 0 not in model.fidelity_protected_pages
        assert model.command_manager.undo()
        assert _pending_pages(model) == []
    finally:
        model.close()


def test_undo_of_a_rebuild_keeps_the_pending_entry_of_an_earlier_command(tmp_path):
    model = _tiered(tmp_path)
    try:
        _add_box(model)  # still applied: its cleanup entry is live
        _grip_move_rebuild(model)
        assert model.command_manager.undo()  # the rebuild
        assert _pending_pages(model) == [0]  # the add's entry survives
        assert model.command_manager.undo()  # the add
        assert _pending_pages(model) == []
    finally:
        model.close()


def test_tier0_redo_survives_a_save_after_an_undone_rebuild(tmp_path):
    """Order A: rebuild, undo, Tier 0 edit, undo, save, redo."""
    model = _tiered(tmp_path)
    try:
        _grip_move_rebuild(model)
        assert model.command_manager.undo()
        tier0 = _edit_cmd(model, TARGET, REPLACEMENT)
        _assert_true_text_commit(model, tier0.result)
        assert model.command_manager.undo()
        before = model.doc[0].read_contents()
        model.save_as(str(tmp_path / "saved.pdf"))
        assert model.doc[0].read_contents() == before, "save must not clean the page"
        assert model.command_manager.redo() is True
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


def test_tier0_redo_survives_a_save_after_a_rebuild_undone_on_top_of_it(tmp_path):
    """Order B: Tier 0 edit, rebuild, undo, undo, save, redo."""
    model = _tiered(tmp_path)
    try:
        tier0 = _edit_cmd(model, TARGET, REPLACEMENT)
        _assert_true_text_commit(model, tier0.result)
        _grip_move_rebuild(model)
        assert model.command_manager.undo()  # the rebuild
        assert 0 in model.fidelity_protected_pages
        assert model.command_manager.undo()  # the Tier 0 edit
        before = model.doc[0].read_contents()
        model.save_as(str(tmp_path / "saved.pdf"))
        assert model.doc[0].read_contents() == before, "save must not clean the page"
        assert model.command_manager.redo() is True
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()


# --- R5-BOOK-1: a rolled-back legacy edit must put the maintenance book back --


def _boom_verify(exc: Exception):
    def _verify(*_args, **_kwargs):
        raise exc

    return _verify


def _fail_rebuild(model: PDFModel, mode: str, monkeypatch) -> None:
    """Drive one consented rebuild to a rollback, by the named failure mode."""
    new_text, new_rect = "Downstream line stays", _moved_rect(model, "Downstream")
    if mode == "overflow":
        new_text, new_rect = "W" * 30000, fitz.Rect(_block(model, "Downstream").layout_rect)
    elif mode == "protected_neighbour":
        monkeypatch.setattr(model, "_validate_protected_spans", lambda *_a, **_k: False)
    elif mode == "unexpected_exception":
        monkeypatch.setattr(model, "_verify_rebuild_edit", _boom_verify(ValueError("boom")))
    elif mode == "runtime_after_mutation":
        monkeypatch.setattr(model, "_verify_rebuild_edit", _boom_verify(RuntimeError("boom")))
    else:  # pragma: no cover
        raise AssertionError(mode)
    with pytest.raises(RuntimeError):
        _edit_cmd(model, "Downstream", new_text, new_rect=new_rect, rebuild=True)


_ROLLBACK_MODES = ["overflow", "protected_neighbour", "unexpected_exception", "runtime_after_mutation"]


@pytest.mark.parametrize("mode", _ROLLBACK_MODES)
def test_failed_rebuild_rollback_restores_protection_and_pending(tmp_path, monkeypatch, mode):
    model = _tiered(tmp_path)
    try:
        tier0 = _edit_cmd(model, TARGET, REPLACEMENT)
        _assert_true_text_commit(model, tier0.result)
        assert _pending_pages(model) == []
        committed = model.doc[0].read_contents()
        _fail_rebuild(model, mode, monkeypatch)
        assert model.doc[0].read_contents() == committed, "the page bytes are rolled back"
        # The bookkeeping travels with the bytes: the page is still the
        # verified Tier 0 page, with nothing queued for clean_contents.
        assert model.fidelity_protected_pages == {0}
        assert _pending_pages(model) == []
        model.save_as(str(tmp_path / "saved.pdf"))
        assert model.doc[0].read_contents() == committed, "save must not clean the page"
        assert model.command_manager.undo() is True
        assert TARGET in model.doc[0].get_text()
    finally:
        model.close()


def test_failed_rebuild_rollback_keeps_an_earlier_pending_entry_once(tmp_path, monkeypatch):
    model = _tiered(tmp_path)
    try:
        _add_box(model)  # a live cleanup entry from an earlier command
        before = [dict(e) for e in model.pending_edits]
        assert len(before) == 1
        _fail_rebuild(model, "overflow", monkeypatch)
        assert [dict(e) for e in model.pending_edits] == before
        assert 0 not in model.fidelity_protected_pages
    finally:
        model.close()


def test_failed_rebuild_rollback_leaves_other_pages_bookkeeping_alone(tmp_path, monkeypatch):
    model = _tiered(tmp_path)
    try:
        model.fidelity_protected_pages.add(7)  # another page, not under edit
        model.pending_edits.append({"page_idx": 9, "rect": fitz.Rect(1, 1, 2, 2)})
        _fail_rebuild(model, "overflow", monkeypatch)
        assert 7 in model.fidelity_protected_pages
        assert _pending_pages(model) == [9]
    finally:
        model.close()


def test_planner_no_longer_has_a_pending_maintenance_gate():
    for fn in (plan.prepare_tier0_plan, plan.prepare_plan):
        assert "page_has_pending_maintenance" not in inspect.signature(fn).parameters


def test_retired_code_never_says_try_later_and_still_offers_the_rebuild():
    code = "pending_page_maintenance"
    text = rejection_reason_text(code)
    assert text and "稍後" not in text and code not in text
    assert rebuild_offered_for(code) is True


# ------------------------------------------------------------ real-app tests
# Synthetic Identity-H document + real QTest input (the part-3 harness).


@pytest.fixture
def launch(qapp, monkeypatch):
    apps: list[_App] = []

    def _launch(path: Path, **kwargs) -> _App:
        app = _App(monkeypatch, path, **kwargs)
        apps.append(app)
        return app

    yield _launch
    for app in apps:
        app.close()


def _ui_add_box(app: _App) -> None:
    """Add a text box through the view's real signal (Controller -> command)."""
    app.view.sig_add_textbox.emit(1, NEW_BOX_RECT, "NEW BOX", "helv", 12, (0.0, 0.0, 0.0), None)
    app.pump(300)
    assert _pending_pages(app.model) == [0], "the add queued no cleanup"


def test_ui_add_textbox_then_true_text_edit_obtains_a_token_and_commits(tmp_path, launch):
    app = launch(_author(tmp_path / "add_then_edit.pdf"))
    _ui_add_box(app)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    token = app.wait_token(editor)  # RED before: refused as pending_page_maintenance
    app.click_apply()

    assert len(app.commits) == 1
    _, prepared, outcome, _ = app.commits[0]
    assert prepared.token == token
    assert outcome.status is CommitStatus.COMMITTED and outcome.fallback_chain == ()
    assert app.editor() is None
    assert encode_cids(_EDIT_B) in app.page_texts()
    assert "NEW BOX" in app.model.doc[0].get_text()


def test_ui_editor_kept_open_across_ctrl_s_after_an_add_still_commits(tmp_path, launch):
    path = _author(tmp_path / "kept_across_save.pdf")
    app = launch(path)
    _ui_add_box(app)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    # Save before the verified preview arrives: the document is saved as-is
    # (the add is cleaned on the unprotected page), the editor stays open.
    app.view._action_save.trigger()
    app.pump(600)
    assert app.editor() is editor and editor.toPlainText() == _EDIT_B
    assert app.model.pending_edits == []

    app.wait_token(editor)  # RED if the session still previews the pre-save page
    app.click_apply()
    assert len(app.commits) == 1
    assert app.commits[0][2].status is CommitStatus.COMMITTED
    assert encode_cids(_EDIT_B) in app.page_texts()


def test_ui_session_opened_before_a_save_previews_the_cleaned_page_after_it(tmp_path, launch):
    """The preview session snapshots the page when it opens.  A save cleans
    an unprotected page that has queued maintenance, so an editor that is
    still open (kept by Ctrl+S, no token yet) must preview the SAVED page."""
    path = _author(tmp_path / "session_before_save.pdf")
    app = launch(path)
    _ui_add_box(app)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)  # the session is open and verified on the old page
    QTest.keyClick(editor, Qt.Key_Backspace)  # new generation: token cleared
    QTest.keyClicks(editor, "o")
    assert editor.current_plan_token() is None
    app.view._action_save.trigger()
    app.pump(600)
    assert app.editor() is editor
    assert app.model.pending_edits == []

    app.wait_token(editor)
    app.click_apply()
    assert len(app.commits) == 1, app.toasts
    assert app.commits[0][2].status is CommitStatus.COMMITTED


# --- ERR-3: a rollback that itself fails must be reported as such ------------


@pytest.mark.parametrize("site", ["outer_runtime_error", "inner_site_stale"])
@pytest.mark.parametrize("restore_kind", ["runtime_error", "page_snapshot_stale"])
def test_failed_rebuild_rollback_is_reported_as_rollback_failure(tmp_path, monkeypatch, site, restore_kind):
    restore_exc: Exception = (
        RuntimeError("page snapshot restore failed; page put back")
        if restore_kind == "runtime_error"
        else PageSnapshotStale("page object changed since the snapshot")
    )

    def _restore_fails(*_a, **_k):
        raise restore_exc

    model = _tiered(tmp_path)
    try:
        tier0 = _edit_cmd(model, TARGET, REPLACEMENT)
        _assert_true_text_commit(model, tier0.result)
        if site == "outer_runtime_error":
            monkeypatch.setattr(model, "_verify_rebuild_edit", _boom_verify(RuntimeError("boom-after-mutation")))
        else:
            monkeypatch.setattr(model, "_validate_protected_spans", lambda *_a, **_k: False)
        monkeypatch.setattr(model, "_restore_page_from_snapshot", _restore_fails)
        moved = _moved_rect(model, "Downstream")
        undo_before = model.command_manager.undo_count
        with pytest.raises(RuntimeError) as info:
            _edit_cmd(model, "Downstream", "Downstream line stays", new_rect=moved, rebuild=True)
        assert "回滾失敗" in str(info.value), str(info.value)
        assert info.value.__cause__ is not None
        assert model.command_manager.undo_count == undo_before
    finally:
        model.close()
