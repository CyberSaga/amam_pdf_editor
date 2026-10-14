from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import fitz
import pytest

from model.pdf_model import PDFModel


CANARY = b"DELETED-PERSISTENCE-CANARY-74091"


def _make_orphaned_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), CANARY.decode("ascii"), fontsize=12)
    doc.save(path)
    doc.close()


def _make_encrypted_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page().insert_text((30, 60), "ENCRYPTED SOURCE")
    doc.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
        permissions=fitz.PDF_PERM_PRINT,
    )
    doc.close()


def _redact_canary_without_gc(model: PDFModel) -> None:
    page = model.doc[0]
    page.add_redact_annot(fitz.Rect(20, 35, 290, 75))
    page.apply_redactions()
    assert CANARY.decode("ascii") not in page.get_text("text")


def _contains_canary_anywhere(path: Path) -> bool:
    doc = fitz.open(path)
    try:
        for xref in range(1, doc.xref_length()):
            for reader in (doc.xref_stream, doc.xref_stream_raw):
                try:
                    data = reader(xref)
                except Exception:
                    data = None
                if data and CANARY in data:
                    return True
            try:
                if CANARY.decode("latin-1") in doc.xref_object(xref):
                    return True
            except Exception:
                pass
        return False
    finally:
        doc.close()


def test_secure_save_forces_full_gc_and_never_incremental(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "saved.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        _redact_canary_without_gc(model)
        model.secure_save_required = True

        calls: list[tuple[int, bool]] = []
        original = model._save_doc

        def _spy(doc, target, *, garbage=0, incremental=False):
            calls.append((garbage, incremental))
            return original(doc, target, garbage=garbage, incremental=incremental)

        monkeypatch.setattr(model, "_save_doc", _spy)
        model.save_as(str(output))

        assert calls and all(garbage == 4 and not incremental for garbage, incremental in calls)
        assert not _contains_canary_anywhere(output)
        assert model.secure_save_required is True
    finally:
        model.close()


def test_secure_overwrite_failure_preserves_existing_destination(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    _make_orphaned_pdf(source)
    destination.write_bytes(b"ORIGINAL-DESTINATION")

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.secure_save_required = True

        def _fail_replace(_src, _dst):
            raise OSError("injected atomic replace failure")

        monkeypatch.setattr("model.pdf_model.os.replace", _fail_replace)
        with pytest.raises(OSError, match="atomic replace failure"):
            model.save_as(str(destination))

        assert destination.read_bytes() == b"ORIGINAL-DESTINATION"
        assert model.doc is not None and not model.doc.is_closed
    finally:
        model.close()


def test_secure_print_snapshot_prunes_deleted_orphans(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    snapshot = tmp_path / "print.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        _redact_canary_without_gc(model)
        model.secure_save_required = True
        model.build_print_snapshot(snapshot)
        assert not _contains_canary_anywhere(snapshot)
    finally:
        model.close()


def test_secure_print_snapshot_forces_garbage_four(tmp_path: Path, monkeypatch) -> None:
    """The prune is garbage=4, but it runs on a clone: the LIVE handle is never
    serialized with garbage >= 2 (that renumbers it and strands undo; DS-1)."""
    source = tmp_path / "source.pdf"
    snapshot = tmp_path / "print.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.secure_save_required = True
        live_calls: list[int | None] = []
        original = model.doc.save

        def _spy(target, *args, **kwargs):
            live_calls.append(kwargs.get("garbage"))
            return original(target, *args, **kwargs)

        monkeypatch.setattr(model.doc, "save", _spy)
        clone_calls: list[int | None] = []
        real_save_doc = PDFModel._save_doc

        def _save_doc_spy(doc, target, *, garbage=0, incremental=False):
            if doc is not model.doc:
                clone_calls.append(garbage)
            return real_save_doc(doc, target, garbage=garbage, incremental=incremental)

        monkeypatch.setattr(PDFModel, "_save_doc", staticmethod(_save_doc_spy))
        model.build_print_snapshot(snapshot)
        assert clone_calls == [4]
        assert all((g or 0) < 2 for g in live_calls)
    finally:
        model.close()


def test_pdf_export_uses_sanitized_serialization_after_delete(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "export.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        _redact_canary_without_gc(model)
        model.secure_save_required = True
        model.export_pages([1], str(output), as_image=False)
        assert not _contains_canary_anywhere(output)
    finally:
        model.close()


def test_periodic_edit_maintenance_keeps_light_cleanup_but_never_full_gc(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    _make_orphaned_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.pending_edits = [{"page_idx": 0, "rect": fitz.Rect(0, 0, 10, 10)}]
        model.edit_count = 20
        calls: list[int] = []
        monkeypatch.setattr(
            model,
            "_roundtrip_live_doc",
            lambda **kwargs: calls.append(int(kwargs["garbage"])),
        )

        model._maybe_garbage_collect()

        assert calls == []
        assert model.pending_edits == []
    finally:
        model.close()


@pytest.mark.parametrize("secure", [False, True])
def test_watermark_save_preserves_encryption_and_user_role(
    tmp_path: Path, secure: bool
) -> None:
    source = tmp_path / "encrypted.pdf"
    output = tmp_path / "watermarked.pdf"
    _make_encrypted_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source), password="user-secret")
        model.tools.watermark.add_watermark([1], "CONFIDENTIAL")
        model.secure_save_required = secure
        model.save_as(str(output))
    finally:
        model.close()

    reopened = fitz.open(output)
    try:
        assert reopened.needs_pass
        assert reopened.authenticate("user-secret") == 2
        assert reopened.permissions != -4
    finally:
        reopened.close()


def test_worker_snapshot_before_edit_does_not_corrupt_later_encrypted_save(
    tmp_path: Path,
) -> None:
    """capture_worker_snapshot_bytes() decrypts the live doc's content for
    background renderers on every page/thumbnail render. Calling
    ``self.doc.tobytes(encryption=NONE)`` directly on the *live* authenticated
    handle silently corrupts its internal crypt state (a real PyMuPDF 1.27.1
    AES-256 quirk): a subsequent ``encryption=KEEP`` save on that same handle
    then writes a file whose content streams no longer decrypt (blank pages on
    reopen), even though the save itself reports success and needs_pass/
    is_encrypted look normal. The snapshot must be taken from an isolated
    clone, never the live handle, so ordinary rendering can never poison a
    later save."""
    source = tmp_path / "encrypted.pdf"
    _make_encrypted_pdf(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source), password="user-secret")

        # Simulate the render/thumbnail workers reading a snapshot before any edit.
        snapshot_before = model.capture_worker_snapshot_bytes()
        before_doc = fitz.open("pdf", snapshot_before)
        assert before_doc[0].get_text("text").strip() == "ENCRYPTED SOURCE"
        before_doc.close()

        model.set_editable_metadata({"title": "Edited", "author": "", "subject": "", "keywords": ""})
        model.save_as(str(source))
    finally:
        model.close()

    reopened = PDFModel()
    try:
        reopened.open_pdf(str(source), password="user-secret")
        assert reopened.doc[0].get_text("text").strip() == "ENCRYPTED SOURCE"
        post_save_snapshot = reopened.capture_worker_snapshot_bytes()
        rendered = fitz.open("pdf", post_save_snapshot)
        assert rendered[0].get_text("text").strip() == "ENCRYPTED SOURCE"
        rendered.close()
    finally:
        reopened.close()


def test_page_delete_sets_secure_latch_and_rolls_back_whole_batch_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "pages.pdf"
    doc = fitz.open()
    for text in ("PAGE ONE", "PAGE TWO", "PAGE THREE"):
        doc.new_page().insert_text((30, 60), text)
    doc.save(source)
    doc.close()

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        original = fitz.Document.delete_page
        calls = 0

        def _fail_second(target, page_index):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected page-delete failure")
            return original(target, page_index)

        monkeypatch.setattr(fitz.Document, "delete_page", _fail_second)
        with pytest.raises(RuntimeError, match="page-delete failure"):
            model.delete_pages([1, 2])

        assert len(model.doc) == 3
        assert [model.doc[i].get_text().strip() for i in range(3)] == [
            "PAGE ONE",
            "PAGE TWO",
            "PAGE THREE",
        ]
        assert model.secure_save_required is False

        monkeypatch.setattr(fitz.Document, "delete_page", original)
        assert model.delete_pages([2]) == [2]
        assert model.secure_save_required is True
    finally:
        model.close()


# --- F13-ENV-1: a user-initiated save never depends on the model temp dir -------
#
# Ctrl+S over the open file stages a recovery / ``save_`` copy in the model's
# private temp dir.  A temp cleaner that removed the idle folder, or a TEMP deep
# enough that ``tmpXXXX\recover_<32hex>.pdf`` passes MAX_PATH (Windows default,
# LongPathsEnabled=0), made Ctrl+S fail with an error naming no path while the
# user's own folder was fine, and the block persisted for the session.

_DEEP_TEMP_MIN = 215  # temp-dir length at which ``recover_<32hex>.pdf`` reaches 260


def _break_model_temp_dir(model: PDFModel, tmp_path: Path, how: str) -> None:
    if how == "gone":
        shutil.rmtree(model.temp_dir.name)
        return
    if os.name != "nt":
        pytest.skip("MAX_PATH is a Windows limit")
    parent = tmp_path / "deep"
    while len(str(parent)) + len(os.sep) + len("tmpXXXXXXXX") < _DEEP_TEMP_MIN + 6:
        parent = parent / ("d" * min(40, _DEEP_TEMP_MIN + 6 - len(str(parent))))
    parent.mkdir(parents=True, exist_ok=True)
    old = model.temp_dir
    model.temp_dir = tempfile.TemporaryDirectory(dir=str(parent))
    old.cleanup()
    assert len(model.temp_dir.name) >= _DEEP_TEMP_MIN


def _make_three_pages(path: Path) -> None:
    doc = fitz.open()
    for index in range(3):
        doc.new_page().insert_text((72, 100), f"page {index + 1} text", fontsize=12)
    doc.save(path)
    doc.close()


def _page_count(path: Path) -> int:
    doc = fitz.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def _files_in(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.is_file())


@pytest.mark.parametrize("how", ["gone", "deep"])
def test_secure_ctrl_s_survives_a_missing_or_too_deep_model_temp_dir(
    tmp_path: Path, how: str
) -> None:
    target = tmp_path / "secure.pdf"
    _make_three_pages(target)
    model = PDFModel()
    try:
        model.open_pdf(str(target))
        assert model.delete_pages([2]) == [2]
        assert model.secure_save_required is True
        _break_model_temp_dir(model, tmp_path, how)

        model.save_as(str(target))  # Ctrl+S: the open file is the target
        assert _page_count(target) == 2
        assert model.doc is not None and model.doc.page_count == 2
        assert model.secure_save_required is True

        model.save_as(str(target))  # the block must not persist either
        assert _page_count(target) == 2
    finally:
        model.close()
    assert _files_in(tmp_path) == ["secure.pdf"]


@pytest.mark.parametrize("how", ["gone", "deep"])
def test_plain_full_ctrl_s_survives_a_missing_or_too_deep_model_temp_dir(
    tmp_path: Path, monkeypatch, how: str
) -> None:
    target = tmp_path / "plain.pdf"
    _make_three_pages(target)
    model = PDFModel()
    try:
        model.open_pdf(str(target))
        model.doc[0].add_highlight_annot(fitz.Rect(72, 88, 160, 104))
        # What a rebuild + undo leaves: orphans force the pruned full save.
        monkeypatch.setattr(model, "_session_orphans_block_incremental", lambda: True)
        assert model.secure_save_required is False
        _break_model_temp_dir(model, tmp_path, how)

        model.save_as(str(target))
        reopened = fitz.open(target)
        try:
            assert reopened.page_count == 3
            assert len(list(reopened[0].annots() or [])) == 1
        finally:
            reopened.close()
        assert model.doc is not None and model.doc.page_count == 3
    finally:
        model.close()
    assert _files_in(tmp_path) == ["plain.pdf"]


@pytest.mark.parametrize("secure", [False, True])
@pytest.mark.parametrize("how", ["gone", "deep"])
def test_watermark_ctrl_s_survives_a_missing_or_too_deep_model_temp_dir(
    tmp_path: Path, how: str, secure: bool
) -> None:
    target = tmp_path / "wm.pdf"
    _make_three_pages(target)
    model = PDFModel()
    try:
        model.open_pdf(str(target))
        model.tools.watermark.add_watermark([1], "CONFIDENTIAL")
        model.secure_save_required = secure
        _break_model_temp_dir(model, tmp_path, how)

        model.save_as(str(target))
        assert _page_count(target) == 3
        assert model.doc is not None and model.doc.page_count == 3
    finally:
        model.close()
    assert _files_in(tmp_path) == ["wm.pdf"]


@pytest.mark.parametrize("how", ["gone", "deep"])
def test_save_as_to_a_new_name_detaches_after_the_temp_dir_is_lost(
    tmp_path: Path, how: str
) -> None:
    """The ``live_`` private copy of the detach step needs the temp dir too."""
    source = tmp_path / "src.pdf"
    _make_three_pages(source)
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        model.doc[0].add_highlight_annot(fitz.Rect(72, 88, 160, 104))
        _break_model_temp_dir(model, tmp_path, how)

        copy = tmp_path / "copy.pdf"
        model.save_as(str(copy))
        assert _page_count(copy) == 3
        # the session left src.pdf: it holds no handle on it any more
        assert model.doc is not None
        assert model._backing_file(model.doc) != source.resolve()
    finally:
        model.close()


def test_private_temp_file_recreates_the_vanished_dir_and_uses_extended_form(
    tmp_path: Path,
) -> None:
    model = PDFModel()
    try:
        shutil.rmtree(model.temp_dir.name)
        path = model.private_temp_file("recover")
        assert path.parent.is_dir()
        assert path.name.startswith("recover_") and path.suffix == ".pdf"
        assert model.private_temp_file("recover") != path  # unique every call
        if os.name == "nt":
            _break_model_temp_dir(model, tmp_path, "deep")
            deep = model.private_temp_file("recover")
            assert len(str(deep)) > 259 and str(deep).startswith("\\" * 2 + "?" + "\\")
            blank = fitz.open()
            blank.new_page()
            blank.save(str(deep))  # MuPDF writes it, plain Python file APIs see it
            blank.close()
            assert deep.read_bytes().startswith(b"%PDF")
            opened = fitz.open(str(deep))
            try:
                # still recognised as one of the model's own copies (retired and
                # deleted with the session) although only the long name carries
                # the extended-length prefix
                assert model._model_temp_file_of(opened) is not None
            finally:
                opened.close()
    finally:
        model.close()
