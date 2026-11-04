"""The conftest's synthetic test_files/1.pdf must be safe to create from two processes.

On CI test_files/ is absent, and with ``run_suite.py --parallel-lanes`` the pure job
and a Qt job import the conftest at the same moment (plans/CI-faster.md).  A direct
``doc.save(target)`` lets one process read a half-written PDF; the write therefore
goes to a per-process temp file that is renamed into place.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import fitz


def _conftest():
    return importlib.import_module("test_scripts.conftest")


def test_fixture_is_written_to_a_temp_file_then_renamed(tmp_path: Path, monkeypatch) -> None:
    cf = _conftest()
    monkeypatch.setattr(cf, "ROOT", tmp_path)
    saved: list[Path] = []
    real_save = fitz.Document.save

    def spy(self, filename, *args, **kwargs):
        saved.append(Path(filename))
        return real_save(self, filename, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "save", spy)
    cf._ensure_test_file_1_pdf()
    target = tmp_path / "test_files" / "1.pdf"
    assert target.is_file()
    assert len(saved) == 1 and saved[0] != target and saved[0].parent == target.parent
    assert sorted(p.name for p in target.parent.iterdir()) == ["1.pdf"], "temp file left behind"
    with fitz.open(target) as doc:
        assert "favorite" in doc[0].get_text()


def test_losing_the_rename_race_keeps_the_winner_and_cleans_up(tmp_path: Path, monkeypatch) -> None:
    cf = _conftest()
    monkeypatch.setattr(cf, "ROOT", tmp_path)
    target = tmp_path / "test_files" / "1.pdf"

    def other_process_won(src, dst):
        Path(dst).write_bytes(b"winner")  # the other process renamed first and holds it open
        raise PermissionError("in use")

    monkeypatch.setattr(os, "replace", other_process_won)
    cf._ensure_test_file_1_pdf()  # must not raise
    assert target.read_bytes() == b"winner"
    assert sorted(p.name for p in target.parent.iterdir()) == ["1.pdf"]


def test_a_failed_save_leaves_no_temp_file(tmp_path: Path, monkeypatch) -> None:
    cf = _conftest()
    monkeypatch.setattr(cf, "ROOT", tmp_path)

    def broken_save(self, filename, *args, **kwargs):
        Path(filename).write_bytes(b"partial")
        raise RuntimeError("disk full")

    monkeypatch.setattr(fitz.Document, "save", broken_save)
    try:
        cf._ensure_test_file_1_pdf()
    except RuntimeError:
        pass
    assert list((tmp_path / "test_files").iterdir()) == []


def test_an_existing_fixture_is_never_touched(tmp_path: Path, monkeypatch) -> None:
    cf = _conftest()
    monkeypatch.setattr(cf, "ROOT", tmp_path)
    target = tmp_path / "test_files" / "1.pdf"
    target.parent.mkdir()
    target.write_bytes(b"real fixture")
    cf._ensure_test_file_1_pdf()
    assert target.read_bytes() == b"real fixture"
