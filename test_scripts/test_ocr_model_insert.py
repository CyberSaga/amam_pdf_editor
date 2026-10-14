from __future__ import annotations

import hashlib

import fitz
import pytest

from model.pdf_model import PDFModel
from model.tools.ocr_types import OcrSpan


def _pixmap_hash(page: fitz.Page, scale: float = 1.5) -> str:
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), annots=False)
    return hashlib.sha1(pix.samples).hexdigest()


def _pixmap_distance(a: fitz.Pixmap, b: fitz.Pixmap) -> float:
    """Mean absolute difference per pixel across all channels, in [0, 255]."""
    assert a.width == b.width and a.height == b.height and a.n == b.n
    buf_a = a.samples
    buf_b = b.samples
    diff = 0
    length = len(buf_a)
    for i in range(0, length, 97):  # sparse sample — good enough for tolerance check
        diff += abs(buf_a[i] - buf_b[i])
    samples = (length + 96) // 97
    return diff / samples if samples else 0.0


def _scanlike_pdf(tmp_path) -> str:
    """Produce a page whose content is a raster shape (no text at all)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(40, 40, 360, 120), color=(0.85, 0.85, 0.85), fill=(0.85, 0.85, 0.85))
    page.draw_rect(fitz.Rect(40, 140, 360, 220), color=(0.7, 0.7, 0.7), fill=(0.7, 0.7, 0.7))
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def model_with_scan(tmp_path) -> PDFModel:
    path = _scanlike_pdf(tmp_path)
    model = PDFModel()
    model.open_pdf(path)
    return model


def test_apply_ocr_spans_inserts_searchable_text(model_with_scan):
    page = model_with_scan.doc[0]
    assert "hello world" not in page.get_text()

    count = model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="hello world", confidence=0.99)],
    )
    assert count == 1
    assert "hello world" in page.get_text().lower()


def test_apply_ocr_spans_locates_text_via_search_for(model_with_scan):
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="invoice", confidence=0.92)],
    )
    page = model_with_scan.doc[0]
    hits = page.search_for("invoice")
    assert len(hits) >= 1


def test_apply_ocr_spans_keeps_render_visually_unchanged(model_with_scan):
    page = model_with_scan.doc[0]
    before = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), annots=False)

    model_with_scan.apply_ocr_spans(
        1,
        [
            OcrSpan(bbox=(50.0, 50.0, 310.0, 110.0), text="sample one", confidence=0.9),
            OcrSpan(bbox=(50.0, 150.0, 310.0, 210.0), text="sample two", confidence=0.9),
        ],
    )
    after = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), annots=False)
    # Render-mode 3 text emits no glyphs to the page content, so pixel output must match.
    mean_diff = _pixmap_distance(before, after)
    assert mean_diff < 1.0, f"page pixels changed unexpectedly: mean diff={mean_diff}"


def test_apply_ocr_spans_handles_cjk_text(model_with_scan):
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="測試文字", confidence=0.85)],
    )
    page = model_with_scan.doc[0]
    hits = page.search_for("測試")
    assert len(hits) >= 1


def test_apply_ocr_spans_handles_japanese_text(model_with_scan):
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 150.0, 250.0, 190.0), text="こんにちは", confidence=0.8)],
    )
    page = model_with_scan.doc[0]
    hits = page.search_for("こんにちは")
    assert len(hits) >= 1


def test_apply_ocr_spans_skips_empty_text(model_with_scan):
    count = model_with_scan.apply_ocr_spans(
        1,
        [
            OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="", confidence=0.5),
            OcrSpan(bbox=(50.0, 100.0, 200.0, 130.0), text="   ", confidence=0.5),
        ],
    )
    assert count == 0


def test_apply_ocr_spans_increments_edit_count(model_with_scan):
    baseline = model_with_scan.edit_count
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="foo", confidence=0.9)],
    )
    assert model_with_scan.edit_count == baseline + 1


def test_apply_ocr_spans_rebuilds_block_index(model_with_scan):
    # Force the page index into 'stale' before OCR.
    model_with_scan.block_manager._page_state[0] = "stale"
    assert model_with_scan.block_manager.page_state(0) == "stale"
    model_with_scan.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(50.0, 50.0, 200.0, 80.0), text="bar", confidence=0.9)],
    )
    assert model_with_scan.block_manager.page_state(0) != "stale"


# ``page.cropbox`` is MediaBox-relative and y-flipped, so on these pages it is
# not page space. The ``/UserUnit`` rows are F15-G6: PyMuPDF's ``insert_text``
# takes UNSCALED user units while the bbox is in page space (``page.rect`` is
# already multiplied by ``/UserUnit``), so the word used to land at 2x the
# position and size.
_OCR_BOX_GEOMETRIES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "crop": {"mediabox": (0, 0, 600, 800), "cropbox": (30, 40, 500, 700)},
    "posmb": {"mediabox": (50, 70, 650, 870)},
    "uu2": {"mediabox": (0, 0, 300, 400), "user_unit": 2},
    "uu0.5": {"mediabox": (0, 0, 1200, 1600), "user_unit": 0.5},
    "uu2_crop": {"mediabox": (0, 0, 300, 400), "cropbox": (15, 20, 250, 350), "user_unit": 2},
    "uu2_negmb": {"mediabox": (-50, -100, 250, 300), "user_unit": 2},
}


@pytest.mark.parametrize("geometry", list(_OCR_BOX_GEOMETRIES))
def test_apply_ocr_spans_word_lands_at_requested_bbox_on_offset_page_boxes(tmp_path, geometry):
    """F15-G1: OCR spans were clamped against raw ``page.cropbox``.

    On a CropBox-inside-MediaBox page a span at (10,10,120,30) became a 1x1 word
    at (30,100); with the MediaBox at (50,70) it was written 40 pt to the right.
    """
    spec = _OCR_BOX_GEOMETRIES[geometry]
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % spec["mediabox"])
    if "cropbox" in spec:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % spec["cropbox"])
    if "user_unit" in spec:
        doc.xref_set_key(page.xref, "UserUnit", str(spec["user_unit"]))
    path = tmp_path / f"ocr_{geometry}.pdf"
    doc.save(str(path))
    doc.close()

    model = PDFModel()
    try:
        model.open_pdf(str(path))
        requested = fitz.Rect(10, 10, 120, 30)
        count = model.apply_ocr_spans(
            1, [OcrSpan(bbox=tuple(requested), text="OCRWORD", confidence=0.9)]
        )
        assert count == 1
        words = [fitz.Rect(w[:4]) for w in model.doc[0].get_text("words") if w[4] == "OCRWORD"]
        assert len(words) == 1, (geometry, words)
        word = words[0]
        assert abs(word.x0 - requested.x0) <= 2.0, (geometry, word, requested)
        assert word.width >= 0.5 * requested.width, (geometry, word, requested)
        assert requested.y0 - 6 <= word.y0 and word.y1 <= requested.y1 + 6, (geometry, word, requested)
        # The glyphs keep the page-unit size (0.9 x the bbox height), not 2x.
        sizes = [
            span["size"]
            for block in model.doc[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
            if span["text"] == "OCRWORD"
        ]
        assert sizes and sizes[0] == pytest.approx(0.9 * requested.height, rel=0.1), (geometry, sizes)
    finally:
        model.close()


def test_apply_ocr_spans_rejects_invalid_page(model_with_scan):
    with pytest.raises(ValueError):
        model_with_scan.apply_ocr_spans(
            0,
            [OcrSpan(bbox=(0, 0, 10, 10), text="x", confidence=0.5)],
        )
    with pytest.raises(ValueError):
        model_with_scan.apply_ocr_spans(
            99,
            [OcrSpan(bbox=(0, 0, 10, 10), text="x", confidence=0.5)],
        )


def test_apply_ocr_spans_without_doc_returns_zero():
    model = PDFModel()
    result = model.apply_ocr_spans(
        1,
        [OcrSpan(bbox=(0, 0, 10, 10), text="x", confidence=0.5)],
    )
    assert result == 0


def test_pixmap_hash_helper():
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    h1 = _pixmap_hash(page)
    page.draw_rect(fitz.Rect(0, 0, 100, 100), fill=(0.5, 0.5, 0.5))
    h2 = _pixmap_hash(page)
    assert h1 != h2
    doc.close()


# ---------------------------------------------------------------------------
# F17-COL-2 (adversarial round 17, high): editing the invisible OCR layer
# (render mode 3) through the consented rebuild ("改用重建文字…") or a
# same-page drag drew the replacement -- and the OCR words it replayed -- as
# visible black fill over the scan, live and after save.  The OCR text must
# stay invisible (and searchable).


def _ocr_scan(tmp_path) -> str:
    """A scanned page (an image of two text lines) with the app's own OCR
    layer over it, saved and reopened like a real session."""
    source = fitz.open()
    drawn = source.new_page(width=400, height=300)
    drawn.insert_text((40, 100), "Invoice total amount", fontsize=16)
    drawn.insert_text((40, 118), "Payment due within days", fontsize=16)
    words = drawn.get_text("words")
    pix = drawn.get_pixmap(dpi=150)
    scan = fitz.open()
    page = scan.new_page(width=400, height=300)
    page.insert_image(page.rect, pixmap=pix)
    scan_path = tmp_path / "ocr_scan.pdf"
    scan.save(str(scan_path))
    scan.close()
    source.close()
    model = PDFModel()
    model.open_pdf(str(scan_path))
    spans = [OcrSpan(bbox=tuple(w[:4]), text=w[4], confidence=0.99) for w in words]
    assert model.apply_ocr_spans(1, spans) == len(spans)
    ocr_path = tmp_path / "ocr_scan_ocrd.pdf"
    model.save_as(str(ocr_path))
    model.close()
    return str(ocr_path)


def _visible_change(a: fitz.Pixmap, b: fitz.Pixmap) -> int:
    sa, sb = a.samples, b.samples
    return sum(
        1
        for i in range(0, len(sa), 3)
        if abs(sa[i] - sb[i]) + abs(sa[i + 1] - sb[i + 1]) + abs(sa[i + 2] - sb[i + 2]) > 30
    )


def _render(page: fitz.Page) -> fitz.Pixmap:
    return page.get_pixmap(dpi=72, colorspace=fitz.csRGB, alpha=False)


def _accept_rebuild(_chain):
    return True


def _assert_ocr_layer_invisible(page: fitz.Page, before: fitz.Pixmap, where: str) -> None:
    assert _visible_change(before, _render(page)) == 0, f"{where}: OCR text drawn over the scan"
    types = {sp["type"] for sp in page.get_texttrace()}
    assert types == {3}, (where, types)


def test_consented_rebuild_of_ocr_text_keeps_the_layer_invisible(tmp_path):
    from model.text_commit.dto import CommitTier, TextCommitSettings

    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(_ocr_scan(tmp_path))
    try:
        model.ensure_page_index_built(1)
        before = _render(model.doc[0])
        run = next(r for r in model.block_manager.get_runs(0) if "total" in (r.text or ""))
        result = model.edit_text(
            1,
            fitz.Rect(run.bbox),
            run.text.replace("total", "sum"),
            font=run.font,
            size=float(run.size),
            color=tuple(run.color),
            original_text=run.text,
            target_span_id=run.span_id,
            target_mode="run",
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result.name == "SUCCESS"
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY
        page = model.doc[0]
        assert "sum" in page.get_text()
        _assert_ocr_layer_invisible(page, before, "live")
        saved = tmp_path / "ocr_edited.pdf"
        model.save_as(str(saved))
    finally:
        model.close()
    doc = fitz.open(str(saved))
    try:
        assert "sum" in doc[0].get_text()
        _assert_ocr_layer_invisible(doc[0], before, "after save + reopen")
    finally:
        doc.close()


def test_dragging_ocr_text_on_its_page_keeps_it_invisible(tmp_path):
    from model.text_commit.dto import TextCommitSettings

    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    model.open_pdf(_ocr_scan(tmp_path))
    try:
        model.ensure_page_index_built(1)
        before = _render(model.doc[0])
        block = next(b for b in model.block_manager.get_blocks(0) if "Invoice" in (b.text or ""))
        rect = fitz.Rect(block.layout_rect)
        result = model.edit_text(
            1,
            rect,
            block.text,
            font=block.font,
            size=float(block.size),
            color=tuple(block.color),
            original_text=block.text,
            new_rect=fitz.Rect(rect.x0, rect.y0 + 120, rect.x1, rect.y1 + 120),
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result.name == "SUCCESS"
        page = model.doc[0]
        moved = [w for w in page.get_text("words") if w[4] == "Invoice"]
        assert moved and moved[0][1] > rect.y0 + 100, moved
        _assert_ocr_layer_invisible(page, before, "after the drag")
    finally:
        model.close()
