"""Redo of a rebuild replays its after-snapshot; a high-fidelity redo never re-runs.

UI critique step 8 of plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md
(ui_spec section 3, rows g and h):

- A command whose first execute was a CONSENTED legacy rebuild (a tiered
  attempt that genuinely fell back, ``is_real_fallback_commit``) redoes by
  restoring the page snapshot captured right after that commit -- never by
  re-running ``model.edit_text`` (which re-runs legacy redact+reinsert and
  could re-prompt or land different bytes).
- A Tier 0/1 command whose reversal patch was not recorded refuses redo with
  ``STALE_PLAN`` and zero mutation -- never a re-prepare, never legacy.
- A rebuild whose after-snapshot could not be captured refuses the same way.

Synthetic Helvetica fixtures (shared with ``test_text_commit_no_silent_legacy``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_text_commit_no_silent_legacy as nsl  # noqa: E402

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    HIGH_FIDELITY_TIERS,
    CommitStatus,
    RejectReason,
    is_real_fallback_commit,
)


def _streams(model: PDFModel, page_index: int = 0) -> list[bytes]:
    page = model.doc[page_index]
    return [model.doc.xref_stream(x) for x in page.get_contents()]


def _command(model: PDFModel, new_text: str, **extra) -> EditTextCommand:
    block = nsl._block(model, nsl.TARGET)
    return EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(0),
        old_block_id=None,
        old_block_text=block.text,
        **extra,
    )


class _Forbidden:
    """Install AFTER the first execute: redo must reach neither."""

    def __init__(self, model: PDFModel, monkeypatch) -> None:
        self.calls: list[str] = []

        def _edit_text(*a, **k):
            self.calls.append("edit_text")
            raise AssertionError("redo re-ran model.edit_text")

        def _legacy(*a, **k):
            self.calls.append("legacy")
            raise AssertionError("redo re-ran the legacy engine")

        monkeypatch.setattr(model, "edit_text", _edit_text)
        monkeypatch.setattr(model, "_apply_redact_insert", _legacy)


@pytest.fixture
def rebuild_model(tmp_path: Path):
    model = nsl._open_model(nsl._write_pdf(tmp_path / "rebuild.pdf", nsl._tj_array_stream()))
    yield model
    model.close()


@pytest.fixture
def tier0_model(tmp_path: Path):
    model = nsl._open_model(nsl._write_pdf(tmp_path / "tier0.pdf", nsl._tier0_stream()))
    yield model
    model.close()


def _consented_rebuild(model: PDFModel, asked: list) -> EditTextCommand:
    cmd = _command(
        model,
        nsl.REPLACEMENT,
        confirm_fallback=lambda chain: asked.append(chain) or True,
        allow_rebuild=True,
    )
    model.command_manager.execute(cmd)
    assert cmd.result is EditTextResult.SUCCESS
    assert is_real_fallback_commit(cmd.outcome), cmd.outcome
    assert len(asked) == 1
    return cmd


def test_redo_of_a_consented_rebuild_restores_the_after_snapshot(
    rebuild_model: PDFModel, monkeypatch
) -> None:
    model = rebuild_model
    before = _streams(model)
    asked: list = []
    cmd = _consented_rebuild(model, asked)
    after = _streams(model)
    after_text = model.doc[0].get_text()
    after_protected = set(model.fidelity_protected_pages)
    assert after != before

    assert model.command_manager.undo() is True
    assert _streams(model) == before

    forbidden = _Forbidden(model, monkeypatch)
    assert model.command_manager.redo() is True
    assert forbidden.calls == []
    assert cmd.result is EditTextResult.SUCCESS
    assert len(asked) == 1, "redo must never ask again"
    assert _streams(model) == after
    assert model.doc[0].get_text() == after_text
    assert set(model.fidelity_protected_pages) == after_protected
    assert model.last_commit_outcome is cmd.outcome

    # The cycle stays exact both ways.
    assert model.command_manager.undo() is True
    assert _streams(model) == before
    assert model.command_manager.redo() is True
    assert _streams(model) == after
    assert forbidden.calls == []


def test_rebuild_redo_refuses_when_the_after_snapshot_was_not_captured(
    rebuild_model: PDFModel, monkeypatch
) -> None:
    model = rebuild_model

    def _no_capture(*a, **k):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(model, "_capture_page_snapshot_strict", _no_capture)
    cmd = _consented_rebuild(model, [])
    assert model.command_manager.undo() is True
    after_undo = _streams(model)
    forbidden = _Forbidden(model, monkeypatch)

    assert model.command_manager.redo() is False
    assert forbidden.calls == []
    assert cmd.result is EditTextResult.STALE_PLAN
    assert model.last_commit_outcome.status is CommitStatus.STALE_PLAN
    assert "legacy" not in model.last_commit_outcome.fallback_chain
    assert _streams(model) == after_undo
    assert model.command_manager.can_redo()


def test_redo_of_a_high_fidelity_command_without_a_reversal_refuses_stale_plan(
    tier0_model: PDFModel, monkeypatch
) -> None:
    model = tier0_model
    # Patched where the command USES it (``from ... import`` binds the name).
    monkeypatch.setattr("model.edit_commands.build_reversal_patchset", lambda *a, **k: None)
    cmd = _command(model, nsl.REPLACEMENT)
    model.command_manager.execute(cmd)
    assert cmd.result is EditTextResult.SUCCESS
    assert cmd.outcome.tier in HIGH_FIDELITY_TIERS
    assert cmd._tier0_forward_patchset is None

    assert model.command_manager.undo() is True
    after_undo = _streams(model)
    assert nsl.TARGET in model.doc[0].get_text()
    forbidden = _Forbidden(model, monkeypatch)

    assert model.command_manager.redo() is False
    assert forbidden.calls == []
    assert cmd.result is EditTextResult.STALE_PLAN
    outcome = model.last_commit_outcome
    assert outcome.status is CommitStatus.STALE_PLAN
    assert outcome.fallback_chain == (f"tier0:{RejectReason.STALE_PLAN}",)
    assert _streams(model) == after_undo
    assert model.command_manager.can_redo()


def test_rebuild_after_snapshot_keeps_live_annotation_parents(
    tmp_path: Path,
) -> None:
    """Guard: capturing the after-snapshot must not strip ``/P`` from the live
    page's annotations (``insert_pdf`` does that to its SOURCE document)."""
    path = tmp_path / "annot.pdf"
    doc = fitz.open()
    nsl._add_raw_page(doc, nsl._tj_array_stream())
    doc[0].add_text_annot((500, 60), "note")
    doc.save(str(path), garbage=0)
    doc.close()
    model = nsl._open_model(path)
    try:
        _consented_rebuild(model, [])
        page = model.doc[0]
        annots = list(page.annots())
        assert annots, "the fixture annotation must survive the rebuild"
        for annot in annots:
            kind, value = model.doc.xref_get_key(annot.xref, "P")
            assert kind == "xref" and value.startswith(f"{page.xref} "), (kind, value)
    finally:
        model.close()
