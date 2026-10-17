from __future__ import annotations

import inspect
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.edit_requests import RebuildConsent, StyleOverrides, UnkeepableGlyph  # noqa: E402
from model.font_stream_compaction import font_compaction_scope  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
import model.pdf_model as pdf_model_module  # noqa: E402
from model.pdf_text_edit import (  # noqa: E402
    _RebuildRolledBack,
    _cores_overlap,
    _glyph_ink_core,
    _is_axis_aligned_dir,
    _page_glyphs,
    _right_wall,
)
from model.text_commit.dto import CommitStatus, TextCommitSettings  # noqa: E402
from model.text_commit.transforms import page_visual_frame  # noqa: E402
from model.text_edit_refusal import TextEditRefusal  # noqa: E402
from model.tools.annotation_tool import AnnotationTool  # noqa: E402


def _accept_rebuild(_chain: tuple[str, ...]) -> bool:
    """UI step 7 (no silent legacy): explicit rebuild consent stub.  The
    tests that use it exercise the rebuild (legacy redact+reinsert) path, which
    a tiered refusal now reaches only with ``allow_rebuild=True`` plus an
    accepting confirm -- the same path they ran before, now consented."""
    return True


@pytest.fixture()
def model_with_pdf(tmp_path: Path):
    """Create a minimal PDF, open in PDFModel, and yield the model."""
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    page.insert_text((72, 200), "Original text to edit", fontsize=12.0, fontname="helv")
    page.insert_text((72, 300), "Third block here", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    try:
        yield model
    finally:
        model.close()


def _find_block(model: PDFModel, page_idx: int, probe: str):
    for block in model.block_manager.get_blocks(page_idx):
        if probe in (block.text or ""):
            return block
    return None


def _first_span_id(model: PDFModel, page_idx: int, rect: fitz.Rect) -> str:
    spans = model.block_manager.find_overlapping_runs(page_idx, rect, tol=0.5)
    assert spans
    return spans[0].span_id


def _resolve_target(
    model: PDFModel,
    block,
    *,
    new_text: str,
    font: str = "helv",
    size: float = 12.0,
    color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    original_text: str | None = None,
    new_rect: fitz.Rect | None = None,
    resolved_target_span_id: str | None = None,
    effective_target_mode: str = "paragraph",
):
    page = model.doc[0]
    rect = fitz.Rect(block.layout_rect) if block is not None else fitz.Rect(9000, 9000, 9010, 9010)
    return model._resolve_edit_target(
        page_num=1,
        page_idx=0,
        page=page,
        rect=rect,
        new_text=new_text,
        font=font,
        size=size,
        color=color,
        original_text=original_text if original_text is not None else (block.text if block is not None else None),
        new_rect=new_rect,
        resolved_target_span_id=resolved_target_span_id,
        effective_target_mode=effective_target_mode,
    )


def _resolve_for_apply(model: PDFModel, probe: str, *, new_text: str):
    block = _find_block(model, 0, probe)
    assert block is not None
    status, result = _resolve_target(
        model,
        block,
        new_text=new_text,
        original_text=block.text,
    )
    assert status is EditTextResult.SUCCESS
    assert result is not None
    return block, result


def _apply_insert(model: PDFModel, probe: str, *, new_text: str) -> tuple[fitz.Page, object, fitz.Rect, bytes]:
    _, resolve_result = _resolve_for_apply(model, probe, new_text=new_text)
    page = model.doc[0]
    snapshot = model._capture_page_snapshot(0)
    new_rect = model._apply_redact_insert(
        page=page,
        page_num=1,
        page_idx=0,
        page_rect=page.rect,
        new_text=new_text,
        size=12.0,
        color=(0.0, 0.0, 0.0),
        vertical_shift_left=True,
        new_rect=None,
        snapshot_bytes=snapshot,
        resolve_result=resolve_result,
    )
    return page, resolve_result, new_rect, snapshot


def test_mode_default_no_args(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode=None,
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=None,
    )

    assert effective == "paragraph"


def test_classify_insert_path_fast_vs_htmlbox() -> None:
    """Shared classifier should pick fast path only for strict single-line cases."""
    # empty member_spans → htmlbox (no anchor span available for insert_text origin)
    assert pdf_model_module._classify_insert_path(
        new_text="hello",
        member_spans=[],
        rotation=0,
        is_vertical=False,
        preserve_multi_style=False,
        has_new_rect=False,
        needs_cjk=False,
        text_width=40.0,
        available_width=80.0,
        size=12.0,
    ) == "htmlbox"

    assert pdf_model_module._classify_insert_path(
        new_text="hello\nworld",
        member_spans=[],
        rotation=0,
        is_vertical=False,
        preserve_multi_style=False,
        has_new_rect=False,
        needs_cjk=False,
        text_width=40.0,
        available_width=80.0,
        size=12.0,
    ) == "htmlbox"

    vertical_span = SimpleNamespace(bbox=fitz.Rect(0, 0, 40, 12))
    assert pdf_model_module._classify_insert_path(
        new_text="hello",
        member_spans=[vertical_span],
        rotation=0,
        is_vertical=True,
        preserve_multi_style=False,
        has_new_rect=False,
        needs_cjk=False,
        text_width=40.0,
        available_width=80.0,
        size=12.0,
    ) == "htmlbox"


def test_mode_explicit_span_id(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None
    span_id = _first_span_id(model_with_pdf, 0, fitz.Rect(block.layout_rect))

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode=None,
        target_span_id=span_id,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "run"


def test_mode_new_rect_promotes(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None
    new_rect = fitz.Rect(block.layout_rect)
    new_rect.y0 += 20
    new_rect.y1 += 20

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode=None,
        target_span_id=None,
        new_rect=new_rect,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "paragraph"


def test_mode_explicit_paragraph(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode="paragraph",
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "paragraph"


def test_mode_run_auto_promotes(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Original text to edit")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode="run",
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text=block.text,
    )

    assert effective == "paragraph"


def test_mode_run_no_promote_subsection(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Original text to edit")
    assert block is not None

    effective = model_with_pdf._resolve_effective_target_mode(
        target_mode="run",
        target_span_id=None,
        new_rect=None,
        page_idx=0,
        rect=fitz.Rect(block.layout_rect),
        original_text="Original",
    )

    assert effective == "run"


def test_resolve_target_happy_path(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    status, result = _resolve_target(
        model_with_pdf,
        block,
        new_text="New text",
        original_text=block.text,
    )

    assert status is EditTextResult.SUCCESS
    assert result is not None
    assert result.target_span is not None
    assert result.target.text == block.text


def test_resolve_target_missing_block(model_with_pdf: PDFModel) -> None:
    status, result = _resolve_target(
        model_with_pdf,
        None,
        new_text="New text",
        original_text="Missing block",
    )

    assert status is EditTextResult.TARGET_BLOCK_NOT_FOUND
    assert result is None


def test_resolve_target_no_change(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None

    status, result = _resolve_target(
        model_with_pdf,
        block,
        new_text=block.text,
        font=block.font,
        size=float(block.size),
        color=tuple(float(c) for c in block.color),
        original_text=block.text,
    )

    assert status is EditTextResult.NO_CHANGE
    assert result is None


def test_resolve_target_by_span_id(model_with_pdf: PDFModel) -> None:
    block = _find_block(model_with_pdf, 0, "Hello World")
    assert block is not None
    span_id = _first_span_id(model_with_pdf, 0, fitz.Rect(block.layout_rect))

    status, result = _resolve_target(
        model_with_pdf,
        block,
        new_text="Updated via span id",
        original_text=block.text,
        resolved_target_span_id=span_id,
        effective_target_mode="run",
    )

    assert status is EditTextResult.SUCCESS
    assert result is not None
    assert result.resolved_target_span_id == span_id


def test_apply_insert_basic(model_with_pdf: PDFModel) -> None:
    page, _, new_rect, _ = _apply_insert(model_with_pdf, "Hello World", new_text="Goodbye")

    page_text = page.get_text("text")
    assert isinstance(new_rect, fitz.Rect)
    assert "Goodbye" in page_text
    assert "Hello World" not in page_text


def test_apply_insert_empty_deletes(model_with_pdf: PDFModel) -> None:
    page, _, new_rect, _ = _apply_insert(model_with_pdf, "Hello World", new_text="")

    assert isinstance(new_rect, fitz.Rect)
    assert "Hello World" not in page.get_text("text")


def test_apply_insert_preserves_others(model_with_pdf: PDFModel) -> None:
    page, _, _, _ = _apply_insert(model_with_pdf, "Hello World", new_text="Goodbye")

    assert "Third block here" in page.get_text("text")


def test_verify_rebuild_passes(model_with_pdf: PDFModel) -> None:
    page, resolve_result, new_rect, snapshot = _apply_insert(
        model_with_pdf, "Hello World", new_text="Goodbye"
    )

    model_with_pdf._verify_rebuild_edit(
        page=page,
        page_num=1,
        page_idx=0,
        page_rect=page.rect,
        new_text="Goodbye",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        snapshot_bytes=snapshot,
        resolve_result=resolve_result,
        new_layout_rect=new_rect,
    )

    updated_block = _find_block(model_with_pdf, 0, "Goodbye")
    assert updated_block is not None


def test_verify_rebuild_rollback(model_with_pdf: PDFModel) -> None:
    block, resolve_result = _resolve_for_apply(
        model_with_pdf, "Hello World", new_text="Replacement text"
    )
    page = model_with_pdf.doc[0]
    snapshot = model_with_pdf._capture_page_snapshot(0)

    with pytest.raises(RuntimeError, match="verification failed"):
        model_with_pdf._verify_rebuild_edit(
            page=page,
            page_num=1,
            page_idx=0,
            page_rect=page.rect,
            new_text="XYZZY_NONEXISTENT",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            snapshot_bytes=snapshot,
            resolve_result=resolve_result,
            new_layout_rect=fitz.Rect(block.layout_rect),
        )


# ── Phase-2 red-light regressions ───────────────────────────────────────────


def test_phase2_single_line_run_edit_preserves_anchor_without_drag(
    model_with_pdf: PDFModel,
) -> None:
    """Phase-2 symptom 1: run-mode non-drag edits must not drift the anchor."""
    target = _find_block(model_with_pdf, 0, "Hello World")
    assert target is not None
    baseline_x0 = float(target.layout_rect.x0)
    baseline_y0 = float(target.layout_rect.y0)

    result = model_with_pdf.edit_text(
        page_num=1,
        rect=fitz.Rect(target.layout_rect),
        new_text="Hello world!",
        font=target.font,
        size=float(target.size),
        color=tuple(float(c) for c in target.color),
        original_text=target.text,
        target_mode="run",
        allow_rebuild=True,
        confirm_fallback=_accept_rebuild,
    )
    assert result is EditTextResult.SUCCESS
    model_with_pdf.block_manager.rebuild_page(0, model_with_pdf.doc)

    edited = _find_block(model_with_pdf, 0, "Hello world!")
    assert edited is not None
    drift_x0 = float(edited.layout_rect.x0) - baseline_x0
    drift_y0 = float(edited.layout_rect.y0) - baseline_y0
    assert abs(drift_x0) < 0.5, f"Anchor drifted x0 by {drift_x0:.3f}pt"
    assert abs(drift_y0) < 0.5, f"Anchor drifted y0 by {drift_y0:.3f}pt"


def test_phase2_edit_text_preserves_fractional_font_size(
    model_with_pdf: PDFModel,
) -> None:
    """Phase-2 symptom 2: fractional font sizes must round-trip through edit_text."""
    target = _find_block(model_with_pdf, 0, "Original text to edit")
    assert target is not None

    result = model_with_pdf.edit_text(
        page_num=1,
        rect=fitz.Rect(target.layout_rect),
        new_text="Fractional edit content",
        font=target.font,
        size=9.5,
        color=tuple(float(c) for c in target.color),
        original_text=target.text,
        target_mode="run",
        # The size change is a user restyle, carried the way the UI carries
        # it.  Without StyleOverrides the tiered engine keeps the source
        # size (style truth stays with the source); this passed before
        # critique step 12 only because Tier 0 refused the growing text
        # into the size-honouring legacy rebuild.
        style_overrides=StyleOverrides(font_size=9.5),
        allow_rebuild=True,
        confirm_fallback=_accept_rebuild,
    )
    assert result is EditTextResult.SUCCESS
    model_with_pdf.block_manager.rebuild_page(0, model_with_pdf.doc)

    edited = _find_block(model_with_pdf, 0, "Fractional edit content")
    assert edited is not None
    observed_size = float(edited.size)
    assert abs(observed_size - 9.5) < 0.1, (
        f"Fractional size collapsed to {observed_size:.3f} (expected ≈9.5)"
    )


# ---------------------------------------------------------------------------
# Text size fidelity — the committed text must not visually grow or shrink
# without an explicit user font-size action.
#
# Two distinct properties are checked:
#   1. font pt size (`hit.size`) — guards against int-truncation regressions
#      (PITFALLS: "PyMuPDF font sizes are floats, not ints")
#   2. visual span height (`hit.target_bbox.height`) — guards against
#      `_build_insert_css` producing a different line_height than the
#      original PDF, which makes the committed block taller/shorter and
#      pushes surrounding text.
# ---------------------------------------------------------------------------


def _make_pdf_at_size(tmp_path: Path, fontsize: float, text: str = "Hello World") -> Path:
    """Create a single-page PDF with one ``insert_text`` block at the given size."""
    pdf_path = tmp_path / f"size_{fontsize}.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), text, fontname="helv", fontsize=fontsize)
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    return pdf_path


def _measure_span_at(model: PDFModel, page_num: int, point: fitz.Point):
    """Return (font_pt_size, bbox_height) for the span under ``point``, or None."""
    model.ensure_page_index_built(page_num)
    hit = model.get_text_info_at_point(page_num, point)
    if hit is None:
        return None
    return float(hit.size), float(hit.target_bbox.height)


@pytest.mark.parametrize("original_size", [12.0, 9.5, 24.0])
def test_edit_preserves_font_size_pt_after_content_change(tmp_path: Path, original_size: float):
    """Font pt size must not change when the user only edits text content.

    Catches integer truncation (9.5pt → 9pt) and any CSS-side rounding the
    re-insert path might introduce.
    """
    pdf_path = _make_pdf_at_size(tmp_path, original_size)
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        probe = fitz.Point(60, 100)
        before = _measure_span_at(model, 1, probe)
        assert before is not None, f"Cannot find span at {probe} for size {original_size}"
        size_before, _ = before

        hit = model.get_text_info_at_point(1, probe)
        assert hit is not None
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text="Hi World",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS
        assert _page_contains_text(model, 1, "Hi World"), (
            "Edited content not found after edit_text — test must fail on no-op edits"
        )

        after = _measure_span_at(model, 1, probe)
        assert after is not None, "Span not found after edit"
        size_after, _ = after

        assert abs(size_after - size_before) < 0.5, (
            f"Font pt drifted {size_before:.3f}pt → {size_after:.3f}pt "
            f"(original_size={original_size}) — size must survive a content edit"
        )
    finally:
        model.close()


@pytest.mark.parametrize("original_size", [12.0, 24.0])
def test_edit_preserves_span_bbox_height_after_content_change(
    tmp_path: Path, original_size: float, monkeypatch: pytest.MonkeyPatch
):
    """Visual span height (bbox height) must not change after a content edit.

    The auto-calculated CSS line_height in ``_build_insert_css`` (when no
    explicit value is passed) inflates committed spans relative to the
    original ``insert_text`` layout — this test asserts that does NOT happen.
    """
    pdf_path = _make_pdf_at_size(tmp_path, original_size)
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        probe = fitz.Point(60, 100)
        before = _measure_span_at(model, 1, probe)
        assert before is not None
        _, height_before = before

        # Force the htmlbox insertion path so this test guards line-height fidelity,
        # not the single-line insert_text fast path.
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)

        hit = model.get_text_info_at_point(1, probe)
        assert hit is not None
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text="Hi World",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS
        assert _page_contains_text(model, 1, "Hi World"), (
            "Edited content not found after edit_text — no-op edits must fail this test"
        )

        after = _measure_span_at(model, 1, probe)
        assert after is not None
        _, height_after = after

        tolerance = 1.5  # pt
        assert abs(height_after - height_before) <= tolerance, (
            f"Span height drifted {height_before:.2f}pt → {height_after:.2f}pt "
            f"(size={original_size}) — line height must survive a content edit"
        )
    finally:
        model.close()


def test_single_line_edit_does_not_push_unedited_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A single-character edit on one line must not shift unedited text below it.

    Reproduces the user's "push unedited lines away" symptom: editing a heading
    used to inflate the redacted region by ~22pt due to (a) MuPDF's 2pt htmlbox
    rendering overhead and (b) an over-conservative est_height heuristic
    forcing _probe_y1 to base_y1 = y0 + line_count × size × 2 + size × 2.
    With both fixes, the probe trusts its actual measurement and subtracts
    MuPDF's known overhead, so a single-line edit does not trigger push-down.
    """
    pdf_path = tmp_path / "layout.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    # 7.5pt keeps the meaningful-growth threshold at 1.5pt, so MuPDF's fixed
    # ~2pt htmlbox overhead will wrongly trigger push-down if not subtracted.
    page.insert_text((50, 100), "Heading line", fontname="helv", fontsize=7.5)
    # Anchor text below — should NOT shift after the heading edit.
    page.insert_text((50, 200), "Anchor text below", fontname="helv", fontsize=7.5)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        anchor_before = model.get_text_info_at_point(1, fitz.Point(60, 200))
        assert anchor_before is not None
        anchor_y_before = float(anchor_before.target_bbox.y0)

        # Force htmlbox path so the pre-push probe path is actually exercised.
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)

        # Edit the heading
        hit = model.get_text_info_at_point(1, fitz.Point(60, 100))
        assert hit is not None
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=hit.target_text + "X",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS
        # UI step 3 (B1): the run-mode hit is the whole proven show
        # "Heading line", so the edit replaces the WHOLE show -- no leftover
        # ' line' word next to the rewritten text.
        assert hit.target_text == "Heading line"
        assert _page_contains_text(model, 1, "Heading lineX"), (
            "Heading text did not change — test must fail on no-op edits"
        )
        page_lines = sorted(
            line.strip()
            for line in model.doc[0].get_text("text").splitlines()
            if line.strip()
        )
        assert page_lines == ["Anchor text below", "Heading lineX"], page_lines

        model.ensure_page_index_built(1)
        anchor_after = model.get_text_info_at_point(1, fitz.Point(60, 200))
        assert anchor_after is not None, "Anchor text disappeared after edit"
        anchor_y_after = float(anchor_after.target_bbox.y0)

        # The anchor must not have moved (small floating-point tolerance only)
        assert abs(anchor_y_after - anchor_y_before) < 1.0, (
            f"Unedited anchor text shifted {anchor_y_before:.3f} → "
            f"{anchor_y_after:.3f} ({anchor_y_after - anchor_y_before:+.3f}pt) "
            f"after a single-line content edit — push-down triggered erroneously"
        )
    finally:
        model.close()


def test_prepush_growth_branch_does_not_raise_name_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pdf_path = tmp_path / "prepush_growth.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), "Heading", fontname="helv", fontsize=8.0)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    # Subject: the legacy rebuild's pre-push growth branch, reached only after
    # a tiered refusal; critique step 12 made Tier 1 (which commits this
    # growing edit itself) the default, so pin Tier 0.
    model = PDFModel(text_commit_settings=TextCommitSettings(max_tier=0))
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, fitz.Point(60, 100))
        assert hit is not None
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)
        pushed = {"called": False}
        monkeypatch.setattr(
            model,
            "_push_down_overlapping_text",
            lambda *args, **kwargs: pushed.__setitem__("called", True),
        )

        real_insert_htmlbox = fitz.Page.insert_htmlbox
        injected = {"done": False}

        def forcing_probe_growth(page_obj, *args, **kwargs):
            try:
                is_probe_doc = page_obj.parent is not model.doc
            except Exception:
                is_probe_doc = False
            if is_probe_doc and not injected["done"]:
                injected["done"] = True
                # "Fits, and fills the whole box": maximal growth.  A negative
                # spare means "does not fit at this scale" and is no longer
                # read as growth (F14-VF4-WRAP: the probe runs B and C next).
                return 0.0, 1.0
            return real_insert_htmlbox(page_obj, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "insert_htmlbox", forcing_probe_growth)

        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=hit.target_text + " extended",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert injected["done"] is True
        assert result is EditTextResult.SUCCESS
        assert pushed["called"] is True
    finally:
        model.close()


def test_render_width_for_edit_does_not_exceed_rect_width(tmp_path: Path):
    """Inline editor wrap width must match the original text-block width.

    If the editor is wider than the source rect, Qt's font renderer (which has
    slightly different glyph metrics than PyMuPDF) lays text at different visual
    widths and breaks lines at different points than the rendered PDF — this is
    the "break lines once edit box opened" symptom.
    """
    pdf_path = tmp_path / "render_width.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=300)
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        test_rect = fitz.Rect(50, 80, 200, 100)  # width = 150pt
        returned_width = model.get_render_width_for_edit(
            page_num=1, rect=test_rect
        )
        assert returned_width <= test_rect.width + 0.5, (
            f"Editor width {returned_width:.1f}pt exceeds source rect width "
            f"{test_rect.width:.1f}pt — wrapping will diverge from PDF render"
        )
    finally:
        model.close()


def test_render_width_for_edit_signature_is_slimmed_to_page_and_rect() -> None:
    """The render-width helper no longer accepts unused layout hints."""
    signature = inspect.signature(PDFModel.get_render_width_for_edit)

    assert list(signature.parameters) == ["self", "page_num", "rect"]


def test_repeated_edits_do_not_accumulate_size_drift(tmp_path: Path):
    """Five consecutive edits on the same span must not amplify any per-edit drift.

    Each commit can introduce a small font-pt or height delta. After five
    rounds, any cumulative drift would exceed tolerance and fail this test.
    """
    pdf_path = _make_pdf_at_size(tmp_path, 12.0)
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        probe = fitz.Point(60, 100)
        before = _measure_span_at(model, 1, probe)
        assert before is not None
        size_before, height_before = before

        for i in range(5):
            model.ensure_page_index_built(1)
            hit = model.get_text_info_at_point(1, probe)
            assert hit is not None, f"Span lost on iteration {i}"
            replacement = f"Edit {i} sentinel"
            result = model.edit_text(
                page_num=1,
                rect=hit.target_bbox,
                new_text=replacement,
                font=hit.font,
                size=hit.size,
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode="run",
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )
            assert result is EditTextResult.SUCCESS, f"edit_text failed on iteration {i}"
            assert _page_contains_text(model, 1, replacement), (
                f"Replacement text missing after iteration {i} — edit did not commit"
            )

        after = _measure_span_at(model, 1, probe)
        assert after is not None, "Span lost after 5 edits"
        size_after, height_after = after

        assert abs(size_after - size_before) < 0.5, (
            f"Font pt drifted {size_before:.3f}pt → {size_after:.3f}pt over 5 edits"
        )
        assert abs(height_after - height_before) <= 2.0, (
            f"Span height drifted {height_before:.2f}pt → {height_after:.2f}pt over 5 edits"
        )
    finally:
        model.close()


# ── Real-PDF regression tests — "larger" and "smaller" symptoms ─────────────

REAL_PDFS_DIR = ROOT / "test_files"


def _find_largest_font_span(model: PDFModel, page_num: int):
    """Return the span with the largest font size on the page (heading proxy)."""
    model.ensure_page_index_built(page_num)
    page_rect = model.doc[page_num - 1].rect
    best = None
    seen: set = set()
    for y in range(30, int(page_rect.height) - 10, 15):
        for x in range(20, int(page_rect.width) - 20, 20):
            hit = model.get_text_info_at_point(page_num, fitz.Point(x, y))
            if hit is None or not hit.target_text.strip():
                continue
            if hit.target_span_id in seen:
                continue
            seen.add(hit.target_span_id)
            if best is None or float(hit.size) > float(best.size):
                best = hit
    return best


def _find_any_editable_span(model: PDFModel, page_num: int):
    """Return a span that can be meaningfully edited (non-trivial text)."""
    model.ensure_page_index_built(page_num)
    page_rect = model.doc[page_num - 1].rect
    seen: set = set()
    for y in range(30, int(page_rect.height) - 10, 15):
        for x in range(20, int(page_rect.width) - 20, 20):
            hit = model.get_text_info_at_point(page_num, fitz.Point(x, y))
            if hit is None or not hit.target_text.strip():
                continue
            if hit.target_span_id in seen:
                continue
            seen.add(hit.target_span_id)
            # Skip trivially short strings that would look identical with a prefix
            if len(hit.target_text.strip()) >= 2:
                return hit
    return None


def _find_span_with_text(model: PDFModel, page_num: int, needle: str):
    """Return the first span whose extracted text contains ``needle``."""
    model.ensure_page_index_built(page_num)
    page_rect = model.doc[page_num - 1].rect
    seen: set = set()
    for y in range(20, int(page_rect.height) - 10, 10):
        for x in range(15, int(page_rect.width) - 15, 12):
            hit = model.get_text_info_at_point(page_num, fitz.Point(x, y))
            if hit is None:
                continue
            if hit.target_span_id in seen:
                continue
            seen.add(hit.target_span_id)
            text = (hit.target_text or "").strip()
            if needle in text:
                return hit
    return None


def _normalized_ws(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split())


def _page_contains_text(model: PDFModel, page_num: int, needle: str) -> bool:
    page_text = model.doc[page_num - 1].get_text("text")
    return _normalized_ws(needle) in _normalized_ws(page_text)


def test_build_insert_css_explicit_tight_line_height_not_clamped():
    """_build_insert_css must honor explicit line_height values below font size.

    Scenario: original PDF has tight leading (e.g. baseline advance 8pt for a 10pt
    font). _apply_redact_insert computes _line_ht=8.0 and passes it explicitly.
    With the bug, line_height = round(max(10, 8), 2) = 10.0 — wrong: committed text
    will be taller than original and surrounding text gets pushed.
    With the fix, explicit positive values bypass the max(size, ...) clamp.
    """
    model = PDFModel()
    model._resolve_add_text_font = lambda hint: "helv"
    model._resolve_cjk_companion_font = lambda font: "helv"
    model._font_face_css_for_token = lambda token: ""

    # Tight leading: line_height (8pt) < size (10pt)
    css = model._build_insert_css(size=10.0, color=(0.0, 0.0, 0.0), font_hint="helv", line_height=8.0)

    assert "line-height: 8.0pt" in css, (
        f"_build_insert_css clamped explicit tight line_height=8.0 up to size=10.0 — "
        f"clamp must only apply to auto-calculated values (line_height<=0). "
        f"CSS produced:\n{css.strip()}"
    )


def test_real_pdf_complexed_layout_edit_does_not_enlarge_span(
    tmp_path: Path,
):
    """Editing the largest-font heading in test-complexed-layout.pdf must not grow
    the span's vertical extent.

    'Larger' symptom reproducer: _build_insert_css clamped line_height to >= size
    even for explicit tight-leading values, making committed boxes taller than original.
    The screenshots (manual-larger-222213/217/220) show the heading oversized after edit.
    """
    import shutil
    from model.edit_commands import EditTextResult

    pdf_src = REAL_PDFS_DIR / "test-complexed-layout.pdf"
    if not pdf_src.exists():
        pytest.skip(f"Reproducer PDF not found: {pdf_src}")

    pdf_copy = tmp_path / "complexed.pdf"
    shutil.copy2(pdf_src, pdf_copy)

    model = PDFModel()
    model.open_pdf(str(pdf_copy))
    try:
        # Deterministic target: '在編輯文字時清除舊有文字的做法' at bbox [117.6, 80.2, 252.6, 89.2]
        # CJK content naturally routes through insert_htmlbox path — no monkeypatch needed.
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, fitz.Point(185, 85))
        assert hit is not None, (
            "Could not find CJK heading span at (185, 85) on page 1 of complexed-layout.pdf"
        )
        assert "在" in hit.target_text, (
            f"Expected CJK heading but found: {hit.target_text!r}"
        )
        height_before = float(hit.target_bbox.height)
        marker = "QFIDLARGE"

        # Prepend "X" so the edit is a real content change (trailing space gets stripped)
        new_text = f"{marker} {hit.target_text}"
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=new_text,
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS, (
            f"edit_text returned {result!r} instead of SUCCESS — edit was not applied"
        )

        model.ensure_page_index_built(1)
        # The rebuilt run, read from the index (a click at its centre would
        # land in the run's reopen-anchor rect, which now sits on the original
        # box: the edit is drawn back on its original baseline, F14-VM-2).
        edited_runs = [r for r in model.block_manager.get_runs(0) if marker in r.text]
        assert edited_runs, (
            f"Edited marker {marker!r} not found after edit — did commit fail? "
            f"height_before={height_before:.2f}pt"
        )
        height_after = float(edited_runs[0].bbox.height)

        assert height_after <= height_before + 1.5, (
            f"Span height grew {height_before:.2f}pt → {height_after:.2f}pt "
            f"(font={hit.size:.2f}pt, text={hit.target_text[:30]!r}) "
            f"in complexed-layout.pdf — 'larger' symptom: _build_insert_css clamp active"
        )
    finally:
        model.close()


def _complexed_heading_model(tmp_path: Path):
    """``test-complexed-layout.pdf`` (a copy) open in a ``PDFModel`` with page 1
    indexed, and the hit on its p1 CJK heading; the caller closes the model
    (the helper closes it itself when indexing or the precondition fails)."""
    import shutil

    pdf_src = REAL_PDFS_DIR / "test-complexed-layout.pdf"
    if not pdf_src.exists():
        pytest.skip(f"Reproducer PDF not found: {pdf_src}")
    pdf_copy = tmp_path / "complexed.pdf"
    shutil.copy2(pdf_src, pdf_copy)
    model = PDFModel()
    model.open_pdf(str(pdf_copy))
    try:
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, fitz.Point(185, 85))
        assert hit is not None and "在" in hit.target_text, f"precondition: {hit!r}"
    except BaseException:
        model.close()
        raise
    return model, hit


def _rebuild_split_heading(model: PDFModel, hit) -> str:
    """Consented rebuild of the heading ``hit`` to ``QFIDANCHOR <heading>``,
    which the app re-inserts as two runs (marker + CJK tail); returns the
    requested text with the page index rebuilt."""
    new_text = f"QFIDANCHOR {hit.target_text}"
    result = model.edit_text(
        page_num=1,
        rect=hit.target_bbox,
        new_text=new_text,
        font=hit.font,
        size=hit.size,
        color=hit.color,
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
        allow_rebuild=True,
        confirm_fallback=_accept_rebuild,
    )
    assert result is EditTextResult.SUCCESS
    model.ensure_page_index_built(1)
    return new_text


def _rebuilt_split_heading_model(tmp_path: Path):
    """``_complexed_heading_model`` after ``_rebuild_split_heading``: returns
    (model, hit_before, new_text) with the model open; the caller closes it."""
    model, hit = _complexed_heading_model(tmp_path)
    return model, hit, _rebuild_split_heading(model, hit)


def test_real_pdf_rebuild_split_heading_reclick_never_opens_another_run(
    tmp_path: Path,
):
    """F14-ANCHOR-STALE: a consented rebuild that re-inserts the heading as TWO
    runs (``QFIDANCHOR`` + the CJK tail) used to migrate the heading's reopen
    anchor onto the nearest run by centre distance -- the unrelated Stirling
    text above it -- so re-clicking the edited heading opened that text.  No
    single run proves the edited text, so the anchor must not be planted on an
    unrelated run, and a click must open the run actually under the cursor.
    """
    model, hit = _complexed_heading_model(tmp_path)
    try:
        old_bbox = fitz.Rect(hit.target_bbox)
        old_center = fitz.Point(
            (old_bbox.x0 + old_bbox.x1) / 2, (old_bbox.y0 + old_bbox.y1) / 2
        )
        stirling_before = next(
            r for r in model.block_manager.get_runs(0) if r.text.startswith("Stirling")
        )
        marker = "QFIDANCHOR"
        _rebuild_split_heading(model, hit)

        # No anchor may be keyed to the unrelated Stirling run.
        stray = [
            key for key in model.run_reopen_anchors
            if key.endswith(stirling_before.span_id)
        ]
        assert not stray, f"heading anchor migrated onto the Stirling run: {stray}"

        after = model.get_text_info_at_point(1, old_center)
        assert after is not None, "re-click inside the edited heading found nothing"
        assert "Stirling" not in after.target_text, after.target_text
        assert marker in after.target_text or "在" in after.target_text, (
            f"re-click opened an unrelated run: {after.target_text!r}"
        )
        # S17-ANCHOR-JOIN: the two runs the app wrote for this one edit reopen
        # as ONE box, so the marker half opens the whole heading too.
        head = model.get_text_info_at_point(1, fitz.Point(130, 85))
        assert head is not None and marker in head.target_text, head
        assert "在" in head.target_text, head
        assert "Stirling" not in head.target_text
    finally:
        model.close()


def _strip_ws(text: str | None) -> str:
    return "".join((text or "").split())


def test_s17_anchor_join_rebuilt_heading_reopens_as_one_box(tmp_path: Path):
    """S17-ANCHOR-JOIN (owner decision ANCHOR-FRAGMENTS): the runs the app wrote
    for ONE edit on one baseline reopen as ONE edit box -- a click on the marker,
    on the CJK tail and in the gap between them all return the whole heading."""
    model, hit, new_text = _rebuilt_split_heading_model(tmp_path)
    try:
        marker_run = next(r for r in model.block_manager.get_runs(0) if r.text.startswith("QFIDANCHOR"))
        runs = [
            r for r in model.block_manager.get_runs(0)
            if (r.block_idx, r.line_idx) == (marker_run.block_idx, marker_run.line_idx)
        ]
        assert len(runs) >= 2, "precondition: the rebuild split the heading into several runs"
        old = fitz.Rect(hit.target_bbox)
        cy = (old.y0 + old.y1) / 2
        got = [
            model.get_text_info_at_point(1, fitz.Point(old.x0 + (k + 0.5) * old.width / 8, cy))
            for k in range(8)
        ]
        assert all(g is not None for g in got)
        assert len({g.target_span_id for g in got}) == 1, [(g.target_span_id, g.target_text) for g in got]
        for g in got:
            assert _strip_ws(g.target_text) == _strip_ws(new_text), g.target_text
            assert g.target_text == new_text
            assert g.target_mode == "run"
            assert len(g.member_span_ids) >= 2
        union = fitz.Rect(runs[0].bbox)
        for r in runs[1:]:
            union |= fitz.Rect(r.bbox)
        assert fitz.Rect(got[0].target_bbox).contains(union)
        # Browse callers (allow_fallback=False) ask for the run under the point:
        # a click in the gap between the fragments still finds none, a click on
        # a fragment reports that fragment as the browse run.
        first, second = sorted(
            (r for r in runs if "QFIDANCHOR" in r.text or "在" in r.text), key=lambda r: r.span_idx
        )[:2]
        gap_x = (first.bbox.x1 + second.bbox.x0) / 2
        assert model.get_text_info_at_point(1, fitz.Point(gap_x, cy), allow_fallback=False) is None
        on_first = model.get_text_info_at_point(
            1, fitz.Point(first.bbox.x0 + 2, cy), allow_fallback=False
        )
        assert on_first is not None and on_first.hit_span_id == first.span_id
        assert on_first.target_text == new_text
        # The stranger above the heading is still its own run.
        above = model.get_text_info_at_point(1, fitz.Point(185, 60))
        assert above is None or "QFIDANCHOR" not in above.target_text
    finally:
        model.close()


def test_s17_anchor_join_joined_box_commits_back_as_one_edit(tmp_path: Path):
    """The joined box commits as ONE edit: both fragments are replaced (neither
    is left behind or drawn twice), the result reopens joined again, and one
    undo restores the pre-edit heading."""
    model, _hit, new_text = _rebuilt_split_heading_model(tmp_path)
    try:
        head = model.get_text_info_at_point(1, fitz.Point(130, 85))
        assert head is not None and head.target_text == new_text
        undo_depth = model.command_manager.undo_count
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=head.target_bbox,
            new_text=f"ZZJOIN {new_text}",
            font=head.font,
            size=head.size,
            color=head.color,
            original_text=head.target_text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=head.target_text,
            target_span_id=head.target_span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        model.command_manager.execute(cmd)
        assert cmd.result is EditTextResult.SUCCESS
        assert model.command_manager.undo_count == undo_depth + 1
        page_text = model.doc[0].get_text()
        assert page_text.count("ZZJOIN") == 1, page_text
        assert page_text.count("QFIDANCHOR") == 1, page_text
        assert page_text.count("在編輯文字時清除舊有文字的做法") == 1, page_text
        model.ensure_page_index_built(1)
        again = model.get_text_info_at_point(1, fitz.Point(130, 85))
        assert again is not None
        assert _strip_ws(again.target_text) == _strip_ws(f"ZZJOIN {new_text}"), again.target_text
        tail = model.get_text_info_at_point(1, fitz.Point(240, 85))
        assert tail is not None and tail.target_span_id == again.target_span_id
        # One undo puts the previous (joined) heading back.
        assert model.command_manager.undo() is True
        model.ensure_page_index_built(1)
        assert model.doc[0].get_text().count("ZZJOIN") == 0
        back = model.get_text_info_at_point(1, fitz.Point(130, 85))
        assert back is not None and _strip_ws(back.target_text) == _strip_ws(new_text), back.target_text
    finally:
        model.close()


def test_s17_anchor_join_does_not_join_runs_the_app_did_not_write(tmp_path: Path):
    """Two source runs on one baseline (two fonts) were NOT written by one app
    edit: they stay two boxes, before and after an unrelated edit on the page."""
    pdf_path = tmp_path / "two_runs.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Alpha", fontsize=12.0, fontname="helv")
    page.insert_text((120, 100), "Beta", fontsize=12.0, fontname="tiro")
    page.insert_text((72, 200), "Other line", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    try:
        model.ensure_page_index_built(1)
        left = model.get_text_info_at_point(1, fitz.Point(80, 97))
        right = model.get_text_info_at_point(1, fitz.Point(125, 97))
        assert left is not None and right is not None
        assert "Alpha" in left.target_text and "Beta" not in left.target_text
        assert "Beta" in right.target_text and "Alpha" not in right.target_text
        assert left.target_span_id != right.target_span_id
        other = model.get_text_info_at_point(1, fitz.Point(80, 197))
        assert other is not None
        assert model.edit_text(
            page_num=1, rect=other.target_bbox, new_text="Other line two",
            font=other.font, size=other.size, color=other.color,
            original_text=other.target_text, target_span_id=other.target_span_id,
            target_mode="run", allow_rebuild=True, confirm_fallback=_accept_rebuild,
        ) is EditTextResult.SUCCESS
        model.ensure_page_index_built(1)
        left2 = model.get_text_info_at_point(1, fitz.Point(80, 97))
        right2 = model.get_text_info_at_point(1, fitz.Point(125, 97))
        assert left2 is not None and right2 is not None
        assert "Beta" not in left2.target_text and "Alpha" not in right2.target_text
    finally:
        model.close()


def test_find_joined_fragments_requires_one_line_exact_text():
    from model.joined_edit_runs import find_joined_fragments

    def run(sid, text, bbox, line=0, idx=0, block=0):
        return SimpleNamespace(
            span_id=sid, text=text, bbox=fitz.Rect(bbox), block_idx=block,
            line_idx=line, span_idx=idx, rotation=0,
        )

    a = run("a", "Hello ", (10, 10, 40, 20), idx=0)
    b = run("b", "世界", (40, 10, 70, 20), idx=1)
    region = fitz.Rect(0, 0, 100, 30)
    assert find_joined_fragments([b, a], "helloworld", region) is None  # text differs
    got = find_joined_fragments([b, a], "hello世界", region)
    assert got is not None and [s.span_id for s in got] == ["a", "b"]  # reading order
    # One run alone is not a join; a second line is not "one baseline".
    assert find_joined_fragments([a], "hello", region) is None
    other_line = run("c", "世界", (40, 30, 70, 40), line=1, idx=0)
    assert find_joined_fragments([a, other_line], "hello世界", fitz.Rect(0, 0, 100, 50)) is None
    # A run outside the region does not count; a stranger between members breaks it.
    far = run("f", "世界", (300, 10, 330, 20), idx=1)
    assert find_joined_fragments([a, far], "hello世界", region) is None
    stranger = run("s", "X", (40, 10, 50, 20), idx=1)
    assert find_joined_fragments([a, stranger, b], "hello世界", region) is None
    # A whitespace-only run between members rides along.
    gap = run("g", " ", (40, 10, 42, 20), idx=1)
    b2 = run("b2", "世界", (42, 10, 70, 20), idx=2)
    got = find_joined_fragments([a, gap, b2], "hello世界", region)
    assert got is not None and [s.span_id for s in got] == ["a", "g", "b2"]


def _anchor_run(span_id: str, text: str, bbox: tuple[float, float, float, float]):
    return SimpleNamespace(span_id=span_id, text=text, bbox=fitz.Rect(bbox))


def test_choose_anchor_run_ranks_text_evidence_over_distance():
    from model.pdf_text_edit import _choose_anchor_run

    anchor = fitz.Rect(100, 80, 250, 90)
    region = fitz.Rect(100, 78, 320, 92)
    near_unrelated = _anchor_run("near", "Stirling", (120, 70, 190, 76))
    exact = _anchor_run("exact", "Edited line", (100, 80, 300, 90))
    # An exact run beats a nearer run outside the region and a closer fragment.
    assert _choose_anchor_run(
        [near_unrelated, _anchor_run("frag", "Edited", (100, 80, 140, 90)), exact],
        anchor, region, "editedline", multi_show=False,
    ) is exact
    # Fragments only: a plain run drops the anchor, a grouped show picks one
    # for the caller to regroup.
    frag_a = _anchor_run("a", "Edited", (100, 80, 140, 90))
    frag_b = _anchor_run("b", "line", (145, 80, 180, 90))
    assert _choose_anchor_run(
        [near_unrelated, frag_a, frag_b], anchor, region, "editedline", multi_show=False
    ) is None
    assert _choose_anchor_run(
        [near_unrelated, frag_a, frag_b], anchor, region, "editedline", multi_show=True
    ) is frag_b  # nearest the anchor centre, as before
    # Drift (no text evidence): one run in the region is bound, several are
    # ambiguous, none (only the run outside the region) is dropped.
    drift = _anchor_run("drift", "Edi?ed line", (100, 80, 300, 90))
    assert _choose_anchor_run(
        [near_unrelated, drift], anchor, region, "editedline", multi_show=False
    ) is drift
    assert _choose_anchor_run(
        [drift, _anchor_run("other", "zzz", (110, 80, 130, 90))],
        anchor, region, "editedline", multi_show=False,
    ) is None
    assert _choose_anchor_run(
        [near_unrelated], anchor, region, "editedline", multi_show=False
    ) is None
    # An emptied edit has no text to prove anything.
    assert _choose_anchor_run([], anchor, region, "", multi_show=False) is None


def test_stale_run_anchor_is_not_rebound_to_a_run_outside_its_rect(model_with_pdf):
    """A reopen anchor whose span id no longer exists used to be re-bound to
    the nearest run on the whole page, even one nowhere near the anchor.  Over
    empty space it now resolves to nothing and the stale key is dropped."""
    model = model_with_pdf
    model.ensure_page_index_built(1)
    model._set_run_reopen_anchor_rect(0, "p0_b99_l9_s9", fitz.Rect(60, 400, 300, 420))
    model._set_run_reopen_anchor_size(0, "p0_b99_l9_s9", 12.0)

    hit = model.get_text_info_at_point(1, fitz.Point(100, 410))

    assert hit is None or hit.target_text not in {
        "Hello World", "Original text to edit", "Third block here"
    }, hit
    assert "0::p0_b99_l9_s9" not in model.run_reopen_anchors


def test_stale_run_anchor_rebinds_to_the_run_under_the_click(model_with_pdf):
    """A stale anchor rect that spans two lines re-binds to the line the click
    is on, not whichever line's centre is nearer the rect's centre."""
    model = model_with_pdf
    model.ensure_page_index_built(1)
    model._set_run_reopen_anchor_rect(0, "p0_b99_l9_s9", fitz.Rect(60, 85, 300, 230))
    model._set_run_reopen_anchor_size(0, "p0_b99_l9_s9", 12.0)

    hit = model.get_text_info_at_point(1, fitz.Point(80, 97))

    assert hit is not None
    assert hit.target_text == "Hello World", hit.target_text


def test_real_pdf_colored_background_edit_does_not_shrink_span(
    tmp_path: Path,
):
    """Editing text in test-colored-background.pdf must not shrink the span's vertical extent.

    'Smaller' symptom reproducer (manual-smaller-222143/147/151): white text on dark
    background appears more compact after editing. The inline editor already shows
    glyphs smaller than original during editing. After commit text is noticeably smaller.
    """
    import shutil
    from model.edit_commands import EditTextResult

    pdf_src = REAL_PDFS_DIR / "test-colored-background.pdf"
    if not pdf_src.exists():
        pytest.skip(f"Reproducer PDF not found: {pdf_src}")

    pdf_copy = tmp_path / "colored.pdf"
    shutil.copy2(pdf_src, pdf_copy)

    model = PDFModel()
    model.open_pdf(str(pdf_copy))
    try:
        # Deterministic target: CJK portion '前置作業操作流程' of the size-60pt heading
        # at bbox ≈ Rect(554, 270, 1030, 330). CJK content naturally routes through
        # insert_htmlbox path — no monkeypatch needed.
        model.ensure_page_index_built(1)
        hit = model.get_text_info_at_point(1, fitz.Point(720, 295))
        assert hit is not None, (
            "Could not find CJK heading span at (720, 295) on page 1 of colored-background.pdf"
        )
        assert "前置" in hit.target_text, (
            f"Expected '前置作業操作流程' heading but found: {hit.target_text!r}"
        )
        assert hit.size >= 50.0, (
            f"Expected size~60pt heading span, got size={hit.size:.1f}pt — wrong target"
        )
        height_before = float(hit.target_bbox.height)
        marker = "QFIDSMALL"

        new_text = f"{marker} {hit.target_text}"
        result = model.edit_text(
            page_num=1,
            rect=hit.target_bbox,
            new_text=new_text,
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS, (
            f"edit_text returned {result!r} instead of SUCCESS — edit was not applied"
        )

        model.ensure_page_index_built(1)
        hit_after = _find_span_with_text(model, 1, marker)
        assert hit_after is not None, (
            f"Edited marker {marker!r} not found after edit — "
            f"height_before={height_before:.2f}pt, text={hit.target_text[:30]!r}"
        )
        height_after = float(hit_after.target_bbox.height)

        assert height_after >= height_before - 1.5, (
            f"Span height shrank {height_before:.2f}pt → {height_after:.2f}pt "
            f"(font={hit.size:.2f}pt, text={hit.target_text[:30]!r}) "
            f"in colored-background.pdf — 'smaller' symptom: _line_ht under-estimated"
        )
    finally:
        model.close()


# Task 1 regression: empty member_spans must not select fast path.
def test_classify_insert_path_empty_member_spans_routes_to_htmlbox():
    from model.pdf_model import _classify_insert_path

    result = _classify_insert_path(
        new_text="hi",
        member_spans=[],
        rotation=0,
        is_vertical=False,
        preserve_multi_style=False,
        has_new_rect=False,
        needs_cjk=False,
        text_width=10.0,
        available_width=100.0,
        size=12.0,
    )
    assert result == "htmlbox", (
        "Empty member_spans means there's no anchor span for insert_text fast path; "
        "must fall back to htmlbox to avoid downstream min(member_spans, ...) crash. "
        f"Got: {result!r}"
    )


# ── Shared helpers for the sections below ──────────────────────────────────


def _open_model(path: Path, **settings) -> PDFModel:
    """``path`` open in a ``PDFModel`` built from ``TextCommitSettings(**settings)``
    (the model's own defaults when none are given) with page 1 indexed; the
    caller closes it."""
    model = PDFModel(text_commit_settings=TextCommitSettings(**settings))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _run_with_text(model: PDFModel, text: str):
    """The first run of the page-0 index whose text is exactly ``text``."""
    return next(r for r in model.block_manager.get_runs(0) if r.text == text)


def _block_style(block) -> dict[str, object]:
    """``font``/``size``/``color`` keywords of an ``edit_text`` call (or an
    ``EditTextCommand``) on ``block``."""
    return {
        "font": block.font or "helv",
        "size": float(block.size or 12.0),
        "color": tuple(block.color) if block.color else (0.0, 0.0, 0.0),
    }


def _word_rects(page: fitz.Page) -> dict[str, fitz.Rect]:
    """The rectangle of each word on ``page``, by its text."""
    return {w[4]: fitz.Rect(w[:4]) for w in page.get_text("words")}


def _protected_span(text: str, size: float, bbox: tuple, origin: tuple, rotation: int = 0):
    """A neighbour run as ``_replay_protected_spans`` receives it (one
    Helvetica span)."""
    return SimpleNamespace(
        span_id="p0",
        text=text,
        size=size,
        color=(0.0, 0.0, 0.0),
        rotation=rotation,
        font="Helvetica",
        bbox=fitz.Rect(*bbox),
        origin=fitz.Point(*origin),
    )


# ---------------------------------------------------------------------------
# F10-UNI-1: a consented rebuild must never persist U+00B7 for the requested
# text.  ``page.insert_text`` with a simple (base-14) font encodes only code
# points < 256 and writes 0xB7 ("·") for everything else (PyMuPDF getTJstr),
# so the fast insert path, the protected-span replay and the verification
# gate must all treat "not Latin-1" -- not just "CJK" -- as "needs htmlbox".
# ---------------------------------------------------------------------------

_F10_LONG = "The quick brown fox jumps over the lazy dog near the riverbank today"
_F10_SHORT = "Total due today"
# (label, replacement, expectation).  Expectations:
#   "text"    -- htmlbox renders AND extracts it faithfully: SUCCESS and the
#                requested characters are in the saved text layer.
#   "glyphs"  -- htmlbox renders it but its text layer is lossy in PyMuPDF 1.27
#                (non-BMP code points cut to 16 bits; shaped conjuncts and
#                ligatures written as their glyph ids).  Owner decision
#                OD-UNI1-COMMIT: SUCCESS with the htmlbox rendering; the glyphs
#                must be on the page (texttrace + ink), live and after
#                save/reopen.  get_text equality is NOT the contract here.
#   "refused" -- htmlbox has no glyph for it (.notdef): the rebuild would render
#                nothing, so it must roll back with the page untouched.
#   "ext_b"   -- CJK Ext-B (U+20000 and up; EXTB-SUBSET, owner decision C):
#                where a Windows Ext-B font is installed the chokepoint draws it
#                from an in-memory subset of that font, so it behaves like
#                "glyphs" (and the Ext-B glyphs must be the font's own outlines);
#                where none is installed it stays "refused".
_F10_REPLACEMENTS = [
    ("arabic", "عربي", "text"),
    ("hebrew", "עברית", "text"),
    ("thai", "ไทย", "text"),
    ("cyrillic", "Привет", "text"),
    ("euro", "€5", "text"),
    ("combining", "café", "text"),
    ("zwj", "a‍b", "text"),
    ("devanagari", "हिन्दी", "glyphs"),
    ("emoji", "\U0001F600", "glyphs"),
    ("emoji_inline", "x\U0001F600y", "glyphs"),
    ("arabic_lam_alef", "لا إله", "glyphs"),
    ("gujarati_conjunct", "ક્ષત્રિય", "glyphs"),
    ("tamil", "தமிழ்", "glyphs"),
    ("ext_b", "\U00020000", "ext_b"),
    ("emoji_and_ext_b", "\U0001F600\U00020000", "ext_b"),
    ("ext_b_run", "\U00020B9F\U0002A6D6 x \U00020000", "ext_b"),
    # Placeholders with no Unicode identity TYPED by the user: htmlbox draws
    # U+FFFD / control codes as a replacement glyph and PUA as .notdef, and a
    # typed placeholder is never acknowledgeable (F11-UNI-1 decision C only
    # lets UNTOUCHED ones through, with an explicit acknowledgement), so
    # glyph evidence must never forgive them.
    ("replacement_char", "\ufffd5", "refused"),
    ("c1_control", "a\u0080b", "refused"),
    ("pua", "\uf0b7 x", "refused"),
    ("emoji_and_replacement_char", "\U0001F600\ufffd", "refused"),
    # F16-PASTE-2: an image in pasted HTML is U+FFFC in toPlainText(); htmlbox
    # draws it as a dashed "OBJ" box and its text layer round-trips it.
    ("object_replacement_char", "x\ufffcy", "refused"),
    ("object_replacement_char_alone", "\ufffc", "refused"),
]


def _f10_reference_glyphs(text: str) -> list[tuple[str, int]]:
    """``(font, glyph id)`` of every inked glyph htmlbox draws for the
    non-ASCII part of ``text`` on a scratch page -- the glyphs the committed
    page must show.  ASCII is left out: the editor sets it in its own Latin
    font (helv), a bare htmlbox in CharisSIL; the fallback fonts htmlbox picks
    for everything else are the same either way."""
    probe = "".join(ch for ch in text if ord(ch) > 0x7F or ch.isspace())
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox(fitz.Rect(20, 20, 575, 822), probe, css="* {font-size: 11pt;}")
        glyphs = [
            (str(span["font"]), int(ch[1]))
            for span in page.get_texttrace()
            for ch in span["chars"]
            if not chr(ch[0]).isspace()
        ]
    finally:
        doc.close()
    assert glyphs and all(gid != 0 for _font, gid in glyphs), (
        f"reference render of {ascii(text)} has no inked glyphs: {glyphs}"
    )
    return glyphs


def _f10_assert_no_notdef(trace: list, where: str) -> None:
    notdef = [hex(ch[0]) for span in trace for ch in span["chars"] if ch[1] == 0]
    assert not notdef, f"{where}: .notdef glyphs on the page: {notdef}"


def _f10_assert_inked(page: fitz.Page, boxes: list[fitz.Rect], what: str, where: str) -> None:
    """The union of ``boxes`` (where ``what`` should be drawn) has ink."""
    area = fitz.Rect(boxes[0])
    for box in boxes[1:]:
        area |= box
    pix = page.get_pixmap(clip=area, dpi=144, colorspace=fitz.csGRAY, alpha=False)
    assert any(value < 128 for value in pix.samples), (
        f"{where}: no ink where {what} should be ({area})"
    )


def _f10_assert_glyphs_rendered(page: fitz.Page, requested: str, where: str) -> None:
    """The page draws every glyph htmlbox draws for ``requested`` (by font and
    glyph id, as a multiset), none of its glyphs is .notdef, and the area
    those glyphs occupy has ink."""
    trace = page.get_texttrace()
    _f10_assert_no_notdef(trace, where)
    want = Counter(_f10_reference_glyphs(requested))
    have: Counter[tuple[str, int]] = Counter()
    boxes: list[fitz.Rect] = []
    for span in trace:
        for ch in span["chars"]:
            key = (str(span["font"]), int(ch[1]))
            if key in want:
                have[key] += 1
                boxes.append(fitz.Rect(ch[3]))
    missing = want - have
    assert not missing, f"{where}: glyphs for {ascii(requested)} not drawn: {dict(missing)}"
    _f10_assert_inked(page, boxes, ascii(requested), where)


def _ext_b_font_installed() -> bool:
    from utils.cjk_ext_b_font import find_ext_b_fonts

    return bool(find_ext_b_fonts())


def _f10_assert_ext_b_drawn(page: fitz.Page, requested: str, where: str) -> None:
    """Every CJK Ext-B character of ``requested`` is drawn (texttrace, not
    get_text: the text layer is the lossy 16-bit cut) from an embedded
    EXTB-SUBSET font whose glyph for that code point has the SAME outline as
    the installed Windows Ext-B font, no .notdef anywhere, and there is ink
    where those glyphs are."""
    import io

    from fontTools.ttLib import TTFont

    from utils import cjk_ext_b_font as extb

    wanted = Counter(ord(ch) for ch in requested if extb.is_ext_b(ch))
    assert wanted, f"no Ext-B character in {ascii(requested)}"
    trace = page.get_texttrace()
    _f10_assert_no_notdef(trace, where)
    programs: dict[str, TTFont] = {}
    for font_row in page.get_fonts(full=True):
        _name, _ext, _type, buf = page.parent.extract_font(font_row[0])
        if not buf:
            continue
        try:
            program = TTFont(io.BytesIO(buf))
            ps_name = program["name"].getDebugName(6) or ""
        except Exception:
            continue
        if ps_name.startswith(extb.FONT_NAME_PREFIX):
            programs[ps_name] = program
    assert programs, f"{where}: no embedded Ext-B subset font on the page"
    sources = {font.key: font for font in extb.find_ext_b_fonts()}
    have: Counter[int] = Counter()
    boxes: list[fitz.Rect] = []
    opened: dict[str, TTFont] = {}  # each source font is read once, not once per glyph
    try:
        for span in trace:
            font_name = str(span["font"])
            if not font_name.startswith(extb.FONT_NAME_PREFIX):
                continue
            program = programs[font_name]
            reverse = {gname: cp for cp, gname in program.getBestCmap().items()}
            for ch in span["chars"]:
                gname = program.getGlyphOrder()[int(ch[1])]
                cp = reverse[gname]
                have[cp] += 1
                boxes.append(fitz.Rect(ch[3]))
                source_font = extb.font_for_codepoint(cp)
                assert source_font is not None and source_font.key in sources
                src = opened.get(source_font.key)
                if src is None:
                    src = opened[source_font.key] = TTFont(
                        str(source_font.path), fontNumber=source_font.font_number, lazy=True
                    )
                src_glyph = src["glyf"][src.getBestCmap()[cp]]
                sub_glyph = program["glyf"][gname]
                src_coords = list(src_glyph.getCoordinates(src["glyf"])[0])
                sub_coords = list(sub_glyph.getCoordinates(program["glyf"])[0])
                assert src_coords == sub_coords, f"{where}: U+{cp:X} drawn with another outline"
    finally:
        for src in opened.values():
            src.close()
    assert have == wanted, (
        f"{where}: Ext-B glyphs drawn {dict(have)} != requested {dict(wanted)}"
    )
    _f10_assert_inked(page, boxes, "the Ext-B glyphs", where)


def _f10_assert_ext_b_rows(page: fitz.Page, requested: str, where: str) -> None:
    """``ext_b`` rows: the Ext-B part per ``_f10_assert_ext_b_drawn``, the
    rest (emoji, ...) per ``_f10_assert_glyphs_rendered``."""
    from utils.cjk_ext_b_font import is_ext_b

    rest = "".join(ch for ch in requested if not is_ext_b(ch))
    if any(ord(ch) > 0x7F and not ch.isspace() for ch in rest):
        _f10_assert_glyphs_rendered(page, rest, where)
    _f10_assert_ext_b_drawn(page, requested, where)


def _f10_missing_chars(requested: str, haystack: str) -> list[str]:
    """Requested characters (NFKC, ignoring whitespace and invisible format
    characters such as ZWJ) that ``haystack`` lacks."""
    import unicodedata

    hay = unicodedata.normalize("NFKC", haystack)
    return [
        f"U+{ord(ch):04X}"
        for ch in unicodedata.normalize("NFKC", requested)
        if not ch.isspace() and unicodedata.category(ch) != "Cf" and ch not in hay
    ]


def _f10_helvetica_pdf(path: Path, line: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 11 Tf 40 700 Td (" + line.encode("latin-1")
        + b") Tj 0 -40 Td (Downstream line stays) Tj ET"
    )
    cx = doc.get_new_xref()
    doc.update_object(cx, "<<>>")
    doc.update_stream(cx, stream)
    doc.xref_set_key(page.xref, "Contents", f"{cx} 0 R")
    fx = doc.get_new_xref()
    doc.update_object(
        fx,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {fx} 0 R >> >>")
    doc.save(str(path), garbage=0)
    doc.close()


def _f10_consented_rebuild(
    tmp_path: Path,
    pdf: Path,
    probe: str,
    old: str,
    new: str,
    expect: str,
    *,
    refusal_mentions: tuple[str, ...] = (),
    refusal_reason: str | None = None,
) -> Path | None:
    """Run one consented rebuild and check it against ``expect``; returns the
    saved file of a commit (``None`` for a refusal)."""
    assert expect in ("text", "glyphs", "refused", "ext_b"), expect
    if expect == "ext_b":
        expect = "ext_b" if _ext_b_font_installed() else "refused"
    model = _open_model(pdf, engine="tiered")
    try:
        block = _find_block(model, 0, probe)
        assert block is not None
        before = model.doc[0].get_text()
        requested = (block.text or "").replace(old, new)
        assert requested != block.text
        try:
            result = model.edit_text(
                1,
                fitz.Rect(block.layout_rect),
                requested,
                **_block_style(block),
                original_text=block.text,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )
        except _RebuildRolledBack as exc:
            assert expect == "refused", f"a renderable script was refused: {ascii(new)}: {exc}"
            assert model.doc[0].get_text() == before, "refusal must leave the page untouched"
            for needle in refusal_mentions:
                assert needle in str(exc), f"refusal reason lacks {needle!r}: {exc}"
            if refusal_reason is not None:
                # ZH-REFUSALS: the stable code the Controller maps to a zh-TW sentence.
                assert exc.reason.value == refusal_reason, f"{exc.reason!r}: {exc}"
            return None
        assert expect != "refused", f"SUCCESS although this rebuild must be refused: {ascii(new)}"
        assert not refusal_mentions, "a refusal was expected"
        assert result is EditTextResult.SUCCESS
        live = model.doc[0].get_text()
        assert "·" not in live, f"U+00B7 substituted on the live page: {ascii(live)}"
        if expect == "glyphs":
            _f10_assert_glyphs_rendered(model.doc[0], new, "live page")
        elif expect == "ext_b":
            _f10_assert_ext_b_rows(model.doc[0], new, "live page")
        out = tmp_path / f"saved_{pdf.name}"
        model.save_as(str(out))
        reopened = fitz.open(str(out))
        try:
            saved = reopened[0].get_text()
            if expect == "glyphs":
                _f10_assert_glyphs_rendered(reopened[0], new, "after save/reopen")
            elif expect == "ext_b":
                _f10_assert_ext_b_rows(reopened[0], new, "after save/reopen")
        finally:
            reopened.close()
        if expect == "text":
            assert "·" not in saved, f"U+00B7 persisted after save/reopen: {ascii(saved)}"
            missing = _f10_missing_chars(new, saved)
            assert not missing, (
                f"SUCCESS but requested chars lost after save/reopen: {missing} in {ascii(saved)}"
            )
        return out
    finally:
        model.close()


@pytest.mark.parametrize("line_label,line", [("long", _F10_LONG), ("short", _F10_SHORT)])
@pytest.mark.parametrize("label,replacement,expect", _F10_REPLACEMENTS)
def test_consented_rebuild_never_substitutes_middle_dot_for_non_latin1(
    tmp_path: Path, line_label: str, line: str, label: str, replacement: str, expect: str
) -> None:
    pdf = tmp_path / f"f10_{line_label}_{label}.pdf"
    _f10_helvetica_pdf(pdf, line)
    _f10_consented_rebuild(tmp_path, pdf, "today", "today", replacement, expect)


@pytest.mark.parametrize("line_label,line", [("long", _F10_LONG), ("short", _F10_SHORT)])
@pytest.mark.parametrize("replacement", ["\U0001F600\U0001F44D", "हिन्दी"])
def test_consented_rebuild_of_a_whole_line_with_a_lossy_text_layer_commits(
    tmp_path: Path, line_label: str, line: str, replacement: str
) -> None:
    """OD-UNI1-COMMIT: when EVERY requested character has a lossy htmlbox
    text layer there is no text left for the presence gates to compare; the
    rendered glyphs are the only evidence, and they must be there."""
    pdf = tmp_path / f"f10_whole_{line_label}.pdf"
    _f10_helvetica_pdf(pdf, line)
    _f10_consented_rebuild(tmp_path, pdf, "today", line, replacement, "glyphs")


@pytest.mark.parametrize("label,replacement,expect", [
    ("arabic", "عربي", "text"),
    ("euro", "€5", "text"),
    ("emoji", "\U0001F600", "glyphs"),
    ("ext_b", "\U00020000", "ext_b"),
])
def test_consented_cid_rebuild_never_substitutes_middle_dot(
    tmp_path: Path, label: str, replacement: str, expect: str
) -> None:
    """Same contract on the ``type0_unicode_unmapped`` leg (Identity-H subset
    source whose ToUnicode lacks the requested characters)."""
    from test_scripts.type0_fixture_builder import build_identity_h_fixture

    fixture = build_identity_h_fixture("Buffer Tank", subset=True)
    pdf = tmp_path / f"f10_cid_{label}.pdf"
    fixture.doc.save(str(pdf))
    fixture.doc.close()
    _f10_consented_rebuild(tmp_path, pdf, "Buffer", "Tank", replacement, expect)


def test_consented_rebuild_rolls_back_when_the_page_does_not_draw_the_lossy_glyphs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lossy text layer is accepted only on glyph evidence: if the real
    insert draws nothing for the emoji (while a scratch render would), the
    rebuild must still roll back."""
    import model.pdf_text_edit as pdf_text_edit_module

    real_insert = pdf_text_edit_module.insert_htmlbox_tracked

    def drop_emoji_on_the_document(page, rect, html, *, scratch=False, **kwargs):
        if not scratch:
            html = html.replace("\U0001F600", "")
        return real_insert(page, rect, html, scratch=scratch, **kwargs)

    monkeypatch.setattr(
        pdf_text_edit_module, "insert_htmlbox_tracked", drop_emoji_on_the_document
    )
    for line_label, line in (("long", _F10_LONG), ("short", _F10_SHORT)):
        pdf = tmp_path / f"f10_dropped_emoji_{line_label}.pdf"
        _f10_helvetica_pdf(pdf, line)
        _f10_consented_rebuild(
            tmp_path, pdf, "today", "today", "ok \U0001F600", "refused",
            refusal_reason="glyphs_not_drawn",
        )


@pytest.mark.parametrize("line_label,line", [("long", _F10_LONG), ("short", _F10_SHORT)])
@pytest.mark.parametrize("replacement", ["\U00020000", "ok \U0001F600\U00020B9F"])
def test_consented_ext_b_rebuild_refuses_with_a_clear_reason_when_no_ext_b_font_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line_label: str, line: str, replacement: str
) -> None:
    """EXTB-SUBSET: off Windows, or with neither SimSun-ExtB nor MingLiU-ExtB
    installed, an Ext-B consented rebuild keeps refusing (page untouched) and
    the reason names the fonts it needs."""
    import utils.cjk_ext_b_font as extb

    monkeypatch.setattr(extb, "find_ext_b_fonts", lambda: ())
    pdf = tmp_path / f"f10_extb_nofont_{line_label}.pdf"
    _f10_helvetica_pdf(pdf, line)
    _f10_consented_rebuild(
        tmp_path,
        pdf,
        "today",
        "today",
        replacement,
        "refused",
        refusal_mentions=("CJK Ext-B", "simsunb.ttf", "mingliub.ttc"),
        refusal_reason="ext_b_font_missing",
    )


# Upper bounds for the saved-file growth an Ext-B consented rebuild may cost
# (measured values are in the EXTB-SUBSET PITFALLS entry).  The whole-font
# @font-face alternative adds 11.7 MB (SimSun-ExtB) / 17.2 MB (MingLiU-ExtB)
# per saved file.
_EXT_B_SIZE_BOUND_FEW = 16 * 1024
_EXT_B_SIZE_BOUND_MANY = 64 * 1024


def _ext_b_saved_size_delta(tmp_path: Path, label: str, ext_b: str) -> int:
    """Saved size of a consented rebuild to ``ok <emoji><ext_b>`` minus the
    same rebuild to ``ok <emoji>``: the emoji forces htmlbox (and its
    fallback font) in both arms, so the difference is the Ext-B cost."""
    sizes = []
    for arm, replacement in (("base", "ok \U0001F600"), ("extb", "ok \U0001F600" + ext_b)):
        pdf = tmp_path / f"f10_size_{label}_{arm}.pdf"
        _f10_helvetica_pdf(pdf, _F10_SHORT)
        expect = "ext_b" if arm == "extb" else "glyphs"
        out = _f10_consented_rebuild(tmp_path, pdf, "today", "today", replacement, expect)
        assert out is not None
        sizes.append(out.stat().st_size)
    return sizes[1] - sizes[0]


def test_consented_ext_b_rebuild_keeps_the_saved_file_small(tmp_path: Path) -> None:
    """EXTB-SUBSET: the saved file grows by the subset of the needed glyphs,
    not by the 11.7 MB / 17.2 MB Ext-B font."""
    if not _ext_b_font_installed():
        pytest.skip("no Windows CJK Ext-B font installed")
    few = _ext_b_saved_size_delta(tmp_path, "few", "\U00020000\U00020B9F")
    many_text = "".join(chr(0x20001 + 97 * i) for i in range(40))
    many = _ext_b_saved_size_delta(tmp_path, "many", many_text)
    print(f"EXTB-SUBSET saved-size delta: 2 glyphs {few} B, 40 glyphs {many} B")
    assert 0 < few <= _EXT_B_SIZE_BOUND_FEW, few
    assert 0 < many <= _EXT_B_SIZE_BOUND_MANY, many


def test_classify_insert_path_routes_non_latin1_text_to_htmlbox() -> None:
    """The fast ``insert_text`` path can encode only code points < 256 with a
    simple font; anything else must take htmlbox (CJK is not the only case)."""
    span = SimpleNamespace(bbox=fitz.Rect(40, 690, 140, 702))
    kwargs = dict(
        member_spans=[span],
        rotation=0,
        is_vertical=False,
        preserve_multi_style=False,
        has_new_rect=False,
        needs_cjk=False,
        text_width=40.0,
        available_width=400.0,
        size=11.0,
    )
    assert pdf_model_module._classify_insert_path(new_text="café ñ ©", **kwargs) == "fast"
    for text in ("€5", "عرب", "При", "\U0001F600", "a‍b", "café"):
        assert pdf_model_module._classify_insert_path(new_text=text, **kwargs) == "htmlbox", ascii(text)


def test_rebuild_verification_refuses_when_requested_chars_are_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backstop: even if an insert path drops characters (forced fast path
    here), verification must roll back instead of reporting SUCCESS."""
    import model.pdf_text_edit as pdf_text_edit_module

    monkeypatch.setattr(pdf_text_edit_module, "_classify_insert_path", lambda **_kw: "fast")
    # The emoji rows: a lossy htmlbox text layer is forgiven only when the
    # htmlbox glyphs are on the page; insert_text's U+00B7 is not that glyph.
    for replacement in ("عربي", "\U0001F600", "x\U0001F600y", "हिन्दी"):
        for line_label, line in (("long", _F10_LONG), ("short", _F10_SHORT)):
            pdf = tmp_path / f"f10_forced_fast_{line_label}.pdf"
            _f10_helvetica_pdf(pdf, line)
            _f10_consented_rebuild(tmp_path, pdf, "today", "today", replacement, "refused")


# --- F15-VM2-RTL: the placement measures the rewrite's START, not its first drawn glyph ---
# MuPDF draws a right-to-left run rightmost glyph first, and a replacement that
# starts with an empty line draws its first glyph on line 2.  The target
# (``_start_glyph_origin``, a run's ``origin``) is geometric: the text start
# along the writing direction on the first line.  Measuring the probe at
# ``chars[0]`` moved a rebuilt Hebrew word left by its own width and pulled a
# pushed-down line back onto the original baseline.

_F15_SHALOM = "שלום"  # logical order, as typed
_F15_OLAM = "עולם"


def _f15_is_hebrew(code: int) -> bool:
    return 0x0590 <= code <= 0x05FF


def _f15_hebrew_origins(page: fitz.Page) -> list[tuple[float, float]]:
    return [
        (float(ch[2][0]), float(ch[2][1]))
        for span in page.get_texttrace()
        for ch in span["chars"]
        if _f15_is_hebrew(ch[0])
    ]


def _f15_rtl_pdf(path: Path, text: str = _F15_SHALOM) -> None:
    """A right-aligned Hebrew line (``text``) drawn by MuPDF (glyphs drawn
    right to left) and a Latin label further down."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(
        fitz.Rect(300, 280, 520, 310),
        f'<p dir="rtl" style="text-align:right">{text}</p>',
        css="p{font-size:14pt}",
    )
    page.insert_text((72, 400), "Below", fontsize=12, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


def _f15_hebrew_runs(model: PDFModel) -> list:
    return [
        r for r in model.block_manager.get_runs(0) if any(_f15_is_hebrew(ord(c)) for c in r.text)
    ]


@pytest.mark.parametrize("append", ["ו", " " + _F15_OLAM])
def test_f15vm2_rtl_rebuild_keeps_the_runs_right_edge_and_baseline(
    tmp_path: Path, append: str
) -> None:
    """A consented rebuild of a Hebrew run keeps the run's start and its
    baseline.  The first DRAWN glyph is the rightmost one, and aligning that
    one's origin moved the whole rewrite left by its own width (27 pt /
    51 pt, F15-VM2-RTL).  The start of a right-to-left run is its RIGHT edge
    (D-RTL-GROW, owner decision after round 15: the longer word grows to the
    left); it used to be the leftmost glyph origin, so the word grew right."""
    pdf = tmp_path / "f15_rtl.pdf"
    _f15_rtl_pdf(pdf)
    model = _open_model(pdf, engine="legacy")
    try:
        (run,) = _f15_hebrew_runs(model)
        right, oy = float(run.bbox.x1), float(run.origin.y)

        def _right_edge() -> float:
            return max(
                float(ch[3][2])
                for span in model.doc[0].get_texttrace()
                for ch in span["chars"]
                if _f15_is_hebrew(ch[0])
            )

        assert _right_edge() == pytest.approx(right, abs=0.05)
        new_text = run.text + append
        result = model.edit_text(
            1, fitz.Rect(run.bbox), new_text, font="helv", size=14.0,
            original_text=run.text, target_span_id=run.span_id, target_mode="run",
            allow_rebuild=True, confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS, result
        after = _f15_hebrew_origins(model.doc[0])
        assert len(after) == len(new_text.replace(" ", "")), after
        assert _right_edge() == pytest.approx(right, abs=_VM2_ORIGIN_TOL), (right, after)
        assert min(x for x, _ in after) < float(run.origin.x) - 2.0, after  # grew left
        assert all(abs(y - oy) <= _VM2_ORIGIN_TOL for _, y in after), (oy, after)
        assert _vm2_first_glyph(model.doc[0], "Below")[:2] == pytest.approx((72.0, 400.0), abs=0.05)
    finally:
        model.close()


def _f15_blank_line_push(model: PDFModel, text: str, size: float) -> float:
    """How far htmlbox draws ``text``'s first glyph below where it draws it
    without ``text``'s leading line breaks (same markup builders as the edit)."""
    css = model._build_insert_css(size, (0, 0, 0), "helv")
    ys = []
    for variant in (text, text.lstrip("\n")):
        doc = fitz.open()
        try:
            page = doc.new_page(width=595, height=842)
            html = model._convert_text_to_html(variant, size, (0, 0, 0), latin_font="helv")
            page.insert_htmlbox(fitz.Rect(100, 100, 400, 400), html, css=css)
            ys.append(float(page.get_texttrace()[0]["chars"][0][2][1]))
        finally:
            doc.close()
    return ys[0] - ys[1]


@pytest.mark.parametrize("new_text", ["\nab", "\n\nab"])
def test_f15vm2_a_leading_blank_line_moves_the_text_down_instead_of_being_cancelled(
    tmp_path: Path, new_text: str
) -> None:
    """Pressing Enter before the text pushes it down: the rewrite's (empty)
    first line takes the original baseline and the text is drawn the
    htmlbox blank-line height lower, at the original x.  Aligning the first
    drawn glyph (on line 2) to the original baseline cancelled the new line."""
    pdf = tmp_path / "f15_newline.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 300), "ab", fontsize=14, fontname="helv")
    page.insert_text((72, 400), "Far below", fontsize=14, fontname="helv")
    doc.save(str(pdf), garbage=0)
    doc.close()
    model = _open_model(pdf, engine="legacy")
    try:
        push = _f15_blank_line_push(model, new_text, 14.0)
        assert push > 7.0, push  # a blank line is a real line
        result, _run = _vm2_edit(model, "ab", new_text)
        assert result is EditTextResult.SUCCESS, result
        x1, y1, size1 = _vm2_first_glyph(model.doc[0], "ab")
        assert abs(size1 - 14.0) <= 0.05
        assert abs(x1 - 72.0) <= _VM2_ORIGIN_TOL, x1
        assert abs(y1 - (300.0 + push)) <= _VM2_ORIGIN_TOL, (y1, 300.0 + push)
        assert _vm2_first_glyph(model.doc[0], "Far below")[:2] == pytest.approx((72.0, 400.0), abs=0.05)
    finally:
        model.close()


_F15_ALIGN_TARGET = fitz.Point(250.0, 400.0)
_F15_ALIGN_CSS = "span { font-size: 14pt; }"


def _f15_first_glyph_y(html: str) -> float:
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox(fitz.Rect(100, 100, 400, 400), html, css=_F15_ALIGN_CSS)
        return float(page.get_texttrace()[0]["chars"][0][2][1])
    finally:
        doc.close()


def _f15_aligned_glyphs(html: str, rotate: int) -> list[tuple[str, float, float]]:
    """Glyphs ``(char, x, y)`` that ``insert_htmlbox`` draws into the box
    ``_align_htmlbox_rect`` returns for ``_F15_ALIGN_TARGET``."""
    from model.pdf_text_edit import _align_htmlbox_rect

    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        box = fitz.Rect(100, 100, 400, 400) if rotate in (0, 180) else fitz.Rect(150, 200, 350, 600)
        placed = _align_htmlbox_rect(
            page, box, html, _F15_ALIGN_CSS, origin=_F15_ALIGN_TARGET, rotate=rotate, scale_low=1
        )
        assert placed.width == pytest.approx(box.width) and placed.height == pytest.approx(box.height)
        page.insert_htmlbox(placed, html, css=_F15_ALIGN_CSS, rotate=rotate)
        return [
            (chr(ch[0]), float(ch[2][0]), float(ch[2][1]))
            for span in page.get_texttrace()
            for ch in span["chars"]
        ]
    finally:
        doc.close()


# Unit step from one line to the next per ``insert_htmlbox`` rotate (the
# text turns by -rotate: rotate 90 reads up, its lines stack to the right).
_F15_LINE_STEP = {0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0), 270: (-1.0, 0.0)}


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
@pytest.mark.parametrize("breaks", [0, 1, 2])
def test_f15vm2_align_htmlbox_rect_puts_the_first_line_start_on_the_origin(
    breaks: int, rotate: int
) -> None:
    """The text start of the FIRST line lands on the origin, in every
    rotation; leading blank lines then push the text by their htmlbox
    height in the line-stacking direction (not pulled back onto it)."""
    html = "<br>" * breaks + "<span>ab</span>"
    push = _f15_first_glyph_y(html) - _f15_first_glyph_y("<span>ab</span>")
    if breaks:
        assert push > 7.0, push
    glyphs = _f15_aligned_glyphs(html, rotate)
    first = next(g for g in glyphs if g[0] == "a")
    step_x, step_y = _F15_LINE_STEP[rotate]
    want = (_F15_ALIGN_TARGET.x + step_x * push, _F15_ALIGN_TARGET.y + step_y * push)
    assert (first[1], first[2]) == pytest.approx(want, abs=_VM2_ORIGIN_TOL), (rotate, glyphs, push)


def test_f15vm2_align_htmlbox_rect_puts_a_right_to_left_word_by_its_start() -> None:
    """Hebrew is drawn rightmost glyph first; the box is aligned by the
    text's start along the line (its leftmost glyph origin, the measure
    ``_start_glyph_origin`` gives the original run), not by the first drawn
    glyph."""
    glyphs = _f15_aligned_glyphs(f"<span>{_F15_SHALOM} {_F15_OLAM}</span>", 0)
    hebrew = [g for g in glyphs if _f15_is_hebrew(ord(g[0]))]
    assert len(hebrew) == 8, glyphs
    assert min(g[1] for g in hebrew) == pytest.approx(_F15_ALIGN_TARGET.x, abs=_VM2_ORIGIN_TOL), glyphs
    assert all(abs(g[2] - _F15_ALIGN_TARGET.y) <= _VM2_ORIGIN_TOL for g in hebrew), glyphs


def test_f15vm2_protected_rtl_neighbours_are_replayed_on_their_own_start(tmp_path: Path) -> None:
    """Protected Hebrew neighbours (index runs: ``origin`` = the leftmost
    glyph) are replayed with their leftmost glyph on that origin, not shifted
    left by their own width onto the other word.  Same-font fixture: the
    replay has the original width, so both edges hold; the edge a replay
    keeps (the RIGHT one, D-RTL-GROW) is pinned by test_rtl_edit_growth.py."""
    pdf = tmp_path / "f15_rtl_neighbours.pdf"
    doc = fitz.open()
    src = doc.new_page(width=595, height=842)
    src.insert_htmlbox(
        fitz.Rect(300, 280, 520, 310),
        f'<p dir="rtl" style="text-align:right">{_F15_SHALOM} {_F15_OLAM}</p>',
        css="p{font-size:14pt}",
    )
    doc.save(str(pdf), garbage=0)
    doc.close()
    model = _open_model(pdf, engine="legacy")
    try:
        runs = _f15_hebrew_runs(model)
        assert len(runs) == 2, [r.text for r in runs]
        out = fitz.open()
        try:
            page = out.new_page(width=595, height=842)
            with font_compaction_scope(out):
                model._replay_protected_spans(page, runs)
            drawn = _f15_hebrew_origins(page)
            assert len(drawn) == 8, drawn
            for run in sorted(runs, key=lambda r: float(r.origin.x)):
                # the run's own glyphs: those inside its original extent
                own = [x for x, _ in drawn if float(run.bbox.x0) - 0.5 <= x < float(run.bbox.x1)]
                assert own, (run.origin, drawn)
                assert min(own) == pytest.approx(float(run.origin.x), abs=_VM2_ORIGIN_TOL), (run.origin, drawn)
            assert min(x for x, _ in drawn) == pytest.approx(
                min(float(r.origin.x) for r in runs), abs=_VM2_ORIGIN_TOL
            ), drawn
            assert model._validate_protected_spans(page, runs)
        finally:
            out.close()
    finally:
        model.close()


def test_f15vm2_push_down_keeps_a_right_to_left_line_on_its_left_edge(tmp_path: Path) -> None:
    """Guard (passes before the F15 fix): the push-down replays a Hebrew line
    with its leftmost glyph where it was.  Its ``dict`` span ``origin`` is
    the first glyph in drawing order (the rightmost one), so a geometric
    measure on the replay needs a geometric target too, or the line moves
    right by its width.  Same-font fixture: both edges hold; the edge the
    push-down keeps (the RIGHT one, D-RTL-GROW) is pinned by
    test_rtl_edit_growth.py."""
    pdf = tmp_path / "f15_pushdown_rtl.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Edited line", fontsize=12, fontname="helv")
    page.insert_htmlbox(
        fitz.Rect(60, 120, 400, 150),
        f'<p dir="rtl">{_F15_SHALOM} {_F15_OLAM}</p>',
        css="p{font-size:14pt}",
    )
    doc.save(str(pdf), garbage=0)
    doc.close()
    model = _open_model(pdf, engine="legacy")
    try:
        page = model.doc[0]
        before = _f15_hebrew_origins(page)
        assert len(before) == 8, before
        x_before = min(x for x, _ in before)
        y_before = before[0][1]
        # the real caller (_apply_redact_insert) pushes down inside this scope
        with font_compaction_scope(model.doc):
            model._push_down_overlapping_text(
                page, fitz.Rect(page.rect), above_y=105.0, new_bottom=160.0,
                edit_x0=60.0, edit_x1=400.0,
            )
        after = _f15_hebrew_origins(page)
        assert len(after) == 8, after
        assert min(x for x, _ in after) == pytest.approx(x_before, abs=_VM2_ORIGIN_TOL), (before, after)
        assert all(y > y_before + 5.0 for _, y in after), (y_before, after)
        assert len({round(y, 1) for _, y in after}) == 1, after
    finally:
        model.close()


# --- F15-RTL-ORDER (round 16): index run text is LOGICAL order -----------------
# MuPDF's text extraction already hands back right-to-left text in logical order
# (``rawdict`` chars rightmost glyph first, ``get_text`` the word as typed).
# The run parser re-sorted every character by x, so a Hebrew word was indexed
# visually ("םולש" for shalom): the editor showed it mirrored and every rebuild
# (htmlbox draws its input as logical text) drew the word mirrored.  The index
# contract: text is logical, geometry (bbox, origin) is visual.

_F15_TWO_WORDS = f"{_F15_SHALOM} {_F15_OLAM}"


def _f16_reading(page: fitz.Page, rect: fitz.Rect | None = None) -> str:
    """The Hebrew letters on ``page`` as a reader meets them: right to left."""
    glyphs = [
        (float(ch[2][0]), chr(ch[0]))
        for span in page.get_texttrace()
        for ch in span["chars"]
        if _f15_is_hebrew(ch[0]) and (rect is None or rect.x0 - 0.5 <= float(ch[2][0]) < rect.x1)
    ]
    return "".join(letter for _x, letter in sorted(glyphs, reverse=True))


def test_f16_rtl_order_index_runs_hold_logical_text_and_visual_geometry(tmp_path: Path) -> None:
    pdf = tmp_path / "f16_rtl_two_words.pdf"
    _f15_rtl_pdf(pdf, _F15_TWO_WORDS)
    model = _open_model(pdf, engine="legacy")
    try:
        runs = _f15_hebrew_runs(model)
        # list order = reading order of the line: the rightmost word is first
        assert [r.text for r in runs] == [_F15_SHALOM, _F15_OLAM]
        assert [r.span_idx for r in runs] == [0, 1]
        assert float(runs[0].bbox.x0) > float(runs[1].bbox.x1) - 0.5  # geometry stays visual
        assert float(runs[0].origin.x) == pytest.approx(float(runs[0].bbox.x0), abs=1.0)
        (para,) = [p for p in model.block_manager.get_paragraphs(0) if "Below" not in p.text]
        assert para.text == _F15_TWO_WORDS
        assert para.run_ids == [r.span_id for r in runs]
        # the run ids resolve to the same runs the list holds
        for run in runs:
            assert model.block_manager.find_run_by_id(0, run.span_id) is run
    finally:
        model.close()


@pytest.mark.parametrize("append", ["ו", " " + _F15_OLAM])
def test_f16_rtl_order_rebuild_draws_the_word_in_the_order_typed(
    tmp_path: Path, append: str
) -> None:
    """The reported scenario: appending one letter (or a word) to a Hebrew
    run drew the word mirrored (original rightmost glyph shin, rebuilt
    rightmost glyph final mem)."""
    pdf = tmp_path / "f16_rtl_rebuild.pdf"
    _f15_rtl_pdf(pdf)
    model = _open_model(pdf, engine="legacy")
    try:
        (run,) = _f15_hebrew_runs(model)
        assert run.text == _F15_SHALOM
        assert _f16_reading(model.doc[0]) == _F15_SHALOM
        new_text = run.text + append
        result = model.edit_text(
            1, fitz.Rect(run.bbox), new_text, font="helv", size=14.0,
            original_text=run.text, target_span_id=run.span_id, target_mode="run",
            allow_rebuild=True, confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS, result
        assert _f16_reading(model.doc[0]) == new_text.replace(" ", "")
        # and the index of the rebuilt page reads back what was typed
        rebuilt = _f15_hebrew_runs(model)
        assert [r.text for r in rebuilt] == new_text.split(" ")
    finally:
        model.close()


def test_f16_rtl_order_protected_neighbours_are_replayed_in_logical_order(tmp_path: Path) -> None:
    """A Hebrew neighbour the edit replays (``_replay_protected_spans``) is
    handed the index's run text; it came back mirrored."""
    pdf = tmp_path / "f16_rtl_neighbours.pdf"
    _f15_rtl_pdf(pdf, _F15_TWO_WORDS)
    model = _open_model(pdf, engine="legacy")
    try:
        runs = _f15_hebrew_runs(model)
        assert [r.text for r in runs] == [_F15_SHALOM, _F15_OLAM]
        out = fitz.open()
        try:
            page = out.new_page(width=595, height=842)
            with font_compaction_scope(out):
                model._replay_protected_spans(page, runs)
            for run in runs:
                assert _f16_reading(page, fitz.Rect(run.bbox)) == run.text
            assert model._validate_protected_spans(page, runs)
        finally:
            out.close()
    finally:
        model.close()


def test_f16_rtl_order_char_context_matches_the_run_text(tmp_path: Path) -> None:
    """``get_char_context_at_point`` pairs text with glyph rectangles by index;
    its text is the run's logical text, rectangle ``i`` is glyph ``i``."""
    pdf = tmp_path / "f16_rtl_context.pdf"
    _f15_rtl_pdf(pdf)
    model = _open_model(pdf, engine="legacy")
    try:
        (run,) = _f15_hebrew_runs(model)
        centre = fitz.Point(
            (run.bbox.x0 + run.bbox.x1) / 2.0, (run.bbox.y0 + run.bbox.y1) / 2.0
        )
        context = model.get_char_context_at_point(1, centre)
        assert context is not None
        text, hit_index, rects = context
        assert text == run.text == _F15_SHALOM
        assert len(rects) == len(text)
        # logical order = rightmost glyph first
        assert [round(r.x0, 1) for r in rects] == sorted((round(r.x0, 1) for r in rects), reverse=True)
        assert fitz.Rect(rects[hit_index]).contains(centre)
    finally:
        model.close()


def test_f16_rtl_order_multi_style_colors_follow_the_logical_text() -> None:
    """``_build_multi_style_html`` diffs the new text against the member runs'
    text to inherit colours; the runs must be taken in reading order."""
    shalom = SimpleNamespace(
        text=_F15_SHALOM, color=(1.0, 0.0, 0.0), bbox=fitz.Rect(330, 295, 360, 309),
        block_idx=0, line_idx=0, span_idx=0,
    )
    olam = SimpleNamespace(
        text=_F15_OLAM, color=(0.0, 0.0, 1.0), bbox=fitz.Rect(301, 295, 327, 309),
        block_idx=0, line_idx=0, span_idx=1,
    )
    model = PDFModel()
    try:
        html = model._build_multi_style_html(_F15_TWO_WORDS, [olam, shalom], (0.0, 0.0, 0.0))
    finally:
        model.close()
    assert "rgb(255, 0, 0)" in html and "rgb(0, 0, 255)" in html, html
    red = html.index("rgb(255, 0, 0)")
    blue = html.index("rgb(0, 0, 255)")
    # the red span carries shalom and precedes the blue one that carries olam
    assert red < html.index(_F15_SHALOM) < blue < html.index(_F15_OLAM), html


def test_protected_span_replay_keeps_non_latin1_text() -> None:
    """A protected neighbour span with non-Latin-1 text must be replayed
    intact, not re-written through ``insert_text(helv)`` as U+00B7."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    model = PDFModel()
    try:
        span = _protected_span("Price €5 عربي При", 11.0, (40, 690, 300, 704), (40, 700))
        # The real caller (_apply_redact_insert) replays inside this scope.
        with font_compaction_scope(doc):
            model._replay_protected_spans(page, [span])
        text = page.get_text()
        assert "·" not in text, ascii(text)
        assert not _f10_missing_chars(span.text, text), ascii(text)
        assert model._validate_protected_spans(page, [span])
    finally:
        model.close()
        doc.close()


@pytest.mark.parametrize("text,expect_valid", [
    ("Note \U0001F600 ok", True),
    ("हिन्दी text", True),
    ("Han \U00020000 ext", "ext_b"),
])
def test_protected_span_replay_with_a_lossy_text_layer(text: str, expect_valid: bool | str) -> None:
    """OD-UNI1-COMMIT, protected neighbours: a span whose htmlbox text layer
    is lossy (emoji, Devanagari) validates on glyph evidence instead of
    refusing the whole edit; a CJK Ext-B span validates when a Windows Ext-B
    font is installed (EXTB-SUBSET) and fails validation (.notdef) when none
    is."""
    ext_b_row = expect_valid == "ext_b"
    if ext_b_row:
        expect_valid = _ext_b_font_installed()

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    model = PDFModel()
    try:
        span = _protected_span(text, 11.0, (40, 690, 300, 704), (40, 700))
        with font_compaction_scope(doc):
            model._replay_protected_spans(page, [span])
        assert "·" not in page.get_text()
        assert model._validate_protected_spans(page, [span]) is expect_valid
        if expect_valid and ext_b_row:
            _f10_assert_ext_b_drawn(page, text, "replayed protected span")
        elif expect_valid:
            _f10_assert_glyphs_rendered(page, text, "replayed protected span")
    finally:
        model.close()
        doc.close()


def test_protected_ext_b_span_fails_validation_without_an_ext_b_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EXTB-SUBSET font-missing path for a replayed neighbour: .notdef, so the
    span is not intact and the edit refuses."""
    import utils.cjk_ext_b_font as extb

    monkeypatch.setattr(extb, "find_ext_b_fonts", lambda: ())
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    model = PDFModel()
    try:
        span = _protected_span("Han \U00020000 ext", 11.0, (40, 690, 300, 704), (40, 700))
        with font_compaction_scope(doc):
            model._replay_protected_spans(page, [span])
        assert model._validate_protected_spans(page, [span]) is False
    finally:
        model.close()
        doc.close()


def test_protected_span_validation_fails_when_the_lossy_glyphs_are_not_drawn() -> None:
    """Glyph evidence is read from the page: a page that lacks the span
    (nothing replayed) never validates, lossy text layer or not."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    model = PDFModel()
    try:
        span = _protected_span("Note \U0001F600 ok", 11.0, (40, 690, 300, 704), (40, 700))
        page.insert_text((40, 700), "Note ok", fontsize=11.0, fontname="helv")
        assert model._validate_protected_spans(page, [span]) is False
    finally:
        model.close()
        doc.close()


# ── F13-VF-3: a replayed neighbour keeps its size and baseline ──
# ``insert_htmlbox(box=the span's own tight bbox, scale_low=0)`` laid the
# neighbour out on a taller line box than the bbox and let MuPDF shrink it
# (60 pt -> 43 pt, 11 pt -> 9.55 pt) and re-anchor it; the validator only read
# the text back, so the shrunk neighbour "passed".


def _f13vf3_glyphs(page: fitz.Page) -> list[tuple[float, tuple[float, float]]]:
    """``(size, origin)`` of every glyph the page draws, in drawing order."""
    return [
        (float(span["size"]), (float(ch[2][0]), float(ch[2][1])))
        for span in page.get_texttrace()
        for ch in span.get("chars", ())
    ]


_F13VF3_CASES = {
    # the finding's two documents: a 60 pt CJK neighbour whose bbox is one em
    # tall, a curly-quote neighbour on a 12.82 pt line
    "cjk_60pt_tight_bbox": ("前置作業操作流程", 60.0, (100, 300, 520, 360), (100, 350), 0),
    "curly_quote_12pt": ("‘Asian", 12.82, (154, 314, 200, 327), (154, 324), 0),
    "euro_cyrillic_11pt": ("Price €5 При", 11.0, (40, 690, 300, 704), (40, 700), 0),
    "quarter_turn_90": ("Price €5 При", 11.0, (300, 400, 314, 520), (310, 520), 90),
    "quarter_turn_270": ("Price €5 При", 11.0, (300, 400, 314, 520), (300, 400), 270),
    "half_turn_180": ("Price €5 При", 11.0, (200, 300, 340, 314), (340, 310), 180),
}


@pytest.mark.parametrize("case", sorted(_F13VF3_CASES))
def test_f13vf3_replayed_neighbour_keeps_its_size_and_origin(case: str) -> None:
    text, size, bbox, origin, rotation = _F13VF3_CASES[case]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    model = PDFModel()
    try:
        span = _protected_span(text, size, bbox, origin, rotation)
        with font_compaction_scope(doc):
            model._replay_protected_spans(page, [span])
        glyphs = _f13vf3_glyphs(page)
        assert glyphs, "the neighbour must be drawn"
        assert all(abs(g_size - size) <= 0.05 for g_size, _o in glyphs), sorted(
            {round(g[0], 2) for g in glyphs}
        )
        first = glyphs[0][1]
        assert abs(first[0] - origin[0]) <= 0.5 and abs(first[1] - origin[1]) <= 0.5, (
            first,
            origin,
        )
        # one line: the coordinate across the text direction is shared
        across = 0 if rotation in (90, 270) else 1
        spread = max(o[across] for _s, o in glyphs) - min(o[across] for _s, o in glyphs)
        assert spread <= 0.5, spread
        assert model._validate_protected_spans(page, [span]) is True
    finally:
        model.close()
        doc.close()


@pytest.mark.parametrize(
    "draw_size,draw_origin",
    [(8.0, (72.0, 100.0)), (12.0, (72.0, 101.5)), (12.0, (73.5, 100.0))],
    ids=["shrunk", "baseline_moved", "start_moved"],
)
def test_f13vf3_validation_refuses_a_neighbour_with_the_wrong_size_or_origin(
    draw_size: float, draw_origin: tuple[float, float]
) -> None:
    """The text is all there; only its size or origin is not the neighbour's."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    model = PDFModel()
    try:
        span = _protected_span("Hello World", 12.0, (72, 90, 150, 104), (72, 100))
        page.insert_text(draw_origin, "Hello World", fontsize=draw_size, fontname="helv")
        assert model._validate_protected_spans(page, [span]) is False
        ok_page = doc.new_page(width=595, height=842)
        ok_page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
        assert model._validate_protected_spans(ok_page, [span]) is True
    finally:
        model.close()
        doc.close()


def test_f13vf3_push_down_replays_a_pushed_block_at_its_size_and_shifted_baseline() -> None:
    """Same bug class: the overflow push-down re-inserted each pushed block's
    spans into an estimated 1.55 em box with the default ``scale_low=0``."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Edited line", fontsize=12.0, fontname="helv")
    with font_compaction_scope(doc):
        page.insert_htmlbox(
            fitz.Rect(72, 190, 520, 260),
            "<span>前置作業操作流程</span>",
            css="* { font-size: 30pt; white-space: pre; margin:0; padding:0; }",
        )
    model = PDFModel()
    try:
        block_before = next(b for b in page.get_text("dict")["blocks"] if "前" in str(b))
        span_before = block_before["lines"][0]["spans"][0]
        origin_before = span_before["origin"]
        size_before = float(span_before["size"])
        bbox_before = fitz.Rect(block_before["bbox"])
        new_bottom = 230.0
        expected_delta = new_bottom + 2.0 - bbox_before.y0
        with font_compaction_scope(doc):
            model._push_down_overlapping_text(
                page,
                fitz.Rect(page.rect),
                above_y=bbox_before.y0 - 5.0,
                new_bottom=new_bottom,
                edit_x0=72.0,
                edit_x1=520.0,
            )
        cjk = [
            (float(span["size"]), (float(ch[2][0]), float(ch[2][1])))
            for span in page.get_texttrace()
            if span["chars"] and span["chars"][0][0] > 0x2E80
            for ch in span["chars"]
        ]
        assert cjk, "the pushed block must be drawn"
        assert all(abs(s - size_before) <= 0.05 for s, _o in cjk), sorted({round(s, 2) for s, _ in cjk})
        assert abs(cjk[0][1][0] - origin_before[0]) <= 0.5, (cjk[0][1], origin_before)
        assert abs(cjk[0][1][1] - (origin_before[1] + expected_delta)) <= 0.5, (
            cjk[0][1],
            origin_before,
            expected_delta,
        )
    finally:
        model.close()
        doc.close()


@pytest.mark.parametrize("page_rotation", [90, 180, 270])
def test_f13vf3_replay_on_a_rotated_page_keeps_size_and_origin(page_rotation: int) -> None:
    """Box, glyph trace and span origin share one (unrotated) space on a page
    with ``/Rotate``: the measured placement lands on the origin there too."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(page_rotation)
    model = PDFModel()
    try:
        span = _protected_span("前置作業 Price \u20ac5", 20.0, (100, 300, 300, 320), (100, 316))
        with font_compaction_scope(doc):
            model._replay_protected_spans(page, [span])
        glyphs = _f13vf3_glyphs(page)
        assert glyphs and all(abs(g_size - 20.0) <= 0.05 for g_size, _o in glyphs)
        assert abs(glyphs[0][1][0] - 100.0) <= 0.5 and abs(glyphs[0][1][1] - 316.0) <= 0.5
        assert model._validate_protected_spans(page, [span]) is True
    finally:
        model.close()
        doc.close()


def _identity_v_vertical_pdf(path: Path) -> None:
    """One hex-Tj show of 你好世界 plus a tail show, /Encoding /Identity-V
    (WMode 1): MuPDF extracts one vertical line per glyph."""
    from test_scripts.type0_fixture_builder import (
        build_identity_h_fixture,
        set_encoding_name,
    )

    fixture = build_identity_h_fixture(tail_text="後綴")
    set_encoding_name(fixture, "Identity-V")
    fixture.doc.save(str(path))
    fixture.doc.close()


def _non_ws_counts(text: str) -> Counter[str]:
    return Counter(ch for ch in text if not ch.isspace())


@pytest.mark.parametrize("target", ["block_rect", "first_run", "middle_run", "last_run"])
def test_consented_rebuild_on_vertical_text_never_leaves_the_source_column(
    tmp_path: Path, target: str
) -> None:
    """F10-UNI-3: MuPDF's redaction boxes for WMode 1 glyphs sit one em above
    the boxes it extracts, so ``apply_redactions`` on a vertical column's
    rect misses the target glyph (and can erase its neighbour).  The rebuild
    then inserted a rotated copy over the surviving column and reported
    SUCCESS.  The contract: SUCCESS only if the page holds exactly the
    requested characters; otherwise a refusal with the page untouched."""
    pdf = tmp_path / "vertical_identity_v.pdf"
    _identity_v_vertical_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    try:
        block = model.block_manager.get_blocks(0)[0]
        runs = model.block_manager.get_runs(0)
        assert len(runs) >= 5, "fixture must extract one vertical run per glyph"
        before = model.doc[0].get_text()
        kwargs: dict[str, object] = {}
        edit_rect = fitz.Rect(block.layout_rect)
        original = block.text
        if target == "block_rect":
            requested = block.text.replace("好", "天", 1)
            expected_page = requested
        else:
            run = {"first_run": runs[0], "middle_run": runs[1], "last_run": runs[-1]}[target]
            kwargs["target_span_id"] = run.span_id
            edit_rect = fitz.Rect(run.bbox)
            original = run.text
            requested = "天"
            expected_page = block.text.replace(run.text, requested, 1)
        try:
            result = model.edit_text(
                1,
                edit_rect,
                requested,
                **_block_style(block),
                original_text=original,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
                **kwargs,
            )
        except _RebuildRolledBack as refusal:
            assert "redaction" in str(refusal), str(refusal)
            assert refusal.reason.value == "redaction_left_source", repr(refusal.reason)
            assert model.doc[0].get_text() == before, "a refusal must leave the page untouched"
            return
        if result is not EditTextResult.SUCCESS:
            assert model.doc[0].get_text() == before
            return
        live = model.doc[0].get_text()
        assert _non_ws_counts(live) == _non_ws_counts(expected_page), (
            f"SUCCESS but the page is not the requested text: {ascii(live)}"
        )
        out = tmp_path / "saved_vertical.pdf"
        model.save_as(str(out))
        reopened = fitz.open(str(out))
        try:
            saved = reopened[0].get_text()
        finally:
            reopened.close()
        assert saved == live
    finally:
        model.close()


def test_redaction_survivor_check_sees_vertical_survivors_but_not_horizontal_erasure(
    tmp_path: Path,
) -> None:
    """The guard behind the refusal above, on the owned-glyph redaction
    (F13-VF-2): erasing a horizontal word leaves none of its glyphs and
    nothing else, erasing a WMode 1 glyph leaves it (MuPDF's box is one em
    off) and erases the glyph below it instead."""
    from model.pdf_text_edit import _redact_owned_glyphs

    vertical = tmp_path / "vertical_survivors.pdf"
    _identity_v_vertical_pdf(vertical)
    horizontal = tmp_path / "horizontal_survivors.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=12.0, fontname="helv")
    doc.save(str(horizontal))
    doc.close()

    for path, expect_survivors in ((horizontal, False), (vertical, True)):
        doc = fitz.open(str(path))
        try:
            page = doc[0]
            glyphs = _page_glyphs(page)
            owned = (
                [g for g in glyphs if g.key[0] in "Hello"][:5]
                if path is horizontal
                else glyphs[:1]
            )
            assert owned, "the fixture must hold glyphs to test the guard"
            outcome = _redact_owned_glyphs(page, glyphs, owned, [])
            assert bool(outcome.survivors) is expect_survivors, (path.name, outcome)
            if path is horizontal:
                assert outcome.lost_foreign == []
                assert page.get_text().split() == ["World"]
        finally:
            doc.close()


def test_push_down_never_redacts_and_replays_a_vertical_neighbour(tmp_path: Path) -> None:
    """F10-UNI-3 sibling: the overflow push-down redacts a neighbouring block
    and replays it lower.  MuPDF cannot redact WMode 1 glyphs by their
    extracted boxes, so a vertical neighbour would keep its original AND get
    a copy.  Such blocks stay where they are."""
    pdf = tmp_path / "vertical_pushdown.pdf"
    _identity_v_vertical_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    try:
        page = model.doc[0]
        before = page.get_text()
        assert before.strip()
        model._push_down_overlapping_text(
            page,
            fitz.Rect(page.rect),
            above_y=100.0,
            new_bottom=170.0,
            edit_x0=60.0,
            edit_x1=100.0,
        )
        assert page.get_text() == before
    finally:
        model.close()



# ── F11-ANN-1: redaction-based rewrites keep each annotation exactly once ──
# ``apply_redactions`` (PyMuPDF 1.27) deletes only FreeText annotations; every
# other kind survives it.  The save/restore wrapped around it re-added every
# overlapping annotation, so survivors were duplicated, and Highlight /
# Underline / StrikeOut were re-added from a vertex list passed as ``quads=``
# (TypeError after the insert: an infinite-rect marker with no QuadPoints).

_ANN11_MARKERS = {"Highlight", "Underline", "StrikeOut", "Squiggly"}
_ANN_LINES = ("Hello World Example Text", "Second line of body text", "Third line here")


def _ann_lines_page(doc: fitz.Document, count: int = 3) -> tuple[fitz.Page, dict[str, fitz.Rect]]:
    """A page of ``doc`` carrying the first ``count`` of ``_ANN_LINES``
    (Helvetica 12, 40 pt apart from y 100) and the rectangle of each word."""
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(_ANN_LINES[:count]):
        page.insert_text((72, 100 + 40 * i), line, fontsize=12, fontname="helv")
    return page, _word_rects(page)


def _ann11_pdf(path: Path) -> None:
    doc = fitz.open()
    page, words = _ann_lines_page(doc)
    annot = page.add_highlight_annot(words["World"])
    annot.set_info(content="hl-note")
    annot.update()
    page.add_underline_annot(words["Example"]).update()
    page.add_strikeout_annot(words["Text"]).update()
    page.add_rect_annot(words["Hello"] + (-2, -2, 2, 2)).update()
    page.add_text_annot((words["Text"].x1 + 4, 92), "sticky body").update()
    page.add_freetext_annot(words["World"] + (0, -2, 40, 2), "FT comment", fontsize=9).update()
    page.add_highlight_annot(words["Second"]).update()
    page.add_rect_annot(words["body"] + (-2, -2, 2, 2)).update()
    doc.save(str(path))
    doc.close()


def _ann11_census(page: fitz.Page) -> Counter[str]:
    return Counter(annot.type[1] for annot in page.annots())


def _ann11_assert_sane(page: fitz.Page) -> None:
    doc = page.parent
    bounds = fitz.Rect(page.rect) + (-50, -50, 50, 50)
    for annot in page.annots():
        name = annot.type[1]
        assert bounds.contains(annot.rect), f"{name} xref {annot.xref} has a corrupt rect {annot.rect}"
        if name in _ANN11_MARKERS:
            kind, _ = doc.xref_get_key(annot.xref, "QuadPoints")
            assert kind == "array", f"{name} xref {annot.xref} lost its QuadPoints"


def _ann11_geometry(page: fitz.Page) -> dict[int, tuple[str, fitz.Rect]]:
    return {annot.xref: (annot.type[1], fitz.Rect(annot.rect)) for annot in page.annots()}


def test_consented_rebuild_keeps_each_overlapping_annotation_once(tmp_path: Path) -> None:
    pdf = tmp_path / "ann11_rebuild.pdf"
    _ann11_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    try:
        page = model.doc[0]
        before_counts = _ann11_census(page)
        before_geometry = _ann11_geometry(page)
        block = _find_block(model, 0, "Hello")
        assert block is not None
        result = model.edit_text(
            1,
            fitz.Rect(block.layout_rect),
            "Hello Ωmega Example Text",
            **_block_style(block),
            original_text=block.text,
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS
        page = model.doc[0]
        assert _ann11_census(page) == before_counts
        _ann11_assert_sane(page)
        after_geometry = _ann11_geometry(page)
        for xref, (name, rect) in before_geometry.items():
            assert xref in after_geometry, f"surviving {name} xref {xref} was replaced"
            assert after_geometry[xref][1] == rect, f"surviving {name} xref {xref} moved"
        out = tmp_path / "ann11_rebuild_saved.pdf"
        model.save_as(str(out))
        reopened = fitz.open(str(out))
        try:
            assert _ann11_census(reopened[0]) == before_counts
            _ann11_assert_sane(reopened[0])
        finally:
            reopened.close()
    finally:
        model.close()


def test_push_down_moves_neighbour_annotations_instead_of_copying_them(tmp_path: Path) -> None:
    pdf = tmp_path / "ann11_pushdown.pdf"
    _ann11_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    try:
        page = model.doc[0]
        before_counts = _ann11_census(page)
        before_geometry = _ann11_geometry(page)
        second_before = _word_rects(page)["Second"]
        model._push_down_overlapping_text(
            page,
            fitz.Rect(page.rect),
            above_y=106.0,
            new_bottom=150.0,
            edit_x0=72.0,
            edit_x1=300.0,
        )
        second_after = _word_rects(page)["Second"]
        delta = second_after.y0 - second_before.y0
        assert delta > 5.0, "the fixture must push line 2 down"
        assert _ann11_census(page) == before_counts
        _ann11_assert_sane(page)
        after_geometry = _ann11_geometry(page)
        moved = 0
        for xref, (name, rect) in before_geometry.items():
            assert xref in after_geometry, f"surviving {name} xref {xref} was replaced"
            new_rect = after_geometry[xref][1]
            if rect.y0 > 120:  # line-2 annotations travel with their text
                moved += 1
                assert abs((new_rect.y0 - rect.y0) - delta) < 1.0, (name, rect, new_rect, delta)
                assert abs(new_rect.x0 - rect.x0) < 0.01
            else:
                assert new_rect == rect, f"line-1 {name} moved: {rect} -> {new_rect}"
        assert moved == 2
        line2_highlight = next(
            a for a in page.annots() if a.type[1] == "Highlight" and a.rect.y0 > 120
        )
        assert min(p[1] for p in line2_highlight.vertices) > second_before.y0 + delta - 1.0
    finally:
        model.close()


@pytest.mark.parametrize("offset", [(0.0, 0.0), (0.0, 30.0)])
@pytest.mark.parametrize("reattach", [False, True])
def test_restore_recreates_a_deleted_text_marker_from_its_quads(
    tmp_path: Path, offset: tuple[float, float], reattach: bool
) -> None:
    """The re-create branch (an entry whose object cannot be put back: no xref)
    rebuilds text markers from their QuadPoints, at the offset the caller asked
    for, and never leaves an infinite-rect marker behind.  With the xref the
    deleted object itself comes back (F11-ANN-5) with the same geometry."""
    pdf = tmp_path / "ann11_markers.pdf"
    _ann11_pdf(pdf)
    model = PDFModel()
    model.open_pdf(str(pdf))
    try:
        page = model.doc[0]
        tool = model.tools.annotation
        line1 = fitz.Rect(60, 80, 300, 110)
        saved = [s for s in tool._save_overlapping_annots(page, line1) if s["type_name"] in _ANN11_MARKERS]
        assert sorted(s["type_name"] for s in saved) == ["Highlight", "StrikeOut", "Underline"]
        originals = {
            a.type[1]: (fitz.Rect(a.rect), list(a.vertices))
            for a in page.annots()
            if a.type[1] in _ANN11_MARKERS and a.rect.y0 < 120
        }
        for xref in [a.xref for a in page.annots() if a.type[1] in _ANN11_MARKERS and a.rect.y0 < 120]:
            page.delete_annot(page.load_annot(xref))
        kept = {a.xref for a in page.annots()}
        tool._restore_annots(page, [dict(s, offset=offset, xref=s["xref"] if reattach else None) for s in saved])
        _ann11_assert_sane(page)
        dx, dy = offset
        restored = [a for a in page.annots() if a.xref not in kept]
        assert sorted(a.type[1] for a in restored) == ["Highlight", "StrikeOut", "Underline"]
        if reattach:
            assert {a.xref for a in restored} == {s["xref"] for s in saved}
        for annot in restored:
            rect, verts = originals[annot.type[1]]
            assert abs(annot.rect.y0 - (rect.y0 + dy)) < 1.0, (annot.type[1], annot.rect, rect)
            assert len(annot.vertices) == len(verts)
            for got, want in zip(annot.vertices, verts):
                assert abs(got[0] - (want[0] + dx)) < 0.01 and abs(got[1] - (want[1] + dy)) < 0.01
        highlight = next(a for a in restored if a.type[1] == "Highlight")
        assert highlight.info.get("content") == "hl-note"
    finally:
        model.close()


def test_failed_recreate_without_a_baseline_never_deletes_existing_annotations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard for the partial-insert cleanup: when the page's annotation list
    could not be read before a re-create that then fails, nothing is deleted
    (an empty baseline would make every annotation look new)."""
    pdf = tmp_path / "ann11_guard.pdf"
    _ann11_pdf(pdf)
    model = PDFModel()
    model.open_pdf(str(pdf))
    try:
        page = model.doc[0]
        existing = {a.xref for a in page.annots()}
        assert existing
        real_annot_xrefs = fitz.Page.annot_xrefs
        real_add_rect = fitz.Page.add_rect_annot
        calls = {"n": 0}

        def flaky_annot_xrefs(self):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("annot list unavailable")
            return real_annot_xrefs(self)

        def insert_then_raise(self, *args, **kwargs):
            real_add_rect(self, *args, **kwargs)
            raise TypeError("validation after insert")

        monkeypatch.setattr(fitz.Page, "annot_xrefs", flaky_annot_xrefs)
        monkeypatch.setattr(fitz.Page, "add_rect_annot", insert_then_raise)
        model.tools.annotation._restore_annots(page, [{
            "type_code": fitz.PDF_ANNOT_SQUARE,
            "type_name": "Square",
            "rect": fitz.Rect(300, 300, 350, 350),
            "info": {},
            "colors": {},
            "opacity": None,
        }])
        monkeypatch.undo()
        assert calls["n"] >= 2
        assert existing <= {a.xref for a in page.annots()}
    finally:
        model.close()


def _ann11_annot_list(page: fitz.Page) -> list[tuple[int, str, str]]:
    return sorted((a.xref, a.type[1], a.info.get("content", "")) for a in page.annots())


def _ann_line_edit(model: PDFModel, probe: str, new_text: str, **kwargs) -> EditTextCommand:
    """Execute an ``EditTextCommand`` on the line holding ``probe``; its rect
    is handed over in displayed space (the page's rotation applied, a no-op
    on an unrotated page)."""
    block = _find_block(model, 0, probe)
    assert block is not None
    cmd = EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect) * model.doc[0].rotation_matrix,
        new_text=new_text,
        **_block_style(block),
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(0),
        old_block_id=block.block_id,
        old_block_text=block.text,
        target_span_id=block.block_id,
        **kwargs,
    )
    model.command_manager.execute(cmd)
    return cmd


def test_undo_of_a_rebuild_keeps_the_annotation_list_of_a_page_still_loaded(tmp_path: Path) -> None:
    """F11-ANN-2: after a consented rebuild of a line carrying a Highlight and a
    FreeText, undo (and redo) put the page's ``/Annots`` back by xref.  A
    ``fitz.Page`` still alive across that restore (``held`` here; in the app a
    Page<->Annot cycle, a traceback a log handler keeps, ...) is the MuPDF page
    every later ``doc[0]`` returns, so its cached annotation list must follow
    the restore: the annotation panel, the page fingerprint and the next edit
    on the page all load every listed annotation by xref."""
    from model.text_commit.inspect import page_fingerprint

    pdf = tmp_path / "ann11_undo_held.pdf"
    _ann11_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    held = None
    try:
        original = _ann11_annot_list(model.doc[0])
        cmd = _ann_line_edit(
            model,
            "Hello",
            "Hello Ωmega Example Text",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert cmd.result is EditTextResult.SUCCESS
        rebuilt = _ann11_annot_list(model.doc[0])
        # F11-ANN-5: the removed FreeText is put back as the same object (same xref).
        assert rebuilt == original

        held = model.doc[0]
        assert model.command_manager.undo() is True
        page = model.doc[0]
        assert _ann11_annot_list(page) == original
        assert _ann11_annot_list(held) == original
        notes = model.tools.annotation.get_all_annotations()
        assert sorted(n["kind"] for n in notes) == ["freetext", "note"]
        page_fingerprint(model.doc, page)

        assert model.command_manager.redo() is True
        assert _ann11_annot_list(model.doc[0]) == rebuilt
        assert model.command_manager.undo() is True
        assert _ann11_annot_list(model.doc[0]) == original

        model.ensure_page_index_built(1)
        # Same width: a lossless Tier 0 patch (a wider line is refused growth_region_not_blank).
        second = _ann_line_edit(model, "Second", "Second line of body test")
        assert second.result is EditTextResult.SUCCESS
        assert {xref for xref, _n, _c in original} <= {xref for xref, _n, _c in _ann11_annot_list(model.doc[0])}
    finally:
        held = None
        model.close()



# ── F11-ANN-3: links under a redacted line are kept, not silently deleted ──
# ``page.annots()`` never returns Link annotations, and ``apply_redactions``
# removes every link that intersects the redaction from ``/Annots`` (the link
# object itself stays in the xref table).  The save/restore wrapped around the
# redaction must put each removed link back -- same object, same target -- and
# refresh the loaded page's link list (a ``held`` Page sees it too, F11-ANN-2).

def _ann3_add_links(page: fitz.Page) -> None:
    words = _word_rects(page)
    page.insert_link({"kind": fitz.LINK_URI, "from": words["Hello"], "uri": "https://example.com/hello"})
    page.insert_link({"kind": fitz.LINK_GOTO, "from": words["World"], "page": 0, "to": fitz.Point(0, 0)})
    page.insert_link({"kind": fitz.LINK_URI, "from": words["body"], "uri": "https://example.com/body"})


def _ann3_pdf(path: Path) -> None:
    doc = fitz.open()
    page, words = _ann_lines_page(doc)
    page.add_highlight_annot(words["Example"]).update()
    _ann3_add_links(page)
    doc.save(str(path))
    doc.close()


def _ann3_links(page: fitz.Page, *, with_xref: bool = True) -> list[tuple]:
    out = []
    for link in page.get_links():
        rect = fitz.Rect(link["from"])
        key = (
            link.get("kind"),
            link.get("uri"),
            link.get("page"),
            round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1),
        )
        out.append(((link.get("xref"),) + key) if with_xref else key)
    return sorted(out, key=repr)


def test_consented_rebuild_keeps_the_links_on_the_rebuilt_line(tmp_path: Path) -> None:
    pdf = tmp_path / "ann3_rebuild.pdf"
    _ann3_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    held = None
    try:
        held = model.doc[0]
        before = _ann3_links(held)
        assert len(before) == 3
        cmd = _ann_line_edit(
            model,
            "Hello",
            "Hello Ωmega Example Text",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert cmd.result is EditTextResult.SUCCESS
        assert _ann3_links(model.doc[0]) == before
        assert _ann3_links(held) == before
        assert model.command_manager.undo() is True
        assert _ann3_links(model.doc[0]) == before
        assert model.command_manager.redo() is True
        assert _ann3_links(model.doc[0]) == before
        assert _ann3_links(held) == before
        expected = _ann3_links(model.doc[0], with_xref=False)
        held = None  # save_as replaces the document handle
        out = tmp_path / "ann3_rebuild_saved.pdf"
        model.save_as(str(out))
        reopened = fitz.open(str(out))
        try:
            assert _ann3_links(reopened[0], with_xref=False) == expected
        finally:
            reopened.close()
    finally:
        held = None
        model.close()


def test_same_page_move_keeps_the_links_where_they_were(tmp_path: Path) -> None:
    """A same-page drag redacts the source line.  Like every other annotation
    on it (F11-ANN-1), its links stay at their original rect; they are not
    deleted (also after redo and save/reopen).  The drag also pushes lines 2-3
    down (``_push_down_overlapping_text``): the link on "body" goes with it."""
    pdf = tmp_path / "ann3_move.pdf"
    _ann3_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    held = None
    try:
        held = model.doc[0]
        before = _ann3_links(held)
        block = _find_block(model, 0, "Hello")
        assert block is not None
        dest = fitz.Rect(block.layout_rect) + (0, 300, 0, 300)
        cmd = _ann_line_edit(
            model,
            "Hello",
            block.text,
            new_rect=dest,
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert cmd.result is EditTextResult.SUCCESS
        moved_words = [w for w in model.doc[0].get_text("words") if w[4] == "Hello"]
        assert moved_words and moved_words[0][1] > 300, "the fixture must move the line"

        def check(page: fitz.Page) -> list[tuple]:
            got = _ann3_links(page)
            assert [g[:4] for g in got] == [b[:4] for b in before]  # same objects, same targets
            body = _word_rects(page)["body"]
            for was, now in zip(before, got):
                if now[2] == "https://example.com/body":
                    assert fitz.Rect(now[4:8]).intersects(body), (now, body)
                else:
                    assert now == was, f"line-1 link moved: {was} -> {now}"
            return got

        after_move = check(model.doc[0])
        assert _ann3_links(held) == after_move
        assert model.command_manager.undo() is True
        assert _ann3_links(model.doc[0]) == before
        assert model.command_manager.redo() is True
        assert check(model.doc[0]) == after_move
        expected = _ann3_links(model.doc[0], with_xref=False)
        held = None  # save_as replaces the document handle
        out = tmp_path / "ann3_move_saved.pdf"
        model.save_as(str(out))
        reopened = fitz.open(str(out))
        try:
            assert _ann3_links(reopened[0], with_xref=False) == expected
        finally:
            reopened.close()
    finally:
        held = None
        model.close()


def test_push_down_moves_the_links_of_a_pushed_line_with_their_text(tmp_path: Path) -> None:
    pdf = tmp_path / "ann3_pushdown.pdf"
    _ann3_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    try:
        page = model.doc[0]
        before = {link["xref"]: (link.get("uri"), link.get("page"), fitz.Rect(link["from"])) for link in page.get_links()}
        body_before = _word_rects(page)["body"]
        model._push_down_overlapping_text(
            page,
            fitz.Rect(page.rect),
            above_y=106.0,
            new_bottom=150.0,
            edit_x0=72.0,
            edit_x1=300.0,
        )
        body_after = _word_rects(page)["body"]
        delta = body_after.y0 - body_before.y0
        assert delta > 5.0, "the fixture must push line 2 down"
        after = {link["xref"]: (link.get("uri"), link.get("page"), fitz.Rect(link["from"])) for link in page.get_links()}
        assert set(after) == set(before)
        for xref, (uri, target, rect) in before.items():
            new_uri, new_target, new_rect = after[xref]
            assert (new_uri, new_target) == (uri, target)
            if rect.y0 > 120:  # the line-2 link travels with its text
                assert abs((new_rect.y0 - rect.y0) - delta) < 1.0, (uri, rect, new_rect, delta)
                assert abs(new_rect.x0 - rect.x0) < 0.01
            else:
                assert new_rect == rect, f"line-1 link moved: {rect} -> {new_rect}"
    finally:
        model.close()


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("offset", [(0.0, 0.0), (0.0, 30.0)])
def test_restore_reattaches_links_a_redaction_removed(
    tmp_path: Path, rotation: int, offset: tuple[float, float]
) -> None:
    """Unit level, real redaction: the link entries saved for the redacted
    rect come back as the same objects, at ``rect + offset``, on rotated pages
    too (link and redact rects share the unrotated space of ``annot.rect``)."""
    pdf = tmp_path / f"ann3_unit_{rotation}.pdf"
    doc = fitz.open()
    page, _words = _ann_lines_page(doc, 2)
    _ann3_add_links(page)
    page.set_rotation(rotation)
    doc.save(str(pdf))
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf))
    try:
        page = model.doc[0]
        tool = model.tools.annotation
        before = {link["xref"]: link for link in page.get_links()}
        line1 = fitz.Rect(60, 80, 300, 110)
        saved = tool._save_overlapping_annots(page, line1)
        line1_links = sorted(x for x, link in before.items() if link.get("uri") != "https://example.com/body")
        assert sorted(s["xref"] for s in saved if s["type_name"] == "Link") == line1_links
        page.add_redact_annot(line1)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        assert len(page.get_links()) == 1, "the redaction must remove the line-1 links"
        tool._restore_annots(page, [dict(s, offset=offset) for s in saved])
        after = {link["xref"]: link for link in page.get_links()}
        assert set(after) == set(before)
        # ``get_links()["from"]`` is in rotated (displayed) space; the offset is unrotated.
        dx, dy = offset
        shift = fitz.Point(dx, dy) * page.rotation_matrix - fitz.Point(0, 0) * page.rotation_matrix
        for xref, link in before.items():
            got = after[xref]
            assert (got.get("kind"), got.get("uri"), got.get("page")) == (
                link.get("kind"), link.get("uri"), link.get("page")
            )
            want = fitz.Rect(link["from"])
            if xref in line1_links:
                want = want + (shift.x, shift.y, shift.x, shift.y)
            got_rect = fitz.Rect(got["from"])
            assert all(abs(a - b) < 0.01 for a, b in zip(got_rect, want)), (xref, got_rect, want)
    finally:
        model.close()


def test_restore_reattaches_a_link_to_an_indirect_annots_array(tmp_path: Path) -> None:
    """``/Annots`` may be an indirect array (``/Annots 12 0 R``, common from
    Office producers).  MuPDF's redaction rewrites it inline, but a page whose
    link was unlisted otherwise keeps the reference: the link goes back into
    that array object, and the page still points at it."""
    pdf = tmp_path / "ann3_indirect.pdf"
    doc = fitz.open()
    page, _words = _ann_lines_page(doc, 2)
    _ann3_add_links(page)
    _kind, inline = doc.xref_get_key(page.xref, "Annots")
    array_xref = doc.get_new_xref()
    doc.update_object(array_xref, inline)
    doc.xref_set_key(page.xref, "Annots", f"{array_xref} 0 R")
    doc.save(str(pdf))
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf))
    try:
        doc = model.doc
        page = doc[0]
        kind, value = doc.xref_get_key(page.xref, "Annots")
        assert kind == "xref"
        array_xref = int(value.split()[0])
        before = _ann3_links(page)
        saved = model.tools.annotation._save_overlapping_annots(page, fitz.Rect(60, 80, 300, 110))
        removed = sorted(s["xref"] for s in saved if s["type_name"] == "Link")
        assert len(removed) == 2
        kept = [x for x, t, _ in page.annot_xrefs() if x not in removed]
        doc.update_object(array_xref, "[" + " ".join(f"{x} 0 R" for x in kept) + "]")
        from utils.pymupdf_refs import sync_open_pages
        sync_open_pages(doc)
        assert len(page.get_links()) == 1
        model.tools.annotation._restore_annots(page, saved)
        assert doc.xref_get_key(page.xref, "Annots") == ("xref", f"{array_xref} 0 R")
        assert _ann3_links(page) == before
    finally:
        model.close()


# ── F11-ANN-5: a FreeText under a redacted line comes back as itself ────────
# ``apply_redactions`` drops a FreeText from ``/Annots`` but leaves the object
# and its appearance stream in the xref table.  The restore used to re-create
# it with ``add_freetext_annot`` (text colour = the old /C background, fixed
# 10.5 pt, yellow fill, /Rotate = page rotation, no /T, no dates, new xref).
# It now puts the same object back, like the links of F11-ANN-3.

_ANN5_DA = "1 0 0 rg /Helv 9.0 Tf"
_ANN5_KEYS = ("DA", "C", "IC", "Rotate", "T", "CreationDate", "M", "IT", "RC", "Subj", "Contents", "F", "AP")


def _ann5_pdf(path: Path, *, rotation: int = 0) -> None:
    doc = fitz.open()
    page, words = _ann_lines_page(doc, 2)
    annot = page.add_freetext_annot(
        words["World"] + (0, -2, 40, 2),
        "FT comment",
        fontsize=9,
        text_color=(1, 0, 0),
        fill_color=(0.8, 0.9, 1),
    )
    annot.set_info(title="Alice", subject="review", creationDate="D:20240101120000", modDate="D:20240102120000")
    annot.update()
    doc.xref_set_key(annot.xref, "IT", "/FreeText")
    doc.xref_set_key(annot.xref, "RC", "(<body><p>FT comment</p></body>)")
    if rotation:
        page.set_rotation(rotation)
    doc.save(str(path))
    doc.close()


def _ann5_freetext_state(doc: fitz.Document, pno: int = 0) -> list[dict]:
    out = []
    for annot in doc[pno].annots():
        if annot.type[1] != "FreeText":
            continue
        entry = {key: doc.xref_get_key(annot.xref, key) for key in _ANN5_KEYS}
        entry["xref"] = annot.xref
        entry["info"] = dict(annot.info)
        entry["rect"] = tuple(round(v, 2) for v in annot.rect)
        out.append(entry)
    return out


@pytest.mark.parametrize("rotation", [0, 90])
def test_consented_rebuild_keeps_a_freetext_exactly_as_it_was(tmp_path: Path, rotation: int) -> None:
    pdf = tmp_path / f"ann5_rebuild_{rotation}.pdf"
    _ann5_pdf(pdf, rotation=rotation)
    model = _open_model(pdf, engine="tiered")
    try:
        before = _ann5_freetext_state(model.doc)
        assert len(before) == 1
        assert before[0]["DA"][1] == _ANN5_DA
        assert before[0]["Rotate"][0] == "null"
        cmd = _ann_line_edit(
            model,
            "Hello",
            "Hello Ωmega Example Text",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert cmd.result is EditTextResult.SUCCESS
        # The rebuild really went through the redaction path that drops the FreeText.
        assert model.last_commit_outcome is not None
        assert model.last_commit_outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert _ann5_freetext_state(model.doc) == before
        assert model.command_manager.undo() is True
        assert _ann5_freetext_state(model.doc) == before
        assert model.command_manager.redo() is True
        assert _ann5_freetext_state(model.doc) == before
        out = tmp_path / f"ann5_rebuild_{rotation}_saved.pdf"
        model.save_as(str(out))
        reopened = fitz.open(str(out))
        try:
            saved = _ann5_freetext_state(reopened)
            assert len(saved) == 1
            for key in ("DA", "C", "IC", "Rotate", "IT", "RC", "Subj", "Contents"):
                assert saved[0][key] == before[0][key], key
            assert saved[0]["info"] == before[0]["info"]
        finally:
            reopened.close()
    finally:
        model.close()


def test_restore_reattaches_a_freetext_the_redaction_removed_and_moves_it(tmp_path: Path) -> None:
    """Push-down carries ``offset``: the same object moves with its text, with
    /Rect and /CL shifted and every other key (and its appearance) untouched."""
    pdf = tmp_path / "ann5_push.pdf"
    _ann5_pdf(pdf)
    model = PDFModel()
    model.open_pdf(str(pdf))
    try:
        page = model.doc[0]
        doc = model.doc
        tool = model.tools.annotation
        before = _ann5_freetext_state(doc)[0]
        cl_before = [float(v) for v in doc.xref_get_key(before["xref"], "CL")[1].strip("[]").split()]
        saved = tool._save_overlapping_annots(page, fitz.Rect(60, 80, 300, 110))
        assert [s["xref"] for s in saved if s["type_name"] == "FreeText"] == [before["xref"]]
        page.add_redact_annot(fitz.Rect(60, 80, 300, 110))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        assert _ann5_freetext_state(doc) == [], "the redaction must have removed the FreeText"
        tool._restore_annots(page, [dict(s, offset=(0.0, 30.0)) for s in saved])
        after = _ann5_freetext_state(doc)
        assert len(after) == 1 and after[0]["xref"] == before["xref"]
        for key in ("DA", "C", "IC", "Rotate", "T", "CreationDate", "M", "IT", "RC", "Subj", "Contents", "F", "AP"):
            assert after[0][key] == before[key], key
        assert after[0]["info"] == before["info"]
        moved = fitz.Rect(before["rect"]) + (0, 30, 0, 30)
        assert fitz.Rect(after[0]["rect"]) == moved
        cl_after = [float(v) for v in doc.xref_get_key(before["xref"], "CL")[1].strip("[]").split()]
        # /CL is in PDF space (y up): a 30 pt visual push-down lowers every y by 30.
        assert [round(b - a, 3) for a, b in zip(cl_before, cl_after)] == [0.0, -30.0] * (len(cl_before) // 2)
        assert len(cl_before) >= 4
        # Still one entry in /Annots (no duplicate) and loadable by xref.
        assert [x for x, t, _ in page.annot_xrefs()].count(before["xref"]) == 1
        page.load_annot(before["xref"])
    finally:
        model.close()


def test_recreated_freetext_keeps_its_style_when_the_object_cannot_be_reattached(tmp_path: Path) -> None:
    """Fallback: an entry without a usable xref (the object is gone) is rebuilt
    from what was saved -- DA colour and size, /C fill, /Rotate, author, dates --
    not from the old hard-coded defaults."""
    pdf = tmp_path / "ann5_fallback.pdf"
    _ann5_pdf(pdf)
    model = PDFModel()
    model.open_pdf(str(pdf))
    try:
        page = model.doc[0]
        doc = model.doc
        tool = model.tools.annotation
        before = _ann5_freetext_state(doc)[0]
        saved = tool._save_overlapping_annots(page, fitz.Rect(60, 80, 300, 110))
        page.add_redact_annot(fitz.Rect(60, 80, 300, 110))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        assert _ann5_freetext_state(doc) == []
        tool._restore_annots(page, [dict(s, xref=None) for s in saved])
        after = _ann5_freetext_state(doc)
        assert len(after) == 1
        assert after[0]["xref"] != before["xref"]
        assert after[0]["DA"][1].startswith("1 0 0 rg /Helv 9") and after[0]["DA"][1].endswith("Tf")
        assert after[0]["C"] == before["C"]
        assert after[0]["Rotate"][0] == "null"
        assert after[0]["info"] == before["info"]
        assert after[0]["rect"] == before["rect"]
    finally:
        model.close()


# ── F11-ANN-4: annotation appearance text is not page content ──────────────
# ``page.get_text`` also walks annotation appearance streams (FreeText body,
# form-field values).  The block index therefore listed a FreeText's text as an
# editable block, a rebuild replayed it as a "protected span" into the content
# stream (the text then showed twice and survived the annotation's deletion),
# and a push-down re-inserted it as page content.  Annotations are edited
# through the annotation tools, never through the page-text index.

_ANN4_FREETEXT = "FT comment"
_ANN4_FIELD = "FieldValue"


def _ann4_content_text(doc: fitz.Document, page_idx: int = 0) -> str:
    """Page text with every annotation and widget removed (what survives an
    annotation deletion)."""
    probe = fitz.open("pdf", doc.tobytes())
    try:
        page = probe[page_idx]
        for widget in list(page.widgets()):
            page.delete_widget(widget)
        for annot in list(page.annots()):
            page.delete_annot(annot)
        return page.get_text()
    finally:
        probe.close()


def _ann4_pdf(path: Path, *, freetext: bool = True, widget: bool = False) -> None:
    doc = fitz.open()
    page, words = _ann_lines_page(doc)
    if freetext:
        page.add_freetext_annot(
            words["World"] + (0, -2, 60, 2), _ANN4_FREETEXT, fontsize=9
        ).update()
    if widget:
        area = fitz.Rect(300, 300, 450, 320)
        fld = fitz.Widget()
        fld.field_name = "f1"
        fld.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        fld.field_value = _ANN4_FIELD
        fld.rect = area
        fld.text_fontsize = 9
        page.add_widget(fld)
    doc.save(str(path))
    doc.close()


def test_annotation_appearance_text_is_not_indexed_as_page_text(tmp_path: Path) -> None:
    pdf = tmp_path / "ann4_index.pdf"
    _ann4_pdf(pdf, widget=True)
    model = _open_model(pdf, engine="tiered")
    try:
        page = model.doc[0]
        # fixture sanity: a plain extraction DOES see the annotation text
        assert _ANN4_FREETEXT in page.get_text()
        assert _ANN4_FIELD in page.get_text()
        bm = model.block_manager
        texts = (
            [b.text for b in bm.get_blocks(0)]
            + [s.text for s in bm.get_runs(0)]
            + [p.text for p in bm.get_paragraphs(0)]
            + list(bm._page_plain_lines[0])
        )
        joined = "\n".join(t or "" for t in texts)
        assert _ANN4_FREETEXT not in joined, texts
        assert _ANN4_FIELD not in joined, texts
        assert "Hello World Example Text" in joined  # real content still indexed
    finally:
        model.close()


def test_consented_rebuild_does_not_burn_annotation_text_into_the_content(tmp_path: Path) -> None:
    pdf = tmp_path / "ann4_rebuild.pdf"
    # (a page carrying a form widget is refused outright by the tiered engine)
    _ann4_pdf(pdf)
    model = _open_model(pdf, engine="tiered")
    try:
        before_content = _ann4_content_text(model.doc)
        assert _ANN4_FREETEXT not in before_content
        block = _find_block(model, 0, "Hello")
        assert block is not None
        result = model.edit_text(
            1,
            fitz.Rect(block.layout_rect),
            "Hello Ωmega Example Text",  # outside Tier 0: forces the rebuild
            **_block_style(block),
            original_text=block.text,
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS
        assert model.last_commit_outcome.status is CommitStatus.DEGRADED_COMMITTED
        after_content = _ann4_content_text(model.doc)
        assert "Hello Ωmega Example Text" in after_content
        assert _ANN4_FREETEXT not in after_content, after_content
        page = model.doc[0]
        assert _ann11_census(page) == {"FreeText": 1}
        assert page.get_text().count(_ANN4_FREETEXT) == 1
    finally:
        model.close()


def test_push_down_leaves_annotation_text_out_of_the_content(tmp_path: Path) -> None:
    pdf = tmp_path / "ann4_pushdown.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World Example Text", fontsize=12, fontname="helv")
    page.insert_text((72, 200), "Far below line", fontsize=12, fontname="helv")
    page.add_freetext_annot(fitz.Rect(72, 112, 220, 132), _ANN4_FREETEXT, fontsize=9).update()
    doc.save(str(pdf))
    doc.close()
    model = _open_model(pdf, engine="tiered")
    try:
        page = model.doc[0]
        model._push_down_overlapping_text(
            page,
            fitz.Rect(page.rect),
            above_y=106.0,
            new_bottom=150.0,
            edit_x0=72.0,
            edit_x1=300.0,
        )
        assert _ANN4_FREETEXT not in _ann4_content_text(model.doc)
        page = model.doc[0]
        # (whether a bare annotation in the overflow zone should travel with
        # the push-down is an open owner question; only its survival is pinned)
        assert [a.type[1] for a in page.annots()] == ["FreeText"]
    finally:
        model.close()



# ---------------------------------------------------------------------------
# F11-UNI-1 (owner decision C): a consented rebuild of text that carries an
# UNTOUCHED glyph with no Unicode identity (U+FFFD, a C1 code, private use)
# commits only when the consent explicitly acknowledged exactly those glyphs.
# htmlbox cannot reproduce such a glyph: U+FFFD / controls become a
# replacement glyph ("replaced"), private use a blank .notdef ("removed").
# ---------------------------------------------------------------------------

_F11_TOUNICODE = (
    b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
    b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
    b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
    b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
    b"1 beginbfchar\n<80> <%s>\nendbfchar\n"
    b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
)

# (label, ToUnicode target of the 0x80 glyph or None for an unknown glyph
#  name, the code point the block index reports, its fate)
_F11_CASES = [
    ("fffd", 0xFFFD, "U+FFFD", "replaced"),
    ("c1_unknown_glyph_name", None, "U+FFFD", "replaced"),
    ("pua_f0b7", 0xF0B7, "U+F0B7", "removed"),
    ("pua_e000", 0xE000, "U+E000", "removed"),
    # F16-PASTE-2: U+FFFC (an inline-object anchor) is category So and has a
    # name, but it is not a character a text layer can mean; htmlbox draws it
    # as a dashed "OBJ" box and round-trips it, so only an explicit check
    # keeps it from being committed silently.
    ("fffc", 0xFFFC, "U+FFFC", "replaced"),
]


def _f11_pdf(path: Path, uni: int | None, *, protected: bool = False) -> None:
    """``Price <0x80 glyph> today`` (one Helvetica show) or, with
    ``protected``, ``Price today`` plus the 0x80 glyph in a second font drawn
    over ``today`` -- an overlapping neighbour run the rebuild must replay."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if protected:
        stream = (
            b"BT /F1 11 Tf 40 700 Td (Price today) Tj ET "
            b"BT /F2 11 Tf 76 700 Td (\x80) Tj ET "
            b"BT /F1 11 Tf 40 660 Td (Downstream line stays) Tj ET"
        )
    else:
        stream = (
            b"BT /F1 11 Tf 40 700 Td (Price \x80 today) Tj "
            b"0 -40 Td (Downstream line stays) Tj ET"
        )
    cx = doc.get_new_xref()
    doc.update_object(cx, "<<>>")
    doc.update_stream(cx, stream)
    doc.xref_set_key(page.xref, "Contents", f"{cx} 0 R")
    f1, f2 = doc.get_new_xref(), doc.get_new_xref()
    if uni is None:
        glyph_font = (
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding "
            "/BaseEncoding /WinAnsiEncoding /Differences [ 128 /glyphXYZ ] >> >>"
        )
    else:
        tx = doc.get_new_xref()
        doc.update_object(tx, "<<>>")
        doc.update_stream(tx, _F11_TOUNICODE % (b"%04X" % uni))
        glyph_font = (
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding "
            f"/ToUnicode {tx} 0 R >>"
        )
    plain = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    doc.update_object(f1, plain if protected else glyph_font)
    doc.update_object(f2, glyph_font if protected else plain)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >>")
    doc.save(str(path), garbage=0)
    doc.close()


class _F11Consent:
    """A consent callback: records the glyph-loss report the model exposes
    at the moment of the ask and answers with ``answer(report)``."""

    def __init__(self, model: PDFModel, answer) -> None:
        self.model = model
        self.answer = answer
        self.reports: list[tuple] = []

    def __call__(self, _chain: tuple[str, ...]):
        report = tuple(self.model.pending_rebuild_glyph_loss)
        self.reports.append(report)
        return self.answer(report)


def _f11_block_edit(model: PDFModel, consent, new_text: str | None = None):
    """Edit the whole ``... today`` block to ``... tomorrow`` with the
    explicit rebuild consent; returns the result or the raised exception."""
    block = _find_block(model, 0, "today")
    assert block is not None
    requested = new_text if new_text is not None else block.text.replace("today", "tomorrow")
    try:
        return model.edit_text(
            1,
            fitz.Rect(block.layout_rect),
            requested,
            font=block.font or "helv",
            size=float(block.size or 11.0),
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            allow_rebuild=True,
            confirm_fallback=consent,
        )
    except _RebuildRolledBack as exc:
        return exc


def _f11_run_edit(model: PDFModel, consent):
    """Edit only the ``today`` run (the overlapping glyph run is protected)."""
    span = _run_with_text(model, "today")
    try:
        return model.edit_text(
            1,
            fitz.Rect(span.bbox),
            "tomorrow",
            font=span.font or "helv",
            size=float(span.size or 11.0),
            color=(0.0, 0.0, 0.0),
            original_text=span.text,
            target_span_id=span.span_id,
            allow_rebuild=True,
            confirm_fallback=consent,
        )
    except _RebuildRolledBack as exc:
        return exc


def _f11_ack(report: tuple):
    return RebuildConsent(acknowledged_glyph_loss=report)


@pytest.mark.parametrize("label,uni,codepoint,fate", _F11_CASES)
def test_rebuild_reports_untouched_unkeepable_glyphs_before_consent(
    tmp_path: Path, label: str, uni: int | None, codepoint: str, fate: str
) -> None:
    pdf = tmp_path / f"f11_report_{label}.pdf"
    _f11_pdf(pdf, uni)
    model = _open_model(pdf, engine="tiered")
    try:
        before = model.doc[0].get_text()
        block = _find_block(model, 0, "today")
        index = block.text.index(chr(int(codepoint[2:], 16)))
        consent = _F11Consent(model, lambda _report: False)
        result = _f11_block_edit(model, consent)
        assert result is EditTextResult.FALLBACK_DECLINED
        assert consent.reports == [
            (UnkeepableGlyph(span_id=None, index=index, codepoint=codepoint, fate=fate),)
        ]
        assert tuple(model.pending_rebuild_glyph_loss) == (), "the report is only live during the ask"
        assert model.doc[0].get_text() == before, "a declined consent must not touch the page"
    finally:
        model.close()


@pytest.mark.parametrize("label,uni,codepoint,fate", _F11_CASES)
def test_acknowledged_untouched_glyph_rebuild_commits(
    tmp_path: Path, label: str, uni: int | None, codepoint: str, fate: str
) -> None:
    pdf = tmp_path / f"f11_ack_{label}.pdf"
    _f11_pdf(pdf, uni)
    model = _open_model(pdf, engine="tiered")
    try:
        consent = _F11Consent(model, _f11_ack)
        result = _f11_block_edit(model, consent)
        assert result is EditTextResult.SUCCESS, f"acknowledged rebuild refused: {result}"
        assert len(consent.reports) == 1 and consent.reports[0]
        live = model.doc[0].get_text()
        assert "tomorrow" in live and "today" not in live
        assert "Downstream line stays" in live
        assert "·" not in live, "U+00B7 substituted"
        assert model.last_commit_outcome is not None
        out = tmp_path / f"saved_{label}.pdf"
        model.save_as(str(out))
        with fitz.open(str(out)) as reopened:
            saved = reopened[0].get_text()
        assert "tomorrow" in saved and "Downstream line stays" in saved
    finally:
        model.close()


@pytest.mark.parametrize("label,uni,codepoint,fate", _F11_CASES)
def test_unacknowledged_untouched_glyph_rebuild_is_still_refused(
    tmp_path: Path, label: str, uni: int | None, codepoint: str, fate: str
) -> None:
    """A bare ``True`` consent (every pre-F11 caller) is not an
    acknowledgement: the rebuild keeps refusing with the page untouched."""
    pdf = tmp_path / f"f11_noack_{label}.pdf"
    _f11_pdf(pdf, uni)
    model = _open_model(pdf, engine="tiered")
    try:
        before = model.doc[0].get_text()
        result = _f11_block_edit(model, _accept_rebuild)
        assert isinstance(result, _RebuildRolledBack), f"committed without acknowledgement: {result}"
        assert result.reason.value == "unidentifiable_glyphs_not_acknowledged", repr(result.reason)
        assert model.doc[0].get_text() == before
    finally:
        model.close()


@pytest.mark.parametrize("mutation", ["wrong_index", "wrong_fate", "empty", "extra"])
def test_a_stale_or_partial_acknowledgement_is_refused(tmp_path: Path, mutation: str) -> None:
    from dataclasses import replace

    pdf = tmp_path / f"f11_stale_{mutation}.pdf"
    _f11_pdf(pdf, 0xFFFD)
    model = _open_model(pdf, engine="tiered")
    try:
        before = model.doc[0].get_text()

        def _answer(report: tuple):
            (glyph,) = report
            ack = {
                "wrong_index": (replace(glyph, index=glyph.index + 1),),
                "wrong_fate": (replace(glyph, fate="removed"),),
                "empty": (),
                "extra": (glyph, UnkeepableGlyph(span_id=None, index=0, codepoint="U+E000", fate="removed")),
            }[mutation]
            return RebuildConsent(acknowledged_glyph_loss=ack)

        result = _f11_block_edit(model, _F11Consent(model, _answer))
        assert isinstance(result, _RebuildRolledBack), f"stale acknowledgement accepted: {result}"
        assert result.reason.value == "unidentifiable_glyphs_not_acknowledged", repr(result.reason)
        assert model.doc[0].get_text() == before
    finally:
        model.close()


@pytest.mark.parametrize("typed", ["\ufffd", "\ufffc"], ids=["fffd", "fffc"])
def test_a_typed_placeholder_is_refused_even_when_acknowledged(tmp_path: Path, typed: str) -> None:
    """Placeholders the USER typed are never acknowledgeable: the report is
    empty (nothing to name in the dialog) and a fabricated acknowledgement
    of every placeholder still refuses."""
    pdf = tmp_path / "f11_typed.pdf"
    _f11_pdf(pdf, 0xFFFD)
    model = _open_model(pdf, engine="tiered")
    try:
        before = model.doc[0].get_text()
        block = _find_block(model, 0, "today")
        requested = block.text.replace("today", "tomorrow" + typed)
        fabricated = tuple(
            UnkeepableGlyph(
                span_id=None, index=i, codepoint=f"U+{ord(typed):04X}", fate="replaced"
            )
            for i, ch in enumerate(requested)
            if ch == typed
        )
        consent = _F11Consent(
            model, lambda _report: RebuildConsent(acknowledged_glyph_loss=fabricated)
        )
        result = _f11_block_edit(model, consent, new_text=requested)
        assert consent.reports == [()], "a typed placeholder must not be offered for acknowledgement"
        assert isinstance(result, _RebuildRolledBack), f"typed placeholder committed: {result}"
        assert result.reason.value == "unidentifiable_glyphs_not_acknowledged", repr(result.reason)
        assert model.doc[0].get_text() == before
    finally:
        model.close()


@pytest.mark.parametrize("label,uni,codepoint,fate", [_F11_CASES[0], _F11_CASES[2]])
def test_protected_neighbour_glyph_needs_acknowledgement(
    tmp_path: Path, label: str, uni: int, codepoint: str, fate: str
) -> None:
    """An unkeepable glyph in an overlapping neighbour run (redacted and
    replayed by the rebuild) is reported with its run id; without the
    acknowledgement the rebuild refuses -- U+FFFD used to be replaced
    silently -- and with it the rebuild commits."""
    pdf = tmp_path / f"f11_protected_{label}.pdf"
    _f11_pdf(pdf, uni, protected=True)
    model = _open_model(pdf, engine="tiered")
    try:
        before = model.doc[0].get_text()
        glyph_run = _run_with_text(model, chr(int(codepoint[2:], 16)))
        refused = _f11_run_edit(model, _accept_rebuild)
        assert isinstance(refused, _RebuildRolledBack), f"neighbour glyph changed silently: {refused}"
        assert refused.reason.value == "unidentifiable_glyphs_not_acknowledged", repr(refused.reason)
        assert model.doc[0].get_text() == before

        consent = _F11Consent(model, _f11_ack)
        result = _f11_run_edit(model, consent)
        assert consent.reports == [
            (UnkeepableGlyph(span_id=glyph_run.span_id, index=0, codepoint=codepoint, fate=fate),)
        ]
        assert result is EditTextResult.SUCCESS, f"acknowledged rebuild refused: {result}"
        live = model.doc[0].get_text()
        assert "tomorrow" in live and "Downstream line stays" in live
    finally:
        model.close()


@pytest.mark.parametrize("label,uni,codepoint,fate", _F11_CASES)
def test_unkeepable_glyph_fate_matches_htmlbox(
    label: str, uni: int | None, codepoint: str, fate: str
) -> None:
    """The fate the dialog announces is what htmlbox does with the glyph:
    "removed" = drawn as .notdef (glyph id 0, blank), "replaced" = some
    other inked glyph.  Pins the static mapping to the pinned PyMuPDF."""
    from model.pdf_text_edit import _unkeepable_glyph_fate

    ch = chr(int(codepoint[2:], 16)) if uni is not None else "\u0080"
    assert _unkeepable_glyph_fate(ch) == ("replaced" if uni is None else fate)
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=100)
        page.insert_htmlbox(fitz.Rect(10, 10, 190, 90), f"a{ch}b", css="* {font-size: 11pt;}")
        gids = [
            int(c[1])
            for span in page.get_texttrace()
            for c in span["chars"]
            if chr(c[0]) not in "ab"
        ]
    finally:
        doc.close()
    assert len(gids) == 1, gids
    assert (gids[0] == 0) == (_unkeepable_glyph_fate(ch) == "removed"), (codepoint, gids)


# --- F13-VF-4: the rebuild must not overprint an untouched right-hand neighbour ---

_NB_EDIT_X = 72.0
_NB_Y = 700.0


def _neighbour_pdf(path: Path, *, gap: float = 0.0, neighbour_dy: float = 0.0,
                   neighbour_left: bool = False, y: float = _NB_Y) -> float:
    """``ab`` (Helvetica 14) followed by the untouched red run ``NEXT`` (10 pt,
    so it is its own run) starting ``gap`` pt after ``ab``.  Returns the
    neighbour's left edge."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    helv = fitz.Font("helv")
    edit_w = helv.text_length("ab", fontsize=14)
    next_x = _NB_EDIT_X + edit_w + gap
    if neighbour_left:
        next_x = _NB_EDIT_X - 60.0
    page.insert_text((_NB_EDIT_X, y), "ab", fontsize=14, fontname="helv")
    page.insert_text(
        (next_x, y + neighbour_dy), "NEXT", fontsize=10, fontname="helv", color=(1, 0, 0)
    )
    page.insert_text((_NB_EDIT_X, y + 40), "Below line", fontsize=14, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()
    return next_x


def _neighbour_edit(pdf: Path, new_text: str, engine: str = "legacy"):
    """Consented rebuild of the ``ab`` run (Helvetica 14), saved to
    ``<pdf>_saved.pdf``; returns ``(outcome_or_exception, spans_after,
    spans_before)`` as ``_text_spans`` reads them from the saved and the
    original file."""
    model = _open_model(pdf, engine=engine)
    try:
        run = _run_with_text(model, "ab")
        try:
            outcome: object = model.edit_text(
                1, fitz.Rect(run.bbox), new_text, font="helv", size=14.0,
                original_text="ab", target_span_id=run.span_id, target_mode="run",
                allow_rebuild=True, confirm_fallback=_accept_rebuild,
            )
        except _RebuildRolledBack as exc:
            outcome = exc
        saved = pdf.with_name(pdf.stem + "_saved.pdf")
        model.save_as(str(saved))
        reopened = fitz.open(str(saved))
        try:
            words = _text_spans(reopened[0])
            original = fitz.open(str(pdf))
            try:
                before = _text_spans(original[0])
            finally:
                original.close()
        finally:
            reopened.close()
        return outcome, words, before
    finally:
        model.close()


def _text_spans(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    """Spans, not words: abutting runs of different style stay separate."""
    return [
        (span["text"].strip(), fitz.Rect(span["bbox"]))
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", ())
        for span in line["spans"]
        if span["text"].strip()
    ]


def _word_rect(words, text: str) -> fitz.Rect:
    return next(rect for word, rect in words if word == text)


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("new_text", ["abc", "abx"])
def test_rebuild_never_overprints_untouched_right_neighbour(
    tmp_path: Path, engine: str, new_text: str
) -> None:
    """F13-VF-4: the edited word is re-drawn at its old origin in the substitute
    font; when it grows it must stay left of the next run on the line (the page
    margin is not the only wall), and the neighbour must not move."""
    pdf = tmp_path / "nb.pdf"
    next_x = _neighbour_pdf(pdf)
    outcome, words, before = _neighbour_edit(pdf, new_text, engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    edited = _word_rect(words, new_text)
    neighbour = _word_rect(words, "NEXT")
    assert neighbour == _word_rect(before, "NEXT"), "the untouched neighbour moved"
    assert abs(neighbour.x0 - next_x) < 0.5
    assert edited.x1 <= neighbour.x0 + 0.5, (
        f"{new_text!r} spans x {edited.x0:.1f}-{edited.x1:.1f} over NEXT at {neighbour.x0:.1f}"
    )
    assert _word_rect(words, "Below line").y0 > edited.y1, "the line below must be untouched"


def test_rebuild_refuses_when_the_text_cannot_fit_before_the_neighbour(tmp_path: Path) -> None:
    """A word that would need to shrink below the 50 % floor to clear the
    neighbour is refused whole (page untouched), never overprinted."""
    pdf = tmp_path / "nb_wide.pdf"
    _neighbour_pdf(pdf)
    outcome, words, before = _neighbour_edit(pdf, "WWWWWWWWWW")
    assert not isinstance(outcome, EditTextResult), outcome
    assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
    assert sorted(w for w, _r in words) == sorted(w for w, _r in before)


def test_rebuild_keeps_the_fast_path_when_the_neighbour_is_far_enough(tmp_path: Path) -> None:
    """GUARD: clearance is measured to the neighbour, not the old text -- a gap
    that holds the growth keeps the unscaled origin-preserving insert."""
    pdf = tmp_path / "nb_gap.pdf"
    _neighbour_pdf(pdf, gap=40.0)
    outcome, words, _before = _neighbour_edit(pdf, "abc")
    assert outcome is EditTextResult.SUCCESS
    edited = _word_rect(words, "abc")
    natural = fitz.Font("helv").text_length("abc", fontsize=14)
    assert abs((edited.x1 - edited.x0) - natural) < 0.6, (edited, natural)


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("gap", [-0.3, -0.45, -1.0])
@pytest.mark.parametrize("new_text", ["abc", "abx"])
def test_rebuild_never_overprints_a_neighbour_that_starts_inside_the_edited_extent(
    tmp_path: Path, engine: str, gap: float, new_text: str
) -> None:
    """F14-VF4-OVERLAP: negative kerning / condensed spacing across a style
    change (or a float32 bbox overlap) puts the next run's left edge a fraction
    of a point INSIDE the edited run's box.  It is replayed at its origin, but
    that does not stop the grown edit being drawn over it: it must be a wall
    too (at the edited extent's old right edge -- the text was already there),
    so the edit shrinks, wraps or is refused, never overprints."""
    pdf = tmp_path / "nb_inside.pdf"
    next_x = _neighbour_pdf(pdf, gap=gap)
    outcome, words, before = _neighbour_edit(pdf, new_text, engine)
    neighbour = _word_rect(words, "NEXT")
    assert neighbour == _word_rect(before, "NEXT"), "the untouched neighbour moved"
    assert abs(neighbour.x0 - next_x) < 0.5
    if isinstance(outcome, EditTextResult):
        assert outcome is EditTextResult.SUCCESS, outcome
        edited = _word_rect(words, new_text)
        orig = _word_rect(before, "ab")
        assert edited.x1 <= orig.x1 + 0.5, (
            f"{new_text!r} spans x {edited.x0:.1f}-{edited.x1:.1f}, past the old right "
            f"edge {orig.x1:.1f} over NEXT at {neighbour.x0:.1f}"
        )
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
        assert sorted(w for w, _r in words) == sorted(w for w, _r in before)


@pytest.mark.parametrize("gap", [-0.3, -1.0])
def test_rebuild_keeps_the_fast_path_for_a_narrower_edit_beside_an_inside_neighbour(
    tmp_path: Path, gap: float
) -> None:
    """GUARD: the wall for a neighbour starting inside the extent is the old
    right edge, so an edit that is not wider than the original keeps the
    unscaled origin-preserving insert."""
    pdf = tmp_path / "nb_inside_narrow.pdf"
    _neighbour_pdf(pdf, gap=gap)
    outcome, words, _before = _neighbour_edit(pdf, "a")
    assert outcome is EditTextResult.SUCCESS
    edited = _word_rect(words, "a")
    natural = fitz.Font("helv").text_length("a", fontsize=14)
    assert abs((edited.x1 - edited.x0) - natural) < 0.6, (edited, natural)


@pytest.mark.parametrize("variant", ["other_line", "left_of_edit"])
def test_rebuild_ignores_runs_that_are_not_to_the_right_on_the_line(
    tmp_path: Path, variant: str
) -> None:
    """GUARD: a run on another line, or to the LEFT of the edit, is no wall."""
    pdf = tmp_path / f"nb_{variant}.pdf"
    if variant == "other_line":
        _neighbour_pdf(pdf, neighbour_dy=-40.0)
    else:
        _neighbour_pdf(pdf, neighbour_left=True)
    outcome, words, _before = _neighbour_edit(pdf, "abcd")
    assert outcome is EditTextResult.SUCCESS
    edited = _word_rect(words, "abcd")
    natural = fitz.Font("helv").text_length("abcd", fontsize=14)
    assert abs((edited.x1 - edited.x0) - natural) < 0.6, (edited, natural)


# --- F15-VF4OV-DIAGONAL: only runs whose bbox IS their footprint are walls ---


def _rotated_neighbour_pdf(path: Path, *, pivot_x: float, angle: float, text: str = "DRAFT",
                           size: float = 60.0) -> fitz.Rect:
    """``ab`` (Helvetica 14) plus a light-grey text run turned by ``angle`` degrees
    about ``(pivot_x, 800)``: a watermark whose axis-aligned bbox covers the edited
    line while its glyphs stay clear of it.  Returns that run's bbox as the model
    reports it."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((_NB_EDIT_X, _NB_Y), "ab", fontsize=14, fontname="helv")
    pivot = fitz.Point(pivot_x, 800.0)
    page.insert_text(pivot, text, fontsize=size, fontname="helv", color=(0.85, 0.85, 0.85),
                     morph=(pivot, fitz.Matrix(angle)))
    page.insert_text((_NB_EDIT_X, _NB_Y + 40), "Below line", fontsize=14, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()
    model = _open_model(path, engine="legacy")
    try:
        return fitz.Rect(_run_with_text(model, text).bbox)
    finally:
        model.close()


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize(
    ("pivot_x", "case"), [(112.0, "starts_inside_extent"), (150.0, "starts_right_of_extent")]
)
def test_rebuild_ignores_a_diagonal_watermark_whose_bbox_covers_the_line(
    tmp_path: Path, engine: str, pivot_x: float, case: str
) -> None:
    """F15-VF4OV-DIAGONAL: a 45-degree watermark's axis-aligned bbox is a huge
    square that covers the edited line, but its glyphs are not ON the line.  It
    is no right-hand neighbour: the edit keeps the unscaled origin-preserving
    insert (no strategy-C shrink), and the untouched watermark does not move.
    Real collisions with its ink stay the overprint guard's job."""
    pdf = tmp_path / f"wm_{case}.pdf"
    wm = _rotated_neighbour_pdf(pdf, pivot_x=pivot_x, angle=45.0)
    # the geometry that tripped the wall: bbox shares the line band and starts
    # past the edit's origin (inside the old extent, or to its right)
    assert wm.y0 < _NB_Y - 14 and wm.y1 > _NB_Y
    assert wm.x0 > _NB_EDIT_X + 0.5
    outcome, words, _before = _neighbour_edit(pdf, "abcdefgh", engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    edited = _word_rect(words, "abcdefgh")
    natural = fitz.Font("helv").text_length("abcdefgh", fontsize=14)
    assert abs((edited.x1 - edited.x0) - natural) < 0.6, (edited, natural)


def test_rebuild_keeps_the_wall_for_an_upright_vertical_run_on_the_line(tmp_path: Path) -> None:
    """GUARD: a 90-degree run's bbox IS its footprint, so it stays a wall -- only
    runs turned off the page axes are exempt (F15-VF4OV-DIAGONAL)."""
    pdf = tmp_path / "nb_vertical.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((_NB_EDIT_X, _NB_Y), "ab", fontsize=14, fontname="helv")
    page.insert_text((_NB_EDIT_X + 40.0, _NB_Y + 10.0), "NEXT", fontsize=10, fontname="helv",
                     rotate=90, color=(1, 0, 0))
    page.insert_text((_NB_EDIT_X, _NB_Y + 40), "Below line", fontsize=14, fontname="helv")
    doc.save(str(pdf), garbage=0)
    doc.close()
    outcome, words, before = _neighbour_edit(pdf, "abcdefgh")
    neighbour_x0 = min(rect.x0 for word, rect in before if word not in ("ab", "Below line"))
    natural = fitz.Font("helv").text_length("abcdefgh", fontsize=14)
    assert isinstance(outcome, EditTextResult), outcome
    edited = _word_rect(words, "abcdefgh")
    assert edited.x1 <= neighbour_x0 + 0.5, (edited, neighbour_x0)
    assert (edited.x1 - edited.x0) < natural - 1.0, "the wall no longer holds the edit back"


_FLOOR_Y = 400.0


def _diagonal_below_pdf(path: Path, *, upright: bool) -> None:
    """A line of upright text and, under it, a 45-degree watermark whose bbox top
    lies below the line though its ink only reaches that height at one corner;
    ``upright`` adds a plain upright run at the same place."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((_NB_EDIT_X, _FLOOR_Y), "ab", fontsize=14, fontname="helv")
    pivot = fitz.Point(60.0, _FLOOR_Y + 210.0)
    page.insert_text(pivot, "DRAFT", fontsize=60, fontname="helv", color=(0.85, 0.85, 0.85),
                     morph=(pivot, fitz.Matrix(45)))
    if upright:
        page.insert_text((_NB_EDIT_X, _FLOOR_Y + 60.0), "Upright", fontsize=14, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()


@pytest.mark.parametrize("upright", [False, True])
def test_wrap_floor_ignores_a_diagonal_run_below_the_line(tmp_path: Path, upright: bool) -> None:
    """F15-VF4OV-DIAGONAL: the wrap floor is the top of the nearest untouched
    text below the edit; a turned run's bbox top is not text there.  An upright
    run beside it still is."""
    from model.pdf_text_edit import _wrap_floor

    pdf = tmp_path / "floor.pdf"
    _diagonal_below_pdf(pdf, upright=upright)
    doc = fitz.open(str(pdf))
    try:
        page = doc[0]
        extent = fitz.Rect(_NB_EDIT_X, _FLOOR_Y - 11.0, _NB_EDIT_X + 15.6, _FLOOR_Y + 3.0)
        diagonal = next(
            fitz.Rect(b["bbox"]) for b in page.get_text("dict")["blocks"]
            if b.get("type") == 0 and any(
                s["text"] == "DRAFT" for ln in b["lines"] for s in ln["spans"]
            )
        )
        assert extent.y1 < diagonal.y0 < _FLOOR_Y + 80.0, "geometry: bbox top just below the line"
        above_y = _FLOOR_Y + 80.0  # blocks that start above it stay put (never pushed down)
        floor = _wrap_floor(page, extent, 60.0, 200.0, above_y)
        if upright:
            assert floor is not None and floor > _FLOOR_Y + 40.0
        else:
            assert floor is None, "a diagonal run's bbox must not floor the wrap"
    finally:
        doc.close()


def test_ink_core_of_a_diagonal_glyph_is_its_own_turned_box_not_the_bbox_square() -> None:
    """F15-VF4OV-DIAGONAL: the extracted box of a 45-degree 60 pt glyph is an
    ~89 pt square; the overprint guard's core must be the glyph's own turned
    box (advance long), so text on a line the glyph never reaches is clear of
    it while text laid on the glyph itself still collides."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        pivot = fitz.Point(150.0, 760.0)
        page.insert_text(pivot, "DRAFT", fontsize=60, fontname="helv",
                         morph=(pivot, fitz.Matrix(45)))
        glyphs = {g.key[0]: g for g in _page_glyphs(page)}
    finally:
        doc.close()
    d = glyphs["D"]
    assert d.bbox.width > 60.0, "the extracted box is the turned box's enclosure"
    assert 35.0 < d.advance < 50.0, d.advance  # Helvetica D at 60 pt is 43.3 pt wide
    core = _glyph_ink_core(d)
    assert not isinstance(core, fitz.Rect)
    far_line = fitz.Rect(115.0, 691.0, 123.0, 702.0)  # inside the bbox square, 60 pt off the ink
    assert d.bbox.intersects(far_line)
    assert not _cores_overlap(core, far_line)
    ux, uy = d.direction
    centre = (d.origin[0] + ux * d.advance / 2 + uy * 21.0, d.origin[1] + uy * d.advance / 2 - ux * 21.0)
    on_ink = fitz.Rect(centre[0] - 2.0, centre[1] - 2.0, centre[0] + 2.0, centre[1] + 2.0)
    assert _cores_overlap(core, on_ink)


# --- D-DIAG-INK: the overprint guard ignores runs turned off the page axes ---
#
# Owner decision (after round 15): edited text may print over a diagonal
# watermark's ink.  Off-axis runs are no collision for the guard, just as they
# are no neighbour wall and no wrap floor; horizontal and vertical runs still
# block.  The watermark itself must come out of the edit unchanged.

_DIAG_X = 110.0
_DIAG_Y = 300.0
_DIAG_PIVOT = (170.0, 330.0)
_DIAG_BAND = (286, 306)  # pixel rows of the edited line


def _diag_ink_pdf(
    path: Path,
    *,
    neighbour_x: float | None = None,
    pivot: tuple[float, float] = _DIAG_PIVOT,
    opacity: float = 1.0,
    rotate_page: int = 0,
) -> None:
    """``John`` (Helvetica 12) on a line, a light-grey 45-degree ``DRAFT COPY``
    whose ink crosses the line to the right of it, a line below; with
    ``neighbour_x`` a red upright ``Smith`` at that x on the same line.
    ``pivot`` moves the watermark (S17-WMARK-UNDER: onto the old word's own
    box), ``opacity`` draws it through an ExtGState, ``rotate_page`` sets
    ``/Rotate``."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72.0, _DIAG_Y), "Name:", fontsize=12, fontname="helv")
    page.insert_text((_DIAG_X, _DIAG_Y), "John", fontsize=12, fontname="helv")
    if neighbour_x is not None:
        page.insert_text((neighbour_x, _DIAG_Y), "Smith", fontsize=12, fontname="helv",
                         color=(1, 0, 0))
    turn = fitz.Point(*pivot)
    page.insert_text(turn, "DRAFT COPY", fontsize=60, fontname="helv", color=(0.85, 0.85, 0.85),
                     morph=(turn, fitz.Matrix(45)), fill_opacity=opacity)
    page.insert_text((72.0, _DIAG_Y + 30.0), "Next paragraph line", fontsize=12, fontname="helv")
    if rotate_page:
        page.set_rotation(rotate_page)
    doc.save(str(path), garbage=0)
    doc.close()


def _diag_edit(pdf: Path, new_text: str, engine: str):
    """Rebuild-edit ``John`` -> ``new_text``; ``(outcome, saved_path)``."""
    model = _open_model(pdf, engine=engine)
    try:
        run = _run_with_text(model, "John")
        try:
            outcome: object = model.edit_text(
                1, fitz.Rect(run.bbox), new_text, font="helv", size=12.0,
                original_text="John", target_span_id=run.span_id, target_mode="run",
                allow_rebuild=True, confirm_fallback=_accept_rebuild,
            )
        except _RebuildRolledBack as exc:
            outcome = exc
        saved = pdf.with_name(pdf.stem + "_saved.pdf")
        model.save_as(str(saved))
        return outcome, saved
    finally:
        model.close()


def _off_axis_glyphs(path: Path) -> list[tuple[str, float, float, float, float]]:
    """(char, origin x, origin y, dir x, dir y) of every off-axis glyph."""
    doc = fitz.open(str(path))
    try:
        return sorted(
            (g.key[0], round(g.origin[0], 1), round(g.origin[1], 1),
             round(g.direction[0], 3), round(g.direction[1], 3))
            for g in _page_glyphs(doc[0]) if not _is_axis_aligned_dir(g.direction)
        )
    finally:
        doc.close()


def _ink_collisions(path: Path, rect: fitz.Rect) -> int:
    """Upright glyphs near ``rect`` whose ink core lies on an off-axis glyph's."""
    doc = fitz.open(str(path))
    try:
        glyphs = [g for g in _page_glyphs(doc[0]) if g.inked]
    finally:
        doc.close()
    upright = [g for g in glyphs if _is_axis_aligned_dir(g.direction) and g.bbox.intersects(rect)]
    turned = [g for g in glyphs if not _is_axis_aligned_dir(g.direction)]
    return sum(
        1 for a in upright
        if any(_cores_overlap(_glyph_ink_core(a), _glyph_ink_core(b)) for b in turned)
    )


def _rows_outside(path: Path, band: tuple[int, int]) -> list[bytes]:
    """Pixel rows of page 1 at 72 dpi except those of ``band``."""
    doc = fitz.open(str(path))
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    finally:
        doc.close()
    stride = pix.width * pix.n
    data = pix.samples
    return [
        data[y * stride:(y + 1) * stride]
        for y in range(pix.height) if not band[0] <= y <= band[1]
    ]


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("new_text", ["Johnathan Smithers", "Johnny B"])
def test_edit_may_print_over_a_diagonal_watermark_and_leaves_it_intact(
    tmp_path: Path, engine: str, new_text: str
) -> None:
    """D-DIAG-INK: the edited word lands on the 45-degree watermark's ink and
    the edit still succeeds at full size in the original font; the watermark
    keeps its text, directions and origins and every pixel outside the line."""
    pdf = tmp_path / "diag.pdf"
    _diag_ink_pdf(pdf)
    before_turned = _off_axis_glyphs(pdf)
    assert sorted(c[0] for c in before_turned if c[0].strip()) == sorted("DRAFTCOPY")
    rows_before = _rows_outside(pdf, _DIAG_BAND)
    outcome, saved = _diag_edit(pdf, new_text, engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    doc = fitz.open(str(saved))
    try:
        spans = [
            s for b in doc[0].get_text("dict")["blocks"] for ln in b.get("lines", ())
            for s in ln["spans"] if s["text"].strip() == new_text
        ]
    finally:
        doc.close()
    assert len(spans) == 1, spans
    span = spans[0]
    assert span["font"] == "Helvetica" and span["size"] == pytest.approx(12.0)
    natural = fitz.Font("helv").text_length(new_text, fontsize=12.0)
    assert span["bbox"][2] - span["bbox"][0] == pytest.approx(natural, abs=0.6)
    # premise: the new word's ink really sits on the watermark's ink
    assert _ink_collisions(saved, fitz.Rect(span["bbox"])) >= 1
    # the watermark: same glyphs, same turn, same places, same pixels off the line
    assert _off_axis_glyphs(saved) == before_turned
    assert _rows_outside(saved, _DIAG_BAND) == rows_before


# --- S17-WMARK-UNDER: the old word's own box lies on the watermark ----------
#
# Owner decision (2026-10-12): a diagonal watermark glyph under the edited
# word's OLD box is protected.  MuPDF's text redaction erases any glyph whose
# box touches the redacted point, and the box of a 60 pt 45-degree glyph is
# a big square; the edit used to be refused as UNTOUCHED_TEXT_WOULD_BE_LOST.
# Now only the old word's glyphs go, the watermark's drawing operators stay
# byte for byte where they were (same text, origins, directions, ink, order).

_WMARK_UNDER_PIVOTS = [(120.0, 350.0), (135.0, 345.0)]


@pytest.mark.parametrize("opacity", [1.0, 0.5])
@pytest.mark.parametrize("pivot", _WMARK_UNDER_PIVOTS)
@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_editing_a_word_over_a_diagonal_watermark_keeps_the_watermark(
    tmp_path: Path, engine: str, pivot: tuple[float, float], opacity: float
) -> None:
    """S17-WMARK-UNDER: ``John`` -> ``Johnny B`` where the watermark's glyphs
    lie under the old word: the edit succeeds, the watermark keeps its text,
    turn, origins and every pixel outside the edited line."""
    pdf = tmp_path / "under.pdf"
    _diag_ink_pdf(pdf, pivot=pivot, opacity=opacity)
    before_turned = _off_axis_glyphs(pdf)
    assert sorted(c[0] for c in before_turned if c[0].strip()) == sorted("DRAFTCOPY")
    rows_before = _rows_outside(pdf, _DIAG_BAND)
    outcome, saved = _diag_edit(pdf, "Johnny B", engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    doc = fitz.open(str(saved))
    try:
        words = [w[4] for w in doc[0].get_text("words")]
    finally:
        doc.close()
    assert "John" not in words and "Johnny" in words, words
    assert _off_axis_glyphs(saved) == before_turned
    assert _rows_outside(saved, _DIAG_BAND) == rows_before


@pytest.mark.parametrize("page_rotation", [0, 90, 180])
@pytest.mark.parametrize("pivot", _WMARK_UNDER_PIVOTS)
def test_owned_redaction_leaves_an_off_axis_run_under_the_word_untouched(
    tmp_path: Path, pivot: tuple[float, float], page_rotation: int
) -> None:
    """S17-WMARK-UNDER at the chokepoint every legacy rewrite erases through
    (``_redact_owned_glyphs``): erasing ``John`` loses no glyph, takes none of
    the watermark's, and its drawing operators come out byte for byte."""
    from model.pdf_text_edit import _redact_owned_glyphs

    pdf = tmp_path / "under_unit.pdf"
    _diag_ink_pdf(pdf, pivot=pivot, rotate_page=page_rotation)
    doc = fitz.open(str(pdf))
    try:
        page = doc[0]
        before = _page_glyphs(page)
        owned = [g for g in before if g.key[0] in "John" and g.direction[1] == 0.0
                 and 108.0 < g.origin[0] < 140.0]
        assert len(owned) == 4
        turned_before = sorted(
            (g.key, round(g.direction[0], 3), round(g.direction[1], 3))
            for g in before if not _is_axis_aligned_dir(g.direction)
        )
        watermark_show = b"[<445241465420434f5059>]TJ"  # DRAFT COPY, as written
        assert watermark_show in page.read_contents()
        outcome = _redact_owned_glyphs(page, before, owned, [])
        assert list(outcome.survivors) == [] and list(outcome.lost_foreign) == [], outcome
        after = _page_glyphs(page)
        assert not [g for g in after if g.key[0] in "John" and 108.0 < g.origin[0] < 140.0
                    and _is_axis_aligned_dir(g.direction)]
        turned_after = sorted(
            (g.key, round(g.direction[0], 3), round(g.direction[1], 3))
            for g in after if not _is_axis_aligned_dir(g.direction)
        )
        assert turned_after == turned_before
        assert watermark_show in page.read_contents()
    finally:
        doc.close()


def test_push_down_keeps_a_diagonal_watermark_whose_box_holds_the_pushed_text(
    tmp_path: Path,
) -> None:
    """S17-WMARK-UNDER at the push-down's erase (the other legacy caller of the
    chokepoint): the block below an overflowing edit is erased and redrawn
    lower, and the 45-degree watermark whose glyph boxes hold it stays."""
    pdf = tmp_path / "pd_wmark.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Edited line", fontsize=12, fontname="helv")
    page.insert_text((300, 300), "Pushme", fontsize=12, fontname="helv")
    turn = fitz.Point(250, 350)
    page.insert_text(turn, "DRAFT COPY", fontsize=60, fontname="helv", color=(0.85, 0.85, 0.85),
                     morph=(turn, fitz.Matrix(45)))
    doc.save(str(pdf), garbage=0)
    doc.close()
    before_turned = _off_axis_glyphs(pdf)
    model = _open_model(pdf, engine="legacy")
    try:
        page = model.doc[0]
        with font_compaction_scope(model.doc):
            model._push_down_overlapping_text(
                page, fitz.Rect(page.rect), above_y=105.0, new_bottom=400.0,
                edit_x0=60.0, edit_x1=500.0,
            )
        words = _word_rects(page)
        assert words["Pushme"].y0 > 390.0, words  # pushed below the new bottom
        saved = tmp_path / "pd_wmark_saved.pdf"
        model.save_as(str(saved))
    finally:
        model.close()
    assert _off_axis_glyphs(saved) == before_turned


def _wwww(text: str, turn: float) -> list:
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        pivot = fitz.Point(100.0, 300.0)
        page.insert_text(pivot, text, fontsize=40, fontname="helv",
                         morph=(pivot, fitz.Matrix(turn)))
        return _page_glyphs(page)
    finally:
        doc.close()


def test_new_text_overprints_skips_off_axis_untouched_glyphs_only() -> None:
    """D-DIAG-INK: an added upright glyph lying on an untouched 45-degree glyph
    is no overprint; the same glyph on an untouched upright one still is."""
    from model.pdf_text_edit import _new_text_overprints

    added = _wwww("MMMM", 0.0)
    turned_under = _wwww("WWWW", 45.0)
    assert any(
        _cores_overlap(_glyph_ink_core(a), _glyph_ink_core(t))
        for a in added for t in turned_under
    ), "premise: the added ink lies on the turned ink"
    assert _new_text_overprints(turned_under, turned_under + added, []) == []
    upright_under = _wwww("WWWW", 0.0)
    assert _new_text_overprints(upright_under, upright_under + added, [])


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_a_horizontal_neighbour_still_blocks_next_to_a_diagonal_watermark(
    tmp_path: Path, engine: str
) -> None:
    """D-DIAG-INK GUARD: the diagonal watermark is ignored, but an upright run
    on the line, clear of the watermark's ink, still holds the edit back: the
    long new text wraps (or is refused) instead of printing over it."""
    neighbour_x = 300.0
    pdf = tmp_path / "diag_nb.pdf"
    _diag_ink_pdf(pdf, neighbour_x=neighbour_x)
    outcome, saved = _diag_edit(pdf, "Johnathan Smithers Johnathan Smithers", engine)
    if isinstance(outcome, _RebuildRolledBack):
        assert outcome.reason is not TextEditRefusal.UNTOUCHED_TEXT_WOULD_BE_LOST, outcome
        return  # refused: the neighbour was protected
    assert outcome is EditTextResult.SUCCESS, outcome
    doc = fitz.open(str(saved))
    try:
        spans = _text_spans(doc[0])
    finally:
        doc.close()
    smith = _word_rect(spans, "Smith")
    assert smith.x0 == pytest.approx(neighbour_x, abs=0.6), "the neighbour did not move"
    edited = [r for t, r in spans if t.startswith(("Johnathan", "Smithers"))]
    assert edited, spans
    for r in edited:
        assert r.x1 <= smith.x0 + 0.5 or r.y0 > smith.y1 - 1.0, (r, smith)


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_a_vertical_run_still_blocks_next_to_a_diagonal_watermark(
    tmp_path: Path, engine: str
) -> None:
    """D-DIAG-INK GUARD: a 90-degree run (its bbox IS its footprint) on the
    line is not exempt: the edit never prints over it."""
    pdf = tmp_path / "diag_vert.pdf"
    _diag_ink_pdf(pdf)
    doc = fitz.open(str(pdf))
    page = doc[0]
    page.insert_text((300.0, _DIAG_Y + 8.0), "NEXT", fontsize=10, fontname="helv", rotate=90,
                     color=(1, 0, 0))
    doc.save(str(tmp_path / "v.pdf"), garbage=0)
    doc.close()
    vert = tmp_path / "v.pdf"
    outcome, saved = _diag_edit(vert, "Johnathan Smithers Johnathan Smithers", engine)
    if isinstance(outcome, _RebuildRolledBack):
        assert outcome.reason is not TextEditRefusal.UNTOUCHED_TEXT_WOULD_BE_LOST, outcome
        return
    assert outcome is EditTextResult.SUCCESS, outcome
    doc = fitz.open(str(saved))
    try:
        glyphs = [g for g in _page_glyphs(doc[0]) if g.inked and _is_axis_aligned_dir(g.direction)]
    finally:
        doc.close()
    upright = [g for g in glyphs if abs(g.direction[0]) > 0.99]
    vertical = [g for g in glyphs if abs(g.direction[1]) > 0.99]
    assert vertical and upright
    assert not any(
        _cores_overlap(_glyph_ink_core(a), _glyph_ink_core(v)) for a in upright for v in vertical
    )


# --- F14-VF4-WRAP: a wrapped edit must not draw over untouched text below ---
#
# The htmlbox runs from the edited line down to the page bottom, but the
# push-down only moves BLOCKS that start below the edit: the next line of the
# same paragraph stays put, so a wrap (forced by the F13-VF-4 neighbour cap,
# or by the page margin) used to be drawn on top of it and reported SUCCESS.

_WRAP_SECOND = "second line untouched"
_WRAP_REST = "rest of the first line"
_WRAP_LONG = " ".join(
    ["ab"] + ["cd", "ef", "gh", "ij", "kl", "mn", "op", "qr", "st", "uv", "wx", "yz"] * 3
)


def _same_block_pdf(
    path: Path, *, neighbour: bool = True, below_dy: float = 17.0, lead: str = ""
) -> None:
    """One block: an optional blue run ``lead``, then ``ab`` (Helvetica 14),
    when ``neighbour`` the flush red run `` rest of the first line``, and
    ``below_dy`` pt lower the same block's next line ``second line untouched``."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    helv = fitz.Font("helv")
    edit_x = _NB_EDIT_X
    if lead:
        page.insert_text((edit_x, _NB_Y), lead, fontsize=14, fontname="helv", color=(0, 0, 1))
        edit_x += helv.text_length(lead, fontsize=14)
    edit_w = helv.text_length("ab", fontsize=14)
    page.insert_text((edit_x, _NB_Y), "ab", fontsize=14, fontname="helv")
    if neighbour:
        page.insert_text(
            (edit_x + edit_w, _NB_Y), " " + _WRAP_REST,
            fontsize=14, fontname="helv", color=(1, 0, 0),
        )
    page.insert_text((_NB_EDIT_X, _NB_Y + below_dy), _WRAP_SECOND, fontsize=14, fontname="helv")
    blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
    assert len(blocks) == 1, "premise: the line below belongs to the edited block"
    doc.save(str(path), garbage=0)
    doc.close()


def _overprinted(words, before, untouched: tuple[str, ...]) -> list[tuple[str, str]]:
    """(new span, untouched span) pairs drawn over each other; also fails when
    an untouched span moved."""
    hits: list[tuple[str, str]] = []
    for name in untouched:
        rect = _word_rect(words, name)
        assert rect == _word_rect(before, name), f"untouched {name!r} moved"
        for word, r in words:
            if word in untouched:
                continue
            common = r & rect
            if r.intersects(rect) and common.height > 1.0 and common.width > 0.5:
                hits.append((word, name))
    return hits


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_rebuild_wrap_at_the_neighbour_never_draws_over_the_same_block_line_below(
    tmp_path: Path, engine: str
) -> None:
    """F14-VF4-WRAP: ``ab`` -> ``ab cd ef`` against a flush neighbour has no
    room to wrap (the next line of the paragraph is 17 pt below and is not
    pushed) and cannot shrink to 50 % before the neighbour: refused whole."""
    pdf = tmp_path / "wrap_nb.pdf"
    _same_block_pdf(pdf)
    outcome, words, before = _neighbour_edit(pdf, "ab cd ef", engine)
    assert not _overprinted(words, before, (_WRAP_SECOND, _WRAP_REST)), words
    assert not isinstance(outcome, EditTextResult), outcome
    assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
    assert sorted(w for w, _r in words) == sorted(w for w, _r in before)


def test_rebuild_wrap_at_the_page_margin_never_draws_over_the_same_block_line_below(
    tmp_path: Path,
) -> None:
    """The same class without a right-hand neighbour (predates F13-VF-4): the
    edited run ends its line, an untouched run starts it, so the paragraph's
    next line stays in the edited block and is never pushed.  A long edit that
    wraps at the page margin stays on its line (shrunk, at most to 50 %) or is
    refused; it is never drawn over the next line."""
    pdf = tmp_path / "wrap_margin_lead.pdf"
    _same_block_pdf(pdf, neighbour=False, lead="Lead ")
    outcome, words, before = _neighbour_edit(pdf, _WRAP_LONG)
    assert not _overprinted(words, before, (_WRAP_SECOND, "Lead")), words
    if isinstance(outcome, EditTextResult):
        assert outcome is EditTextResult.SUCCESS, outcome
        drawn = " ".join(w for w, _r in words if w not in (_WRAP_SECOND, "Lead")).split()
        assert drawn == _WRAP_LONG.split()
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
        assert sorted(w for w, _r in words) == sorted(w for w, _r in before)


def test_rebuild_wrap_of_a_whole_first_line_pushes_the_rest_of_the_paragraph(
    tmp_path: Path,
) -> None:
    """GUARD: when the edited run IS the whole first line, erasing it leaves the
    rest of the paragraph a block of its own, so the push-down may move it
    straight down (same x and size); either way nothing is drawn over it."""
    pdf = tmp_path / "wrap_margin.pdf"
    _same_block_pdf(pdf, neighbour=False)
    outcome, words, before = _neighbour_edit(pdf, _WRAP_LONG)
    second, second_before = _word_rect(words, _WRAP_SECOND), _word_rect(before, _WRAP_SECOND)
    assert abs(second.x0 - second_before.x0) < 0.5 and abs(second.height - second_before.height) < 0.5
    assert second.y0 >= second_before.y0 - 0.5, "the paragraph's next line moved up"
    for word, r in words:
        if word != _WRAP_SECOND:
            common = r & second
            assert not (r.intersects(second) and common.height > 1.0 and common.width > 0.5), (
                f"{word!r} drawn over the next line"
            )
    if isinstance(outcome, EditTextResult):
        assert outcome is EditTextResult.SUCCESS, outcome
        drawn = " ".join(w for w, _r in words if w != _WRAP_SECOND).split()
        assert drawn == _WRAP_LONG.split()
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
        assert sorted(w for w, _r in words) == sorted(w for w, _r in before)


def test_rebuild_wrap_still_pushes_a_separate_block_below(tmp_path: Path) -> None:
    """GUARD: when the edited line is the last of its block the wrapped lines
    still get room -- the next BLOCK is pushed down, nothing is refused."""
    pdf = tmp_path / "wrap_push.pdf"
    _neighbour_pdf(pdf)
    outcome, words, before = _neighbour_edit(pdf, "ab cd ef")
    assert outcome is EditTextResult.SUCCESS, outcome
    assert [w for w, _r in words if w in {"ab", "cd", "ef"}] == ["ab", "cd", "ef"]
    below = _word_rect(words, "Below line")
    assert below.y0 > _word_rect(before, "Below line").y0, "the next block was not pushed"
    for word in ("ab", "cd", "ef"):
        assert not _word_rect(words, word).intersects(below)
        assert not _word_rect(words, word).intersects(_word_rect(words, "NEXT"))


def test_rebuild_refuses_a_wrap_over_a_block_the_push_down_cannot_move(tmp_path: Path) -> None:
    """Chokepoint guard: near the page foot the push-down skips a block that
    would leave the page; the wrapped text must not then be drawn over it."""
    pdf = tmp_path / "wrap_foot.pdf"
    _neighbour_pdf(pdf, y=780.0)
    outcome, words, before = _neighbour_edit(pdf, "ab cd ef gh ij kl mn")
    assert not _overprinted(words, before, ("Below line", "NEXT")), words
    if not isinstance(outcome, EditTextResult):
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome


# --- F14-DT-1: text already past the page's right safe margin keeps its line ---

_EDGE_PAGE_W = 595.0


def _edge_pdf(path: Path, x0: float, text: str, *, size: float, font: str,
              below: str | None = None) -> None:
    """``text`` (``font`` ``size``) starting at ``x0`` on a 595 pt page, and an
    optional untouched line 30 pt below it (its own block)."""
    doc = fitz.open()
    page = doc.new_page(width=_EDGE_PAGE_W, height=842)
    page.insert_text((x0, 100), text, fontsize=size, fontname=font)
    if below:
        page.insert_text((x0, 130), below, fontsize=size, fontname=font)
    doc.save(str(path), garbage=0)
    doc.close()


def _edge_edit(pdf: Path, old: str, new: str, engine: str, *, size: float, font: str):
    """Rebuild-edit ``old`` -> ``new``; returns ``(outcome, lines)`` where
    ``lines`` are ``(text, bbox)`` of the LIVE page's lines."""
    model = _open_model(pdf, engine=engine, max_tier=0)
    try:
        run = _run_with_text(model, old)
        try:
            outcome: object = model.edit_text(
                1, fitz.Rect(run.bbox), new, font=font, size=size,
                original_text=old, target_span_id=run.span_id, target_mode="run",
                allow_rebuild=True, confirm_fallback=_accept_rebuild,
            )
        except _RebuildRolledBack as exc:
            outcome = exc
        lines = [
            ("".join(s["text"] for s in ln["spans"]), fitz.Rect(ln["bbox"]))
            for b in model.doc[0].get_text("dict")["blocks"]
            for ln in b.get("lines", ())
        ]
        return outcome, lines
    finally:
        model.close()


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("new_text", ["機房配置圖", "平面配置圖二"])
def test_rebuild_keeps_a_title_past_the_safe_margin_on_one_line(
    tmp_path: Path, engine: str, new_text: str
) -> None:
    """F14-DT-1: a 60 pt CJK title at x 480-540 on a 595 pt page already reaches
    past the safe margin (535).  The rebuild's htmlbox was clamped to that
    margin -- narrower than the word itself -- so the title was re-wrapped onto
    two lines (and the lines below pushed down).  The edit stays on its line,
    and the untouched line below does not move."""
    pdf = tmp_path / "edge_cjk.pdf"
    _edge_pdf(pdf, 480.0, "平面配置圖", size=12.0, font="china-t", below="廠商名稱")
    outcome, lines = _edge_edit(pdf, "平面配置圖", new_text, engine, size=12.0, font="china-t")
    assert outcome is EditTextResult.SUCCESS, outcome
    band = [(t, bb) for t, bb in lines if bb.y0 < 106.0 and bb.y1 > 88.0]
    assert [t for t, _bb in band] == [new_text], f"edited word re-wrapped: {band!r}"
    assert band[0][1].x1 <= _EDGE_PAGE_W - 5, band
    below = [bb for t, bb in lines if t == "廠商名稱"]
    assert len(below) == 1 and abs(below[0].y0 - 119.0) < 6.0, ("untouched line moved", below)


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("new_text", ["13", "123"])
def test_rebuild_does_not_refuse_a_page_number_that_starts_in_the_right_margin(
    tmp_path: Path, engine: str, new_text: str
) -> None:
    """F14-DT-1: ``12`` at x 550 starts past the safe margin (535), so the
    clamped htmlbox was inverted/empty and the rebuild raised TEXT_DOES_NOT_FIT
    for an edit the lossless tiers commit in place.  It stays on one line."""
    pdf = tmp_path / "pageno.pdf"
    _edge_pdf(pdf, 550.0, "12", size=10.0, font="helv")
    outcome, lines = _edge_edit(pdf, "12", new_text, engine, size=10.0, font="helv")
    assert outcome is EditTextResult.SUCCESS, outcome
    band = [(t, bb) for t, bb in lines if bb.y0 < 106.0 and bb.y1 > 90.0]
    assert [t for t, _bb in band] == [new_text], band
    assert band[0][1].x1 <= _EDGE_PAGE_W - 5, band


def test_rebuild_still_keeps_the_safe_margin_for_a_line_that_ends_before_it(
    tmp_path: Path,
) -> None:
    """GUARD: the safe margin is unchanged for text that ends inside it -- an
    edit of ``ab`` at x 72 may not run into the right margin zone (x 535+)."""
    page_rect = fitz.Rect(0, 0, _EDGE_PAGE_W, 842)
    inside = fitz.Rect(72, 90, 120, 102)
    assert _right_wall(page_rect, 12.0, inside) == _EDGE_PAGE_W - 60.0
    assert _right_wall(page_rect, 100.0, inside) == _EDGE_PAGE_W - 120.0


def test_right_wall_for_text_that_already_reaches_past_the_safe_margin() -> None:
    """A single line past the margin may grow up to 10 pt short of the page
    edge (the bound the dragged box and strategy B already use); a multi-line
    extent (a paragraph) keeps at least its own old right edge; no extent
    falls back to the margin."""
    page_rect = fitz.Rect(0, 0, _EDGE_PAGE_W, 842)
    one_line = fitz.Rect(480, 90, 540, 102)
    assert _right_wall(page_rect, 12.0, one_line) == _EDGE_PAGE_W - 10.0
    paragraph = fitz.Rect(50, 90, 545, 130)
    assert _right_wall(page_rect, 12.0, paragraph) == 545.0
    assert _right_wall(page_rect, 12.0, fitz.Rect()) == _EDGE_PAGE_W - 60.0
    # already flush with the page edge: never beyond the page
    assert _right_wall(page_rect, 12.0, fitz.Rect(560, 90, 595, 102)) == _EDGE_PAGE_W


# --- F14-VM-2: the rebuild draws the edited text on its first-glyph origin ---

_VM2_ORIGIN_TOL = 0.1


def _vm2_pdf(path: Path, *, font: str, size: float, rotation: int = 0) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Alpha", fontsize=size, fontname=font)
    page.insert_text((72, 100 + 2 * size), "Bravo", fontsize=size, fontname=font)
    page.insert_text((72, 100 + 4 * size), "Charlie", fontsize=size, fontname=font)
    if rotation:
        page.set_rotation(rotation)
    doc.save(str(path), garbage=0)
    doc.close()


def _vm2_first_glyph(page: fitz.Page, needle: str) -> tuple[float, float, float]:
    """``(x, y, size)`` of the first character of the line holding ``needle``
    (its origin, in the page's unrotated space)."""
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", ()):
            text = "".join(c["c"] for span in line["spans"] for c in span["chars"])
            if needle in text:
                span = line["spans"][0]
                ch = span["chars"][0]
                return float(ch["origin"][0]), float(ch["origin"][1]), float(span["size"])
    raise AssertionError(f"{needle!r} not on the page")


def _vm2_edit(model: PDFModel, old: str, new_text: str, *, new_rect=None, engine_font="helv"):
    run = _run_with_text(model, old)
    return model.edit_text(
        1, fitz.Rect(run.bbox), new_text, font=engine_font, size=float(run.size),
        original_text=old, target_span_id=run.span_id, target_mode="run",
        new_rect=new_rect, allow_rebuild=True, confirm_fallback=_accept_rebuild,
    ), run


def _vm2_shifted_bbox(model: PDFModel, text: str, dx: float, dy: float) -> fitz.Rect:
    return fitz.Rect(_run_with_text(model, text).bbox) + (dx, dy, dx, dy)


@pytest.mark.parametrize("size", [8.0, 12.0, 48.0])
@pytest.mark.parametrize("font", ["helv", "tiro"])
def test_f14vm2_in_place_htmlbox_edit_keeps_the_first_glyph_origin(
    tmp_path: Path, font: str, size: float
) -> None:
    """The htmlbox drew the edited word by its rect's top-left: 1.0 pt right and
    a substitute-font line-box baseline shift (up to ~2.5 pt at 48 pt).  The
    first glyph of the rewritten run must sit on the original origin."""
    pdf = tmp_path / "vm2_inplace.pdf"
    _vm2_pdf(pdf, font=font, size=size)
    model = _open_model(pdf, engine="legacy")
    try:
        x0, y0, _ = _vm2_first_glyph(model.doc[0], "Bravo")
        # CJK text cannot go through insert_text: this is the htmlbox path.
        result, _run = _vm2_edit(model, "Bravo", "Bravo 世界", engine_font=font)
        assert result is EditTextResult.SUCCESS, result
        x1, y1, size1 = _vm2_first_glyph(model.doc[0], "Bravo")
        assert abs(size1 - size) <= 0.05
        assert abs(x1 - x0) <= _VM2_ORIGIN_TOL, (x0, x1)
        assert abs(y1 - y0) <= _VM2_ORIGIN_TOL, (y0, y1)
        # untouched neighbours stay put
        assert _vm2_first_glyph(model.doc[0], "Alpha")[:2] == pytest.approx((72.0, 100.0), abs=0.05)
    finally:
        model.close()


@pytest.mark.parametrize("size", [12.0, 48.0])
@pytest.mark.parametrize("font", ["helv", "tiro"])
def test_f14vm2_a_drag_moves_the_text_by_exactly_the_drag_and_back(
    tmp_path: Path, font: str, size: float
) -> None:
    """MM-3: a drag (``new_rect``) is a pure translation of the run: moving by
    (dx, dy) lands the first glyph on origin + (dx, dy), moving back returns
    it to where it started (it used to add +1.0 pt x and a baseline error per
    move, so the text never came home)."""
    pdf = tmp_path / "vm2_drag.pdf"
    _vm2_pdf(pdf, font=font, size=size)
    model = _open_model(pdf, engine="legacy")
    try:
        dx, dy = 50.0, 30.0
        x0, y0, _ = _vm2_first_glyph(model.doc[0], "Bravo")
        result, _run = _vm2_edit(
            model, "Bravo", "Bravo",
            new_rect=fitz.Rect(_vm2_shifted_bbox(model, "Bravo", dx, dy)), engine_font=font,
        )
        assert result is EditTextResult.SUCCESS, result
        x1, y1, _ = _vm2_first_glyph(model.doc[0], "Bravo")
        assert abs(x1 - (x0 + dx)) <= _VM2_ORIGIN_TOL, (x0 + dx, x1)
        assert abs(y1 - (y0 + dy)) <= _VM2_ORIGIN_TOL, (y0 + dy, y1)
        result2, _run2 = _vm2_edit(
            model, "Bravo", "Bravo",
            new_rect=fitz.Rect(_vm2_shifted_bbox(model, "Bravo", -dx, -dy)), engine_font=font,
        )
        assert result2 is EditTextResult.SUCCESS, result2
        x2, y2, size2 = _vm2_first_glyph(model.doc[0], "Bravo")
        assert abs(size2 - size) <= 0.05
        assert abs(x2 - x0) <= _VM2_ORIGIN_TOL, (x0, x2)
        assert abs(y2 - y0) <= _VM2_ORIGIN_TOL, (y0, y2)
    finally:
        model.close()


def _vm2_turned_pdf(path: Path, *, page_rotation: int, text_rotation: int) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((300, 400), "Bravo", fontsize=14, fontname="helv", rotate=text_rotation)
    page.insert_text((300, 600), "Other", fontsize=14, fontname="helv", rotate=text_rotation)
    if page_rotation:
        page.set_rotation(page_rotation)
    doc.save(str(path), garbage=0)
    doc.close()


@pytest.mark.parametrize("move", [False, True])
@pytest.mark.parametrize("text_rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("page_rotation", [0, 90, 270])
def test_f14vm2_quarter_turn_and_rotated_page_edits_keep_the_first_glyph_origin(
    tmp_path: Path, page_rotation: int, text_rotation: int, move: bool
) -> None:
    """Same law for text reading up/down and for pages with ``/Rotate``: the
    rewrite starts on the original origin, a drag translates it by exactly the
    drag (the displayed drag mapped into unrotated space)."""
    pdf = tmp_path / "vm2_turned.pdf"
    _vm2_turned_pdf(pdf, page_rotation=page_rotation, text_rotation=text_rotation)
    model = _open_model(pdf, engine="legacy")
    try:
        page = model.doc[0]
        x0, y0, _ = _vm2_first_glyph(page, "Bravo")
        run = _run_with_text(model, "Bravo")
        shown = fitz.Rect(run.bbox) * page.rotation_matrix
        new_rect = fitz.Rect(shown) + (40, 25, 40, 25) if move else None
        result = model.edit_text(
            1, shown, "Bravo" if move else "Bravo 世", font="helv", size=14.0,
            original_text="Bravo", target_span_id=run.span_id, target_mode="run",
            new_rect=new_rect, allow_rebuild=True, confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS, result
        want = fitz.Point(x0, y0)
        if move:
            zero = fitz.Point(0, 0) * page.derotation_matrix
            shift = fitz.Point(40, 25) * page.derotation_matrix - zero
            want = fitz.Point(x0 + shift.x, y0 + shift.y)
        x1, y1, _ = _vm2_first_glyph(model.doc[0], "Bravo")
        assert abs(x1 - want.x) <= _VM2_ORIGIN_TOL, (want, (x1, y1))
        assert abs(y1 - want.y) <= _VM2_ORIGIN_TOL, (want, (x1, y1))
        assert _vm2_first_glyph(model.doc[0], "Other")[:2] == pytest.approx((300.0, 600.0), abs=0.05)
    finally:
        model.close()


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_f15vm2_fast180_classifier_sends_every_turned_run_to_htmlbox(rotation: int) -> None:
    """F15-VM2-FAST180: ``insert_text(..., rotate=0)`` writes upright text that
    runs +x, which is right only for a run written along +x.  Every turned
    run (180 as well as the quarter turns) takes htmlbox, which follows the
    run's direction; only rotation 0 may take the fast path."""
    span = SimpleNamespace(bbox=fitz.Rect(40, 690, 140, 702))
    kwargs = dict(
        new_text="Bravo!",
        member_spans=[span],
        is_vertical=False,
        preserve_multi_style=False,
        has_new_rect=False,
        needs_cjk=False,
        text_width=40.0,
        available_width=400.0,
        size=11.0,
    )
    assert pdf_model_module._classify_insert_path(rotation=0, **kwargs) == "fast"
    assert pdf_model_module._classify_insert_path(rotation=rotation, **kwargs) == "htmlbox"


def _fast180_line_glyphs(page: fitz.Page, needle: str) -> tuple[tuple[float, float], list]:
    """``((dx, dy), [(char, x, y), ...])`` of the text-trace line holding
    ``needle`` (drawing order)."""
    for span in page.get_texttrace():
        text = "".join(chr(c[0]) for c in span["chars"])
        if needle in text:
            return (
                (float(span["dir"][0]), float(span["dir"][1])),
                [(chr(c[0]), float(c[2][0]), float(c[2][1])) for c in span["chars"]],
            )
    raise AssertionError(f"{needle!r} not on the page")


@pytest.mark.parametrize("new_text", ["Bravo!", "Bravo, Charlie", "Brav"])
@pytest.mark.parametrize("page_rotation", [0, 180])
def test_f15vm2_fast180_a_rebuilt_upside_down_run_stays_upside_down(
    tmp_path: Path, page_rotation: int, new_text: str
) -> None:
    """F15-VM2-FAST180: a consented rebuild of an upside-down (text rotation
    180) Latin-1 run took the single-line ``insert_text`` fast path with
    ``rotate=0``: the rewrite was drawn upright, its glyphs ran +x from the old
    origin (the run grew the other way) and the word flipped on screen.  The
    rewrite keeps the run's direction (-1, 0) and starts on the old origin,
    and the untouched run is not disturbed."""
    pdf = tmp_path / "fast180.pdf"
    _vm2_turned_pdf(pdf, page_rotation=page_rotation, text_rotation=180)
    model = _open_model(pdf, engine="legacy")
    try:
        page = model.doc[0]
        x0, y0, _ = _vm2_first_glyph(page, "Bravo")
        direction, _glyphs = _fast180_line_glyphs(page, "Bravo")
        assert direction == pytest.approx((-1.0, 0.0), abs=1e-3), direction
        run = _run_with_text(model, "Bravo")
        shown = fitz.Rect(run.bbox) * page.rotation_matrix
        result = model.edit_text(
            1, shown, new_text, font="helv", size=14.0,
            original_text="Bravo", target_span_id=run.span_id, target_mode="run",
            allow_rebuild=True, confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS, result
        direction, glyphs = _fast180_line_glyphs(model.doc[0], new_text.replace(" ", "")[:4])
        assert direction == pytest.approx((-1.0, 0.0), abs=1e-3), ("drawn upright", direction)
        xs = [x for ch, x, _y in glyphs if ch != " "]
        assert xs == sorted(xs, reverse=True), ("glyphs run +x", glyphs)
        assert abs(glyphs[0][1] - x0) <= _VM2_ORIGIN_TOL, (x0, glyphs[0])
        assert all(abs(y - y0) <= _VM2_ORIGIN_TOL for _ch, _x, y in glyphs), (y0, glyphs)
        assert _vm2_first_glyph(model.doc[0], "Other")[:2] == pytest.approx((300.0, 600.0), abs=0.05)
    finally:
        model.close()


# --- F16-2: an upside-down run grows into -x and stacks its extra lines up ---
#
# F15-VM2-FAST180 sent every 180-degree run to the htmlbox route, but that route
# still walled the edit at the next run to the RIGHT (+x), the side an upside-down
# run does not grow into, and gave the side it does grow into no wall at all.

_F162_SIZE = 14.0
_F162_BASE = (400.0, 400.0)  # origin of "Hello" (upside down: the word runs to -x)


def _f162_pdf(
    path: Path,
    *,
    page_rotation: int,
    hello: bool = True,
    world: bool = True,
    left_x1: float | None = None,
    above: bool = False,
    below: bool = False,
) -> None:
    """``Hello World`` written upside down (text rotate 180) on one baseline:
    ``Hello`` at larger x, ``World`` to its -x side (the reading order of the
    turned line).  Optional untouched upside-down runs: ``Left`` whose right
    edge is ``left_x1``, ``Above`` one line up the page, ``Below`` 30 pt down."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    helv = fitz.Font("helv")
    x, y = _F162_BASE

    def put(origin_x: float, origin_y: float, text: str) -> None:
        page.insert_text(
            (origin_x, origin_y), text, fontsize=_F162_SIZE, fontname="helv", rotate=180
        )

    if hello:
        put(x, y, "Hello")
    if world:
        put(x - helv.text_length("Hello ", fontsize=_F162_SIZE), y, "World")
    if left_x1 is not None:
        put(left_x1, y, "Left")
    if above:
        put(x, y - 16.0, "Above")
    if below:
        put(x, y + 30.0, "Below")
    if page_rotation:
        page.set_rotation(page_rotation)
    doc.save(str(path), garbage=0)
    doc.close()


def _f162_edit(model: PDFModel, old: str, new_text: str):
    run = _run_with_text(model, old)
    shown = fitz.Rect(run.bbox) * model.doc[0].rotation_matrix
    try:
        return model.edit_text(
            1, shown, new_text, font="helv", size=_F162_SIZE,
            original_text=old, target_span_id=run.span_id, target_mode="run",
            allow_rebuild=True, confirm_fallback=_accept_rebuild,
        )
    except _RebuildRolledBack as exc:
        return exc


def _f162_trace(page: fitz.Page, skip: tuple[str, ...]) -> list[tuple[str, float, tuple, list]]:
    """``(text, size, dir, [(x, y), ...])`` of every text-trace span whose text is
    not one of the ``skip`` untouched words."""
    out = []
    for span in page.get_texttrace():
        text = "".join(chr(c[0]) for c in span["chars"])
        if text.strip() in skip:
            continue
        out.append((
            text,
            float(span["size"]),
            (float(span["dir"][0]), float(span["dir"][1])),
            [(float(c[2][0]), float(c[2][1])) for c in span["chars"] if chr(c[0]) != " "],
        ))
    return out


@pytest.mark.parametrize("page_rotation", [0, 180])
def test_f16_2_upside_down_edit_grows_into_the_empty_side_at_full_size(
    tmp_path: Path, page_rotation: int
) -> None:
    """F16-2: ``World`` -> ``Worldwide wonders`` in an upside-down line.  The
    run grows toward -x, where nothing stands; ``Hello`` is on the +x side the
    run does not grow into.  The +x neighbour walled the box at ``Hello``'s left
    edge, so the text was shrunk to ~8 pt and wrapped; the upright twin keeps
    14 pt on one line."""
    pdf = tmp_path / "f162_world.pdf"
    _f162_pdf(pdf, page_rotation=page_rotation)
    model = _open_model(pdf, engine="legacy")
    try:
        hello_before = _vm2_first_glyph(model.doc[0], "Hello")
        result = _f162_edit(model, "World", "Worldwide wonders")
        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        drawn = _f162_trace(page, skip=("Hello",))
        assert drawn, "the edited text must be drawn"
        for text, size, direction, _glyphs in drawn:
            assert size == pytest.approx(_F162_SIZE, abs=0.05), (text, size)
            assert direction == pytest.approx((-1.0, 0.0), abs=1e-3), (text, direction)
        baselines = {round(y, 1) for _t, _s, _d, glyphs in drawn for _x, y in glyphs}
        assert len(baselines) == 1, ("wrapped onto several lines", baselines)
        assert _vm2_first_glyph(page, "Hello") == pytest.approx(hello_before, abs=0.05)
    finally:
        model.close()


@pytest.mark.parametrize("page_rotation", [0, 180])
def test_f16_2_upside_down_edit_wraps_away_from_the_neighbour_it_grows_toward(
    tmp_path: Path, page_rotation: int
) -> None:
    """F16-2: ``Hello`` -> ``Hello there`` grows toward ``World`` (its -x side).
    Nothing walled that side, so ``there`` was drawn over ``World`` and the
    overprint guard rolled the edit back, while the upright twin succeeds by
    wrapping.  The upside-down run wraps its extra line UP the page (the
    line-stacking direction of a turned run), at full size, clear of ``World``;
    the untouched runs, below included, stay where they are."""
    pdf = tmp_path / "f162_hello.pdf"
    _f162_pdf(pdf, page_rotation=page_rotation, below=True)
    model = _open_model(pdf, engine="legacy")
    try:
        before = _word_rects(model.doc[0])
        result = _f162_edit(model, "Hello", "Hello there")
        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        words = _word_rects(page)
        assert words["World"] == before["World"], "the untouched neighbour moved"
        assert words["Below"] == before["Below"], "the run below was pushed"
        for name in ("Hello", "there"):
            assert not words[name].intersects(words["World"]), (name, words)
        assert words["there"].y1 <= words["Hello"].y0 + 1.0, ("not wrapped up the page", words)
        for text, size, direction, _glyphs in _f162_trace(page, skip=("World", "Below")):
            assert size == pytest.approx(_F162_SIZE, abs=0.05), (text, size)
            assert direction == pytest.approx((-1.0, 0.0), abs=1e-3), (text, direction)
    finally:
        model.close()


def test_f16_2_upside_down_edit_is_refused_not_overprinted_when_no_line_is_free(
    tmp_path: Path,
) -> None:
    """GUARD (F16-2): ``Left`` ends 70 pt to the -x side of ``Hello`` and
    ``Above`` fills the line a wrap would use.  A long rewrite fits neither on
    one line (``Left`` walls it) nor on a second (``Above`` is there): it
    stays on its line, shrunk to at most half size, or is refused and rolled
    back -- never drawn over ``Left`` or ``Above``."""
    pdf = tmp_path / "f162_noroom.pdf"
    _f162_pdf(pdf, page_rotation=0, world=False, left_x1=330.0, above=True)
    model = _open_model(pdf, engine="legacy")
    try:
        before = _word_rects(model.doc[0])
        result = _f162_edit(model, "Hello", "Hello there wonders of all")
        words = _word_rects(model.doc[0])
        assert words["Left"] == before["Left"] and words["Above"] == before["Above"]
        if isinstance(result, _RebuildRolledBack):
            assert words["Hello"] == before["Hello"]
        else:
            assert result is EditTextResult.SUCCESS, result
            for name, rect in words.items():
                if name not in ("Left", "Above"):
                    assert not rect.intersects(words["Left"]), (name, words)
                    assert not rect.intersects(words["Above"]), (name, words)
            for _t, size, _d, _g in _f162_trace(model.doc[0], skip=("Left", "Above")):
                assert size >= _F162_SIZE * 0.5 - 0.05, size
    finally:
        model.close()


def _stub_runs(*specs: tuple[str, tuple[float, float, float, float], tuple[float, float]]):
    """Index-run stand-ins ``(span_id, bbox, dir_vec)`` for the neighbour-limit
    helpers."""
    return [
        SimpleNamespace(span_id=sid, text="x", bbox=bbox, dir_vec=dvec)
        for sid, bbox, dvec in specs
    ]


@pytest.mark.parametrize(
    ("grows_left", "extent", "runs", "expected"),
    [
        # grows +x: the nearest run to the right is the wall (its left edge)
        (False, (100, 100, 130, 114), [("n", (140, 100, 170, 114), (1, 0)),
                                       ("far", (300, 100, 330, 114), (1, 0))], 140.0),
        # grows -x: the nearest run to the LEFT is the wall (its right edge)
        (True, (100, 100, 130, 114), [("n", (50, 100, 90, 114), (-1, 0)),
                                      ("far", (10, 100, 20, 114), (-1, 0))], 90.0),
        # a run on the side the edit does not grow into is no wall
        (True, (100, 100, 130, 114), [("right", (140, 100, 170, 114), (-1, 0))], None),
        (False, (100, 100, 130, 114), [("left", (50, 100, 90, 114), (1, 0))], None),
        # on another line, the edited run itself, a diagonal run: no wall
        (True, (100, 100, 130, 114), [("line", (50, 130, 90, 144), (-1, 0)),
                                      ("self", (50, 100, 90, 114), (-1, 0)),
                                      ("diag", (50, 100, 90, 114), (0.7, 0.7))], None),
        # sticks out of the extent's far edge: the old far edge is the wall
        (True, (100, 100, 130, 114), [("ov", (90, 100, 120, 114), (-1, 0))], 100.0),
        (False, (100, 100, 130, 114), [("ov", (110, 100, 140, 114), (1, 0))], 130.0),
    ],
)
def test_f16_2_horizontal_neighbour_limit_follows_the_growth_direction(
    grows_left, extent, runs, expected
) -> None:
    from model.pdf_text_edit import _horizontal_neighbour_limit

    spans = [SimpleNamespace(bbox=extent)]
    model = SimpleNamespace(
        block_manager=SimpleNamespace(get_runs=lambda _p: _stub_runs(*runs))
    )
    got = _horizontal_neighbour_limit(model, 0, spans, {"self"}, grows_left=grows_left)
    assert got == expected


def test_f16_2_left_wall_mirrors_the_right_wall() -> None:
    """The safe margin an upside-down run grows toward is the page's LEFT
    margin; the same rules as ``_right_wall`` (F14-DT-1), mirrored."""
    from model.pdf_text_edit import _left_wall

    page_rect = fitz.Rect(0, 0, _EDGE_PAGE_W, 842)
    for size, extent in [
        (12.0, fitz.Rect(400, 90, 520, 102)),     # inside the margin
        (100.0, fitz.Rect(400, 90, 520, 102)),    # big type: wider margin
        (12.0, fitz.Rect(5, 90, 60, 102)),        # one line already in the margin
        (12.0, fitz.Rect(5, 90, 60, 140)),        # a paragraph in the margin
        (12.0, fitz.Rect()),                      # no extent
        (12.0, fitz.Rect(0, 90, 35, 102)),        # flush with the page edge
    ]:
        mirrored = fitz.Rect(
            _EDGE_PAGE_W - extent.x1, extent.y0, _EDGE_PAGE_W - extent.x0, extent.y1
        )
        want = _EDGE_PAGE_W - _right_wall(page_rect, size, mirrored)
        assert _left_wall(page_rect, size, extent) == pytest.approx(want), (size, extent)
    assert _left_wall(page_rect, 12.0, fitz.Rect(400, 90, 520, 102)) == 60.0


def test_f16_2_wrap_ceiling_is_the_nearest_untouched_line_above(tmp_path: Path) -> None:
    """The mirror of ``_wrap_floor``: an upside-down run stacks its extra lines
    UP the page, and nothing is pushed up out of the way, so every untouched run
    above the edited line in the box's columns bounds the wrap -- whichever
    block it belongs to."""
    from model.pdf_text_edit import _wrap_ceiling

    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 300), "far above", fontsize=14, fontname="helv")
        page.insert_text((100, 350), "near above", fontsize=14, fontname="helv")
        page.insert_text((400, 340), "other column", fontsize=14, fontname="helv")
        page.insert_text((100, 400), "the edited line", fontsize=14, fontname="helv")
        page.insert_text((100, 450), "below", fontsize=14, fontname="helv")
        pivot = fitz.Point(100.0, 380.0)
        page.insert_text(pivot, "DIAG", fontsize=40, fontname="helv",
                         morph=(pivot, fitz.Matrix(45)))
        near = _word_rects(page)["near"]
        extent = fitz.Rect(100, 390, 200, 405)
        ceiling = _wrap_ceiling(page, extent, 90.0, 250.0)
        assert ceiling == pytest.approx(near.y1, abs=0.5)
        assert _wrap_ceiling(page, extent, 500.0, 560.0) is None
    finally:
        doc.close()


def _direction_of(rotation: int) -> tuple[float, float]:
    """The unit direction a run with this ``rotation`` is written along
    (``rotation_degrees_from_dir`` inverted: 90 reads DOWN the page)."""
    return {0: (1.0, 0.0), 90: (0.0, 1.0), 180: (-1.0, 0.0), 270: (0.0, -1.0)}[rotation]


@pytest.mark.parametrize("text", ["Price 5", "Price €5"], ids=["insert_text", "htmlbox"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_f15vm2_fast180_a_replayed_neighbour_keeps_its_writing_direction(
    rotation: int, text: str
) -> None:
    """F15-VM2-FAST180, same class: the protected-neighbour replay handed the
    span's own rotation to ``insert_text`` / ``insert_htmlbox``, whose ``rotate``
    runs the other way for the quarter turns, so a neighbour reading up the
    page came back reading down (and the reverse).  Only 0 and 180 were
    right.  The replay keeps the direction the run was written in."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    model = PDFModel()
    try:
        span = _protected_span(text, 11.0, (290, 390, 330, 420), (300, 400), rotation)
        with font_compaction_scope(doc):
            model._replay_protected_spans(page, [span])
        spans = page.get_texttrace()
        assert spans, "the neighbour must be drawn"
        for traced in spans:
            assert tuple(traced["dir"]) == pytest.approx(_direction_of(rotation), abs=1e-3), (
                rotation,
                traced["dir"],
            )
        first = spans[0]["chars"][0][2]
        assert (first[0], first[1]) == pytest.approx((300.0, 400.0), abs=0.5)
    finally:
        model.close()
        doc.close()


def _push_down_turned_pdf(path: Path, *, origin: tuple[float, float], rotation: int) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Edited line", fontsize=12, fontname="helv")
    page.insert_text(origin, "Pushme", fontsize=12, fontname="helv", rotate=rotation)
    doc.save(str(path), garbage=0)
    doc.close()


@pytest.mark.parametrize(
    ("rotation", "origin"),
    [(0, (300, 130)), (90, (300, 180)), (180, (300, 130)), (270, (300, 130))],
)
def test_f15vm2_fast180_push_down_keeps_a_turned_block_turned(
    tmp_path: Path, rotation: int, origin: tuple[float, float]
) -> None:
    """F15-VM2-FAST180, same class: the push-down redrew every pushed span
    upright (no ``rotate``), so an upside-down or reading-down block below an
    edit was flipped to horizontal text when it was pushed down.  It moves down
    by the push, in the direction it was written, glyph for glyph."""
    pdf = tmp_path / "pd_turned.pdf"
    _push_down_turned_pdf(pdf, origin=origin, rotation=rotation)
    model = _open_model(pdf, engine="legacy")
    try:
        page = model.doc[0]
        (before,) = [t for t in page.get_texttrace() if t["chars"][0][0] == ord("P")]
        x0, y0 = before["chars"][0][2]
        # ``rotation`` is insert_text's own (counter-clockwise) turn here
        want_dir = _direction_of((360 - rotation) % 360)
        assert tuple(before["dir"]) == pytest.approx(want_dir, abs=1e-3)
        with font_compaction_scope(model.doc):
            model._push_down_overlapping_text(
                page, fitz.Rect(page.rect), above_y=105.0, new_bottom=160.0,
                edit_x0=60.0, edit_x1=500.0,
            )
        (after,) = [t for t in page.get_texttrace() if t["chars"][0][0] == ord("P")]
        assert "".join(chr(c[0]) for c in after["chars"]) == "Pushme"
        assert tuple(after["dir"]) == pytest.approx(want_dir, abs=1e-3), (rotation, after["dir"])
        x1, y1 = after["chars"][0][2]
        assert x1 == pytest.approx(x0, abs=0.5), (x0, x1)
        assert y1 > y0 + 5.0, ("not pushed down", y0, y1)
    finally:
        model.close()


def test_f15vm2_fast180_push_down_leaves_a_diagonal_block_where_it_is(tmp_path: Path) -> None:
    """A block written off the page axes cannot be redrawn by a quarter-turn
    htmlbox (it came back upright when pushed).  Like a vertical (WMode 1)
    block it stays where it is; the wrap floor already ignores it."""
    pdf = tmp_path / "pd_diag.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Edited line", fontsize=12, fontname="helv")
    page.insert_text(
        (300, 300), "Pushme", fontsize=12, fontname="helv",
        morph=(fitz.Point(300, 300), fitz.Matrix(-45)),
    )
    doc.save(str(pdf), garbage=0)
    doc.close()
    model = _open_model(pdf, engine="legacy")
    try:
        page = model.doc[0]
        (before,) = [t for t in page.get_texttrace() if t["chars"][0][0] == ord("P")]
        assert not _is_axis_aligned_dir(before["dir"])
        with font_compaction_scope(model.doc):
            model._push_down_overlapping_text(
                page, fitz.Rect(page.rect), above_y=105.0, new_bottom=400.0,
                edit_x0=60.0, edit_x1=500.0,
            )
        (after,) = [t for t in page.get_texttrace() if t["chars"][0][0] == ord("P")]
        assert tuple(after["dir"]) == pytest.approx(tuple(before["dir"]), abs=1e-3)
        assert tuple(after["chars"][0][2]) == pytest.approx(tuple(before["chars"][0][2]), abs=0.01)
    finally:
        model.close()


def _vm2_span(origin: tuple[float, float], rotation: int = 0):
    return _protected_span("x", 12.0, (0, 0, 10, 10), origin, rotation)


@pytest.mark.parametrize(
    ("rotation", "spans", "want"),
    [
        # one line: the run nearest the text start
        (0, [(130, 100), (72, 100)], (72, 100)),
        # a superscript (baseline 4 pt higher) is still the first line
        (0, [(72, 100), (80, 96), (90, 100), (72, 114)], (72, 100)),
        # a first line indented 20 pt: every line starts on the block's left edge
        (0, [(92, 100), (72, 114)], (72, 100)),
        # lines further than 0.6 em apart are other lines
        (0, [(72, 114), (72, 100)], (72, 100)),
        # reading down: first line at the right edge, text starts at the top
        (90, [(300, 400), (300, 300), (286, 350)], (300, 300)),
        # reading up: first line at the left edge, text starts at the bottom
        (270, [(300, 400), (300, 300), (314, 350)], (300, 400)),
        # upside down: first line at the bottom, text starts at the right
        (180, [(100, 100), (150, 100), (150, 86)], (150, 100)),
    ],
)
def test_f14vm2_start_glyph_origin_follows_the_writing_direction(rotation, spans, want) -> None:
    from model.pdf_text_edit import _start_glyph_origin

    got = _start_glyph_origin([_vm2_span(o, rotation) for o in spans], rotation, 12.0)
    assert got is not None
    assert (got.x, got.y) == pytest.approx(want, abs=0.01)


def test_f14vm2_start_glyph_origin_without_spans_is_none() -> None:
    from model.pdf_text_edit import _start_glyph_origin

    assert _start_glyph_origin([], 0, 12.0) is None


def test_f14vm2_align_htmlbox_rect_keeps_the_box_when_there_is_nothing_to_align() -> None:
    from model.pdf_text_edit import _align_htmlbox_rect

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    box = fitz.Rect(72, 90, 300, 120)
    try:
        # no origin: untouched
        assert _align_htmlbox_rect(
            page, box, "<p>x</p>", "", origin=None, rotate=0, scale_low=1
        ) == box
        # markup that cannot fit at scale_low=1 draws nothing: untouched
        too_small = fitz.Rect(72, 90, 80, 92)
        long_html = "<p>" + "word " * 40 + "</p>"
        assert _align_htmlbox_rect(
            page, too_small, long_html, "", origin=fitz.Point(72, 100), rotate=0, scale_low=1
        ) == too_small
        # a real markup: moved by the measured offset, same size
        moved = _align_htmlbox_rect(
            page, box, "<p>x</p>", "", origin=fitz.Point(72, 100), rotate=0, scale_low=1
        )
        assert moved.width == pytest.approx(box.width) and moved.height == pytest.approx(box.height)
        assert moved != box
    finally:
        doc.close()


# ── F13-VF-4b: quarter-turn rebuilds are bounded by the next run ────────────
_VQ_X = 150.0
_VQ_Y = 300.0


def _vq_pdf(path: Path, rotate: int, *, gap: float = 4.0, dx: float = 0.0) -> None:
    """``ab`` (Helvetica 14) and the untouched red run ``NEXT`` (10 pt, its own
    run) on one column, ``NEXT`` ``gap`` pt after ``ab`` along the reading
    direction and ``dx`` pt across it.  PyMuPDF ``rotate=90`` reads UP (the
    next run lies at smaller y), ``rotate=270`` reads DOWN."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    w = fitz.Font("helv").text_length("ab", fontsize=14)
    step = -(w + gap) if rotate == 90 else (w + gap)
    page.insert_text((_VQ_X, _VQ_Y), "ab", fontsize=14, fontname="helv", rotate=rotate)
    page.insert_text(
        (_VQ_X + dx, _VQ_Y + step), "NEXT", fontsize=10, fontname="helv",
        rotate=rotate, color=(1, 0, 0),
    )
    doc.save(str(path), garbage=0)
    doc.close()


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("rotate", [90, 270])
def test_f13vf4b_vertical_rebuild_never_overprints_next_run(
    tmp_path: Path, engine: str, rotate: int
) -> None:
    """A longer quarter-turn word is re-drawn at its old start and grows along
    the reading direction; the next run on the column stays put and the new
    text must not be drawn over it -- refused (page untouched) or clear of it,
    never SUCCESS with an overprint."""
    pdf = tmp_path / f"vq_{rotate}_{engine}.pdf"
    _vq_pdf(pdf, rotate)
    outcome, after, before = _neighbour_edit(pdf, "abcdefghijklmnop", engine)
    next_before = _word_rect(before, "NEXT")
    assert (_word_rect(before, "ab") & next_before).get_area() < 1.0  # fixture sanity
    if outcome is not EditTextResult.SUCCESS:
        assert sorted(t for t, _ in after) == sorted(t for t, _ in before), "refusal must roll back"
        return
    next_after = _word_rect(after, "NEXT")
    assert next_after == next_before, "the untouched neighbour must not move"
    edited = [r for t, r in after if t != "NEXT"]
    assert edited, "the edited text must be drawn"
    assert all((r & next_after).get_area() < 1.0 for r in edited), (
        f"rotate {rotate} {engine}: edited text {edited} overprints NEXT {next_after}"
    )


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("rotate", [90, 270])
def test_f13vf4b_vertical_rebuild_refuses_when_the_word_cannot_fit_before_next_run(
    tmp_path: Path, engine: str, rotate: int
) -> None:
    """With NEXT 4 pt after ``ab`` there is no room for 16 characters at any
    legible size: the consented rebuild is refused and rolled back."""
    pdf = tmp_path / f"vq_refuse_{rotate}_{engine}.pdf"
    _vq_pdf(pdf, rotate)
    outcome, after, before = _neighbour_edit(pdf, "abcdefghijklmnop", engine)
    assert outcome is not EditTextResult.SUCCESS, outcome
    assert sorted(t for t, _ in after) == sorted(t for t, _ in before)
    assert _word_rect(after, "ab") == _word_rect(before, "ab")


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("rotate", [90, 270])
def test_f13vf4b_vertical_rebuild_that_fits_before_next_run_still_succeeds(
    tmp_path: Path, engine: str, rotate: int
) -> None:
    """The cap must not break a growth that fits: with 60 pt before NEXT,
    ``abcd`` (about 31 pt) is written and clears it."""
    pdf = tmp_path / f"vq_fit_{rotate}_{engine}.pdf"
    _vq_pdf(pdf, rotate, gap=60.0)
    outcome, after, before = _neighbour_edit(pdf, "abcd", engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    next_after = _word_rect(after, "NEXT")
    assert next_after == _word_rect(before, "NEXT")
    edited = _word_rect(after, "abcd")
    assert (edited & next_after).get_area() < 1.0
    assert edited.get_area() > _word_rect(before, "ab").get_area()


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("rotate", [90, 270])
def test_f13vf4b_vertical_run_on_another_column_is_not_a_wall(
    tmp_path: Path, engine: str, rotate: int
) -> None:
    """A run along the same axis but on another column (30 pt across) shares no
    ink with the edit and must not cap it."""
    pdf = tmp_path / f"vq_col_{rotate}_{engine}.pdf"
    _vq_pdf(pdf, rotate, gap=4.0, dx=30.0)
    outcome, after, before = _neighbour_edit(pdf, "abcdefghijklmnop", engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    assert _word_rect(after, "NEXT") == _word_rect(before, "NEXT")
    assert _word_rect(after, "abcdefghijklmnop").get_area() > 3 * _word_rect(before, "ab").get_area()


@pytest.mark.parametrize(
    ("reads_up", "extent", "runs", "expected"),
    [
        # reads down: the nearest untouched run below on the column is the wall
        (False, (100, 100, 114, 130), [("n", (100, 140, 110, 170), (0, 1)),
                                       ("far", (100, 300, 110, 320), (0, 1))], 140.0),
        # reads up: the nearest one ABOVE is the wall (its lower edge)
        (True, (100, 100, 114, 130), [("n", (100, 60, 110, 90), (0, -1)),
                                      ("far", (100, 10, 110, 20), (0, -1))], 90.0),
        # behind the start, on another column, the edited run itself: no wall
        (False, (100, 100, 114, 130), [("behind", (100, 40, 110, 70), (0, 1)),
                                       ("col", (160, 140, 170, 170), (0, 1)),
                                       ("self", (100, 140, 110, 170), (0, 1))], None),
        # starts inside the extent but sticks out past its far edge: the old edge
        (False, (100, 100, 114, 130), [("ov", (100, 120, 110, 150), (0, 1))], 130.0),
        (True, (100, 100, 114, 130), [("ov", (100, 80, 110, 110), (0, -1))], 100.0),
        # a diagonal run's bbox is no wall
        (False, (100, 100, 114, 130), [("diag", (100, 140, 140, 180), (0.7, 0.7))], None),
    ],
)
def test_f13vf4b_vertical_neighbour_limit(reads_up, extent, runs, expected) -> None:
    from model.pdf_text_edit import _vertical_neighbour_limit

    spans = [SimpleNamespace(bbox=extent)]
    model = SimpleNamespace(
        block_manager=SimpleNamespace(get_runs=lambda _p: _stub_runs(*runs))
    )
    got = _vertical_neighbour_limit(model, 0, spans, {"self"}, reads_up=reads_up)
    assert got == expected


# ── F15-G2-ANNOT: annotation geometry on /Rotate pages with an offset box / UserUnit ──
# PyMuPDF's ``page.transformation_matrix`` drops the CropBox/MediaBox origin and
# ``/UserUnit`` once ``/Rotate != 0``, and ``Annot.rect`` drops ``/UserUnit`` on a
# rotated page.  The annotation snapshot and the annotation move must map the raw
# /Rect through ``PageVisualFrame.base`` instead.  Oracles: that frame (agrees with
# the rendered ink within a pixel), a real ``apply_redactions`` (a link is
# "overlapped" exactly when the redaction removes it) and a rendered red box.

_G2A_RECT = fitz.Rect(100, 150, 220, 250)
_G2A_GEOMETRIES = {
    "plain": ("[0 0 600 800]", None),
    "crop": ("[0 0 600 800]", "[30 40 500 700]"),
    "negmb": ("[-100 -200 500 600]", "[-70 -160 400 500]"),
}
_G2A_CASES = [
    pytest.param(rotate, uu, geometry, id=f"rot{rotate}-uu{uu}-{geometry}")
    for geometry in _G2A_GEOMETRIES
    for rotate in (0, 90, 180, 270)
    for uu in (None, 2)
]


def _g2a_open(rotate: int, uu: int | None, geometry: str) -> fitz.Document:
    mediabox, cropbox = _G2A_GEOMETRIES[geometry]
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    doc.xref_set_key(page.xref, "MediaBox", mediabox)
    if cropbox:
        doc.xref_set_key(page.xref, "CropBox", cropbox)
    if rotate:
        doc.xref_set_key(page.xref, "Rotate", str(rotate))
    if uu is not None:
        doc.xref_set_key(page.xref, "UserUnit", str(uu))
    doc.reload_page(page)
    return doc


def _g2a_raw_rect(doc: fitz.Document, xref: int) -> fitz.Rect:
    kind, value = doc.xref_get_key(xref, "Rect")
    assert kind == "array", kind
    return fitz.Rect([float(v) for v in value.strip()[1:-1].split()])


def _g2a_xref(page: fitz.Page, code: int) -> int:
    return next(int(item[0]) for item in page.annot_xrefs() if int(item[1]) == code)


def _g2a_link_page(rotate: int, uu: int | None, geometry: str) -> tuple[fitz.Document, int]:
    """A page whose only link covers ``_G2A_RECT`` in TRUE page space.

    The raw /Rect is written from the independent frame (``page_visual_frame``),
    not from PyMuPDF's ``insert_link`` mapping.
    """
    doc = _g2a_open(rotate, uu, geometry)
    page = doc[0]
    page.insert_link({"kind": fitz.LINK_URI, "from": _G2A_RECT, "uri": "https://example.invalid/"})
    link = _g2a_xref(page, fitz.PDF_ANNOT_LINK)
    raw = fitz.Rect(_G2A_RECT) * ~page_visual_frame(page).base
    doc.xref_set_key(link, "Rect", "[" + " ".join(f"{v:.4f}" for v in raw) + "]")
    data = doc.tobytes()
    doc.close()
    reopened = fitz.open("pdf", data)
    return reopened, _g2a_xref(reopened[0], fitz.PDF_ANNOT_LINK)


def _g2a_corner(rect: fitz.Rect) -> fitz.Rect:
    return fitz.Rect(rect.x0 + 1, rect.y0 + 1, rect.x0 + 5, rect.y0 + 5)


@pytest.mark.parametrize(("rotate", "uu", "geometry"), _G2A_CASES)
def test_link_under_a_redaction_is_saved_on_rotated_offset_pages(
    rotate: int, uu: int | None, geometry: str
) -> None:
    """Saved exactly when the redaction really removes the link (not a rect-vs-rect echo)."""
    tool = AnnotationTool(SimpleNamespace(doc=None))
    for redact_rect, removes in (
        (_g2a_corner(_G2A_RECT), True),
        (fitz.Rect(450, 700, 470, 720), False),
    ):
        doc, link = _g2a_link_page(rotate, uu, geometry)
        try:
            page = doc[0]
            saved = tool._save_overlapping_links(page, redact_rect)
            page.add_redact_annot(redact_rect)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            gone = link not in {int(item[0]) for item in page.annot_xrefs()}
            assert gone is removes
            assert [entry["xref"] for entry in saved] == ([link] if removes else [])
            if removes:
                assert fitz.Rect(saved[0]["rect"]).intersects(redact_rect)
        finally:
            doc.close()


@pytest.mark.parametrize(("rotate", "uu", "geometry"), _G2A_CASES)
def test_a_square_under_a_redaction_is_saved_with_its_page_space_rect(
    rotate: int, uu: int | None, geometry: str
) -> None:
    """``Annot.rect`` drops /UserUnit on a rotated page (y = -512 at /Rotate 90, UserUnit 2)."""
    doc = _g2a_open(rotate, uu, geometry)
    try:
        page = doc[0]
        square = page.add_rect_annot(_G2A_RECT)
        square.update()
        xref = square.xref
        want = _g2a_raw_rect(doc, xref) * page_visual_frame(page).base
        want.normalize()
        tool = AnnotationTool(SimpleNamespace(doc=None))
        saved = tool._save_overlapping_annots(page, _g2a_corner(_G2A_RECT))
        assert [entry["xref"] for entry in saved] == [xref]
        assert tuple(saved[0]["rect"]) == pytest.approx(tuple(want), abs=0.01)
        # The page-space box is the requested rect grown by the border inset only.
        assert fitz.Rect(saved[0]["rect"]).contains(_G2A_RECT)
        assert fitz.Rect(saved[0]["rect"]).width < _G2A_RECT.width + 6
        assert tool._save_overlapping_annots(page, fitz.Rect(450, 700, 470, 720)) == []
    finally:
        doc.close()


@pytest.mark.parametrize(("rotate", "uu", "geometry"), _G2A_CASES)
def test_a_highlight_under_a_redaction_is_saved_with_page_space_vertices(
    rotate: int, uu: int | None, geometry: str
) -> None:
    """``Annot.vertices`` drops /UserUnit like ``Annot.rect``; the re-create reads these points."""
    doc = _g2a_open(rotate, uu, geometry)
    try:
        page = doc[0]
        highlight = page.add_highlight_annot(fitz.Rect(100, 150, 220, 170))
        highlight.update()
        kind, value = doc.xref_get_key(highlight.xref, "QuadPoints")
        assert kind == "array"
        numbers = [float(v) for v in value.strip()[1:-1].split()]
        base = page_visual_frame(page).base
        want = [tuple(fitz.Point(numbers[i], numbers[i + 1]) * base) for i in range(0, len(numbers), 2)]
        saved = AnnotationTool(SimpleNamespace(doc=None))._save_overlapping_annots(page, _g2a_corner(_G2A_RECT))
        assert [entry["xref"] for entry in saved] == [highlight.xref]
        got = [tuple(point) for point in saved[0]["vertices"]]
        assert got == pytest.approx(want, abs=0.01)
        assert min(y for _x, y in got) == pytest.approx(150.0, abs=0.5)
    finally:
        doc.close()


def _g2a_ink_box(page: fitz.Page) -> tuple[int, int, int, int]:
    pix = page.get_pixmap(alpha=False)
    width, height, stride, samples = pix.width, pix.height, pix.stride, pix.samples
    x0 = y0 = 10**9
    x1 = y1 = -1
    for y in range(height):
        row = samples[y * stride : y * stride + width * 3]
        for x in range(width):
            i = 3 * x
            if row[i] > 200 and row[i + 1] < 60 and row[i + 2] < 60:
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    assert x1 >= 0, "no red ink rendered"
    return (x0, y0, x1 + 1, y1 + 1)


@pytest.mark.parametrize(("rotate", "uu", "geometry"), _G2A_CASES)
def test_translate_annot_moves_the_rendered_ink_by_the_requested_page_vector(
    rotate: int, uu: int | None, geometry: str
) -> None:
    """The (dx, dy) is a TRUE-page-space vector; the ink turns with /Rotate and scales with UserUnit."""
    dx, dy = 20.0, 10.0
    doc = _g2a_open(rotate, uu, geometry)
    try:
        page = doc[0]
        square = page.add_rect_annot(_G2A_RECT)
        square.set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
        square.update()
        xref = square.xref
        frame = page_visual_frame(page)
        before = _g2a_ink_box(page)
        AnnotationTool(SimpleNamespace(doc=None))._translate_annot(page, xref, dx, dy)
        data = doc.tobytes()
    finally:
        doc.close()
    moved = fitz.open("pdf", data)
    try:
        after = _g2a_ink_box(moved[0])
    finally:
        moved.close()
    quarter = frame.quarter_turn
    expected = (quarter.a * dx + quarter.c * dy, quarter.b * dx + quarter.d * dy)
    assert (after[0] - before[0], after[1] - before[1]) == pytest.approx(expected, abs=1.0)


def test_annotation_geometry_falls_back_when_the_page_frame_cannot_be_proven() -> None:
    """A non-quarter /Rotate has no provable frame: no exception, MuPDF's own matrix is used."""
    doc = _g2a_open(0, None, "plain")
    try:
        page = doc[0]
        page.insert_link({"kind": fitz.LINK_URI, "from": _G2A_RECT, "uri": "https://example.invalid/"})
        link = _g2a_xref(page, fitz.PDF_ANNOT_LINK)
        doc.xref_set_key(page.xref, "Rotate", "45")
        doc.reload_page(page)
        page = doc[0]
        tool = AnnotationTool(SimpleNamespace(doc=None))
        saved = tool._save_overlapping_links(page, fitz.Rect(0, 0, 600, 800))
        assert [entry["xref"] for entry in saved] == [link]
        before = _g2a_raw_rect(doc, link)
        tool._translate_annot(page, link, 5.0, 7.0)
        after = _g2a_raw_rect(doc, link)
        legacy = fitz.Point(5.0, 7.0) * ~page.transformation_matrix - fitz.Point(0, 0) * ~page.transformation_matrix
        assert (after.x0 - before.x0, after.y0 - before.y0) == pytest.approx((legacy.x, legacy.y), abs=0.01)
    finally:
        doc.close()


# ── S17-DRAG-GUARD (TODOS F13-VF-4c): a dragged box is guarded, never capped ──
# Owner decision: a user-dragged ``new_rect`` skips the neighbour cap and the
# wrap floor (the user's placement wins on size) but keeps the overprint guard.
# A refused drop raises ``DRAGGED_BOX_OVERPRINTS`` and the Controller offers
# "place anyway" for that one edit (``place_anyway=True``: neither cap nor guard).
_DG_X = 72.0
_DG_Y = 700.0


def _dg_pdf(path: Path) -> None:
    """``ab`` (Helvetica 14) with the untouched red run ``NEXT`` (10 pt) right
    after it on the same line."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    next_x = _DG_X + fitz.Font("helv").text_length("ab", fontsize=14)
    page.insert_text((_DG_X, _DG_Y), "ab", fontsize=14, fontname="helv")
    page.insert_text((next_x, _DG_Y), "NEXT", fontsize=10, fontname="helv", color=(1, 0, 0))
    doc.save(str(path), garbage=0)
    doc.close()


def _dg_drag(pdf: Path, new_text: str, engine: str, *, dx: float, dy: float = 0.0, **kwargs):
    """Consented rebuild of ``ab`` dragged by ``(dx, dy)``; returns
    ``(outcome_or_exception, spans_after, spans_before)``."""
    model = _open_model(pdf, engine=engine)
    try:
        run = _run_with_text(model, "ab")
        drop = fitz.Rect(run.bbox) + (dx, dy, dx, dy)
        try:
            outcome: object = model.edit_text(
                1, fitz.Rect(run.bbox), new_text, font="helv", size=14.0,
                original_text="ab", target_span_id=run.span_id, target_mode="run",
                new_rect=drop, allow_rebuild=True, confirm_fallback=_accept_rebuild,
                **kwargs,
            )
        except RuntimeError as exc:
            outcome = exc
        saved = pdf.with_name(pdf.stem + "_saved.pdf")
        model.save_as(str(saved))
    finally:
        model.close()
    after, before = fitz.open(str(saved)), fitz.open(str(pdf))
    try:
        return outcome, _text_spans(after[0]), _text_spans(before[0])
    finally:
        after.close()
        before.close()


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("new_text", ["ab", "abc"])
def test_s17_dragged_box_onto_untouched_text_is_refused_and_rolled_back(
    tmp_path: Path, engine: str, new_text: str
) -> None:
    """A drop that lands on the untouched ``NEXT`` run is never SUCCESS: the
    overprint guard refuses it with its own code (so the Controller can offer
    "place anyway") and the page is exactly as it was."""
    pdf = tmp_path / f"dg_refuse_{engine}_{len(new_text)}.pdf"
    _dg_pdf(pdf)
    outcome, after, before = _dg_drag(pdf, new_text, engine, dx=20.0)
    assert isinstance(outcome, RuntimeError), f"dragged edit printed over NEXT: {outcome!r}"
    assert getattr(getattr(outcome, "reason", None), "value", None) == "dragged_box_overprints"
    assert sorted(t for t, _ in after) == sorted(t for t, _ in before), "refusal must roll back"
    assert _word_rect(after, "ab") == _word_rect(before, "ab")
    assert _word_rect(after, "NEXT") == _word_rect(before, "NEXT")


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_s17_dragged_box_in_free_space_still_succeeds_uncapped(
    tmp_path: Path, engine: str
) -> None:
    """The guard must not refuse a legitimate drag: dropped on empty page space
    the (longer) text is written at the drop, at full size, not capped by the
    untouched ``NEXT`` run that sits on the line it came from."""
    pdf = tmp_path / f"dg_free_{engine}.pdf"
    _dg_pdf(pdf)
    outcome, after, before = _dg_drag(pdf, "abcdefghijklmnopqrstuvwxyz", engine, dx=0.0, dy=-300.0)
    assert outcome is EditTextResult.SUCCESS, outcome
    assert _word_rect(after, "NEXT") == _word_rect(before, "NEXT")
    moved = _word_rect(after, "abcdefghijklmnopqrstuvwxyz")
    assert moved.y1 < _word_rect(before, "ab").y0 - 200.0, "the text must be at the drop"
    full = fitz.Font("helv").text_length("abcdefghijklmnopqrstuvwxyz", fontsize=14.0)
    assert moved.width > 0.9 * full, "a dragged box is not shrunk to a neighbour cap"


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_s17_place_anyway_writes_the_drop_over_the_neighbour(
    tmp_path: Path, engine: str
) -> None:
    """The per-edit choice: ``place_anyway=True`` applies neither cap nor guard,
    so the drop commits where the user put it and the neighbour stays put."""
    pdf = tmp_path / f"dg_anyway_{engine}.pdf"
    _dg_pdf(pdf)
    outcome, after, before = _dg_drag(pdf, "abc", engine, dx=20.0, place_anyway=True)
    assert outcome is EditTextResult.SUCCESS, outcome
    next_after = _word_rect(after, "NEXT")
    assert next_after == _word_rect(before, "NEXT")
    edited = _word_rect(after, "abc")
    assert (edited & next_after).get_area() > 20.0, "the user asked for this overlap"
    assert edited.x0 == pytest.approx(_word_rect(before, "ab").x0 + 20.0, abs=1.0)


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_s17_place_anyway_does_not_lift_the_guard_of_an_in_place_edit(
    tmp_path: Path, engine: str
) -> None:
    """``place_anyway`` is about a dragged box only: an edit that stays on its
    line keeps its neighbour cap and guard whatever the flag says."""
    pdf = tmp_path / f"dg_inplace_{engine}.pdf"
    _dg_pdf(pdf)
    plain = _dg_drag_free_inplace(pdf, engine, place_anyway=False)
    flagged = _dg_drag_free_inplace(pdf, engine, place_anyway=True)
    assert type(flagged) is type(plain)
    assert getattr(flagged, "reason", None) == getattr(plain, "reason", None)
    if not isinstance(plain, RuntimeError):
        assert flagged == plain


def _dg_drag_free_inplace(pdf: Path, engine: str, *, place_anyway: bool):
    model = _open_model(pdf, engine=engine)
    try:
        run = _run_with_text(model, "ab")
        try:
            return model.edit_text(
                1, fitz.Rect(run.bbox), "abcdefghijklmnopqrstuvwxyz", font="helv", size=14.0,
                original_text="ab", target_span_id=run.span_id, target_mode="run",
                allow_rebuild=True, confirm_fallback=_accept_rebuild,
                place_anyway=place_anyway,
            )
        except RuntimeError as exc:
            return exc
    finally:
        model.close()


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
def test_s17_a_sub_tolerance_drag_keeps_the_in_place_cluster_domain(
    tmp_path: Path, engine: str
) -> None:
    """A drop that did not really move the text (0.2 pt) still sits where the
    source was, so the neighbour that touched it in the source is not a new
    overprint: it is judged like an in-place edit, never as a dragged box."""
    pdf = tmp_path / f"dg_nudge_{engine}.pdf"
    _dg_pdf(pdf)
    outcome, _after, _before = _dg_drag(pdf, "abc", engine, dx=0.2)
    assert getattr(getattr(outcome, "reason", None), "value", None) != "dragged_box_overprints", outcome


@pytest.mark.parametrize("engine", ["legacy", "tiered"])
@pytest.mark.parametrize("rotate", [90, 270])
def test_s17_dragged_quarter_turn_box_onto_untouched_text_is_refused(
    tmp_path: Path, engine: str, rotate: int
) -> None:
    """The vertical rebuild is guarded for a dragged box too: dropped onto the
    next run of its column it is refused and rolled back."""
    pdf = tmp_path / f"dg_vert_{rotate}_{engine}.pdf"
    _vq_pdf(pdf, rotate)
    step = -20.0 if rotate == 90 else 20.0  # along the reading direction
    model = _open_model(pdf, engine=engine)
    try:
        run = _run_with_text(model, "ab")
        drop = fitz.Rect(run.bbox) + (0.0, step, 0.0, step)

        def place(**kwargs):
            return model.edit_text(
                1, fitz.Rect(run.bbox), "abc", font="helv", size=14.0,
                original_text="ab", target_span_id=run.span_id, target_mode="run",
                new_rect=drop, allow_rebuild=True, confirm_fallback=_accept_rebuild,
                **kwargs,
            )

        with pytest.raises(RuntimeError) as caught:
            place()
        assert getattr(caught.value.reason, "value", None) == "dragged_box_overprints"
        assert place(place_anyway=True) is EditTextResult.SUCCESS
    finally:
        model.close()
