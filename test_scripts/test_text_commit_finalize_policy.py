"""Finalize policy completion: every path that ends or suspends the inline editor.

Part-3 VERIFY (2026-10-01) defects 1, 2, 3, 5, 6, 7 and the S10 focus concern
of plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md,
treated as one bug class.  Every path that ends or suspends an inline edit
must (i) confirm any cancellable action BEFORE it finalizes, (ii) keep the
editor and the input when the scene is not actually cleared, and (iii) never
lose verified or refused input silently (plan section 3: a refusal or a
cancel keeps the typed input).

Real-app tests launch ``main.run`` through the harness of
``test_text_commit_finalize_by_result.py`` (synthetic Identity-H documents,
real QTest input, recorders only).  Close prompts are answered by a REAL
window-modal ``QMessageBox`` (``open()`` + event pumping, so focus really
leaves the editor and the delayed focus-out finalize gets its chance to run
under the prompt), then the chosen button is reported -- never a vacuous
``clickedButton() is None``.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402
from test_scripts.test_text_commit_finalize_by_result import (  # noqa: E402
    _EDIT_B,
    _App,
    _author,
    _original_texts,
)
from test_scripts.type0_fixture_builder import encode_cids  # noqa: E402
import view.text_editing as text_editing  # noqa: E402
from view.text_editing import TextEditFinalizeReason  # noqa: E402

_REFUSED_INPUT = "Pump Ro"  # shorter: needs Tier 1, so max_tier=0 refuses it
_DISCARD_WORD = "已捨棄"


@pytest.fixture
def launch(qapp, monkeypatch):
    apps: list[_App] = []

    def _launch(path: Path, **kwargs) -> _App:
        app = _App(monkeypatch, path, **kwargs)
        apps.append(app)
        return app

    yield _launch
    for app in apps:
        app.close()


def _file_texts(path: Path, page_index: int = 0) -> list[bytes]:
    """Decoded show texts of a page of the file ON DISK (stream replay)."""
    doc = fitz.open(str(path))
    try:
        page = doc[page_index]
        shows = replay_page_streams([(x, doc.xref_stream(x)) for x in page.get_contents()]).shows
        return [show.decoded_bytes for show in shows]
    finally:
        doc.close()


class _Prompts:
    """Answer every ``QMessageBox.exec`` prompt with a REAL modal dialog.

    ``open()`` shows the box window-modal and the event loop runs for a
    while, so focus really leaves the editor (the app-level focus net and
    its 40 ms finalize timer get their chance); then ``answer`` is reported
    as the clicked button.  A prompt whose buttons lack ``answer`` fails the
    test -- a Cancel can never pass vacuously."""

    def __init__(self, app: _App, monkeypatch, answer: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        self.answer = answer
        self.texts: list[str] = []
        # (requests, commits) already made when the prompt appeared, and
        # those made while it was still unanswered.
        self.at_prompt: list[tuple[int, int]] = []
        self.under_prompt: list[tuple[int, int]] = []

        def _exec(box, *args, **kwargs):
            self.texts.append(f"{box.text()} | {box.informativeText()}")
            requests_before = len(app.requests)
            commits_before = len(app.commits)
            self.at_prompt.append((requests_before, commits_before))
            box.open()
            app.pump(300)
            self.under_prompt.append(
                (len(app.requests) - requests_before, len(app.commits) - commits_before)
            )
            chosen = next((b for b in box.buttons() if b.text() == self.answer), None)
            assert chosen is not None, (
                f"prompt {box.text()!r} has no {self.answer!r} button: "
                f"{[b.text() for b in box.buttons()]}"
            )
            box._chosen_button = chosen
            box.done(0)
            app.pump(40)
            return 0

        monkeypatch.setattr(QMessageBox, "exec", _exec)
        monkeypatch.setattr(
            QMessageBox, "clickedButton", lambda box: getattr(box, "_chosen_button", None)
        )


def _refuse_by_apply(app: _App):
    """Legacy preview + max_tier=0: Apply sends the shorter text, the model
    refuses it (REJECTED, zero mutation) and the editor keeps the input."""
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _REFUSED_INPUT)
    app.pump(300)
    app.click_apply()
    app.pump(300)
    assert len(app.requests) == 1
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert app.view._last_text_edit_finalize_result.outcome.value == "refused"
    return editor


def _refused_by_plan_preview(app: _App):
    """Plan preview + max_tier=0: the preview itself refuses the shorter
    text, so no token ever exists (Apply stays disabled)."""
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _REFUSED_INPUT)
    assert app.wait(lambda: editor.plan_rejection_reason() is not None), "no preview refusal"
    app.pump(60)
    assert editor.current_plan_token() is None
    return editor


def _search(app: _App, query: str, expected: int) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app.view._show_search_panel()
    app.pump(80)
    field = app.view.search_input
    field.selectAll()
    QTest.keyClicks(field, query)
    QTest.keyClick(field, Qt.Key_Return)
    assert app.wait(lambda: app.view.search_results_list.count() >= expected, 20), (
        f"search for {query!r} gave {app.view.search_results_list.count()} results"
    )
    app.pump(150)


def _click_search_result(app: _App, page_num: int) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    results = app.view.search_results_list
    item = next(
        results.item(row)
        for row in range(results.count())
        if (results.item(row).data(Qt.UserRole) or (None,))[0] == page_num
    )
    results.scrollToItem(item)
    app.pump(40)
    assert results.isVisible(), "the search results list is not visible"
    position = results.visualItemRect(item).center()
    QTest.mouseClick(results.viewport(), Qt.LeftButton, Qt.NoModifier, position)


def _ctrl_wheel(app: _App, notches: int = 1) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    viewport = app.view.graphics_view.viewport()
    position = QPointF(viewport.rect().center())
    global_position = QPointF(viewport.mapToGlobal(viewport.rect().center()))
    for _ in range(notches):
        event = QWheelEvent(
            position,
            global_position,
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.NoButton,
            Qt.ControlModifier,
            Qt.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(viewport, event)
        app.app.processEvents()


def _click_tab_close_button(app: _App, index: int = 0) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QTabBar

    button = app.view.document_tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
    assert button is not None and button.isVisible(), "no visible tab close button"
    QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())


def _discard_warnings(app: _App, since: float) -> list[str]:
    return [m for m in app.warnings_since(since) if _DISCARD_WORD in m]


# ------------------------------------------------- guard: one policy per reason


def test_every_finalize_reason_has_exactly_one_policy() -> None:
    """GUARD for the bug class: a new reason must be placed deliberately.
    Keep (the editor survives an un-applied edit), discard (always), or
    close-always (commit a verified edit, else discard with a warning)."""
    keep = text_editing._KEEP_EDITOR_REASONS
    sets = (keep, text_editing._DISCARD_REASONS, getattr(text_editing, "_CLOSE_ALWAYS_REASONS", None))
    assert sets[2] is not None, "no explicit close-always policy set"
    for reason in TextEditFinalizeReason:
        owners = [s for s in sets if reason in s]
        assert len(owners) == 1, f"{reason} is in {len(owners)} policy sets"
    # Cancellable closes keep the input when they cannot apply it.
    assert TextEditFinalizeReason.CLOSE_DOCUMENT in keep
    assert TextEditFinalizeReason("view_rescale") in keep


# ------------------------------------------- defect 1: scene survives -> keep


@pytest.mark.parametrize("preview", ["legacy", "plan"])
def test_search_jump_keeps_a_refused_editor_and_its_input(
    tmp_path: Path, launch, preview: str
) -> None:
    """RED before: ``display_page`` finalized SCENE_REBUILD in continuous
    mode too, where the scene is NOT cleared, so a search-result jump
    discarded refused input with a warning toast.  The editor, the input and
    the PDF must survive; nothing is (re)sent."""
    path = _author(tmp_path / f"jump_{preview}.pdf", pages=2)
    app = launch(path, preview=preview, max_tier="0")
    _search(app, "Buffer", expected=2)
    editor = _refuse_by_apply(app) if preview == "legacy" else _refused_by_plan_preview(app)
    requests_before = len(app.requests)
    since = time.monotonic()
    _click_search_result(app, page_num=2)
    app.pump(600)

    assert app.view.current_page == 1, "the jump did not reach page 2"
    assert app.editor() is editor, "the search jump closed the editor"
    assert editor.toPlainText() == _REFUSED_INPUT
    assert _discard_warnings(app, since) == [], app.toasts
    assert len(app.requests) == requests_before
    assert app.commits == []
    assert app.page_texts(page_index=0) == _original_texts()
    assert app.page_texts(page_index=1) == _original_texts()
    assert app.modals == []


def test_search_jump_itself_never_finalizes_the_editor(tmp_path: Path, launch) -> None:
    """RED before: the jump's SCENE_REBUILD finalize committed the verified
    token synchronously, inside the click, although the continuous scene
    survives.  Now the jump only scrolls and never finalizes.  What follows
    is the ordinary focus-out policy (focus moved to the results list): a
    click-away commits only a CURRENT verified preview (the page switch
    re-requests it, plan section 3), otherwise the editor and input stay.
    Which of the two happens depends on whether the re-requested preview
    lands before the 40 ms focus check, so both are accepted -- but never a
    scene_rebuild finalize and never a discard."""
    path = _author(tmp_path / "jump_token.pdf", pages=2)
    app = launch(path)
    _search(app, "Buffer", expected=2)
    editor = app.open_editor("Pump Room", page_index=0)
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    reasons: list[str] = []
    original_finalize = app.view._finalize_text_edit

    def _spy(reason=TextEditFinalizeReason.CLICK_AWAY):
        reasons.append(reason.value)
        return original_finalize(reason)

    app.view._finalize_text_edit = _spy
    since = time.monotonic()
    _click_search_result(app, page_num=2)
    # Synchronously, inside the click: the jump ran, nothing was finalized.
    assert app.commits == [], "the search jump itself committed the token"
    assert reasons == [], reasons
    app.pump(600)

    assert app.view.current_page == 1
    assert "scene_rebuild" not in reasons, reasons
    assert set(reasons) <= {"focus_outside"}, reasons
    assert _discard_warnings(app, since) == []
    if app.commits:
        result = app.view._last_text_edit_finalize_result
        assert result.reason.value == "focus_outside" and result.outcome.value == "committed"
        assert app.page_texts(page_index=0) == [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]
    else:
        assert app.editor() is editor and editor.toPlainText() == _EDIT_B
        assert app.page_texts(page_index=0) == _original_texts()
    assert app.page_texts(page_index=1) == _original_texts()
    assert app.modals == []


def test_ctrl_wheel_zoom_with_refused_input_keeps_the_editor(tmp_path: Path, launch) -> None:
    """RED before: zoom rebuilds the whole continuous scene (a real clear),
    and the SCENE_REBUILD finalize discarded the refused input.  Zoom cannot
    keep the editor proxy across the rebuild, so it is refused instead
    while un-applied input exists: scale unchanged, editor and input kept,
    a warning says why."""
    path = _author(tmp_path / "zoom_wheel.pdf")
    app = launch(path, preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    scale_before = app.view.scale
    since = time.monotonic()
    _ctrl_wheel(app, notches=2)
    app.pump(800)  # past the 300 ms zoom debounce

    assert app.editor() is editor, "the zoom closed the editor"
    assert editor.toPlainText() == _REFUSED_INPUT
    assert app.view.scale == pytest.approx(scale_before)
    assert _discard_warnings(app, since) == [], app.toasts
    assert any("縮放" in m for m in app.warnings_since(since)), app.toasts
    assert len(app.requests) == 1 and app.commits == []
    assert app.page_texts() == _original_texts()


def test_zoom_combo_with_pending_input_keeps_the_editor(tmp_path: Path, launch) -> None:
    """RED before: the zoom combo (``change_scale``) rebuilt the scene and
    discarded the input.  Now the zoom is refused, the combo shows the
    unchanged zoom again, and the editor keeps the input."""
    path = _author(tmp_path / "zoom_combo.pdf")
    app = launch(path, preview="plan", max_tier="0")
    editor = _refused_by_plan_preview(app)
    scale_before = app.view.scale
    combo_before = app.view.zoom_combo.currentText()
    target = next(
        i for i in range(app.view.zoom_combo.count())
        if app.view.zoom_combo.itemText(i) != combo_before
    )
    since = time.monotonic()
    app.view.zoom_combo.setCurrentIndex(target)
    app.pump(600)

    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert app.view.scale == pytest.approx(scale_before)
    assert app.view.zoom_combo.currentText() == combo_before
    assert _discard_warnings(app, since) == []
    assert any("縮放" in m for m in app.warnings_since(since)), app.toasts
    assert app.requests == [] and app.commits == []


def test_zoom_with_an_untouched_editor_still_zooms(tmp_path: Path, launch) -> None:
    """GUARD (passes before and after; labelled, not a red): no input to keep -> the zoom runs and
    the untouched editor closes as a no-op."""
    path = _author(tmp_path / "zoom_clean.pdf")
    app = launch(path)
    app.open_editor("Pump Room")
    scale_before = app.view.scale
    _ctrl_wheel(app, notches=2)
    app.pump(800)
    assert app.editor() is None
    assert app.view.scale != pytest.approx(scale_before)
    assert app.requests == [] and app.commits == []


# ------------------------------------- defect 2: tab close confirms first


def test_tab_close_cancel_keeps_tab_editor_and_refused_input(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """RED before: the active tab was finalized BEFORE the prompt (refused
    input discarded with a warning), and a clean document closed with no
    prompt at all.  Un-applied input now counts as unsaved; Cancel keeps the
    tab, the editor and the input with zero PDF change."""
    path = _author(tmp_path / "tab_cancel.pdf")
    app = launch(path, preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    prompts = _Prompts(app, monkeypatch, "取消")
    since = time.monotonic()
    _click_tab_close_button(app)
    app.pump(500)

    assert len(prompts.texts) == 1, "un-applied input did not count as unsaved"
    assert len(app.model.session_ids) == 1, "Cancel closed the tab"
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert _discard_warnings(app, since) == []
    assert len(app.requests) == 1 and app.commits == []
    assert app.page_texts() == _original_texts()


def test_tab_close_cancel_never_commits_the_token(tmp_path: Path, launch, monkeypatch) -> None:
    """RED before: the verified token committed before the prompt was even
    shown.  Nothing may be sent while the prompt is unanswered, nor after a
    Cancel."""
    path = _author(tmp_path / "tab_token_cancel.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    prompts = _Prompts(app, monkeypatch, "取消")
    _click_tab_close_button(app)
    app.pump(500)

    assert len(prompts.texts) == 1
    assert prompts.under_prompt == [(0, 0)], "an edit was sent before the answer"
    assert app.requests == [] and app.commits == []
    assert len(app.model.session_ids) == 1
    assert app.editor() is editor and editor.toPlainText() == _EDIT_B
    assert app.page_texts() == _original_texts()


def test_tab_close_save_commits_the_token_then_saves(tmp_path: Path, launch, monkeypatch) -> None:
    """「儲存後關閉」 with a verified token: the edit commits only AFTER the
    answer (RED before: it committed before the prompt appeared) and the
    SAVED FILE (measured on disk) contains it."""
    from PySide6.QtWidgets import QFileDialog

    path = _author(tmp_path / "tab_token_save.pdf")
    saved = tmp_path / "tab_token_saved.pdf"
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    prompts = _Prompts(app, monkeypatch, "儲存後關閉")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(saved), "PDF (*.pdf)"))
    )
    _click_tab_close_button(app)
    app.pump(600)

    assert len(prompts.texts) == 1
    assert prompts.at_prompt == [(0, 0)], "the edit was sent before the prompt"
    assert prompts.under_prompt == [(0, 0)]
    assert len(app.commits) == 1
    assert len(app.model.session_ids) == 0
    assert saved.exists(), "nothing was saved"
    assert _file_texts(saved) == [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]


def test_tab_close_save_with_refused_input_keeps_the_tab(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """「儲存後關閉」 cannot save refused input: the close is aborted with a
    visible reason; the tab, the editor and the input stay; nothing is saved."""
    from PySide6.QtWidgets import QFileDialog

    path = _author(tmp_path / "tab_refused_save.pdf")
    saved = tmp_path / "tab_refused_saved.pdf"
    app = launch(path, preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    _Prompts(app, monkeypatch, "儲存後關閉")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(saved), "PDF (*.pdf)"))
    )
    since = time.monotonic()
    _click_tab_close_button(app)
    app.pump(600)

    assert len(app.model.session_ids) == 1, "the tab closed without the input"
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert not saved.exists()
    assert app.commits == []
    assert any("關閉" in m for m in app.warnings_since(since)), app.toasts
    assert _discard_warnings(app, since) == []


def test_tab_close_discard_closes_without_any_edit(tmp_path: Path, launch, monkeypatch) -> None:
    """「放棄變更」 is the explicit discard: the tab closes, nothing commits."""
    path = _author(tmp_path / "tab_discard.pdf")
    before = path.read_bytes()
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    _Prompts(app, monkeypatch, "放棄變更")
    _click_tab_close_button(app)
    app.pump(500)

    assert len(app.model.session_ids) == 0
    assert app.requests == [] and app.commits == []
    assert path.read_bytes() == before


@pytest.mark.parametrize("variant", ["refused", "token"])
def test_closing_another_tab_never_ends_the_active_editor(
    tmp_path: Path, launch, monkeypatch, variant: str
) -> None:
    """RED before: closing a NON-active (clean) tab re-rendered the active
    session, whose scene rebuild finalized the active editor SCENE_REBUILD --
    a refused input was discarded, a verified token committed, as a side
    effect of an action aimed at another document."""
    first = _author(tmp_path / f"other_{variant}.pdf")
    second = _author(tmp_path / f"active_{variant}.pdf")
    if variant == "refused":
        app = launch(first, preview="legacy", max_tier="0")
    else:
        app = launch(first)
    app.view.sig_open_pdf.emit(str(second))
    app.pump(1200)
    active_sid = app.model.get_active_session_id()
    active_doc = app.model.doc
    assert len(app.model.session_ids) == 2
    if variant == "refused":
        editor = _refuse_by_apply(app)
        expected_text = _REFUSED_INPUT
    else:
        editor = app.open_editor("Pump Room")
        app.type_replacing_all(editor, _EDIT_B)
        app.wait_token(editor)
        expected_text = _EDIT_B
    requests_before = len(app.requests)
    _Prompts(app, monkeypatch, "取消")  # the other tab is clean: no prompt expected
    since = time.monotonic()
    other_index = next(
        i for i in range(app.view.document_tab_bar.count())
        if app.view.document_tab_bar.tabData(i) != active_sid
    )
    _click_tab_close_button(app, other_index)
    app.pump(600)

    assert app.model.session_ids == [active_sid], "the other tab did not close"
    assert app.model.doc is active_doc
    assert app.editor() is editor, "closing another tab ended the active editor"
    assert editor.toPlainText() == expected_text
    assert len(app.requests) == requests_before and app.commits == []
    assert _discard_warnings(app, since) == []
    assert app.page_texts() == _original_texts()


# ------------------------------------- defect 3: window close finalizes


def test_window_close_with_a_token_prompts_and_save_all_writes_the_edit(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """RED before: a clean document with a verified token closed with no
    prompt and the input was lost silently.  Now the input counts as
    unsaved; 「全部儲存」 commits it after the answer, and the file on disk
    (MEASURED by reopening it) contains the edit."""
    path = _author(tmp_path / "close_token.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    prompts = _Prompts(app, monkeypatch, "全部儲存")
    closed = app.view.close()
    app.pump(400)

    assert len(prompts.texts) == 1, "the window closed without asking"
    assert prompts.under_prompt == [(0, 0)], "an edit was sent before the answer"
    assert closed is True
    assert len(app.commits) == 1
    assert _file_texts(path) == [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]


def test_window_close_cancel_keeps_window_editor_and_input(
    tmp_path: Path, launch, monkeypatch
) -> None:
    path = _author(tmp_path / "close_cancel.pdf")
    before = path.read_bytes()
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    prompts = _Prompts(app, monkeypatch, "取消")
    closed = app.view.close()
    app.pump(400)

    assert len(prompts.texts) == 1
    assert closed is False and app.view.isVisible()
    assert app.requests == [] and app.commits == []
    assert app.editor() is editor and editor.toPlainText() == _EDIT_B
    assert path.read_bytes() == before


def test_window_close_save_all_with_refused_input_aborts_the_close(
    tmp_path: Path, launch, monkeypatch
) -> None:
    path = _author(tmp_path / "close_refused.pdf")
    before = path.read_bytes()
    app = launch(path, preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    _Prompts(app, monkeypatch, "全部儲存")
    since = time.monotonic()
    closed = app.view.close()
    app.pump(400)

    assert closed is False and app.view.isVisible(), "closed without the input"
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert app.commits == []
    assert path.read_bytes() == before
    assert any("關閉" in m for m in app.warnings_since(since)), app.toasts


def test_window_close_discard_all_closes_without_any_edit(
    tmp_path: Path, launch, monkeypatch
) -> None:
    path = _author(tmp_path / "close_discard.pdf")
    before = path.read_bytes()
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    prompts = _Prompts(app, monkeypatch, "全部放棄")
    closed = app.view.close()
    app.pump(300)

    assert len(prompts.texts) == 1, "un-applied input did not count as unsaved"
    assert closed is True
    assert app.requests == [] and app.commits == []
    assert path.read_bytes() == before


# ------------------------------------- defect 5: panel re-synced on teardown


def test_refusal_label_and_rebuild_button_hide_when_the_editor_closes(
    tmp_path: Path, launch
) -> None:
    """RED before: ``_sync_text_property_panel_state`` re-synced the refusal
    panel only while a live editor existed, so Esc left a stale reason and a
    dead "改用重建文字…" button."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    path = _author(tmp_path / "stale_panel.pdf")
    app = launch(path, preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    assert not app.view.text_plan_status_label.isHidden(), "no refusal reason shown"
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_Escape)
    app.pump(300)

    assert app.editor() is None
    assert app.view.text_plan_status_label.isHidden(), "stale refusal reason"
    assert app.view.text_rebuild_btn.isHidden(), "stale rebuild button"
    assert app.view.text_apply_btn.isEnabled() is False


# ------------------------------------- defect 6: the real reason on Ctrl+S


def test_ctrl_s_on_already_refused_input_names_the_refusal(tmp_path: Path, launch) -> None:
    """RED before: the refused input is not re-sent, but the notice said
    "預覽仍在更新" -- false in legacy preview, where no preview exists."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    path = _author(tmp_path / "ctrl_s.pdf")
    app = launch(path, preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    since = time.monotonic()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_S, Qt.ControlModifier)
    app.pump(400)

    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert len(app.requests) == 1, "the refused input was re-sent"
    warnings = app.warnings_since(since)
    assert warnings, "Ctrl+S gave no reason"
    assert all("預覽仍在更新" not in m for m in warnings), warnings
    assert any("拒絕" in m for m in warnings), warnings


# ------------------------------------- S10 concern: refused Apply keeps focus


def test_refused_token_apply_keeps_focus_and_its_result(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """RED before: in plan mode a refused Apply re-armed the preview, which
    disabled the FOCUSED Apply button; focus left the edit context and a
    FOCUS_OUTSIDE finalize ran and overwrote the Apply result.  The commit
    is made to refuse through a real fail-closed path: the cached verified
    candidate no longer binds to the live page (PREVIEW_STALE)."""
    path = _author(tmp_path / "focus.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    monkeypatch.setattr(
        TieredCommitEngine,
        "cached_candidate_identity_failure",
        lambda self, *a, **k: "page_changed",
    )
    reasons: list[str] = []
    original_finalize = app.view._finalize_text_edit

    def _spy(reason=TextEditFinalizeReason.CLICK_AWAY):
        reasons.append(reason.value)
        return original_finalize(reason)

    app.view._finalize_text_edit = _spy
    app.click_apply()
    app.pump(600)

    assert app.commits == []
    assert app.editor() is editor and editor.toPlainText() == _EDIT_B
    result = app.view._last_text_edit_finalize_result
    assert result.reason.value == "apply", reasons
    assert result.edit_result is EditTextResult.PREVIEW_STALE
    assert "focus_outside" not in reasons, reasons
    # Typing simply continues: a real key press goes to whatever holds the
    # keyboard focus now, and must land in the kept editor.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    focus = app.app.focusWidget()
    assert focus is not None
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    QTest.keyClick(focus, Qt.Key_X)
    app.pump(100)
    assert editor.toPlainText() == _EDIT_B + "x", (
        focus,
        getattr(focus, "text", lambda: "")(),
        editor.toPlainText(),
    )
    assert app.view._last_text_edit_finalize_result.reason.value == "apply"
