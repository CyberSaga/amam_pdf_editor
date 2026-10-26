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

import subprocess
import sys
import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402
from test_scripts.test_text_commit_finalize_by_result import (  # noqa: E402
    _EDIT_A,
    _EDIT_B,
    _App,
    _author,
    _original_texts,
)
from test_scripts.type0_fixture_builder import encode_cids  # noqa: E402
import view.text_editing as text_editing  # noqa: E402
from view.text_edit_reasons import rejection_reason_text  # noqa: E402
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
    failures = [
        failure
        for app in apps
        for prompts in app.__dict__.get("_prompt_logs", [])
        for failure in prompts.failures
    ]
    for app in apps:
        app.close()
    assert failures == [], failures


def _file_texts(path: Path, page_index: int = 0) -> list[bytes]:
    """Decoded show texts of a page of the file ON DISK (stream replay)."""
    doc = fitz.open(str(path))
    try:
        page = doc[page_index]
        shows = replay_page_streams([(x, doc.xref_stream(x)) for x in page.get_contents()]).shows
        return [show.decoded_bytes for show in shows]
    finally:
        doc.close()


def _edited_texts() -> list[bytes]:
    """``_original_texts`` with the Pump Room line replaced by ``_EDIT_B``."""
    return [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]


def _editor_with_token(app: _App):
    """The Pump Room editor with ``_EDIT_B`` typed and its preview verified."""
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    assert app.wait_token(editor)
    return editor


class _Prompts:
    """Answer every ``QMessageBox.exec`` prompt with a REAL modal dialog.

    ``open()`` shows the box window-modal and the event loop runs for a
    while, so focus really leaves the editor (the app-level focus net and
    its 40 ms finalize timer get their chance); then ``answer`` is reported
    as the clicked button.  A prompt whose buttons lack ``answer`` is recorded
    in ``failures`` (the box is still closed, so the app tears down cleanly);
    ``launch`` asserts every ``_Prompts`` of a test has none, and the tests of
    the close prompts assert it themselves -- a Cancel can never pass
    vacuously, and a wrong prompt is a named assertion, not a crash."""

    def __init__(self, app: _App, monkeypatch, answer: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        self.answer = answer
        self.texts: list[str] = []
        self.titles: list[str] = []
        self.buttons: list[list[str]] = []
        self.failures: list[str] = []
        app.__dict__.setdefault("_prompt_logs", []).append(self)
        # (requests, commits) already made when the prompt appeared, and
        # those made while it was still unanswered.
        self.at_prompt: list[tuple[int, int]] = []
        self.under_prompt: list[tuple[int, int]] = []

        def _exec(box, *args, **kwargs):
            self.texts.append(f"{box.text()} | {box.informativeText()}")
            self.titles.append(box.windowTitle())
            self.buttons.append([b.text() for b in box.buttons()])
            requests_before = len(app.requests)
            commits_before = len(app.commits)
            self.at_prompt.append((requests_before, commits_before))
            box.open()
            app.pump(300)
            self.under_prompt.append(
                (len(app.requests) - requests_before, len(app.commits) - commits_before)
            )
            chosen = next((b for b in box.buttons() if b.text() == self.answer), None)
            if chosen is None:
                self.failures.append(
                    f"prompt {box.windowTitle()!r} {box.text()!r} has no {self.answer!r} "
                    f"button: {[b.text() for b in box.buttons()]}"
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


def _dirty_then_plan_refused(app: _App):
    """A committed edit makes the document dirty (an unsaved change), then a
    second line holds plan-refused input: the dirty + refused close case."""
    first = app.open_editor("Buffer Tank")
    app.type_replacing_all(first, _EDIT_A)
    assert app.wait_token(first)
    app.click_apply()
    assert len(app.commits) == 1 and app.editor() is None
    assert app.model.session_has_unsaved_changes(app.model.get_active_session_id())
    return _refused_by_plan_preview(app)


def _search(app: _App, query: str, expected: int) -> None:
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
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

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
        assert app.page_texts(page_index=0) == _edited_texts()
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
    editor = _editor_with_token(app)
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
    path = _author(tmp_path / "tab_token_save.pdf")
    saved = tmp_path / "tab_token_saved.pdf"
    app = launch(path)
    _editor_with_token(app)
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
    assert _file_texts(saved) == _edited_texts()


_REFUSED_CLOSE_TITLE = "無法套用的文字編輯"
_REFUSED_CLOSE_BUTTONS = ["取消", "捨棄並關閉"]
_SAVE_CLOSE_BUTTONS = ["取消", "放棄變更", "儲存後關閉"]
_REFUSED_SAVE_SENTENCE = "「儲存後關閉」會先捨棄編輯框內無法套用的文字，再儲存文件。"


@pytest.mark.parametrize("state", ["plan_refused", "legacy_refused"])
def test_tab_close_clean_document_with_refused_input_offers_discard_only(
    tmp_path: Path, launch, monkeypatch, state: str
) -> None:
    """CLOSE-PROMPT-1 (owner finding 2026-10-26).  RED before: the document
    was already saved and the editor held refused input, yet the prompt said
    there were unsaved changes and offered 「儲存後關閉」, which could not do
    what it said (the close was aborted, read as a failed save).  Now the
    prompt says the input cannot be applied, with exactly 捨棄並關閉 / 取消;
    捨棄並關閉 closes the tab, the editor is gone, the file is untouched."""
    path = _author(tmp_path / f"tab_clean_refused_{state}.pdf")
    before = path.read_bytes()
    if state == "legacy_refused":
        app = launch(path, preview="legacy", max_tier="0")
        editor = _refuse_by_apply(app)
        requests_before = 1
    else:
        app = launch(path, max_tier="0")
        editor = _refused_by_plan_preview(app)
        requests_before = 0
    reason_text = rejection_reason_text(editor.plan_rejection_reason())
    assert reason_text
    prompts = _Prompts(app, monkeypatch, "捨棄並關閉")
    _click_tab_close_button(app)
    app.pump(500)

    assert prompts.failures == [], prompts.failures
    assert len(prompts.texts) == 1
    assert prompts.titles == [_REFUSED_CLOSE_TITLE]
    assert "無法套用" in prompts.texts[0]
    assert reason_text in prompts.texts[0], prompts.texts[0]
    assert "關閉將捨棄這段輸入" in prompts.texts[0]
    assert sorted(prompts.buttons[0]) == sorted(_REFUSED_CLOSE_BUTTONS)
    assert app.model.session_ids == [], "the tab did not close"
    assert app.editor() is None
    assert len(app.requests) == requests_before and app.commits == []
    assert path.read_bytes() == before


def test_tab_close_clean_document_refused_input_cancel_keeps_everything(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """The 取消 answer of the new two-button prompt keeps the tab, the editor
    and the input untouched (it is the default button)."""
    path = _author(tmp_path / "tab_clean_refused_cancel.pdf")
    before = path.read_bytes()
    app = launch(path, max_tier="0")
    editor = _refused_by_plan_preview(app)
    prompts = _Prompts(app, monkeypatch, "取消")
    since = time.monotonic()
    _click_tab_close_button(app)
    app.pump(500)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == [_REFUSED_CLOSE_TITLE]
    assert sorted(prompts.buttons[0]) == sorted(_REFUSED_CLOSE_BUTTONS)
    assert len(app.model.session_ids) == 1
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert app.requests == [] and app.commits == []
    assert _discard_warnings(app, since) == []
    assert path.read_bytes() == before


def test_tab_close_clean_document_with_a_verified_token_keeps_the_save_prompt(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """GUARD (green before and after): a verified editor on a clean document
    keeps today's three-button prompt, with no refusal wording."""
    path = _author(tmp_path / "tab_clean_token.pdf")
    app = launch(path)
    _editor_with_token(app)
    prompts = _Prompts(app, monkeypatch, "取消")
    _click_tab_close_button(app)
    app.pump(400)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == ["未儲存的變更"]
    assert sorted(prompts.buttons[0]) == sorted(_SAVE_CLOSE_BUTTONS)
    assert "有尚未套用的文字編輯或未儲存的變更" in prompts.texts[0]
    assert "無法套用" not in prompts.texts[0]


def test_tab_close_save_with_refused_input_discards_it_then_saves(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """Dirty document + refused input: the three buttons stay, the prompt says
    what 「儲存後關閉」 does with the refused input, and it does exactly that:
    the document is saved WITHOUT the refused text, the editor is gone and the
    tab closes.

    REWRITTEN on purpose (owner finding 2026-10-26, CLOSE-PROMPT-1): this test
    used to pin "「儲存後關閉」 cannot save refused input: the close is aborted"
    (the editor and the input stay, nothing is saved).  That policy made the
    button look like a failed save; the owner chose one policy for both
    prompts: the refused input is dropped, the document is saved, the tab
    closes.  A VERIFIED editor still commits first (the token tests above)."""
    path = _author(tmp_path / "tab_dirty_refused_save.pdf")
    saved = tmp_path / "tab_dirty_refused_saved.pdf"
    app = launch(path, max_tier="0")
    _dirty_then_plan_refused(app)
    prompts = _Prompts(app, monkeypatch, "儲存後關閉")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(saved), "PDF (*.pdf)"))
    )
    _click_tab_close_button(app)
    app.pump(600)

    assert prompts.failures == [], prompts.failures
    assert len(prompts.texts) == 1
    assert prompts.titles == ["未儲存的變更"]
    assert sorted(prompts.buttons[0]) == sorted(_SAVE_CLOSE_BUTTONS)
    assert _REFUSED_SAVE_SENTENCE in prompts.texts[0], prompts.texts[0]
    assert app.model.session_ids == [], "the tab did not close"
    assert app.editor() is None
    assert len(app.commits) == 1, "the refused input must not be committed"
    assert saved.exists(), "nothing was saved"
    assert _file_texts(saved) == [encode_cids(_EDIT_A), encode_cids("Pump Room")]


def test_tab_close_save_with_refused_input_and_a_cancelled_save_keeps_the_input(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """GUARD (green before and after; labelled, not a red): the refused input is
    dropped only once the save went through, so a Save dialog the user cancels
    keeps the tab, the editor and the input."""
    path = _author(tmp_path / "tab_dirty_refused_nosave.pdf")
    app = launch(path, max_tier="0")
    editor = _dirty_then_plan_refused(app)
    _Prompts(app, monkeypatch, "儲存後關閉")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", ""))
    )
    _click_tab_close_button(app)
    app.pump(500)

    assert len(app.model.session_ids) == 1
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT


def test_tab_close_dirty_document_with_a_verified_token_keeps_todays_prompt(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """GUARD (green before and after): dirty document + VERIFIED input has no
    refusal sentence; the verified edit is what 「儲存後關閉」 commits."""
    path = _author(tmp_path / "tab_dirty_token.pdf")
    app = launch(path)
    first = app.open_editor("Buffer Tank")
    app.type_replacing_all(first, _EDIT_A)
    assert app.wait_token(first)
    app.click_apply()
    assert len(app.commits) == 1
    _editor_with_token(app)
    prompts = _Prompts(app, monkeypatch, "取消")
    _click_tab_close_button(app)
    app.pump(400)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == ["未儲存的變更"]
    assert sorted(prompts.buttons[0]) == sorted(_SAVE_CLOSE_BUTTONS)
    assert _REFUSED_SAVE_SENTENCE not in prompts.texts[0]
    assert "無法套用" not in prompts.texts[0]


@pytest.mark.parametrize("state", ["legacy_refused", "plan_refused"])
def test_tab_close_after_ctrl_s_still_offers_the_refused_input_prompt(
    tmp_path: Path, launch, monkeypatch, state: str
) -> None:
    """Reviewer F1 (the owner's exact sequence: refused input -> Ctrl+S -> close
    the tab).  Saving invalidates the editor's preview (the document changed),
    which used to drop a refusal for good in legacy preview mode (nothing asks
    again), so the close fell back to the old three-button prompt and the
    aborted close.  The refusal must survive while the input is unchanged; in
    plan mode the re-preview records it again (waited for here)."""
    path = _author(tmp_path / f"tab_ctrl_s_{state}.pdf")
    out = tmp_path / f"tab_ctrl_s_{state}_out.pdf"
    if state == "legacy_refused":
        app = launch(path, preview="legacy", max_tier="0")
        editor = _refuse_by_apply(app)
    else:
        app = launch(path, max_tier="0")
        editor = _refused_by_plan_preview(app)
    _arm_save(app, monkeypatch, out)
    _do_save(app, "save")
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    if state == "plan_refused":
        assert app.wait(lambda: editor.plan_rejection_reason() is not None), (
            "the re-preview after the save did not refuse again"
        )
    prompts = _Prompts(app, monkeypatch, "捨棄並關閉")
    _click_tab_close_button(app)
    app.pump(500)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == [_REFUSED_CLOSE_TITLE]
    assert sorted(prompts.buttons[0]) == sorted(_REFUSED_CLOSE_BUTTONS)
    assert app.model.session_ids == []
    assert app.editor() is None


def test_window_close_after_ctrl_s_still_offers_the_refused_input_prompt(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """F1 for the window close (legacy preview: the case a save used to break)."""
    path = _author(tmp_path / "close_ctrl_s.pdf")
    out = tmp_path / "close_ctrl_s_out.pdf"
    app = launch(path, preview="legacy", max_tier="0")
    _refuse_by_apply(app)
    _arm_save(app, monkeypatch, out)
    _do_save(app, "save")
    prompts = _Prompts(app, monkeypatch, "捨棄並關閉")
    closed = app.view.close()
    app.pump(400)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == [_REFUSED_CLOSE_TITLE]
    assert closed is True
    assert app.editor() is None


def test_tab_close_with_a_pending_plan_preview_keeps_todays_prompt(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """F1 guard: a refusal that a document-change invalidate supersedes in PLAN
    mode is NOT carried over while its re-preview is pending (no request is
    made here, so it stays pending): the input is neither refused nor
    verified, and the prompt keeps today's three buttons."""
    path = _author(tmp_path / "tab_pending.pdf")
    app = launch(path, max_tier="0")
    editor = _refused_by_plan_preview(app)
    editor.invalidate_plan_preview(regenerate=False, keep_refusal=True)
    assert editor.plan_rejection_reason() is None, "a pending preview reported a stale refusal"
    prompts = _Prompts(app, monkeypatch, "取消")
    _click_tab_close_button(app)
    app.pump(400)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == ["未儲存的變更"]
    assert sorted(prompts.buttons[0]) == sorted(_SAVE_CLOSE_BUTTONS)
    assert app.editor() is editor


def test_tab_close_with_a_composition_over_refused_input_keeps_todays_prompt(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """Reviewer F3: a composition is input the input method still owns, so
    even with a standing refusal the prompt stays the three-button one and
    Cancel keeps the composition."""
    path = _author(tmp_path / "tab_composing_refused.pdf")
    app = launch(path, max_tier="0")
    editor = _refused_by_plan_preview(app)
    _send_preedit(editor, _PREEDIT)
    app.pump(300)
    assert editor.preedit_text() == _PREEDIT, "precondition: composing"
    assert app.wait(lambda: editor.plan_rejection_reason() is not None), (
        "precondition: the refusal stands while composing (else the guard is not exercised)"
    )
    prompts = _Prompts(app, monkeypatch, "取消")
    _click_tab_close_button(app)
    app.pump(400)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == ["未儲存的變更"]
    assert sorted(prompts.buttons[0]) == sorted(_SAVE_CLOSE_BUTTONS)
    assert app.editor() is editor and editor.preedit_text() == _PREEDIT


def test_tab_close_discard_closes_without_any_edit(tmp_path: Path, launch, monkeypatch) -> None:
    """「放棄變更」 is the explicit discard: the tab closes, nothing commits."""
    path = _author(tmp_path / "tab_discard.pdf")
    before = path.read_bytes()
    app = launch(path)
    _editor_with_token(app)
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
        editor = _editor_with_token(app)
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
    _editor_with_token(app)
    prompts = _Prompts(app, monkeypatch, "全部儲存")
    closed = app.view.close()
    app.pump(400)

    assert len(prompts.texts) == 1, "the window closed without asking"
    assert prompts.under_prompt == [(0, 0)], "an edit was sent before the answer"
    assert closed is True
    assert len(app.commits) == 1
    assert _file_texts(path) == _edited_texts()


def test_window_close_cancel_keeps_window_editor_and_input(
    tmp_path: Path, launch, monkeypatch
) -> None:
    path = _author(tmp_path / "close_cancel.pdf")
    before = path.read_bytes()
    app = launch(path)
    editor = _editor_with_token(app)
    prompts = _Prompts(app, monkeypatch, "取消")
    closed = app.view.close()
    app.pump(400)

    assert len(prompts.texts) == 1
    assert closed is False and app.view.isVisible()
    assert app.requests == [] and app.commits == []
    assert app.editor() is editor and editor.toPlainText() == _EDIT_B
    assert path.read_bytes() == before


def test_window_close_clean_document_with_refused_input_offers_discard_only(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """CLOSE-PROMPT-1 for the window close (owner finding 2026-10-26).  This
    replaces ``..._save_all_with_refused_input_aborts_the_close``: with a clean
    document and refused input the prompt no longer offers 「全部儲存」, which
    could not do what it said; it offers 捨棄並關閉 / 取消, and 捨棄並關閉
    closes the window with the file untouched."""
    path = _author(tmp_path / "close_refused.pdf")
    before = path.read_bytes()
    app = launch(path, preview="legacy", max_tier="0")
    _refuse_by_apply(app)
    prompts = _Prompts(app, monkeypatch, "捨棄並關閉")
    closed = app.view.close()
    app.pump(400)

    assert prompts.failures == [], prompts.failures
    assert prompts.titles == [_REFUSED_CLOSE_TITLE]
    assert "無法套用" in prompts.texts[0]
    assert sorted(prompts.buttons[0]) == sorted(_REFUSED_CLOSE_BUTTONS)
    assert closed is True
    assert app.editor() is None
    assert app.commits == []
    assert path.read_bytes() == before


def test_window_close_save_all_with_refused_input_discards_it_then_saves(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """Dirty document + refused input at window close: 「全部儲存」 drops the
    refused input, saves the document in place and closes (the same policy as
    the single-tab close; the old test pinned an aborted close)."""
    path = _author(tmp_path / "close_dirty_refused.pdf")
    app = launch(path, max_tier="0")
    _dirty_then_plan_refused(app)
    prompts = _Prompts(app, monkeypatch, "全部儲存")
    closed = app.view.close()
    app.pump(600)

    assert prompts.failures == [], prompts.failures
    assert len(prompts.texts) == 1
    assert "「全部儲存」會先捨棄編輯框內無法套用的文字，再儲存文件。" in prompts.texts[0], prompts.texts[0]
    assert closed is True
    assert len(app.commits) == 1
    assert _file_texts(path) == [encode_cids(_EDIT_A), encode_cids("Pump Room")]


def test_window_close_count_excludes_the_clean_tab_of_refused_input(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """Another tab is dirty; the active tab is clean and its editor holds
    refused input.  Refused input is dropped, never saved, so it must not be
    counted among the 「尚未儲存」 tabs: the prompt says 1 tab, not 2, and
    「全部儲存」 writes the dirty tab, drops the input and closes."""
    other = _author(tmp_path / "count_other.pdf")
    active = _author(tmp_path / "count_active.pdf")
    before_active = active.read_bytes()
    app = launch(other, max_tier="0")
    first = app.open_editor("Buffer Tank")
    app.type_replacing_all(first, _EDIT_A)
    assert app.wait_token(first)
    app.click_apply()
    assert len(app.commits) == 1 and app.editor() is None
    app.view.sig_open_pdf.emit(str(active))
    app.pump(1200)
    assert len(app.model.session_ids) == 2
    assert not app.model.session_has_unsaved_changes(app.model.get_active_session_id())
    _refused_by_plan_preview(app)
    prompts = _Prompts(app, monkeypatch, "全部儲存")
    closed = app.view.close()
    app.pump(800)

    assert prompts.failures == [], prompts.failures
    assert len(prompts.texts) == 1
    assert "共有 1 個分頁尚未儲存" in prompts.texts[0], prompts.texts[0]
    assert "含尚未套用的文字編輯" not in prompts.texts[0], prompts.texts[0]
    assert "「全部儲存」會先捨棄編輯框內無法套用的文字" in prompts.texts[0]
    assert closed is True
    assert len(app.commits) == 1
    assert _file_texts(other) == [encode_cids(_EDIT_A), encode_cids("Pump Room")]
    assert active.read_bytes() == before_active


def test_window_close_discard_all_closes_without_any_edit(
    tmp_path: Path, launch, monkeypatch
) -> None:
    path = _author(tmp_path / "close_discard.pdf")
    before = path.read_bytes()
    app = launch(path)
    _editor_with_token(app)
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
    editor = _editor_with_token(app)
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


# --------------------------------- TEARDOWN-1: no preview thread outlives the app
#
# RED before: the harness ended the controller's preview session while a kept
# editor was still alive.  A keystroke typed shortly before the end of such a
# test leaves the editor's 150 ms debounce armed; it fired AFTER the session
# had been ended, and ``on_text_edit_plan_preview_request`` began a NEW
# session -- a running QThread nobody joined.  Destroying it at interpreter
# exit is a Qt fatal ("QThread: Destroyed while thread is still running"),
# i.e. every test that passed still exited with 0xC0000409.  The product's own
# close path finalizes the editor (CLOSE_DISCARD) before the window goes, so
# only the harness's shortcut was wrong.


def test_app_close_tears_the_editor_down_before_ending_the_preview_session(
    tmp_path: Path, launch
) -> None:
    path = _author(tmp_path / "late_keystroke.pdf")
    app = launch(path)
    editor = _editor_with_token(app)
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_X)
    assert editor._debounce.isActive(), "the keystroke did not arm the preview debounce"
    app.pump(100)
    app.close()

    coordinator = app.controller._text_commit_preview_coordinator
    assert coordinator is not None
    assert app.editor() is None, "the harness left the inline editor alive"
    assert not coordinator.has_active_session, "a late debounce began a new preview session"
    assert coordinator._thread is None, "a preview worker thread is still running"
    assert all(thread.isFinished() for thread, _worker in coordinator._retired)


def test_kept_editor_with_a_late_keystroke_exits_the_process_cleanly() -> None:
    """The symptom itself: pytest must exit 0, not 0xC0000409, after a test
    that ends with a kept editor and a late keystroke.  Runs the focus-keeping
    test alone in a fresh interpreter (the crash is at process teardown, so
    nothing in-process can observe it)."""
    node = f"{Path(__file__).as_posix()}::test_refused_token_apply_keeps_focus_and_its_result"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = (completed.stdout + completed.stderr)[-1500:]
    assert " passed" in completed.stdout, tail
    assert completed.returncode == 0, f"exit {completed.returncode} after the run\n{tail}"


# ============================================================ part 5 / A1: IME
#
# An input-method composition (preedit) lives in the editor's layout, NOT in
# ``toPlainText()``.  Every finalize path must treat it as un-applied input:
# a keep-reason refuses and keeps the editor + the preedit, a close-always
# reason discards visibly, and nothing is ever committed WITHOUT the preedit
# (the token text excludes it).  Offscreen Qt has no platform input context,
# so ``QInputMethodEvent`` is sent by hand.

_COMPOSING_WORD = "組字"
_PREEDIT = "mo"


def _send_preedit(editor, text: str) -> None:
    QApplication.sendEvent(editor, QInputMethodEvent(text, []))


def _send_commit(editor, text: str) -> None:
    event = QInputMethodEvent("", [])
    event.setCommitString(text)
    QApplication.sendEvent(editor, event)


def _composing_with_token(app: _App):
    """An edit with a verified token, then a composition on top of it."""
    editor = _editor_with_token(app)
    _send_preedit(editor, _PREEDIT)
    app.pump(300)
    assert editor.toPlainText() == _EDIT_B, "precondition: the preedit reached the document"
    return editor


def _assert_kept_with_preedit(
    app: _App, editor, requests_before: int = 0, *, saved: bool = False
) -> None:
    assert app.editor() is editor, "the editor was torn down during a composition"
    assert editor.toPlainText() == _EDIT_B
    assert editor.preedit_text() == _PREEDIT, "the composition was dropped"
    assert len(app.requests) == requests_before, [r.new_text for r in app.requests]
    assert app.commits == []
    assert app.page_texts() == _original_texts()
    if not saved:
        assert app.modals == []


def _trigger_save_as(app: _App, monkeypatch) -> list[int]:
    dialogs: list[int] = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: dialogs.append(1) or ("", ""))
    )
    app.view._action_save_as.trigger()
    return dialogs


@pytest.mark.parametrize(
    "reason",
    [
        TextEditFinalizeReason.APPLY,
        TextEditFinalizeReason.CLICK_AWAY,
        TextEditFinalizeReason.FOCUS_OUTSIDE,
        TextEditFinalizeReason.SAVE_SHORTCUT,
        TextEditFinalizeReason.CLOSE_DOCUMENT,
        TextEditFinalizeReason.VIEW_RESCALE,
    ],
)
def test_every_keep_reason_keeps_the_editor_and_the_preedit(
    tmp_path: Path, launch, reason: TextEditFinalizeReason
) -> None:
    """RED before: the finalize read only ``toPlainText()``, so a valid token
    committed the text WITHOUT the composition (and tore the editor down,
    dropping the preedit).  Now every keep reason refuses and says why."""
    app = launch(_author(tmp_path / f"preedit_{reason.value}.pdf"))
    editor = _composing_with_token(app)
    since = time.monotonic()
    result = app.view._finalize_text_edit(reason)
    app.pump(200)

    assert result is not None and result.outcome.value == "refused", result
    _assert_kept_with_preedit(app, editor)
    assert any(_COMPOSING_WORD in m for m in app.warnings_since(since)), app.toasts


def test_apply_is_disabled_while_composing_and_a_click_sends_nothing(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "preedit_apply.pdf"))
    editor = _composing_with_token(app)
    assert app.view.text_apply_btn.isEnabled() is False
    assert editor.is_composing() and editor.current_plan_token() is None
    app.click_apply()
    _assert_kept_with_preedit(app, editor)


def test_has_unapplied_input_counts_a_preedit_over_unchanged_text(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "preedit_unapplied.pdf"))
    editor = app.open_editor("Pump Room")
    assert app.view.has_unapplied_text_edit() is False
    _send_preedit(editor, _PREEDIT)
    assert app.view.has_unapplied_text_edit() is True
    _send_preedit(editor, "")
    assert app.view.has_unapplied_text_edit() is False


def test_untouched_box_with_a_preedit_is_not_a_no_op(tmp_path: Path, launch) -> None:
    """RED before: unchanged text + preedit -> NO_OP teardown lost the composition."""
    app = launch(_author(tmp_path / "preedit_untouched.pdf"))
    editor = app.open_editor("Pump Room")
    _send_preedit(editor, _PREEDIT)
    result = app.view._finalize_text_edit(TextEditFinalizeReason.CLICK_AWAY)
    app.pump(200)
    assert result is not None and result.outcome.value == "refused"
    assert app.editor() is editor and editor.preedit_text() == _PREEDIT
    assert app.requests == [] and app.commits == []


@pytest.mark.parametrize(
    "reason",
    [
        TextEditFinalizeReason.MODE_SWITCH,
        TextEditFinalizeReason.SESSION_SWITCH,
        TextEditFinalizeReason.SCENE_REBUILD,
    ],
)
def test_close_always_reasons_discard_a_composition_visibly(
    tmp_path: Path, launch, reason: TextEditFinalizeReason
) -> None:
    """The editor cannot survive; the token text excludes the preedit, so it
    is NEVER committed even with a valid token -- discarded, with a warning
    that names the composition."""
    app = launch(_author(tmp_path / f"preedit_close_{reason.value}.pdf"))
    _composing_with_token(app)
    since = time.monotonic()
    result = app.view._finalize_text_edit(reason)
    app.pump(200)

    assert result is not None and result.outcome.value == "discarded", result
    assert app.editor() is None
    assert app.requests == [] and app.commits == []
    assert app.page_texts() == _original_texts()
    warnings = app.warnings_since(since)
    assert any(_COMPOSING_WORD in m and _DISCARD_WORD in m for m in warnings), app.toasts


def test_the_composition_discard_notice_names_the_whole_input_not_only_the_composition(
    tmp_path: Path, launch
) -> None:
    """RED before: the notice said only the composition was discarded
    ("組字內容已捨棄") although the whole edit -- the verified text too -- is."""
    app = launch(_author(tmp_path / "preedit_notice.pdf"))
    _composing_with_token(app)
    since = time.monotonic()
    result = app.view._finalize_text_edit(TextEditFinalizeReason.SESSION_SWITCH)
    app.pump(200)

    assert result is not None and result.outcome.value == "discarded", result
    warnings = app.warnings_since(since)
    assert any(
        "輸入已捨棄" in m and "含組字中的內容" in m and "文件未變更" in m for m in warnings
    ), app.toasts
    assert not any("組字內容已捨棄" in m for m in warnings), warnings


def test_mode_switch_through_the_real_action_discards_a_composition(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "preedit_mode.pdf"))
    _composing_with_token(app)
    app.view._action_browse.trigger()
    app.pump(400)
    assert app.editor() is None and app.requests == [] and app.commits == []
    assert app.page_texts() == _original_texts()


def test_ctrl_s_and_save_as_during_a_composition_keep_everything(
    tmp_path: Path, launch, monkeypatch
) -> None:
    app = launch(_author(tmp_path / "preedit_save.pdf"))
    editor = _composing_with_token(app)
    # Q1: Ctrl+S saves the document as it is (the composition is not in it)
    # and keeps the editor, the input and the composition.
    app.view._action_save.trigger()
    app.pump(300)
    _assert_kept_with_preedit(app, editor, saved=True)
    dialogs = _trigger_save_as(app, monkeypatch)
    app.pump(300)
    _assert_kept_with_preedit(app, editor, saved=True)
    assert dialogs == [1], "Save As must still show its dialog"
    assert any(_COMPOSING_WORD in m for m, _t, _s in app.toasts), app.toasts


def test_ctrl_wheel_zoom_during_a_composition_is_refused(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "preedit_zoom.pdf"))
    editor = _composing_with_token(app)
    scale_before = app.view.scale
    _ctrl_wheel(app, notches=2)
    app.pump(800)
    _assert_kept_with_preedit(app, editor)
    assert app.view.scale == pytest.approx(scale_before)


def test_close_prompt_with_a_composition_prompts_and_save_keeps_the_editor(
    tmp_path: Path, launch
) -> None:
    """has_unapplied_input is True for a composition, so the close prompt
    shows; answering Save keeps the editor (nothing to commit), Discard
    closes without committing."""
    app = launch(_author(tmp_path / "preedit_close_doc.pdf"))
    editor = _composing_with_token(app)
    assert app.view.has_unapplied_text_edit() is True
    assert app.view.finalize_text_edit_for_close(save=True) is False
    _assert_kept_with_preedit(app, editor)
    assert app.view.finalize_text_edit_for_close(save=False) is True
    assert app.editor() is None and app.requests == [] and app.commits == []


def test_escape_during_a_composition_lets_the_input_method_take_it(
    tmp_path: Path, launch
) -> None:
    """A real IME consumes Escape to cancel the composition; the shortcut
    forwarder must not discard the whole edit under it."""
    app = launch(_author(tmp_path / "preedit_escape.pdf"))
    editor = _composing_with_token(app)
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_Escape)
    app.pump(300)
    assert app.editor() is editor, "Escape discarded the edit during a composition"
    assert editor.toPlainText() == _EDIT_B


def test_preedit_then_commit_string_keeps_both_parts_and_commits_them(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "preedit_commit.pdf"))
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, "Pump Ro")
    _send_preedit(editor, "m")
    app.pump(300)
    assert editor.toPlainText() == "Pump Ro" and editor.is_composing()
    _send_commit(editor, "mo")
    app.pump(100)
    assert editor.toPlainText() == _EDIT_B and not editor.is_composing()
    assert app.wait_token(editor)
    app.click_apply()
    assert [r.new_text for r in app.requests] == [_EDIT_B]
    assert len(app.commits) == 1
    assert app.page_texts() == _edited_texts()
    assert app.editor() is None


def test_a_cancelled_composition_re_enables_apply_without_a_keystroke(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "preedit_cancel.pdf"))
    editor = _composing_with_token(app)
    assert app.view.text_apply_btn.isEnabled() is False
    _send_preedit(editor, "")
    assert not editor.is_composing()
    # Qt itself reports the composition start/end as a text change (a new
    # generation), so the verified preview is re-requested: no keystroke.
    assert app.wait_token(editor)
    assert app.view.text_apply_btn.isEnabled() is True


def test_an_add_box_holding_only_a_preedit_is_kept_on_click_away(
    tmp_path: Path, launch
) -> None:
    from test_scripts.test_text_commit_add_text_intent import _open_add_box

    app = launch(_author(tmp_path / "preedit_add.pdf"))
    editor = _open_add_box(app, 72.0, 450.0)
    _send_preedit(editor, _PREEDIT)
    app.pump(200)
    result = app.view._finalize_text_edit(TextEditFinalizeReason.CLICK_AWAY)
    app.pump(200)
    assert result is not None and result.outcome.value == "refused", result
    assert app.editor() is editor and editor.preedit_text() == _PREEDIT
    assert app.requests == []
    assert app.view.has_unapplied_text_edit() is True


# ---- IME display (hypothesis B: the paint path never drew the preedit)


def test_preedit_events_reach_the_embedded_editor_through_the_view(
    tmp_path: Path, launch
) -> None:
    """Routing probe: the REAL Qt focus widget is the graphics view (or its
    viewport); an input-method event sent there must reach the proxy-embedded
    editor's text layout."""
    app = launch(_author(tmp_path / "preedit_route.pdf"))
    editor = app.open_editor("Pump Room")
    editor.setFocus()
    app.pump(100)
    focus = QApplication.focusWidget()
    graphics_view = app.view.graphics_view
    assert focus in (graphics_view, graphics_view.viewport()), focus
    _send_preedit(focus, _PREEDIT)
    app.pump(100)
    assert editor.textCursor().block().layout().preeditAreaText() == _PREEDIT
    assert app.view.graphics_view.inputMethodQuery(Qt.ImEnabled)


def test_the_ime_cursor_rectangle_is_a_non_empty_anchor(tmp_path: Path, launch) -> None:
    """RED before (V1 review fix-up 1): the plan-mode editor hides its caret
    (cursor width 0) and the widening override raised TypeError on
    ``QRect(QRectF)`` -- so the candidate window got a zero-width anchor."""
    app = launch(_author(tmp_path / "ime_rect.pdf"))
    editor = app.open_editor("Pump Room")
    app.pump(100)
    assert editor.cursorWidth() == 0, "precondition: plan mode hides the caret"
    rect = editor.inputMethodQuery(Qt.ImCursorRectangle)
    assert rect.width() > 0 and rect.height() > 0, rect


@pytest.mark.parametrize("typed", [False, True])
def test_a_preedit_is_visible_in_the_editor_paint(tmp_path: Path, launch, typed: bool) -> None:
    """RED before: the viewport was pixel-identical with and without a
    composition (frozen-frame short-circuit / plan frame never drew it).
    Round 7: the box shows the 組字中 badge and the preedit is drawn in the
    live text strip above it (no in-box chip in plan mode)."""
    app = launch(_author(tmp_path / f"preedit_paint_{typed}.pdf"))
    editor = app.open_editor("Pump Room")
    if typed:
        app.type_replacing_all(editor, _EDIT_B)
        app.wait_token(editor)
    app.pump(100)
    before = editor.viewport().grab().toImage()
    _send_preedit(editor, _PREEDIT)
    app.pump(100)
    after = editor.viewport().grab().toImage()
    assert before != after, "the composing badge left the viewport pixel-identical"
    strip = app.view.text_action_bar.live_text_strip
    assert strip.isVisible() and strip.preedit_area()[1] == _PREEDIT
    assert editor.plan_preview_badge_text() == "組字中"
    assert editor.plan_preview_pending() is True
    _send_preedit(editor, "")
    if typed:
        app.wait_token(editor)
    app.pump(100)
    assert editor.plan_preview_badge_text() != "組字中"
    assert editor.viewport().grab().toImage() == before, "the overlay did not go away"


@pytest.mark.parametrize("typed", [False, True])
def test_a_plan_mode_box_paints_no_chip_while_composing(
    tmp_path: Path, launch, typed: bool
) -> None:
    """Round 7 / F2 (real app, M8 b): while composing in plan mode the
    bottom-left band of the box grab equals the frame painted before the
    composition -- no chip pixels -- and the badge is the only change."""
    app = launch(_author(tmp_path / f"preedit_nochip_{typed}.pdf"))
    editor = app.open_editor("Pump Room")
    if typed:
        app.type_replacing_all(editor, _EDIT_B)
        app.wait_token(editor)
    app.pump(100)
    before = editor.viewport().grab().toImage()
    _send_preedit(editor, _PREEDIT)
    app.pump(100)
    after = editor.viewport().grab().toImage()
    assert after.size() == before.size()
    width, height = before.width(), before.height()
    # The left quarter is clear of the top-right badge (about 33 px wide here),
    # so any change in it is the chip.
    assert width - width // 4 >= 40, "the band would overlap the badge"
    band = [
        (x, y)
        for y in range(max(0, height - 12), height)
        for x in range(0, max(1, width // 4))
    ]
    changed = [(x, y) for x, y in band if before.pixel(x, y) != after.pixel(x, y)]
    assert changed == [], f"chip pixels in the bottom-left band: {changed[:5]}"
    assert before != after, "the 組字中 badge must still be painted"
    _send_preedit(editor, "")


# ======================================================== part 5 / A2: F5 (Q4)
#
# Owner decision Q4: F5 with a verified token commits first, then enters
# fullscreen -- exactly like zoom.  A refused / unverified / composing input
# keeps the editor and the input and enters nothing (and clears nothing: the
# search state, the fullscreen snapshot and the mode stay as they were).


def _press_f5(app: _App, editor) -> None:
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_F5)
    app.pump(600)


def _assert_fullscreen_refused(app: _App, editor, requests_before: int = 0) -> None:
    assert app.view.is_fullscreen_active() is False, "F5 entered fullscreen with un-applied input"
    assert app.editor() is editor, "F5 closed the editor"
    assert len(app.requests) == requests_before
    assert app.commits == []
    # Nothing was cleared by the refused F5.
    assert app.controller._fullscreen_session_snapshots == {}
    assert app.view.current_mode == "edit_text"


def test_ctrl_wheel_zoom_with_a_verified_token_commits_then_zooms(
    tmp_path: Path, launch
) -> None:
    """GUARD (green before and after; labelled, not a red): the zoom
    behaviour F5 must mirror -- a verified token commits, THEN the view
    rescales."""
    app = launch(_author(tmp_path / "zoom_token.pdf"))
    _editor_with_token(app)
    scale_before = app.view.scale
    _ctrl_wheel(app, notches=2)
    app.pump(800)

    assert len(app.commits) == 1, "the zoom did not commit the verified token"
    assert app.editor() is None
    assert app.view.scale != pytest.approx(scale_before)
    assert app.page_texts() == _edited_texts()


def test_f5_with_an_untouched_editor_enters_fullscreen(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "f5_clean.pdf"))
    editor = app.open_editor("Pump Room")
    _press_f5(app, editor)
    assert app.view.is_fullscreen_active() is True, "F5 never reached enter_fullscreen"
    assert app.editor() is None
    assert app.requests == [] and app.commits == []


def test_f5_with_a_verified_token_commits_then_enters_fullscreen(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "f5_token.pdf"))
    editor = _editor_with_token(app)
    _press_f5(app, editor)
    assert len(app.commits) == 1, "F5 did not commit the verified token"
    assert app.view.is_fullscreen_active() is True
    assert app.editor() is None
    assert app.page_texts() == _edited_texts()
    assert app.view._last_text_edit_finalize_result.reason.value == "fullscreen"


def test_f5_with_an_unverified_input_keeps_everything(tmp_path: Path, launch) -> None:
    """RED before: the MODE_SWITCH finalize discarded the unverified input
    (after the search was cancelled and the snapshot taken)."""
    app = launch(_author(tmp_path / "f5_unverified.pdf"))
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    since = time.monotonic()
    _press_f5(app, editor)
    _assert_fullscreen_refused(app, editor)
    assert editor.toPlainText() == _EDIT_B
    assert app.warnings_since(since), "the refused F5 gave no reason"
    assert _discard_warnings(app, since) == [], app.toasts


def test_f5_with_a_refused_input_keeps_everything(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "f5_refused.pdf"), preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    since = time.monotonic()
    _press_f5(app, editor)
    _assert_fullscreen_refused(app, editor, requests_before=1)
    assert editor.toPlainText() == _REFUSED_INPUT
    assert _discard_warnings(app, since) == [], app.toasts
    assert app.page_texts() == _original_texts()


def test_f5_with_a_plan_refused_input_keeps_everything(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "f5_plan_refused.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    _press_f5(app, editor)
    _assert_fullscreen_refused(app, editor)
    assert editor.toPlainText() == _REFUSED_INPUT


def test_f5_during_a_composition_keeps_everything(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "f5_preedit.pdf"))
    editor = _composing_with_token(app)
    since = time.monotonic()
    _press_f5(app, editor)
    _assert_fullscreen_refused(app, editor)
    assert editor.preedit_text() == _PREEDIT
    assert any(_COMPOSING_WORD in m for m in app.warnings_since(since)), app.toasts


def test_a_refused_f5_leaves_the_search_state_alone(tmp_path: Path, launch) -> None:
    """RED before: ``enter_fullscreen`` cancelled the search and cleared the
    search UI BEFORE the editor finalize had its say."""
    app = launch(_author(tmp_path / "f5_search.pdf", pages=2))
    _search(app, "Buffer", expected=2)
    results_before = app.view.search_results_list.count()
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    _press_f5(app, editor)
    _assert_fullscreen_refused(app, editor)
    assert app.view.search_results_list.count() == results_before


# ============================================ part 5 / A3: Ctrl+S (Q1), defect 3
#
# Q1: token -> commit, then save.  No token / refused -> the document is saved
# as it is, the editor and the input stay, and the notice names the REAL state
# (defect 3: a plan-mode refusal used to get the "preview still updating"
# wording).  ``_save`` adds no dialog; ``_save_as`` shows its dialog as usual.


def _arm_save(app: _App, monkeypatch, out: Path):
    """Record every save / save-as and route the Save As dialog to ``out``.
    Returns (saves, dialogs)."""
    saves: list[str] = []
    dialogs: list[int] = []
    app.view.sig_save.connect(lambda: saves.append("save"))
    app.view.sig_save_as.connect(lambda path: saves.append(path))
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: dialogs.append(1) or (str(out), "")),
    )
    return saves, dialogs


def _do_save(app: _App, which: str) -> None:
    (app.view._action_save if which == "save" else app.view._action_save_as).trigger()
    app.pump(600)


@pytest.mark.parametrize("which", ["save", "save_as"])
def test_save_with_a_verified_token_commits_then_saves(
    tmp_path: Path, launch, monkeypatch, which: str
) -> None:
    """GUARD (green before and after; labelled, not a red)."""
    path = _author(tmp_path / f"s_token_{which}.pdf")
    out = tmp_path / f"s_token_{which}_out.pdf"
    app = launch(path)
    saves, dialogs = _arm_save(app, monkeypatch, out)
    _editor_with_token(app)
    _do_save(app, which)

    assert len(app.commits) == 1
    assert app.editor() is None
    assert len(saves) == 1
    assert dialogs == ([] if which == "save" else [1])
    target = path if which == "save" else out
    assert _file_texts(target) == _edited_texts()


def test_status_bar_drops_the_modified_mark_after_a_save(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """Owner screenshot 2026-10-26: after Ctrl+S the tab title dropped its
    ``*`` while the status bar still read 已修改.  The status bar is built from
    ``has_unsaved_changes()`` and must be refreshed by the save itself."""
    path = _author(tmp_path / "status_after_save.pdf")
    out = tmp_path / "status_after_save_out.pdf"
    app = launch(path)
    _arm_save(app, monkeypatch, out)
    first = app.open_editor("Buffer Tank")
    app.type_replacing_all(first, _EDIT_A)
    assert app.wait_token(first)
    app.click_apply()
    assert len(app.commits) == 1
    app.view._update_status_bar()
    assert "已修改" in app.view.status_bar.currentMessage()
    _do_save(app, "save")

    assert not app.model.has_any_unsaved_changes()
    assert "已修改" not in app.view.status_bar.currentMessage(), (
        app.view.status_bar.currentMessage()
    )


@pytest.mark.parametrize("which", ["save", "save_as"])
@pytest.mark.parametrize("state", ["plan_refused", "legacy_refused", "pending"])
def test_save_without_a_token_saves_as_is_and_names_the_real_state(
    tmp_path: Path, launch, monkeypatch, which: str, state: str
) -> None:
    """RED before (plan_refused): the notice said "預覽仍在更新" for a
    refusal.  The document is saved without the edit, the editor and the
    input stay, nothing is sent, and the notice matches the editor's state."""
    path = _author(tmp_path / f"s_{state}_{which}.pdf")
    out = tmp_path / f"s_{state}_{which}_out.pdf"
    if state == "legacy_refused":
        app = launch(path, preview="legacy", max_tier="0")
    else:
        app = launch(path, max_tier="0" if state == "plan_refused" else "1")
    saves, dialogs = _arm_save(app, monkeypatch, out)
    if state == "legacy_refused":
        editor = _refuse_by_apply(app)
        typed, requests_before = _REFUSED_INPUT, 1
    elif state == "plan_refused":
        editor = _refused_by_plan_preview(app)
        typed, requests_before = _REFUSED_INPUT, 0
    else:
        editor = app.open_editor("Pump Room")
        app.type_replacing_all(editor, _EDIT_B)
        typed, requests_before = _EDIT_B, 0
    since = time.monotonic()
    _do_save(app, which)

    assert app.editor() is editor and editor.toPlainText() == typed
    assert len(app.requests) == requests_before, "the input was re-sent"
    assert app.commits == []
    assert len(saves) == 1
    assert dialogs == ([] if which == "save" else [1])
    assert app.page_texts() == _original_texts()
    warnings = app.warnings_since(since)
    assert warnings, "the kept edit gave no reason"
    if state == "pending":
        assert any("預覽仍在更新" in m for m in warnings), warnings
    else:
        assert all("預覽仍在更新" not in m for m in warnings), warnings
        assert any("拒絕" in m for m in warnings), warnings


@pytest.mark.parametrize("which", ["save", "save_as"])
@pytest.mark.parametrize("state", ["plan_refused", "composing", "pending"])
def test_the_save_kept_notice_does_not_claim_the_document_is_unchanged(
    tmp_path: Path, launch, monkeypatch, which: str, state: str
) -> None:
    """RED before (V1 review fix-up 4): Ctrl+S / Save As with an editor that is
    refused, composing or unverified SAVES the document as it is, yet the kept
    notice said "文件未變更" right before the modal said it was saved.  The
    notice must say the edit was not applied and that the saved file lacks it,
    and keep the state's own reason."""
    path = _author(tmp_path / f"kn_{state}_{which}.pdf")
    out = tmp_path / f"kn_{state}_{which}_out.pdf"
    app = launch(path, max_tier="0" if state == "plan_refused" else "1")
    saves, _dialogs = _arm_save(app, monkeypatch, out)
    if state == "plan_refused":
        _refused_by_plan_preview(app)
    elif state == "composing":
        _composing_with_token(app)
    else:
        editor = app.open_editor("Pump Room")
        app.type_replacing_all(editor, _EDIT_B)
    since = time.monotonic()
    _do_save(app, which)

    assert len(saves) == 1, "the document is saved as it is"
    warnings = app.warnings_since(since)
    assert len(warnings) == 1, warnings
    notice = warnings[0]
    assert "文件未變更" not in notice, notice
    assert "未套用" in notice and "儲存的檔案不含" in notice, notice
    reason = {"plan_refused": "拒絕", "composing": _COMPOSING_WORD, "pending": "預覽仍在更新"}
    assert reason[state] in notice, notice


# ============================================ part 5 / Stage C: save, save_as, undo
#
# The semantic reopen compare of part 4 (umbrella ``save_reopen``) runs real
# fixtures and is skipped without them; these run on a synthetic document in
# CI.  Ctrl+S (``save``) writes INCREMENTALLY back to the original path;
# ``save_as`` to a new path is a full rewrite that leaves the original alone.
# Both must leave every non-target object semantically unchanged on reopen.


def _assert_saved_file_only_differs_in_the_edit(
    source: Path, saved: Path, source_objects, edited_stream_xrefs: set[int]
) -> None:
    from test_scripts import test_text_commit_real_corpus_acceptance as acc

    with fitz.open(str(saved)) as reopened:
        acc._assert_only_target_streams_changed(
            source_objects, reopened, edited_stream_xrefs, semantic=True
        )
        appended = [
            xref
            for xref in range(len(source_objects) + 1, reopened.xref_length())
            if reopened.xref_get_key(xref, "Type") != ("name", "/XRef")
        ]
        assert appended == [], f"the save appended non-XRef objects {appended}"
        assert reopened.embfile_count() == 0, "the save attached a file"
        catalog_after = reopened.xref_object(reopened.pdf_catalog(), compressed=True)
    with fitz.open(str(source)) as original:
        assert acc._objects_semantically_equal(
            original.xref_object(original.pdf_catalog(), compressed=True), catalog_after
        ), "the catalog changed"


@pytest.mark.parametrize("which", ["save", "save_as"])
def test_ui_save_and_save_as_reopen_semantically_equal_outside_the_edit(
    tmp_path: Path, launch, monkeypatch, which: str
) -> None:
    """GUARD (green before and after; labelled, not a red): token -> commit ->
    save/save_as, then reopen the file ON DISK and compare every object."""
    from test_scripts import test_text_commit_real_corpus_acceptance as acc

    path = _author(tmp_path / f"sem_{which}.pdf")
    out = tmp_path / f"sem_{which}_out.pdf"
    with fitz.open(str(path)) as source:
        source_objects = acc._object_snapshot(source)
        edited = {source[0].get_contents()[0]}
    original_bytes = path.read_bytes()

    app = launch(path)
    saves, dialogs = _arm_save(app, monkeypatch, out)
    _editor_with_token(app)
    _do_save(app, which)

    assert len(app.commits) == 1 and app.editor() is None and len(saves) == 1
    saved = path if which == "save" else out
    assert _file_texts(saved) == _edited_texts()
    _assert_saved_file_only_differs_in_the_edit(path, saved, source_objects, edited)
    if which == "save":
        # incremental: the original bytes are a verbatim prefix of the file
        assert saved.read_bytes().startswith(original_bytes)
    else:
        assert path.read_bytes() == original_bytes, "save_as touched the original file"


@pytest.mark.parametrize("which", ["save", "save_as"])
def test_ui_undo_after_a_renumbering_full_save_restores_the_original(
    tmp_path: Path, launch, monkeypatch, which: str
) -> None:
    """RED before (Stage C): a secure (``garbage=4``) save renumbers the LIVE
    document, the retained Tier 0 inverse targets the old xrefs, and the
    toolbar undo is refused for the rest of the session."""
    path = _author(tmp_path / f"renum_{which}.pdf", junk_objects=5)  # garbage=4 renumbers
    out = tmp_path / f"renum_{which}_out.pdf"
    app = launch(path)
    saves, _dialogs = _arm_save(app, monkeypatch, out)
    _editor_with_token(app)
    app.click_apply()
    assert len(app.commits) == 1 and app.editor() is None
    committed = app.page_texts()
    assert committed == _edited_texts()
    page_xref = app.model.doc[0].xref

    app.model.secure_save_required = True
    _do_save(app, which)
    assert len(saves) == 1
    assert app.model.doc[0].xref != page_xref, "the fixture must really renumber"
    assert app.page_texts() == committed

    depth = len(app.model.command_manager._undo_stack)
    app.click_toolbar_action(app.view._action_undo)
    assert len(app.model.command_manager._undo_stack) == depth - 1, "the undo was refused"
    assert app.page_texts() == _original_texts()
    app.click_toolbar_action(app.view._action_redo)
    assert app.page_texts() == committed


# ------------------------------------------------ R4-4: re-entering the same mode
#
# Owner (2026-10-06): pressing F2 while already in edit-text mode used to end
# the editor with MODE_SWITCH and discard the un-applied input.  Re-entering
# the CURRENT mode is not a mode switch; a real switch keeps the A1 rule.


def _run_info(app: _App, text: str):
    """The Controller's hit info for the run ``text`` (as the context menu gets it)."""
    rect = app.glyph_rect(text)
    centre = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    info = app.controller.get_text_info_at_point(1, centre, allow_fallback=True)
    assert info is not None and info.target_text == text, info
    return info


def test_f2_on_the_current_mode_keeps_a_refused_editor(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "f2_refused.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    since = time.monotonic()
    app.view._action_edit_text.trigger()
    app.pump(300)

    assert app.editor() is editor, "F2 on the current mode tore the editor down"
    assert editor.toPlainText() == _REFUSED_INPUT
    assert _discard_warnings(app, since) == [], app.toasts
    assert app.view.current_mode == "edit_text"
    assert app.view._mode_actions["edit_text"].isChecked()
    result = app.view._last_text_edit_finalize_result
    assert result is None or result.reason is not TextEditFinalizeReason.MODE_SWITCH, result


def test_f2_during_a_composition_keeps_the_preedit(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "f2_preedit.pdf"))
    editor = _composing_with_token(app)
    app.view._action_edit_text.trigger()
    app.pump(300)
    _assert_kept_with_preedit(app, editor)
    assert app.view.current_mode == "edit_text"


def test_reentering_add_text_keeps_an_add_box(tmp_path: Path, launch) -> None:
    from test_scripts.test_text_commit_add_text_intent import _open_add_box, _type

    app = launch(_author(tmp_path / "add_reenter.pdf"))
    editor = _open_add_box(app, 72.0, 450.0)
    _type(app, editor, "Hello")
    since = time.monotonic()
    app.view.set_mode("add_text")
    app.pump(200)

    assert app.editor() is editor, "re-entering add_text tore the add box down"
    assert editor.toPlainText() == "Hello"
    assert _discard_warnings(app, since) == [], app.toasts
    assert app.view.current_mode == "add_text"


def test_context_menu_edit_text_on_the_editors_own_run_keeps_it(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "ctx_own.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    info = _run_info(app, "Pump Room")
    since = time.monotonic()
    assert app.view._start_text_edit_from_hit(0, info) is True
    app.pump(200)

    assert app.editor() is editor, "the editor was discarded and reopened"
    assert editor.toPlainText() == _REFUSED_INPUT
    assert _discard_warnings(app, since) == [], app.toasts


def test_context_menu_edit_text_on_another_run_keeps_unapplied_input(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "ctx_other.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    info = _run_info(app, "Buffer Tank")
    original_text = app.view.editing_original_text
    page_idx = app.view._editing_page_idx
    since = time.monotonic()
    assert app.view._start_text_edit_from_hit(0, info) is False
    app.pump(200)

    assert app.editor() is editor, "the click-away rule did not keep the editor"
    assert editor.toPlainText() == _REFUSED_INPUT
    assert app.view.editing_original_text == original_text == "Pump Room"
    assert app.view._editing_page_idx == page_idx
    assert _discard_warnings(app, since) == [], app.toasts


def test_context_menu_edit_text_on_another_run_commits_a_verified_edit_first(
    tmp_path: Path, launch
) -> None:
    """GUARD (green before and after): a verified token commits, then the new run opens."""
    app = launch(_author(tmp_path / "ctx_commit.pdf"))
    editor = _editor_with_token(app)
    info = _run_info(app, "Buffer Tank")
    assert app.view._start_text_edit_from_hit(0, info) is True
    assert app.wait(lambda: app.editor() is not None and app.editor() is not editor, 20)

    assert len(app.commits) == 1, app.commits
    assert app.editor().toPlainText() == "Buffer Tank"


# ---- part 5 round 5: same-mode re-entry notifies only (never finalizes)
#
# Owner (2026-10-07, video 3): F2 on a kept, refused editor changed nothing and
# said nothing, while click-away / F5 / Ctrl+wheel each said why.  Re-entry
# still must not finalize (R4-4); it only names the refusal.


def _refusal_text(app: _App) -> str:
    reason_text = rejection_reason_text(
        app.view._ensure_text_edit_manager().current_rejection_reason()
    )
    assert reason_text
    return reason_text


def _blank_click(app: _App) -> None:
    app.click_scene_at(0, fitz.Rect(400, 700, 410, 710))


def test_f2_after_a_click_away_on_a_refused_editor_says_why_again(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "f2_after_click.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    reason_text = _refusal_text(app)
    since = time.monotonic()
    _blank_click(app)
    app.pump(300)
    assert len(app.warnings_since(since)) == 1, app.toasts

    app.view._action_edit_text.trigger()
    app.pump(300)
    warnings = app.warnings_since(since)
    assert len(warnings) == 2, warnings
    assert reason_text in warnings[1], warnings
    assert "保留" in warnings[1] and "編輯模式" in warnings[1], warnings
    assert _DISCARD_WORD not in warnings[1], warnings
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT
    assert app.view.current_mode == "edit_text"

    app.view._action_edit_text.trigger()
    app.pump(200)
    app.view._action_edit_text.trigger()
    app.pump(200)
    assert len(app.warnings_since(since)) == 2, app.toasts


def test_f2_on_a_refused_editor_says_why_once(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "f2_once.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    reason_text = _refusal_text(app)
    since = time.monotonic()
    for _ in range(3):
        app.view._action_edit_text.trigger()
        app.pump(200)

    warnings = app.warnings_since(since)
    assert len(warnings) == 1, warnings
    assert reason_text in warnings[0], warnings
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT


def test_f2_during_a_composition_names_the_cancelled_mode_switch(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "f2_compose_notice.pdf"))
    editor = _composing_with_token(app)
    since = time.monotonic()
    app.view._action_edit_text.trigger()
    app.pump(300)

    warnings = app.warnings_since(since)
    assert len(warnings) == 1, warnings
    assert _COMPOSING_WORD in warnings[0] and "切換模式" in warnings[0], warnings
    _assert_kept_with_preedit(app, editor)


def test_context_menu_edit_text_on_the_editors_own_run_says_why(
    tmp_path: Path, launch
) -> None:
    app = launch(_author(tmp_path / "ctx_own_notice.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    reason_text = _refusal_text(app)
    info = _run_info(app, "Pump Room")
    since = time.monotonic()
    assert app.view._start_text_edit_from_hit(0, info) is True
    app.pump(200)

    warnings = app.warnings_since(since)
    assert len(warnings) == 1, warnings
    assert reason_text in warnings[0], warnings
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT


def test_f2_with_a_verified_token_is_silent_and_commits_nothing(
    tmp_path: Path, launch
) -> None:
    """GUARD (green before and after): re-entry never finalizes."""
    app = launch(_author(tmp_path / "f2_token.pdf"))
    editor = _editor_with_token(app)
    since = time.monotonic()
    app.view._action_edit_text.trigger()
    app.pump(300)

    assert app.warnings_since(since) == [], app.toasts
    assert app.commits == []
    assert app.editor() is editor and editor.toPlainText() == _EDIT_B
    assert editor.current_plan_token() is not None


def test_f2_on_an_unchanged_editor_is_silent(tmp_path: Path, launch) -> None:
    """GUARD (green before and after)."""
    app = launch(_author(tmp_path / "f2_unchanged.pdf"))
    editor = app.open_editor("Pump Room")
    since = time.monotonic()
    app.view._action_edit_text.trigger()
    app.pump(300)

    assert app.warnings_since(since) == [], app.toasts
    assert app.editor() is editor


# ============================== part 5 round 4 / R4-3: say why, once
#
# A click or a focus change that the kept editor ignored used to say nothing
# (plan refusal / pending preview), and a composition always got the same
# generic words whatever action was cancelled.  Escape on changed text
# discarded silently.


def test_click_away_on_a_plan_refused_input_says_why_once(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "ca_refused.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    reason_text = _refusal_text(app)
    since = time.monotonic()
    _blank_click(app)
    app.pump(300)
    _blank_click(app)
    app.pump(300)

    warnings = app.warnings_since(since)
    assert len(warnings) == 1, warnings
    assert reason_text in warnings[0] and "保留" in warnings[0], warnings
    assert _DISCARD_WORD not in warnings[0], warnings
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT


def test_click_away_while_the_preview_is_pending_says_so(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "ca_pending.pdf"))
    editor = app.open_editor("Pump Room")
    editor.setPlainText(_EDIT_B)  # no pump: no verified preview yet
    since = time.monotonic()
    result = app.view._finalize_text_edit(TextEditFinalizeReason.CLICK_AWAY)

    assert result is not None and result.outcome.value == "refused", result
    warnings = app.warnings_since(since)
    assert len(warnings) == 1, warnings
    assert "預覽仍在更新" in warnings[0], warnings
    assert app.editor() is editor


def test_focus_leaving_a_refused_editor_says_why_once(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "fo_refused.pdf"), max_tier="0")
    editor = _refused_by_plan_preview(app)
    since = time.monotonic()
    app.view.page_number_input.setFocus()
    app.pump(300)
    editor.setFocus()
    app.view.graphics_view.setFocus()
    app.pump(100)
    app.view.page_number_input.setFocus()
    app.pump(300)

    warnings = app.warnings_since(since)
    assert len(warnings) == 1, warnings
    assert app.editor() is editor and editor.toPlainText() == _REFUSED_INPUT


def test_ctrl_s_then_focus_loss_gives_one_notice(tmp_path: Path, launch, monkeypatch) -> None:
    """GUARD plus stamp check: the SAVE notice and the focus change the save
    modal causes are one event for the user."""
    app = launch(_author(tmp_path / "save_focus.pdf"), max_tier="0")
    _saves, _dialogs = _arm_save(app, monkeypatch, tmp_path / "save_focus_out.pdf")
    _refused_by_plan_preview(app)
    since = time.monotonic()
    app.view._action_save.trigger()
    app.pump(300)
    app.view.page_number_input.setFocus()
    app.pump(300)

    assert len(app.warnings_since(since)) == 1, app.toasts


def test_focus_outside_notice_is_suppressed_under_a_modal(
    tmp_path: Path, launch, monkeypatch
) -> None:
    from PySide6.QtWidgets import QWidget

    app = launch(_author(tmp_path / "fo_modal.pdf"), max_tier="0")
    _refused_by_plan_preview(app)
    dialog = QWidget()
    since = time.monotonic()
    with monkeypatch.context() as patch:
        patch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: dialog))
        app.view._finalize_text_edit(TextEditFinalizeReason.FOCUS_OUTSIDE)
        assert app.warnings_since(since) == [], app.toasts
    app.view._finalize_text_edit(TextEditFinalizeReason.FOCUS_OUTSIDE)
    assert len(app.warnings_since(since)) == 1, app.toasts
    dialog.deleteLater()


@pytest.mark.parametrize(
    ("reason", "word"),
    [
        (TextEditFinalizeReason.FULLSCREEN, "全螢幕"),
        (TextEditFinalizeReason.VIEW_RESCALE, "縮放"),
        (TextEditFinalizeReason.CLICK_AWAY, "點擊"),
        (TextEditFinalizeReason.CLOSE_DOCUMENT, "關閉"),
        (TextEditFinalizeReason.APPLY, "套用"),
    ],
)
def test_composing_kept_notice_names_the_cancelled_action(
    tmp_path: Path, launch, reason: TextEditFinalizeReason, word: str
) -> None:
    app = launch(_author(tmp_path / f"cn_{reason.value}.pdf"))
    _composing_with_token(app)
    since = time.monotonic()
    app.view._finalize_text_edit(reason)
    app.pump(100)

    warnings = app.warnings_since(since)
    assert any(word in m and _COMPOSING_WORD in m for m in warnings), warnings


def test_escape_discarding_changed_text_says_so_once(tmp_path: Path, launch) -> None:
    app = launch(_author(tmp_path / "esc_changed.pdf"))
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    since = time.monotonic()
    QTest.keyClick(editor, Qt.Key_Escape)
    app.pump(200)

    assert app.editor() is None
    warnings = app.warnings_since(since)
    assert len(warnings) == 1 and _DISCARD_WORD in warnings[0], warnings


def test_escape_on_unchanged_text_is_silent(tmp_path: Path, launch) -> None:
    """GUARD (green before and after)."""
    app = launch(_author(tmp_path / "esc_same.pdf"))
    editor = app.open_editor("Pump Room")
    since = time.monotonic()
    QTest.keyClick(editor, Qt.Key_Escape)
    app.pump(200)

    assert app.editor() is None
    assert app.warnings_since(since) == [], app.toasts
