"""The add-text box is a NEW text box, never a true-text edit (Task B).

Part-3 VERIFY (2026-10-01) defect 4 of
plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md: with
plan preview on, the add-text box ("新增文字框") inherited the true-text edit
machinery that is keyed on mode flags instead of the editor intent:

* on a blank area the plan preview returned ``target_unresolved``, the panel
  said "找不到這段文字…" next to "改用重建文字…", Apply stayed disabled for
  ever, the typed text was invisible, and the rebuild button inserted the
  box without any consent dialog;
* over existing text the preview resolved the run UNDER the box and issued a
  verified token, while Apply inserted a new box and left the original text
  alone -- the preview and Apply disagreed;
* ``sig_add_textbox`` carried no document session, so only the finalize
  ordering kept it from landing in another (byte-identical) document.

The add_new intent never uses the plan preview, the Apply token gate, the
refusal label or the rebuild button; it shows the typed text while typing
and commits through ``add_textbox`` exactly once, bound to the document it
was opened in.

Real-app tests launch ``main.run`` through the harness of
``test_text_commit_finalize_by_result.py`` (synthetic Identity-H documents,
real QTest clicks and keys, recorders only).
"""
from __future__ import annotations

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
from model.pdf_model import PDFModel  # noqa: E402
from test_scripts.test_text_commit_finalize_by_result import (  # noqa: E402
    _App,
    _author,
    _original_texts,
    _sha,
)
from test_scripts.type0_fixture_builder import encode_cids  # noqa: E402
from view.text_edit_reasons import rejection_reason_text  # noqa: E402

_TYPED = "Hello World"
_BLANK_POINT = (72.0, 450.0)  # well below both fixture lines (y 150 / 300)


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


@pytest.fixture
def add_calls(monkeypatch) -> list[tuple]:
    """Every real ``PDFModel.add_textbox`` call: (document, page, text, size)."""
    calls: list[tuple] = []
    original = PDFModel.add_textbox

    def _spy(model, page_num, visual_rect, text, *args, **kwargs):
        calls.append((model.doc, page_num, text, kwargs.get("size")))
        return original(model, page_num, visual_rect, text, *args, **kwargs)

    monkeypatch.setattr(PDFModel, "add_textbox", _spy)
    return calls


def _enter_add_text_mode(app: _App) -> None:
    app.click_toolbar_action(app.view._action_add_text)
    assert app.view.current_mode == "add_text"


def _click_doc_point(app: _App, page_index: int, x: float, y: float) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    scene_point = app.view._doc_rect_to_scene_rect(
        page_index, fitz.Rect(x, y, x + 0.5, y + 0.5)
    ).center()
    app.view.graphics_view.centerOn(scene_point)
    app.pump(120)
    position = app.view.graphics_view.mapFromScene(scene_point)
    QTest.mouseClick(app.view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, position)


def _open_add_box(app: _App, x: float, y: float, page_index: int = 0):
    _enter_add_text_mode(app)
    _click_doc_point(app, page_index, x, y)
    assert app.wait(lambda: app.editor() is not None, 20), "the click opened no add box"
    editor = app.editor()
    assert app.view.editing_intent == "add_new"
    assert editor.toPlainText() == ""
    return editor


def _type(app: _App, editor, text: str) -> None:
    from PySide6.QtTest import QTest

    editor.setFocus()
    QTest.keyClicks(editor, text)


def _dark_pixels(editor) -> int:
    """Opaque dark pixels the editor viewport actually paints."""
    image = editor.viewport().grab().toImage()
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 128 and max(colour.red(), colour.green(), colour.blue()) < 128:
                count += 1
    return count


def _page_text(doc: fitz.Document, page_index: int = 0) -> str:
    return doc[page_index].get_text()


def _assert_no_true_text_machinery(app: _App, editor, payloads_before: int) -> None:
    """All observations at once, so a red run shows every symptom."""
    view = app.view
    observed = {
        "plan_preview_mode": editor.plan_preview_mode(),
        "plan_payloads": len(app.payloads[payloads_before:]),
        "plan_token": editor.current_plan_token() is not None,
        "rejection_reason": editor.plan_rejection_reason(),
        "status_label": "" if view.text_plan_status_label.isHidden()
        else view.text_plan_status_label.text(),
        "rebuild_button_shown": not view.text_rebuild_btn.isHidden(),
        "rebuild_offered": view._ensure_text_edit_manager().rebuild_offered(),
        "apply_enabled": view.text_apply_btn.isEnabled(),
        "painted_text_px": _dark_pixels(editor) > 0,
    }
    assert observed == {
        "plan_preview_mode": False,
        "plan_payloads": 0,
        "plan_token": False,
        "rejection_reason": None,
        "status_label": "",
        "rebuild_button_shown": False,
        "rebuild_offered": False,
        "apply_enabled": True,
        "painted_text_px": True,
    }


# ------------------------------------------------------------ blank-area add


def test_blank_area_add_shows_the_text_and_applies_once_under_plan_settings(
    tmp_path: Path, launch, add_calls
) -> None:
    """RED before Task B: target_unresolved preview, refusal label and rebuild
    button, Apply disabled for ever, 0 painted text pixels."""
    path = _author(tmp_path / "blank.pdf")
    app = launch(path)  # preview='plan', max_tier=1 (the step-12 settings)
    doc = app.model.doc
    payloads_before = len(app.payloads)
    editor = _open_add_box(app, *_BLANK_POINT)
    _type(app, editor, _TYPED)
    app.pump(900)  # debounce + any preview round trip

    assert editor.toPlainText() == _TYPED
    _assert_no_true_text_machinery(app, editor, payloads_before)
    assert add_calls == [] and app.requests == []

    since = time.monotonic()
    app.click_apply()
    app.pump(400)

    assert [(c[0], c[1], c[2]) for c in add_calls] == [(doc, 1, _TYPED)]
    assert app.editor() is None
    assert app.view._last_text_edit_finalize_result.outcome.value == "committed"
    assert app.requests == [] and app.commits == []
    assert app.modals == [], "an add box asked for consent"
    assert len(app.model.command_manager._undo_stack) == 1
    assert "Hello" in _page_text(doc)
    assert app.warnings_since(since) == []
    # Nothing re-sends later (focus net, delayed timers).
    app.pump(400)
    assert len(add_calls) == 1


def test_blank_area_add_commits_once_on_click_away(tmp_path: Path, launch, add_calls) -> None:
    """GUARD (passes before Task B too: click-away was the only working path).
    Click-away commits the add box once; the click does not re-send it."""
    path = _author(tmp_path / "click_away.pdf")
    app = launch(path)
    doc = app.model.doc
    editor = _open_add_box(app, *_BLANK_POINT)
    _type(app, editor, _TYPED)
    app.pump(400)
    _click_doc_point(app, 0, 72.0, 700.0)  # outside the box: finalize CLICK_AWAY
    app.pump(600)

    assert [(c[0], c[2]) for c in add_calls] == [(doc, _TYPED)]
    assert app.view._last_text_edit_finalize_result.outcome.value == "committed"
    assert app.requests == [] and app.commits == [] and app.modals == []
    assert "Hello" in _page_text(doc)


def test_restyled_add_box_still_applies_as_a_plain_add(
    tmp_path: Path, launch, add_calls
) -> None:
    """RED before Task B: a size change counted as a true-text style override
    (token gate), so Apply stayed disabled.  For an add box the size is just
    the new box's size."""
    path = _author(tmp_path / "restyle.pdf")
    app = launch(path)
    payloads_before = len(app.payloads)
    editor = _open_add_box(app, *_BLANK_POINT)
    _type(app, editor, _TYPED)
    app.view.text_size.setCurrentText("16")
    app.pump(600)

    _assert_no_true_text_machinery(app, editor, payloads_before)
    app.click_apply()
    assert [(c[2], c[3]) for c in add_calls] == [(_TYPED, 16)]
    assert app.modals == [] and app.requests == []


# ----------------------------------------------------- add over existing text


def test_add_box_over_existing_text_never_resolves_or_edits_it(
    tmp_path: Path, launch, add_calls
) -> None:
    """RED before Task B: the plan preview resolved the "Pump Room" run under
    the box and issued a verified token, while Apply inserted a new box --
    preview and Apply disagreed.  Now the box never previews, never resolves
    the text underneath, and Apply adds exactly one box; the original run is
    byte-identical."""
    path = _author(tmp_path / "over.pdf")
    app = launch(path)
    doc = app.model.doc
    target = app.glyph_rect("Pump Room")
    payloads_before = len(app.payloads)
    editor = _open_add_box(app, target.x0 + 1.0, target.y0 + 1.0)
    assert app.view.editing_rect.intersects(target), "the box does not cover the text"
    _type(app, editor, "Pump Romo")
    app.pump(1500)  # long enough for a (wrong) preview round trip to land

    _assert_no_true_text_machinery(app, editor, payloads_before)
    app.click_apply()

    assert [(c[0], c[2]) for c in add_calls] == [(doc, "Pump Romo")]
    assert app.requests == [], "Apply sent a true-text edit"
    assert app.commits == [], "the true-text engine committed"
    texts = app.page_texts(doc)
    assert encode_cids("Pump Room") in texts, "the original text was changed"
    assert encode_cids("Buffer Tank") in texts
    assert app.modals == []


# ------------------------------------------------------------ session binding


def _click_document_tab(app: _App, index: int) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    bar = app.view.document_tab_bar
    QTest.mouseClick(bar, Qt.LeftButton, Qt.NoModifier, bar.tabRect(index).center())
    app.pump(1200)


def _open_copy_and_return(app: _App, tmp_path: Path, original: Path):
    """Open a byte-identical copy B, then click A's tab again (real click)."""
    copy = tmp_path / f"{original.stem} (1).pdf"
    shutil.copyfile(original, copy)
    a_sid = app.model.get_active_session_id()
    a_doc = app.model.doc
    app.view.sig_open_pdf.emit(str(copy))
    app.pump(1500)
    b_sid = app.model.get_active_session_id()
    b_doc = app.model.doc
    assert b_sid != a_sid and b_doc is not a_doc
    a_index = next(
        i for i in range(app.view.document_tab_bar.count())
        if app.view.document_tab_bar.tabData(i) == a_sid
    )
    _click_document_tab(app, a_index)
    assert app.model.get_active_session_id() == a_sid
    return copy, a_sid, a_doc, b_sid, b_doc


@pytest.mark.parametrize("preview", ["legacy", "plan"])
def test_add_box_is_bound_to_its_document_session(
    tmp_path: Path, launch, add_calls, preview: str
) -> None:
    """RED before Task B: ``sig_add_textbox`` carried no session id, so an add
    finalized while another document was active landed in THAT document
    (here: a byte-identical copy; measured with the legacy preview, where
    Apply was reachable).  Now it is refused under both preview settings
    (zero mutation in both documents), the box and its text are kept, the
    reason is shown without a rebuild offer, and a later finalize does not
    re-send it."""
    original = _author(tmp_path / "bound.pdf")
    app = launch(original, preview=preview)
    copy, a_sid, a_doc, b_sid, b_doc = _open_copy_and_return(app, tmp_path, original)
    copy_sha = _sha(copy)
    editor = _open_add_box(app, *_BLANK_POINT)
    _type(app, editor, _TYPED)
    app.pump(400)
    # A path that changes the active document without finalizing the editor
    # first (the finalize ordering was the only protection).
    assert app.model.activate_session(b_sid)
    since = time.monotonic()
    app.click_apply()
    app.pump(400)

    assert add_calls == [], f"the add box landed in {add_calls}"
    assert "Hello" not in _page_text(b_doc), "the add box landed in the copy"
    assert "Hello" not in _page_text(a_doc)
    assert app.page_texts(b_doc) == _original_texts()
    assert _sha(copy) == copy_sha
    assert app.editor() is editor and editor.toPlainText() == _TYPED
    result = app.view._last_text_edit_finalize_result
    assert result.outcome.value == "refused"
    assert result.edit_result is EditTextResult.REJECTED
    assert app.view.text_plan_status_label.text() == rejection_reason_text(
        "document_session_mismatch"
    )
    assert app.view.text_rebuild_btn.isHidden()
    assert app.warnings_since(since), "the refusal was silent"
    assert app.modals == []
    # The same refused input is not re-sent by a later focus-out finalize.
    app.view._finalize_text_edit()
    app.pump(200)
    assert add_calls == []


def test_tab_switch_with_an_add_box_lands_only_in_the_origin_document(
    tmp_path: Path, launch, add_calls
) -> None:
    """GUARD (the finalize-before-session-change ordering already held before
    Task B): switching to a byte-identical copy's tab with an add box open in
    A puts the box into A only; the copy is untouched."""
    original = _author(tmp_path / "switch.pdf")
    app = launch(original)
    copy, a_sid, a_doc, b_sid, b_doc = _open_copy_and_return(app, tmp_path, original)
    copy_sha = _sha(copy)
    editor = _open_add_box(app, *_BLANK_POINT)
    _type(app, editor, _TYPED)
    app.pump(400)
    b_index = next(
        i for i in range(app.view.document_tab_bar.count())
        if app.view.document_tab_bar.tabData(i) == b_sid
    )
    _click_document_tab(app, b_index)

    assert app.model.get_active_session_id() == b_sid
    assert [(c[0], c[2]) for c in add_calls] == [(a_doc, _TYPED)]
    assert "Hello" in _page_text(a_doc)
    assert "Hello" not in _page_text(b_doc)
    assert app.page_texts(b_doc) == _original_texts()
    assert _sha(copy) == copy_sha
    assert app.modals == []


def test_opening_a_byte_identical_copy_with_an_add_box_lands_only_in_the_origin(
    tmp_path: Path, launch, add_calls
) -> None:
    """GUARD (``open_pdf`` already finalizes before it activates the new
    session): opening a byte-identical copy through ``sig_open_pdf`` (the
    recent-files path) while an add box in A holds text puts the box into A
    only -- the session binding must not turn this into a refusal."""
    original = _author(tmp_path / "opened.pdf")
    copy = tmp_path / "opened (1).pdf"
    shutil.copyfile(original, copy)
    copy_sha = _sha(copy)
    app = launch(original)
    a_sid = app.model.get_active_session_id()
    a_doc = app.model.doc
    editor = _open_add_box(app, *_BLANK_POINT)
    _type(app, editor, _TYPED)
    app.pump(400)
    app.view.sig_open_pdf.emit(str(copy))
    app.pump(1500)

    assert app.model.get_active_session_id() != a_sid
    b_doc = app.model.doc
    assert b_doc is not a_doc
    assert [(c[0], c[2]) for c in add_calls] == [(a_doc, _TYPED)]
    assert "Hello" in _page_text(a_doc)
    assert app.page_texts(b_doc) == _original_texts()
    assert _sha(copy) == copy_sha
    assert app.editor() is None
    assert app.modals == []


# ------------------------------------------------------------------- audit


def test_plan_mode_flag_is_read_only_through_the_intent_chokepoint() -> None:
    """GUARD (pitfall: a new mode flag must be checked for every editor
    intent).  ``view/text_editing.py`` reads the plan-preview flag in exactly
    one place, the helper that also checks the editor intent."""
    source = (ROOT / "view" / "text_editing.py").read_text(encoding="utf-8")
    reads = source.count("_text_plan_preview_required")
    assert reads == 1, f"{reads} direct reads of the plan-preview flag"
    assert "def _plan_preview_applies(" in source
