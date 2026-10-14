"""SIG-DIALOG: a signed save that would invalidate the signature asks first.

The append-only save keeps a digitally signed source a byte prefix of the new
file (R7-1, H10-2).  Whatever still declines it -- the secure latch, a changed
or vanished source, a repaired file, the growth cap, a failed verification, a
watermark clone, a failed in-place append -- used to fall back to a full
rewrite that silently invalidated the signature.  The owner's decision: the
model raises ``SignatureWouldBreakError(reason_code, path)`` instead and only
writes the rewrite when called with ``allow_signature_loss=True``; the
controller asks (Traditional Chinese dialog: save anyway / cancel, suggesting
Save As) and retries only on consent.  A cancel writes nothing and keeps the
session dirty, including on the close / Save All path.
"""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import test_save_prunes_orphans as spo  # noqa: E402

import controller.pdf_controller as controller_module  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel, SignatureWouldBreakError  # noqa: E402


def _staging_leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.startswith("."))


def _assert_refused(model: PDFModel, target: Path, reason: str) -> None:
    """``save_as(target)`` raises with ``reason`` and writes nothing at ``target``."""
    before = target.read_bytes() if target.exists() else None
    with pytest.raises(SignatureWouldBreakError) as excinfo:
        model.save_as(str(target))
    assert excinfo.value.reason_code == reason, excinfo.value.reason_code
    assert Path(excinfo.value.path) == target
    after = target.read_bytes() if target.exists() else None
    assert after == before, "a refused signed save must not write the target"
    assert _staging_leftovers(target.parent) == []


# ---------------------------------------------------------------- model: every residual decline asks


def test_secure_latch_on_a_signed_doc_refuses_then_rewrites_only_with_consent(tmp_path) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        model.secure_save_required = True
        _assert_refused(model, path, "secure_latch")
        assert model.has_unsaved_changes(), "a refused save keeps the session dirty"
        assert path.read_bytes() == original

        model.save_as(str(path), allow_signature_loss=True)
        assert not model.has_unsaved_changes()
    finally:
        model.close()
    assert spo._eof_count(path) == 1, "the consented save is the sanitising full rewrite"
    assert spo._highlight_count(path) == 1


def test_a_failed_append_on_a_memory_backed_signed_doc_refuses_with_its_reason(
    tmp_path, monkeypatch
) -> None:
    import model.signed_append_save as signed_append_save

    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        model.command_manager.undo()
        spo._record_highlight(model)
        monkeypatch.setattr(
            signed_append_save, "try_append_state_onto_source", lambda *a, **k: "verify_failed"
        )
        _assert_refused(model, path, "verify_failed")
        assert path.read_bytes() == original
        assert model.has_unsaved_changes()

        model.save_as(str(path), allow_signature_loss=True)
    finally:
        model.close()
    assert spo._eof_count(path) == 1
    assert spo._highlight_count(path) == 1


def test_an_exploding_append_refuses_as_append_error(tmp_path, monkeypatch) -> None:
    import model.signed_append_save as signed_append_save

    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        model.command_manager.undo()
        spo._record_highlight(model)

        def _boom(*_a, **_k):
            raise RuntimeError("replay exploded")

        monkeypatch.setattr(signed_append_save, "try_append_state_onto_source", _boom)
        _assert_refused(model, path, "append_error")
    finally:
        model.close()


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_save_as_after_a_foreign_rewrite_of_the_signed_source_refuses(tmp_path) -> None:
    path = spo._make_signed_pdf(tmp_path / "contract.pdf")
    original = path.read_bytes()
    out = tmp_path / "contract_copy.pdf"
    model = spo._memory_backed_signed_session(path)
    try:
        needle = b"<506167652074776f20626f6479>"
        spo._overwrite_in_place(path, original.replace(needle, b"<506167652054574f20626f6479>"))
        _assert_refused(model, out, "source_changed")
        assert not out.exists()
        model.save_as(str(out), allow_signature_loss=True)
    finally:
        model.close()
    saved = fitz.open(str(out))
    try:
        assert len(saved) == 2
        assert saved[0].first_annot is not None
    finally:
        saved.close()


@pytest.mark.usefixtures("share_lock_disabled")  # foreign writer: degraded-lock mode (OD-FS1-LOCK)
def test_save_as_after_the_signed_source_vanished_refuses(tmp_path) -> None:
    path = spo._make_signed_pdf(tmp_path / "contract.pdf")
    out = tmp_path / "contract_copy.pdf"
    model = spo._memory_backed_signed_session(path)
    try:
        path.unlink()
        _assert_refused(model, out, "source_missing")
        model.save_as(str(out), allow_signature_loss=True)
    finally:
        model.close()
    assert len(fitz.open(str(out))) == 2


def test_incremental_saving_switched_off_on_a_signed_doc_refuses(tmp_path) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    model = spo._open(path, incremental=False)
    try:
        spo._record_highlight(model)
        _assert_refused(model, path, "incremental_disabled")
        model.save_as(str(path), allow_signature_loss=True)
    finally:
        model.close()
    assert spo._eof_count(path) == 1


def test_a_live_handle_that_cannot_append_to_its_own_signed_file_refuses(tmp_path, monkeypatch) -> None:
    """A repaired file (``can_save_incrementally()`` is false) still opened on the target."""
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        model.doc[0].add_text_annot((300, 300), "note")
        model.edit_count += 1
        assert Path(model.doc.name).resolve() == path.resolve(), "the live handle is the file"
        monkeypatch.setattr(model, "_handle_is_spent_for_incremental", lambda _doc: True)
        _assert_refused(model, path, "in_place_append_unavailable")
        assert path.read_bytes() == original
        model.save_as(str(path), allow_signature_loss=True)
    finally:
        model.close()
    assert spo._eof_count(path) == 1


def test_a_watermark_on_a_signed_doc_refuses_the_clone_rewrite(tmp_path) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        _assert_refused(model, path, "watermark_rewrite")
        assert path.read_bytes() == original
        model.save_as(str(path), allow_signature_loss=True)
    finally:
        model.close()
    assert path.read_bytes() != original


def test_a_failed_in_place_append_of_a_signed_doc_refuses_instead_of_rewriting(
    tmp_path, monkeypatch
) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        model.doc[0].add_text_annot((300, 300), "note")
        model.edit_count += 1
        real_save_doc = model._save_doc

        def _save_doc(doc, target, **kwargs):
            if kwargs.get("incremental"):
                raise RuntimeError("append failed (injected)")
            return real_save_doc(doc, target, **kwargs)

        monkeypatch.setattr(model, "_save_doc", _save_doc)
        _assert_refused(model, path, "incremental_failed")
        assert path.read_bytes() == original
        model.save_as(str(path), allow_signature_loss=True)
    finally:
        model.close()
    assert spo._eof_count(path) == 1


_TORN_TAIL = b"\n12 0 obj\n<< /Type /Annot /Subtype /Highl"


def _tear_the_in_place_append(model: PDFModel, monkeypatch) -> None:
    """The next in-place append writes part of a revision, then the disk is full (F12-SIG-1)."""
    real_save_doc = model._save_doc

    def _save_doc(doc, target, **kwargs):
        if kwargs.get("incremental"):
            with open(target, "ab") as fh:
                fh.write(_TORN_TAIL + b"x" * 4096)
            raise OSError(28, "No space left on device (injected)")
        return real_save_doc(doc, target, **kwargs)

    monkeypatch.setattr(model, "_save_doc", _save_doc)


def test_a_torn_in_place_append_of_a_signed_doc_is_rolled_back_and_the_retry_saves(
    tmp_path, monkeypatch
) -> None:
    """F12-SIG-1: a partial append is the session's own write, not a foreign one.

    The refusal used to leave the torn revision on disk with the fingerprint of
    the file before it, so the consented retry and every later Ctrl+S were
    refused as "changed by another program" and the file stayed torn.
    """
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        _tear_the_in_place_append(model, monkeypatch)
        _assert_refused(model, path, "incremental_failed")
        assert path.read_bytes() == original
        assert model.has_unsaved_changes()

        monkeypatch.undo()  # the disk has space again
        model.save_as(str(path), allow_signature_loss=True)
        assert not model.has_unsaved_changes()
        model.save_as(str(path))  # the next Ctrl+S is not refused either
    finally:
        model.close()
    data = path.read_bytes()
    assert _TORN_TAIL not in data
    assert data.startswith(original), "the signed revision must stay a byte prefix"
    assert spo._eof_count(path) == 2
    assert spo._highlight_count(path) == 1


@pytest.mark.parametrize(
    ("after", "rolled_back"),
    [
        ("unchanged", True),
        ("appended", True),
        ("prefix_changed", False),
        ("shorter", False),
        ("missing", False),
    ],
)
def test_the_rollback_only_ever_cuts_the_failed_revision(tmp_path, after, rolled_back) -> None:
    """``_roll_back_partial_append`` never cuts bytes that are not the failed append."""
    from model.pdf_model import _file_fingerprint

    target = tmp_path / "f.pdf"
    base = bytes(range(256)) * 40  # past both 4 KB edges of the fingerprint
    target.write_bytes(base)
    before = _file_fingerprint(target)
    assert before is not None
    expected = {
        "unchanged": base,
        "appended": base + _TORN_TAIL,
        "prefix_changed": b"Z" + base[1:] + _TORN_TAIL,
        "shorter": base[:-10],
    }.get(after)
    if expected is None:
        target.unlink()
    else:
        target.write_bytes(expected)
    model = PDFModel()
    try:
        assert model._roll_back_partial_append(str(target), before) is rolled_back
    finally:
        model.close()
    if after in ("unchanged", "appended"):
        assert target.read_bytes() == base
    elif expected is not None:
        assert target.read_bytes() == expected, "a guarded rollback must not touch the file"
    else:
        assert not target.exists()


def test_save_as_after_a_cancelled_torn_append_does_not_copy_the_torn_bytes(
    tmp_path, monkeypatch
) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    other = tmp_path / "other.pdf"
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        _tear_the_in_place_append(model, monkeypatch)
        with pytest.raises(SignatureWouldBreakError):
            model.save_as(str(path))
        monkeypatch.undo()
        assert path.read_bytes() == original
        model.save_as(str(other))  # the user cancelled the dialog and picked Save As
    finally:
        model.close()
    data = other.read_bytes()
    assert _TORN_TAIL not in data
    assert data.startswith(original)
    assert spo._eof_count(other) == 2


def test_a_torn_append_that_cannot_be_rolled_back_does_not_lock_the_session_out(
    tmp_path, monkeypatch
) -> None:
    """The rollback is best effort; the fingerprint re-record is what keeps Ctrl+S working."""
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    rollbacks: list[tuple[str, int]] = []
    try:
        spo._record_highlight(model)
        _tear_the_in_place_append(model, monkeypatch)
        monkeypatch.setattr(
            model,
            "_roll_back_partial_append",
            lambda target, before: rollbacks.append((str(target), before[0])) or False,
            raising=False,
        )
        with pytest.raises(SignatureWouldBreakError) as excinfo:
            model.save_as(str(path))
        assert excinfo.value.reason_code == "incremental_failed"
        assert _TORN_TAIL in path.read_bytes()

        monkeypatch.undo()
        model.save_as(str(path), allow_signature_loss=True)
        model.save_as(str(path))
    finally:
        model.close()
    assert [(Path(t).resolve(), n) for t, n in rollbacks] == [(path.resolve(), len(original))]
    data = path.read_bytes()
    assert _TORN_TAIL not in data
    assert data.startswith(original)
    assert spo._eof_count(path) == 2


def test_save_session_as_threads_the_consent(tmp_path) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        model.secure_save_required = True
        sid = model.get_active_session_id()
        with pytest.raises(SignatureWouldBreakError):
            model.save_session_as(sid, str(path))
        assert model.session_has_unsaved_changes(sid)
        model.save_session_as(sid, str(path), allow_signature_loss=True)
        assert not model.session_has_unsaved_changes(sid)
    finally:
        model.close()
    assert spo._eof_count(path) == 1


@pytest.mark.parametrize("route", ["full_save", "watermark_clone"])
def test_an_unsigned_doc_never_asks(tmp_path, route) -> None:
    path = spo._make_signed_pdf(tmp_path / "plain.pdf", signed=False)
    model = spo._open(path, incremental=False)
    try:
        spo._record_highlight(model)
        model.secure_save_required = True
        if route == "watermark_clone":
            model.tools.watermark.add_watermark([1], "DRAFT")
        model.save_as(str(path))
    finally:
        model.close()
    assert spo._eof_count(path) == 1


def test_a_signed_append_that_works_never_asks(tmp_path) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        model.command_manager.undo()
        spo._record_highlight(model)
        model.save_as(str(path))
    finally:
        model.close()
    assert path.read_bytes().startswith(original)
    assert spo._eof_count(path) == 2


# ---------------------------------------------------------------- signed_append_save reason codes


def test_try_append_reports_why_it_declined(tmp_path, monkeypatch) -> None:
    import model.signed_append_save as signed_append_save
    from model.signed_append_save import append_state_onto_source, try_append_state_onto_source

    unsigned = spo._make_signed_pdf(tmp_path / "plain.pdf", signed=False)
    signed = spo._make_signed_pdf(tmp_path / "signed.pdf")
    doc = fitz.open(str(unsigned))
    try:
        assert try_append_state_onto_source(doc, unsigned, tmp_path / "s1.pdf") == "unsigned_source"
        assert append_state_onto_source(doc, unsigned, tmp_path / "s1.pdf") is False
    finally:
        doc.close()
    grown = fitz.open(str(signed))
    try:
        grown[1].insert_text((72, 300), "added", fontsize=12)
        with monkeypatch.context() as patch:
            patch.setattr(signed_append_save, "MAX_APPEND_GROWTH_SLOTS", 0)
            assert try_append_state_onto_source(grown, signed, tmp_path / "s2.pdf") == "object_limit"
        assert not (tmp_path / "s2.pdf").exists()
    finally:
        grown.close()
    state = fitz.open(str(signed))
    try:
        state[1].insert_text((72, 300), "added", fontsize=12)
        assert try_append_state_onto_source(state, signed, tmp_path / "s3.pdf") is None
        assert append_state_onto_source(state, signed, tmp_path / "s4.pdf") is True
    finally:
        state.close()


# ---------------------------------------------------------------- controller: ask, retry or cancel


def _signature_error(path: str = "doc.pdf") -> SignatureWouldBreakError:
    return SignatureWouldBreakError("secure_latch", Path(path))


def _controller(model: object) -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.view = MagicMock()
    controller._background_file_readers_released = lambda **_k: nullcontext()  # type: ignore[method-assign]
    controller._invalidate_inline_editor_preview = MagicMock()
    controller._refresh_document_tabs = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()
    controller.model = model
    return controller


def _mock_model(side_effect: list) -> MagicMock:
    model = MagicMock()
    model.saved_path = "doc.pdf"
    model.original_path = "doc.pdf"
    model.save_as.side_effect = list(side_effect)
    model.save_session_as.side_effect = list(side_effect)
    model.get_session_meta.return_value = {"path": "doc.pdf", "display_name": "doc.pdf"}
    model.get_active_session_id.return_value = "sid-a"
    return model


@pytest.fixture
def ui_spies(monkeypatch):
    spies = {"errors": [], "infos": [], "dialogs": [], "asked": []}
    monkeypatch.setattr(controller_module, "show_error", lambda _v, text: spies["errors"].append(text))
    monkeypatch.setattr(
        controller_module.QMessageBox, "information", lambda *a, **_k: spies["infos"].append(a)
    )

    def _dialog(*args, **_kwargs):
        spies["dialogs"].append(args)
        return ("other.pdf", "PDF (*.pdf)")

    monkeypatch.setattr(controller_module.QFileDialog, "getSaveFileName", _dialog)
    return spies


def _answer(controller: PDFController, spies: dict, answer: bool) -> None:
    def _confirm(exc, _session_id=None) -> bool:
        spies["asked"].append(exc.reason_code)
        return answer

    controller._confirm_signature_loss = _confirm  # type: ignore[method-assign]


@pytest.mark.parametrize("entry", ["save", "save_as"])
def test_controller_save_retries_with_consent(ui_spies, entry) -> None:
    controller = _controller(_mock_model([_signature_error(), None]))
    _answer(controller, ui_spies, True)

    getattr(controller, entry)(*(["doc.pdf"] if entry == "save_as" else []))

    assert ui_spies["asked"] == ["secure_latch"]
    calls = controller.model.save_as.call_args_list
    assert [c.args for c in calls] == [("doc.pdf",), ("doc.pdf",)]
    assert calls[0].kwargs == {}
    assert calls[1].kwargs == {"allow_signature_loss": True}
    assert ui_spies["errors"] == []
    if entry == "save":
        assert len(ui_spies["infos"]) == 1


@pytest.mark.parametrize("entry", ["save", "save_as"])
def test_controller_save_cancel_writes_nothing_and_says_nothing_else(ui_spies, entry) -> None:
    controller = _controller(_mock_model([_signature_error(), None]))
    _answer(controller, ui_spies, False)

    getattr(controller, entry)(*(["doc.pdf"] if entry == "save_as" else []))

    assert ui_spies["asked"] == ["secure_latch"]
    assert controller.model.save_as.call_count == 1
    assert ui_spies["errors"] == []
    assert ui_spies["infos"] == []
    assert ui_spies["dialogs"] == []


def test_close_save_cancel_keeps_the_tab_and_offers_no_save_dialog(ui_spies) -> None:
    controller = _controller(_mock_model([_signature_error(), None]))
    _answer(controller, ui_spies, False)

    assert controller._save_session_for_close("sid-b") is False

    assert ui_spies["asked"] == ["secure_latch"]
    assert ui_spies["dialogs"] == [], "a declined consent is not a failed save"
    assert ui_spies["errors"] == []
    controller.model.save_session_as.assert_called_once_with("sid-b", "doc.pdf")


def test_close_save_consent_retries_and_closes(ui_spies) -> None:
    controller = _controller(_mock_model([_signature_error(), None]))
    _answer(controller, ui_spies, True)

    assert controller._save_session_for_close("sid-b") is True

    calls = controller.model.save_session_as.call_args_list
    assert [c.args for c in calls] == [("sid-b", "doc.pdf"), ("sid-b", "doc.pdf")]
    assert calls[1].kwargs == {"allow_signature_loss": True}
    assert ui_spies["dialogs"] == []


@pytest.mark.parametrize("answer", [True, False])
def test_save_session_with_dialog_asks_too(ui_spies, answer) -> None:
    controller = _controller(_mock_model([_signature_error("other.pdf"), None]))
    _answer(controller, ui_spies, answer)

    assert controller._save_session_with_dialog("sid-b") is answer

    assert ui_spies["asked"] == ["secure_latch"]
    assert controller.model.save_session_as.call_count == (2 if answer else 1)
    assert ui_spies["errors"] == []


def test_a_consented_retry_that_fails_is_reported(ui_spies) -> None:
    controller = _controller(_mock_model([_signature_error(), PermissionError("locked")]))
    _answer(controller, ui_spies, True)

    controller.save()

    assert ui_spies["errors"] == ["儲存失敗: locked"]
    assert ui_spies["infos"] == []


def test_the_dialog_text_is_traditional_chinese_and_suggests_save_as() -> None:
    text, informative = PDFController._signature_loss_texts(_signature_error())
    assert "簽章" in text and "失效" in text
    assert "另存新檔" in informative
    for code in (
        "secure_latch",
        "source_changed",
        "source_missing",
        "incremental_disabled",
        "in_place_append_unavailable",
        "watermark_rewrite",
        "incremental_failed",
        "append_error",
        "verify_failed",
        "catalog_mismatch",
        "encryption_mismatch",
        "repaired_source",
        "object_limit",
        "some_future_code",
    ):
        line, _ = PDFController._signature_loss_texts(SignatureWouldBreakError(code, Path("doc.pdf")))
        assert code not in line, "technical codes go to the log, not the dialog"


def test_close_with_a_real_signed_model_cancel_keeps_file_and_edits(tmp_path, ui_spies) -> None:
    path = spo._make_signed_pdf(tmp_path / "signed.pdf")
    original = path.read_bytes()
    model = spo._open(path, incremental=True)
    try:
        spo._record_highlight(model)
        model.secure_save_required = True
        sid = model.get_active_session_id()
        controller = _controller(model)
        _answer(controller, ui_spies, False)
        assert controller._save_session_for_close(sid) is False
        assert path.read_bytes() == original
        assert model.session_has_unsaved_changes(sid)

        _answer(controller, ui_spies, True)
        assert controller._save_session_for_close(sid) is True
        assert not model.session_has_unsaved_changes(sid)
    finally:
        model.close()
    assert spo._eof_count(path) == 1
    assert spo._highlight_count(path) == 1


# ------------------------------------------- the dialog names the signed document (F12-DLG-1)


@pytest.fixture
def seen_dialogs(monkeypatch):
    """Capture what ``confirm_signature_loss`` is shown; every dialog answers Cancel."""
    seen: list[tuple[str, str]] = []

    def _confirm(_parent, text, informative) -> bool:
        seen.append((text, informative))
        return False

    monkeypatch.setattr(controller_module, "confirm_signature_loss", _confirm)
    return seen


def _two_tab_model(side_effect: list, active: str) -> MagicMock:
    model = _mock_model(side_effect)
    names = {"sid-signed": "Signed_Contract.pdf", "sid-plain": "Plain_Notes.pdf"}
    model.get_session_meta.side_effect = lambda sid: {"path": names[sid], "display_name": names[sid]}
    model.get_active_session_id.return_value = active
    return model


def test_texts_name_the_document_and_point_to_its_tab_only_when_it_is_not_active() -> None:
    text, informative = PDFController._signature_loss_texts(
        _signature_error(), "Signed_Contract.pdf", other_tab=True
    )
    assert "Signed_Contract.pdf" in text
    assert "Signed_Contract.pdf" in informative and "分頁" in informative
    assert "另存新檔" in informative

    text, informative = PDFController._signature_loss_texts(
        _signature_error(), "Signed_Contract.pdf", other_tab=False
    )
    assert "Signed_Contract.pdf" in text
    assert "分頁" not in informative, "the active tab is the signed one: no tab to switch to"

    text, informative = PDFController._signature_loss_texts(_signature_error(), None)
    assert "簽章" in text and "另存新檔" in informative  # an unknown name degrades, never raises


def test_close_loop_dialog_for_a_background_tab_names_that_tab(ui_spies, seen_dialogs) -> None:
    controller = _controller(_two_tab_model([_signature_error("Signed_Contract.pdf")], "sid-plain"))

    assert controller._save_session_for_close("sid-signed") is False

    (text, informative), = seen_dialogs
    assert "Signed_Contract.pdf" in text
    assert "Signed_Contract.pdf" in informative, "Save As acts on the ACTIVE tab: say which tab"
    assert "Plain_Notes.pdf" not in text + informative


def test_close_loop_dialog_for_the_active_tab_names_it_without_a_tab_switch(ui_spies, seen_dialogs) -> None:
    controller = _controller(_two_tab_model([_signature_error("Signed_Contract.pdf")], "sid-signed"))

    assert controller._save_session_for_close("sid-signed") is False

    (text, informative), = seen_dialogs
    assert "Signed_Contract.pdf" in text
    assert "分頁" not in informative


@pytest.mark.parametrize("entry", ["save", "save_as"])
def test_save_and_save_as_dialog_name_the_active_document(ui_spies, seen_dialogs, entry) -> None:
    controller = _controller(_two_tab_model([_signature_error("Signed_Contract.pdf")], "sid-signed"))
    controller.model.saved_path = "Signed_Contract.pdf"

    getattr(controller, entry)(*(["Signed_Contract.pdf"] if entry == "save_as" else []))

    (text, _informative), = seen_dialogs
    assert "Signed_Contract.pdf" in text


def test_save_session_with_dialog_names_the_session_not_the_active_tab(ui_spies, seen_dialogs) -> None:
    controller = _controller(_two_tab_model([_signature_error("other.pdf")], "sid-plain"))

    assert controller._save_session_with_dialog("sid-signed") is False

    (text, informative), = seen_dialogs
    assert "Signed_Contract.pdf" in text
    assert "Signed_Contract.pdf" in informative


def test_real_models_save_all_dialog_names_the_signed_background_tab(tmp_path, ui_spies, seen_dialogs) -> None:
    """The F12-DLG-1 shape with real sessions: the plain tab is active while the
    signed tab's secure-latch edit asks."""
    signed = spo._make_signed_pdf(tmp_path / "Signed_Contract.pdf")
    plain = tmp_path / "Plain_Notes.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "plain notes", fontsize=12.0)
    doc.save(str(plain))
    doc.close()
    model = spo._open(signed, incremental=True)
    try:
        signed_sid = model.get_active_session_id()
        spo._record_highlight(model)
        model.secure_save_required = True
        model.open_pdf(str(plain), append=True)
        assert model.get_active_session_id() != signed_sid
        controller = _controller(model)

        assert controller._save_session_for_close(signed_sid) is False

        (text, informative), = seen_dialogs
        assert "Signed_Contract.pdf" in text + informative
        assert "Plain_Notes.pdf" not in text + informative
        assert model.session_has_unsaved_changes(signed_sid)
    finally:
        model.close()
