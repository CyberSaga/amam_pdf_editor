"""H10-2 Part B: document serialization through MuPDF's native output (Model only, no Qt).

PyMuPDF's ``tobytes()`` / ``save(io.BytesIO)`` send every ``fz_write`` through a
Python file object, and MuPDF's classic xref writer makes about one write per
row: a 4M-slot table took 18.6 s per snapshot against 0.35 s for the same bytes
written to a file.  Every snapshot site now goes through ``model.doc_bytes``,
which writes to a temp file -- or, for a decrypted copy of an encrypted document
(or a secure-latched session), into an in-memory MuPDF buffer that never touches
disk.

The ``no_python_sink`` fixture makes PyMuPDF's Python file-object output raise,
so a site that still serializes through it fails loudly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402

TEXT = "Snapshot body text"


def _make_pdf(path: Path, *, user_pw: str | None = None, pages: int = 2) -> Path:
    doc = fitz.open()
    for number in range(pages):
        doc.new_page().insert_text((72, 100), f"{TEXT} {number}", fontsize=12.0)
    if user_pw is None:
        doc.save(str(path))
    else:
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw=user_pw,
            permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_MODIFY,
        )
    doc.close()
    return path


def _open(path: Path, password: str | None = None) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(path), password=password)
    return model


@pytest.fixture
def no_python_sink(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise RuntimeError("serialized through PyMuPDF's Python file-object sink")

    monkeypatch.setattr(pymupdf, "JM_new_output_fileptr", _refuse)


@pytest.fixture
def disk_writes(monkeypatch) -> list[bytes]:
    """Every byte string ``model.doc_bytes`` wrote through a temp file."""
    import model.doc_bytes as doc_bytes

    written: list[bytes] = []
    original = doc_bytes.serialize_via_file

    def _recording(doc, scratch_dir=None, **options):
        data = original(doc, scratch_dir, **options)
        written.append(data)
        return data

    monkeypatch.setattr(doc_bytes, "serialize_via_file", _recording)
    return written


def _all_locked(written: list[bytes]) -> bool:
    """Every temp file held ciphertext only: it cannot be opened without the password."""
    for data in written:
        doc = fitz.open("pdf", data)
        try:
            if not doc.needs_pass:
                return False
        finally:
            doc.close()
    return True


# ---------------------------------------------------------------- the helper


@pytest.mark.parametrize(
    "options",
    [
        {"garbage": 0, "no_new_id": 1, "encryption": fitz.PDF_ENCRYPT_KEEP},
        {"garbage": 0, "no_new_id": 1, "encryption": fitz.PDF_ENCRYPT_NONE},
        {"garbage": 1, "no_new_id": 1, "encryption": fitz.PDF_ENCRYPT_NONE},
        {"garbage": 0, "no_new_id": 1, "deflate": 1, "encryption": fitz.PDF_ENCRYPT_KEEP},
    ],
)
def test_both_sinks_are_byte_identical_to_tobytes(tmp_path, options) -> None:
    # The in-memory sink mirrors these private PyMuPDF names; a bump must fail here,
    # not fall back silently to the slow ``tobytes``.
    for name in ("_as_pdf_document", "JM_embedded_clean", "JM_ensure_identity"):
        assert hasattr(fitz, name), name
    from model.doc_bytes import serialize_in_memory, serialize_via_file

    path = _make_pdf(tmp_path / "plain.pdf")
    doc = fitz.open(str(path))
    try:
        doc[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
        expected = doc.tobytes(**options)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        assert serialize_via_file(doc, scratch, **options) == expected
        assert list(scratch.iterdir()) == [], "the temp file is removed at once"
        assert serialize_in_memory(doc, **options) == expected
    finally:
        doc.close()


def test_a_new_id_is_still_generated_when_asked_for(tmp_path) -> None:
    from model.doc_bytes import serialize_doc, serialize_in_memory

    doc = fitz.open()
    doc.new_page().insert_text((72, 100), TEXT)
    try:
        for data in (
            serialize_doc(doc, scratch_dir=tmp_path, encryption=fitz.PDF_ENCRYPT_KEEP),
            serialize_in_memory(doc, encryption=fitz.PDF_ENCRYPT_KEEP),
        ):
            reopened = fitz.open("pdf", data)
            try:
                assert reopened.xref_get_key(-1, "ID")[0] == "array"
                assert TEXT in reopened[0].get_text()
            finally:
                reopened.close()
    finally:
        doc.close()


def test_the_decrypted_copy_of_an_encrypted_document_stays_in_memory(
    tmp_path, disk_writes
) -> None:
    from model.doc_bytes import serialize_doc

    path = _make_pdf(tmp_path / "locked.pdf", user_pw="user-secret")
    clone = fitz.open(str(path))
    try:
        assert clone.authenticate("user-secret")
        expected = clone.tobytes(garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_NONE)
        data = serialize_doc(
            clone, scratch_dir=tmp_path, garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_NONE
        )
        assert data == expected
    finally:
        clone.close()
    assert disk_writes == []
    plain = fitz.open("pdf", data)
    try:
        assert not plain.needs_pass and f"{TEXT} 0" in plain[0].get_text()
    finally:
        plain.close()


def test_a_caller_can_force_the_in_memory_sink(tmp_path, disk_writes) -> None:
    from model.doc_bytes import serialize_doc

    doc = fitz.open(str(_make_pdf(tmp_path / "plain.pdf")))
    try:
        data = serialize_doc(doc, encryption=fitz.PDF_ENCRYPT_KEEP, no_new_id=1, in_memory=True)
        assert data == doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP, no_new_id=1)
    finally:
        doc.close()
    assert disk_writes == []


def test_a_failed_serialization_raises_and_leaves_no_temp_file(tmp_path) -> None:
    from model.doc_bytes import serialize_doc

    empty = fitz.open()  # zero pages: save() refuses
    try:
        with pytest.raises(ValueError):
            serialize_doc(empty, scratch_dir=tmp_path, encryption=fitz.PDF_ENCRYPT_KEEP)
        with pytest.raises(ValueError):
            serialize_doc(empty, encryption=fitz.PDF_ENCRYPT_KEEP, in_memory=True)
    finally:
        empty.close()
    assert list(tmp_path.iterdir()) == []


def test_serialize_doc_takes_only_whole_document_options(tmp_path) -> None:
    """An incremental save appends to the doc's own file; it is never a snapshot."""
    from model.doc_bytes import serialize_doc

    doc = fitz.open(str(_make_pdf(tmp_path / "plain.pdf")))
    try:
        with pytest.raises(TypeError):
            serialize_doc(doc, encryption=fitz.PDF_ENCRYPT_KEEP, incremental=True)
        with pytest.raises(TypeError):
            serialize_doc(doc)  # the encryption mode is never implicit
    finally:
        doc.close()


# ---------------------------------------------------------------- PDFModel sites


def test_doc_snapshot_does_not_serialize_through_a_python_file_object(
    tmp_path, no_python_sink
) -> None:
    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    try:
        model.doc[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
        snapshot = model._capture_doc_snapshot()
        reopened = fitz.open("pdf", bytes(snapshot))
        try:
            assert int(reopened.xref_length()) == int(model.doc.xref_length())
            assert len(reopened) == len(model.doc)
        finally:
            reopened.close()
    finally:
        model.close()


def test_an_encrypted_doc_snapshot_keeps_its_encryption(tmp_path, no_python_sink) -> None:
    model = _open(_make_pdf(tmp_path / "locked.pdf", user_pw="user-secret"), "user-secret")
    try:
        snapshot = model._capture_doc_snapshot()
    finally:
        model.close()
    reopened = fitz.open("pdf", bytes(snapshot))
    try:
        assert reopened.needs_pass
        assert reopened.authenticate("user-secret")
        assert f"{TEXT} 0" in reopened[0].get_text()
    finally:
        reopened.close()


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize(
    "capture",
    ["capture_worker_snapshot_bytes", "capture_print_snapshot_bytes", "capture_session_transfer_bytes"],
)
def test_worker_print_and_transfer_snapshots_use_the_native_sink(
    tmp_path, no_python_sink, encrypted, capture
) -> None:
    password = "user-secret" if encrypted else None
    model = _open(_make_pdf(tmp_path / "doc.pdf", user_pw=password), password)
    try:
        model.secure_save_required = capture == "capture_print_snapshot_bytes"
        data = getattr(model, capture)()
    finally:
        model.close()
    reopened = fitz.open("pdf", data)
    try:
        if reopened.needs_pass:
            assert capture == "capture_session_transfer_bytes" and encrypted
            assert reopened.authenticate("user-secret")
        assert f"{TEXT} 0" in reopened[0].get_text()
    finally:
        reopened.close()


@pytest.mark.parametrize("capture", ["capture_worker_snapshot_bytes", "capture_print_snapshot_bytes"])
def test_decrypted_worker_snapshots_of_an_encrypted_doc_never_touch_disk(
    tmp_path, disk_writes, capture
) -> None:
    model = _open(_make_pdf(tmp_path / "locked.pdf", user_pw="user-secret"), "user-secret")
    try:
        model.secure_save_required = capture == "capture_print_snapshot_bytes"
        data = getattr(model, capture)()
    finally:
        model.close()
    assert _all_locked(disk_writes), "only ciphertext may reach a temp file"
    plain = fitz.open("pdf", data)
    try:
        assert not plain.needs_pass and f"{TEXT} 0" in plain[0].get_text()
    finally:
        plain.close()


def test_a_secure_session_snapshot_never_touches_disk(tmp_path, disk_writes) -> None:
    """A secure-latched session (destructive edits) keeps its garbage=0 snapshots, which
    still hold the removed objects, in memory."""
    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    try:
        model.secure_save_required = True
        snapshot = model._capture_doc_snapshot()
        assert len(fitz.open("pdf", bytes(snapshot))) == 2
        model.capture_worker_snapshot_bytes()
    finally:
        model.close()
    assert disk_writes == []


def _latched_model(tmp_path: Path, written: list[bytes]) -> PDFModel:
    """A model whose secure latch was set by a real destructive edit (page delete).

    ``written`` is cleared afterwards: the delete's own pre-state undo snapshot is
    taken before the latch and is not what these tests pin.
    """
    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    model.delete_pages([2])
    assert model.secure_save_required
    written.clear()
    return model


def test_a_secure_session_text_edit_never_touches_disk(tmp_path, disk_writes) -> None:
    """F12-H102-1: the text-commit engine's scratch clones are garbage=0 serializations
    of the live doc, so a secure-latched session keeps them in memory too."""
    model = _latched_model(tmp_path, disk_writes)
    try:
        model.ensure_page_index_built(1)
        result = model.edit_text(
            1,
            fitz.Rect(70, 85, 300, 110),
            "Snapshot body text edited",
            original_text=f"{TEXT} 0",
        )
        assert str(result).endswith("SUCCESS")
    finally:
        model.close()
    assert disk_writes == []


def test_a_secure_session_engine_scratch_copy_never_touches_disk(tmp_path, disk_writes) -> None:
    model = _latched_model(tmp_path, disk_writes)
    try:
        scratch = model.get_tiered_commit_engine()._build_scratch_copy()
        assert scratch is not None and len(scratch) == 1
        scratch.close()
    finally:
        model.close()
    assert disk_writes == []


def test_a_secure_session_preview_snapshot_never_touches_disk(tmp_path, disk_writes) -> None:
    from model.text_commit.preview import open_preview_session

    model = _latched_model(tmp_path, disk_writes)
    try:
        session = open_preview_session(
            model.doc, 0, "sess", serialize=model.serialize_document_bytes
        )
        assert session is not None
    finally:
        model.close()
    assert disk_writes == []


def test_an_ordinary_session_text_commit_snapshots_go_through_the_model_temp_dir(
    tmp_path, monkeypatch
) -> None:
    import model.doc_bytes as doc_bytes
    from model.text_commit.preview import open_preview_session

    seen: list[object] = []
    original = doc_bytes.serialize_via_file

    def _spy(doc, scratch_dir=None, **options):
        seen.append(scratch_dir)
        return original(doc, scratch_dir, **options)

    monkeypatch.setattr(doc_bytes, "serialize_via_file", _spy)
    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    try:
        seen.clear()
        scratch = model.get_tiered_commit_engine()._build_scratch_copy()
        assert scratch is not None
        scratch.close()
        assert open_preview_session(
            model.doc, 0, "sess", serialize=model.serialize_document_bytes
        )
        assert len(seen) == 2
        assert all(Path(str(s)) == Path(model.temp_dir.name) for s in seen), seen
    finally:
        model.close()


def test_a_bare_engine_and_preview_keep_their_snapshot_in_memory(tmp_path, disk_writes) -> None:
    """Without a model-supplied serializer the default is the safe one: no temp file."""
    from model.text_commit.engine import TieredCommitEngine
    from model.text_commit.preview import open_preview_session

    doc = fitz.open(str(_make_pdf(tmp_path / "plain.pdf")))
    try:
        scratch = TieredCommitEngine(doc)._build_scratch_copy()
        assert scratch is not None
        scratch.close()
        assert open_preview_session(doc, 0, "sess") is not None
    finally:
        doc.close()
    assert disk_writes == []


def test_no_production_site_serializes_a_live_doc_to_disk_behind_the_models_back() -> None:
    """Bug class of F12-H102-1: ``doc_bytes.serialize_doc`` without ``in_memory=True``
    may only be called from the model's funnel (``serialize_document_bytes``), which
    keeps a secure-latched session's snapshots off disk and in the model temp dir."""
    import ast

    allowed = {("model/pdf_model.py", "serialize_document_bytes")}
    offenders: list[str] = []

    def _walk(node: ast.AST, rel: str, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, ast.FunctionDef) else owner
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "serialize_doc"
            ):
                forced = any(
                    kw.arg == "in_memory"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in child.keywords
                )
                if not forced and (rel, owner) not in allowed:
                    offenders.append(f"{rel}:{child.lineno}")
            _walk(child, rel, inner)

    for package in ("model", "controller", "view", "utils"):
        for path in sorted((ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            _walk(tree, path.relative_to(ROOT).as_posix(), "")
    assert offenders == []


def test_an_ordinary_snapshot_goes_through_the_model_temp_dir(tmp_path, monkeypatch) -> None:
    import model.doc_bytes as doc_bytes

    seen: list[object] = []
    original = doc_bytes.serialize_via_file

    def _spy(doc, scratch_dir=None, **options):
        seen.append(scratch_dir)
        return original(doc, scratch_dir, **options)

    monkeypatch.setattr(doc_bytes, "serialize_via_file", _spy)
    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    try:
        seen.clear()
        model._capture_doc_snapshot()
        assert seen and Path(str(seen[0])) == Path(model.temp_dir.name)
        assert not [p for p in Path(model.temp_dir.name).iterdir() if p.name.startswith("snap_")]
    finally:
        model.close()


# ---------------------------------------------------------------- other model sites


def test_optimizer_size_probes_and_source_capture_use_the_native_sink(
    tmp_path, no_python_sink
) -> None:
    from model.pdf_optimizer import (
        build_pdf_audit_report,
        capture_optimize_source,
        current_document_size_bytes,
    )

    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    try:
        model.doc[0].add_highlight_annot(fitz.Rect(72, 90, 150, 105))
        sid = model.get_active_session_id()
        model._sessions_by_id[sid].transferred_dirty = True  # a dirty session: no file shortcut
        working = fitz.open(str(tmp_path / "plain.pdf"))
        try:
            assert build_pdf_audit_report(model, doc=working).total_bytes > 0
        finally:
            working.close()
        snapshot = capture_optimize_source(model, sid)
        assert snapshot.source_bytes and snapshot.source_size == len(snapshot.source_bytes)
        assert current_document_size_bytes(model, sid) > 0
    finally:
        model.close()


def test_the_watermark_save_clone_uses_the_native_sink(tmp_path, no_python_sink) -> None:
    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    try:
        model.tools.watermark.add_watermark([1], "CONFIDENTIAL")
        sid = model.get_active_session_id()
        prepared = model.tools.prepare_doc_for_save(sid, model.doc)
        assert prepared is not None and prepared is not model.doc
        prepared.close()
    finally:
        model.close()


def test_text_commit_snapshots_use_the_native_sink(tmp_path, no_python_sink) -> None:
    from model.text_commit.engine import TieredCommitEngine
    from model.text_commit.preview import PreviewSessionInput, open_preview_session
    from model.text_commit.verify import _ocg_membership_status

    doc = fitz.open(str(_make_pdf(tmp_path / "plain.pdf")))
    try:
        assert isinstance(open_preview_session(doc, 0, "sess"), PreviewSessionInput)
        scratch = TieredCommitEngine(doc)._build_scratch_copy()
        assert scratch is not None
        scratch.close()
        assert _ocg_membership_status(doc, f"{TEXT} 0") == "preserved"
    finally:
        doc.close()


def test_encrypted_text_commit_scratch_decrypts_in_memory_only(tmp_path, disk_writes) -> None:
    from model.text_commit.preview import open_preview_session

    doc = fitz.open(str(_make_pdf(tmp_path / "locked.pdf", user_pw="user-secret")))
    try:
        assert doc.authenticate("user-secret")
        session = open_preview_session(doc, 0, "sess", password="user-secret")
        assert session is not None
        plain = fitz.open("pdf", session.snapshot_bytes)
        try:
            assert not plain.needs_pass
        finally:
            plain.close()
    finally:
        doc.close()
    # A bare session (no model funnel) stays in memory; any temp file would be ciphertext.
    assert _all_locked(disk_writes), "only ciphertext may reach a temp file"


# ---------------------------------------- F12-H102-2: no edit depends on the disk


def _break_file_sink(monkeypatch, exc: BaseException) -> None:
    """Every ``Document.save`` to a path raises ``exc`` (a full or vanished volume)."""

    def _fail(self, *_args, **_kwargs):
        raise exc

    monkeypatch.setattr(fitz.Document, "save", _fail)


@pytest.mark.parametrize(
    "exc",
    [
        OSError(28, "No space left on device"),
        fitz.mupdf.FzErrorSystem("cannot write to file: no space left on device"),
    ],
    ids=["oserror", "mupdf_system_error"],
)
def test_a_failing_file_sink_falls_back_to_the_memory_sink(tmp_path, monkeypatch, exc) -> None:
    from model.doc_bytes import serialize_doc

    doc = fitz.open(str(_make_pdf(tmp_path / "plain.pdf")))
    try:
        expected = doc.tobytes(garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_KEEP)
        _break_file_sink(monkeypatch, exc)
        got = serialize_doc(
            doc, scratch_dir=tmp_path, no_new_id=1, encryption=fitz.PDF_ENCRYPT_KEEP
        )
        assert got == expected
    finally:
        doc.close()


def test_a_vanished_scratch_dir_falls_back_to_the_memory_sink(tmp_path) -> None:
    from model.doc_bytes import serialize_doc

    doc = fitz.open(str(_make_pdf(tmp_path / "plain.pdf")))
    try:
        expected = doc.tobytes(garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_KEEP)
        got = serialize_doc(
            doc,
            scratch_dir=tmp_path / "gone",
            no_new_id=1,
            encryption=fitz.PDF_ENCRYPT_KEEP,
        )
        assert got == expected
    finally:
        doc.close()


def test_a_genuine_document_error_still_propagates_through_the_fallback(tmp_path) -> None:
    from model.doc_bytes import serialize_doc

    empty = fitz.open()
    try:
        with pytest.raises(ValueError):
            serialize_doc(empty, scratch_dir=tmp_path / "gone", encryption=fitz.PDF_ENCRYPT_KEEP)
    finally:
        empty.close()


def test_edits_are_still_recorded_after_the_model_temp_dir_is_removed(tmp_path) -> None:
    """A temp cleaner removed the idle folder: the snapshot-recorded edit must still work
    (it did when snapshots were ``tobytes``), the snapshots staying in memory."""
    import shutil

    from model.edit_commands import SnapshotCommand

    model = _open(_make_pdf(tmp_path / "plain.pdf"))
    try:
        shutil.rmtree(model.temp_dir.name)
        before = model._capture_doc_snapshot()
        model.tools.annotation.add_highlight(
            1, fitz.Rect(72, 90, 200, 110), (1.0, 1.0, 0.0, 1.0)
        )
        after = model._capture_doc_snapshot()
        assert after != before
        model.command_manager.record(
            SnapshotCommand(
                model=model,
                command_type="add_highlight",
                affected_pages=[1],
                before_bytes=before,
                after_bytes=after,
                description="hl",
            )
        )
        assert model.command_manager.undo_count == 1
        assert len(list(model.doc[0].annots() or [])) == 1
        model.command_manager.undo()
        assert not list(model.doc[0].annots() or [])
    finally:
        model.close()
