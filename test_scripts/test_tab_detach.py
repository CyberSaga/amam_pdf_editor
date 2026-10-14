from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from controller.pdf_controller import PDFController
from controller.session_transfer import SessionTransferPayload
from model.pdf_model import PDFModel
from view.detachable_tab_bar import DetachableTabBar
from view.pdf_view import PDFView


def _make_pdf(path: Path, text: str = "DETACH") -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), text)
    doc.save(path)
    doc.close()


def test_transfer_payload_repr_hides_bytes_and_password() -> None:
    payload = SessionTransferPayload(
        snapshot_bytes=b"secret-pdf-bytes",
        source_path="source.pdf",
        saved_path=None,
        display_name="source.pdf",
        dirty=True,
        current_page=2,
        scale=1.5,
        color_profile="srgb",
        password="secret-password",
        auth_level=2,
    )
    rendered = repr(payload)
    assert "secret-pdf-bytes" not in rendered
    assert "secret-password" not in rendered


def test_model_import_transfer_uses_independent_document_and_empty_history(tmp_path: Path) -> None:
    path = tmp_path / "source.pdf"
    _make_pdf(path)
    source = PDFModel()
    destination = PDFModel()
    try:
        source.open_pdf(str(path))
        source.doc[0].insert_text((40, 90), "DIRTY")
        source.edit_count += 1
        payload = SessionTransferPayload.from_model(
            source,
            source.get_active_session_id(),
            current_page=0,
            scale=1.25,
            color_profile="gray",
        )

        sid = destination.import_session_transfer(payload)

        assert sid == destination.get_active_session_id()
        assert destination.doc is not source.doc
        assert "DIRTY" in destination.doc[0].get_text()
        assert destination.session_has_unsaved_changes(sid) is True
        assert destination.command_manager.can_undo() is False
        meta = destination.get_session_meta(sid)
        assert meta["path"] == str(path)
        assert meta["dirty"] is True
    finally:
        source.close()
        destination.close()


def test_detachable_tab_bar_emits_only_for_thresholded_release_outside(qapp) -> None:
    bar = DetachableTabBar()
    bar.resize(320, 32)
    bar.addTab("A")
    bar.setTabData(0, "sid-a")
    bar.show()
    emitted: list[tuple[str, QPoint]] = []
    bar.detach_requested.connect(lambda sid, pos: emitted.append((sid, pos)))
    qapp.processEvents()
    try:
        QTest.mousePress(bar, Qt.LeftButton, pos=QPoint(20, 15))
        QTest.mouseRelease(bar, Qt.LeftButton, pos=QPoint(24, 15))
        assert emitted == []

        QTest.mousePress(bar, Qt.LeftButton, pos=QPoint(20, 15))
        QTest.mouseMove(bar, QPoint(120, 15), delay=10)
        QTest.mouseRelease(bar, Qt.LeftButton, pos=QPoint(120, 15))
        assert emitted == []

        QTest.mousePress(bar, Qt.LeftButton, pos=QPoint(20, 15))
        QTest.mouseMove(bar, QPoint(400, 80), delay=10)
        QTest.mouseRelease(bar, Qt.LeftButton, pos=QPoint(400, 80))
        assert len(emitted) == 1
        assert emitted[0][0] == "sid-a"
    finally:
        bar.close()
        qapp.processEvents()


def test_controller_removes_source_only_after_successful_handoff(qapp, tmp_path: Path) -> None:
    path = tmp_path / "atomic.pdf"
    _make_pdf(path)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    sid = model.get_active_session_id()
    try:
        controller.set_session_handoff_callback(lambda _payload, _pos: False)
        controller.detach_document_session(sid, QPoint(100, 100))
        assert sid in model.session_ids

        captured: list[SessionTransferPayload] = []
        controller.set_session_handoff_callback(
            lambda payload, _pos: captured.append(payload) or True
        )
        controller.detach_document_session(sid, QPoint(100, 100))
        assert len(captured) == 1
        assert sid not in model.session_ids
    finally:
        view.close()
        model.close()
        qapp.processEvents()


# --- F11-OPEN-1: detaching an encrypted tab must not decrypt the session ------

_SECRET = "TOP SECRET"


def _make_encrypted_pdf(path: Path, *, user_pw: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), _SECRET, fontsize=12)
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw=user_pw,
        owner_pw="owner-pw",
        permissions=fitz.PDF_PERM_PRINT,
    )
    doc.close()


def _transfer(source: PDFModel) -> tuple[SessionTransferPayload, PDFModel]:
    sid = source.get_active_session_id()
    payload = SessionTransferPayload.from_model(
        source, sid, current_page=0, scale=1.0, color_profile="default"
    )
    source.close_session(sid)
    destination = PDFModel()
    destination.import_session_transfer(payload)
    return payload, destination


def test_transfer_payload_of_encrypted_session_stays_encrypted(tmp_path: Path) -> None:
    path = tmp_path / "secret.pdf"
    _make_encrypted_pdf(path, user_pw="user-pw")
    source = PDFModel()
    try:
        source.open_pdf(str(path), password="user-pw")
        payload = SessionTransferPayload.from_model(
            source,
            source.get_active_session_id(),
            current_page=0,
            scale=1.0,
            color_profile="default",
        )
    finally:
        source.close()
    probe = fitz.open("pdf", payload.snapshot_bytes)
    try:
        # A fresh, never-authenticated handle: needs_pass is safe to read here.
        assert probe.needs_pass == 1, "transfer payload carries a decrypted PDF"
    finally:
        probe.close()


def test_detached_user_password_session_saves_back_encrypted(tmp_path: Path) -> None:
    path = tmp_path / "secret.pdf"
    _make_encrypted_pdf(path, user_pw="user-pw")
    source = PDFModel()
    source.open_pdf(str(path), password="user-pw")
    destination: PDFModel | None = None
    try:
        _payload, destination = _transfer(source)
        # The detached session is unlocked (renders / edits) yet still knows the
        # source was encrypted (metadata, not needs_pass: R9 M9-1).
        assert _SECRET in destination.doc[0].get_text()
        assert PDFModel._doc_is_encrypted(destination.doc) is True
        destination.doc[0].insert_text((72, 200), "edit", fontsize=12)
        destination.save_as(str(path))  # Ctrl+S in the detached window
        assert "edit" in destination.doc[0].get_text()
    finally:
        if destination is not None:
            destination.close()
        source.close()
    reread = fitz.open(str(path))
    try:
        assert reread.needs_pass == 1, "detached save wrote an unencrypted file"
        assert reread.authenticate("user-pw") != 0
        text = reread[0].get_text()
        assert _SECRET in text and "edit" in text
    finally:
        reread.close()


def test_detached_owner_only_session_keeps_permission_restrictions(tmp_path: Path) -> None:
    path = tmp_path / "restricted.pdf"
    _make_encrypted_pdf(path, user_pw="")
    before = fitz.open(str(path))
    restricted_permissions = before.permissions
    before.close()
    assert not restricted_permissions & fitz.PDF_PERM_MODIFY
    source = PDFModel()
    source.open_pdf(str(path))
    destination: PDFModel | None = None
    try:
        _payload, destination = _transfer(source)
        assert PDFModel._doc_is_encrypted(destination.doc) is True
        destination.doc[0].insert_text((72, 200), "edit", fontsize=12)
        destination.save_as(str(path))
    finally:
        if destination is not None:
            destination.close()
        source.close()
    reread = fitz.open(str(path))
    try:
        assert (reread.metadata or {}).get("encryption"), "owner-only encryption dropped"
        assert not reread.permissions & fitz.PDF_PERM_MODIFY, "permission restrictions dropped"
        assert "edit" in reread[0].get_text()
    finally:
        reread.close()


def test_import_transfer_refuses_encrypted_snapshot_without_password(tmp_path: Path) -> None:
    path = tmp_path / "secret.pdf"
    _make_encrypted_pdf(path, user_pw="user-pw")
    data = path.read_bytes()
    destination = PDFModel()
    try:
        for password in (None, "wrong-pw"):
            payload = SessionTransferPayload(
                snapshot_bytes=data,
                source_path=str(path),
                saved_path=None,
                display_name="secret.pdf",
                dirty=False,
                current_page=0,
                scale=1.0,
                color_profile="default",
                password=password,
                auth_level=2,
            )
            try:
                destination.import_session_transfer(payload)
            except (RuntimeError, ValueError):
                pass
            else:
                raise AssertionError(f"locked transfer accepted with password={password!r}")
            assert destination.session_ids == []
            assert destination.doc is None
    finally:
        destination.close()


# --- F11-OPEN-2: detaching must not re-baseline the on-disk fingerprint -------


def _rewrite_in_place(path: Path, text: str, scratch: Path) -> bytes:
    """Replace ``path``'s bytes in place, the way Explorer / ``copy /y`` does."""
    _make_pdf(scratch, text)
    foreign = scratch.read_bytes()
    with open(path, "r+b") as handle:
        handle.write(foreign)
        handle.truncate()
    return foreign


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_detached_save_refuses_a_foreign_rewrite_made_before_the_detach(tmp_path: Path) -> None:
    from model.pdf_model import SourceChangedOnDiskError

    plain = tmp_path / "plain.pdf"
    _make_pdf(plain, "original")
    source = PDFModel()
    sid = source.open_pdf(str(plain), append=True)
    source.doc[0].insert_text((72, 200), "my edit", fontsize=12)
    saved = tmp_path / "saved_as.pdf"
    source.save_as(str(saved))  # the live handle moves to a private copy
    foreign = _rewrite_in_place(saved, "FOREIGN CONTENT", tmp_path / "other.pdf")
    # The same window refuses (F10-FS-1); the detached one must as well.
    with pytest.raises(SourceChangedOnDiskError):
        source.save_as(str(saved))

    destination = PDFModel()
    try:
        payload = SessionTransferPayload.from_model(
            source, sid, current_page=0, scale=1.0, color_profile="default"
        )
        source.close_session(sid)
        destination.import_session_transfer(payload)
        with pytest.raises(SourceChangedOnDiskError):
            destination.save_as(str(saved))
    finally:
        destination.close()
        source.close()
    assert saved.read_bytes() == foreign


def test_import_keeps_the_senders_baseline_when_the_file_changes_after_capture(
    tmp_path: Path,
) -> None:
    from model.pdf_model import SourceChangedOnDiskError

    path = tmp_path / "opened.pdf"
    _make_pdf(path, "original")
    source = PDFModel()
    source.open_pdf(str(path))
    payload = SessionTransferPayload.from_model(
        source,
        source.get_active_session_id(),
        current_page=0,
        scale=1.0,
        color_profile="default",
    )
    source.close()
    # Another program rewrites the file between the capture and the import.
    foreign = _rewrite_in_place(path, "FOREIGN CONTENT", tmp_path / "other.pdf")

    destination = PDFModel()
    try:
        destination.import_session_transfer(payload)
        destination.doc[0].insert_text((72, 200), "edit", fontsize=12)
        with pytest.raises(SourceChangedOnDiskError):
            destination.save_as(str(path))
    finally:
        destination.close()
    assert path.read_bytes() == foreign


def test_payload_carries_the_senders_disk_baseline(tmp_path: Path) -> None:
    from model.pdf_model import _file_fingerprint

    path = tmp_path / "carried.pdf"
    _make_pdf(path, "original")
    source = PDFModel()
    try:
        source.open_pdf(str(path))
        sid = source.get_active_session_id()
        session = source._sessions_by_id[sid]
        payload = SessionTransferPayload.from_model(
            source, sid, current_page=0, scale=1.0, color_profile="default"
        )
        assert payload.disk_fingerprint == session.disk_fingerprint == _file_fingerprint(path)
        assert payload.disk_fingerprint_path == session.disk_fingerprint_path
    finally:
        source.close()


def test_an_untouched_detached_session_still_saves_and_rebaselines(tmp_path: Path) -> None:
    path = tmp_path / "plain.pdf"
    _make_pdf(path, "original")
    source = PDFModel()
    source.open_pdf(str(path))
    destination: PDFModel | None = None
    try:
        _payload, destination = _transfer(source)
        destination.doc[0].insert_text((72, 200), "first", fontsize=12)
        destination.save_as(str(path))
        destination.doc[0].insert_text((72, 220), "second", fontsize=12)
        destination.save_as(str(path))  # its own first save is not a foreign rewrite
    finally:
        if destination is not None:
            destination.close()
        source.close()
    reread = fitz.open(str(path))
    try:
        text = reread[0].get_text()
        assert "first" in text and "second" in text
    finally:
        reread.close()


def test_a_payload_without_a_baseline_imports_without_measuring_the_file(tmp_path: Path) -> None:
    path = tmp_path / "plain.pdf"
    _make_pdf(path, "original")
    payload = SessionTransferPayload(
        snapshot_bytes=path.read_bytes(),
        source_path=str(path),
        saved_path=None,
        display_name="plain.pdf",
        dirty=False,
        current_page=0,
        scale=1.0,
        color_profile="default",
    )
    destination = PDFModel()
    try:
        sid = destination.import_session_transfer(payload)
        session = destination._sessions_by_id[sid]
        assert session.disk_fingerprint is None
        assert session.disk_fingerprint_path is None
    finally:
        destination.close()
