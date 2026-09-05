"""Red-light tests for the Task 16 T16-3 review round: what the *shipped*
default engine (``"tiered"``, non-strict, ``max_tier=0``) actually does to a
user.

The default flip (``ed55b35``) made three previously-dead ``engine ==
"tiered"`` branches live at once, and the suite that went green around it
never drove any of them end to end under the shipped configuration:

1. ``PDFModel.edit_text``'s signed/widget-page hard reject returns
   ``REJECTED_UNSUPPORTED`` with zero mutation -- intended -- but the
   Controller had no message for that result, so the edit vanished silently.
2. That same hard reject failed **open** when its probe raised, degrading a
   widget page to redact+reinsert -- the exact opposite of the fail-closed
   contract stated in its own comment -- and its ``except`` tuple could not
   see MuPDF's own error class.
3. The P0-C pre-commit consent modal fired on essentially *every* ordinary
   edit (measured 12/12 across three real fixtures), not just on cross-page
   moves, because under ``max_tier=0`` a Tier 0 refusal plus a legacy
   fallback is the common path. T16-3 was accepted on the premise that a
   non-strict fallback is *silent* and the T16-1 degrade notice is what
   surfaces it, so the modal is now opt-in
   (``TextCommitSettings.confirm_degrade``).

Fixtures are synthetic (data policy) -- no corpus text reaches this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.pdf_controller import PDFController  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.edit_requests import EditTextRequest  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import CommitStatus, TextCommitSettings  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    page_fingerprint,
    page_has_widgets_or_signatures,
)
from view.pdf_view import PDFView  # noqa: E402

TARGET = "Hello World"
REPLACEMENT = "Hallo World"


# ---------------------------------------------------------------- fixtures


def _write_widget_pdf(path: Path) -> Path:
    """One page holding ordinary text plus one form text widget."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 200), TARGET, fontname="helv", fontsize=12.0)
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "field_a"
    widget.rect = fitz.Rect(72, 400, 272, 425)
    widget.field_value = ""
    page.add_widget(widget)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _write_plain_pdf(path: Path) -> Path:
    """One page of ordinary text, no widgets, no signature flags."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 200), TARGET, fontname="helv", fontsize=12.0)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _open(path: Path, settings: TextCommitSettings | None = None) -> PDFModel:
    model = PDFModel() if settings is None else PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _target_block(model: PDFModel, probe: str = TARGET):
    return next(b for b in model.block_manager.get_blocks(0) if probe in (b.text or ""))


class _ConfirmSpy:
    def __init__(self, answer: bool = True) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.answer = answer

    def __call__(self, chain: tuple[str, ...]) -> bool:
        self.calls.append(chain)
        return self.answer


def _launch(path: Path, settings: TextCommitSettings | None, monkeypatch):
    model = PDFModel() if settings is None else PDFModel(text_commit_settings=settings)
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(path))
    monkeypatch.setattr(controller, "show_page", lambda _page: None)
    monkeypatch.setattr(
        controller,
        "_invalidate_active_render_state",
        lambda *args, **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(controller, "_update_undo_redo_tooltips", lambda: None)
    monkeypatch.setattr(view, "capture_viewport_anchor", lambda: None)
    return model, view, controller


def _teardown(model: PDFModel, view: PDFView, qapp) -> None:
    model.close()
    view.close()
    qapp.processEvents()


def _edit_via_signal(model: PDFModel, view: PDFView, probe: str, new_text: str) -> None:
    """Drive the edit through the production wiring: the View's
    ``sig_edit_text`` signal into ``PDFController.edit_text``."""
    model.ensure_page_index_built(1)
    block = _target_block(model, probe)
    view.sig_edit_text.emit(
        EditTextRequest(
            page=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=new_text,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
        )
    )


# ------------------------------------------- the probe itself, fail-closed


def test_widget_probe_fails_closed_when_page_widgets_raises(tmp_path, monkeypatch):
    """RED: ``page_has_widgets_or_signatures`` documents itself as "refuse
    rather than guess", but only the ``get_sigflags()`` half sat inside a
    ``try``; ``page.widgets()`` was outside it, so an unreadable /Annots
    array escaped to the caller instead of answering True."""
    path = _write_plain_pdf(tmp_path / "plain.pdf")
    doc = fitz.open(str(path))
    try:

        def _boom(*_args, **_kwargs):
            raise RuntimeError("unreadable /Annots")

        monkeypatch.setattr(fitz.Page, "widgets", _boom, raising=False)
        assert page_has_widgets_or_signatures(doc, doc[0]) is True
    finally:
        doc.close()


def test_widget_probe_fails_closed_on_a_mupdf_error(tmp_path, monkeypatch):
    """RED: ``fitz.mupdf.FzErrorBase`` derives from ``Exception``, NOT from
    ``RuntimeError`` (verified MRO), so a real MuPDF failure on a malformed
    AcroForm slipped past a ``(RuntimeError, ValueError)`` handler entirely.
    ``_page_contents_xrefs`` in the same module already catches it."""
    path = _write_plain_pdf(tmp_path / "plain.pdf")
    doc = fitz.open(str(path))
    try:

        def _boom(*_args, **_kwargs):
            raise fitz.mupdf.FzErrorBase(0, "malformed AcroForm")

        monkeypatch.setattr(fitz.Page, "widgets", _boom, raising=False)
        assert page_has_widgets_or_signatures(doc, doc[0]) is True
    finally:
        doc.close()


def test_sigflags_probe_still_fails_closed(tmp_path, monkeypatch):
    """PIN: the pre-existing fail-closed half must not regress while the
    widgets half is being moved inside the same guard."""
    path = _write_plain_pdf(tmp_path / "plain.pdf")
    doc = fitz.open(str(path))
    try:

        def _boom(*_args, **_kwargs):
            raise ValueError("unreadable AcroForm")

        monkeypatch.setattr(fitz.Document, "get_sigflags", _boom, raising=False)
        assert page_has_widgets_or_signatures(doc, doc[0]) is True
    finally:
        doc.close()


# ------------------------------------------- the Model-side hard reject


def test_widget_page_edit_rejects_with_zero_mutation(tmp_path):
    """PIN (T16-3 known intended delta): under the shipped default a page
    carrying a form widget refuses the edit outright instead of degrading to
    redact+reinsert. Zero mutation means all of: the refusal result code, the
    same page bytes, no undo entry, and no ``edit_count`` bump."""
    path = _write_widget_pdf(tmp_path / "widget.pdf")
    model = _open(path)
    try:
        assert model.text_commit_settings.engine == "tiered"
        block = _target_block(model)
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        undo_before = model.command_manager.undo_count
        edits_before = model.edit_count

        result = model.edit_text(
            1, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )

        assert result is EditTextResult.REJECTED_UNSUPPORTED
        assert TARGET in model.doc[0].get_text()
        assert REPLACEMENT not in model.doc[0].get_text()
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert model.command_manager.undo_count == undo_before
        assert model.edit_count == edits_before
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.REJECTED
    finally:
        model.close()


def test_signed_document_edit_rejects_with_zero_mutation(tmp_path, monkeypatch):
    """PIN: the /SigFlags > 0 half of the same boundary. The flag is forced
    through ``get_sigflags`` rather than by writing a real signature, so the
    fixture stays synthetic and the assertion stays about the boundary."""
    path = _write_plain_pdf(tmp_path / "signed.pdf")
    model = _open(path)
    try:
        monkeypatch.setattr(
            fitz.Document, "get_sigflags", lambda _self: 3, raising=False
        )
        block = _target_block(model)
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])

        result = model.edit_text(
            1, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )

        assert result is EditTextResult.REJECTED_UNSUPPORTED
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert TARGET in model.doc[0].get_text()
    finally:
        model.close()


def test_hard_reject_fails_closed_when_the_probe_raises(tmp_path, monkeypatch):
    """RED: the call site turned a raising probe into ``hard_reject = False``
    -- "the probe blew up, so assume no widgets, so run the legacy mutation"
    -- inverting the fail-closed contract its own comment states."""
    path = _write_widget_pdf(tmp_path / "widget.pdf")
    model = _open(path)
    try:
        import model.pdf_model as pdf_model_module

        def _boom(*_args, **_kwargs):
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(pdf_model_module, "page_has_widgets_or_signatures", _boom)
        block = _target_block(model)
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])

        result = model.edit_text(
            1, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )

        assert result is EditTextResult.REJECTED_UNSUPPORTED
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert REPLACEMENT not in model.doc[0].get_text()
    finally:
        model.close()


def test_hard_reject_fails_closed_on_a_mupdf_probe_error(tmp_path, monkeypatch):
    """RED: ``FzErrorBase`` is not a ``RuntimeError``, so before this fix the
    exception unwound out of ``PDFModel.edit_text`` entirely and was swallowed
    by the Controller's broad ``except Exception`` as a log line."""
    path = _write_widget_pdf(tmp_path / "widget.pdf")
    model = _open(path)
    try:
        import model.pdf_model as pdf_model_module

        def _boom(*_args, **_kwargs):
            raise fitz.mupdf.FzErrorBase(0, "probe exploded")

        monkeypatch.setattr(pdf_model_module, "page_has_widgets_or_signatures", _boom)
        block = _target_block(model)
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])

        result = model.edit_text(
            1, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )

        assert result is EditTextResult.REJECTED_UNSUPPORTED
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
    finally:
        model.close()


def test_legacy_kill_switch_still_edits_a_widget_page(tmp_path):
    """PIN: the hard reject is gated on ``engine == "tiered"``, so the kill
    switch stays a real escape hatch for a user blocked by a form page."""
    path = _write_widget_pdf(tmp_path / "widget.pdf")
    model = _open(path, TextCommitSettings(engine="legacy"))
    try:
        block = _target_block(model)
        result = model.edit_text(
            1, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )
        assert result is EditTextResult.SUCCESS
    finally:
        model.close()


# ------------------------------------------- what the user is actually told


def test_rejected_unsupported_has_a_user_facing_message():
    """RED: every other non-SUCCESS result the same-page edit path can return
    has a message; ``REJECTED_UNSUPPORTED`` fell through to ``None``, and
    ``_show_edit_result_feedback`` early-returns on a falsy message, so the
    edit was discarded in total silence."""
    message = PDFController._edit_result_to_message(
        None, EditTextResult.REJECTED_UNSUPPORTED
    )
    assert message
    assert isinstance(message, str)


def test_widget_page_edit_tells_the_user_why_nothing_happened(
    qapp, tmp_path, monkeypatch
):
    """RED: end to end through the production wiring (View signal ->
    Controller -> Model). A refused edit must produce exactly one error
    surface, and the document must still be untouched afterwards."""
    path = _write_widget_pdf(tmp_path / "widget.pdf")
    model, view, controller = _launch(path, None, monkeypatch)
    try:
        toasts: list[tuple[str, str]] = []
        monkeypatch.setattr(
            view,
            "_show_toast",
            lambda message, duration_ms=2500, tone="info": toasts.append(
                (str(message), str(tone))
            ),
            raising=False,
        )
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(toasts) == 1, f"expected exactly one error toast, got {toasts}"
        assert toasts[0][1] == "error"
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert (
            controller.consume_last_edit_result() is EditTextResult.REJECTED_UNSUPPORTED
        )
    finally:
        _teardown(model, view, qapp)


# ------------------------------------------- the consent modal, now opt-in


def test_shipped_default_never_prompts_for_consent(qapp, tmp_path, monkeypatch):
    """RED: measured 12/12 ordinary edits prompting under the shipped default
    before this fix. T16-3 was accepted on the premise that a non-strict
    fallback is silent and the T16-1 degrade notice is what makes it visible
    -- so the edit must commit, and notify, without a blocking modal."""
    path = _write_plain_pdf(tmp_path / "plain.pdf")
    model, view, controller = _launch(path, None, monkeypatch)
    try:
        assert model.text_commit_settings.confirm_degrade is False
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)
        notices: list[str] = []
        monkeypatch.setattr(
            view,
            "notify_degraded_commit",
            lambda message: notices.append(str(message)),
            raising=False,
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == [], f"shipped default must not prompt, got {spy.calls}"
        assert REPLACEMENT in model.doc[0].get_text()
        assert len(notices) == 1, f"expected exactly one degrade notice, got {notices}"
    finally:
        _teardown(model, view, qapp)


def test_confirm_degrade_opt_in_restores_the_consent_prompt(
    qapp, tmp_path, monkeypatch
):
    """RED: the P0-C gate is not deleted, only demoted to an opt-in --
    ``confirm_degrade=True`` must still pause before the legacy mutation."""
    path = _write_plain_pdf(tmp_path / "plain.pdf")
    model, view, controller = _launch(
        path, TextCommitSettings(confirm_degrade=True), monkeypatch
    )
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert len(spy.calls) == 1
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        _teardown(model, view, qapp)


def test_confirm_degrade_opt_in_decline_is_still_zero_mutation(
    qapp, tmp_path, monkeypatch
):
    """RED: declining under the opt-in keeps the Task 12 P0-C contract --
    no bytes changed, no undo entry, no outcome recorded."""
    path = _write_plain_pdf(tmp_path / "plain.pdf")
    model, view, controller = _launch(
        path, TextCommitSettings(confirm_degrade=True), monkeypatch
    )
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        undo_before = model.command_manager.undo_count
        monkeypatch.setattr(
            controller, "_confirm_legacy_fallback", _ConfirmSpy(answer=False)
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert model.command_manager.undo_count == undo_before
        assert model.last_commit_outcome is None
    finally:
        _teardown(model, view, qapp)


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_kill_switch_and_default_agree_on_the_final_text(tmp_path, engine):
    """PIN: whatever the engine, an ordinary non-widget edit must land the
    same visible text -- the flip changes fidelity and reporting, never the
    user's typed content."""
    path = _write_plain_pdf(tmp_path / f"plain_{engine}.pdf")
    model = _open(path, TextCommitSettings(engine=engine))
    try:
        block = _target_block(model)
        result = model.edit_text(
            1, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )
        assert result is EditTextResult.SUCCESS
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        model.close()
