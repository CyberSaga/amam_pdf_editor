"""Regression tests for controller-driven cross-page text moves.

UI step 7: a cross-page move always rebuilds text (source deletion AND
destination add_textbox), so every move here carries the explicit
rebuild consent (``allow_rebuild=True`` + a stubbed confirm).  The refusal
without consent is pinned in test_text_commit_no_silent_legacy.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import pytest

import controller.pdf_controller as pdf_controller_module
from controller.pdf_controller import PDFController
from model.edit_commands import EditTextResult, SnapshotCommand
from model.pdf_model import PDFModel


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def _make_two_page_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=360, height=240)
    doc.new_page(width=360, height=240)
    page1 = doc[0]
    page2 = doc[1]
    page1.insert_text(fitz.Point(40, 60), "MOVE_ME", fontsize=16, fontname="helv", color=(0, 0, 0))
    page2.insert_text(fitz.Point(40, 160), "KEEP_PAGE_TWO", fontsize=16, fontname="helv", color=(0, 0, 0))
    doc.save(path)
    doc.close()


class _FakeView:
    def capture_viewport_anchor(self):
        return None


def _make_controller(model: PDFModel) -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = model
    controller.view = _FakeView()
    controller._invalidate_active_render_state = lambda *args, **kwargs: None
    controller._invalidate_thumbnails = lambda *args, **kwargs: None
    controller.show_page = lambda page_idx: None
    controller._update_undo_redo_tooltips = lambda: None
    # UI step 7: a cross-page move needs the explicit rebuild consent;
    # stub the confirm (a real one is a Qt modal).
    controller._confirm_legacy_fallback = lambda _chain: True
    return controller


def _capture_errors(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every ``show_error`` message the controller would have shown."""
    errors: list[str] = []
    monkeypatch.setattr(pdf_controller_module, "show_error", lambda _view, message: errors.append(message))
    return errors


def test_move_text_across_pages_records_single_snapshot_command_and_undoes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_move.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            hit = model.get_text_info_at_point(1, fitz.Point(60, 56))
            assert hit is not None
            controller = _make_controller(model)

            before_undo = model.command_manager.undo_count
            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(hit.target_bbox),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text=hit.target_text,
                font=hit.font,
                size=int(round(hit.size)),
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode=hit.target_mode,
                allow_rebuild=True,
            )

            assert model.command_manager.undo_count == before_undo + 1
            last_cmd = model.command_manager._undo_stack[-1]
            assert isinstance(last_cmd, SnapshotCommand)
            assert last_cmd.description == "跨頁移動文字"

            page1_text = _norm(model.doc[0].get_text("text"))
            page2_text = _norm(model.doc[1].get_text("text"))
            assert "move_me" not in page1_text
            assert "move_me" in page2_text
            assert "keep_page_two" in page2_text

            model.command_manager.undo()
            page1_undo = _norm(model.doc[0].get_text("text"))
            page2_undo = _norm(model.doc[1].get_text("text"))
            assert "move_me" in page1_undo
            assert "move_me" not in page2_undo
            assert "keep_page_two" in page2_undo

            model.command_manager.redo()
            page1_redo = _norm(model.doc[0].get_text("text"))
            page2_redo = _norm(model.doc[1].get_text("text"))
            assert "move_me" not in page1_redo
            assert "move_me" in page2_redo
        finally:
            model.close()


def test_cross_page_move_success_invalidates_thumbnails_for_both_pages() -> None:
    """Successful cross-page text move must invalidate thumbnails for source
    and destination pages (the old code had a wrong 'thumbnails stay valid' comment)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_thumb.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            hit = model.get_text_info_at_point(1, fitz.Point(60, 56))
            assert hit is not None

            thumb_calls: list[tuple] = []
            controller = PDFController.__new__(PDFController)
            controller.model = model
            controller.view = _FakeView()
            controller._invalidate_active_render_state = lambda *args, **kwargs: None
            controller._invalidate_thumbnails = lambda *args, **kwargs: thumb_calls.append((args, kwargs))
            controller.show_page = lambda page_idx: None
            controller._update_undo_redo_tooltips = lambda: None
            controller._confirm_legacy_fallback = lambda _chain: True

            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(hit.target_bbox),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text=hit.target_text,
                font=hit.font,
                size=int(round(hit.size)),
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode=hit.target_mode,
                allow_rebuild=True,
            )

            assert thumb_calls, "success path must invalidate thumbnails"
            affected = thumb_calls[0][0][0]  # first positional arg
            assert 1 in affected and 2 in affected, (
                f"must invalidate both source and dest pages, got {affected}"
            )
        finally:
            model.close()


def test_cross_page_move_unresolved_source_without_span_id_aborts_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors = _capture_errors(monkeypatch)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_missing_source.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            controller = _make_controller(model)

            before_page1 = _norm(model.doc[0].get_text("text"))
            before_page2 = _norm(model.doc[1].get_text("text"))
            before_undo = model.command_manager.undo_count

            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(220, 180, 320, 220),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text="MOVE_ME",
                font="helv",
                size=16,
                color=(0.0, 0.0, 0.0),
                original_text="DOES_NOT_EXIST",
                target_span_id=None,
                target_mode="run",
                allow_rebuild=True,
            )

            assert model.command_manager.undo_count == before_undo
            assert _norm(model.doc[0].get_text("text")) == before_page1
            assert _norm(model.doc[1].get_text("text")) == before_page2
            assert errors
        finally:
            model.close()


def test_cross_page_move_stale_span_id_falls_back_to_rect_text_resolution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_stale_span_id.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            hit = model.get_text_info_at_point(1, fitz.Point(60, 56))
            assert hit is not None
            controller = _make_controller(model)

            before_undo = model.command_manager.undo_count
            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(hit.target_bbox),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text=hit.target_text,
                font=hit.font,
                size=int(round(hit.size)),
                color=hit.color,
                original_text=hit.target_text,
                target_span_id="stale-span-id",
                target_mode=hit.target_mode,
                allow_rebuild=True,
            )

            assert model.command_manager.undo_count == before_undo + 1
            assert "move_me" not in _norm(model.doc[0].get_text("text"))
            assert "move_me" in _norm(model.doc[1].get_text("text"))
        finally:
            model.close()


def test_cross_page_move_add_failure_restores_before_snapshot_and_refreshes_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors = _capture_errors(monkeypatch)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_add_failure.pdf"
        _make_two_page_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            hit = model.get_text_info_at_point(1, fitz.Point(60, 56))
            assert hit is not None

            controller = PDFController.__new__(PDFController)
            controller.model = model
            controller.view = _FakeView()
            invalidate_calls: list[tuple] = []
            thumb_invalidate_calls: list[tuple] = []
            shown_pages: list[int] = []
            tooltip_calls: list[bool] = []
            controller._invalidate_active_render_state = lambda *args, **kwargs: invalidate_calls.append((args, kwargs))
            controller._invalidate_thumbnails = lambda *args, **kwargs: thumb_invalidate_calls.append((args, kwargs))
            controller.show_page = lambda page_idx: shown_pages.append(page_idx)
            controller._update_undo_redo_tooltips = lambda: tooltip_calls.append(True)
            controller._confirm_legacy_fallback = lambda _chain: True

            before_page1 = _norm(model.doc[0].get_text("text"))
            before_page2 = _norm(model.doc[1].get_text("text"))
            before_undo = model.command_manager.undo_count

            monkeypatch.setattr(
                model,
                "add_textbox",
                lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
            )

            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(hit.target_bbox),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text=hit.target_text,
                font=hit.font,
                size=int(round(hit.size)),
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode=hit.target_mode,
                allow_rebuild=True,
            )

            assert model.command_manager.undo_count == before_undo
            assert _norm(model.doc[0].get_text("text")) == before_page1
            assert _norm(model.doc[1].get_text("text")) == before_page2
            assert invalidate_calls
            # Rollback path must invalidate thumbnails for affected pages.
            assert thumb_invalidate_calls, "rollback must invalidate thumbnails"
            assert shown_pages == [0]
            assert tooltip_calls
            assert errors
        finally:
            model.close()


def _make_multi_line_pdf(path: Path, lines: list[str]) -> None:
    """Page 1 carries one block per line (a middle line has a block after it)
    and page 2 is blank."""
    doc = fitz.open()
    doc.new_page(width=360, height=240)
    doc.new_page(width=360, height=240)
    for index, text in enumerate(lines):
        doc[0].insert_text(
            fitz.Point(40, 60 + 50 * index), text, fontsize=16, fontname="helv", color=(0, 0, 0)
        )
    doc.save(path)
    doc.close()


def _move_line(model: PDFModel, controller: PDFController, line_index: int) -> str:
    model.set_text_target_mode("run")
    hit = model.get_text_info_at_point(1, fitz.Point(60, 56 + 50 * line_index))
    assert hit is not None
    controller.move_text_across_pages(
        source_page=1,
        source_rect=fitz.Rect(hit.target_bbox),
        destination_page=2,
        destination_rect=fitz.Rect(60, 60, 220, 110),
        new_text=hit.target_text,
        font=hit.font,
        size=float(hit.size),
        color=hit.color,
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode=hit.target_mode,
        allow_rebuild=True,
    )
    return hit.target_text


@pytest.mark.parametrize("line_index", [0, 1, 2])
def test_cross_page_move_of_a_line_with_blocks_after_it_succeeds(
    monkeypatch: pytest.MonkeyPatch, line_index: int
) -> None:
    """HIST-3: span ids are positional, so after the source block is deleted
    the next block is renumbered into the same id.  The deletion guard must
    judge by content, not by that reused id -- every non-last line used to end
    in an error dialog with no move and no history entry."""
    errors = _capture_errors(monkeypatch)
    lines = ["ALPHA_ONE", "MOVE_ME", "CHARLIE_THREE"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_multi_line.pdf"
        _make_multi_line_pdf(path, lines)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            controller = _make_controller(model)
            before_undo = model.command_manager.undo_count

            moved = _move_line(model, controller, line_index)

            assert errors == []
            assert _norm(moved) == _norm(lines[line_index])
            assert model.command_manager.undo_count == before_undo + 1
            page1 = _norm(model.doc[0].get_text("text"))
            page2 = _norm(model.doc[1].get_text("text"))
            for index, line in enumerate(lines):
                if index == line_index:
                    assert _norm(line) not in page1
                    assert _norm(line) in page2
                else:
                    assert _norm(line) in page1
                    assert _norm(line) not in page2

            model.command_manager.undo()
            page1_undo = _norm(model.doc[0].get_text("text"))
            assert all(_norm(line) in page1_undo for line in lines)
            assert not _norm(model.doc[1].get_text("text"))
        finally:
            model.close()


def test_cross_page_move_of_a_duplicated_line_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors = _capture_errors(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_duplicate_line.pdf"
        _make_multi_line_pdf(path, ["SAME_LINE", "SAME_LINE", "TAIL_LINE"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            controller = _make_controller(model)

            _move_line(model, controller, 0)

            assert errors == []
            assert model.doc[0].get_text("text").upper().count("SAME_LINE") == 1
            assert "same_line" in _norm(model.doc[1].get_text("text"))
        finally:
            model.close()


def test_cross_page_move_aborts_when_the_source_text_is_really_still_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard keeps its job: a source deletion that reports SUCCESS but
    removed nothing cancels the move and rolls back (no history entry)."""
    errors = _capture_errors(monkeypatch)
    lines = ["ALPHA_ONE", "MOVE_ME", "CHARLIE_THREE"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_noop_delete.pdf"
        _make_multi_line_pdf(path, lines)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            controller = _make_controller(model)
            monkeypatch.setattr(model, "edit_text", lambda *args, **kwargs: EditTextResult.SUCCESS)
            before_undo = model.command_manager.undo_count

            _move_line(model, controller, 1)

            assert errors and "原始文字刪除未完成" in errors[0]
            assert model.command_manager.undo_count == before_undo
            assert all(_norm(line) in _norm(model.doc[0].get_text("text")) for line in lines)
            assert not _norm(model.doc[1].get_text("text"))
        finally:
            model.close()


def test_cross_page_move_source_resolution_ranks_overlapping_candidates_by_text() -> None:
    """The ambiguous-candidate ranking used a model helper that does not exist
    (AttributeError); it must pick the run whose text matches the request."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_overlapping_runs.pdf"
        doc = fitz.open()
        doc.new_page(width=360, height=240)
        doc.new_page(width=360, height=240)
        doc[0].insert_text(fitz.Point(40, 60), "AAAA", fontsize=16, fontname="helv")
        doc[0].insert_text(fitz.Point(40, 60), "BBBB", fontsize=16, fontname="helv")
        doc.save(path)
        doc.close()
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            controller = _make_controller(model)
            runs = {run.text: run for run in model.block_manager.get_runs(0)}
            assert set(runs) == {"AAAA", "BBBB"}

            for wanted in ("AAAA", "BBBB"):
                resolved = controller._resolve_cross_page_move_source_span_id(
                    source_page=1,
                    source_rect=fitz.Rect(runs[wanted].bbox),
                    original_text=wanted,
                    target_span_id=None,
                )
                assert resolved == runs[wanted].span_id
        finally:
            model.close()


def test_cross_page_move_of_invisible_text_is_refused_not_made_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F17-COL-2/3 same class: a cross-page move re-creates the text as a plain
    text box on the destination page, which carries no render mode, colour
    space, transparency or layer.  Invisible (3 Tr) text would arrive visible:
    the move is refused before anything changes, with the paint-state
    sentence."""
    errors = _capture_errors(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cross_page_invisible.pdf"
        doc = fitz.open()
        doc.new_page(width=360, height=240)
        doc.new_page(width=360, height=240)
        doc[0].insert_text(fitz.Point(40, 60), "MOVE_ME", fontsize=16, fontname="helv", render_mode=3)
        doc[1].insert_text(
            fitz.Point(40, 160), "KEEP_PAGE_TWO", fontsize=16, fontname="helv", color=(0, 0, 0)
        )
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            controller = _make_controller(model)
            before_undo = model.command_manager.undo_count
            page2_before = [model.doc.xref_stream(x) for x in model.doc[1].get_contents()]

            moved = _move_line(model, controller, 0)

            assert "MOVE_ME" in moved
            assert model.command_manager.undo_count == before_undo
            assert "move_me" in _norm(model.doc[0].get_text("text"))
            assert "move_me" not in _norm(model.doc[1].get_text("text"))
            assert [model.doc.xref_stream(x) for x in model.doc[1].get_contents()] == page2_before
            assert errors and "顯示方式" in errors[-1], errors
        finally:
            model.close()
