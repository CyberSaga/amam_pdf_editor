"""Finalize by the real result, view-side token invalidation, session binding.

UI critique step 9 of plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md
plus three defects from the 2026-09-30 VERIFY (part 2):

(a) The inline editor is torn down only when the Controller's REAL result is
    SUCCESS.  A refused Apply (REJECTED / PREVIEW_PENDING / PREVIEW_STALE /
    DECLINED) keeps the editor and the typed input and shows the reason, never
    a success notice.  Click-away with no verified preview keeps the editor
    (owner decision 2026-09-30).  A mode switch, a session change or a scene
    rebuild cannot keep it: it commits a verified edit, otherwise it discards
    with a visible "not applied" warning -- never silently.
(b) A document mutation while the editor is open (toolbar undo) and a page
    switch that keeps the editor open invalidate the token and re-request a
    preview, so a stale token can never be applied.
(c) Opening another document finalizes the editor against the ORIGINAL
    session first, and every request is bound to the document session it
    was made in, so it can never commit into another document -- not even
    a byte-identical copy at another path (the headline VERIFY defect).

Every test launches the real app through ``main.run`` (the composition root;
``TextCommitSettings.from_env`` and ``PDFController.activate()`` run as for a
user) on SYNTHETIC Identity-H documents (plan section 10 data policy), drives
it with real QTest input, and only records: modal dialogs return a safe
default (a real modal hangs offscreen pytest), toasts / requests / engine
commits pass through.  User preferences go to an in-memory store so a test
never writes the real recent-files list.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.edit_requests import EditTextRequest  # noqa: E402
from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402

from test_scripts.type0_fixture_builder import encode_cids  # noqa: E402
from view.text_editing import ESCAPE_DISCARD_NOTICE  # noqa: E402

_PAGE_W, _PAGE_H = 595.0, 842.0
#: (x, y-from-top, text).  Replacements permute the same glyphs: equal
#: advance, so a verified Tier 0 candidate exists for each.
_LINES = ((72.0, 150.0, "Buffer Tank"), (72.0, 300.0, "Pump Room"))
_EDIT_A = "Buffer Tnak"
_EDIT_B = "Pump Romo"
PREVIEW_TIMEOUT_S = 30.0


# ---------------------------------------------------------------- fixtures


def _author(path: Path, pages: int = 1, *, junk_objects: int = 0) -> Path:
    """Synthetic Identity-H page(s): one hex ``Tj`` per line.

    ``junk_objects`` unreferenced objects go ahead of the page(s), so a
    ``garbage=4`` save renumbers."""
    font = fitz.Font("cjk")
    doc = fitz.open()
    for _ in range(junk_objects):
        doc.update_object(doc.get_new_xref(), "<< /Junk 1 >>")
    for _ in range(pages):
        page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
        writer = fitz.TextWriter(page.rect)
        for x, y, text in _LINES:
            writer.append((x, y), text, font=font, fontsize=12)
        writer.write_text(page)
        name = page.get_fonts(full=True)[0][4]
        body = " ".join(
            f"BT /{name} 12 Tf 1 0 0 1 {x:g} {_PAGE_H - y:g} Tm "
            f"<{encode_cids(text).hex().upper()}> Tj ET"
            for x, y, text in _LINES
        )
        doc.update_stream(page.get_contents()[0], body.encode("ascii"))
    doc.save(str(path))
    doc.close()
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _MemoryStore:
    """QSettings stand-in: never touch the user's real preferences."""

    def __init__(self) -> None:
        self._data: dict = {}

    def value(self, key, default=None, type=None):  # noqa: A002
        return self._data.get(key, default)

    def setValue(self, key, value) -> None:
        self._data[key] = value

    def remove(self, key) -> None:
        self._data.pop(key, None)

    def sync(self) -> None:
        return None


class _App:
    """One real app (``main.run``) on a tmp document, recorders only."""

    def __init__(self, monkeypatch, path: Path, *, preview: str = "plan", max_tier: str = "1"):
        from PySide6.QtWidgets import QMessageBox

        import controller.pdf_controller as controller_module
        import main
        import utils.preferences as preferences
        import view.message_boxes as message_boxes
        import view.pdf_view as pdf_view_module

        monkeypatch.setenv("TEXT_COMMIT_ENGINE", "tiered")
        monkeypatch.setenv("TEXT_COMMIT_MAX_TIER", max_tier)
        monkeypatch.setenv("TEXT_COMMIT_PREVIEW", preview)
        for name in ("TEXT_COMMIT_STRICT", "TEXT_COMMIT_TELEMETRY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(preferences, "_make_default_store", _MemoryStore)
        self.modals: list[tuple[str, str]] = []
        self.toasts: list[tuple[str, str, float]] = []
        self.requests: list = []
        self.payloads: list[dict] = []
        self.deliveries: list[dict] = []
        self.commits: list[tuple[object, object, object, float]] = []

        def _modal(kind: str, default):
            def _record(*args, **kwargs):
                texts = [str(a) for a in args[1:3] if isinstance(a, str)]
                self.modals.append((kind, " | ".join(texts)))
                return default

            return _record

        monkeypatch.setattr(QMessageBox, "information", staticmethod(_modal("information", QMessageBox.Ok)))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(_modal("warning", QMessageBox.Ok)))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(_modal("critical", QMessageBox.Ok)))
        monkeypatch.setattr(QMessageBox, "question", staticmethod(_modal("question", QMessageBox.No)))
        monkeypatch.setattr(QMessageBox, "exec", lambda box, *a, **k: self.modals.append(("exec", box.text())) or 0)
        for module in (controller_module, message_boxes, pdf_view_module):
            if hasattr(module, "show_error"):
                monkeypatch.setattr(module, "show_error", _modal("show_error", None))
        monkeypatch.setattr(
            controller_module, "confirm_degraded_fallback", _modal("confirm_degraded_fallback", False)
        )
        original_commit = TieredCommitEngine.commit

        def _commit_spy(engine, prepared):
            outcome = original_commit(engine, prepared)
            self.commits.append((engine._doc, prepared, outcome, time.monotonic()))
            return outcome

        monkeypatch.setattr(TieredCommitEngine, "commit", _commit_spy)

        startup = main.run(argv=[str(path)], start_event_loop=False)
        self.app = startup["app"]
        self.view = view = startup["view"]
        self.model = startup["model"]
        self.controller = startup["controller"]
        assert self.model is not None and self.controller is not None
        original_toast = view._show_toast

        def _toast(message, duration_ms=1500, tone="success"):
            self.toasts.append((str(message), str(tone), time.monotonic()))
            return original_toast(message, duration_ms, tone)

        view._show_toast = _toast
        original_delivery = view.apply_text_edit_plan_preview

        def _delivery(**kwargs):
            self.deliveries.append(
                {
                    "generation": kwargs.get("generation"),
                    "plan_token": kwargs.get("plan_token"),
                    "t": time.monotonic(),
                }
            )
            return original_delivery(**kwargs)

        view.apply_text_edit_plan_preview = _delivery
        view.sig_text_edit_plan_preview.connect(
            lambda payload: self.payloads.append(dict(payload, t=time.monotonic()))
        )
        view.sig_edit_text.connect(self.requests.append)
        view.resize(1200, 900)
        view.show()
        view.activateWindow()
        self.pump(300)

    # ---- event loop

    def pump(self, ms: float) -> None:
        end = time.monotonic() + ms / 1000.0
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def wait(self, predicate, timeout_s: float = PREVIEW_TIMEOUT_S) -> bool:
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        self.app.processEvents()
        return bool(predicate())

    # ---- readers

    def editor(self):
        proxy = self.view.text_editor
        return proxy.widget() if proxy is not None else None

    def page_texts(self, doc: fitz.Document | None = None, page_index: int = 0) -> list[str]:
        """Decoded show texts of one page (stream replay; never the live extraction)."""
        doc = doc if doc is not None else self.model.doc
        page = doc[page_index]
        shows = replay_page_streams([(x, doc.xref_stream(x)) for x in page.get_contents()]).shows
        return [show.decoded_bytes for show in shows]

    def warnings_since(self, since: float) -> list[str]:
        return [m for m, tone, t in self.toasts if t >= since and tone == "warning"]

    def successes_since(self, since: float) -> list[str]:
        return [m for m, tone, t in self.toasts if t >= since and tone == "success"]

    # ---- real input

    def enter_edit_text_run_mode(self) -> None:
        if self.view.current_mode != "edit_text":
            self.view._action_edit_text.trigger()
            self.pump(100)
        combo = self.view.text_target_mode_combo
        combo.setCurrentIndex(combo.findData("run"))
        self.pump(80)
        assert self.model.text_target_mode == "run"

    def glyph_rect(self, text: str, page_index: int = 0) -> fitz.Rect:
        rects = self.model.doc[page_index].search_for(text)
        assert rects, f"fixture text {text!r} not found"
        return rects[0]

    def click_scene_at(self, page_index: int, rect: fitz.Rect) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        centre = self.view._doc_rect_to_scene_rect(page_index, rect).center()
        position = self.view.graphics_view.mapFromScene(centre)
        QTest.mouseClick(self.view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, position)

    def open_editor(self, text: str, page_index: int = 0):
        self.enter_edit_text_run_mode()
        rect = self.glyph_rect(text, page_index)
        centre = self.view._doc_rect_to_scene_rect(page_index, rect).center()
        self.view.graphics_view.centerOn(centre)
        self.pump(150)
        self.click_scene_at(page_index, rect)
        assert self.wait(lambda: self.editor() is not None, 20), "click opened no editor"
        editor = self.editor()
        assert editor.toPlainText() == text
        return editor

    def type_replacing_all(self, editor, text: str) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        editor.setFocus()
        QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(editor, text)

    def wait_token(self, editor) -> str:
        assert self.wait(lambda: editor.current_plan_token() is not None), "no verified preview"
        self.pump(40)
        return editor.current_plan_token()

    def click_apply(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        button = self.view.text_apply_btn
        QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
        self.pump(400)

    def click_toolbar_action(self, action) -> None:
        """A real mouse click on the toolbar button that carries ``action``."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QToolButton

        buttons = [w for w in action.associatedObjects() if isinstance(w, QToolButton)]
        assert buttons, "the action has no toolbar button"
        tabs = self.view.toolbar_tabs
        for index in range(tabs.count()):
            if tabs.widget(index).isAncestorOf(buttons[0]):
                # The ribbon tab a user would pick first (QTabBar takes no click focus).
                tabs.setCurrentIndex(index)
                break
        self.pump(80)
        assert buttons[0].isVisible(), "the toolbar button is not visible"
        QTest.mouseClick(buttons[0], Qt.LeftButton, Qt.NoModifier, buttons[0].rect().center())
        self.pump(400)

    def wheel_until_page(self, target_page: int, direction: int, max_notches: int = 400) -> float:
        """Real wheel events over the viewport; returns when ``current_page`` arrived."""
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication

        viewport = self.view.graphics_view.viewport()
        position = QPointF(viewport.rect().center())
        global_position = QPointF(viewport.mapToGlobal(viewport.rect().center()))
        notches = 0
        while self.view.current_page != target_page and notches < max_notches:
            event = QWheelEvent(
                position,
                global_position,
                QPoint(0, 0),
                QPoint(0, 120 * direction),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.NoScrollPhase,
                False,
            )
            QApplication.sendEvent(viewport, event)
            self.app.processEvents()
            notches += 1
        arrived = time.monotonic()
        assert self.view.current_page == target_page, (
            f"the wheel did not reach page {target_page} (at {self.view.current_page})"
        )
        return arrived

    def close(self) -> None:
        try:
            try:
                # Tear a kept editor down FIRST, exactly as the real close path
                # does (CLOSE_DISCARD): a live editor's armed preview debounce
                # would otherwise fire after the session ended below, begin a
                # new session, and leave a running QThread that Qt aborts on at
                # interpreter exit (0xC0000409 after "N passed").
                self.view.finalize_text_edit_for_close(save=False)
                self.controller._end_text_edit_plan_preview_session()
                coordinator = getattr(self.controller, "_text_commit_preview_coordinator", None)
                if coordinator is not None:
                    coordinator.wait_for_done(int(PREVIEW_TIMEOUT_S * 1000))
            finally:
                self.controller.handle_app_close = lambda event: event.accept()
                self.view.close()
                self.pump(80)
        finally:
            self.model.close()
            self.app.setStyleSheet("")
            self.pump(40)


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


def _original_texts() -> list[bytes]:
    return [encode_cids(text) for _, _, text in _LINES]


# ------------------------------------------------------ (a) finalize by result


def test_refused_apply_keeps_the_editor_the_input_and_the_pdf(tmp_path: Path, launch) -> None:
    """RED before step 9: finalize returned COMMITTED once the signal emitted
    and tore the editor down first, so a refused Apply lost the typed input.

    Legacy preview (no token exists, Apply is allowed tokenless) with
    ``max_tier=0``: the shorter text needs Tier 1, so the model refuses
    (REJECTED, zero mutation).  The editor, its input, its focus guard and
    the PDF must survive; the reason is shown; there is no success notice;
    the delayed focus path never re-emits the refused request."""
    path = _author(tmp_path / "refused.pdf")
    app = launch(path, preview="legacy", max_tier="0")
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, "Pump Ro")
    app.pump(300)
    generation_before = editor._plan_generation
    payloads_before = len(app.payloads)
    since = time.monotonic()
    app.click_apply()
    app.pump(600)  # let the 40 ms focus-out finalize path run if it would

    # The attempt ended the Controller's preview session: the kept editor
    # must re-request a preview (a newer generation), or in plan mode Apply
    # could never become available again.
    assert editor._plan_generation > generation_before
    assert any(
        p["generation"] > generation_before for p in app.payloads[payloads_before:]
    ), "the kept editor did not re-request a preview"
    assert len(app.requests) == 1, f"{len(app.requests)} edit requests"
    assert app.commits == []
    assert app.page_texts() == _original_texts()
    assert app.model.command_manager._undo_stack == []
    assert app.editor() is editor, "a refused Apply closed the editor"
    assert editor.toPlainText() == "Pump Ro"
    result = app.view._last_text_edit_finalize_result
    assert result.outcome.value == "refused", result
    assert result.edit_result is EditTextResult.REJECTED
    assert app.view._edit_focus_guard_connected is True, "the kept editor lost its focus guard"
    assert app.successes_since(since) == []
    warnings = app.warnings_since(since)
    assert len(warnings) == 1 and "文件未變更" in warnings[0], warnings

    # Esc still cancels the kept editor: discard, nothing sent, one 已捨棄 notice.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    escaped = time.monotonic()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_Escape)
    app.pump(300)
    assert app.editor() is None
    assert app.view._last_text_edit_finalize_result.reason.value == "escape"
    assert len(app.requests) == 1 and app.commits == []
    assert app.page_texts() == _original_texts()
    assert app.successes_since(escaped) == []
    assert app.warnings_since(escaped) == [ESCAPE_DISCARD_NOTICE]
    assert app.modals == []


def test_a_refused_click_away_is_not_resent_for_the_same_input(tmp_path: Path, launch) -> None:
    """Legacy preview (still the shipped default): no token can ever gate a
    click-away, so the Controller refuses it and the editor stays.  Further
    click-aways / focus changes must not re-send the SAME refused input (and
    re-toast) in a loop; a changed input is sent again.  (Before step 9 the
    first refusal closed the editor.)"""
    path = _author(tmp_path / "resend.pdf")
    app = launch(path, preview="legacy", max_tier="0")
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, "Pump Ro")
    blank = fitz.Rect(400, 700, 410, 710)
    since = time.monotonic()
    app.click_scene_at(0, blank)
    app.pump(600)
    assert len(app.requests) == 1 and app.editor() is editor
    app.click_scene_at(0, blank)
    app.pump(600)
    assert len(app.requests) == 1, "the same refused input was sent again"
    assert len(app.warnings_since(since)) == 1, app.toasts
    assert app.editor() is editor and editor.toPlainText() == "Pump Ro"
    app.type_replacing_all(editor, "Pump R")
    app.click_scene_at(0, blank)
    app.pump(600)
    assert len(app.requests) == 2, "a changed input must be tried again"
    assert app.commits == [] and app.page_texts() == _original_texts()
    assert app.modals == []


def test_click_away_without_a_verified_preview_keeps_the_editor(tmp_path: Path, launch) -> None:
    """RED before step 9: the click-away emitted a tokenless request (Tier 0
    committed the unverified text, or it was refused and the editor closed).
    Owner decision 2026-09-30: no verified preview -> keep editor and input,
    ignore the click (no new editor opens under it), send nothing."""
    path = _author(tmp_path / "clickaway.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    # No event processing: the 150 ms preview debounce has not fired yet.
    assert editor.current_plan_token() is None
    app.click_scene_at(0, app.glyph_rect("Buffer Tank"))
    app.pump(700)

    assert app.requests == [], [(r.new_text, r.plan_token) for r in app.requests]
    assert app.commits == []
    assert app.page_texts() == _original_texts()
    assert app.editor() is editor
    assert editor.toPlainText() == _EDIT_B
    assert app.view.editing_original_text == "Pump Room", "the click opened another editor"
    assert app.modals == []


def test_click_away_with_a_verified_preview_commits_that_token(tmp_path: Path, launch) -> None:
    """RED before step 9 on ``requires_preview_token``: only APPLY armed the
    model-side token gate, so a click-away commit was not bound to the token.
    With a current token the click-away commits exactly the verified
    candidate and closes the editor."""
    path = _author(tmp_path / "clickaway_token.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    token = app.wait_token(editor)
    app.click_scene_at(0, fitz.Rect(400, 700, 410, 710))
    app.pump(500)

    assert len(app.requests) == 1
    request = app.requests[0]
    assert request.plan_token == token
    assert request.requires_preview_token is True
    assert len(app.commits) == 1 and app.commits[0][1].token == token
    assert app.commits[0][2].status is CommitStatus.COMMITTED
    assert app.page_texts() == [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]
    assert app.editor() is None
    assert app.view._last_text_edit_finalize_result.reason.value == "click_away"
    assert app.modals == []


def test_mode_switch_without_a_verified_preview_discards_with_a_warning(
    tmp_path: Path, launch
) -> None:
    """RED before step 9: MODE_SWITCH committed the unverified text tokenless.
    A mode switch cannot keep the editor; without a verified preview it
    discards -- visibly (spec section 8 table), never silently."""
    path = _author(tmp_path / "mode_switch.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    since = time.monotonic()
    app.view._action_browse.trigger()
    app.pump(400)

    assert app.commits == []
    assert app.page_texts() == _original_texts()
    assert app.editor() is None
    assert app.view.current_mode == "browse"
    warnings = app.warnings_since(since)
    assert any("未套用" in message for message in warnings), app.toasts
    assert app.successes_since(since) == []
    assert app.modals == []


def test_save_shortcut_without_a_verified_preview_keeps_the_editor(tmp_path: Path, launch) -> None:
    """RED before step 9: SAVE_SHORTCUT committed the unverified text
    tokenless before saving.  Spec section 8: keep the editor and say why."""
    path = _author(tmp_path / "save_shortcut.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    since = time.monotonic()
    app.view._action_save.trigger()
    app.pump(400)

    assert app.commits == []
    assert app.page_texts() == _original_texts()
    assert app.editor() is editor and editor.toPlainText() == _EDIT_B
    assert app.warnings_since(since), "the kept edit gave no reason"


def test_success_teardown_survives_a_synchronous_scene_rebuild(tmp_path: Path, launch) -> None:
    """GUARD for the step-9 reordering (before step 9 the teardown ran BEFORE
    the emit, so only the new ``edit_result`` field failed): the success
    path's ``show_page`` rebuilds the scene synchronously in single-page mode
    (``display_page`` -> ``scene.clear()``) while the editor still exists.
    The first step-9 build failed here -- the clear deleted the proxy and
    ``_refresh_undo_redo_action_state`` raised on it inside the commit
    (``show_error`` "already deleted").  The editor must be torn down once,
    after the result, with no error."""
    path = _author(tmp_path / "rebuild.pdf")
    app = launch(path)
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    token = app.wait_token(editor)
    app.view.continuous_pages = False
    app.click_apply()

    assert len(app.commits) == 1 and app.commits[0][1].token == token
    assert app.view.text_editor is None
    assert app.page_texts() == [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]
    result = app.view._last_text_edit_finalize_result
    assert result.reason.value == "apply" and result.outcome.value == "committed"
    assert result.edit_result is EditTextResult.SUCCESS
    assert app.modals == []


# ------------------------------------------------------ (b) invalidation


def test_toolbar_undo_while_the_editor_is_open_never_applies_the_old_token(
    tmp_path: Path, launch
) -> None:
    """RED before step 9 (VERIFY part 2): the token survived a document
    mutation; Apply then returned PREVIEW_STALE and the editor closed with
    the input lost.  Now the mutation invalidates the token at once (Apply
    disabled, nothing applied, editor and input kept) and a fresh preview
    is requested against the undone document; only that token commits."""
    path = _author(tmp_path / "undo_open.pdf")
    app = launch(path)
    editor = app.open_editor("Buffer Tank")
    app.type_replacing_all(editor, _EDIT_A)
    app.wait_token(editor)
    app.click_apply()
    assert app.editor() is None and len(app.commits) == 1
    assert app.page_texts() == [encode_cids(_EDIT_A), encode_cids("Pump Room")]

    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    stale_token = app.wait_token(editor)
    stale_generation = editor._plan_generation
    depth = len(app.model.command_manager._undo_stack)
    payloads_before = len(app.payloads)
    app.click_toolbar_action(app.view._action_undo)

    assert len(app.model.command_manager._undo_stack) == depth - 1, "the toolbar undo did not run"
    assert app.page_texts() == _original_texts()
    assert app.editor() is editor, "the undo closed the editor"
    assert editor.toPlainText() == _EDIT_B
    assert editor._plan_generation > stale_generation
    assert any(p["generation"] > stale_generation for p in app.payloads[payloads_before:]), (
        "no fresh preview was requested after the document changed"
    )
    requests_before = len(app.requests)
    commits_before = len(app.commits)
    if editor.current_plan_token() is None:
        assert app.view.text_apply_btn.isEnabled() is False
        app.click_apply()
    fresh = app.wait_token(editor)
    fresh_deliveries = [d for d in app.deliveries if d["generation"] > stale_generation]
    assert fresh_deliveries, "the token in use was delivered before the undo"
    app.click_apply()
    new_commits = app.commits[commits_before:]
    assert len(new_commits) == 1, f"{len(new_commits)} commits"
    assert new_commits[0][1].token == fresh
    assert all(r.plan_token != stale_token or r.plan_token == fresh for r in app.requests[requests_before:])
    assert app.page_texts() == [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]
    assert app.modals == []


def test_a_page_switch_that_keeps_the_editor_invalidates_the_token(tmp_path: Path, launch) -> None:
    """RED before step 9 (plan section 3): a wheel scroll to another page and
    back kept the old token and generation, so Apply committed it.  The
    switch must bump the generation, drop the token and re-request."""
    path = _author(tmp_path / "pages.pdf", pages=2)
    app = launch(path)
    editor = app.open_editor("Pump Room", page_index=0)
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    generation = editor._plan_generation
    app.wheel_until_page(1, direction=-1)
    assert app.editor() is editor, "the wheel closed the editor"
    returned_at = app.wheel_until_page(0, direction=1)

    assert editor._plan_generation > generation
    assert editor.current_plan_token() is None or any(
        d["t"] >= returned_at and d["plan_token"] is not None for d in app.deliveries
    )
    fresh = app.wait_token(editor)
    assert any(d["t"] >= returned_at and d["plan_token"] == fresh for d in app.deliveries)
    app.click_apply()
    assert len(app.commits) == 1 and app.commits[0][1].token == fresh
    assert app.modals == []


# ------------------------------------------------------ (c) session binding


def test_opening_a_byte_identical_copy_never_commits_into_the_copy(
    tmp_path: Path, launch
) -> None:
    """RED before step 9 -- the headline VERIFY defect.  ``open_pdf`` switched
    the active session BEFORE the scene rebuild finalized the editor, so a
    verified token (content-derived: same xref, fingerprint, offsets)
    committed the edit into the byte-identical copy.  The recent-files menu
    emits ``sig_open_pdf`` directly, which is the path driven here.

    Now the editor is finalized against the ORIGINAL session first (its
    verified token commits there) and the copy is untouched."""
    original = _author(tmp_path / "doc.pdf")
    copy = tmp_path / "doc (1).pdf"
    shutil.copyfile(original, copy)
    copy_sha = _sha(copy)
    app = launch(original)
    original_sid = app.model.get_active_session_id()
    original_doc = app.model.doc
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    token = app.wait_token(editor)
    app.view.sig_open_pdf.emit(str(copy))
    app.pump(1500)

    copy_sid = app.model.get_active_session_id()
    assert copy_sid != original_sid
    copy_doc = app.model.doc
    assert copy_doc is not original_doc
    assert app.page_texts(copy_doc) == _original_texts(), "the edit landed in the copy"
    assert app.model.command_manager._undo_stack == [], "the copy got an undo entry"
    assert _sha(copy) == copy_sha
    assert [entry[0] for entry in app.commits] == [original_doc]
    assert app.commits[0][1].token == token
    assert app.page_texts(original_doc) == [encode_cids("Buffer Tank"), encode_cids(_EDIT_B)]
    assert app.editor() is None
    assert app.modals == []


def test_opening_another_document_with_a_pending_preview_discards_visibly(
    tmp_path: Path, launch
) -> None:
    """RED before step 9: with no verified preview the tokenless request was
    applied to the NEW document (same layout).  Now nothing is committed
    anywhere and the discard is announced."""
    original = _author(tmp_path / "pending.pdf")
    other = _author(tmp_path / "other.pdf")
    other_sha = _sha(other)
    app = launch(original)
    original_doc = app.model.doc
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    assert editor.current_plan_token() is None
    since = time.monotonic()
    app.view.sig_open_pdf.emit(str(other))
    app.pump(1500)

    assert app.commits == []
    assert app.page_texts(original_doc) == _original_texts()
    assert app.page_texts(app.model.doc) == _original_texts()
    assert _sha(other) == other_sha
    assert app.editor() is None
    assert any("未套用" in message for message in app.warnings_since(since)), app.toasts
    assert app.modals == []


def test_a_request_bound_to_another_session_is_refused(tmp_path: Path, launch) -> None:
    """RED before step 9 (no ``session_id`` on the request): a request made
    in document A can never commit into document B, whatever path delivers
    it -- zero mutation on both, a notice, never a modal."""
    first = _author(tmp_path / "first.pdf")
    second = tmp_path / "second.pdf"
    shutil.copyfile(first, second)
    app = launch(first)
    first_sid = app.model.get_active_session_id()
    first_doc = app.model.doc
    app.view.sig_open_pdf.emit(str(second))
    app.pump(1200)
    assert app.model.get_active_session_id() != first_sid
    rect = app.glyph_rect("Pump Room")
    since = time.monotonic()
    app.controller.edit_text(
        EditTextRequest(
            page=1,
            rect=rect,
            new_text=_EDIT_B,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text="Pump Room",
            session_id=first_sid,
        )
    )
    assert app.controller.consume_last_edit_result() is EditTextResult.REJECTED
    assert app.commits == []
    assert app.page_texts(app.model.doc) == _original_texts()
    assert app.page_texts(first_doc) == _original_texts()
    assert app.model.command_manager._undo_stack == []
    assert app.warnings_since(since), "the refusal was silent"
    assert app.modals == []


def test_the_editor_stamps_its_document_session_on_request_and_preview(
    tmp_path: Path, launch
) -> None:
    """RED before step 9: requests and preview payloads carried no document
    identity, so nothing downstream could tell which document they meant."""
    path = _author(tmp_path / "stamp.pdf")
    app = launch(path)
    sid = app.model.get_active_session_id()
    editor = app.open_editor("Pump Room")
    app.type_replacing_all(editor, _EDIT_B)
    token = app.wait_token(editor)
    assert app.payloads and all(p.get("document_session_id") == sid for p in app.payloads)
    app.click_apply()
    assert len(app.requests) == 1 and app.requests[0].session_id == sid
    assert app.commits[0][1].token == token
