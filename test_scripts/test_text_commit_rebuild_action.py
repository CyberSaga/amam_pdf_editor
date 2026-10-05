"""The rejection reason and the explicit "改用重建文字…" action.

UI critique step 10 of plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md
(ui_spec sections 3 and 6; owner decision 2026-09-30 "Explicit action"):

- A refusal -- the current generation's plan preview came back rejected, or
  the Controller refused the commit -- is shown in plain Traditional Chinese
  (``type0_unicode_unmapped`` / ``type0_glyph_missing`` -> 原字型沒有這個字;
  an unmapped code gets a generic message plus the code), set through the
  editor's ``set_plan_preview_state``.
- Apply stays disabled without a current-generation token (a drag, a
  restyle or an emptied text has no token: their only way forward is the
  rebuild action).
- "改用重建文字…" is shown only while a rebuildable refusal is current.  It
  sends the SAME target and text with ``allow_rebuild=True`` through the
  Controller's existing consent dialog (default No).  Consent is per
  request; any input change hides the button.
- Decline: the PDF, the undo stack and the editor (with its input) are
  unchanged, and there is no notice.  Accept: exactly one rebuild commit and
  one (degrade) notice; undo/redo are exact and never ask again.

Every app test launches the real app through ``main.run`` on a SYNTHETIC
subset Identity-H document (plan section 10 data policy) and drives it with
real QTest input; modal dialogs only record and return a default.
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
from model.text_commit.dto import CommitStatus, RejectReason  # noqa: E402

from test_scripts import test_text_commit_finalize_by_result as fbr  # noqa: E402
from test_scripts.type0_fixture_builder import build_identity_h_fixture  # noqa: E402

TARGET = "Buffer Tank"
MISSING = "Buffer 路"  # '路' is not in the embedded subset
MISSING_TEXT = "原字型沒有這個字"
PREVIEW_TIMEOUT_S = 30.0


# ------------------------------------------------------------------ helpers


def _subset_pdf(tmp_path: Path, name: str = "subset.pdf") -> Path:
    fixture = build_identity_h_fixture(TARGET, subset=True)
    path = tmp_path / name
    fixture.doc.save(str(path))
    fixture.doc.close()
    return path


def _streams(model, page_index: int = 0) -> list[bytes]:
    page = model.doc[page_index]
    return [model.doc.xref_stream(x) for x in page.get_contents()]


def _launch(monkeypatch, path: Path, **kwargs):
    app = fbr._App(monkeypatch, path, **kwargs)
    app.rejections = []
    delivered = app.view.apply_text_edit_plan_preview

    def _record(**kw):
        app.rejections.append((kw.get("generation"), kw.get("reject_reason")))
        return delivered(**kw)

    app.view.apply_text_edit_plan_preview = _record
    return app


@pytest.fixture
def launch(qapp, monkeypatch):
    apps: list = []

    def _go(path: Path, **kwargs):
        app = _launch(monkeypatch, path, **kwargs)
        apps.append(app)
        return app

    yield _go
    for app in apps:
        app.close()


def _type(editor, text: str) -> None:
    """Ctrl+A, then ASCII as key clicks and CJK as IME commit strings
    (``QTest.keyClicks`` with a CJK character kills the offscreen process)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
    for char in text:
        if char.isascii():
            QTest.keyClicks(editor, char)
        else:
            event = QInputMethodEvent("", [])
            event.setCommitString(char)
            QApplication.sendEvent(editor, event)
    if not text:
        QTest.keyClick(editor, Qt.Key_Delete)


def _wait_rejection(app, editor) -> str:
    """The reject reason delivered for the editor's CURRENT generation."""
    found: dict = {}

    def _arrived() -> bool:
        generation = editor._plan_generation
        for delivered_generation, reason in reversed(app.rejections):
            if delivered_generation == generation and reason is not None:
                found["reason"] = reason
                return True
        return False

    assert app.wait(_arrived, PREVIEW_TIMEOUT_S), "no rejection for the current generation"
    app.pump(60)
    return found["reason"]


def _rebuild_button(app):
    return app.view.text_rebuild_btn


def _status_label(app):
    return app.view.text_plan_status_label


def _click(widget) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, widget.rect().center())


def _accept_consent(monkeypatch, app) -> list:
    """Replace the recorded-No consent with a recorded Yes."""
    import controller.pdf_controller as controller_module

    asked: list = []

    def _yes(_parent, message):
        asked.append(message)
        return True

    monkeypatch.setattr(controller_module, "confirm_degraded_fallback", _yes)
    return asked


def _consents(app) -> list:
    return [m for m in app.modals if m[0] == "confirm_degraded_fallback"]


# ------------------------------------------------------------- reason text


def test_reason_codes_map_to_plain_traditional_chinese() -> None:
    from view.text_edit_reasons import (
        rebuild_offered_for,
        rejection_reason_text,
    )

    assert rejection_reason_text("type0_unicode_unmapped") == MISSING_TEXT
    assert rejection_reason_text("type0_glyph_missing") == MISSING_TEXT
    assert rejection_reason_text("encoding_failed") == MISSING_TEXT
    for code in (
        "growth_region_not_blank",
        "advance_mismatch",
        "style_override_present",
        "geometry_override_present",
        "empty_replacement",
        "multi_span_target",
        "cross_page_move_requires_rebuild",
        "target_unresolved",
        "document_session_mismatch",
    ):
        text = rejection_reason_text(code)
        assert text and code not in text, (code, text)
    # Every engine reason code has its OWN plain sentence (the generic one
    # carries the code, so a missing mapping fails here); an unknown code
    # gets the generic message plus the code (never an empty refusal).
    for name, code in vars(RejectReason).items():
        if name.isupper() and isinstance(code, str):
            text = rejection_reason_text(code)
            assert text and code not in text, (code, text)
    generic = rejection_reason_text("some_future_code")
    assert "some_future_code" in generic
    assert rejection_reason_text(None) == ""

    assert rebuild_offered_for("type0_unicode_unmapped") is True
    assert rebuild_offered_for("geometry_override_present") is True
    for code in (
        None,
        "no_change",
        "document_session_mismatch",
        "preview_stale",
        "stale_plan",
        "signed_or_widget_target",
    ):
        assert rebuild_offered_for(code) is False, code


def test_rejected_toast_uses_the_plain_reason_text() -> None:
    """The Controller's REJECTED notice says the same plain text as the
    editor (one mapping), keeps "文件未變更", and gives the session-mismatch
    refusal friendly text instead of a bare code."""
    from controller.pdf_controller import PDFController
    from view.text_edit_reasons import rejection_reason_text

    message = PDFController._edit_result_to_message(
        None, EditTextResult.REJECTED, "type0_unicode_unmapped"
    )
    assert MISSING_TEXT in message and "文件未變更" in message
    assert "type0_unicode_unmapped" not in message
    mismatch = PDFController._edit_result_to_message(
        None, EditTextResult.REJECTED, "document_session_mismatch"
    )
    assert rejection_reason_text("document_session_mismatch") in mismatch
    assert "document_session_mismatch" not in mismatch


# ------------------------------------------------------------- app: refusal


def test_missing_glyph_shows_the_reason_and_the_rebuild_button(tmp_path, launch) -> None:
    app = launch(_subset_pdf(tmp_path))
    editor = app.open_editor(TARGET)
    assert _rebuild_button(app).isHidden(), "the button must start hidden"
    _type(editor, MISSING)
    assert _wait_rejection(app, editor) == "type0_glyph_missing"

    assert editor.current_plan_token() is None
    assert app.view.text_apply_btn.isEnabled() is False
    label = _status_label(app)
    assert not label.isHidden() and label.text() == MISSING_TEXT
    button = _rebuild_button(app)
    assert not button.isHidden() and button.isEnabled()
    assert button.text() == "改用重建文字…"
    assert MISSING_TEXT in editor.toolTip()
    assert app.requests == [] and app.modals == []


def test_declined_rebuild_changes_nothing_and_keeps_the_editor(tmp_path, launch) -> None:
    app = launch(_subset_pdf(tmp_path))
    editor = app.open_editor(TARGET)
    hit_ref = app.view.editing_source_ref
    _type(editor, MISSING)
    _wait_rejection(app, editor)
    before = _streams(app.model)
    since = time.monotonic()

    _click(_rebuild_button(app))  # the recorded consent answers No (its default)
    app.pump(400)

    assert len(_consents(app)) == 1, app.modals
    assert len(app.requests) == 1
    request = app.requests[0]
    assert request.allow_rebuild is True
    assert request.plan_token is None and request.requires_preview_token is False
    assert request.new_text == MISSING and request.original_text == TARGET
    assert request.source_ref == hit_ref and request.session_id is not None
    assert app.view._last_text_edit_finalize_result.edit_result is EditTextResult.FALLBACK_DECLINED
    assert app.commits == []
    assert _streams(app.model) == before
    assert app.model.command_manager._undo_stack == []
    assert app.editor() is editor and editor.toPlainText() == MISSING
    assert app.successes_since(since) == [] and app.warnings_since(since) == []
    # The kept editor re-requests its preview and offers the action again.
    assert app.wait(lambda: not _rebuild_button(app).isHidden(), PREVIEW_TIMEOUT_S)
    assert _status_label(app).text() == MISSING_TEXT


def test_accepted_rebuild_commits_once_with_one_notice_and_exact_undo_redo(
    tmp_path, launch, monkeypatch
) -> None:
    app = launch(_subset_pdf(tmp_path))
    asked = _accept_consent(monkeypatch, app)
    editor = app.open_editor(TARGET)
    _type(editor, MISSING)
    _wait_rejection(app, editor)
    before = _streams(app.model)
    since = time.monotonic()

    _click(_rebuild_button(app))
    app.pump(500)

    assert len(asked) == 1
    assert len(app.requests) == 1 and app.requests[0].allow_rebuild is True
    assert app.view._last_text_edit_finalize_result.edit_result is EditTextResult.SUCCESS
    assert app.editor() is None
    stack = app.model.command_manager._undo_stack
    assert len(stack) == 1
    outcome = stack[0].outcome
    assert outcome.status is CommitStatus.DEGRADED_COMMITTED
    assert outcome.fallback_chain[-1] == "legacy"
    assert app.successes_since(since) == []
    assert len(app.warnings_since(since)) == 1, app.toasts
    after = _streams(app.model)
    assert after != before
    assert "路" in app.model.doc[0].get_text()

    app.controller.undo()
    app.pump(200)
    assert _streams(app.model) == before
    app.controller.redo()
    app.pump(200)
    assert _streams(app.model) == after
    assert len(asked) == 1, "undo/redo must never ask again"
    assert len(app.warnings_since(since)) == 1, "redo must not repeat the notice"
    assert [m for m in app.modals if m[0] != "confirm_degraded_fallback"] == []


def test_any_input_change_hides_the_button_and_a_stale_click_sends_nothing(
    tmp_path, launch
) -> None:
    app = launch(_subset_pdf(tmp_path))
    editor = app.open_editor(TARGET)
    _type(editor, MISSING)
    _wait_rejection(app, editor)
    assert not _rebuild_button(app).isHidden()

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClicks(editor, "x")
    # Synchronously, before any new preview result: the refusal is stale.
    assert _rebuild_button(app).isHidden()
    assert _status_label(app).isHidden()
    app.view._on_text_rebuild_clicked()  # a stale click (e.g. queued) is ignored
    app.pump(100)
    assert app.requests == [] and app.modals == []

    # A font change is an input change too.
    _wait_rejection(app, editor)
    assert not _rebuild_button(app).isHidden()
    combo = app.view.text_font
    combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
    assert _rebuild_button(app).isHidden()


def test_consent_is_per_request_not_sticky(tmp_path, launch) -> None:
    """After a declined rebuild, a normal edit of the same editor carries no
    consent and commits true-text through its verified token."""
    app = launch(_subset_pdf(tmp_path))
    editor = app.open_editor(TARGET)
    _type(editor, MISSING)
    _wait_rejection(app, editor)
    _click(_rebuild_button(app))
    app.pump(300)
    assert app.editor() is editor

    _type(editor, "Buffer Tnak")
    token = app.wait_token(editor)
    assert _rebuild_button(app).isHidden()
    app.click_apply()
    assert len(app.requests) == 2
    assert app.requests[1].allow_rebuild is False
    assert app.requests[1].plan_token == token
    assert app.commits and app.commits[-1][2].status is CommitStatus.COMMITTED
    assert app.editor() is None
    assert len(_consents(app)) == 1


def test_restyle_has_no_token_and_offers_the_rebuild(tmp_path, launch) -> None:
    """A font change with the text unchanged: the preview reports
    ``no_change`` (gate order), the editor shows the real reason, Apply stays
    disabled and the rebuild action is the way forward."""
    app = launch(_subset_pdf(tmp_path))
    editor = app.open_editor(TARGET)
    combo = app.view.text_font
    combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
    _wait_rejection(app, editor)
    assert app.view.text_apply_btn.isEnabled() is False
    from view.text_edit_reasons import rejection_reason_text

    assert _status_label(app).text() == rejection_reason_text("style_override_present")
    assert not _rebuild_button(app).isHidden()


def test_drag_has_no_token_and_offers_the_rebuild(tmp_path, launch, monkeypatch) -> None:
    """RED before step 10: a dragged editor was exempt from the token gate
    (its tokenless Apply then failed REJECTED).  Apply now stays disabled;
    the reason is shown; the rebuild action moves the text with consent."""
    app = launch(_subset_pdf(tmp_path))
    asked = _accept_consent(monkeypatch, app)
    editor = app.open_editor(TARGET)
    # The drag's end state (what ``_mouse_release`` records), then the same
    # invalidation the release performs.
    rect = fitz.Rect(app.view.editing_rect)
    app.view.editing_rect = fitz.Rect(rect.x0 + 40, rect.y0 + 60, rect.x1 + 40, rect.y1 + 60)
    app.view._invalidate_editor_plan_preview(regenerate=True)
    app.view._sync_text_apply_enabled()
    _wait_rejection(app, editor)
    assert app.view.text_apply_btn.isEnabled() is False

    from view.text_edit_reasons import rejection_reason_text

    assert _status_label(app).text() == rejection_reason_text("geometry_override_present")
    _click(_rebuild_button(app))
    app.pump(400)
    assert len(asked) == 1
    assert len(app.requests) == 1
    request = app.requests[0]
    assert request.allow_rebuild is True and request.new_rect is not None
    assert app.view._last_text_edit_finalize_result.edit_result is EditTextResult.SUCCESS
    assert len(app.model.command_manager._undo_stack) == 1


def test_a_non_rebuildable_refusal_shows_text_but_no_button(tmp_path, launch) -> None:
    app = launch(_subset_pdf(tmp_path))
    editor = app.open_editor(TARGET)
    _type(editor, "Buffer Tnak")
    app.pump(40)
    app.view.apply_text_edit_plan_preview(
        session_key=editor.plan_preview_session_key,
        generation=editor._plan_generation,
        image=None,
        plan_token=None,
        reject_reason="document_session_mismatch",
    )
    from view.text_edit_reasons import rejection_reason_text

    assert _status_label(app).text() == rejection_reason_text("document_session_mismatch")
    assert _rebuild_button(app).isHidden()
    app.view._on_text_rebuild_clicked()
    app.pump(100)
    assert app.requests == [] and app.modals == []


def test_legacy_preview_commit_refusal_offers_the_rebuild(tmp_path, launch) -> None:
    """Legacy preview (still the shipped default): no preview can refuse, so
    the Controller's commit refusal is the reason source.  It must survive
    the kept editor's preview re-arm and offer the action."""
    path = fbr._author(tmp_path / "legacy.pdf")
    app = launch(path, preview="legacy", max_tier="0")
    editor = app.open_editor("Pump Room")
    fbr._App.type_replacing_all(app, editor, "Pump Ro")
    app.pump(300)
    assert _rebuild_button(app).isHidden()
    app.click_apply()
    app.pump(300)
    assert app.view._last_text_edit_finalize_result.edit_result is EditTextResult.REJECTED
    reason = app.model.last_commit_outcome.degraded_reason
    from view.text_edit_reasons import rejection_reason_text

    assert app.editor() is editor
    assert _status_label(app).text() == rejection_reason_text(reason)
    assert not _rebuild_button(app).isHidden()


def _two_line_paragraph_pdf(path: Path) -> Path:
    """Synthetic Identity-H page with one two-line paragraph (one hex ``Tj``
    per line, close enough for MuPDF to join them into one block)."""
    from test_scripts.type0_fixture_builder import encode_cids

    font = fitz.Font("cjk")
    doc = fitz.open()
    height = 842.0
    lines = ((72.0, 150.0, "Buffer Tank"), (72.0, 164.5, "Pump Room"))
    page = doc.new_page(width=595.0, height=height)
    writer = fitz.TextWriter(page.rect)
    for x, y, text in lines:
        writer.append((x, y), text, font=font, fontsize=12)
    writer.write_text(page)
    name = page.get_fonts(full=True)[0][4]
    body = " ".join(
        f"BT /{name} 12 Tf 1 0 0 1 {x:g} {height - y:g} Tm "
        f"<{encode_cids(text).hex().upper()}> Tj ET"
        for x, y, text in lines
    )
    doc.update_stream(page.get_contents()[0], body.encode("ascii"))
    doc.save(str(path))
    doc.close()
    return path


def test_paragraph_mode_names_the_paragraph_and_offers_the_rebuild(
    tmp_path, launch, monkeypatch
) -> None:
    """Paragraph mode (the shipped default target): the preview cannot
    resolve a multi-line target and says ``target_unresolved``; the editor
    must name the real cause (a paragraph edit needs a rebuild), not claim
    the text is missing from the PDF.  Accepting rebuilds it once."""
    from view.text_edit_reasons import rejection_reason_text

    app = launch(_two_line_paragraph_pdf(tmp_path / "paragraph.pdf"))
    asked = _accept_consent(monkeypatch, app)
    app.view._action_edit_text.trigger()
    app.pump(100)
    combo = app.view.text_target_mode_combo
    combo.setCurrentIndex(combo.findData("paragraph"))
    app.pump(80)
    rect = app.glyph_rect("Buffer Tank")
    app.view.graphics_view.centerOn(app.view._doc_rect_to_scene_rect(0, rect).center())
    app.pump(150)
    app.click_scene_at(0, rect)
    assert app.wait(lambda: app.editor() is not None, 20)
    editor = app.editor()
    assert app.view.editing_target_mode == "paragraph"
    assert editor.toPlainText() == "Buffer Tank Pump Room"
    _type(editor, "Buffer Tnak Pump Room")
    _wait_rejection(app, editor)

    assert app.view.text_apply_btn.isEnabled() is False
    assert _status_label(app).text() == rejection_reason_text("multi_span_target")
    _click(_rebuild_button(app))
    app.pump(500)
    assert len(asked) == 1
    assert app.requests[-1].allow_rebuild is True
    assert app.requests[-1].target_mode == "paragraph"
    assert app.view._last_text_edit_finalize_result.edit_result is EditTextResult.SUCCESS
    assert len(app.model.command_manager._undo_stack) == 1


def test_cross_page_drag_offers_the_rebuild_and_moves_with_one_consent(
    tmp_path, launch, monkeypatch
) -> None:
    """A cross-page drag has no token (Apply disabled); the editor names the
    cross-page rebuild and the action sends a ``MoveTextRequest`` with the
    consent, asked once, recorded as one undo entry."""
    from view.text_edit_reasons import rejection_reason_text

    app = launch(fbr._author(tmp_path / "two_pages.pdf", pages=2))
    moves: list = []
    app.view.sig_move_text_across_pages.connect(moves.append)
    asked = _accept_consent(monkeypatch, app)
    editor = app.open_editor("Pump Room")
    # The drag's end state on page 2 (what ``_mouse_move``/``_mouse_release``
    # record), then the release's invalidation.
    rect = fitz.Rect(app.view.editing_rect)
    app.view._editing_page_idx = 1
    app.view.editing_rect = fitz.Rect(rect.x0, rect.y0 + 50, rect.x1, rect.y1 + 50)
    app.view._invalidate_editor_plan_preview(regenerate=True)
    app.view._sync_text_apply_enabled()
    _wait_rejection(app, editor)

    assert app.view.text_apply_btn.isEnabled() is False
    assert _status_label(app).text() == rejection_reason_text("cross_page_move_requires_rebuild")
    _click(_rebuild_button(app))
    app.pump(800)
    assert len(asked) == 1
    assert len(moves) == 1 and moves[0].allow_rebuild is True
    assert app.requests == []
    assert app.editor() is None
    assert len(app.model.command_manager._undo_stack) == 1
    assert "Pump Room" not in app.model.doc[0].get_text()
    # Page 2 had its own "Pump Room"; the moved one is the second.
    assert app.model.doc[1].get_text().count("Pump Room") == 2
