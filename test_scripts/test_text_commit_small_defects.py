"""Part-5 Stage D: the small part-3 VERIFY defects 5, 6 and 7.

Plan: plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md
(section 6, "Part 5 Stage D") and plans/true-text-ui-part5.md section 5.

* Defect 7: ``PDFView.sig_add_textbox`` was declared ``Signal(int, ..., int,
  ...)``; the size slot is a point size, so a 10.5 pt add box arrived as 10.
* Defect 5: every Ctrl+wheel notch refused by an un-applied editor re-showed
  the identical "縮放 ..." toast; a flick of the wheel stacked a dozen of them.
  The same reason with the same text shows once while the editor is kept.
* Defect 6: the rebuild-consent dialog and the degrade toast printed the raw
  chain (``tier0:advance_mismatch → legacy``).  The codes now go through
  ``view/text_edit_reasons.py`` like every other refusal text.

Real-app tests reuse the harness of ``test_text_commit_finalize_by_result.py``
(synthetic Identity-H documents, real QTest input, recorders only).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from test_scripts.test_text_commit_add_text_intent import (  # noqa: E402
    _BLANK_POINT,
    _TYPED,
    _click_doc_point,
    _enter_add_text_mode,
    _type,
)
from test_scripts.test_text_commit_finalize_by_result import _App, _author  # noqa: E402
from test_scripts.test_text_commit_finalize_policy import (  # noqa: E402
    _ctrl_wheel,
    _refuse_by_apply,
)
from view.pdf_view import PDFView  # noqa: E402
from view.text_edit_reasons import rejection_reason_text  # noqa: E402


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


# ------------------------------------------------ defect 7: fractional add size


def test_sig_add_textbox_carries_a_fractional_size_unchanged(qapp) -> None:
    """RED before: ``Signal(int, ..., int, ...)`` truncated 10.5 to 10."""
    view = PDFView(defer_heavy_panels=True)
    received: list[tuple] = []
    view.sig_add_textbox.connect(lambda *args: received.append(args))
    try:
        view.sig_add_textbox.emit(
            1, fitz.Rect(10, 10, 100, 40), "x", "helv", 10.5, (0.0, 0.0, 0.0), None
        )
        qapp.processEvents()
    finally:
        view.close()
    assert len(received) == 1
    size = received[0][4]
    assert isinstance(size, float) and size == pytest.approx(10.5), size


def test_add_box_with_a_fractional_size_reaches_the_model_as_10_5(
    tmp_path: Path, launch, monkeypatch
) -> None:
    """RED before: the whole path View -> signal -> Controller -> command ->
    ``PDFModel.add_textbox`` carried ``int(10.5) == 10``."""
    sizes: list[object] = []
    original = PDFModel.add_textbox

    def _spy(model, page_num, visual_rect, text, *args, **kwargs):
        sizes.append(kwargs.get("size"))
        return original(model, page_num, visual_rect, text, *args, **kwargs)

    monkeypatch.setattr(PDFModel, "add_textbox", _spy)
    app = launch(_author(tmp_path / "frac.pdf"))
    _enter_add_text_mode(app)  # the first entry applies the default size 12
    app.view.text_size.setCurrentText("10.5")
    _click_doc_point(app, 0, *_BLANK_POINT)
    assert app.wait(lambda: app.editor() is not None, 20), "the click opened no add box"
    editor = app.editor()
    assert app.view.editing_intent == "add_new"
    assert app.view._editing_current_pdf_size == pytest.approx(10.5)
    _type(app, editor, _TYPED)
    app.pump(300)
    app.click_apply()
    app.pump(300)

    assert app.editor() is None, "the add box was not committed"
    assert len(sizes) == 1, sizes
    assert sizes[0] == pytest.approx(10.5), sizes


# ------------------------------------------------- defect 5: one toast per hold


def _rescale_toasts(app: _App, since: float) -> list[str]:
    return [m for m in app.warnings_since(since) if "縮放" in m]


def test_ctrl_wheel_with_a_kept_editor_shows_the_same_notice_once(
    tmp_path: Path, launch
) -> None:
    """RED before: every refused notch re-showed the identical toast (three
    notches, three toasts).  Same reason + same text, editor kept and input
    unchanged: once.  Changed input is news again: a new notice."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app = launch(_author(tmp_path / "wheel_dup.pdf"), preview="legacy", max_tier="0")
    editor = _refuse_by_apply(app)
    since = time.monotonic()
    _ctrl_wheel(app, notches=3)
    app.pump(500)

    assert app.editor() is editor, "the zoom closed the editor"
    assert len(_rescale_toasts(app, since)) == 1, app.toasts

    # The input changed: the editor is still kept, the notice may speak again.
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End)
    QTest.keyClicks(editor, "x")
    app.pump(300)
    _ctrl_wheel(app, notches=2)
    app.pump(500)

    assert app.editor() is editor
    assert len(_rescale_toasts(app, since)) == 2, app.toasts


# --------------------------------------- defect 6: no raw tier codes for users

_CHAIN_LEGACY = ("tier0:advance_mismatch", "legacy")
_CHAIN_TIER1 = ("tier0:rejected:advance_mismatch", "tier1:committed")
_CHAIN_UNMAPPED = ("tier0:some_future_code", "legacy")
# Every Tier 1 chain starts with the tier 0 refusal; the user is told the LAST
# refusal before the rebuild (the one that actually forced it), as the preview
# panel does.
_CHAIN_TIER1_FAILED = ("tier0:advance_mismatch", "tier1:verification_failed", "legacy")
# ``PDFController.move_text_across_pages`` asks for consent with this chain.
_CHAIN_MOVE = ("cross_page_move_requires_rebuild", "legacy")


def _bare_controller() -> PDFController:
    """The two message builders read nothing from ``self``."""
    return object.__new__(PDFController)


def test_fallback_chain_reason_text_names_the_last_refusal_before_legacy() -> None:
    """RED before (part 5 final review): the FIRST refusal step was named, and
    every Tier 1 chain starts with tier0:advance_mismatch, so the consent dialog
    and the degrade toast disagreed with the preview panel."""
    from view.text_edit_reasons import fallback_chain_reason_text

    plain = rejection_reason_text("advance_mismatch")
    assert plain
    assert fallback_chain_reason_text(_CHAIN_LEGACY) == plain
    assert fallback_chain_reason_text(_CHAIN_TIER1) == plain
    verification = rejection_reason_text("verification_failed")
    assert verification and verification != plain
    assert fallback_chain_reason_text(_CHAIN_TIER1_FAILED) == verification
    # The cross-page move asks for consent with a BARE code (no tier prefix).
    assert fallback_chain_reason_text(_CHAIN_MOVE) == rejection_reason_text(
        "cross_page_move_requires_rebuild"
    )
    # Nothing to explain: no refusal step in the chain.
    assert fallback_chain_reason_text(("legacy",)) == ""
    assert fallback_chain_reason_text(("tier0:committed",)) == ""
    assert fallback_chain_reason_text(()) == ""
    # An unmapped code is never silent and never a raw ``tierN:`` string.
    unmapped = fallback_chain_reason_text(_CHAIN_UNMAPPED)
    assert "some_future_code" in unmapped and "tier0" not in unmapped


@pytest.mark.parametrize(
    "chain", [_CHAIN_LEGACY, _CHAIN_UNMAPPED, _CHAIN_MOVE, _CHAIN_TIER1_FAILED]
)
def test_consent_dialog_message_uses_plain_reasons_not_tier_codes(chain) -> None:
    """RED before: the dialog said ``原因：tier0:advance_mismatch → legacy``."""
    message = _bare_controller()._fallback_confirmation_message(chain)

    assert "tier0" not in message and "→" not in message, message
    assert "advance_mismatch" not in message, message
    if chain is _CHAIN_LEGACY:
        assert rejection_reason_text("advance_mismatch") in message, message
    if chain is _CHAIN_MOVE:
        assert "cross_page_move_requires_rebuild" not in message, message
        assert rejection_reason_text("cross_page_move_requires_rebuild") in message, message
    if chain is _CHAIN_TIER1_FAILED:
        assert "verification_failed" not in message, message
        assert rejection_reason_text("verification_failed") in message, message
        assert rejection_reason_text("advance_mismatch") not in message, message
    assert "是否繼續" in message and "保留編輯框與輸入" in message


def test_consent_dialog_message_without_a_refusal_code_still_gives_a_reason() -> None:
    """RED before: the raw word "legacy" was printed as the reason.  A chain
    with no refusal step keeps the 原因 line, with a fixed sentence."""
    message = _bare_controller()._fallback_confirmation_message(("legacy",))
    assert "原因：" in message and "legacy" not in message.split("原因：", 1)[1].split("\n", 1)[0]


@pytest.mark.parametrize("chain", [_CHAIN_LEGACY, _CHAIN_UNMAPPED, _CHAIN_TIER1_FAILED])
def test_degrade_toast_uses_plain_reasons_not_tier_codes(chain) -> None:
    """RED before: the toast ended in ``：tier0:advance_mismatch → legacy``.
    The word legacy stays: the degrade counters of the visibility suite look
    for it, and it tells the user the edit fell back to a rebuild."""
    outcome = SimpleNamespace(fallback_chain=chain)
    message = _bare_controller()._degraded_commit_message(outcome)

    assert "tier0" not in message and "→" not in message, message
    assert "advance_mismatch" not in message, message
    assert "已以降級模式完成編輯" in message and "legacy" in message
    if chain is _CHAIN_TIER1_FAILED:
        assert rejection_reason_text("verification_failed") in message, message
        assert rejection_reason_text("advance_mismatch") not in message, message
    if chain is _CHAIN_LEGACY:
        assert rejection_reason_text("advance_mismatch") in message, message


# ------------- part 5 final review: a failed save still invalidates the preview


class _SaveFailure(RuntimeError):
    """Stand-in for ProtectedPageViolation / an OS write error."""


def _controller_with_an_open_editor(monkeypatch, *, fail_save: bool):
    """A bare controller whose model.save_as raises (or not) and whose view has
    an open inline editor with a live plan-preview session."""
    import controller.pdf_controller as pdf_controller_module
    from model.tools.manager import ProtectedPageViolation

    notified: list[int] = []
    shown: list[str] = []
    monkeypatch.setattr(pdf_controller_module, "show_error", lambda _v, m: shown.append(m))
    monkeypatch.setattr(
        pdf_controller_module.QMessageBox, "information", staticmethod(lambda *a, **k: None)
    )

    save_calls: list[str] = []

    def _save_as(path):
        save_calls.append(path)
        if fail_save:
            # ``apply_pending_redactions`` already rewrote unprotected pages by
            # the time a later step (a save hook, the write) raises.
            raise ProtectedPageViolation("simulated refusal after the clean pass")

    controller = object.__new__(PDFController)
    controller.model = SimpleNamespace(
        save_as=_save_as,
        save_calls=save_calls,
        saved_path="doc.pdf",
        original_path="doc.pdf",
    )
    controller.view = SimpleNamespace(
        text_editor=object(),
        _finalizing_text_edit=False,
        invalidate_text_edit_plan_preview=lambda: notified.append(1),
    )
    # ``save``/``save_as`` join the thumbnail worker first
    # (``_background_file_readers_released``); a controller built without
    # ``__init__`` must therefore carry the coordinator and generation map that
    # only ``__init__`` sets (GATE7-1).  An idle coordinator: nothing to resume.
    controller._thumbnail_coordinator = SimpleNamespace(
        has_active_job=False,
        cancel=lambda *a, **k: None,
        wait_for_done=lambda _ms: True,
    )
    controller._thumb_gen_by_session = {}
    controller._plan_preview_session_key = "session-key"
    controller._plan_preview_target = object()
    controller._refresh_document_tabs = lambda: None
    controller._update_undo_redo_tooltips = lambda: None
    return controller, notified, shown


@pytest.mark.parametrize("entry", ["save_as", "save"])
@pytest.mark.parametrize("fail_save", [True, False], ids=["failed_save", "ok_save"])
def test_a_save_always_invalidates_the_open_editors_preview_session(
    monkeypatch, entry, fail_save
) -> None:
    """RED before (failed_save): the invalidation ran only after a SUCCESSFUL
    save, but ``apply_pending_redactions`` may already have rewritten pages, so
    the kept editor kept a preview session snapshotted from the old bytes.
    GUARD (ok_save): the successful path still invalidates exactly once."""
    controller, notified, shown = _controller_with_an_open_editor(
        monkeypatch, fail_save=fail_save
    )
    if entry == "save_as":
        controller.save_as("out.pdf")
    else:
        controller.save()

    # The model write really ran (GATE7-1: the params used to "pass" on an
    # AttributeError raised before the write, ``bool(shown) == fail_save``).
    assert controller.model.save_calls == ["out.pdf" if entry == "save_as" else "doc.pdf"]
    assert controller._plan_preview_session_key is None, "the preview session survived the save"
    assert controller._plan_preview_target is None
    assert notified == [1], "the view must drop the token and re-request exactly once"
    if fail_save:
        assert len(shown) == 1 and "simulated refusal after the clean pass" in shown[0], shown
    else:
        assert shown == [], shown
