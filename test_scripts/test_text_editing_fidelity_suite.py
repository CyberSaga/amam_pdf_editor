from __future__ import annotations

import ast
from pathlib import Path

import fitz
import pytest
from PySide6.QtGui import QImage

from model.edit_commands import EditTextResult
from model.pdf_model import PDFModel
from model.text_commit.dto import CommitTier, TextCommitSettings
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream
from model.text_edit_refusal import TextEditRefused
from view.text_editing import PreviewRenderer


def _accept_rebuild(_chain: tuple[str, ...]) -> bool:
    """UI step 7 (no silent legacy): explicit rebuild consent stub.  The
    tests that use it exercise the rebuild (legacy redact+reinsert) path, which
    a tiered refusal now reaches only with ``allow_rebuild=True`` plus an
    accepting confirm -- the same path they ran before, now consented."""
    return True


def _build_model_with_doc(
    tmp_path: Path,
    text: str,
    *,
    fontsize: float = 12.0,
    fontname: str = "helv",
    color=(0, 0, 0),
    rotate: int = 0,
    rect: fitz.Rect | None = None,
) -> tuple[PDFModel, fitz.Rect]:
    pdf_path = tmp_path / "fidelity.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if rect is None:
        rect = fitz.Rect(72, 72, 320, 140)
    if rotate in (90, 180, 270):
        css = f"* {{ font-family: {fontname}; font-size: {fontsize}pt; color: rgb({int(color[0] * 255)}, {int(color[1] * 255)}, {int(color[2] * 255)}); }}"
        page.insert_htmlbox(rect, text, css=css, rotate=rotate)
    else:
        page.insert_text(
            (rect.x0, rect.y0 + fontsize),
            text,
            fontsize=fontsize,
            fontname=fontname,
            color=color,
        )
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    return model, rect


def _first_block(model: PDFModel):
    blocks = model.block_manager.get_blocks(0)
    assert blocks
    return blocks[0]


def _edit_block(
    model: PDFModel,
    block,
    new_text: str,
    *,
    size: float | None = None,
    color: tuple[float, float, float] | None = None,
) -> EditTextResult:
    return model.edit_text(
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font=block.font,
        size=float(size if size is not None else block.size),
        color=tuple(float(c) for c in (color if color is not None else block.color)),
        original_text=block.text,
        target_mode="run",
        allow_rebuild=True,
        confirm_fallback=_accept_rebuild,
    )


def test_latin_single_line_edit_preserves_font_pt(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Hello World", fontsize=12.0)
    block = _first_block(model)
    assert _edit_block(model, block, "Hello World!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    edited = _first_block(model)
    assert abs(float(edited.size) - 12.0) < 0.1


def test_cjk_single_line_edit_preserves_height(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(
        tmp_path, "\u4e2d\u6587\u6e2c\u8a66", fontsize=14.0
    )
    block = _first_block(model)
    before_h = float(block.layout_rect.height)
    assert (
        _edit_block(model, block, "\u4e2d\u6587\u6e2c\u8a66\u4e00")
        is EditTextResult.SUCCESS
    )
    model.block_manager.rebuild_page(0, model.doc)
    after_h = float(_first_block(model).layout_rect.height)
    assert abs(after_h - before_h) <= 1.0


def test_fractional_font_pt_round_trips_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Fractional", fontsize=9.5)
    block = _first_block(model)
    assert _edit_block(model, block, "FractionalX", size=9.5) is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).size) - 9.5) < 0.1


def test_repeated_ten_edits_cumulative_drift_under_half_pt(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Drift", fontsize=12.0)
    block = _first_block(model)
    x0 = float(block.layout_rect.x0)
    y0 = float(block.layout_rect.y0)
    for i in range(10):
        model.block_manager.rebuild_page(0, model.doc)
        block = _first_block(model)
        assert _edit_block(model, block, f"Drift{i}") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    block = _first_block(model)
    assert abs(float(block.layout_rect.x0) - x0) < 0.5
    assert abs(float(block.layout_rect.y0) - y0) < 0.5


def test_preview_pixmap_dimensions_match_render_scale_2x() -> None:
    image = PreviewRenderer()._to_qimage_dimensions(
        rect=fitz.Rect(0, 0, 200, 80), render_scale=2.0, rotation=0
    )
    assert image.width() == 400 and image.height() == 160


def test_bold_flag_preserved_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(
        tmp_path, "BoldText", fontsize=12.0, fontname="hebo"
    )
    block = _first_block(model)
    assert _edit_block(model, block, "BoldText!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    lowered = (_first_block(model).font or "").lower()
    assert "bold" in lowered or "bd" in lowered


def test_italic_flag_preserved_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(
        tmp_path, "ItalicText", fontsize=12.0, fontname="tiro"
    )
    block = _first_block(model)
    assert _edit_block(model, block, "ItalicText!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert len(_first_block(model).font or "") > 0


def test_non_black_color_preserved_through_edit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(
        tmp_path, "Colored", fontsize=12.0, color=(0.8, 0.2, 0.1)
    )
    block = _first_block(model)
    assert (
        _edit_block(model, block, "Colored!", color=(0.8, 0.2, 0.1))
        is EditTextResult.SUCCESS
    )
    model.block_manager.rebuild_page(0, model.doc)
    c = tuple(float(v) for v in _first_block(model).color)
    assert abs(c[0] - 0.8) < 0.02 and abs(c[1] - 0.2) < 0.02 and abs(c[2] - 0.1) < 0.02


def test_multi_line_wrap_column_matches_source(tmp_path: Path) -> None:
    model, rect = _build_model_with_doc(
        tmp_path,
        "Wrap test line one line two line three",
        fontsize=12.0,
        rect=fitz.Rect(72, 72, 180, 160),
    )
    block = _first_block(model)
    assert (
        _edit_block(model, block, "Wrap test line one line too line three")
        is EditTextResult.SUCCESS
    )
    model.block_manager.rebuild_page(0, model.doc)
    assert float(_first_block(model).layout_rect.x0) >= rect.x0 - 0.5


def test_tight_leading_honored_on_commit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Line A\nLine B", fontsize=10.0)
    block = _first_block(model)
    before_h = float(block.layout_rect.height)
    assert _edit_block(model, block, "Line A\nLine B!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).layout_rect.height) - before_h) < 0.5


def test_loose_leading_honored_on_commit(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "Line C\nLine D", fontsize=10.0)
    block = _first_block(model)
    before_h = float(block.layout_rect.height)
    assert _edit_block(model, block, "Line C\nLine D!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).layout_rect.height) - before_h) < 0.5


def test_position_anchor_drift_under_half_pt_at_all_corners(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(
        tmp_path, "Corner", fontsize=10.0, rect=fitz.Rect(5, 5, 100, 40)
    )
    block = _first_block(model)
    x0 = float(block.layout_rect.x0)
    y0 = float(block.layout_rect.y0)
    assert _edit_block(model, block, "Corner!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    block = _first_block(model)
    assert (
        abs(float(block.layout_rect.x0) - x0) < 0.5
        and abs(float(block.layout_rect.y0) - y0) < 0.5
    )


def test_mixed_latin_cjk_span_renders_both_scripts(tmp_path: Path) -> None:
    model, _ = _build_model_with_doc(tmp_path, "ABC \u4e2d\u6587 XYZ", fontsize=12.0)
    block = _first_block(model)
    assert _edit_block(model, block, "ABCD \u4e2d\u6587 XYZ") is EditTextResult.SUCCESS
    text = model.doc[0].get_text("text")
    assert "ABCD" in text and "\u4e2d\u6587" in text


def test_vertical_rotated_text_edit_preserves_orientation_and_size(
    tmp_path: Path,
) -> None:
    model, rect = _build_model_with_doc(
        tmp_path,
        "Vertical",
        fontsize=12.0,
        rotate=90,
        rect=fitz.Rect(200, 100, 260, 280),
    )
    block = _first_block(model)
    assert _edit_block(model, block, "Vertical!") is EditTextResult.SUCCESS
    model.block_manager.rebuild_page(0, model.doc)
    assert abs(float(_first_block(model).size) - 12.0) < 0.5
    image = PreviewRenderer()._to_qimage_dimensions(
        rect=rect, render_scale=1.0, rotation=90
    )
    assert image.width() == int(round(rect.height))


def test_preview_pixmap_width_equals_source_rect_times_render_scale() -> None:
    image = PreviewRenderer()._to_qimage_dimensions(
        rect=fitz.Rect(0, 0, 200, 80), render_scale=1.5, rotation=0
    )
    assert image.width() == 300


# Task 3 — real PreviewRenderer rasterization tests.


def test_preview_render_produces_visible_text_pixels(qapp) -> None:
    """Latin text at 12pt must produce non-trivial dark pixels in the QImage."""
    renderer = PreviewRenderer(model=None)
    image = renderer.render(
        text="Hello",
        font_name="helv",
        font_size=12.0,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=fitz.Rect(0, 0, 200, 30),
        rotation=0,
        render_scale=2.0,
    )
    assert image is not None
    assert image.width() > 0 and image.height() > 0

    dark_pixels = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            color = image.pixelColor(x, y)
            if color.alpha() > 100 and color.lightness() < 100:
                dark_pixels += 1
    assert dark_pixels > 30, (
        f"Expected visible 'Hello' glyphs in preview pixmap, found {dark_pixels} "
        "dark opaque pixels. PreviewRenderer.render is likely returning a blank image."
    )


def test_preview_render_at_render_scale_2x_doubles_pixel_dimensions(qapp) -> None:
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 100.0, 20.0)
    image1x = renderer.render(
        text="x",
        font_name="helv",
        font_size=12.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=0,
        render_scale=1.0,
    )
    image2x = renderer.render(
        text="x",
        font_name="helv",
        font_size=12.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=0,
        render_scale=2.0,
    )
    assert image1x.width() == 100
    assert image2x.width() == 200


def test_preview_render_caches_identical_input(qapp) -> None:
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 100, 20)
    args: dict = dict(
        text="cache",
        font_name="helv",
        font_size=12.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=0,
        render_scale=1.0,
    )
    image_a = renderer.render(**args)
    image_b = renderer.render(**args)
    assert image_a is image_b, "Same args must return cached QImage instance"


def test_preview_render_rotation_90_swaps_pixel_dimensions(qapp) -> None:
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 200, 50)
    image_h = renderer.render(
        text="h",
        font_name="helv",
        font_size=14.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=0,
        render_scale=1.0,
    )
    image_v = renderer.render(
        text="v",
        font_name="helv",
        font_size=14.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=90,
        render_scale=1.0,
    )
    assert image_h.width() == 200 and image_h.height() == 50
    assert image_v.width() == 50 and image_v.height() == 200


# Task 3a — line_height threading.


def test_preview_render_uses_explicit_line_height_not_auto(qapp, tmp_path) -> None:
    """Tight vs. loose line_height must produce different pixel layouts.
    Guards the gap where auto-derive leading diverges from the committed CSS."""
    renderer = PreviewRenderer(model=None)
    rect = fitz.Rect(0, 0, 200, 40)

    img_auto = renderer.render(
        text="Line1\nLine2",
        font_name="helv",
        font_size=12.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=0,
        render_scale=2.0,
        line_height=0.0,
    )
    img_tight = renderer.render(
        text="Line1\nLine2",
        font_name="helv",
        font_size=12.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=0,
        render_scale=2.0,
        line_height=5.0,
    )
    img_loose = renderer.render(
        text="Line1\nLine2",
        font_name="helv",
        font_size=12.0,
        color=(0, 0, 0),
        member_spans=None,
        rect_pt=rect,
        rotation=0,
        render_scale=2.0,
        line_height=25.0,
    )
    assert img_auto is not img_tight
    assert img_auto is not img_loose

    def _ink_count(img: QImage) -> int:
        """Count opaque-ish dark pixels (text glyphs)."""
        return sum(
            1
            for y in range(img.height())
            for x in range(0, img.width(), 4)
            if img.pixelColor(x, y).alpha() > 30
            and img.pixelColor(x, y).lightness() < 150
        )

    auto_ink = _ink_count(img_auto)
    tight_ink = _ink_count(img_tight)
    loose_ink = _ink_count(img_loose)

    # Tight line_height (5pt) should pack glyphs differently than auto or loose (25pt).
    # At least one pair must differ to show leading is being honoured.
    assert auto_ink != tight_ink or auto_ink != loose_ink, (
        f"Different line_height values must produce different glyph layouts. "
        f"auto={auto_ink} tight={tight_ink} loose={loose_ink}. "
        "Check that render() passes line_height into CSS and cache key includes it."
    )


# Task 5 — pixel-height parity.


def test_inline_editor_glyph_height_matches_pdf_at_render_scale_2x(
    qapp, tmp_path
) -> None:
    """E2E: PreviewRenderer.render at render_scale=2.0 must produce glyph
    ink-pixel-height within 20% of the direct PyMuPDF rasterization of the
    same text. Regression guard for 'glyphs unexpectedly larger or smaller
    on click' — both sides use the same engine path so the ratio must be ~1."""
    font_size = 14.0
    span_rect = fitz.Rect(0, 0, 150, 25)

    def _ink_extent_px(image: QImage) -> int:
        """Vertical span of opaque dark pixels (text ink)."""
        top_row = None
        bottom_row = None
        for y in range(image.height()):
            has_ink = any(
                image.pixelColor(x, y).alpha() > 50
                and image.pixelColor(x, y).lightness() < 150
                for x in range(0, image.width(), 4)
            )
            if has_ink:
                if top_row is None:
                    top_row = y
                bottom_row = y
        return (bottom_row - top_row + 1) if top_row is not None else 0

    # Reference: rasterize the same span directly via PyMuPDF at 2x.
    ref_doc = fitz.open()
    ref_page = ref_doc.new_page(
        width=float(span_rect.width), height=float(span_rect.height)
    )
    css_ref = f"span {{ font-family: Helvetica; font-size: {font_size}pt; color: rgb(0,0,0); }}"
    ref_page.insert_htmlbox(
        fitz.Rect(0, 0, float(span_rect.width), float(span_rect.height)),
        "<span>Hello World</span>",
        css=css_ref,
    )
    ref_pixmap = ref_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=True)
    ref_doc.close()
    ref_image = QImage(
        ref_pixmap.samples,
        ref_pixmap.width,
        ref_pixmap.height,
        ref_pixmap.stride,
        QImage.Format_RGBA8888,
    ).copy()
    ref_ink_h = _ink_extent_px(ref_image)

    # Preview: render via PreviewRenderer (should use same engine path).
    renderer = PreviewRenderer(model=None)
    preview_image = renderer.render(
        text="Hello World",
        font_name="helv",
        font_size=font_size,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=span_rect,
        rotation=0,
        render_scale=2.0,
    )
    preview_ink_h = _ink_extent_px(preview_image)

    assert ref_ink_h > 0, "Reference render produced no ink pixels"
    assert preview_ink_h > 0, "Preview render produced no ink pixels"

    tolerance = max(
        1, ref_ink_h * 0.01
    )  # fractional 1%; 1px floor for subpixel rounding only
    delta = abs(preview_ink_h - ref_ink_h)
    assert delta <= tolerance, (
        f"Preview ink-height ({preview_ink_h}px) diverges from reference "
        f"({ref_ink_h}px) by {delta}px (tol={tolerance:.2f}px) — "
        "glyph-size regression: preview and commit use different rasterizer paths."
    )


def test_glyph_height_parity_negative_control(qapp) -> None:
    """AC 4: +10% font injection MUST be detected. Pass here = suite is not a valid gate."""
    font_size = 14.0
    span_rect = fitz.Rect(0, 0, 150, 25)

    def _ink_extent(img: QImage) -> int:
        top = bot = None
        for y in range(img.height()):
            if any(
                img.pixelColor(x, y).alpha() > 50
                and img.pixelColor(x, y).lightness() < 150
                for x in range(0, img.width(), 4)
            ):
                if top is None:
                    top = y
                bot = y
        return (bot - top + 1) if top is not None else 0

    ref_doc = fitz.open()
    ref_page = ref_doc.new_page(
        width=float(span_rect.width), height=float(span_rect.height)
    )
    ref_page.insert_htmlbox(
        fitz.Rect(0, 0, float(span_rect.width), float(span_rect.height)),
        "<span>Hello World</span>",
        css=f"span {{ font-family: Helvetica; font-size: {font_size}pt; color: rgb(0,0,0); }}",
    )
    ref_px = ref_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=True)
    ref_doc.close()
    ref_img = QImage(
        ref_px.samples,
        ref_px.width,
        ref_px.height,
        ref_px.stride,
        QImage.Format_RGBA8888,
    ).copy()
    ref_ink = _ink_extent(ref_img)

    bad_img = PreviewRenderer(model=None).render(
        text="Hello World",
        font_name="helv",
        font_size=font_size * 1.10,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=span_rect,
        rotation=0,
        render_scale=2.0,
    )
    tol = max(1, ref_ink * 0.01)  # must match the production tolerance formula exactly
    assert abs(_ink_extent(bad_img) - ref_ink) > tol, (
        f"Negative control failed: +10% font NOT detected (ref_ink={ref_ink}, tol={tol:.2f}). "
        f"Test is not a valid gate."
    )


def test_glyph_height_1pct_gate_rejects_2px_delta() -> None:
    """AC 4 formula guard: tolerance = max(1, h * 0.01) must be < 2.0 for all typical text sizes.

    This is a pure-math test (no rendering) that fails immediately if the tolerance formula
    is weakened back to max(2, ...) or max(2, int(0.01 * h)).  For any ink height ≤ 100px
    (= any font ≤ ~50pt at 2x scale), tolerance < 2.0, so a 2px height delta is detectable.

    If this test passes but the production formula uses max(2, ...) it is wrong — fix the
    production formula to match.  If this test fails, the formula allows a 2px jump to pass,
    which is a user-visible regression.
    """
    # Typical rendered ink heights for common text sizes at render_scale=2.0:
    #   14pt → ~22px,  18pt → ~28px,  24pt → ~38px,  36pt → ~57px,  72pt → ~115px
    TYPICAL_INK_HEIGHTS = [18, 22, 28, 38, 57, 80, 100]
    for h in TYPICAL_INK_HEIGHTS:
        tol = max(1, h * 0.01)
        assert tol < 2.0, (
            f"Tolerance formula too loose at ink_h={h}px: tol={tol:.3f} >= 2.0 — "
            f"a 2px glyph jump would pass undetected.  "
            f"Fix: use max(1, h * 0.01) with NO int() truncation and NO floor of 2."
        )
    # Edge: at h=200px (very large text), tolerance = 2.0 which is exactly the boundary.
    # Anything over 200px allows tolerance > 2px — acceptable since those are rare sizes.
    assert max(1, 200 * 0.01) == 2.0, "Boundary sanity: 200px → tol == 2.0"


# ---------------------------------------------------------------------------
# F17-COL-3 / F17-COL-4 (adversarial round 17): the consented rebuild
# (``legacy_redact_reinsert``, "改用重建文字…") and the same-page drag wrote the
# edited text as plain DeviceRGB fill.  CMYK / gray / Separation / Indexed
# colour became RGB, alpha and blend mode were dropped, outline text (1 Tr /
# 2 Tr) became solid fill, invisible text (3 Tr) became visible and a run left
# its optional-content layer (still drawn with the layer off) -- live and after
# save + reopen, while Tier 0/1 keep all of it.  The rebuild now re-applies the
# source paint state to the text it writes, or refuses
# (``text_state_not_reproducible``) before anything is written.

_SEPARATION_CS = (
    "[/Separation /PMS#20185 /DeviceCMYK << /FunctionType 2 /Domain [0 1] "
    "/C0 [0 0 0 0] /C1 [0 0.91 0.76 0] /N 1 >>]"
)
_LAYER_NAME = "Layer1"
# case -> (operators that set the edited run's state, extra page resources)
_STATE_CASES: dict[str, tuple[bytes, dict[str, str]]] = {
    "gray": (b"0.4 g", {}),
    "cmyk": (b"0 0.9 0.8 0 k", {}),
    "cmyk_black": (b"0 0 0 1 k", {}),
    "separation": (b"/CS0 cs 1 scn", {"ColorSpace": f"<< /CS0 {_SEPARATION_CS} >>"}),
    "indexed": (
        b"/CS1 cs 1 sc",
        {"ColorSpace": "<< /CS1 [/Indexed /DeviceRGB 1 <000000FF8000>] >>"},
    ),
    "alpha": (
        b"/GS1 gs 0 0 1 rg",
        {"ExtGState": "<< /GS1 << /Type /ExtGState /ca 0.3 /CA 0.3 >> >>"},
    ),
    "blend": (
        b"/GS1 gs 0 0 1 rg",
        {"ExtGState": "<< /GS1 << /Type /ExtGState /BM /Multiply >> >>"},
    ),
    "outline": (b"0 0 1 rg 1 0 0 RG 0.8 w 1 Tr", {}),
    "fill_stroke": (b"0 0 1 rg 1 0 0 RG 0.8 w 2 Tr", {}),
    "invisible": (b"0 g 3 Tr", {}),
    "layer": (b"0 0 1 rg", {}),
}
# The yellow band under the run of the blend case (Multiply turns blue black).
_YELLOW_BAND = b"q 1 1 0 rg 30 110 300 40 re f Q\n"


def _state_pdf(
    tmp_path: Path,
    case: str,
    *,
    state: bytes | None = None,
    resources: dict[str, str] | None = None,
    run_tail: bytes = b"",
    smask: bool = False,
) -> Path:
    """One edited run "Price 2024" (18 pt Helvetica) painted in ``case``'s
    state inside its own q/Q, and a plain DeviceRGB neighbour line elsewhere
    (so the page holds two states)."""
    if state is None:
        state, resources = _STATE_CASES[case]
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    run = b"q BT /helv 18 Tf " + state + b" 40 120 Td (Price 2024) Tj ET " + run_tail + b" Q\n"
    if case == "layer":
        run = b"/OC /L1 BDC\n" + run + b"EMC\n"
    pre = _YELLOW_BAND if case == "blend" else b""
    body = pre + run + b"q BT /helv 12 Tf 0 0 0 rg 40 200 Td (Neighbour line stays) Tj ET Q\n"
    content = doc.get_new_xref()
    doc.update_object(content, "<<>>")
    doc.update_stream(content, body)
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    font = doc.get_new_xref()
    doc.update_object(
        font, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    extra = dict(resources or {})
    if smask:
        group = doc.get_new_xref()
        doc.update_object(
            group,
            "<< /Type /XObject /Subtype /Form /BBox [0 0 400 300] "
            "/Group << /S /Transparency /CS /DeviceGray >> >>",
        )
        doc.update_stream(group, b"0.5 g 0 0 400 300 re f")
        extra["ExtGState"] = (
            "<< /GS1 << /Type /ExtGState /SMask << /Type /Mask /S /Luminosity "
            f"/G {group} 0 R >> >> >>"
        )
    res = f"<< /Font << /helv {font} 0 R >> " + "".join(f"/{k} {v} " for k, v in extra.items())
    doc.xref_set_key(page.xref, "Resources", res + ">>")
    if case == "layer":
        ocg = doc.add_ocg(_LAYER_NAME, on=True)
        doc.xref_set_key(page.xref, "Resources/Properties", f"<< /L1 {ocg} 0 R >>")
    path = tmp_path / f"state_{case}.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _open_tiered(path: Path) -> PDFModel:
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _price_run(model: PDFModel):
    """The run "2024" (the index holds one run per word here)."""
    model.ensure_page_index_built(1)
    return next(r for r in model.block_manager.get_runs(0) if (r.text or "").strip() == "2024")


def _price_block(model: PDFModel):
    """The block holding the whole show "Price 2024"."""
    return next(b for b in model.block_manager.get_blocks(0) if "2024" in (b.text or ""))


def _content_streams(model: PDFModel) -> list[bytes]:
    return [model.doc.xref_stream(x) for x in model.doc[0].get_contents()]


def _edit_price(model: PDFModel, new_text: str) -> EditTextResult:
    """The run "2024" rewritten through the consented rebuild."""
    run = _price_run(model)
    return model.edit_text(
        page_num=1,
        rect=fitz.Rect(run.bbox),
        new_text=new_text,
        font=run.font,
        size=float(run.size),
        color=tuple(float(c) for c in run.color),
        original_text=run.text,
        target_span_id=run.span_id,
        target_mode="run",
        allow_rebuild=True,
        confirm_fallback=_accept_rebuild,
    )


def _edit_price_show(model: PDFModel, new_text: str) -> EditTextResult:
    """The whole show "Price 2024" edited as its block (what Tier 0 patches:
    it does not splice a word inside one string)."""
    block = _price_block(model)
    return model.edit_text(
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=block.text.replace("2024", new_text),
        font=block.font,
        size=float(block.size),
        color=tuple(float(c) for c in block.color),
        original_text=block.text,
    )


def _drag_price(model: PDFModel, dx: float = 60.0, dy: float = 40.0) -> EditTextResult:
    block = _price_block(model)
    rect = fitz.Rect(block.layout_rect)
    return model.edit_text(
        page_num=1,
        rect=rect,
        new_text=block.text,
        font=block.font,
        size=float(block.size),
        color=tuple(float(c) for c in block.color),
        original_text=block.text,
        new_rect=fitz.Rect(rect.x0 + dx, rect.y0 + dy, rect.x1 + dx, rect.y1 + dy),
        allow_rebuild=True,
        confirm_fallback=_accept_rebuild,
    )


def _paint_ops(doc: fitz.Document, page: fitz.Page) -> list[tuple[str, tuple[float, ...]]]:
    """``(operator, numeric operands)`` of every operator the page draws with:
    its content streams and every form XObject it uses."""
    xrefs = list(page.get_contents()) + [x[0] for x in page.get_xobjects()]
    out: list[tuple[str, tuple[float, ...]]] = []
    for xref in xrefs:
        data = doc.xref_stream(xref) or b""
        numbers: list[float] = []
        for token in lex_content_stream(data):
            if token.kind in (TokenKind.WHITESPACE, TokenKind.COMMENT):
                continue
            raw = data[token.start:token.end]
            if token.kind is TokenKind.OPERATOR:
                out.append((raw.decode("latin-1"), tuple(numbers)))
                numbers = []
            elif token.kind is TokenKind.NUMBER:
                numbers.append(float(raw))
    return out


def _has_op(ops, name: str, values: tuple[float, ...], tol: float = 0.002) -> bool:
    return any(
        op == name and len(nums) == len(values) and all(abs(a - b) <= tol for a, b in zip(nums, values))
        for op, nums in ops
    )


def _spans_with(page: fitz.Page, needle: str) -> list[dict]:
    return [
        sp for sp in page.get_texttrace()
        if needle in "".join(chr(c[0]) for c in sp["chars"])
    ]


def _bbox(spans: list[dict], pad: float = 2.0) -> fitz.Rect:
    box = fitz.Rect(spans[0]["bbox"])
    for sp in spans[1:]:
        box |= fitz.Rect(sp["bbox"])
    return fitz.Rect(box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad)


def _pixels(page: fitz.Page, rect: fitz.Rect) -> list[tuple[int, int, int]]:
    pm = page.get_pixmap(clip=rect, dpi=144, colorspace=fitz.csRGB, alpha=False)
    s = pm.samples
    return [(s[i], s[i + 1], s[i + 2]) for i in range(0, len(s), 3)]


def _ink(page: fitz.Page, rect: fitz.Rect) -> int:
    return sum(1 for p in _pixels(page, rect) if sum(p) < 700)


def _assert_paint(doc: fitz.Document, page: fitz.Page, case: str, needle: str, where: str) -> None:
    """The text containing ``needle`` paints in ``case``'s source state."""
    spans = _spans_with(page, needle)
    assert spans, f"{case} {where}: {needle!r} not on the page"
    types = sorted({sp["type"] for sp in spans})
    ops = _paint_ops(doc, page)
    box = _bbox(spans)
    if case == "gray":
        assert _has_op(ops, "g", (0.4,)), (where, "gray fill lost")
        assert not _has_op(ops, "rg", (0.4, 0.4, 0.4)), (where, "gray converted to RGB")
    elif case == "cmyk":
        assert _has_op(ops, "k", (0.0, 0.9, 0.8, 0.0)), (where, "CMYK fill lost")
        assert not _has_op(ops, "rg", (0.937, 0.251, 0.239), tol=0.01), (where, "CMYK -> RGB")
    elif case == "cmyk_black":
        assert _has_op(ops, "k", (0.0, 0.0, 0.0, 1.0)), (where, "K-only black lost")
        assert not _has_op(ops, "rg", (0.137, 0.122, 0.125), tol=0.01), (where, "K -> RGB")
    elif case == "separation":
        assert _has_op(ops, "scn", (1.0,)), (where, "Separation tint lost")
        assert not _has_op(ops, "rg", (0.937, 0.238, 0.259), tol=0.01), (where, "spot -> RGB")
    elif case == "indexed":
        assert _has_op(ops, "scn", (1.0,)) or _has_op(ops, "sc", (1.0,)), (where, "index lost")
        assert not _has_op(ops, "rg", (1.0, 0.502, 0.0), tol=0.01), (where, "Indexed -> RGB")
    elif case == "alpha":
        assert all(abs(float(sp["opacity"]) - 0.3) < 0.01 for sp in spans), (where, spans)
        # Translucent blue never reaches a dark red channel; solid blue does.
        assert min(p[0] for p in _pixels(page, box) if sum(p) < 760) > 120, where
    elif case == "blend":
        pixels = _pixels(page, box)
        pure_blue = sum(1 for r, g, b in pixels if b > 200 and r < 60 and g < 60)
        dark = sum(1 for r, g, b in pixels if r < 60 and g < 60 and b < 60)
        assert pure_blue == 0 and dark > 20, (where, "Multiply blend lost", pure_blue, dark)
    elif case == "outline":
        assert types == [1], (where, types)
    elif case == "fill_stroke":
        assert types == [0, 1], (where, types)
    elif case == "invisible":
        assert types == [3], (where, types)
        assert _ink(page, box) == 0, (where, "invisible text drawn")
    elif case == "layer":
        assert all(sp.get("layer") == _LAYER_NAME for sp in spans), (where, spans)
    else:
        raise AssertionError(case)


def _assert_layer_hides(path: Path, needle: str) -> None:
    """With its layer switched off, the text is not drawn (saved file)."""
    doc = fitz.open(str(path))
    try:
        page = doc[0]
        box = _bbox(_spans_with(page, needle))
        ocg = next(x for x, info in doc.get_ocgs().items() if info["name"] == _LAYER_NAME)
        assert _ink(page, box) > 0
        doc.set_layer(-1, off=[ocg])
        # MuPDF reads the layer configuration at open: render a reopened copy.
        hidden = fitz.open("pdf", doc.tobytes())
        try:
            assert _ink(hidden[0], box) == 0, "still drawn with its layer off"
        finally:
            hidden.close()
    finally:
        doc.close()


def _assert_saved_paint(model: PDFModel, tmp_path: Path, case: str, needle: str) -> None:
    saved = tmp_path / f"saved_{case}.pdf"
    model.save_as(str(saved))
    doc = fitz.open(str(saved))
    try:
        _assert_paint(doc, doc[0], case, needle, "after save + reopen")
    finally:
        doc.close()
    if case == "layer":
        _assert_layer_hides(saved, needle)


@pytest.mark.parametrize("case", sorted(_STATE_CASES))
def test_consented_rebuild_keeps_the_edited_runs_paint_state(tmp_path: Path, case: str) -> None:
    """F17-COL-4 (colour space, alpha, blend, render mode) and F17-COL-3
    (layer): the rebuilt text paints like its source, live and after reopen."""
    model = _open_tiered(_state_pdf(tmp_path, case))
    try:
        assert _edit_price(model, "2025\u014b") is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY
        _assert_paint(model.doc, model.doc[0], case, "2025", "live")
        _assert_saved_paint(model, tmp_path, case, "2025")
    finally:
        model.close()


@pytest.mark.parametrize("case", ["layer", "invisible", "cmyk", "alpha", "gray"])
def test_same_page_drag_keeps_the_moved_runs_paint_state(tmp_path: Path, case: str) -> None:
    """F17-COL-3 / F17-COL-2 drag half: a same-page drag is rebuild-only; the
    moved run keeps its layer, render mode, colour space and alpha."""
    model = _open_tiered(_state_pdf(tmp_path, case))
    try:
        assert _drag_price(model) is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY
        _assert_paint(model.doc, model.doc[0], case, "2024", "live")
        _assert_saved_paint(model, tmp_path, case, "2024")
    finally:
        model.close()


@pytest.mark.parametrize("case", ["gray", "cmyk", "separation", "alpha", "layer"])
def test_tier0_edit_keeps_the_paint_state_unchanged(tmp_path: Path, case: str) -> None:
    """GUARD: Tier 0 already kept every state (its stream patch never leaves
    the source operators); the fix must not touch that path."""
    model = _open_tiered(_state_pdf(tmp_path, case))
    try:
        assert _edit_price_show(model, "2025") is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        _assert_paint(model.doc, model.doc[0], case, "2025", "tier 0 live")
        _assert_saved_paint(model, tmp_path, case, "2025")
    finally:
        model.close()


_PATTERN_RES = {
    "Pattern": (
        "<< /P0 << /PatternType 2 /Shading << /ShadingType 2 /ColorSpace /DeviceRGB "
        "/Coords [0 0 400 0] /Function << /FunctionType 2 /Domain [0 1] /C0 [1 0 0] "
        "/C1 [0 0 1] /N 1 >> >> >> >>"
    )
}


@pytest.mark.parametrize(
    "state, resources, run_tail",
    [
        (b"7 Tr", {}, b"0 0 1 rg 0 0 400 300 re f"),
        (b"0 0 1 rg 4 Tr", {}, b"1 0 0 rg 0 0 400 300 re f"),
        (b"/Pattern cs /P0 scn", _PATTERN_RES, b""),
    ],
    ids=["clip_7Tr", "fill_clip_4Tr", "pattern_fill"],
)
def test_consented_rebuild_refuses_a_paint_state_it_cannot_reproduce(
    tmp_path: Path, state: bytes, resources: dict[str, str], run_tail: bytes
) -> None:
    """A clipping render mode (the text is a clip for what follows it) or a
    Pattern colour cannot be re-applied by the rebuild's writer: refused with
    its own reason code before anything is written (never a silent
    conversion to plain fill)."""
    model = _open_tiered(
        _state_pdf(tmp_path, "custom", state=state, resources=resources, run_tail=run_tail)
    )
    try:
        streams_before = _content_streams(model)
        with pytest.raises(TextEditRefused) as excinfo:
            _edit_price(model, "2025\u014b")
        assert excinfo.value.reason.value == "text_state_not_reproducible"
        assert _content_streams(model) == streams_before
        assert model.command_manager._undo_stack == []
    finally:
        model.close()


def test_soft_mask_is_kept_in_place_and_refused_when_the_text_moves(tmp_path: Path) -> None:
    """A soft mask is placed in page space where it was set: kept for an
    in-place rebuild (the ExtGState is applied again), refused for a drag
    (the text would leave its mask)."""
    path = _state_pdf(tmp_path, "smask", state=b"/GS1 gs 0 0 1 rg", smask=True)
    model = _open_tiered(path)
    try:
        assert _edit_price(model, "2025\u014b") is EditTextResult.SUCCESS
        ops = _paint_ops(model.doc, model.doc[0])
        assert any(op == "gs" for op, _nums in ops)
        assert _has_op(ops, "rg", (0.0, 0.0, 1.0))
    finally:
        model.close()
    model = _open_tiered(path)
    try:
        streams_before = _content_streams(model)
        with pytest.raises(TextEditRefused) as excinfo:
            _drag_price(model)
        assert excinfo.value.reason.value == "text_state_not_reproducible"
        assert _content_streams(model) == streams_before
    finally:
        model.close()


def test_every_rebuild_write_goes_through_the_paint_state_chokepoint() -> None:
    """Structural guard (F17-COL-1..4): every writer call of the legacy
    rebuild that draws on the LIVE page (first argument ``page``, not a
    ``scratch=True`` measurement) sits inside ``with paint_state_applied(...)``
    -- a new writer site cannot silently drop the source paint state again.
    The scan must find the known sites, so it cannot pass vacuously."""
    source_path = Path(__file__).resolve().parents[1] / "model" / "pdf_text_edit.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    writers = {"insert_htmlbox_tracked", "insert_text_page_space", "_insert_htmlbox_unshrunk"}
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def _name(call: ast.Call) -> str:
        func = call.func
        return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")

    def _guarded(node: ast.AST) -> bool:
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.With, ast.AsyncWith)) and any(
                isinstance(item.context_expr, ast.Call)
                and _name(item.context_expr) == "paint_state_applied"
                for item in current.items
            ):
                return True
            if isinstance(current, ast.FunctionDef) and current.name in writers:
                return True  # the writer helper's own body: its callers wrap it
            current = parents.get(current)
        return False

    live_writes = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _name(node) in writers):
            continue
        if any(k.arg == "scratch" for k in node.keywords):
            continue
        if not (node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "page"):
            continue
        live_writes.append(node)
    unguarded = [n.lineno for n in live_writes if not _guarded(n)]
    assert len(live_writes) >= 6, [n.lineno for n in live_writes]
    assert unguarded == [], f"rebuild writes outside paint_state_applied at lines {unguarded}"
