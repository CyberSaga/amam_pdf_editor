from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication, QDialog

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _pump_events(ms: int = 100) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _reorder_list_widget(dialog, from_row: int, to_row: int) -> None:
    item = dialog.file_list.takeItem(from_row)
    assert item is not None
    dialog.file_list.insertItem(to_row, item)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def mvc(monkeypatch, qapp):
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)

    from controller.pdf_controller import PDFController
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    yield model, view, controller
    model.close()
    view.close()
    _pump_events(50)


def test_merge_session_keeps_current_entry_locked_and_appends_new_files() -> None:
    from model.merge_session import MergeSessionModel

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")

    session.add_files(
        [
            str(Path("C:/tmp/B.pdf")),
            str(Path("C:/tmp/C.pdf")),
        ]
    )

    assert [entry.display_name for entry in session.entries] == [
        "Current.pdf",
        "B.pdf",
        "C.pdf",
    ]
    assert session.entries[0].locked is True
    assert session.remove_selected([0]) == []


def test_save_merged_copy_uses_model_external_persistence_policy(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    output = tmp_path / "merged.pdf"
    controller.open_pdf(str(current))
    _pump_events(100)

    calls: list[tuple[int, Path]] = []

    def _save(doc, path, *, sanitize=None):
        calls.append((len(doc), Path(path)))
        doc.save(str(path), garbage=4)

    monkeypatch.setattr(model, "save_external_document", _save)
    monkeypatch.setattr(controller, "open_pdf", lambda _path: None)
    controller.save_ordered_sources_as_new([{"source_kind": "current"}], str(output))

    assert calls == [(1, output)]


def test_start_merge_pdfs_seeds_dialog_with_current_document(mvc, monkeypatch, tmp_path: Path) -> None:
    _model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["alpha"])
    controller.open_pdf(str(current))
    _pump_events(100)

    observed: dict[str, list[str]] = {}
    import view.pdf_view as pdf_view_module

    def fake_exec(self) -> int:
        observed["entries"] = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        return QDialog.Rejected

    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "exec", fake_exec)

    controller.start_merge_pdfs()

    assert observed["entries"] == ["Current.pdf"]


def test_merge_ordered_sources_into_current_replaces_active_document_in_list_order(
    mvc,
    tmp_path: Path,
) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    controller.open_pdf(str(current))
    _pump_events(100)

    controller.merge_ordered_sources_into_current(
        [
            {"source_kind": "file", "path": str(extra)},
            {"source_kind": "current"},
        ]
    )

    assert len(model.doc) == 2
    first_text = model.doc[0].get_text("text")
    second_text = model.doc[1].get_text("text")
    assert "extra page" in first_text
    assert "current page" in second_text
    assert model.has_unsaved_changes() is True


def test_merge_into_current_never_serializes_through_a_python_file_object(
    mvc, tmp_path: Path, monkeypatch
) -> None:
    """H10-2 Part B: the merged document's bytes come from the model's native-sink
    serializer, not ``save(io.BytesIO)`` in the controller (~4.5 us per xref row)."""
    import pymupdf

    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    controller.open_pdf(str(current))
    _pump_events(100)

    def _refuse(*_args, **_kwargs):
        raise RuntimeError("serialized through PyMuPDF's Python file-object sink")

    monkeypatch.setattr(pymupdf, "JM_new_output_fileptr", _refuse)
    controller.merge_ordered_sources_into_current(
        [{"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}]
    )

    assert len(model.doc) == 2
    assert "extra page" in model.doc[0].get_text("text")


def _merge_extra_above_current_with_primed_cache(mvc, tmp_path: Path):
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["CURRENT ONE", "CURRENT TWO"])
    other = _make_pdf(tmp_path / "Other.pdf", ["OTHER ALPHA"])
    controller.open_pdf(str(current))
    _pump_events(300)
    sid = model.get_active_session_id()
    # Prime the revision-keyed worker snapshot cache the way search/OCR/render do.
    controller.capture_worker_snapshot_bytes()
    rev_before = controller._render_revision(sid)
    controller.merge_ordered_sources_into_current(
        [
            {"source_kind": "file", "path": str(other)},
            {"source_kind": "current"},
        ]
    )
    return model, controller, sid, rev_before


def test_merge_into_current_bumps_render_revision_and_page_sizes(mvc, tmp_path: Path) -> None:
    """DS-2: the merge replaces the live doc, so every revision-keyed cache must die."""
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["CURRENT ONE", "CURRENT TWO"])
    controller.open_pdf(str(current))
    _pump_events(300)
    sid = model.get_active_session_id()
    controller._page_sizes_by_session[sid] = [(1.0, 1.0)]
    rev_before = controller._render_revision(sid)
    other = _make_pdf(tmp_path / "Other.pdf", ["OTHER ALPHA"])

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "file", "path": str(other)}, {"source_kind": "current"}]
    )

    assert len(model.doc) == 3
    assert controller._render_revision(sid) > rev_before
    assert sid not in controller._page_sizes_by_session or controller._page_sizes_by_session[sid] != [(1.0, 1.0)]


def test_merge_into_current_worker_snapshot_matches_live_doc(mvc, tmp_path: Path) -> None:
    model, controller, _sid, _rev = _merge_extra_above_current_with_primed_cache(mvc, tmp_path)
    snap = fitz.open("pdf", controller.capture_worker_snapshot_bytes())
    try:
        assert len(snap) == len(model.doc) == 3
        assert "OTHER ALPHA" in snap[0].get_text("text")
    finally:
        snap.close()


def test_search_after_merge_into_current_uses_merged_document(mvc, tmp_path: Path) -> None:
    model, controller, sid, _rev = _merge_extra_above_current_with_primed_cache(mvc, tmp_path)
    assert "OTHER ALPHA" in model.doc[0].get_text("text")

    controller.search_text("OTHER ALPHA")
    _pump_events(1500)
    hits = controller._get_ui_state(sid).search_state.get("results") or []
    assert hits, "search for text from the merged-in file must find it"

    controller.search_text("CURRENT ONE")
    _pump_events(1500)
    stale = controller._get_ui_state(sid).search_state.get("results") or []
    assert [h for h in stale if h[0] == 1] == [], "text no longer on page 1 must not be reported there"


def test_every_live_document_replacement_in_controller_bumps_render_revision() -> None:
    """Bug-class guard (DS-2): a controller method that swaps the live document from
    snapshot bytes must also call ``_invalidate_active_render_state``."""
    source = (REPO_ROOT / "controller" / "pdf_controller.py").read_text(encoding="utf-8")
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        called = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        if "replace_active_document_from_snapshot" in called and "_invalidate_active_render_state" not in called:
            offenders.append(node.name)
    assert offenders == []


def test_merge_dialog_appends_picker_results_and_deletes_only_unlocked_rows(monkeypatch, qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    dialog = MergePdfDialog(session)

    picks = iter(
        [
            ([str(Path("C:/tmp/B.pdf")), str(Path("C:/tmp/C.pdf"))], "PDF (*.pdf)"),
            ([str(Path("C:/tmp/D.pdf"))], "PDF (*.pdf)"),
        ]
    )
    monkeypatch.setattr("view.pdf_view.QFileDialog.getOpenFileNames", lambda *args, **kwargs: next(picks))

    dialog._select_files()
    dialog._select_files()

    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "B.pdf",
        "C.pdf",
        "D.pdf",
    ]

    dialog.file_list.setCurrentRow(0)
    dialog._delete_selected()
    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "B.pdf",
        "C.pdf",
        "D.pdf",
    ]

    dialog.file_list.setCurrentRow(2)
    dialog._delete_selected()
    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "B.pdf",
        "D.pdf",
    ]
    assert dialog.confirm_button.isEnabled() is True


def test_save_ordered_sources_as_new_opens_merged_result_as_new_tab(mvc, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    out_path = tmp_path / "Merged.pdf"

    controller.open_pdf(str(current))
    _pump_events(100)

    controller.save_ordered_sources_as_new(
        [
            {"source_kind": "current"},
            {"source_kind": "file", "path": str(extra)},
        ],
        str(out_path),
    )
    _pump_events(100)

    assert out_path.exists() is True
    assert len(model.session_ids) == 2
    assert model.get_active_session_id() is not None
    merged_text = "".join(model.doc[i].get_text("text") for i in range(len(model.doc)))
    assert "current page" in merged_text
    assert "extra page" in merged_text


def test_resolve_merge_file_retries_password_and_skips_on_cancel(mvc, monkeypatch) -> None:
    from model.pdf_model import PdfPasswordRejectedError, PdfPasswordRequiredError

    _model, view, controller = mvc
    prompts = iter(["wrong", None])
    monkeypatch.setattr(view, "ask_pdf_password", lambda path: next(prompts))

    errors: list[str] = []
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *_args: errors.append(_args[-1]))

    attempts: list[str | None] = []

    def fake_open_merge_source(path: str, password: str | None = None):
        attempts.append(password)
        if password is None:
            raise PdfPasswordRequiredError("document closed or encrypted — 需要密碼")
        if password == "wrong":
            raise PdfPasswordRejectedError("PDF 密碼驗證失敗（authenticate 回傳 0）: locked.pdf")
        return {"path": path, "password": password}

    monkeypatch.setattr(controller.model, "open_merge_source", fake_open_merge_source, raising=False)

    result = controller._resolve_merge_file({"source_kind": "file", "path": "locked.pdf"})

    assert result is None
    assert attempts == [None, "wrong"]
    assert any("密碼錯誤" in msg for msg in errors)


def test_start_merge_pdfs_accepts_dialog_and_saves_new_file(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    output = tmp_path / "MergedFromDialog.pdf"
    controller.open_pdf(str(current))
    _pump_events(100)

    import view.pdf_view as pdf_view_module

    def fake_exec(self) -> int:
        self.session_model.add_files([str(extra)])
        self._refresh_file_list()
        self.new_file_radio.setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "exec", fake_exec)
    monkeypatch.setattr(
        "controller.pdf_controller.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "PDF (*.pdf)")),
    )

    controller.start_merge_pdfs()
    _pump_events(100)

    assert output.exists() is True
    assert len(model.session_ids) == 2
    merged_text = "".join(model.doc[i].get_text("text") for i in range(len(model.doc)))
    assert "current page" in merged_text
    assert "extra page" in merged_text


def test_start_merge_pdfs_passes_controller_resolver_into_dialog(mvc, monkeypatch, tmp_path: Path) -> None:
    _model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    controller.open_pdf(str(current))
    _pump_events(100)

    import view.pdf_view as pdf_view_module

    observed: dict[str, object] = {}
    original_init = pdf_view_module.MergePdfDialog.__init__

    def fake_init(self, session_model, parent=None, file_resolver=None, progress_factory=None):
        observed["resolver"] = file_resolver
        return original_init(
            self,
            session_model,
            parent=parent,
            file_resolver=file_resolver,
            progress_factory=progress_factory,
        )

    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "__init__", fake_init)
    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "exec", lambda self: QDialog.Rejected)

    controller.start_merge_pdfs()

    assert observed["resolver"] == controller._resolve_merge_file


def test_merge_dialog_validates_selected_files_before_appending(monkeypatch, qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    resolved_calls: list[str] = []

    def resolver(entry: dict) -> dict | None:
        path = entry["path"]
        resolved_calls.append(path)
        if path.endswith("bad.pdf"):
            return None
        return {
            "source_kind": "file",
            "path": path,
            "display_name": Path(path).name,
            "password": "pw" if path.endswith("locked.pdf") else None,
        }

    dialog = MergePdfDialog(session, file_resolver=resolver)
    monkeypatch.setattr(
        "view.pdf_view.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: (
            [str(Path("C:/tmp/bad.pdf")), str(Path("C:/tmp/locked.pdf")), str(Path("C:/tmp/ok.pdf"))],
            "PDF (*.pdf)",
        ),
    )

    dialog._select_files()

    assert resolved_calls == [
        str(Path("C:/tmp/bad.pdf")),
        str(Path("C:/tmp/locked.pdf")),
        str(Path("C:/tmp/ok.pdf")),
    ]
    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "locked.pdf",
        "ok.pdf",
    ]


def test_merge_dialog_updates_progress_while_processing_picker_batch(monkeypatch, qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    progress_values: list[int] = []

    class FakeProgress:
        def __init__(self):
            self.closed = False

        def setValue(self, value: int) -> None:
            progress_values.append(value)

        def wasCanceled(self) -> bool:
            return False

        def show(self) -> None:
            progress_values.append(-1)

        def close(self) -> None:
            self.closed = True
            progress_values.append(-2)

    dialog = MergePdfDialog(
        session,
        file_resolver=lambda entry: {
            "source_kind": "file",
            "path": entry["path"],
            "display_name": Path(entry["path"]).name,
        },
        progress_factory=lambda total: FakeProgress(),
    )
    monkeypatch.setattr(
        "view.pdf_view.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: (
            [str(Path("C:/tmp/one.pdf")), str(Path("C:/tmp/two.pdf"))],
            "PDF (*.pdf)",
        ),
    )

    dialog._select_files()

    assert progress_values == [-1, 0, 1, 2, -2]


def test_merge_dialog_preserves_reordered_list_when_adding_files(monkeypatch, qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    session.add_files(
        [
            str(Path("C:/tmp/B.pdf")),
            str(Path("C:/tmp/C.pdf")),
        ]
    )
    dialog = MergePdfDialog(session)

    _reorder_list_widget(dialog, 2, 1)

    monkeypatch.setattr(
        "view.pdf_view.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(Path("C:/tmp/D.pdf"))], "PDF (*.pdf)"),
    )

    dialog._select_files()

    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "C.pdf",
        "B.pdf",
        "D.pdf",
    ]


def test_merge_dialog_preserves_reordered_list_when_removing_files(qapp) -> None:
    from model.merge_session import MergeSessionModel
    from view.pdf_view import MergePdfDialog

    session = MergeSessionModel(current_label="Current.pdf", current_source_id="active")
    session.add_files(
        [
            str(Path("C:/tmp/B.pdf")),
            str(Path("C:/tmp/C.pdf")),
            str(Path("C:/tmp/D.pdf")),
        ]
    )
    dialog = MergePdfDialog(session)

    _reorder_list_widget(dialog, 3, 1)
    dialog.file_list.setCurrentRow(2)

    dialog._delete_selected()

    assert [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())] == [
        "Current.pdf",
        "D.pdf",
        "C.pdf",
    ]


# --- F11-OPEN-3: password retry is decided by a typed error, never by the path ---------------
#
# Model errors embed the user's path.  Classifying "password needed" by a substring of the
# message made a corrupt/missing file under ``Unencrypted Exports\`` loop on password prompts
# and hid the real error; a wrong password for such a path skipped the "wrong password" notice.

_TRICKY_DIR = "Unencrypted Exports"


def _tricky_path(tmp_path: Path, name: str = "report.pdf") -> Path:
    folder = tmp_path / _TRICKY_DIR
    folder.mkdir()
    return folder / name


def _encrypted_pdf_at(path: Path, user_pw: str) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "secret page", fontsize=12, fontname="helv")
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw="owner")
    doc.close()
    return path


def _capture_prompts_and_errors(view, monkeypatch, answers: list[str | None]):
    prompts: list[str] = []
    errors: list[str] = []
    replies = iter(answers)

    def _ask(path: str) -> str | None:
        prompts.append(path)
        return next(replies, None)

    monkeypatch.setattr(view, "ask_pdf_password", _ask)
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: errors.append(a[-1]))
    return prompts, errors


@pytest.mark.parametrize("kind", ["corrupt", "missing"])
def test_open_pdf_unreadable_file_under_encrypted_named_path_shows_error_not_password_prompt(
    mvc, monkeypatch, tmp_path: Path, kind: str
) -> None:
    model, view, controller = mvc
    target = _tricky_path(tmp_path)
    if kind == "corrupt":
        target.write_bytes(b"this is not a pdf at all")
    prompts, errors = _capture_prompts_and_errors(view, monkeypatch, ["guess", "guess", None])

    controller.open_pdf(str(target))

    assert prompts == []
    assert len(errors) == 1 and "打開 PDF 失敗" in errors[0]
    assert model.get_active_session_id() is None


def test_open_pdf_wrong_password_under_encrypted_named_path_still_reports_wrong_password(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    model, view, controller = mvc
    target = _encrypted_pdf_at(_tricky_path(tmp_path), "secret")
    prompts, errors = _capture_prompts_and_errors(view, monkeypatch, ["wrong", "secret"])

    controller.open_pdf(str(target))

    assert len(prompts) == 2
    assert errors == ["密碼錯誤，請重試。"]
    assert model.get_active_session_id() is not None
    assert len(model.doc) == 1


def test_open_pdf_encrypted_file_prompts_then_cancel_opens_nothing(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    model, view, controller = mvc
    target = _encrypted_pdf_at(tmp_path / "plain_name.pdf", "secret")
    prompts, errors = _capture_prompts_and_errors(view, monkeypatch, [None])

    controller.open_pdf(str(target))

    assert len(prompts) == 1
    assert errors == []
    assert model.get_active_session_id() is None


@pytest.mark.parametrize("kind", ["corrupt", "missing"])
def test_resolve_merge_file_unreadable_file_under_encrypted_named_path_shows_error(
    mvc, monkeypatch, tmp_path: Path, kind: str
) -> None:
    _model, view, controller = mvc
    target = _tricky_path(tmp_path)
    if kind == "corrupt":
        target.write_bytes(b"this is not a pdf at all")
    prompts, errors = _capture_prompts_and_errors(view, monkeypatch, ["guess", None])

    assert controller._resolve_merge_file({"source_kind": "file", "path": str(target)}) is None

    assert prompts == []
    assert len(errors) == 1 and "無法讀取來源檔案" in errors[0]


def test_resolve_merge_file_wrong_password_under_encrypted_named_path_reports_wrong_password(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    _model, view, controller = mvc
    target = _encrypted_pdf_at(_tricky_path(tmp_path), "secret")
    prompts, errors = _capture_prompts_and_errors(view, monkeypatch, ["wrong", "secret"])

    resolved = controller._resolve_merge_file({"source_kind": "file", "path": str(target)})

    assert resolved is not None and resolved["password"] == "secret"
    assert len(prompts) == 2
    assert errors == ["密碼錯誤，請重試。"]


@pytest.mark.parametrize("kind", ["corrupt", "missing"])
def test_resolve_insert_source_unreadable_file_under_encrypted_named_path_shows_error(
    mvc, monkeypatch, tmp_path: Path, kind: str
) -> None:
    _model, view, controller = mvc
    target = _tricky_path(tmp_path)
    if kind == "corrupt":
        target.write_bytes(b"this is not a pdf at all")
    prompts, errors = _capture_prompts_and_errors(view, monkeypatch, ["guess", None])

    assert controller.resolve_insert_source_file(str(target)) is None

    assert prompts == []
    assert len(errors) == 1 and "無法讀取來源檔案" in errors[0]


def test_resolve_insert_source_wrong_password_under_encrypted_named_path_reports_wrong_password(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    _model, view, controller = mvc
    target = _encrypted_pdf_at(_tricky_path(tmp_path), "secret")
    prompts, errors = _capture_prompts_and_errors(view, monkeypatch, ["wrong", "secret"])

    resolved = controller.resolve_insert_source_file(str(target))

    assert resolved is not None and resolved["password"] == "secret"
    assert len(prompts) == 2
    assert errors == ["密碼錯誤，請重試。"]


def test_merge_into_current_refuses_when_the_active_tab_changed_under_the_dialog(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    """F11-1 pin: the merge dialog was opened for A.  If the active tab is
    switched while it is up (an activation the modal gate did not see), the
    merge must not land on the newly active document."""
    from types import SimpleNamespace

    import view.pdf_view as pdf_view_module

    model, _view, controller = mvc
    a = _make_pdf(tmp_path / "A.pdf", ["AAAA"])
    b = _make_pdf(tmp_path / "B.pdf", ["BBBB"])
    c = _make_pdf(tmp_path / "C.pdf", ["CCCC"])
    controller.open_pdf(str(a))
    _pump_events(100)
    sid_a = model.get_active_session_id()
    errors: list[str] = []
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: errors.append(a[-1]))

    def fake_exec(self) -> int:
        controller.open_pdf(str(b))  # direct activation, bypassing the gate
        return QDialog.Accepted

    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "exec", fake_exec)
    monkeypatch.setattr(pdf_view_module.MergePdfDialog, "selected_mode", lambda self: "merge_current")
    monkeypatch.setattr(
        pdf_view_module.MergePdfDialog,
        "ordered_entries",
        lambda self: [
            SimpleNamespace(source_kind="current"),
            SimpleNamespace(source_kind="file", path=str(c), password=None),
        ],
    )

    controller.start_merge_pdfs()
    _pump_events(50)

    for sid in model.session_ids:
        session = model._sessions_by_id[sid]
        assert len(session.doc) == 1, model.get_session_meta(sid)["display_name"]
        assert model.session_has_unsaved_changes(sid) is False
    assert model._sessions_by_id[sid_a].doc[0].get_text().strip() == "AAAA"
    assert errors, "the refused merge must tell the user why"


# --- F16-NAV-3: the merged document keeps the bookmarks, labels and links ---


def test_merge_into_current_keeps_navigation_shows_bookmarks_and_undoes(mvc, tmp_path: Path) -> None:
    from test_scripts.navigation_fixtures import labels, link_targets, make_nav_pdf, make_src_pdf

    model, view, controller = mvc
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "src.pdf"
    make_nav_pdf(nav)
    make_src_pdf(src)
    controller.open_pdf(str(nav))
    _pump_events(100)
    labels_before = labels(model.doc)
    assert view.bookmark_tree.topLevelItemCount() == 4

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(src)}]
    )
    _pump_events(100)

    assert [row[1:3] for row in model.get_toc()][-2:] == [["Src A", 7], ["Src C", 9]]
    assert len(model.get_toc()) == 7
    assert labels(model.doc) == [*labels_before, "1", "2", "3"]
    assert link_targets(model.doc, 0)[600] == "chap3" and link_targets(model.doc, 0)[662] == 3
    # the bookmark panel was reloaded from the merged document (4 + 2 top level items; Section 4.1 is a child)
    assert view.bookmark_tree.topLevelItemCount() == 6

    controller.undo()
    _pump_events(100)
    assert len(model.doc) == 6
    assert len(model.get_toc()) == 5
    assert labels(model.doc) == labels_before


# --- S17-ENC-MERGE: merging while the CURRENT document is encrypted asks each time ---
#
# The owner's choice (keep the current encryption and permissions, or save the merged
# result unencrypted; cancel leaves the document alone).  The merge itself must never
# fail with "document closed or encrypted".

_ENC_USER_PW = "userpw"
_ENC_OWNER_PW = "ownerpw"
_ENC_PERMS = int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT)


def _encrypted_current(path: Path, *, user_pw: str = _ENC_USER_PW) -> Path:
    doc = fitz.open()
    for text in ("ENC page one", "ENC page two"):
        doc.new_page().insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.set_toc([[1, "Enc chapter", 1], [1, "Enc second", 2]])
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw=user_pw,
        owner_pw=_ENC_OWNER_PW,
        permissions=_ENC_PERMS,
    )
    doc.close()
    return path


def _open_encrypted_current(mvc, monkeypatch, path: Path, choice):
    """Open ``path`` through the controller; return the list that records every
    call of the (monkeypatched) merge-encryption question."""
    model, view, controller = mvc
    monkeypatch.setattr(view, "ask_pdf_password", lambda _path: _ENC_USER_PW)
    asked: list[bool] = []

    def _ask(*_args, **_kwargs):
        asked.append(True)
        return choice

    monkeypatch.setattr(view, "ask_merge_encryption_choice", _ask, raising=False)
    controller.open_pdf(str(path))
    _pump_events(100)
    assert model._doc_is_encrypted(model.doc)
    assert "ENC page one" in model.doc[0].get_text()
    return asked


def _assert_encrypted_like(path: Path, source: Path) -> None:
    """``path`` is AES-256 encrypted like ``source``: the user AND owner passwords
    still work and the permissions are the source's."""
    as_user = fitz.open(str(path))
    try:
        assert as_user.needs_pass
        assert as_user.authenticate(_ENC_USER_PW) in (2, 6)
        assert as_user.metadata["encryption"].endswith("256-bit AES")
        merged_permissions = as_user.permissions
    finally:
        as_user.close()
    as_owner = fitz.open(str(path))
    try:
        assert as_owner.authenticate(_ENC_OWNER_PW) in (4, 6)
    finally:
        as_owner.close()
    original = fitz.open(str(source))
    try:
        original.authenticate(_ENC_USER_PW)
        assert merged_permissions == original.permissions
    finally:
        original.close()


def _assert_plain_file(path: Path, expected_texts: list[str]) -> None:
    doc = fitz.open(str(path))
    try:
        assert not doc.needs_pass and not doc.is_encrypted
        assert not (doc.metadata or {}).get("encryption")
        text = "".join(page.get_text() for page in doc)
        for expected in expected_texts:
            assert expected in text
    finally:
        doc.close()


def _encrypted_page_texts(path: Path) -> list[str]:
    """The page texts of an encrypted file, read as the user."""
    doc = fitz.open(str(path))
    try:
        doc.authenticate(_ENC_USER_PW)
        return [page.get_text().strip() for page in doc]
    finally:
        doc.close()


def test_compose_merged_document_with_encrypted_current_does_not_fail(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    """The repro: ``compose_merged_document`` reopened the KEEP snapshot of an
    authenticated encrypted document without authenticating it."""
    model, _view, _controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    _open_encrypted_current(mvc, monkeypatch, enc, "plain")

    sources = [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}]
    for keep in (False, True):
        merged = model.compose_merged_document(sources, keep_encryption=keep)
        try:
            assert len(merged) == 3
            text = "".join(page.get_text() for page in merged)
            assert "ENC page one" in text and "extra page" in text
        finally:
            merged.close()


@pytest.mark.parametrize("keep", [True, False])
def test_compose_merged_document_keep_flag_decides_the_output_encryption(
    mvc, monkeypatch, tmp_path: Path, keep: bool
) -> None:
    model, _view, _controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    _open_encrypted_current(mvc, monkeypatch, enc, "plain")
    merged = model.compose_merged_document([{"source_kind": "current"}], keep_encryption=keep)
    try:
        out = tmp_path / "composed.pdf"
        model.save_external_document(merged, out)
    finally:
        merged.close()
    if keep:
        _assert_encrypted_like(out, enc)
    else:
        _assert_plain_file(out, ["ENC page one", "ENC page two"])


def test_merge_into_encrypted_current_keep_encryption_branch(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    asked = _open_encrypted_current(mvc, monkeypatch, enc, "keep")

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}]
    )
    _pump_events(100)

    assert asked == [True]
    assert len(model.doc) == 3
    assert "extra page" in model.doc[0].get_text()
    assert "ENC page one" in model.doc[1].get_text()
    assert model.has_unsaved_changes() is True
    assert model._doc_is_encrypted(model.doc)
    assert [row[1] for row in model.get_toc()] == ["Enc chapter", "Enc second"]

    saved = tmp_path / "saved_keep.pdf"
    controller.save_as(str(saved))
    _pump_events(100)
    _assert_encrypted_like(saved, enc)
    assert _encrypted_page_texts(saved) == ["extra page", "ENC page one", "ENC page two"]

    controller.undo()
    _pump_events(100)
    assert len(model.doc) == 2
    assert model._doc_is_encrypted(model.doc)
    assert "ENC page two" in model.doc[1].get_text()
    undone = tmp_path / "saved_undone.pdf"
    controller.save_as(str(undone))
    _assert_encrypted_like(undone, enc)

    controller.redo()
    _pump_events(100)
    assert len(model.doc) == 3
    assert "extra page" in model.doc[0].get_text()
    assert model._doc_is_encrypted(model.doc)


def test_merge_into_encrypted_current_unencrypted_branch(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    asked = _open_encrypted_current(mvc, monkeypatch, enc, "plain")

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}]
    )
    _pump_events(100)

    assert asked == [True]
    assert len(model.doc) == 3
    assert not model._doc_is_encrypted(model.doc)
    assert model.has_unsaved_changes() is True
    assert [row[1] for row in model.get_toc()] == ["Enc chapter", "Enc second"]

    saved = tmp_path / "saved_plain.pdf"
    controller.save_as(str(saved))
    _pump_events(100)
    _assert_plain_file(saved, ["ENC page one", "ENC page two", "extra page"])

    # Undo returns to the encrypted document (the session still holds its password).
    controller.undo()
    _pump_events(100)
    assert len(model.doc) == 2
    assert model._doc_is_encrypted(model.doc)
    assert "ENC page one" in model.doc[0].get_text()
    undone = tmp_path / "saved_undone.pdf"
    controller.save_as(str(undone))
    _assert_encrypted_like(undone, enc)


def test_merge_into_encrypted_current_cancel_leaves_the_document_unchanged(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    model, _view, controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    asked = _open_encrypted_current(mvc, monkeypatch, enc, None)
    doc_before = model.doc
    undo_depth = len(model.command_manager._undo_stack)

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}]
    )

    assert asked == [True]
    assert model.doc is doc_before
    assert len(model.doc) == 2
    assert model.has_unsaved_changes() is False
    assert len(model.command_manager._undo_stack) == undo_depth
    assert model._doc_is_encrypted(model.doc)


def test_merge_into_unencrypted_current_never_asks_about_encryption(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    model, view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["current page"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["extra page"])
    asked: list[bool] = []
    monkeypatch.setattr(
        view, "ask_merge_encryption_choice", lambda *a, **k: asked.append(True), raising=False
    )
    controller.open_pdf(str(current))
    _pump_events(100)

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}]
    )

    assert asked == []
    assert len(model.doc) == 2


def test_merge_into_encrypted_current_owner_only_encryption_keeps_it(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    """Owner-password-only encryption opens without a prompt and has no user
    password; the keep branch must still re-save it encrypted."""
    model, _view, controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf", user_pw="")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    asked = _open_encrypted_current(mvc, monkeypatch, enc, "keep")

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}]
    )
    _pump_events(100)

    assert asked == [True]
    assert len(model.doc) == 3
    saved = tmp_path / "saved_owner_only.pdf"
    controller.save_as(str(saved))
    _pump_events(100)
    reopened = fitz.open(str(saved))
    try:
        assert (reopened.metadata or {}).get("encryption") or reopened.is_encrypted
        assert reopened.authenticate(_ENC_OWNER_PW) in (4, 6)
    finally:
        reopened.close()


@pytest.mark.parametrize("choice", ["keep", "plain", None])
def test_save_merged_copy_with_encrypted_current_follows_the_choice(
    mvc, monkeypatch, tmp_path: Path, choice
) -> None:
    _model, _view, controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    asked = _open_encrypted_current(mvc, monkeypatch, enc, choice)
    output = tmp_path / "merged_copy.pdf"
    opened: list[str] = []
    monkeypatch.setattr(controller, "open_pdf", lambda path: opened.append(path))

    controller.save_ordered_sources_as_new(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}], str(output)
    )

    assert asked == [True]
    if choice is None:
        assert not output.exists() and opened == []
        return
    assert opened == [str(output)]
    if choice == "keep":
        _assert_encrypted_like(output, enc)
        assert len(_encrypted_page_texts(output)) == 3
    else:
        _assert_plain_file(output, ["ENC page one", "extra page"])


def test_save_merged_copy_without_the_current_entry_does_not_ask(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    """The result holds nothing of the encrypted current document: no question."""
    _model, _view, controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    asked = _open_encrypted_current(mvc, monkeypatch, enc, "keep")
    output = tmp_path / "no_current.pdf"
    monkeypatch.setattr(controller, "open_pdf", lambda _path: None)

    controller.save_ordered_sources_as_new([{"source_kind": "file", "path": str(extra)}], str(output))

    assert asked == []
    _assert_plain_file(output, ["extra page"])


def test_view_merge_encryption_question_maps_the_three_buttons(qapp) -> None:
    """The zh-TW dialog: keep / unencrypted / cancel."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    from view.pdf_view import PDFView

    view = PDFView()
    try:
        for wanted, expected in (("保留", "keep"), ("未加密", "plain"), ("取消", None)):

            def _click(wanted=wanted) -> None:
                box = QApplication.activeModalWidget()
                assert isinstance(box, QMessageBox)
                for button in box.buttons():
                    if wanted in button.text():
                        button.click()
                        return
                box.reject()
                raise AssertionError(f"no button containing {wanted!r}")

            QTimer.singleShot(0, _click)
            assert view.ask_merge_encryption_choice() == expected
    finally:
        view.close()


def test_kept_encryption_container_carries_no_orphans_of_the_emptied_document(
    mvc, monkeypatch, tmp_path: Path
) -> None:
    """The kept-encryption container is the live document emptied of its pages: the
    objects of those pages must be pruned, not saved along (a merge that leaves the
    current document out must not carry any of its content)."""
    model, _view, _controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    _open_encrypted_current(mvc, monkeypatch, enc, "keep")
    sources = [{"source_kind": "file", "path": str(extra)}]

    kept = model.compose_merged_document(sources, keep_encryption=True)
    plain = model.compose_merged_document(sources, keep_encryption=False)
    try:
        assert len(kept) == len(plain) == 1
        assert "ENC page" not in kept[0].get_text()
        assert kept.xref_length() <= plain.xref_length() + 3  # the /Encrypt dict and its /ID
        assert not kept.get_toc()
    finally:
        kept.close()
        plain.close()


@pytest.mark.parametrize("choice", ["keep", "plain"])
def test_save_in_place_after_merge_into_encrypted_current_follows_the_choice(
    mvc, monkeypatch, tmp_path: Path, choice: str
) -> None:
    model, _view, controller = mvc
    enc = _encrypted_current(tmp_path / "enc_current.pdf")
    reference = tmp_path / "reference.pdf"
    reference.write_bytes(enc.read_bytes())
    extra = _make_pdf(tmp_path / "extra.pdf", ["extra page"])
    _open_encrypted_current(mvc, monkeypatch, enc, choice)

    controller.merge_ordered_sources_into_current(
        [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}]
    )
    controller.save()
    _pump_events(100)

    assert model.has_unsaved_changes() is False
    if choice == "keep":
        _assert_encrypted_like(enc, reference)
        assert len(_encrypted_page_texts(enc)) == 3
    else:
        _assert_plain_file(enc, ["ENC page one", "extra page"])
    # the live session still renders after the save
    assert "ENC page one" in model.doc[0].get_text()


# --- F17-COH-3 / F17-COH-4: the pending watermark through a merge ---------------


def _join_workers(controller) -> None:
    controller._thumbnail_coordinator.cancel()
    controller._thumbnail_coordinator.wait_for_done()
    controller._page_render_coordinator.wait_for_done()
    _pump_events(50)


def _stamped_labels(model) -> list[str]:
    sid = model.get_active_session_id()
    return [
        model.doc[i].get_text("text").strip()
        for i in range(len(model.doc))
        if model.tools.watermark.needs_page_overlay(sid, i + 1, "view")
    ]


def _wm_pages(model) -> list[list[int]]:
    return [list(wm["pages"]) for wm in model.tools.watermark.get_watermarks()]


def test_merge_into_current_keeps_the_watermark_on_its_page_through_undo_and_redo(
    mvc, tmp_path: Path
) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["ONE", "TWO", "THREE"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRA"])
    try:
        controller.open_pdf(str(current))
        _pump_events(100)
        model.tools.watermark.add_watermark([2], "STAMP")

        controller.merge_ordered_sources_into_current(
            [{"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}]
        )
        _pump_events(100)

        assert [model.doc[i].get_text("text").strip() for i in range(4)] == ["EXTRA", "ONE", "TWO", "THREE"]
        assert _wm_pages(model) == [[3]]
        assert _stamped_labels(model) == ["TWO"]
        # The live document stays unbaked: the list draws the watermark, once.
        assert "STAMP" not in "".join(model.doc[i].get_text("text") for i in range(4))

        controller.undo()
        _pump_events(100)
        assert len(model.doc) == 3
        assert _wm_pages(model) == [[2]]
        assert _stamped_labels(model) == ["TWO"]

        controller.redo()
        _pump_events(100)
        assert _wm_pages(model) == [[3]]
        assert _stamped_labels(model) == ["TWO"]
    finally:
        _join_workers(controller)


def test_merge_into_current_with_the_current_document_twice_stamps_both_copies(mvc, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["ONE", "TWO"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRA"])
    try:
        controller.open_pdf(str(current))
        _pump_events(100)
        model.tools.watermark.add_watermark([2], "STAMP")

        controller.merge_ordered_sources_into_current(
            [{"source_kind": "current"}, {"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}]
        )
        _pump_events(100)

        assert _wm_pages(model) == [[2, 5]]
        assert _stamped_labels(model) == ["TWO", "TWO"]
        controller.undo()
        _pump_events(100)
        assert _wm_pages(model) == [[2]]
    finally:
        _join_workers(controller)


def test_merge_that_drops_the_current_document_hides_its_watermark_until_undo(mvc, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["ONE", "TWO"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRA"])
    try:
        controller.open_pdf(str(current))
        _pump_events(100)
        model.tools.watermark.add_watermark([2], "STAMP")

        controller.merge_ordered_sources_into_current([{"source_kind": "file", "path": str(extra)}])
        _pump_events(100)
        assert model.tools.watermark.get_watermarks() == []
        assert _stamped_labels(model) == []

        controller.undo()
        _pump_events(100)
        assert _wm_pages(model) == [[2]]
        assert _stamped_labels(model) == ["TWO"]
    finally:
        _join_workers(controller)


def test_save_ordered_sources_as_new_bakes_the_pending_watermark(mvc, monkeypatch, tmp_path: Path) -> None:
    model, _view, controller = mvc
    current = _make_pdf(tmp_path / "Current.pdf", ["ONE", "TWO", "THREE"])
    extra = _make_pdf(tmp_path / "Extra.pdf", ["EXTRA"])
    output = tmp_path / "merged.pdf"
    try:
        controller.open_pdf(str(current))
        _pump_events(100)
        model.tools.watermark.add_watermark([2], "STAMP")
        monkeypatch.setattr(controller, "open_pdf", lambda _path: None)

        controller.save_ordered_sources_as_new(
            [{"source_kind": "file", "path": str(extra)}, {"source_kind": "current"}], str(output)
        )

        with fitz.open(str(output)) as merged:
            texts = [merged[i].get_text("text") for i in range(len(merged))]
            assert [("STAMP" in text) for text in texts] == [False, False, True, False]
            assert texts[2].strip().startswith("TWO")
        # The session itself is untouched: still unbaked, still one watermark on page 2.
        assert _wm_pages(model) == [[2]]
        assert "STAMP" not in model.doc[1].get_text("text")
    finally:
        _join_workers(controller)
