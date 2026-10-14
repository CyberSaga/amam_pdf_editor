"""OD-FS1-LOCK: a deny-write share lock on the session's file (owner decision for F10-FS-1, RAM half).

MuPDF opens the PDF with a share mode that lets another program rewrite it in
place; a file-backed live document then reads the foreign bytes and the
unsaved edits vanish before any save.  On Windows the model now holds a second
handle shared READ-only for the whole session: other writers (in-place
``open('r+b')``, ``os.replace`` over it, rename, delete) fail while the
session is open and succeed after it closes; the app's own saves release it
around the write and take it back after.  Off Windows nothing changes.
"""

from __future__ import annotations

import gc
import logging
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from model.pdf_model import PDFModel

win32_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows share-mode lock")


def _make_pdf(path: Path, label: str = "hello", pages: int = 3) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{label} p{i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def _texts(doc: fitz.Document) -> list[str]:
    return [doc[i].get_text().strip() for i in range(len(doc))]


def _first_page_text(path: Path) -> str:
    """Page-1 text of the file at ``path``, read from its bytes (no handle kept on it)."""
    doc = fitz.open("pdf", path.read_bytes())
    try:
        return doc[0].get_text()
    finally:
        doc.close()


def _write_blocked(path: Path) -> bool:
    """True when an in-place writer (``open('r+b')``) is refused; writes nothing."""
    try:
        with open(path, "r+b"):
            pass
    except PermissionError:
        return True
    return False


def _replace_blocked(path: Path, scratch: Path) -> bool:
    """True when ``os.replace`` of a same-bytes copy over ``path`` is refused."""
    copy = scratch / f"replacement_{path.name}"
    shutil.copyfile(path, copy)
    try:
        os.replace(copy, path)
    except PermissionError:
        copy.unlink(missing_ok=True)
        return True
    return False


def _released(path: Path) -> bool:
    gc.collect()  # PyMuPDF cycle garbage can pin a MuPDF handle (MBT-1), not the lock
    return not _write_blocked(path)


def _open_model(path: Path) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def _edit(model: PDFModel, text: str = "MY EDIT") -> None:
    model.doc[0].insert_text((72, 120), text)
    model.edit_count += 1


# --------------------------------------------------------------------------- core


def _go_memory_backed(model: PDFModel) -> None:
    """The live handle stops reading the file (as after a snapshot undo or a compacted open)."""
    model._roundtrip_live_doc(garbage=0, deflate=False)
    gc.collect()
    assert model._backing_file(model.doc) is None


@win32_only
@pytest.mark.parametrize("backing", ["file", "memory"])
def test_foreign_writers_are_refused_while_the_session_is_open_and_allowed_after_close(
    tmp_path, backing
) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open_model(src)
    try:
        if backing == "memory":
            _go_memory_backed(model)
        assert _write_blocked(src)
        assert _replace_blocked(src, tmp_path)
        with pytest.raises(PermissionError):
            os.rename(src, tmp_path / "renamed.pdf")
        with pytest.raises(PermissionError):
            os.remove(src)
        # Readers still work (other viewers, the app's own reopen).
        assert src.read_bytes().startswith(b"%PDF")
        probe = fitz.open(str(src))
        assert len(probe) == 3
        probe.close()
    finally:
        model.close()
    assert _released(src)
    assert not _replace_blocked(src, tmp_path)


@win32_only
def test_an_external_process_cannot_rewrite_the_file_and_the_session_keeps_its_content(tmp_path) -> None:
    """The round-10 F10-FS-1 RAM repro: a foreign rewrite replaced what the live session showed."""
    src = _make_pdf(tmp_path / "doc.pdf")
    ext = _make_pdf(tmp_path / "ext.pdf", "EXTERNAL", 9)
    model = _open_model(src)
    try:
        _edit(model)
        before = _texts(model.doc)
        script = (
            "import sys\n"
            "data = open(sys.argv[1], 'rb').read()\n"
            "try:\n"
            "    f = open(sys.argv[2], 'r+b')\n"
            "except PermissionError:\n"
            "    sys.exit(3)\n"
            "f.write(data); f.truncate(); f.close()\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(ext), str(src)], capture_output=True, timeout=60
        )
        assert result.returncode == 3, result.stderr
        assert _texts(model.doc) == before
        assert "MY EDIT" in model.doc[0].get_text()
    finally:
        model.close()


@win32_only
def test_close_session_releases_the_file_and_other_sessions_keep_theirs(tmp_path) -> None:
    a = _make_pdf(tmp_path / "a.pdf")
    b = _make_pdf(tmp_path / "b.pdf")
    model = PDFModel()
    try:
        sid_a = model.open_pdf(str(a))
        model.open_pdf(str(b), append=True)
        assert _write_blocked(a) and _write_blocked(b)
        model.close_session(sid_a)
        assert _released(a)
        assert _write_blocked(b)
    finally:
        model.close()
    assert _released(b)


# --------------------------------------------------------------------------- the app's own writes


@win32_only
@pytest.mark.parametrize("mode", ["incremental", "full", "secure"])
def test_ctrl_s_still_writes_the_locked_file_and_the_lock_comes_back(tmp_path, mode) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open_model(src)
    try:
        if mode == "full":
            model.use_incremental_save = False
        if mode == "secure":
            model.secure_save_required = True
        _edit(model)
        model.save_as(str(src))
        assert model.has_unsaved_changes() is False
        assert _write_blocked(src), "the lock must be taken back after the app's own save"
        assert "MY EDIT" in _first_page_text(src)
        # A second save on the same session works too (handle renewed / reopened).
        _edit(model, "SECOND")
        model.save_as(str(src))
        assert _write_blocked(src)
    finally:
        model.close()
    assert _released(src)


@win32_only
@pytest.mark.parametrize("mode", ["full", "secure", "save_as_elsewhere"])
def test_the_file_stays_locked_while_the_document_is_serialized(tmp_path, monkeypatch, mode) -> None:
    """Only the write itself releases the lock: serializing a large document can take
    seconds, and a file-backed live handle reading foreign bytes then is the bug."""
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open_model(src)
    seen: list[bool] = []
    real_save_doc = PDFModel._save_doc

    def spying_save_doc(doc, target, *args, **kwargs):
        if not kwargs.get("incremental"):
            seen.append(_write_blocked(src))
        return real_save_doc(doc, target, *args, **kwargs)

    monkeypatch.setattr(PDFModel, "_save_doc", staticmethod(spying_save_doc))
    try:
        model.use_incremental_save = False
        if mode == "secure":
            model.secure_save_required = True
        _edit(model)
        model.save_as(str(tmp_path / "other.pdf") if mode == "save_as_elsewhere" else str(src))
        assert seen and all(seen), seen
    finally:
        model.close()


@win32_only
def test_save_as_moves_the_lock_to_the_new_file(tmp_path) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    dst = tmp_path / "copy.pdf"
    model = _open_model(src)
    try:
        _edit(model)
        model.save_as(str(dst))
        assert _write_blocked(dst)
        assert _released(src), "the file the session left must be free"
        _edit(model, "AGAIN")
        model.save_as(str(dst))  # Ctrl+S on the new file
        assert _write_blocked(dst)
    finally:
        model.close()
    assert _released(dst)


@win32_only
def test_save_as_onto_an_existing_other_file_overwrites_it_and_locks_it(tmp_path) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    dst = _make_pdf(tmp_path / "old.pdf", "OLD")
    model = _open_model(src)
    try:
        _edit(model)
        model.save_as(str(dst))
        assert "MY EDIT" in _first_page_text(dst)
        assert _write_blocked(dst)
        assert _released(src)
    finally:
        model.close()


@win32_only
def test_close_with_save_writes_then_releases(tmp_path) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open_model(src)
    try:
        sid = model.get_active_session_id()
        _edit(model)
        model.save_session_as(sid, str(src))
        assert _write_blocked(src)
        model.close_session(sid)
        assert _released(src)
        assert "MY EDIT" in _first_page_text(src)
    finally:
        model.close()


@win32_only
def test_the_app_can_replace_a_path_this_process_locks(tmp_path) -> None:
    """Every staged install goes through ``replace_file``: it must suspend the lock."""
    from utils.file_share_lock import acquire
    from utils.path_staging import replace_file

    target = _make_pdf(tmp_path / "doc.pdf")
    stage = _make_pdf(tmp_path / "stage.pdf", "STAGED")
    token = acquire(target)
    try:
        assert _write_blocked(target)
        replace_file(stage, target)
        assert "STAGED" in _first_page_text(target)
        assert _write_blocked(target), "the lock must be re-taken on the installed file"
    finally:
        token.release()
    assert _released(target)


# --------------------------------------------------------------------------- failure paths


@win32_only
def test_a_failed_save_takes_the_lock_back(tmp_path, monkeypatch) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open_model(src)
    try:
        _edit(model)

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(model, "_save_as_unchecked", boom)
        with pytest.raises(OSError):
            model.save_as(str(src))
        assert _write_blocked(src)
        monkeypatch.undo()
        model.save_as(str(src))
        assert _write_blocked(src)
    finally:
        model.close()
    assert _released(src)


@win32_only
def test_a_failed_install_rebinds_and_keeps_the_lock(tmp_path, monkeypatch) -> None:
    import utils.path_staging as path_staging

    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open_model(src)
    try:
        model.use_incremental_save = False
        _edit(model)
        real_replace = os.replace

        def failing_replace(a, b):
            if Path(b).name == src.name:
                raise PermissionError(13, "simulated", str(b))
            return real_replace(a, b)

        monkeypatch.setattr(path_staging.os, "replace", failing_replace)
        with pytest.raises(PermissionError):
            model.save_as(str(src))
        monkeypatch.undo()
        assert "MY EDIT" in model.doc[0].get_text()
        assert _write_blocked(src)
        model.save_as(str(src))
        assert _write_blocked(src)
    finally:
        model.close()
    assert _released(src)


@win32_only
def test_a_refused_open_never_keeps_the_file_locked(tmp_path) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    model = PDFModel()
    try:
        def refuse() -> None:
            raise RuntimeError("cancelled")

        with pytest.raises(RuntimeError):
            model.open_pdf(str(src), before_activate=refuse)
        assert _released(src)

        enc = tmp_path / "enc.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "secret")
        doc.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="own")
        doc.close()
        with pytest.raises(RuntimeError):
            model.open_pdf(str(enc))
        with pytest.raises(RuntimeError):
            model.open_pdf(str(enc), password="wrong")
        assert _released(enc)
        model.open_pdf(str(enc), password="pw")
        assert _write_blocked(enc)
    finally:
        model.close()
    assert _released(enc)


@win32_only
def test_replace_open_of_the_same_file_keeps_it_locked(tmp_path) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    model = _open_model(src)
    try:
        model.open_pdf(str(src))  # replace-open: old session closed, new one opened
        assert _write_blocked(src)
    finally:
        model.close()
    assert _released(src)


# --------------------------------------------------------------------------- multi-window / transfer


@win32_only
def test_two_windows_on_the_same_file_both_open_and_release_independently(tmp_path) -> None:
    src = _make_pdf(tmp_path / "doc.pdf")
    first = _open_model(src)
    second = PDFModel()
    try:
        second.open_pdf(str(src))
        assert _write_blocked(src)
        first.close()
        assert _write_blocked(src), "the other window still holds the file"
        second.close()
        assert _released(src)
    finally:
        first.close()
        second.close()


@win32_only
def test_session_transfer_keeps_the_file_locked_until_the_last_window_closes_it(tmp_path) -> None:
    from controller.session_transfer import SessionTransferPayload

    src = _make_pdf(tmp_path / "doc.pdf")
    source = _open_model(src)
    destination = PDFModel()
    try:
        _edit(source)
        payload = SessionTransferPayload.from_model(
            source, source.get_active_session_id(), current_page=0, scale=1.0, color_profile="srgb"
        )
        destination.import_session_transfer(payload)
        source.close_session(source.get_active_session_id())
        assert _write_blocked(src), "the detached window owns the file now"
        destination.save_as(str(src))
        assert _write_blocked(src)
        destination.close()
        assert _released(src)
    finally:
        source.close()
        destination.close()


# --------------------------------------------------------------------------- degrade


@win32_only
def test_read_only_file_opens_locked(tmp_path) -> None:
    """A read-only file can still be renamed on Windows - unless the session holds it."""
    src = _make_pdf(tmp_path / "ro.pdf")
    os.chmod(src, stat.S_IREAD)
    moved = tmp_path / "moved.pdf"
    model = PDFModel()
    try:
        model.open_pdf(str(src))
        _go_memory_backed(model)
        assert len(model.doc) == 3
        with pytest.raises(PermissionError):
            os.rename(src, moved)
    finally:
        model.close()
    gc.collect()
    os.rename(src, moved)
    os.chmod(moved, stat.S_IREAD | stat.S_IWRITE)


def test_a_lock_that_cannot_be_taken_degrades_to_the_old_behaviour(tmp_path, monkeypatch, caplog) -> None:
    """Network share / file already opened for writing elsewhere: open anyway, log it."""
    import utils.file_share_lock as file_share_lock

    def refuse(path: str) -> int:
        raise OSError(32, "The process cannot access the file", path)

    monkeypatch.setattr(file_share_lock, "_os_open", refuse)
    src = _make_pdf(tmp_path / "doc.pdf")
    model = PDFModel()
    try:
        with caplog.at_level(logging.WARNING, logger="utils.file_share_lock"):
            model.open_pdf(str(src))
        assert len(model.doc) == 3
        if sys.platform == "win32":
            assert any(str(src) in r.getMessage() for r in caplog.records)
        assert not _write_blocked(src)
        # The F10-FS-1 fingerprint gate is the defence in that mode.
        with open(src, "r+b") as handle:
            handle.write(_make_pdf(tmp_path / "ext.pdf", "EXTERNAL").read_bytes())
            handle.truncate()
        _edit(model)
        from model.pdf_model import SourceChangedOnDiskError

        with pytest.raises(SourceChangedOnDiskError):
            model.save_as(str(src))
    finally:
        model.close()


def test_non_windows_is_a_no_op(tmp_path, monkeypatch) -> None:
    import utils.file_share_lock as file_share_lock

    calls: list[str] = []

    def must_not_run(path: str) -> int:
        calls.append(path)
        raise AssertionError("no OS lock off Windows")

    monkeypatch.setattr(file_share_lock, "platform_supported", lambda: False)
    monkeypatch.setattr(file_share_lock, "_os_open", must_not_run)
    src = _make_pdf(tmp_path / "doc.pdf")
    token = file_share_lock.acquire(src)
    assert token.held is False
    with file_share_lock.suspended(src):
        pass
    token.release()
    model = _open_model(src)
    try:
        assert not _write_blocked(src)
        _edit(model)
        model.save_as(str(src))
    finally:
        model.close()
    assert calls == []


@win32_only
def test_lock_tokens_are_counted_and_suspension_is_reentrant(tmp_path) -> None:
    import utils.file_share_lock as file_share_lock

    src = _make_pdf(tmp_path / "doc.pdf")
    first = file_share_lock.acquire(src)
    second = file_share_lock.acquire(str(src).upper())
    try:
        assert first.held and second.held
        assert _write_blocked(src)
        with file_share_lock.suspended(src):
            with file_share_lock.suspended(src):
                assert not _write_blocked(src)
            assert not _write_blocked(src)
        assert _write_blocked(src)
        first.release()
        first.release()  # idempotent
        assert _write_blocked(src)
    finally:
        first.release()
        second.release()
    assert not _write_blocked(src)


@win32_only
def test_a_garbage_collected_claim_never_blocks_the_collecting_thread(tmp_path) -> None:
    """A finalizer runs in whatever thread triggers GC (maybe one holding a logging
    or Qt lock): it must not wait for the registry mutex, or two threads deadlock."""
    import threading

    import utils.file_share_lock as file_share_lock

    src = _make_pdf(tmp_path / "doc.pdf")
    holder_ready = threading.Event()
    let_go = threading.Event()

    def hold_mutex() -> None:
        with file_share_lock._mutex:
            holder_ready.set()
            let_go.wait(30)

    holder = threading.Thread(target=hold_mutex)
    box: dict[str, object] = {"token": file_share_lock.acquire(src)}
    assert _write_blocked(src)
    holder.start()
    assert holder_ready.wait(10)

    def drop_by_gc() -> None:
        box.pop("token")
        gc.collect()

    collector = threading.Thread(target=drop_by_gc)
    try:
        collector.start()
        collector.join(5)
        blocked = collector.is_alive()
    finally:
        let_go.set()
        holder.join(10)
        collector.join(10)
    assert not blocked, "the GC-time release waited for the registry mutex"
    assert not file_share_lock.is_locked(src)  # the queued drop is applied on the next call
    assert not _write_blocked(src)
