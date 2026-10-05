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
   fallback is the common path. T16-3 made the modal an opt-in
   (``TextCommitSettings.confirm_degrade``). UI step 7 (owner decision
   2026-09-30) retired that opt-in AND the silent fallback: a Tier 0
   refusal is now final (``EditTextResult.REJECTED``) unless the request
   carries the explicit rebuild consent (``allow_rebuild``), which alone
   reaches the modal.

Fixtures are synthetic (data policy) -- no corpus text reaches this file.
"""

from __future__ import annotations

import re
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


def _write_legacy_only_pdf(path: Path) -> Path:
    """:func:`_write_plain_pdf`'s page, respelled so Tier 0 still refuses it.

    ``insert_text`` writes a SINGLE-item ``[<hex>] TJ``, which T16-4X S1
    admits — the three degrade/consent tests below would then commit at
    Tier 0 and never reach the legacy fallback whose behaviour they exist
    to pin. Splitting the SAME hex codes across two array items keeps the
    page ordinary (same glyphs, same origin, same font) and keeps the
    refusal, now ``tj_multi_item_array``.
    """
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 200), TARGET, fontname="helv", fontsize=12.0)
        xref = page.get_contents()[0]

        def _split(match: "re.Match[bytes]") -> bytes:
            digits = match.group(1)
            cut = (len(digits) // 4) * 2 or 2
            return b"[<" + digits[:cut] + b"> <" + digits[cut:] + b">] TJ"

        rewritten, count = re.subn(
            rb"\[<([0-9A-Fa-f]+)>\]\s*TJ", _split, doc.xref_stream(xref)
        )
        assert count == 1, f"expected one array TJ to split, found {count}"
        doc.update_stream(xref, rewritten)
        doc.save(str(path), garbage=0)
    finally:
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


def _edit_via_signal(
    model: PDFModel,
    view: PDFView,
    probe: str,
    new_text: str,
    *,
    allow_rebuild: bool = False,
) -> None:
    """Drive the edit through the production wiring: the View's
    ``sig_edit_text`` signal into ``PDFController.edit_text``.
    ``allow_rebuild`` is the explicit rebuild consent (UI step 7)."""
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
            allow_rebuild=allow_rebuild,
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


def test_shipped_default_never_prompts_and_never_falls_back(
    qapp, tmp_path, monkeypatch
):
    """POLICY PIN, rewritten in UI step 7 (owner decision 2026-09-30, "no
    silent legacy"). T16-3 pinned the opposite -- a silent legacy commit plus
    one degrade notice. Now an ordinary edit Tier 0 refuses is REFUSED under
    the shipped default: no modal, no legacy commit, no degrade notice, zero
    mutation, and one non-modal notice carrying the reason code."""
    path = _write_legacy_only_pdf(tmp_path / "plain.pdf")
    model, view, controller = _launch(path, None, monkeypatch)
    try:
        assert not hasattr(model.text_commit_settings, "confirm_degrade")
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)
        notices: list[str] = []
        monkeypatch.setattr(
            view,
            "notify_degraded_commit",
            lambda message: notices.append(str(message)),
            raising=False,
        )
        toasts: list[str] = []
        monkeypatch.setattr(
            view,
            "_show_toast",
            lambda message, **_k: toasts.append(str(message)),
            raising=False,
        )
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])

        _edit_via_signal(model, view, TARGET, REPLACEMENT)

        assert spy.calls == [], f"shipped default must not prompt, got {spy.calls}"
        assert controller.consume_last_edit_result() is EditTextResult.REJECTED
        assert page_fingerprint(model.doc, model.doc[0]) == fingerprint_before
        assert TARGET in model.doc[0].get_text()
        assert notices == [], f"a refusal is not a degraded commit, got {notices}"
        assert len(toasts) == 1 and "文件未變更" in toasts[0]
    finally:
        _teardown(model, view, qapp)


def test_explicit_rebuild_request_restores_the_consent_prompt(
    qapp, tmp_path, monkeypatch
):
    """The P0-C gate now hangs off the REQUEST's explicit rebuild consent
    (``allow_rebuild``; the retired ``confirm_degrade`` opt-in used to own
    it): it must still pause before the legacy mutation."""
    path = _write_legacy_only_pdf(tmp_path / "plain.pdf")
    model, view, controller = _launch(path, None, monkeypatch)
    try:
        spy = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", spy)

        _edit_via_signal(model, view, TARGET, REPLACEMENT, allow_rebuild=True)

        assert len(spy.calls) == 1
        assert REPLACEMENT in model.doc[0].get_text()
    finally:
        _teardown(model, view, qapp)


def test_explicit_rebuild_decline_is_still_zero_mutation(
    qapp, tmp_path, monkeypatch
):
    """Declining the explicit rebuild keeps the Task 12 P0-C contract --
    no bytes changed, no undo entry, no outcome recorded."""
    path = _write_legacy_only_pdf(tmp_path / "plain.pdf")
    model, view, controller = _launch(path, None, monkeypatch)
    try:
        fingerprint_before = page_fingerprint(model.doc, model.doc[0])
        undo_before = model.command_manager.undo_count
        monkeypatch.setattr(
            controller, "_confirm_legacy_fallback", _ConfirmSpy(answer=False)
        )

        _edit_via_signal(model, view, TARGET, REPLACEMENT, allow_rebuild=True)

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


# ==========================================================================
# Task 16 T16-3, review round 2
# ==========================================================================
#
# Two more surfaces the default flip made live that the round-1 sweep did not
# reach:
#
# 4. ``page_has_widgets_or_signatures`` answered the /SigFlags half with
#    ``sig_flags > 0``. ``/SigFlags`` declares that signature FIELDS EXIST,
#    it does not attest that any of them is signed -- PyMuPDF writes 3
#    (SignaturesExist|AppendOnly) for a bare, never-signed placeholder, which
#    is what Acrobat/Word put in every contract template. So under the
#    shipped default an unsigned form template became uneditable on EVERY
#    page, including pages with no field on them at all, and the message
#    round 1 added ("this page has form fields or the document is signed")
#    was false on both clauses in exactly that case.
# 5. Tier 0 patch-replay undo became live, and its ``STALE_UNDO`` refusal was
#    mute: ``PDFController.undo()`` discarded ``CommandManager.undo()``'s
#    bool and ``_edit_result_to_message`` had no branch for it -- the same
#    mute-failure class round 1 fixed for ``REJECTED_UNSUPPORTED``.


SECOND_TARGET = "Downstream line stays"
SECOND_REPLACEMENT = "Downstream line stayt"
_SIGNATURE_VALUE = (
    "<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/adbe.pkcs7.detached"
    "/ByteRange[0 0 0 0]/Contents<00>>>"
)


def _write_signature_template_pdf(path: Path, *, signed: bool = False) -> Path:
    """Page 1 carries ONE signature widget; page 2 carries only text.

    With ``signed=False`` the field is a never-signed placeholder -- exactly
    what a contract template ships as -- and PyMuPDF still writes
    ``/SigFlags 3``. With ``signed=True`` the field's ``/V`` is filled in so
    the document reads back as genuinely signed.
    """
    doc = fitz.open()
    page_one = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
    widget.field_name = "sig_a"
    widget.rect = fitz.Rect(72, 400, 272, 460)
    page_one.add_widget(widget)
    page_two = doc.new_page(width=595, height=842)
    page_two.insert_text((72, 200), TARGET, fontname="helv", fontsize=12.0)
    doc.save(str(path), garbage=0)
    doc.close()
    if not signed:
        return path
    doc = fitz.open(str(path))
    try:
        sig_xref = next(
            w.xref
            for w in doc[0].widgets()
            if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE
        )
        doc.xref_set_key(sig_xref, "V", _SIGNATURE_VALUE)
        doc.save(str(path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    finally:
        doc.close()
    return path


def _write_two_line_stream_pdf(path: Path) -> Path:
    """A hand-built page whose two lines are two separate literal ``Tj`` ops.

    The first line is Tier 0 eligible (single literal show op); committing the
    SECOND line falls back to the legacy redact+reinsert engine, which
    rewrites the whole content stream and so invalidates the first commit's
    retained inverse patch. That is the ordinary two-edit sequence that
    wedges undo.
    """
    stream = (
        b"BT /F1 12 Tf 72 700 Td (Price 2024) Tj 0 -40 Td ("
        + SECOND_TARGET.encode("ascii")
        + b") Tj ET"
    )
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    resources_xref = doc.get_new_xref()
    doc.update_object(resources_xref, f"<</Font<</F1 {font_xref} 0 R>>>>")
    doc.xref_set_key(page.xref, "Resources", f"{resources_xref} 0 R")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _open_at(path: Path, page_num: int, settings=None) -> PDFModel:
    model = PDFModel() if settings is None else PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path))
    model.ensure_page_index_built(page_num)
    return model


def _block_on(model: PDFModel, page_num: int, probe: str):
    return next(
        b
        for b in model.block_manager.get_blocks(page_num - 1)
        if probe in (b.text or "")
    )


# ------------------------ /SigFlags declares, it does not attest


def test_unsigned_signature_placeholder_is_not_a_signed_document(tmp_path):
    """RED: ``sig_flags > 0`` is true for a never-signed placeholder, so the
    probe called an ordinary form template "signed" -- on a page that carries
    no field at all."""
    path = _write_signature_template_pdf(tmp_path / "template.pdf")
    doc = fitz.open(str(path))
    try:
        assert doc.get_sigflags() > 0, "fixture must declare signature fields"
        assert len(list(doc[1].widgets())) == 0, "page 2 must carry no widget"
        assert page_has_widgets_or_signatures(doc, doc[1]) is False
    finally:
        doc.close()


def test_unsigned_signature_placeholder_page_with_the_field_still_refuses(tmp_path):
    """PIN: narrowing the /SigFlags half must not narrow the widget half --
    the page that actually carries the signature field stays refused."""
    path = _write_signature_template_pdf(tmp_path / "template.pdf")
    doc = fitz.open(str(path))
    try:
        assert page_has_widgets_or_signatures(doc, doc[0]) is True
    finally:
        doc.close()


def test_unsigned_signature_placeholder_still_edits_under_the_shipped_default(
    tmp_path,
):
    """RED: end to end. A contract template with an unsigned signature
    placeholder became wholly uneditable under the shipped default, with the
    only escape an env var plus a restart. Editing a page that carries no
    field invalidates nothing and must commit."""
    path = _write_signature_template_pdf(tmp_path / "template.pdf")
    model = _open_at(path, 2)
    try:
        assert model.text_commit_settings.engine == "tiered"
        block = _block_on(model, 2, TARGET)
        result = model.edit_text(
            2, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )
        assert result is EditTextResult.SUCCESS
        assert REPLACEMENT in model.doc[1].get_text()
    finally:
        model.close()


def test_genuinely_signed_document_still_refuses_every_page(tmp_path):
    """PIN: the narrowing must not reach a document that IS signed -- any
    byte change invalidates the signature, so every page stays refused."""
    path = _write_signature_template_pdf(tmp_path / "signed.pdf", signed=True)
    doc = fitz.open(str(path))
    try:
        sig_xref = next(
            w.xref
            for w in doc[0].widgets()
            if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE
        )
        assert doc.xref_get_key(sig_xref, "V")[0] != "null", (
            "fixture is vacuous: /V did not survive save+reopen"
        )
        assert page_has_widgets_or_signatures(doc, doc[1]) is True
    finally:
        doc.close()
    model = _open_at(path, 2)
    try:
        block = _block_on(model, 2, TARGET)
        fingerprint_before = page_fingerprint(model.doc, model.doc[1])
        result = model.edit_text(
            2, fitz.Rect(block.layout_rect), REPLACEMENT, original_text=block.text
        )
        assert result is EditTextResult.REJECTED_UNSUPPORTED
        assert page_fingerprint(model.doc, model.doc[1]) == fingerprint_before
        assert TARGET in model.doc[1].get_text()
    finally:
        model.close()


def test_unparseable_acroform_fields_fail_closed(tmp_path, monkeypatch):
    """PIN (green before AND after, for different reasons -- said out loud so
    nobody reads it as redness): before the narrowing it passed vacuously,
    because ``sig_flags > 0`` never consulted the field tree at all. After
    it, it is the real oracle for the module's fail-closed rule -- a field
    tree the walk cannot read is answered ``True``, never "unsigned"."""
    path = _write_signature_template_pdf(tmp_path / "template.pdf")
    doc = fitz.open(str(path))
    try:
        real_get_key = fitz.Document.xref_get_key

        def _boom(self, xref, key):
            if key in ("AcroForm", "Fields", "FT", "V", "Kids"):
                raise RuntimeError("unreadable AcroForm")
            return real_get_key(self, xref, key)

        monkeypatch.setattr(fitz.Document, "xref_get_key", _boom, raising=False)
        assert page_has_widgets_or_signatures(doc, doc[1]) is True
    finally:
        doc.close()


# ------------------------ a refused undo must not be silent


def test_stale_undo_has_a_user_facing_message():
    """RED: ``STALE_UNDO`` fell through ``_edit_result_to_message`` to
    ``None``, and ``_show_edit_result_feedback`` early-returns on a falsy
    message -- the same silence round 1 removed for
    ``REJECTED_UNSUPPORTED``."""
    message = PDFController._edit_result_to_message(None, EditTextResult.STALE_UNDO)
    assert message
    assert isinstance(message, str)


def test_stale_plan_redo_has_a_user_facing_message():
    """RED: the redo twin of the same defect (``model/edit_commands.py``
    ``_redo_tier0``)."""
    message = PDFController._edit_result_to_message(None, EditTextResult.STALE_PLAN)
    assert message
    assert isinstance(message, str)


def test_refused_undo_without_a_mapped_result_still_speaks(qapp, tmp_path, monkeypatch):
    """RED: routing the refusal through ``_edit_result_to_message`` alone
    would re-create the bug for any command that returns ``False`` without
    setting a mapped ``result`` -- the branch needs its own fallback."""
    path = _write_plain_pdf(tmp_path / "plain.pdf")
    model, view, controller = _launch(path, None, monkeypatch)
    try:
        errors: list[str] = []
        monkeypatch.setattr(
            view,
            "_show_toast",
            lambda message, duration_ms=2500, tone="info": errors.append(str(message)),
            raising=False,
        )

        class _RefusingCommand:
            description = "refusing command"
            is_structural = False
            result = None

            def undo(self) -> bool:
                return False

        model.command_manager._undo_stack.append(_RefusingCommand())

        controller.undo()

        assert errors, "a refused undo must tell the user something"
        assert len(model.command_manager._undo_stack) == 1
    finally:
        _teardown(model, view, qapp)


def test_stale_undo_tells_the_user_and_leaves_the_stack_honest(
    qapp, tmp_path, monkeypatch
):
    """RED: reproduced through the production wiring. Edit 1 commits at Tier
    0 and retains an inverse patch; edit 2 on the same page falls back to the
    legacy engine and rewrites the content stream; the second Ctrl+Z then
    refuses with ``STALE_UNDO`` -- zero mutation, command retained -- and
    before this fix said NOTHING, leaving a lit undo button on a stack that
    can never move again."""
    path = _write_two_line_stream_pdf(tmp_path / "two_line.pdf")
    # Edit 2 must be refused by the tiered engine to reach the legacy
    # rewrite; critique step 12 made Tier 1 (which commits it losslessly)
    # the default, so this test pins the Tier 0 setting it was written under.
    model, view, controller = _launch(
        path, TextCommitSettings(max_tier=0), monkeypatch
    )
    try:
        _edit_via_signal(model, view, "Price 2024", "Price 2025")
        # UI step 7: the legacy rewrite of edit 2 needs the explicit
        # rebuild consent (request flag + an accepting confirm stub).
        consent = _ConfirmSpy(answer=True)
        monkeypatch.setattr(controller, "_confirm_legacy_fallback", consent)
        _edit_via_signal(
            model, view, SECOND_TARGET, SECOND_REPLACEMENT, allow_rebuild=True
        )
        assert len(consent.calls) == 1
        assert len(model.command_manager._undo_stack) == 2

        controller.undo()
        assert len(model.command_manager._undo_stack) == 1

        toasts: list[tuple[str, str]] = []
        monkeypatch.setattr(
            view,
            "_show_toast",
            lambda message, duration_ms=2500, tone="info": toasts.append(
                (str(message), str(tone))
            ),
            raising=False,
        )
        text_before = model.doc[0].get_text()

        controller.undo()

        assert len(toasts) == 1, f"expected exactly one refusal toast, got {toasts}"
        assert toasts[0][1] == "error"
        # zero mutation: the refusal must not have touched the page
        assert model.doc[0].get_text() == text_before
        assert len(model.command_manager._undo_stack) == 1
    finally:
        _teardown(model, view, qapp)
