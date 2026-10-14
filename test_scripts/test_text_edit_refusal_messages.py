"""ZH-REFUSALS (adversarial round 11, owner decision "Refusal UI"): every
refused text edit reaches the user as ONE plain Traditional Chinese message
per refusal reason, never as the exception's English technical text.

Layers: the Model raises ``TextEditRefused`` carrying a ``TextEditRefusal``
code (Qt-free); the Controller maps code -> fixed zh-TW sentence
(``controller/text_edit_refusals.py``) and logs the technical detail; an
unknown code or an uncoded exception gets the generic sentence and the detail
still goes to the log.

All fixtures are synthetic.
"""
from __future__ import annotations

import logging
import re
import sys
from collections import Counter
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.pdf_text_edit as pdf_text_edit  # noqa: E402
from controller import pdf_controller as pdf_controller_module  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from controller.text_edit_refusals import (  # noqa: E402
    GENERIC_REFUSAL_MESSAGE,
    UserFacingEditError,
    refusal_message,
    user_message_for_exception,
)
from model.edit_commands import EditTextResult  # noqa: E402
from model.edit_requests import EditTextRequest, UnkeepableGlyph  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402
from model.text_edit_refusal import TextEditRefusal, TextEditRefused  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402

ALL_CODES = list(TextEditRefusal)
DETAIL = "internal verification failed: spare_height=-3.2 SECRET_DETAIL_MARKER"
LATIN = re.compile(r"[A-Za-z]")

TARGET = "Price 2024"
DOWNSTREAM = "Downstream line stays"


# ---------------------------------------------------------------- fixtures


def _array_tj_pdf(path: Path) -> Path:
    """Multi-item ``TJ`` page: structurally ineligible for Tier 0, so a
    consented edit reaches the legacy rebuild (and its verification)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    head, tail = TARGET[: len(TARGET) // 2], TARGET[len(TARGET) // 2 :]
    stream = (
        b"BT /F1 12 Tf 72 700 Td [(" + head.encode() + b") (" + tail.encode() + b")] TJ "
        b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
    )
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _accept(_chain, *_a):
    return True


@pytest.fixture
def rebuild_model(tmp_path: Path):
    pdf = _array_tj_pdf(tmp_path / "refusal_source.pdf")
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(pdf))
    model.ensure_page_index_built(1)
    try:
        yield model
    finally:
        model.close()


def _rebuild(model: PDFModel, new_text: str, *, target_mode: str | None = None):
    """Consented rebuild of the ``Price 2024`` line (of its first run when
    ``target_mode`` is ``"run"``); returns the result or the exception it
    raised."""
    block = next(b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or ""))
    rect, original, span_id = fitz.Rect(block.layout_rect), block.text, None
    if target_mode == "run":
        run = model.block_manager.get_runs(0)[0]
        rect, original, span_id = fitz.Rect(run.bbox), run.text, run.span_id
    try:
        return model.edit_text(
            1,
            rect,
            new_text,
            font=block.font or "helv",
            size=float(block.size or 12.0),
            color=(0.0, 0.0, 0.0),
            original_text=original,
            target_span_id=span_id,
            target_mode=target_mode,
            allow_rebuild=True,
            confirm_fallback=_accept,
        )
    except RuntimeError as exc:
        return exc


def _launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str = "tiered"):
    pdf = _array_tj_pdf(tmp_path / "controller_source.pdf")
    model = PDFModel(text_commit_settings=TextCommitSettings(engine=engine))
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(pdf))
    monkeypatch.setattr(controller, "show_page", lambda _page: None)
    monkeypatch.setattr(
        controller, "_invalidate_active_render_state", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(controller, "_invalidate_thumbnails", lambda *a, **k: None, )
    monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)
    monkeypatch.setattr(view, "capture_viewport_anchor", lambda: None)
    errors: list[str] = []
    monkeypatch.setattr(
        pdf_controller_module, "show_error", lambda _view, message: errors.append(str(message))
    )
    return model, view, controller, errors


def _request(model: PDFModel) -> EditTextRequest:
    model.ensure_page_index_built(1)
    block = next(b for b in model.block_manager.get_blocks(0) if TARGET in (b.text or ""))
    return EditTextRequest(
        page=1,
        rect=fitz.Rect(block.layout_rect),
        new_text="Price 2025",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        allow_rebuild=True,
    )


# ------------------------------------------------- the code -> message map


@pytest.mark.parametrize("code", ALL_CODES, ids=lambda c: c.value)
def test_every_refusal_code_has_a_plain_zh_tw_sentence(code: TextEditRefusal) -> None:
    text = refusal_message(code)
    assert text and text != GENERIC_REFUSAL_MESSAGE or code is TextEditRefusal.EDIT_FAILED
    assert not LATIN.search(text), f"English/technical text in the zh-TW sentence: {text}"
    assert re.search(r"[一-鿿]", text)
    # the string value maps too (a code that crossed a boundary as text)
    assert refusal_message(code.value) == text


def test_distinct_refusal_reasons_get_distinct_sentences() -> None:
    texts = {code: refusal_message(code) for code in ALL_CODES}
    assert len(set(texts.values())) == len(ALL_CODES), "two reasons share one sentence"



def test_the_paint_state_refusal_has_its_own_sentence() -> None:
    """F17-COL-1..4: a rebuild (or a cross-page move) that cannot keep the
    paint state of the text it writes again -- render mode, colour space,
    transparency, layer -- refuses with its own plain sentence, the same on
    both paths."""
    text = refusal_message("text_state_not_reproducible")
    assert text != GENERIC_REFUSAL_MESSAGE
    assert "顯示方式" in text and "文件沒有被改動" in text
    assert not LATIN.search(text)
    assert refusal_message("text_state_not_reproducible", cross_page_move=True) == text

@pytest.mark.parametrize("bad", [None, "", "no_such_reason", 42, object()])
def test_unknown_code_falls_back_to_the_generic_sentence(bad: object) -> None:
    assert refusal_message(bad) == GENERIC_REFUSAL_MESSAGE
    assert not LATIN.search(GENERIC_REFUSAL_MESSAGE)


def test_text_edit_refused_keeps_the_detail_out_of_the_sentence() -> None:
    exc = TextEditRefused(TextEditRefusal.TEXT_DOES_NOT_FIT, DETAIL)
    assert isinstance(exc, RuntimeError)
    assert str(exc) == DETAIL and exc.detail == DETAIL
    assert exc.reason is TextEditRefusal.TEXT_DOES_NOT_FIT
    assert "SECRET_DETAIL_MARKER" not in user_message_for_exception(exc)
    assert user_message_for_exception(RuntimeError(DETAIL)) == GENERIC_REFUSAL_MESSAGE
    assert TextEditRefused(TextEditRefusal.EDIT_FAILED).detail == "edit_failed"


# ----------------------------------- controller: the dialog shows the map


@pytest.mark.parametrize("code", ALL_CODES, ids=lambda c: c.value)
def test_edit_text_dialog_shows_the_mapped_sentence_and_logs_the_detail(
    qapp, tmp_path, monkeypatch, caplog, code: TextEditRefusal
) -> None:
    model, view, controller, errors = _launch(tmp_path, monkeypatch)
    try:

        def _refuse(_cmd):
            raise TextEditRefused(code, DETAIL)

        monkeypatch.setattr(model.command_manager, "execute", _refuse)
        with caplog.at_level(logging.ERROR):
            controller.edit_text(_request(model))
        assert errors == [refusal_message(code)]
        assert not LATIN.search(errors[0])
        assert "SECRET_DETAIL_MARKER" not in errors[0]
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "SECRET_DETAIL_MARKER" in logged and code.value in logged
    finally:
        model.close()
        view.close()
        qapp.processEvents()


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("編輯文字失敗: MuPDF error: unsupported SECRET_DETAIL_MARKER"),
        ValueError("bad value SECRET_DETAIL_MARKER"),
        KeyError("SECRET_DETAIL_MARKER"),
    ],
    ids=["runtime", "value", "key"],
)
def test_an_uncoded_exception_gets_the_generic_sentence_and_is_logged(
    qapp, tmp_path, monkeypatch, caplog, exc: Exception
) -> None:
    model, view, controller, errors = _launch(tmp_path, monkeypatch)
    try:

        def _boom(_cmd):
            raise exc

        monkeypatch.setattr(model.command_manager, "execute", _boom)
        with caplog.at_level(logging.ERROR):
            controller.edit_text(_request(model))
        assert errors == [GENERIC_REFUSAL_MESSAGE]
        assert "SECRET_DETAIL_MARKER" in "\n".join(r.getMessage() for r in caplog.records)
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_a_cross_page_move_refusal_shows_the_mapped_sentence(
    qapp, tmp_path, monkeypatch, caplog
) -> None:
    """The move's source deletion is a text edit: its coded refusal must not
    come out as ``跨頁移動文字失敗: <English detail>``."""
    model, view, controller, errors = _launch(tmp_path, monkeypatch)
    try:
        model.ensure_page_index_built(1)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", lambda _chain: True)
        monkeypatch.setattr(
            controller, "_resolve_cross_page_move_source_span_id", lambda **_k: "p0_b0_l0_s0"
        )
        monkeypatch.setattr(controller, "_source_run_text_probe", lambda *_a: "")
        monkeypatch.setattr(controller, "_count_page_runs_with_text", lambda *_a: 0)

        def _refuse(*_a, **_k):
            raise TextEditRefused(TextEditRefusal.REDACTION_LEFT_SOURCE, DETAIL)

        monkeypatch.setattr(model, "edit_text", _refuse)
        doc = model.doc
        doc.new_page(width=595, height=842)
        with caplog.at_level(logging.ERROR):
            controller.move_text_across_pages(
                source_page=1,
                source_rect=fitz.Rect(72, 90, 200, 110),
                destination_page=2,
                destination_rect=fitz.Rect(60, 60, 220, 110),
                new_text="MOVED",
                font="helv",
                size=12,
                color=(0.0, 0.0, 0.0),
                original_text=TARGET,
                target_span_id=None,
                target_mode="run",
                allow_rebuild=True,
            )
        assert errors, "the refusal must reach the user"
        assert refusal_message(TextEditRefusal.REDACTION_LEFT_SOURCE) in errors[0]
        assert not LATIN.search(errors[0]) and "SECRET_DETAIL_MARKER" not in errors[0]
        assert "SECRET_DETAIL_MARKER" in "\n".join(r.getMessage() for r in caplog.records)
    finally:
        model.close()
        view.close()
        qapp.processEvents()


# F12-DLG-3: the cross-page move asks its consent BEFORE the model runs, so
# the prompt cannot carry the glyph acknowledgement and the source deletion
# replays a bare True.  The generic glyph sentence ends "redo and confirm when
# prompted" -- advice that cannot work on the move path (the same Yes gives
# the same refusal), so the move maps its own sentence.
_CONFIRM_AT_PROMPT = "在提示時確認"


def test_the_move_sentence_for_unacknowledged_glyphs_does_not_point_at_a_prompt() -> None:
    code = TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED
    plain = refusal_message(code)
    moved = refusal_message(code, cross_page_move=True)
    assert _CONFIRM_AT_PROMPT in plain, "the same-page sentence keeps its prompt advice"
    assert moved != plain
    assert _CONFIRM_AT_PROMPT not in moved
    assert not LATIN.search(moved) and re.search(r"[一-鿿]", moved)
    exc = TextEditRefused(code, DETAIL)
    assert user_message_for_exception(exc, cross_page_move=True) == moved
    assert user_message_for_exception(exc) == plain
    assert "SECRET_DETAIL_MARKER" not in moved


@pytest.mark.parametrize("code", ALL_CODES, ids=lambda c: c.value)
def test_no_move_sentence_promises_a_confirmation_the_move_cannot_show(
    code: TextEditRefusal,
) -> None:
    moved = refusal_message(code, cross_page_move=True)
    assert moved and not LATIN.search(moved)
    assert _CONFIRM_AT_PROMPT not in moved
    if code is not TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED:
        assert moved == refusal_message(code), "only the glyph sentence is path-specific"


def test_a_cross_page_move_glyph_refusal_does_not_tell_the_user_to_confirm_again(
    qapp, tmp_path, monkeypatch, caplog
) -> None:
    """Real MVC stack: a line overlapped by an untouched U+FFFD run is moved
    to another page and the user answers Yes to the move's prompt.  The move
    still refuses (accepted, TODOS F11-UNI-1) but the dialog must not send the
    user back to a prompt that never offers the acknowledgement."""
    from model.edit_requests import MoveTextRequest
    from test_edit_text_helpers import _f11_pdf

    pdf = tmp_path / "glyph_move.pdf"
    _f11_pdf(pdf, 0xFFFD, protected=True)
    with fitz.open(str(pdf)) as extra:
        extra.new_page(width=595, height=842)
        extra.saveIncr()
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    errors: list[str] = []
    prompts: list[str] = []
    monkeypatch.setattr(
        pdf_controller_module, "show_error", lambda _view, message: errors.append(str(message))
    )
    monkeypatch.setattr(
        pdf_controller_module,
        "confirm_degraded_fallback",
        lambda _parent, message: prompts.append(str(message)) or True,
    )
    monkeypatch.setattr(controller, "show_page", lambda _page: None)
    monkeypatch.setattr(controller, "_invalidate_active_render_state", lambda *a, **k: None)
    monkeypatch.setattr(controller, "_invalidate_thumbnails", lambda *a, **k: None)
    monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)
    try:
        controller.open_pdf(str(pdf))
        model.ensure_page_index_built(1)
        span = next(s for s in model.block_manager.get_runs(0) if (s.text or "") == "today")
        before = model.doc[0].get_text()
        with caplog.at_level(logging.ERROR):
            controller.move_text_across_pages(
                MoveTextRequest(
                    source_page=1,
                    source_rect=fitz.Rect(span.bbox),
                    destination_page=2,
                    destination_rect=fitz.Rect(72, 100, 300, 130),
                    new_text="today",
                    font="helv",
                    size=11.0,
                    color=(0, 0, 0),
                    original_text="today",
                    target_span_id=span.span_id,
                    allow_rebuild=True,
                    session_id=model.get_active_session_id(),
                )
            )
        assert len(prompts) == 1, "the move asks once, before the model runs"
        assert "unidentifiable_glyphs_not_acknowledged" in "\n".join(
            r.getMessage() for r in caplog.records
        ), "the refusal is the glyph one (technical detail goes to the log)"
        assert model.doc[0].get_text() == before, "a refused move leaves the page unchanged"
        assert errors, "the refusal must reach the user"
        assert _CONFIRM_AT_PROMPT not in errors[-1]
        assert refusal_message(
            TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED, cross_page_move=True
        ) in errors[-1]
        assert not LATIN.search(errors[-1])
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_add_textbox_failure_shows_no_english_technical_text(
    qapp, tmp_path, monkeypatch, caplog
) -> None:
    model, view, controller, errors = _launch(tmp_path, monkeypatch)
    try:

        def _boom(_cmd):
            raise RuntimeError("insert_htmlbox failed: SECRET_DETAIL_MARKER")

        monkeypatch.setattr(model.command_manager, "execute", _boom)
        with caplog.at_level(logging.ERROR):
            controller.add_textbox(1, fitz.Rect(72, 300, 200, 320), "hello", "helv", 12.0, (0, 0, 0))
        assert errors == [GENERIC_REFUSAL_MESSAGE]
        assert "SECRET_DETAIL_MARKER" in "\n".join(r.getMessage() for r in caplog.records)
    finally:
        model.close()
        view.close()
        qapp.processEvents()


@pytest.mark.parametrize("pasted", ["\x00\x01", "\x0b\x00\x7f", "   ", "\ufffc", " \ufffc\ufffc "])
def test_add_textbox_of_blank_or_control_only_text_is_a_silent_no_op(
    qapp, tmp_path, monkeypatch, pasted
) -> None:
    """F16-PASTE-1: nothing drawable remains after the control characters go."""
    model, view, controller, errors = _launch(tmp_path, monkeypatch)
    try:
        before = model.doc[0].get_text()
        controller.add_textbox(1, fitz.Rect(72, 300, 200, 320), pasted, "helv", 12.0, (0, 0, 0))
        assert errors == []
        assert not model.command_manager.can_undo()
        assert model.doc[0].get_text() == before
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_add_textbox_with_a_pasted_image_anchor_commits_the_text_without_it(
    qapp, tmp_path, monkeypatch
) -> None:
    """F16-PASTE-2: no OBJ box, no U+FFFC in the text layer, and no prompt."""
    model, view, controller, errors = _launch(tmp_path, monkeypatch)
    try:
        controller.add_textbox(1, fitz.Rect(72, 300, 300, 340), "Logo \ufffc X", "helv", 12.0, (0, 0, 0))
        assert errors == []
        assert model.command_manager.can_undo()
        assert "\ufffc" not in model.doc[0].get_text()
        assert "LogoX" in "".join(model.doc[0].get_text().split())
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_add_textbox_with_pasted_control_characters_commits_the_clean_text(
    qapp, tmp_path, monkeypatch
) -> None:
    model, view, controller, errors = _launch(tmp_path, monkeypatch)
    try:
        controller.add_textbox(1, fitz.Rect(72, 300, 300, 340), "Ab\x00\x01Cd", "helv", 12.0, (0, 0, 0))
        assert errors == []
        assert model.command_manager.can_undo()
        assert "AbCd" in "".join(model.doc[0].get_text().split())
    finally:
        model.close()
        view.close()
        qapp.processEvents()


# ------------------ controller: undo/redo are an exception boundary (R12)


def _legacy_history(tmp_path, monkeypatch):
    """A committed, then undone, ``engine="legacy"`` edit.  That commit keeps
    no replay record, so its redo RE-RUNS ``model.edit_text`` -- the one redo
    path that can raise a coded refusal."""
    model, view, controller, errors = _launch(tmp_path, monkeypatch, engine="legacy")
    controller.edit_text(_request(model))
    cm = model.command_manager
    assert cm.can_undo() and not errors, errors
    controller.undo()
    assert cm.can_redo() and not cm.can_undo() and not errors, errors
    return model, view, controller, errors


@pytest.mark.parametrize(
    "code",
    [TextEditRefusal.VERIFICATION_FAILED, TextEditRefusal.ROLLBACK_FAILED],
    ids=lambda c: c.value,
)
def test_redo_that_re_runs_a_refused_edit_shows_the_mapped_sentence(
    qapp, tmp_path, monkeypatch, caplog, code: TextEditRefusal
) -> None:
    model, view, controller, errors = _legacy_history(tmp_path, monkeypatch)
    try:
        cm = model.command_manager
        before = (cm.undo_count, cm.redo_count)
        real_edit_text = model.edit_text

        def _refuse(*_a, **_k):
            raise TextEditRefused(code, DETAIL)

        monkeypatch.setattr(model, "edit_text", _refuse)
        with caplog.at_level(logging.ERROR):
            controller.redo()  # must not raise out of the Qt slot
        assert errors == [refusal_message(code)]
        assert not LATIN.search(errors[0]) and "SECRET_DETAIL_MARKER" not in errors[0]
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "SECRET_DETAIL_MARKER" in logged and code.value in logged
        # history stays consistent: the command is still redoable, nothing moved
        assert (cm.undo_count, cm.redo_count) == before
        assert cm.can_redo() and not cm.can_undo()
        # ... and a later redo that no longer refuses really redoes it
        monkeypatch.setattr(model, "edit_text", real_edit_text)
        controller.redo()
        assert len(errors) == 1, errors
        assert (cm.undo_count, cm.redo_count) == (1, 0)
        assert "2025" in model.doc[0].get_text()
    finally:
        model.close()
        view.close()
        qapp.processEvents()


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_an_uncoded_history_failure_is_reported_not_raised(
    qapp, tmp_path, monkeypatch, caplog, direction: str
) -> None:
    """The same boundary for every command kind: an uncoded exception from a
    command's own undo/redo gets a neutral sentence (never the text-edit one,
    never the English detail), is logged, and leaves both stacks alone."""
    model, view, controller, errors = _legacy_history(tmp_path, monkeypatch)
    try:
        cm = model.command_manager
        if direction == "undo":
            controller.redo()
            assert cm.can_undo() and not errors, errors
            cmd = cm._undo_stack[-1]
            monkeypatch.setattr(
                cmd, "undo", lambda: (_ for _ in ()).throw(RuntimeError("boom SECRET_DETAIL_MARKER"))
            )
        else:
            cmd = cm._redo_stack[-1]
            monkeypatch.setattr(
                cmd, "execute", lambda: (_ for _ in ()).throw(RuntimeError("boom SECRET_DETAIL_MARKER"))
            )
        before = (cm.undo_count, cm.redo_count)
        with caplog.at_level(logging.ERROR):
            getattr(controller, direction)()
        assert len(errors) == 1
        assert errors[0] not in (GENERIC_REFUSAL_MESSAGE,) and not LATIN.search(errors[0])
        assert "SECRET_DETAIL_MARKER" not in errors[0]
        assert "SECRET_DETAIL_MARKER" in "\n".join(r.getMessage() for r in caplog.records)
        assert (cm.undo_count, cm.redo_count) == before
    finally:
        model.close()
        view.close()
        qapp.processEvents()


# ------------------------- model: every refusal site raises a coded refusal

_CJK_NEW = "價格二〇二五"
_LONG_CJK_NEW = "價格" * 30  # 60 characters: reaches the long-line presence gate


def _draw_nothing_on_the_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real insert draws nothing; the scratch reference render is real."""
    real_insert = pdf_text_edit.insert_htmlbox_tracked

    def _insert(page, rect, html, *, scratch=False, **kwargs):
        if scratch:
            return real_insert(page, rect, html, scratch=scratch, **kwargs)
        return 5.0, 1.0

    monkeypatch.setattr(pdf_text_edit, "insert_htmlbox_tracked", _insert)


def _assert_refused(result: object, model: PDFModel, before: str, code: TextEditRefusal) -> None:
    assert isinstance(result, TextEditRefused), f"expected a coded refusal, got {result!r}"
    assert result.reason is code, f"{result.reason!r}: {result}"
    assert model.doc[0].get_text() == before, "a refusal must leave the page untouched"


def test_text_that_cannot_fit_is_refused_with_text_does_not_fit(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = rebuild_model.doc[0].get_text()
    monkeypatch.setattr(pdf_text_edit, "insert_htmlbox_tracked", lambda *a, **k: (-1.0, 1.0))
    result = _rebuild(rebuild_model, _CJK_NEW)
    _assert_refused(result, rebuild_model, before, TextEditRefusal.TEXT_DOES_NOT_FIT)


def test_requested_characters_missing_after_the_insert_are_characters_lost(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = rebuild_model.doc[0].get_text()
    _draw_nothing_on_the_document(monkeypatch)
    result = _rebuild(rebuild_model, _CJK_NEW)
    _assert_refused(result, rebuild_model, before, TextEditRefusal.CHARACTERS_LOST)


def test_target_text_not_on_the_page_is_target_not_present(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = rebuild_model.doc[0].get_text()
    _draw_nothing_on_the_document(monkeypatch)
    monkeypatch.setattr(pdf_text_edit, "_lost_requested_chars", lambda *_a, **_k: [])
    result = _rebuild(rebuild_model, _CJK_NEW)
    _assert_refused(result, rebuild_model, before, TextEditRefusal.TARGET_NOT_PRESENT)


def test_a_replayed_neighbour_that_fails_validation_is_protected_span_changed(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = rebuild_model.doc[0].get_text()
    monkeypatch.setattr(rebuild_model, "_validate_protected_spans", lambda *_a, **_k: False)
    result = _rebuild(rebuild_model, _CJK_NEW)
    _assert_refused(result, rebuild_model, before, TextEditRefusal.PROTECTED_SPAN_CHANGED)


def test_a_low_similarity_after_a_present_target_is_verification_failed(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = rebuild_model.doc[0].get_text()
    _draw_nothing_on_the_document(monkeypatch)
    monkeypatch.setattr(pdf_text_edit, "_lost_requested_chars", lambda *_a, **_k: [])
    monkeypatch.setattr(pdf_text_edit, "token_coverage_ratio", lambda *_a, **_k: 1.0)
    # the strict similarity gate does not apply to paragraph-mode edits
    result = _rebuild(rebuild_model, _LONG_CJK_NEW, target_mode="run")
    _assert_refused(result, rebuild_model, before, TextEditRefusal.VERIFICATION_FAILED)


def test_a_failed_rollback_is_rollback_failed(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pdf_text_edit, "insert_htmlbox_tracked", lambda *a, **k: (-1.0, 1.0))

    def _no_way_back(*_a, **_k):
        raise RuntimeError("snapshot restore failed")

    monkeypatch.setattr(pdf_text_edit, "_rollback_rebuild_page", _no_way_back)
    result = _rebuild(rebuild_model, _CJK_NEW)
    assert isinstance(result, TextEditRefused), repr(result)
    assert result.reason is TextEditRefusal.ROLLBACK_FAILED


@pytest.mark.parametrize("error", [ValueError("boom"), RuntimeError("MuPDF: boom")], ids=["value", "runtime"])
def test_an_unexpected_failure_inside_the_edit_is_edit_failed(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Whatever escapes the rewrite (after the page is rolled back) is coded
    too, so the Controller never has to guess from an English message."""
    before = rebuild_model.doc[0].get_text()

    def _boom(*_a, **_k):
        raise error

    monkeypatch.setattr(rebuild_model, "_apply_redact_insert", _boom)
    result = _rebuild(rebuild_model, _CJK_NEW)
    _assert_refused(result, rebuild_model, before, TextEditRefusal.EDIT_FAILED)
    assert str(error) in str(result)
    assert result.__cause__ is error


# ---- the verification's text-layer branches, one reason code each

_REQUESTED = "ab\U00020000"


def _problem(requested, page_text, reference, page_glyphs=None, acknowledged=()):
    return pdf_text_edit._lossy_text_layer_problem(
        requested, page_text, reference, page_glyphs or Counter(), acknowledged
    )


def _reference(text: str = "", glyphs=None, notdef: int = 0):
    return pdf_text_edit._HtmlboxReference(text, glyphs or Counter(), notdef)


def test_text_layer_problem_carries_the_reason_of_each_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. the scratch render carries the character but the page lacks it
    p = _problem("ab", "a", _reference("ab"))
    assert p is not None and p.reason is TextEditRefusal.CHARACTERS_LOST
    assert isinstance(p, str) and "requested characters are not on the page" in p

    # 2. an identity-less placeholder nobody acknowledged (F11-UNI-1)
    p = _problem("a�", "a", _reference("a�"))
    assert p is not None
    assert p.reason is TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED

    # ... but a lost real character next to it is the plainer reason
    p = _problem("ab�", "a", _reference("ab�"))
    assert p is not None and p.reason is TextEditRefusal.CHARACTERS_LOST

    # 3. no font draws a requested character (.notdef), not an Ext-B one
    monkeypatch.setattr(pdf_text_edit, "ext_b_refusal_reason", lambda _t: None)
    p = _problem("ab", "a", _reference("a", notdef=1))
    assert p is not None and p.reason is TextEditRefusal.NO_FONT_FOR_CHARACTERS

    # 4. ... an Ext-B one with no Ext-B font installed
    monkeypatch.setattr(pdf_text_edit, "ext_b_refusal_reason", lambda _t: "no Ext-B font")
    monkeypatch.setattr(pdf_text_edit, "ext_b_install_would_help", lambda: True)
    p = _problem("ab", "a", _reference("a", notdef=1))
    assert p is not None and p.reason is TextEditRefusal.EXT_B_FONT_MISSING
    assert "no Ext-B font" in p

    # 5. the reference glyphs are not drawn on the page
    glyphs: Counter = Counter({("F", 7): 1})
    p = _problem("a\U0001F600", "a", _reference("a", glyphs=glyphs), Counter())
    assert p is not None and p.reason is TextEditRefusal.GLYPHS_NOT_DRAWN

    # nothing wrong -> None, and the accepted lossy layer stays accepted
    assert _problem("ab", "ab", _reference("ab")) is None


def test_an_acknowledged_placeholder_is_still_accepted_with_a_reason_type() -> None:
    ack = (UnkeepableGlyph(span_id=None, index=1, codepoint="U+FFFD", fate="replaced"),)
    assert _problem("a�", "a", _reference("a"), acknowledged=ack) is None


def test_the_edit_result_enum_is_untouched_by_the_refusal_codes() -> None:
    # EditTextResult values keep their own mapping (_edit_result_to_message);
    # the refusal codes are for refusals that raise.
    assert not {c.value for c in TextEditRefusal} & {r.value for r in EditTextResult}


# ----------------------------- F12-DLG-4: install advice only where it can help


def _ext_b_world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, installed: bool, windows: bool):
    """Pretend Ext-B fonts are (not) installed on (not) Windows.  An installed
    font here is an unreadable file: it exists, so the machine HAS the fonts, but
    it covers no code point (the 'installed fonts lack the glyph' case)."""
    import utils.cjk_ext_b_font as extb

    fake = tmp_path / "simsunb.ttf"
    fake.write_bytes(b"not a font")
    fonts = (extb.ExtBFont(fake, 0, "SimSun"),) if installed else ()
    monkeypatch.setattr(extb, "find_ext_b_fonts", lambda: fonts)
    monkeypatch.setattr(extb, "_on_windows", lambda: windows, )
    extb._coverage_cached.cache_clear()
    return extb


def _ext_b_problem(requested: str = "a\U00030000"):
    p = _problem(requested, "a", _reference("a", notdef=1))
    assert p is not None
    return p


def test_ext_b_character_the_installed_fonts_lack_does_not_say_install_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ext_b_world(monkeypatch, tmp_path, installed=True, windows=True)
    p = _ext_b_problem()
    message = refusal_message(p.reason)
    assert p.reason is TextEditRefusal.NO_FONT_FOR_CHARACTERS
    assert "安裝" not in message and "改用其他字" in message
    assert "have no glyph for U+30000" in p  # the log keeps the detail


def test_ext_b_with_no_font_on_windows_still_says_install_the_fonts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ext_b_world(monkeypatch, tmp_path, installed=False, windows=True)
    p = _ext_b_problem()
    assert p.reason is TextEditRefusal.EXT_B_FONT_MISSING
    assert "請安裝" in refusal_message(p.reason)


def test_ext_b_off_windows_does_not_say_install_because_no_font_can_be_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ext_b_world(monkeypatch, tmp_path, installed=False, windows=False)
    p = _ext_b_problem()
    assert p.reason is TextEditRefusal.NO_FONT_FOR_CHARACTERS
    assert "安裝" not in refusal_message(p.reason)


def test_install_advice_predicate_follows_platform_and_installed_fonts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extb = _ext_b_world(monkeypatch, tmp_path, installed=False, windows=True)
    assert extb.ext_b_install_would_help() is True
    monkeypatch.setattr(extb, "_on_windows", lambda: False)
    assert extb.ext_b_install_would_help() is False
    _ext_b_world(monkeypatch, tmp_path, installed=True, windows=True)
    assert extb.ext_b_install_would_help() is False


def test_ext_b_with_fonttools_unimportable_names_the_broken_install_not_the_glyphs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F13-ENV-3: fonts installed but fontTools unimportable (a venv from before
    it became a runtime dependency, a partial install) is a broken program, so
    the dialog must not tell the user to pick other characters or to install
    fonts that are already there."""
    _ext_b_world(monkeypatch, tmp_path, installed=True, windows=True)
    for name in ("fontTools", "fontTools.ttLib", "fontTools.subset"):
        monkeypatch.setitem(sys.modules, name, None)
    p = _ext_b_problem()
    assert p.reason is TextEditRefusal.EXT_B_COMPONENT_MISSING
    assert "fontTools" in p and "have no glyph" not in p  # the log names the cause
    message = refusal_message(p.reason)
    assert "重新安裝" in message and "改用其他字再試" not in message
    assert message != refusal_message(TextEditRefusal.EXT_B_FONT_MISSING)
    assert "細明體" not in message  # not the install-the-fonts advice


# ------------- S13-DLG5-DAMAGED: a failed rollback latches the session damaged
#
# Owner decision A + C (F12-DLG-5): after ROLLBACK_FAILED the sentence says to
# close the tab without saving and reopen, AND the model refuses every in-place
# write of the session (only a Save As to another file is allowed).  Reopening
# the same path just returns the damaged tab, so the sentence alone was not safe.


def _half_rewrite(*args, **kwargs):
    page = kwargs.get("page") or args[0]
    page.insert_text((72, 300), "HALF-WRITTEN", fontsize=12)
    raise RuntimeError("mupdf failure mid-rewrite")


def _rollback_cannot_restore(*_a, **_k):
    raise RuntimeError("rollback failed")


def _file_digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_on_disk(path: Path) -> str:
    with fitz.open(str(path)) as doc:
        return doc[0].get_text()


@pytest.fixture
def damaged_launch(qapp, tmp_path, monkeypatch):
    """A controller session whose consented rebuild half-rewrote the page and
    whose rollback failed; yields ``(model, view, controller, errors, pdf)``."""
    model, view, controller, errors = _launch(tmp_path, monkeypatch, engine="legacy")
    infos: list[str] = []
    monkeypatch.setattr(
        pdf_controller_module.QMessageBox,
        "information",
        staticmethod(lambda *a, **k: infos.append(str(a[2]) if len(a) > 2 else "")),
    )
    monkeypatch.setattr(pdf_controller_module, "confirm_degraded_fallback", lambda *_a: True)
    monkeypatch.setattr(model, "_apply_redact_insert", _half_rewrite)
    monkeypatch.setattr(pdf_text_edit, "_rollback_rebuild_page", _rollback_cannot_restore)
    pdf = Path(model.original_path)
    controller.edit_text(_request(model))
    assert errors and errors[-1] == refusal_message(TextEditRefusal.ROLLBACK_FAILED), errors
    errors.clear()
    controller._test_infos = infos
    try:
        yield model, view, controller, errors, pdf
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_rollback_failed_sentence_says_close_the_tab_without_saving_then_reopen() -> None:
    message = refusal_message(TextEditRefusal.ROLLBACK_FAILED)
    assert "關閉" in message and "不儲存" in message and "重新開啟" in message, message
    assert "另存新檔" in message  # the only way to keep the current content
    assert not LATIN.search(message)


@pytest.mark.parametrize("failure", [RuntimeError("mupdf"), ValueError("boom")], ids=["runtime", "value"])
def test_both_rollback_failed_raise_sites_latch_the_session_damaged(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def _fail(*_a, **_k):
        raise failure

    monkeypatch.setattr(rebuild_model, "_apply_redact_insert", _fail)
    monkeypatch.setattr(pdf_text_edit, "_rollback_rebuild_page", _rollback_cannot_restore)
    assert rebuild_model.session_damaged is False
    result = _rebuild(rebuild_model, _CJK_NEW)
    assert isinstance(result, TextEditRefused) and result.reason is TextEditRefusal.ROLLBACK_FAILED
    assert rebuild_model.session_damaged is True
    assert rebuild_model.is_session_damaged(rebuild_model.get_active_session_id()) is True


def test_a_failure_that_rolled_back_cleanly_does_not_latch_damaged(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_a, **_k):
        raise ValueError("boom")

    monkeypatch.setattr(rebuild_model, "_apply_redact_insert", _boom)
    result = _rebuild(rebuild_model, _CJK_NEW)
    assert isinstance(result, TextEditRefused) and result.reason is TextEditRefusal.EDIT_FAILED
    assert rebuild_model.session_damaged is False


def test_damaged_session_refuses_a_controller_save_and_leaves_the_file_alone(damaged_launch) -> None:
    model, _view, controller, errors, pdf = damaged_launch
    assert "HALF-WRITTEN" in model.doc[0].get_text()
    assert model.session_damaged is True
    before = _file_digest(pdf)
    controller.save()
    assert _file_digest(pdf) == before, "the original must not be overwritten"
    assert "HALF-WRITTEN" not in _text_on_disk(pdf)
    assert len(errors) == 1 and "另存新檔" in errors[0] and "關閉" in errors[0], errors
    assert controller._test_infos == [], "no success message for a refused save"


def test_damaged_session_refuses_model_save_as_onto_its_own_file(damaged_launch) -> None:
    from model.pdf_model import DamagedSessionSaveError

    model, _view, _controller, _errors, pdf = damaged_launch
    before = _file_digest(pdf)
    with pytest.raises(DamagedSessionSaveError, match="另存新檔"):
        model.save_as(str(pdf))
    # the same file spelled differently is the same file
    with pytest.raises(DamagedSessionSaveError):
        model.save_as(str(pdf.parent / ".." / pdf.parent.name / pdf.name.upper()))
    assert _file_digest(pdf) == before


def test_damaged_session_can_still_save_as_a_new_file(damaged_launch, tmp_path) -> None:
    from model.pdf_model import DamagedSessionSaveError

    model, _view, controller, errors, pdf = damaged_launch
    before = _file_digest(pdf)
    copy = tmp_path / "kept_copy.pdf"
    controller.save_as(str(copy))
    assert errors == [] and copy.exists()
    assert "HALF-WRITTEN" in _text_on_disk(copy), "Save As keeps the user's current content"
    assert _file_digest(pdf) == before, "the original stays untouched"
    # the latch is not cleared by the Save As: the session is still its (new) file
    assert model.session_damaged is True
    with pytest.raises(DamagedSessionSaveError):
        model.save_as(str(copy))


# F14-DMG-1: the protection must not be derived from the session's CURRENT
# file only.  A Save As rebinds saved/original/canonical path to the new file,
# so a second Save As (or an export / merge / optimize copy) pointed back at the
# file the session was opened from overwrote the only good copy.


def test_damaged_session_save_as_back_onto_the_original_after_a_save_as_is_refused(
    damaged_launch, tmp_path
) -> None:
    from model.pdf_model import DamagedSessionSaveError

    model, _view, controller, errors, pdf = damaged_launch
    before = _file_digest(pdf)
    copy = tmp_path / "kept_copy.pdf"
    controller.save_as(str(copy))
    assert errors == [] and copy.exists()
    with pytest.raises(DamagedSessionSaveError, match="另存新檔"):
        model.save_as(str(pdf))
    # the same file spelled differently is the same file
    with pytest.raises(DamagedSessionSaveError):
        model.save_as(str(pdf.parent / ".." / pdf.parent.name / pdf.name.upper()))
    assert _file_digest(pdf) == before, "the original must not be overwritten"
    assert "HALF-WRITTEN" not in _text_on_disk(pdf)
    # GUARD: a genuinely new file is still allowed after the first Save As
    third = tmp_path / "third_copy.pdf"
    model.save_as(str(third))
    assert third.exists() and "HALF-WRITTEN" in _text_on_disk(third)
    assert model.session_damaged is True
    with pytest.raises(DamagedSessionSaveError):
        model.save_as(str(pdf))
    assert _file_digest(pdf) == before


def test_damaged_session_controller_save_as_back_onto_the_original_is_refused(
    damaged_launch, tmp_path
) -> None:
    model, _view, controller, errors, pdf = damaged_launch
    before = _file_digest(pdf)
    controller.save_as(str(tmp_path / "kept_copy.pdf"))
    assert errors == []
    controller.save_as(str(pdf))
    assert _file_digest(pdf) == before
    assert errors and "另存新檔" in errors[-1], errors


def test_damaged_session_export_and_merge_never_target_the_original_after_a_save_as(
    damaged_launch, tmp_path
) -> None:
    from model.pdf_model import DamagedSessionSaveError

    model, _view, controller, errors, pdf = damaged_launch
    before = _file_digest(pdf)
    controller.save_as(str(tmp_path / "kept_copy.pdf"))
    assert errors == []
    with pytest.raises(DamagedSessionSaveError):
        model.export_pages([1], str(pdf), as_image=False)
    merged = model.compose_merged_document([{"source_kind": "current"}])
    try:
        with pytest.raises(DamagedSessionSaveError):
            model.save_external_document(merged, str(pdf))
    finally:
        merged.close()
    assert _file_digest(pdf) == before
    # GUARD: an export to a new file still works
    out = tmp_path / "exported.pdf"
    model.export_pages([1], str(out), as_image=False)
    assert out.exists()


def test_damaged_session_optimize_copy_never_targets_the_original_after_a_save_as(
    damaged_launch, tmp_path
) -> None:
    from model import pdf_optimizer

    model, _view, controller, errors, pdf = damaged_launch
    before = _file_digest(pdf)
    controller.save_as(str(tmp_path / "kept_copy.pdf"))
    assert errors == []
    sid = model.get_active_session_id()
    with pytest.raises(Exception, match="另存|新的檔名"):
        model.save_optimized_copy(str(pdf), session_id=sid)
    # the worker path (snapshot captured on the GUI thread, written off it)
    snapshot = pdf_optimizer.capture_optimize_source(model, sid)
    with pytest.raises(Exception, match="另存|新的檔名"):
        pdf_optimizer.save_optimized_copy_from_snapshot(model, snapshot, str(pdf))
    assert _file_digest(pdf) == before


def test_damaged_lost_session_recovery_copy_never_targets_the_original(
    damaged_launch, tmp_path
) -> None:
    from model.pdf_model import DamagedSessionSaveError, SaveRecoveryError

    model, _view, controller, errors, pdf = damaged_launch
    before = _file_digest(pdf)
    controller.save_as(str(tmp_path / "kept_copy.pdf"))
    assert errors == []
    recovery = tmp_path / "recovery.pdf"
    model.doc.save(str(recovery))
    model._mark_session_lost(
        SaveRecoveryError("lost", recovery_path=recovery, target_written=False)
    )
    with pytest.raises(DamagedSessionSaveError):
        model.copy_lost_session_recovery(str(pdf))
    assert _file_digest(pdf) == before


def test_damaged_session_keeps_the_original_protected_across_a_tab_detach(
    damaged_launch, tmp_path
) -> None:
    from controller.session_transfer import SessionTransferPayload
    from model.pdf_model import DamagedSessionSaveError

    model, _view, controller, errors, pdf = damaged_launch
    before = _file_digest(pdf)
    controller.save_as(str(tmp_path / "kept_copy.pdf"))
    assert errors == []
    sid = model.get_active_session_id()
    payload = SessionTransferPayload.from_model(
        model, sid, current_page=0, scale=1.0, color_profile="srgb"
    )
    receiver = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        receiver.import_session_transfer(payload)
        with pytest.raises(DamagedSessionSaveError):
            receiver.save_as(str(pdf))
        receiver.save_as(str(tmp_path / "receiver_copy.pdf"))
        with pytest.raises(DamagedSessionSaveError):
            receiver.save_as(str(pdf))
        assert _file_digest(pdf) == before
    finally:
        receiver.close()


def test_damaged_session_save_on_close_never_writes_the_original(
    damaged_launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    model, _view, controller, errors, pdf = damaged_launch
    offered: list[str] = []

    def _cancelled_dialog(_parent, _title, default_path, _filter):
        offered.append(str(default_path))
        return "", ""

    monkeypatch.setattr(pdf_controller_module.QFileDialog, "getSaveFileName", _cancelled_dialog)
    before = _file_digest(pdf)
    sid = model.get_active_session_id()
    assert controller._save_session_for_close(sid) is False
    assert controller.save_and_close() is False
    assert _file_digest(pdf) == before
    assert offered, "the Save As dialog is offered after the explanation"
    assert errors and all("另存新檔" in e for e in errors), errors


def test_damaged_session_save_dialog_pointed_at_the_original_is_refused(
    damaged_launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    model, _view, controller, errors, pdf = damaged_launch
    monkeypatch.setattr(
        pdf_controller_module.QFileDialog,
        "getSaveFileName",
        lambda *_a, **_k: (str(pdf), ""),
    )
    before = _file_digest(pdf)
    assert controller._save_session_with_dialog(model.get_active_session_id()) is False
    assert _file_digest(pdf) == before
    assert errors and "另存新檔" in errors[-1]


def test_an_undamaged_session_still_saves_in_place(qapp, tmp_path, monkeypatch) -> None:
    """GUARD: the gate only bites a damaged session."""
    model, view, controller, errors = _launch(tmp_path, monkeypatch, engine="legacy")
    try:
        monkeypatch.setattr(
            pdf_controller_module.QMessageBox, "information", staticmethod(lambda *a, **k: None)
        )
        assert model.session_damaged is False
        controller.save()
        assert errors == []
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_the_damage_travels_with_a_detached_tab(damaged_launch) -> None:
    from controller.session_transfer import SessionTransferPayload
    from model.pdf_model import DamagedSessionSaveError

    model, _view, _controller, _errors, pdf = damaged_launch
    sid = model.get_active_session_id()
    payload = SessionTransferPayload.from_model(
        model, sid, current_page=0, scale=1.0, color_profile="srgb"
    )
    assert payload.damaged is True
    receiver = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        new_sid = receiver.import_session_transfer(payload)
        assert receiver.is_session_damaged(new_sid) is True
        before = _file_digest(pdf)
        with pytest.raises(DamagedSessionSaveError):
            receiver.save_as(str(pdf))
        assert _file_digest(pdf) == before
    finally:
        receiver.close()


def test_a_clean_payload_stays_undamaged(qapp, tmp_path, monkeypatch) -> None:
    from controller.session_transfer import SessionTransferPayload

    model, view, _controller, _errors = _launch(tmp_path, monkeypatch, engine="legacy")
    try:
        payload = SessionTransferPayload.from_model(
            model, model.get_active_session_id(), current_page=0, scale=1.0, color_profile="srgb"
        )
        assert payload.damaged is False
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_a_failed_structural_rollback_latches_the_session_damaged(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same bug class: ``delete_pages`` fails mid-way and its snapshot restore
    fails too -- the document is whatever the failed operation left."""
    from model.pdf_model import DamagedSessionSaveError

    rebuild_model.insert_blank_page(2)

    def _fail(*_a, **_k):
        raise RuntimeError("shift failed")

    def _no_restore(_snapshot):
        raise RuntimeError("restore failed")

    monkeypatch.setattr(rebuild_model.block_manager, "shift_after_delete", _fail)
    monkeypatch.setattr(rebuild_model, "_restore_doc_from_snapshot", _no_restore)
    assert rebuild_model.session_damaged is False
    with pytest.raises(RuntimeError, match="restore failed"):
        rebuild_model.delete_pages([2])
    assert rebuild_model.session_damaged is True
    with pytest.raises(DamagedSessionSaveError):
        rebuild_model.save_as(str(rebuild_model.original_path))


def test_a_structural_rollback_that_succeeds_does_not_latch_damaged(
    rebuild_model: PDFModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    rebuild_model.insert_blank_page(2)

    def _fail(*_a, **_k):
        raise RuntimeError("shift failed")

    monkeypatch.setattr(rebuild_model.block_manager, "shift_after_delete", _fail)
    with pytest.raises(RuntimeError, match="shift failed"):
        rebuild_model.delete_pages([2])
    assert rebuild_model.session_damaged is False


# --------- F13-MOVE-1a: the cross-page move's message follows ITS OWN restore
#
# ``move_text_across_pages`` restores the WHOLE document from the snapshot it
# captured before the source deletion.  When that restore succeeds the page is
# intact whatever the model's inner rollback did, so the do-not-save/reopen
# sentence (and the model's damaged latch) would be false: a user obeying it
# loses every other unsaved edit of a healthy document.  When the restore
# itself fails the document really is untrusted, whatever the original error.

_MOVE_CALL = dict(
    source_page=1,
    source_rect=fitz.Rect(72, 90, 200, 110),
    destination_page=2,
    destination_rect=fitz.Rect(60, 60, 220, 110),
    new_text="MOVED",
    font="helv",
    size=12,
    color=(0.0, 0.0, 0.0),
    original_text=TARGET,
    target_span_id=None,
    target_mode="run",
    allow_rebuild=True,
)


@pytest.fixture
def move_launch(qapp, tmp_path, monkeypatch):
    """A legacy-engine session with a second page; the move's source-deletion
    rewrite half-writes the page and the model's own page rollback fails."""
    model, view, controller, errors = _launch(tmp_path, monkeypatch, engine="legacy")
    monkeypatch.setattr(
        pdf_controller_module.QMessageBox, "information", staticmethod(lambda *a, **k: None)
    )
    monkeypatch.setattr(pdf_controller_module, "confirm_degraded_fallback", lambda *_a: True)
    monkeypatch.setattr(controller, "_confirm_legacy_fallback", lambda _chain: True)
    monkeypatch.setattr(
        controller, "_resolve_cross_page_move_source_span_id", lambda **_k: "p0_b0_l0_s0"
    )
    model.ensure_page_index_built(1)
    model.doc.new_page(width=595, height=842)
    before_text = model.doc[0].get_text()
    monkeypatch.setattr(model, "_apply_redact_insert", _half_rewrite)
    monkeypatch.setattr(pdf_text_edit, "_rollback_rebuild_page", _rollback_cannot_restore)
    try:
        yield model, view, controller, errors, before_text
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_a_move_whose_document_restore_succeeded_does_not_say_the_page_is_damaged(
    move_launch,
) -> None:
    model, _view, controller, errors, before_text = move_launch
    controller.move_text_across_pages(**_MOVE_CALL)
    assert model.doc[0].get_text() == before_text and "HALF-WRITTEN" not in model.doc[0].get_text()
    assert errors, "the failure must reach the user"
    assert errors[-1].startswith("跨頁移動文字沒有完成。")
    assert "請不要儲存" not in errors[-1] and "重新開啟" not in errors[-1]
    assert refusal_message(TextEditRefusal.EDIT_FAILED) in errors[-1]  # intact: "page restored"
    assert not LATIN.search(errors[-1])


def test_a_move_whose_document_restore_succeeded_clears_the_damaged_latch(move_launch) -> None:
    """The model latched the session at its ROLLBACK_FAILED raise; the
    controller's whole-document restore repaired it, so in-place Save works."""
    model, _view, controller, errors, _before = move_launch
    pdf = Path(model.original_path)
    controller.move_text_across_pages(**_MOVE_CALL)
    assert model.session_damaged is False
    assert len(model.command_manager._undo_stack) == 0
    errors.clear()
    controller.save()
    assert errors == [], errors
    assert "HALF-WRITTEN" not in _text_on_disk(pdf)


def test_a_move_whose_document_restore_failed_says_do_not_save_and_stays_damaged(
    move_launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    model, _view, controller, errors, _before = move_launch

    def _no_restore(*_a, **_k):
        raise RuntimeError("snapshot restore failed")

    monkeypatch.setattr(model, "replace_active_document_from_snapshot", _no_restore)
    controller.move_text_across_pages(**_MOVE_CALL)
    assert errors and errors[-1].startswith("跨頁移動文字沒有完成。")
    assert refusal_message(TextEditRefusal.ROLLBACK_FAILED) in errors[-1]
    assert model.session_damaged is True


def test_a_move_failure_whose_restore_failed_latches_damaged_whatever_the_error(
    move_launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inverse of the finding: an ordinary refusal ("page restored") followed
    by a restore that fails is NOT restored -- the sentence and the latch
    follow the restore, not the original error."""
    model, _view, controller, errors, _before = move_launch

    def _refuse(*_a, **_k):
        raise TextEditRefused(TextEditRefusal.VERIFICATION_FAILED, DETAIL)

    def _no_restore(*_a, **_k):
        raise RuntimeError("snapshot restore failed")

    monkeypatch.setattr(model, "edit_text", _refuse)
    monkeypatch.setattr(model, "replace_active_document_from_snapshot", _no_restore)
    assert model.session_damaged is False
    controller.move_text_across_pages(**_MOVE_CALL)
    assert refusal_message(TextEditRefusal.ROLLBACK_FAILED) in errors[-1]
    assert refusal_message(TextEditRefusal.VERIFICATION_FAILED) not in errors[-1]
    assert model.session_damaged is True


def test_a_move_failure_with_a_good_restore_keeps_its_own_coded_sentence(
    move_launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GUARD: only ROLLBACK_FAILED is re-judged by the restore outcome."""
    model, _view, controller, errors, _before = move_launch

    def _refuse(*_a, **_k):
        raise TextEditRefused(TextEditRefusal.VERIFICATION_FAILED, DETAIL)

    monkeypatch.setattr(model, "edit_text", _refuse)
    controller.move_text_across_pages(**_MOVE_CALL)
    assert refusal_message(TextEditRefusal.VERIFICATION_FAILED) in errors[-1]
    assert model.session_damaged is False


def test_a_move_restore_does_not_heal_a_session_that_was_already_damaged(move_launch) -> None:
    """The latch may only be lifted for damage THIS move caused; a session
    damaged earlier stays damaged (its snapshot already contains the damage)."""
    model, _view, controller, errors, _before = move_launch
    model.mark_session_damaged("an earlier failed edit")
    controller.move_text_across_pages(**_MOVE_CALL)
    assert model.session_damaged is True
    assert errors and refusal_message(TextEditRefusal.EDIT_FAILED) in errors[-1]


@pytest.mark.parametrize("restored", [True, False, None], ids=["restored", "failed", "none"])
def test_user_message_follows_the_restore_outcome(restored) -> None:
    rolled = TextEditRefused(TextEditRefusal.ROLLBACK_FAILED, DETAIL)
    other = TextEditRefused(TextEditRefusal.VERIFICATION_FAILED, DETAIL)
    plain = UserFacingEditError("原始文字刪除未完成，已取消跨頁移動。")
    damaged = refusal_message(TextEditRefusal.ROLLBACK_FAILED)
    intact = refusal_message(TextEditRefusal.EDIT_FAILED)
    kw = dict(cross_page_move=True, document_restored=restored)
    if restored is True:
        assert user_message_for_exception(rolled, **kw) == intact
        assert user_message_for_exception(other, **kw) == refusal_message(
            TextEditRefusal.VERIFICATION_FAILED
        )
        assert user_message_for_exception(plain, **kw) == str(plain)
    elif restored is False:
        for exc in (rolled, other, plain, RuntimeError("x")):
            assert user_message_for_exception(exc, **kw) == damaged
    else:
        assert user_message_for_exception(rolled, **kw) == damaged
        assert user_message_for_exception(other, **kw) == refusal_message(
            TextEditRefusal.VERIFICATION_FAILED
        )


# --------- F13-MOVE-1b: source deleted, destination add failed, restore failed
#
# The exact reproduced state: the source deletion (a direct model call, outside
# any command) really removed the text, the destination ``add_textbox`` raised
# and the whole-document restore raised as well.  The document then holds the
# deletion with no undo entry and no dirty mark, so the ONLY things standing
# between the user and a silent loss are the do-not-save sentence and the
# damaged latch that blocks every in-place write.  (The close prompt stays
# quiet on purpose: the sentence already says "close without saving", and a
# Save/Discard prompt whose Save is refused would be noise.)


@pytest.fixture
def move_lost_source_launch(qapp, tmp_path, monkeypatch):
    model, view, controller, errors = _launch(tmp_path, monkeypatch, engine="legacy")
    monkeypatch.setattr(
        pdf_controller_module.QMessageBox, "information", staticmethod(lambda *a, **k: None)
    )
    monkeypatch.setattr(pdf_controller_module, "confirm_degraded_fallback", lambda *_a: True)
    monkeypatch.setattr(controller, "_confirm_legacy_fallback", lambda _chain: True)
    monkeypatch.setattr(
        controller, "_resolve_cross_page_move_source_span_id", lambda **_k: "p0_b0_l0_s0"
    )
    model.ensure_page_index_built(1)
    model.doc.new_page(width=595, height=842)

    def _add_fails(*_a, **_k):
        raise RuntimeError("add_textbox failed")

    def _restore_fails(*_a, **_k):
        raise RuntimeError("snapshot restore failed")

    monkeypatch.setattr(model, "add_textbox", _add_fails)
    monkeypatch.setattr(model, "replace_active_document_from_snapshot", _restore_fails)
    pdf = Path(model.original_path)
    try:
        yield model, view, controller, errors, pdf
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_a_lost_source_with_a_failed_restore_says_do_not_save_not_try_again(
    move_lost_source_launch,
) -> None:
    model, _view, controller, errors, _pdf = move_lost_source_launch
    controller.move_text_across_pages(**_MOVE_CALL)
    assert TARGET not in model.doc[0].get_text(), "the source deletion really happened"
    assert errors and errors[-1].startswith("跨頁移動文字沒有完成。")
    assert refusal_message(TextEditRefusal.ROLLBACK_FAILED) in errors[-1]
    assert GENERIC_REFUSAL_MESSAGE not in errors[-1], "'try again' would delete the next block"
    assert model.session_damaged is True
    assert len(model.command_manager._undo_stack) == 0


def test_a_lost_source_with_a_failed_restore_cannot_be_saved_over_the_original(
    move_lost_source_launch,
) -> None:
    """The silent-persist path of the finding: a later Ctrl+S must not write
    the half-moved document over the user's file."""
    model, _view, controller, errors, pdf = move_lost_source_launch
    before = _file_digest(pdf)
    controller.move_text_across_pages(**_MOVE_CALL)
    errors.clear()
    controller.save()
    assert _file_digest(pdf) == before, "the original must not be overwritten"
    assert TARGET in _text_on_disk(pdf)
    assert len(errors) == 1 and "另存新檔" in errors[0] and "關閉" in errors[0], errors


# ------------------------------- S17-DRAG-GUARD (TODOS F13-VF-4c): place anyway
# A dragged box that would print over untouched text is refused by the Model
# with ``DRAGGED_BOX_OVERPRINTS``; the Controller offers, for that one edit,
# to place it anyway (neither cap nor guard) or cancel.  No global setting.

_DG_NEXT = "NEXT"


def _drag_guard_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    next_x = 72.0 + fitz.Font("helv").text_length("ab", fontsize=14)
    page.insert_text((72.0, 700.0), "ab", fontsize=14, fontname="helv")
    page.insert_text((next_x, 700.0), _DG_NEXT, fontsize=10, fontname="helv", color=(1, 0, 0))
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _launch_drag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pdf = _drag_guard_pdf(tmp_path / "drag_guard.pdf")
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(pdf))
    monkeypatch.setattr(controller, "show_page", lambda _page: None)
    monkeypatch.setattr(
        controller, "_invalidate_active_render_state", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(controller, "_invalidate_thumbnails", lambda *a, **k: None)
    monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)
    monkeypatch.setattr(view, "capture_viewport_anchor", lambda: None)
    errors: list[str] = []
    monkeypatch.setattr(
        pdf_controller_module, "show_error", lambda _view, message: errors.append(str(message))
    )
    asked: dict[str, list] = {"rebuild": [], "anyway": []}
    return model, view, controller, errors, asked


def _drag_request(model: PDFModel, *, dx: float = 20.0, **extra) -> EditTextRequest:
    model.ensure_page_index_built(1)
    run = next(r for r in model.block_manager.get_runs(0) if r.text == "ab")
    return EditTextRequest(
        page=1,
        rect=fitz.Rect(run.bbox),
        new_text="abc",
        font="helv",
        size=14.0,
        color=(0.0, 0.0, 0.0),
        original_text="ab",
        new_rect=fitz.Rect(run.bbox) + (dx, 0.0, dx, 0.0),
        target_span_id=run.span_id,
        target_mode="run",
        allow_rebuild=True,
        **extra,
    )


def _page_spans(model: PDFModel) -> list[tuple[str, tuple[float, ...]]]:
    return sorted(
        (span["text"].strip(), tuple(round(v, 2) for v in span["bbox"]))
        for block in model.doc[0].get_text("dict")["blocks"]
        for line in block.get("lines", ())
        for span in line["spans"]
        if span["text"].strip()
    )


def test_dragged_refusal_zh_tw_sentence_names_the_choice() -> None:
    text = refusal_message(TextEditRefusal.DRAGGED_BOX_OVERPRINTS)
    assert "仍要放在這裡" in text and "取消" in text
    assert not LATIN.search(text)
    assert text != refusal_message(TextEditRefusal.TEXT_DOES_NOT_FIT)


def test_dragged_refusal_place_anyway_yes_commits_the_drop_with_one_rebuild_consent(
    qapp, tmp_path, monkeypatch
) -> None:
    model, view, controller, errors, asked = _launch_drag(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(
            pdf_controller_module,
            "confirm_degraded_fallback",
            lambda _view, message: asked["rebuild"].append(message) or True,
        )
        monkeypatch.setattr(
            pdf_controller_module,
            "confirm_place_anyway",
            lambda _view, message: asked["anyway"].append(message) or True,
        )
        controller.edit_text(_drag_request(model))
        assert errors == [], "the choice replaces the refusal dialog"
        assert len(asked["anyway"]) == 1
        assert asked["anyway"][0] == refusal_message(TextEditRefusal.DRAGGED_BOX_OVERPRINTS)
        assert len(asked["rebuild"]) == 1, "the rebuild consent is replayed, not asked twice"
        assert controller.consume_last_edit_result() is EditTextResult.SUCCESS
        spans = dict(_page_spans(model))
        edited, neighbour = fitz.Rect(spans["abc"]), fitz.Rect(spans[_DG_NEXT])
        assert (edited & neighbour).get_area() > 20.0, "placed where the user dropped it"
        assert len(model.command_manager._undo_stack) == 1
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_dragged_refusal_place_anyway_cancel_leaves_the_page_and_history_untouched(
    qapp, tmp_path, monkeypatch
) -> None:
    model, view, controller, errors, asked = _launch_drag(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(pdf_controller_module, "confirm_degraded_fallback", lambda *_a: True)
        monkeypatch.setattr(
            pdf_controller_module,
            "confirm_place_anyway",
            lambda _view, message: asked["anyway"].append(message) or False,
        )
        before = _page_spans(model)
        controller.edit_text(_drag_request(model))
        assert len(asked["anyway"]) == 1
        assert errors == [], "a cancel is the user's own choice, not an error"
        assert _page_spans(model) == before
        assert model.command_manager._undo_stack == []
        # Not SUCCESS: the View keeps the editor open with the user's text.
        assert controller.consume_last_edit_result() is not EditTextResult.SUCCESS
    finally:
        model.close()
        view.close()
        qapp.processEvents()


def test_an_in_place_edit_is_never_offered_place_anyway(
    qapp, tmp_path, monkeypatch
) -> None:
    """Only a dragged box has the choice: the same code raised for a request
    with no ``new_rect`` shows the plain refusal sentence."""
    model, view, controller, errors, asked = _launch_drag(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(
            pdf_controller_module,
            "confirm_place_anyway",
            lambda _view, message: asked["anyway"].append(message) or True,
        )

        def _refuse(_cmd):
            raise TextEditRefused(TextEditRefusal.DRAGGED_BOX_OVERPRINTS, DETAIL)

        monkeypatch.setattr(model.command_manager, "execute", _refuse)
        request = _drag_request(model)
        controller.edit_text(
            EditTextRequest(**{**request.__dict__, "new_rect": None})
        )
        assert asked["anyway"] == []
        assert errors == [refusal_message(TextEditRefusal.DRAGGED_BOX_OVERPRINTS)]
    finally:
        model.close()
        view.close()
        qapp.processEvents()
