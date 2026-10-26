"""Round 8 UX, R8-1: a line drawn by two fonts is a multi-span target.

Owner IME acceptance 2026-10-26: a paragraph target whose line is one Latin
show in one Type0 font plus one CJK show in another (zero gap) was refused
as ``no_source_match`` ("找不到這段文字在 PDF 中的原始內容"), a sentence the
user reads as "the glyphs are wrong".  The accurate code is
``multi_span_target``: the commit side already issues it whenever
``_tier0_target_from_resolve`` returns ``None``.  The resolver instead built a
joined two-run target, and ``bind_source_text`` (one show only) then found no
single show carrying the joined text.

Predicate under test: in paragraph mode a joined target whose member runs carry
more than one font cannot be one show operator, so it resolves to no target.  Everything
else keeps today's outcome, pinned here by controls: a one-run target whose
text does not bind and a same-font two-run line both stay ``no_source_match``.

Every fixture is synthetic (the cached Droid Sans Fallback builder font of
``type0_fixture_builder``); no document text from ``test_files/`` is used.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import derive_tier0_preview_target  # noqa: E402
from model.text_commit.dto import CommitStatus, RejectReason, TextCommitSettings  # noqa: E402
from model.text_commit.inspect import page_fingerprint  # noqa: E402
from test_scripts import type0_fixture_builder as t0  # noqa: E402
from view.text_edit_reasons import (  # noqa: E402
    effective_rejection_reason,
    rejection_reason_text,
)

LATIN = "ABC"
CJK = "你好"


def _line_pdf(path: Path, *, second_font: bool, color_split: bool = False) -> Path:
    """One baseline, two zero-gap hex ``Tj`` shows: Latin then CJK.

    ``second_font`` draws the CJK show in a second Type0 font resource whose
    ``/BaseFont`` differs (a clone of the first sharing its descriptor and
    program); otherwise both shows use the one resource, optionally split by
    a fill-colour change so the index still yields two runs.
    """
    fx = t0.build_identity_h_fixture(LATIN + CJK)
    doc = fx.doc
    resource_two = fx.resource_name
    if second_font:
        descendant = doc.xref_object(fx.descendant_xref, compressed=False)
        descendant_two = doc.get_new_xref()
        doc.update_object(descendant_two, descendant.replace("Regular", "Bold"))
        font = doc.xref_object(fx.font_xref, compressed=False).replace("Regular", "Bold")
        font = re.sub(
            r"/DescendantFonts\s*\[[^\]]*\]",
            f"/DescendantFonts [ {descendant_two} 0 R ]",
            font,
        )
        font_two = doc.get_new_xref()
        doc.update_object(font_two, font)
        resources = doc.xref_get_key(fx.page.xref, "Resources")
        assert resources[0] == "xref", resources
        doc.xref_set_key(int(resources[1].split()[0]), "Font/F9", f"{font_two} 0 R")
        resource_two = "F9"
    latin_hex = t0.encode_cids(LATIN).hex().upper()
    cjk_hex = t0.encode_cids(CJK).hex().upper()
    split = "1 0 0 rg " if color_split else ""
    stream = (
        f"BT /{fx.resource_name} 12 Tf 1 0 0 1 72 700 Tm 0 0 0 rg <{latin_hex}> Tj "
        f"/{resource_two} 12 Tf {split}<{cjk_hex}> Tj ET"
    )
    doc.update_stream(fx.content_xref, stream.encode("ascii"))
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _single_run_pdf(path: Path) -> Path:
    """``(To) Tj (tal) Tj``: two shows, ONE index run (adjacent same style)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content = doc.get_new_xref()
    doc.update_object(content, "<<>>")
    doc.update_stream(content, b"BT /F1 12 Tf 72 700 Td (To) Tj (tal) Tj ET")
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    font = doc.get_new_xref()
    doc.update_object(
        font,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font} 0 R >> >>")
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _open(path: Path) -> PDFModel:
    model = PDFModel(text_commit_settings=TextCommitSettings())
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    model.set_text_target_mode("paragraph")
    return model


def _block(model: PDFModel):
    return model.block_manager.get_blocks(0)[0]


def _paragraph_edit(model: PDFModel, new_text: str) -> EditTextResult:
    block = _block(model)
    return model.edit_text(
        1,
        fitz.Rect(block.layout_rect),
        new_text,
        "helv",
        12.0,
        (0.0, 0.0, 0.0),
        original_text=block.text,
        target_mode="paragraph",
    )


def _preview_target(model: PDFModel):
    block = _block(model)
    return derive_tier0_preview_target(
        model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
        target_span_id=None,
        target_mode="paragraph",
    )


def _assert_refusal(model: PDFModel, result: EditTextResult, reason: str) -> None:
    assert result is EditTextResult.REJECTED, result
    outcome = model.last_commit_outcome
    assert outcome is not None
    assert outcome.status is CommitStatus.REJECTED, outcome
    assert outcome.degraded_reason == reason, outcome
    assert outcome.fallback_chain == (f"tier0:{reason}",)


def test_two_font_line_fixture_is_two_runs_in_two_fonts(tmp_path: Path) -> None:
    """Precondition: the fixture is the owner's shape, not a one-run page."""
    model = _open(_line_pdf(tmp_path / "two.pdf", second_font=True))
    try:
        runs = sorted(model.block_manager.get_runs(0), key=lambda r: r.origin.x)
        assert len(runs) == 2
        assert runs[0].font != runs[1].font
        assert runs[0].text == LATIN and runs[1].text == CJK
    finally:
        model.close()


def test_paragraph_commit_on_a_two_font_line_is_multi_span_target(
    tmp_path: Path,
) -> None:
    model = _open(_line_pdf(tmp_path / "two.pdf", second_font=True))
    try:
        doc = model.doc
        fingerprint = page_fingerprint(doc, doc[0])
        streams = [doc.xref_stream(x) for x in doc[0].get_contents()]
        result = _paragraph_edit(model, "XYZ" + CJK)
        _assert_refusal(model, result, RejectReason.MULTI_SPAN_TARGET)
        # Zero mutation on a refusal.
        assert page_fingerprint(doc, doc[0]) == fingerprint
        assert [doc.xref_stream(x) for x in doc[0].get_contents()] == streams
    finally:
        model.close()


def test_preview_target_of_a_two_font_line_is_unresolved(tmp_path: Path) -> None:
    """The controller's preview path (``derive_tier0_preview_target``) gives
    no target; the controller then reports ``target_unresolved`` and the view
    shows the paragraph-mode cause, ``multi_span_target``."""
    model = _open(_line_pdf(tmp_path / "two.pdf", second_font=True))
    try:
        assert _preview_target(model) is None
    finally:
        model.close()
    shown = effective_rejection_reason(
        "target_unresolved",
        page_changed=False,
        position_changed=False,
        style_changed=False,
        paragraph_mode=True,
    )
    assert shown == "multi_span_target"
    assert rejection_reason_text(shown) == "一次修改多段文字（段落）需要重建文字"


def test_single_run_target_that_does_not_bind_stays_no_source_match(
    tmp_path: Path,
) -> None:
    """Control: one run (two shows, same style) is not a font question."""
    model = _open(_single_run_pdf(tmp_path / "one.pdf"))
    try:
        assert len(model.block_manager.get_runs(0)) == 1
        assert _preview_target(model) is not None
        result = _paragraph_edit(model, "Totaz")
        _assert_refusal(model, result, RejectReason.NO_MATCH)
    finally:
        model.close()


def test_same_font_two_run_line_keeps_today_outcome(tmp_path: Path) -> None:
    """Control (pins HEAD): two runs split by colour in ONE font resource are
    still a resolved joined target that fails to bind: ``no_source_match``.
    The multi-span label is for the font-split shape only; the same-font
    shape is a separate, unchanged behaviour."""
    model = _open(_line_pdf(tmp_path / "same.pdf", second_font=False, color_split=True))
    try:
        runs = model.block_manager.get_runs(0)
        assert len(runs) == 2 and runs[0].font == runs[1].font
        assert _preview_target(model) is not None
        result = _paragraph_edit(model, "XYZ" + CJK)
        _assert_refusal(model, result, RejectReason.NO_MATCH)
    finally:
        model.close()


def test_run_mode_joined_two_font_box_keeps_head_outcome(tmp_path: Path) -> None:
    """Scope control (reviewer F2): the multi-font rule is paragraph-only.  A
    legacy rebuild of 'Heading' -> 'Head' + CJK leaves two runs in two fonts
    that the app re-opens as ONE run-mode (S17 joined) box; its tier-0 re-edit
    keeps HEAD's ``no_source_match`` (the view's ``multi_span_target`` remap is
    paragraph-only, so a run-mode multi-span label would contradict the
    preview badge)."""
    path = tmp_path / "heading.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=400).insert_text(
        (50, 100), "Heading", fontname="helv", fontsize=12
    )
    doc.save(str(path))
    doc.close()
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, fitz.Point(60, 97))
        rebuilt = model.edit_text(
            page_num=1, rect=hit.target_bbox, new_text="Head" + CJK, font=hit.font,
            size=hit.size, color=hit.color, original_text=hit.target_text,
            target_span_id=hit.target_span_id, target_mode="run",
        )
        assert rebuilt is EditTextResult.SUCCESS
        model.ensure_page_index_built(1)
        runs = model.block_manager.get_runs(0)
        assert len(runs) == 2 and runs[0].font != runs[1].font
        model.text_commit_settings = TextCommitSettings()
        hit = model.get_text_info_at_point(1, fitz.Point(60, 97))
        assert hit.target_text == "Head" + CJK
        result = model.edit_text(
            page_num=1, rect=hit.target_bbox, new_text="Hexd" + CJK, font=hit.font,
            size=hit.size, color=hit.color, original_text=hit.target_text,
            target_span_id=hit.target_span_id, target_mode="run",
        )
        _assert_refusal(model, result, RejectReason.NO_MATCH)
    finally:
        model.close()
