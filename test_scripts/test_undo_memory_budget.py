"""Phase 3.1 — undo stack byte budget + adjacent snapshot dedup."""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from model.edit_commands import (
    AddTextboxCommand,
    CommandManager,
    EditCommand,
    EditTextCommand,
    SnapshotCommand,
)
from model.pdf_model import PDFModel


class _FakeModel:
    """Minimal stand-in: SnapshotCommand only needs these two methods."""

    def _restore_doc_from_snapshot(self, snapshot_bytes: bytes) -> None:
        pass

    def refresh_structural_indexes(self, affected_pages: list[int]) -> None:
        pass


def _snapshot_cmd(model: _FakeModel, before: bytes, after: bytes, desc: str) -> SnapshotCommand:
    return SnapshotCommand(
        model=model,
        command_type="delete_pages",
        affected_pages=[1],
        before_bytes=before,
        after_bytes=after,
        description=desc,
    )


def _make_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), f"page {i + 1}", fontsize=12, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def test_byte_budget_evicts_oldest_snapshot_commands(monkeypatch) -> None:
    # Red-light: MAX_UNDO_STACK_BYTES does not exist yet -> AttributeError here.
    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 300 * 1024)

    cm = CommandManager()
    model = _FakeModel()

    # Three commands of ~160 KiB each (80 KiB before + 80 KiB after), unique
    # payloads so the dedup pass cannot fire.
    cmds = []
    for i in range(3):
        before = bytes([i]) * (80 * 1024)
        after = bytes([i + 10]) * (80 * 1024)
        cmd = _snapshot_cmd(model, before, after, f"op {i}")
        cmds.append(cmd)

    cm.record(cmds[0])
    cm.mark_saved()  # saved marker = cmds[0]; evicting it must not read clean
    cm.record(cmds[1])
    cm.record(cmds[2])

    # 3 x 160 KiB = 480 KiB > 300 KiB -> evict cmd0 (320 KiB still > 300) -> evict
    # cmd1 (160 KiB <= 300). Only the newest survives.
    assert cm.undo_count == 1, f"byte budget should evict oldest, undo_count={cm.undo_count}"
    assert cm._undo_stack[-1] is cmds[2]
    # The saved command (cmds[0]) was evicted: its state is unreachable, so
    # has_pending_changes() must report the unsaved tail.
    assert cm.has_pending_changes() is True


def test_adjacent_dedup_shares_bytes_object() -> None:
    cm = CommandManager()
    model = _FakeModel()

    shared_after = bytes(bytearray(b"y" * 4096))
    equal_before = bytes(bytearray(b"y" * 4096))
    assert shared_after == equal_before
    assert shared_after is not equal_before

    cmd1 = _snapshot_cmd(model, b"a" * 1024, shared_after, "op 1")
    cmd2 = _snapshot_cmd(model, equal_before, b"z" * 1024, "op 2")

    cm.record(cmd1)
    cm.record(cmd2)

    assert cm._undo_stack[-2]._after_bytes is cm._undo_stack[-1]._before_bytes, (
        "adjacent SnapshotCommands with equal boundary bytes should share one object"
    )


def test_dedup_does_not_corrupt_undo_redo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "three_page.pdf"
        _make_pdf(pdf_path, pages=3)

        m = PDFModel()
        try:
            m.open_pdf(str(pdf_path))
            assert len(m.doc) == 3

            # Op 1: delete page 3.
            before1 = m._capture_doc_snapshot()
            m.delete_pages([3])
            after1 = m._capture_doc_snapshot()
            m.command_manager.record(
                SnapshotCommand(
                    model=m,
                    command_type="delete_pages",
                    affected_pages=[3],
                    before_bytes=before1,
                    after_bytes=after1,
                    description="delete page 3",
                )
            )
            assert len(m.doc) == 2

            # Op 2: insert a blank page (adjacent snapshot boundary == after1).
            before2 = m._capture_doc_snapshot()
            m.insert_blank_page(2)
            after2 = m._capture_doc_snapshot()
            m.command_manager.record(
                SnapshotCommand(
                    model=m,
                    command_type="insert_blank_page",
                    affected_pages=[2],
                    before_bytes=before2,
                    after_bytes=after2,
                    description="insert blank page",
                )
            )
            assert len(m.doc) == 3

            # Full round-trip must survive any dedup sharing.
            assert m.command_manager.undo() is True
            assert len(m.doc) == 2
            assert m.command_manager.undo() is True
            assert len(m.doc) == 3
            assert m.command_manager.redo() is True
            assert len(m.doc) == 2
            assert m.command_manager.redo() is True
            assert len(m.doc) == 3
        finally:
            m.close()


def test_byte_size_returns_correct_values() -> None:
    class _NoopCommand(EditCommand):
        def execute(self) -> None:
            pass

        def undo(self) -> None:
            pass

    # Red-light: _byte_size() does not exist yet -> AttributeError.
    assert _NoopCommand()._byte_size() == 0

    edit_cmd = EditTextCommand(
        model=None,
        page_num=1,
        rect=fitz.Rect(0, 0, 10, 10),
        new_text="t",
        font="helv",
        size=12.0,
        color=(0, 0, 0),
        original_text="o",
        vertical_shift_left=False,
        page_snapshot_bytes=b"abc",
        old_block_id=None,
        old_block_text=None,
    )
    assert edit_cmd._byte_size() == 3

    textbox_cmd = AddTextboxCommand(
        model=None,
        page_num=1,
        visual_rect=fitz.Rect(0, 0, 10, 10),
        text="t",
        font="helv",
        size=12,
        color=(0, 0, 0),
        before_page_snapshot_bytes=b"abcd",
    )
    assert textbox_cmd._byte_size() == 4  # after-bytes still None
    textbox_cmd._after_page_snapshot_bytes = b"xy"
    assert textbox_cmd._byte_size() == 6

    snap_cmd = SnapshotCommand(
        model=None,
        command_type="delete_pages",
        affected_pages=[1],
        before_bytes=b"123",
        after_bytes=b"4567",
        description="d",
    )
    assert snap_cmd._byte_size() == 7


def test_single_oversized_command_survives_byte_trim(monkeypatch) -> None:
    """A single command larger than the budget must survive (can_undo stays True)."""
    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 100)

    cm = CommandManager()
    model = _FakeModel()
    big = _snapshot_cmd(model, b"x" * 200, b"y" * 200, "big")
    cm.record(big)

    assert cm.can_undo() is True, "oversized newest command must survive trim"
    assert cm._undo_stack[-1] is big
    assert cm.has_pending_changes() is True


def test_dedup_shared_bytes_counted_once_in_budget(monkeypatch) -> None:
    """After dedup, shared bytes between adjacent commands should count once,
    not twice. A budget that fits unique bytes but not double-counted bytes
    must not evict anything."""
    cm = CommandManager()
    model = _FakeModel()

    shared = b"s" * 100
    cmd1 = _snapshot_cmd(model, b"a" * 50, bytes(shared), "op1")
    cmd2 = _snapshot_cmd(model, bytes(shared), b"c" * 50, "op2")

    cm.record(cmd1)
    cm.record(cmd2)

    # Verify dedup fired.
    assert cm._undo_stack[0]._after_bytes is cm._undo_stack[1]._before_bytes

    # Unique bytes: 50 (a) + 100 (shared) + 50 (c) = 200.
    # Double-counted: 50 + 100 + 100 + 50 = 300.
    # Budget = 250: fits unique (200), but not double-counted (300).
    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 250)
    cm._trim_undo_stack_if_needed()

    assert cm.undo_count == 2, (
        f"dedup'd shared bytes should count once — both commands fit in 250-byte budget, "
        f"but got undo_count={cm.undo_count}"
    )


def test_non_adjacent_identical_bytes_counted_once() -> None:
    """R4.4: byte-identical snapshots that are NOT an adjacent boundary pair must
    still count once against the budget. `_dedup_top_snapshot_pair` only aliases the
    top two commands at push time, so non-adjacent duplicates stay distinct objects;
    `_unique_byte_total` must dedup them by CONTENT, not by id()."""
    cm = CommandManager()
    model = _FakeModel()

    x = b"x" * 100
    x_dup = bytes(bytearray(b"x" * 100))  # identical content, distinct object
    assert x == x_dup and x is not x_dup

    cmd1 = _snapshot_cmd(model, b"a" * 50, x, "op1")
    cmd2 = _snapshot_cmd(model, b"b" * 50, b"c" * 50, "op2")
    cmd3 = _snapshot_cmd(model, x_dup, b"d" * 50, "op3")

    cm.record(cmd1)
    cm.record(cmd2)
    cm.record(cmd3)

    # The duplicate (x / x_dup) is non-adjacent, so no alias was created.
    assert cm._undo_stack[0]._after_bytes is not cm._undo_stack[2]._before_bytes

    # Distinct content: a(50) + x(100) + b(50) + c(50) + d(50) = 300.
    # id()-keyed double-counts x twice -> 400.
    assert cm._unique_byte_total() == 300, (
        f"non-adjacent identical bytes must count once, got {cm._unique_byte_total()}"
    )


def test_non_adjacent_duplicate_does_not_prematurely_evict(monkeypatch) -> None:
    """R4.4: a budget that fits the unique footprint but not the id()-double-counted
    figure must NOT evict when the duplicate is non-adjacent."""
    cm = CommandManager()
    model = _FakeModel()

    x = b"x" * 100
    cmd1 = _snapshot_cmd(model, b"a" * 50, x, "op1")
    cmd2 = _snapshot_cmd(model, b"b" * 50, b"c" * 50, "op2")
    cmd3 = _snapshot_cmd(model, bytes(bytearray(b"x" * 100)), b"d" * 50, "op3")

    cm.record(cmd1)
    cm.record(cmd2)
    cm.record(cmd3)

    # Unique footprint = 300; id()-double-counted = 400. Budget 350 fits unique only.
    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 350)
    cm._trim_undo_stack_if_needed()

    assert cm.undo_count == 3, (
        f"non-adjacent duplicate should count once — all 3 fit in 350-byte budget, "
        f"got undo_count={cm.undo_count}"
    )


# ---------------------------------------------------------------------------
# LS-1: the saved marker must identify the saved STATE, not a stack length
# ---------------------------------------------------------------------------


class _CountingCommand(EditCommand):
    """Applies +delta to a shared register: the register is the 'document'."""

    def __init__(self, register: dict, delta: int = 1) -> None:
        self._register = register
        self._delta = delta

    def execute(self) -> None:
        self._register["v"] += self._delta

    def undo(self) -> None:
        self._register["v"] -= self._delta

    @property
    def description(self) -> str:
        return f"add {self._delta}"


def _do(cm: CommandManager, register: dict, delta: int = 1) -> _CountingCommand:
    cmd = _CountingCommand(register, delta)
    cm.execute(cmd)
    return cmd


def test_save_undo_new_edit_is_pending_even_at_the_saved_length() -> None:
    """save -> undo -> a DIFFERENT edit leaves the stack at the saved length but the
    document is not the saved one (length-only marker reported it clean)."""
    reg = {"v": 0}
    cm = CommandManager()
    _do(cm, reg)
    cm.mark_saved()
    assert cm.has_pending_changes() is False

    assert cm.undo() is True
    assert cm.has_pending_changes() is True
    _do(cm, reg, 10)  # different history, same length (1)
    assert cm.undo_count == 1
    assert reg["v"] == 10  # differs from the saved value 1
    assert cm.has_pending_changes() is True


def test_save_undo_redo_returns_to_clean() -> None:
    reg = {"v": 0}
    cm = CommandManager()
    _do(cm, reg)
    cm.mark_saved()
    cm.undo()
    assert cm.has_pending_changes() is True
    assert cm.redo() is True
    assert cm.has_pending_changes() is False
    # further undo/redo cycles keep tracking the same saved state
    cm.undo()
    assert cm.has_pending_changes() is True
    cm.redo()
    assert cm.has_pending_changes() is False


def test_saved_at_empty_base_tracks_undo_to_base() -> None:
    reg = {"v": 0}
    cm = CommandManager()
    cm.mark_saved()  # saved with an empty stack (fresh open)
    _do(cm, reg)
    assert cm.has_pending_changes() is True
    cm.undo()
    assert cm.has_pending_changes() is False  # back at the saved base
    _do(cm, reg)
    cm.mark_saved()
    cm.undo()  # base is no longer the saved state
    assert cm.has_pending_changes() is True


def test_save_then_new_branch_then_undo_stays_pending() -> None:
    """save at [A]; undo A; record B; undo B -> stack [] != saved state [A]."""
    reg = {"v": 0}
    cm = CommandManager()
    _do(cm, reg)
    cm.mark_saved()
    cm.undo()
    _do(cm, reg, 10)
    cm.undo()
    assert cm.undo_count == 0
    assert reg["v"] == 0  # saved value was 1
    assert cm.has_pending_changes() is True


def test_two_saves_use_the_latest_state() -> None:
    reg = {"v": 0}
    cm = CommandManager()
    _do(cm, reg)
    cm.mark_saved()
    _do(cm, reg)
    cm.mark_saved()
    assert cm.has_pending_changes() is False
    cm.undo()
    assert cm.has_pending_changes() is True
    cm.redo()
    assert cm.has_pending_changes() is False


def test_evicting_past_a_saved_empty_base_never_reads_clean() -> None:
    """Saved at the empty base, then 101 commands (the first is evicted) and 100 undos:
    the stack is empty again, but the first command is still applied to the document."""
    reg = {"v": 0}
    cm = CommandManager()
    cm.mark_saved()
    for _ in range(CommandManager.MAX_UNDO_STACK_SIZE + 1):
        _do(cm, reg)
    for _ in range(CommandManager.MAX_UNDO_STACK_SIZE):
        assert cm.undo() is True
    assert cm.undo_count == 0
    assert reg["v"] == 1  # the evicted command is still in the document
    assert cm.has_pending_changes() is True
    assert cm.can_undo() is False


def test_evicting_the_saved_command_never_reads_clean() -> None:
    reg = {"v": 0}
    cm = CommandManager()
    _do(cm, reg)
    cm.mark_saved()  # saved state = after command #1
    for _ in range(CommandManager.MAX_UNDO_STACK_SIZE):
        _do(cm, reg)  # evicts command #1 (count cap)
    assert cm.has_pending_changes() is True
    for _ in range(CommandManager.MAX_UNDO_STACK_SIZE):
        cm.undo()
    assert reg["v"] == 1 and cm.undo_count == 0
    assert cm.has_pending_changes() is True


def test_byte_budget_eviction_of_the_saved_command_never_reads_clean(monkeypatch) -> None:
    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 300 * 1024)
    cm = CommandManager()
    model = _FakeModel()
    cmds = [
        _snapshot_cmd(model, bytes([i]) * (80 * 1024), bytes([i + 10]) * (80 * 1024), f"op {i}")
        for i in range(3)
    ]
    cm.record(cmds[0])
    cm.mark_saved()
    cm.record(cmds[1])
    cm.record(cmds[2])  # evicts cmds[0] and cmds[1]
    assert cm.undo_count == 1
    assert cm.has_pending_changes() is True
    cm.undo()
    assert cm.undo_count == 0
    assert cm.has_pending_changes() is True  # stack is empty but base was never saved


def test_byte_budget_eviction_of_an_empty_base_never_reads_clean(monkeypatch) -> None:
    monkeypatch.setattr(CommandManager, "MAX_UNDO_STACK_BYTES", 300 * 1024)
    cm = CommandManager()
    model = _FakeModel()
    cm.mark_saved()  # empty base
    for i in range(3):
        cm.record(_snapshot_cmd(model, bytes([i]) * (80 * 1024), bytes([i + 10]) * (80 * 1024), f"op {i}"))
    assert cm.undo_count == 1
    cm.undo()
    assert cm.undo_count == 0
    assert cm.has_pending_changes() is True


def test_saved_marker_survives_unrelated_eviction() -> None:
    """Evicting commands OLDER than the saved one keeps the saved state reachable."""
    reg = {"v": 0}
    cm = CommandManager()
    for _ in range(CommandManager.MAX_UNDO_STACK_SIZE):
        _do(cm, reg)
    cm.mark_saved()
    assert cm.has_pending_changes() is False
    _do(cm, reg)  # evicts the oldest command, saved command still on the stack
    assert cm.has_pending_changes() is True
    cm.undo()
    assert cm.has_pending_changes() is False


def test_a_discarded_saved_command_is_not_retained_and_clear_resets() -> None:
    import gc
    import weakref

    reg = {"v": 0}
    cm = CommandManager()
    cmd = _do(cm, reg)
    cm.mark_saved()
    cm.undo()
    ref = weakref.ref(cmd)
    del cmd
    _do(cm, reg, 10)  # clears the redo stack: the saved command is gone for good
    cm.undo()
    gc.collect()
    assert ref() is None, "the saved marker must not keep a discarded command (and its snapshots) alive"
    assert cm.has_pending_changes() is True
    cm.clear()
    assert cm.has_pending_changes() is False


def test_session_dirty_after_save_undo_new_edit_through_the_model() -> None:
    """The model-level readers (active tab, any tab, dirty ids) all see the session as dirty."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "doc.pdf"
        _make_pdf(pdf_path, pages=3)
        m = PDFModel()
        try:
            m.open_pdf(str(pdf_path))
            sid = m.get_active_session_id()
            reg = {"v": 0}
            _do(m.command_manager, reg)
            m.save_as(str(Path(tmp) / "saved.pdf"))
            assert m.has_unsaved_changes() is False
            m.command_manager.undo()
            assert m.has_unsaved_changes() is True
            _do(m.command_manager, reg, 10)
            assert m.command_manager.undo_count == 1
            assert m.has_unsaved_changes() is True
            assert m.has_any_unsaved_changes() is True
            assert m.get_dirty_session_ids() == [sid]
        finally:
            m.close()
