"""ERR-1: the save error modals tell a lost session apart from a retryable failure.

A ``SaveRecoveryError`` (the live handle was closed for the install and nothing
could take its place) must reach the user as written - whether the file was
written and where the unsaved edits were kept - not as an ordinary
"儲存失敗: ..." that reads like a retry will work.
"""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import controller.pdf_controller as controller_module  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import SaveRecoveryError  # noqa: E402


def _controller(error: Exception) -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.view = MagicMock()
    controller._background_file_readers_released = lambda **_k: nullcontext()  # type: ignore[method-assign]
    controller._invalidate_inline_editor_preview = MagicMock()
    controller._refresh_document_tabs = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()
    model = MagicMock()
    model.saved_path = "doc.pdf"
    model.original_path = "doc.pdf"
    model.save_as.side_effect = error
    model.save_session_as.side_effect = error
    controller.model = model
    return controller


def _recovery_error() -> SaveRecoveryError:
    return SaveRecoveryError(
        "檔案已儲存至 doc.pdf，但無法重新開啟，備份副本：recover_x.pdf",
        recovery_path=Path("recover_x.pdf"),
        target_written=True,
    )


@pytest.mark.parametrize("entry", ["save", "save_as"])
def test_a_lost_session_is_reported_as_written_not_as_a_plain_failure(monkeypatch, entry) -> None:
    shown: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: shown.append(text))
    controller = _controller(_recovery_error())

    getattr(controller, entry)(*(["doc.pdf"] if entry == "save_as" else []))

    assert shown == ["檔案已儲存至 doc.pdf，但無法重新開啟，備份副本：recover_x.pdf"]


@pytest.mark.parametrize(("prefix", "expected"), [("儲存失敗", "儲存失敗: boom"), ("另存失敗", "另存失敗: boom")])
def test_an_ordinary_error_keeps_the_prefix(prefix, expected) -> None:
    assert PDFController._save_failure_text(prefix, PermissionError("boom")) == expected


def test_save_session_as_dialog_failure_also_reports_the_lost_session(monkeypatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: shown.append(text))
    monkeypatch.setattr(
        controller_module.QFileDialog, "getSaveFileName", lambda *_a, **_k: ("out.pdf", "PDF (*.pdf)")
    )
    controller = _controller(_recovery_error())
    controller.model.get_session_meta.return_value = {"path": "doc.pdf", "display_name": "doc.pdf"}
    controller.model.get_active_session_id.return_value = "sid-a"

    assert controller._save_session_with_dialog("sid-b") is False

    assert shown == ["檔案已儲存至 doc.pdf，但無法重新開啟，備份副本：recover_x.pdf"]


# ---------------------------------------------------------------- close / Save All path (R8-ERR1-CLOSE)


def _dialog_spy(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    def _dialog(*args, **_kwargs):
        calls.append(args)
        return ("out.pdf", "PDF (*.pdf)")

    monkeypatch.setattr(controller_module.QFileDialog, "getSaveFileName", _dialog)
    return calls


@pytest.mark.parametrize("target_written", [False, True], ids=["target_untouched", "target_written"])
def test_close_path_reports_a_lost_session_and_offers_no_dialog(monkeypatch, target_written) -> None:
    """Save All on close: the lost session's message is shown as written, the Save
    dialog is not offered for the dead handle, and the close is not allowed to go on
    (the recovery copy is the only copy of the edits)."""
    shown: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: shown.append(text))
    dialog_calls = _dialog_spy(monkeypatch)
    error = SaveRecoveryError(
        "recover_x.pdf holds the edits", recovery_path=Path("recover_x.pdf"), target_written=target_written
    )
    controller = _controller(error)
    controller.model.get_session_meta.return_value = {"path": "doc.pdf", "display_name": "doc.pdf"}
    controller.model.get_active_session_id.return_value = "sid-a"

    assert controller._save_session_for_close("sid-b") is False

    assert shown == ["recover_x.pdf holds the edits"]
    assert dialog_calls == []
    controller.model.save_session_as.assert_called_once_with("sid-b", "doc.pdf")


def test_close_path_ordinary_failure_still_falls_back_to_the_dialog(monkeypatch) -> None:
    """A retryable error keeps the old fallback: ask for another path, and save there."""
    shown: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: shown.append(text))
    dialog_calls = _dialog_spy(monkeypatch)
    controller = _controller(PermissionError("locked"))
    controller.model.get_session_meta.return_value = {"path": "doc.pdf", "display_name": "doc.pdf"}
    controller.model.get_active_session_id.return_value = "sid-a"
    controller.model.save_session_as.side_effect = [PermissionError("locked"), None]

    assert controller._save_session_for_close("sid-b") is True

    assert len(dialog_calls) == 1
    assert shown == []
    assert [c.args for c in controller.model.save_session_as.call_args_list] == [
        ("sid-b", "doc.pdf"),
        ("sid-b", "out.pdf"),
    ]


def test_close_path_with_a_real_model_names_the_recovery_copy(tmp_path, monkeypatch) -> None:
    """End to end on a real PDFModel: replace fails and no reopen works."""
    import fitz

    import model.pdf_model as pdf_model_module
    from model.pdf_model import PDFModel

    src = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(str(src))
    doc.close()

    model = PDFModel()
    model.open_pdf(str(src))
    model.use_incremental_save = False
    sid = model.get_active_session_id()
    try:
        model.doc[0].insert_text((72, 150), "MY EDIT", fontsize=12.0)
        model.edit_count += 1

        controller = PDFController.__new__(PDFController)
        controller.view = MagicMock()
        controller.model = model
        controller._background_file_readers_released = lambda **_k: nullcontext()  # type: ignore[method-assign]
        shown: list[str] = []
        monkeypatch.setattr(controller_module, "show_error", lambda _view, text: shown.append(text))
        dialog_calls = _dialog_spy(monkeypatch)

        real_replace = pdf_model_module.os.replace

        def _replace(src_path, dst, *a, **k):
            if Path(str(src_path)).name.startswith("."):
                raise PermissionError(13, "sharing violation (injected)")
            return real_replace(src_path, dst, *a, **k)

        def _reopen_fails(*_a, **_k):
            raise RuntimeError("reopen failed (injected)")

        with monkeypatch.context() as patch:
            patch.setattr(pdf_model_module.os, "replace", _replace)
            patch.setattr(model, "_reopen_doc_after_save", _reopen_fails)
            patch.setattr(model, "_open_recovery_in_memory", _reopen_fails)
            assert controller._save_session_for_close(sid) is False

        temp_root = Path(model.temp_dir.name)
        survivors = sorted(temp_root.glob("*.pdf"))
        assert len(survivors) == 1, "the only copy of the edits must survive"
        assert len(shown) == 1 and str(survivors[0]) in shown[0], "the user is told where the edits are"
        assert "document closed" not in shown[0]
        assert dialog_calls == []
    finally:
        model.close()


# ---------------------------------------------------------------- F10-FS-1: file changed on disk


def _changed_on_disk_error():
    from model.pdf_model import SourceChangedOnDiskError

    return SourceChangedOnDiskError("「doc.pdf」已被其他程式修改，請改用另存新檔。", path=Path("doc.pdf"))


@pytest.mark.parametrize("entry", ["save", "save_as"])
def test_a_save_refused_because_the_file_changed_on_disk_is_shown_as_written(monkeypatch, entry) -> None:
    shown: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: shown.append(text))
    controller = _controller(_changed_on_disk_error())

    getattr(controller, entry)(*(["doc.pdf"] if entry == "save_as" else []))

    assert shown == ["「doc.pdf」已被其他程式修改，請改用另存新檔。"]


def test_close_path_explains_a_changed_file_then_offers_save_as(monkeypatch) -> None:
    """Save All on close: the refusal is explained, then the Save dialog is the way out."""
    shown: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: shown.append(text))
    dialog_calls = _dialog_spy(monkeypatch)
    controller = _controller(_changed_on_disk_error())
    controller.model.get_session_meta.return_value = {"path": "doc.pdf", "display_name": "doc.pdf"}
    controller.model.get_active_session_id.return_value = "sid-a"
    controller.model.save_session_as.side_effect = [_changed_on_disk_error(), None]

    assert controller._save_session_for_close("sid-b") is True

    assert shown == ["「doc.pdf」已被其他程式修改，請改用另存新檔。"]
    assert len(dialog_calls) == 1
    assert [c.args for c in controller.model.save_session_as.call_args_list] == [
        ("sid-b", "doc.pdf"),
        ("sid-b", "out.pdf"),
    ]


# ---------------------------------------------------------------- S14-SAVEREC-DEAD-TAB: the tab that lost its document
#
# Owner decision C: after a SaveRecoveryError the session sits on a CLOSED handle
# (``bool(closed_doc)`` raises ``document closed``).  It must be a visibly dead
# tab: no slot touches the handle, a retry keeps the recovery-path message, and
# only Save As (copies the recovery file) and Discard are offered.
#
# RED/GUARD per test: the ids ending in ``_guard`` pass before the fix too.

_RECOVERY_TEXT = "尚未儲存的編輯已保留於暫存副本"


def _pump(ms: int = 60) -> None:
    import time

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def _write_pdf(path: Path, pages: int = 3) -> Path:
    import fitz

    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"Page {i + 1}", fontsize=12.0)
    doc.save(str(path))
    doc.close()
    return path


class _LostTab:
    """A real PDFModel / PDFView / PDFController whose active tab lost its document."""

    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


@pytest.fixture
def lost_tab(monkeypatch, qapp, tmp_path):
    """Drive a Ctrl+S that fails twice: the replace is refused and no reopen works."""
    import model.pdf_model as pdf_model_module
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    escaped: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: escaped.append(f"{t.__name__}: {v}"))
    errors: list[str] = []
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, text: errors.append(text))
    monkeypatch.setattr(
        controller_module.QMessageBox, "information", staticmethod(lambda _p, title, text: infos.append((title, text)))
    )

    pdf = _write_pdf(tmp_path / "doc.pdf")
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    try:
        controller.open_pdf(str(pdf))
        _pump(200)
        sid = model.get_active_session_id()
        controller.delete_pages([3])  # latches the secure (full rewrite) save
        _pump(60)

        real_replace = pdf_model_module.replace_file

        def refuse_target(src, dst, *a, **k):
            if Path(dst).resolve() == pdf.resolve():
                raise PermissionError(13, "sharing violation (injected)", str(dst))
            return real_replace(src, dst, *a, **k)

        def reopen_fails(*_a, **_k):
            raise RuntimeError("reopen failed (injected)")

        with monkeypatch.context() as patch:
            patch.setattr(pdf_model_module, "replace_file", refuse_target)
            patch.setattr(model, "_reopen_doc_after_save", reopen_fails)
            patch.setattr(model, "_open_recovery_in_memory", reopen_fails)
            controller.save()
        _pump(60)
        first_error = errors[-1] if errors else ""
        errors.clear()
        infos.clear()
        escaped.clear()
        yield _LostTab(
            controller=controller,
            model=model,
            view=view,
            sid=sid,
            pdf=pdf,
            tmp=tmp_path,
            escaped=escaped,
            errors=errors,
            infos=infos,
            first_error=first_error,
        )
    finally:
        model.close()
        view.close()
        _pump(50)


def test_first_failed_save_makes_a_visibly_dead_tab(lost_tab) -> None:
    """The failed save names the recovery copy AND marks the tab / view as lost."""
    t = lost_tab
    assert _RECOVERY_TEXT in t.first_error
    assert t.model.is_session_lost(t.sid)
    assert t.model.doc is None, "a closed handle must never be handed out"
    assert any(t.view.document_tab_bar.tabText(i).endswith("（已中斷）") for i in range(t.view.document_tab_bar.count()))
    assert t.view.total_pages == 0, "editing is off: the view has no pages"
    assert t.view._lost_session_proxy is not None, "the notice is shown in place of the document"
    assert "已中斷" in t.view.status_bar.currentMessage()
    assert not t.escaped


def test_second_save_keeps_the_recovery_path_message(lost_tab) -> None:
    t = lost_tab
    recovery = t.model.lost_session_error(t.sid).recovery_path

    t.controller.save()
    t.controller.save()

    assert len(t.errors) == 2
    for text in t.errors:
        assert _RECOVERY_TEXT in text and str(recovery) in text
        assert "document closed" not in text
    assert recovery.is_file(), "the only copy of the edits survives every retry"


def test_model_save_as_and_save_session_as_re_raise_the_loss(lost_tab) -> None:
    from model.pdf_model import SaveRecoveryError

    t = lost_tab
    recovery = t.model.lost_session_error(t.sid).recovery_path

    for call in (
        lambda: t.model.save_as(str(t.tmp / "x.pdf")),
        lambda: t.model.save_session_as(t.sid, str(t.tmp / "y.pdf")),
    ):
        with pytest.raises(SaveRecoveryError) as raised:
            call()
        assert raised.value.recovery_path == recovery
        assert raised.value.target_written is False
    assert not (t.tmp / "x.pdf").exists() and not (t.tmp / "y.pdf").exists()


def test_save_as_on_a_lost_tab_copies_the_recovery_file_and_shows_both_paths(lost_tab) -> None:
    import fitz

    t = lost_tab
    recovery = t.model.lost_session_error(t.sid).recovery_path
    target = t.tmp / "rescued.pdf"

    t.controller.save_as(str(target))

    assert target.is_file()
    with fitz.open(str(target)) as copy:
        assert len(copy) == 2, "the copy holds the unsaved edit (page 3 was deleted)"
    assert t.errors == []
    assert len(t.infos) == 1
    assert str(target) in t.infos[0][1] and str(recovery) in t.infos[0][1]
    assert t.model.is_session_lost(t.sid), "Save As does not revive the tab"
    assert recovery.is_file()


def test_failed_copy_shows_the_recovery_path_again(lost_tab, monkeypatch) -> None:
    import model.pdf_model as pdf_model_module

    t = lost_tab

    def refuse(*_a, **_k):
        raise PermissionError(13, "disk is read-only (injected)")

    monkeypatch.setattr(pdf_model_module, "replace_file", refuse)
    t.controller.save_as(str(t.tmp / "rescued.pdf"))

    assert len(t.errors) == 1
    assert "disk is read-only" in t.errors[0] and _RECOVERY_TEXT in t.errors[0]
    assert not (t.tmp / "rescued.pdf").exists()
    assert t.infos == []


@pytest.mark.parametrize(
    ("emit", "args"),
    [
        ("sig_page_changed", (1,)),
        ("sig_bookmark_activated", (1,)),
        ("sig_scale_changed", (0, 1.5)),
        ("sig_rotate_pages", ([1], 90)),
        ("sig_delete_pages", ([1],)),
        ("sig_undo", ()),
        ("sig_redo", ()),
        ("sig_search", ("Page",)),
        ("sig_viewport_changed", ()),
        ("sig_request_rerender", ()),
        ("sig_snapshot_page", (0,)),
        ("sig_insert_blank_page", (1,)),
        ("sig_print_requested", ()),
        ("sig_request_metadata_editor", ()),
    ],
)
def test_signal_slots_do_nothing_on_a_lost_tab(lost_tab, emit, args) -> None:
    """None of the view's signals reaches a closed handle (no ``document closed``)."""
    t = lost_tab
    pages_in_recovery = t.model.lost_session_error(t.sid)

    getattr(t.view, emit).emit(*args)
    _pump(30)

    assert t.escaped == [], t.escaped
    assert t.errors == []
    assert t.model.lost_session_error(t.sid) is pages_in_recovery
    assert t.model.session_has_unsaved_changes(t.sid) is True, "nothing was edited or undone"


def test_live_tab_signals_still_reach_their_slots_guard(monkeypatch, qapp, tmp_path) -> None:
    """The wrapper trims signal arguments like Qt does and passes live sessions through."""
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    escaped: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: escaped.append(f"{t.__name__}: {v}"))
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    try:
        controller.open_pdf(str(_write_pdf(tmp_path / "live.pdf")))
        _pump(200)
        view.sig_rotate_pages.emit([1], 90)
        view.sig_page_changed.emit(2)
        _pump(60)
        assert model.doc[0].rotation == 90
        assert controller._get_ui_state(model.get_active_session_id()).current_page == 2
        assert escaped == []
    finally:
        model.close()
        view.close()
        _pump(50)


def test_live_only_passes_only_the_arguments_the_slot_accepts_guard() -> None:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.session_lost = False
    seen: list[tuple] = []

    def one_arg(a):
        seen.append((a,))

    def any_args(*a):
        seen.append(a)

    controller._live_only(one_arg)(1, 2, 3)
    controller._live_only(any_args)(1, 2, 3)

    assert seen == [(1,), (1, 2, 3)]
    controller.model.session_lost = True
    controller._live_only(one_arg)(9)
    assert seen == [(1,), (1, 2, 3)], "a lost session drops the call"


def test_is_lost_reads_a_model_without_the_lost_session_api_as_live_guard() -> None:
    """GATE14-1: a controller test double that predates the lost-session API is a live model.

    ``_is_lost`` is the one chokepoint in front of every guarded slot, save,
    close, detach and render.  A model that answers neither ``session_lost`` nor
    ``is_session_lost`` (a ``SimpleNamespace`` double) never raises and is never
    lost; only a real ``True`` from the model marks a lost session.
    """
    from types import SimpleNamespace

    controller = PDFController.__new__(PDFController)
    controller.model = SimpleNamespace()
    assert controller._is_lost() is False
    assert controller._is_lost("sid") is False

    ran: list[int] = []
    controller._live_only(lambda: ran.append(1))()
    assert ran == [1], "a model without the API must not drop the slot"

    controller.model = SimpleNamespace(session_lost=True, is_session_lost=lambda sid: sid == "dead")
    assert controller._is_lost() is True
    assert controller._is_lost("dead") is True
    assert controller._is_lost("other") is False

    controller.model = MagicMock()  # a truthy-for-everything double is not a lost tab
    assert controller._is_lost() is False
    assert controller._is_lost("sid") is False


def test_pdf_model_exposes_every_lost_session_name_the_controller_reads_guard() -> None:
    """GATE14-1: ``_is_lost`` tolerates a missing API, so a renamed model name must fail HERE.

    Without this a rename of ``session_lost`` / ``is_session_lost`` on the model
    would silently turn the controller's guard off.
    """
    from model.pdf_model import PDFModel

    assert isinstance(PDFModel.session_lost, property)
    assert callable(PDFModel.is_session_lost)
    assert callable(PDFModel.lost_session_error)
    model = PDFModel()
    try:
        assert model.session_lost is False
        assert model.is_session_lost("no-such-session") is False
        assert model.lost_session_error() is None
        controller = PDFController.__new__(PDFController)
        controller.model = model
        assert controller._is_lost() is False
        assert controller._is_lost("no-such-session") is False
    finally:
        model.close()


def test_tab_switch_shows_the_dead_tab_and_back_restores_a_live_one(lost_tab) -> None:
    t = lost_tab
    other = _write_pdf(t.tmp / "other.pdf", pages=2)
    t.controller.open_pdf(str(other))
    _pump(200)
    live_sid = t.model.get_active_session_id()
    assert live_sid != t.sid and not t.model.is_session_lost(live_sid)
    assert t.view._lost_session_proxy is None

    t.controller.on_tab_changed(t.model.session_ids.index(t.sid))
    _pump(60)
    assert t.model.get_active_session_id() == t.sid
    assert t.view._lost_session_proxy is not None and t.view.total_pages == 0
    assert t.model.doc is None

    t.controller.on_tab_changed(t.model.session_ids.index(live_sid))
    _pump(200)
    assert t.model.get_active_session_id() == live_sid
    assert t.view._lost_session_proxy is None and t.view._lost_session_status is None
    assert t.view.total_pages == 2
    assert len(t.model.doc) == 2
    assert t.escaped == [], t.escaped


def test_closing_a_lost_tab_with_discard_keeps_the_recovery_file_until_exit(lost_tab, monkeypatch) -> None:
    t = lost_tab
    recovery = t.model.lost_session_error(t.sid).recovery_path

    class _Box:
        AcceptRole = DestructiveRole = RejectRole = Warning = 0

        def __init__(self, *_a) -> None:
            self.buttons: dict[str, object] = {}

        def addButton(self, text, _role):
            self.buttons[text] = object()
            return self.buttons[text]

        def setWindowTitle(self, *_a): ...
        def setText(self, *_a): ...
        def setInformativeText(self, text):
            _Box.shown = text

        def setDefaultButton(self, *_a): ...
        def setIcon(self, *_a): ...
        def exec(self): ...

        def clickedButton(self):
            return self.buttons["放棄並關閉"]

        information = staticmethod(lambda _p, title, text: t.infos.append((title, text)))

    monkeypatch.setattr(controller_module, "QMessageBox", _Box)

    t.controller.on_tab_close_requested(t.model.session_ids.index(t.sid))

    assert t.sid not in t.model.session_ids
    assert str(recovery) in _Box.shown, "the close prompt names the recovery copy"
    assert any(str(recovery) in text for _title, text in t.infos), "Discard shows the path again"
    assert recovery.is_file(), "discarding the tab does not delete the only copy of the edits"
    t.model.close()
    assert not recovery.exists(), "the model's temp dir (and the copy) goes at exit"


class _AppCloseEvent:
    def __init__(self) -> None:
        self.accepted: bool | None = None

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


def _patch_app_close_box(monkeypatch, t, choice: str) -> dict[str, list[str]]:
    """Replace the controller's QMessageBox with a stub that answers ``choice``."""
    seen: dict[str, list[str]] = {"text": [], "informative": []}

    class _Box:
        AcceptRole = DestructiveRole = RejectRole = Warning = 0

        def __init__(self, *_a) -> None:
            self.buttons: dict[str, object] = {}

        def addButton(self, text, _role):
            self.buttons[text] = object()
            return self.buttons[text]

        def setWindowTitle(self, *_a): ...
        def setText(self, text):
            seen["text"].append(text)

        def setInformativeText(self, text):
            seen["informative"].append(text)

        def setDefaultButton(self, *_a): ...
        def setIcon(self, *_a): ...
        def exec(self): ...

        def clickedButton(self):
            return self.buttons[choice]

        information = staticmethod(lambda _p, title, text: t.infos.append((title, text)))

    monkeypatch.setattr(controller_module, "QMessageBox", _Box)
    monkeypatch.setattr(PDFController, "_attach_yes_no_shortcuts", lambda *_a, **_k: None)
    return seen


def test_window_close_discard_all_shows_the_lost_tabs_recovery_path(lost_tab, monkeypatch) -> None:
    """F15-DEADTAB-APPCLOSE: 全部放棄 on window close names the recovery copy, like the single-tab close."""
    t = lost_tab
    recovery = t.model.lost_session_error(t.sid).recovery_path
    seen = _patch_app_close_box(monkeypatch, t, "全部放棄")
    event = _AppCloseEvent()

    t.controller.handle_app_close(event)

    assert event.accepted is True
    assert any(str(recovery) in text for text in seen["informative"]), "the prompt itself names the lost tab's copy"
    assert any(str(recovery) in text for _title, text in t.infos), "Discard all shows the path again"
    assert recovery.is_file(), "closing the window does not delete the only copy of the edits"
    t.model.close()
    assert not recovery.exists(), "the model's temp dir (and the copy) goes at exit"


def test_window_close_cancel_keeps_the_lost_tab_and_shows_no_discard_notice(lost_tab, monkeypatch) -> None:
    t = lost_tab
    _patch_app_close_box(monkeypatch, t, "取消")
    event = _AppCloseEvent()

    t.controller.handle_app_close(event)

    assert event.accepted is False
    assert t.sid in t.model.session_ids
    assert t.infos == []


def test_window_close_discard_all_without_a_lost_tab_shows_no_recovery_notice_guard(
    qapp, monkeypatch, tmp_path
) -> None:
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    pdf = _write_pdf(tmp_path / "live.pdf")
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    infos: list[tuple[str, str]] = []
    holder = _LostTab(infos=infos)
    try:
        controller.open_pdf(str(pdf))
        _pump(200)
        controller.delete_pages([3])
        _pump(60)
        assert model.get_dirty_session_ids()
        _patch_app_close_box(monkeypatch, holder, "全部放棄")
        event = _AppCloseEvent()

        controller.handle_app_close(event)

        assert event.accepted is True
        assert infos == []
    finally:
        model.close()
        view.close()


def test_reopening_the_file_starts_a_live_tab_and_closing_the_dead_one_keeps_it(lost_tab, monkeypatch) -> None:
    t = lost_tab

    t.controller.open_pdf(str(t.pdf))
    _pump(200)

    new_sid = t.model.get_active_session_id()
    assert new_sid != t.sid and not t.model.is_session_lost(new_sid)
    assert len(t.model.doc) == 3
    t.model.close_session(t.sid)
    assert t.model.find_session_by_path(str(t.pdf)) == new_sid, "closing the dead tab leaves the new tab's path"


def test_detach_refuses_a_lost_tab(lost_tab) -> None:
    t = lost_tab
    handed: list[object] = []
    t.controller.set_session_handoff_callback(lambda payload, pos: handed.append(payload) or True)

    t.controller.detach_document_session(t.sid, None)

    assert handed == []
    assert t.sid in t.model.session_ids
    assert len(t.errors) == 1
    assert t.escaped == []


def test_close_path_copies_the_recovery_file_for_a_lost_tab(lost_tab, monkeypatch) -> None:
    """Save All on close: no in-place save is attempted; the dialog target gets the recovery copy."""
    t = lost_tab
    target = t.tmp / "from_close.pdf"
    monkeypatch.setattr(
        controller_module.QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(target), "PDF (*.pdf)")
    )

    assert t.controller._save_session_for_close(t.sid) is True

    assert target.is_file()
    assert t.errors == []


def test_session_meta_marks_a_lost_tab(lost_tab) -> None:
    t = lost_tab
    meta = t.model.get_session_meta(t.sid)
    assert meta["lost"] is True
    assert meta["recovery_path"] == str(t.model.lost_session_error(t.sid).recovery_path)
    assert [m["lost"] for m in t.model.list_sessions()] == [True]


def test_copy_refuses_a_target_another_tab_has_open(lost_tab) -> None:
    t = lost_tab
    other = _write_pdf(t.tmp / "other.pdf", pages=1)
    t.controller.open_pdf(str(other))
    _pump(200)
    t.model.activate_session(t.sid)

    with pytest.raises(RuntimeError, match="其他分頁"):
        t.model.copy_lost_session_recovery(str(other))
    assert other.stat().st_size > 0


def test_copy_refuses_a_session_that_is_not_lost_guard(tmp_path) -> None:
    from model.pdf_model import PDFModel

    model = PDFModel()
    try:
        model.open_pdf(str(_write_pdf(tmp_path / "ok.pdf", pages=1)))
        assert model.session_lost is False
        with pytest.raises(RuntimeError, match="沒有中斷"):
            model.copy_lost_session_recovery(str(tmp_path / "out.pdf"))
        assert not (tmp_path / "out.pdf").exists()
    finally:
        model.close()
