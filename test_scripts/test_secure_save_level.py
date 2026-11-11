"""Secure-save garbage level contract (owner design "fix B", 2026-11-11).

A latched session (page delete/move, TOC edit, metadata edit) saves at
``SECURE_SAVE_GARBAGE_LEVEL`` (1): ``test_secure_save_leakage.py`` measured no
leakage at level 1 and 4-23 s cost at levels 3/4.  Compaction (garbage=4) is the
explicit optimize-document action.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from model.edit_commands import SnapshotCommand
from model.pdf_model import SECURE_SAVE_GARBAGE_LEVEL, PDFModel, PdfOptimizeOptions
from model.pdf_optimizer import capture_optimize_source, save_optimized_copy_from_snapshot


def _make_pdf(path: Path, pages: int = 3) -> Path:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page(width=300, height=200).insert_text((30, 60), f"page {i + 1}", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def _spy_save_doc(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, bool]]:
    calls: list[tuple[int, bool]] = []
    original = PDFModel._save_doc

    def _spy(doc, target, *, garbage=0, incremental=False):
        calls.append((garbage, incremental))
        return original(doc, target, garbage=garbage, incremental=incremental)

    monkeypatch.setattr(PDFModel, "_save_doc", staticmethod(_spy))
    return calls


def test_secure_level_constant_is_one() -> None:
    assert SECURE_SAVE_GARBAGE_LEVEL == 1


def test_latched_save_as_new_path_never_runs_a_level_two_plus_pass(tmp_path, monkeypatch) -> None:
    source = _make_pdf(tmp_path / "src.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        assert model.delete_pages([2]) == [2]
        assert model.secure_save_required is True
        calls = _spy_save_doc(monkeypatch)
        model.save_as(str(tmp_path / "out.pdf"))
        # the user-visible save plus (at most) the detach copy, both level 1, never incremental
        assert 1 <= len(calls) <= 2
        assert all(g == SECURE_SAVE_GARBAGE_LEVEL and not inc for g, inc in calls), calls
        assert model.secure_save_required is True  # the latch is never cleared by a save
    finally:
        model.close_all_sessions()
    check = fitz.open(tmp_path / "out.pdf")
    assert check.page_count == 2
    check.close()


def test_latched_save_over_open_file_uses_the_secure_level(tmp_path, monkeypatch) -> None:
    source = _make_pdf(tmp_path / "src.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        assert model.delete_pages([2]) == [2]
        calls = _spy_save_doc(monkeypatch)
        model.save_as(str(source))
        assert calls and all(g == SECURE_SAVE_GARBAGE_LEVEL for g, _ in calls), calls
    finally:
        model.close_all_sessions()
    check = fitz.open(source)
    assert check.page_count == 2
    check.close()


def test_undo_after_a_latched_save_as_still_works(tmp_path) -> None:
    source = _make_pdf(tmp_path / "src.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        before = model._capture_doc_snapshot()
        assert model.delete_pages([2]) == [2]
        after = model._capture_doc_snapshot()
        model.command_manager.record(
            SnapshotCommand(
                model=model,
                command_type="delete_pages",
                affected_pages=[2],
                before_bytes=before,
                after_bytes=after,
                description="delete page 2",
            )
        )
        model.save_as(str(tmp_path / "out.pdf"))
        assert len(model.doc) == 2
        model.command_manager.undo()
        assert len(model.doc) == 3
    finally:
        model.close_all_sessions()


def test_optimize_of_a_latched_session_at_level_four_compacts_at_garbage_four(tmp_path, monkeypatch) -> None:
    # Duplicate streams (same bytes, different objects): level 1 keeps them,
    # level 4 merges them.
    doc = fitz.open()
    blob = b"0 0 m 10 10 l S\n" * 400
    for _ in range(3):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 20), "x")
        extra = doc.get_new_xref()
        doc.update_object(extra, "<<>>")
        doc.update_stream(extra, blob)
        old = page.get_contents()[0]
        doc.xref_set_key(page.xref, "Contents", f"[{old} 0 R {extra} 0 R]")
    source = tmp_path / "dup.pdf"
    doc.save(source)
    plain = doc.tobytes(garbage=1)
    doc.close()
    out = tmp_path / "opt.pdf"
    observed: list[dict] = []
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source))
        model._sessions_by_id[sid].secure_save_required = True
        snapshot = capture_optimize_source(model, sid)
        original = model._fast_save_kwargs

        def _capture(options):
            kwargs = original(options)
            observed.append(kwargs)  # the optimizer overrides garbage on this same dict
            return kwargs

        monkeypatch.setattr(model, "_fast_save_kwargs", _capture)
        save_optimized_copy_from_snapshot(model, snapshot, str(out), PdfOptimizeOptions(optimize_images=False, garbage_level=4))
    finally:
        model.close_all_sessions()
    assert [k["garbage"] for k in observed] == [4]
    assert out.stat().st_size <= len(plain)


@pytest.mark.parametrize("target", ["same", "new"])
def test_latched_save_keeps_the_xref_epoch(tmp_path, target) -> None:
    # Level 1 keeps the numbering, so retained page snapshots stay valid: a
    # latched Ctrl+S onto the open file must not bump the epoch (the reopen
    # assigns a fresh one; the save restores it, as the non-secure path does).
    source = _make_pdf(tmp_path / "src.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        assert model.delete_pages([2]) == [2]
        assert model.secure_save_required is True
        before = model.xref_epoch
        model.save_as(str(source if target == "same" else tmp_path / "out.pdf"))
        assert model.xref_epoch == before
    finally:
        model.close_all_sessions()
