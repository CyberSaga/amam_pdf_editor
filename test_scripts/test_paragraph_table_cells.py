"""T16-2: paragraph mode must not span table cells.

A raw PyMuPDF text block happily contains a whole table row (every cell of it),
so building exactly one ``EditableParagraph`` per block made paragraph-mode edits
redact the entire row.  These tests pin the three splitting rules added to
``model.text_block_parsing._build_paragraphs``:

(a)  one PyMuPDF line is cut into cells at a horizontal run gap wider than
     ``_CELL_GAP_RATIO`` x the larger run's font size,
(a2) cells from *different* PyMuPDF lines that share a baseline are re-joined
     when their gap is at most ``_SAME_BASELINE_GAP_RATIO`` x the larger font
     size (MuPDF opens a new line at every positioning jump, so one visual line
     of prose arrives as several lines), and
(b)  the resulting units are grouped into sub-paragraphs by horizontal-range
     overlap.

Measured evidence for the thresholds lives in
``plans/task16-legacy-path-fidelity.md`` (Log, 2026-09-05).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import pytest

from model import text_block_parsing as tbp
from model.pdf_model import PDFModel
from model.text_block import EditableSpan

HVAC_FIXTURE = Path("test_files/[HVAC_DWG_PDF]")

# Sibling-cell tokens that must never share a paragraph with 工程資料名稱.
FOREIGN_CELL_TOKENS = ("[SITE_SHORT]", "[CLIENT_ACRONYM]", "送審", "[HVAC_PROJECT]")

# The 工程資料名稱 label cell ends at x 126.36; the next cell starts at 137.18.
# Anything reaching past 300 has swallowed the right-hand half of the row.
LABEL_CELL_X_LIMIT = 300.0


def _span(
    span_id: str,
    line_idx: int,
    span_idx: int,
    bbox: tuple[float, float, float, float],
    text: str,
    size: float = 12.0,
) -> EditableSpan:
    rect = fitz.Rect(*bbox)
    return EditableSpan(
        span_id=span_id,
        page_idx=0,
        block_idx=0,
        line_idx=line_idx,
        span_idx=span_idx,
        bbox=rect,
        origin=fitz.Point(rect.x0, rect.y1),
        text=text,
        font="helv",
        size=size,
        color=(0.0, 0.0, 0.0),
        dir_vec=(1.0, 0.0),
        rotation=0,
    )


def _make_row_and_wrapped_pdf(path: Path) -> None:
    """One table row of three cells, plus a genuine wrapped paragraph below it."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=300)
    for x, text in ((72, "Item name"), (300, "Quantity"), (420, "Unit price")):
        page.insert_text(fitz.Point(x, 100), text, fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(72, 140, 260, 220),
        "The wrapped paragraph body continues onto a second visual line here.",
        fontsize=12,
        fontname="helv",
    )
    doc.save(path, garbage=0)
    doc.close()


# --------------------------------------------------------------------------
# Rule (a): intra-line cell split
# --------------------------------------------------------------------------


def test_wide_intra_line_gap_splits_a_line_into_cells() -> None:
    """The measured HVAC cell boundary (gap 10.82 at size 12 = 0.90x) splits."""
    paragraphs = tbp._build_paragraphs(
        0,
        [
            _span("run-label", 0, 0, (52.56, 131.65, 126.36, 143.65), "工程資料名稱"),
            _span("run-value", 0, 1, (137.18, 131.65, 161.18, 143.65), "[SITE_SHORT]"),
        ],
    )

    assert len(paragraphs) == 2, [p.text for p in paragraphs]
    assert paragraphs[0].text == "工程資料名稱"
    assert paragraphs[0].run_ids == ["run-label"]
    assert paragraphs[0].bbox.x1 == pytest.approx(126.36, abs=0.01)
    assert paragraphs[1].text == "[SITE_SHORT]"
    assert paragraphs[1].run_ids == ["run-value"]
    assert {p.paragraph_id for p in paragraphs} == {"pg0_b0_p0", "pg0_b0_p1"}


def test_ordinary_word_gap_does_not_split_a_line() -> None:
    """The widest justified-prose gap measured in 1.pdf (6.98 at size 12 = 0.58x) holds."""
    paragraphs = tbp._build_paragraphs(
        0,
        [
            _span("run-1", 0, 0, (10.0, 10.0, 80.0, 22.0), "was"),
            _span("run-2", 0, 1, (86.98, 10.0, 120.0, 22.0), "young"),
        ],
    )

    assert len(paragraphs) == 1, [p.text for p in paragraphs]
    assert paragraphs[0].text == "was young"
    assert paragraphs[0].run_ids == ["run-1", "run-2"]
    assert paragraphs[0].paragraph_id == "pg0_b0_p0"


def test_vertical_block_is_never_cell_split() -> None:
    """90/270 blocks keep one paragraph per block: their re-merge path assumes it."""
    runs = [
        _span("run-1", 0, 0, (52.56, 131.65, 126.36, 143.65), "縦書き"),
        _span("run-2", 0, 1, (137.18, 131.65, 161.18, 143.65), "本文"),
    ]
    rotated = [
        EditableSpan(
            span_id=r.span_id,
            page_idx=r.page_idx,
            block_idx=r.block_idx,
            line_idx=r.line_idx,
            span_idx=r.span_idx,
            bbox=r.bbox,
            origin=r.origin,
            text=r.text,
            font=r.font,
            size=r.size,
            color=r.color,
            dir_vec=(0.0, 1.0),
            rotation=270,
        )
        for r in runs
    ]

    paragraphs = tbp._build_paragraphs(0, rotated)

    assert len(paragraphs) == 1, [p.text for p in paragraphs]
    assert paragraphs[0].paragraph_id == "pg0_b0_p0"


# --------------------------------------------------------------------------
# Rule (b): cross-line column grouping
# --------------------------------------------------------------------------


def test_synthetic_table_row_yields_one_paragraph_per_cell() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "row.pdf"
        _make_row_and_wrapped_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            row_paragraphs = [
                p for p in model.block_manager.get_paragraphs(0) if p.bbox.y1 < 130.0
            ]

            assert [p.text for p in row_paragraphs] == [
                "Item name",
                "Quantity",
                "Unit price",
            ]
            assert [p.paragraph_id for p in row_paragraphs] == [
                "pg0_b0_p0",
                "pg0_b0_p1",
                "pg0_b0_p2",
            ]
            assert row_paragraphs[0].bbox.x1 < 300.0
        finally:
            model.close()


def test_synthetic_wrapped_paragraph_stays_one_paragraph() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "row.pdf"
        _make_row_and_wrapped_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            body_paragraphs = [
                p for p in model.block_manager.get_paragraphs(0) if p.bbox.y0 > 130.0
            ]

            assert len(body_paragraphs) == 1, [p.text for p in body_paragraphs]
            assert body_paragraphs[0].text == (
                "The wrapped paragraph body continues onto a second visual line here."
            )
            assert body_paragraphs[0].paragraph_id == "pg0_b1_p0"
        finally:
            model.close()


# --------------------------------------------------------------------------
# Real-corpus regression: HVAC page 1, raw block 6
# --------------------------------------------------------------------------


def _hvac_label_run(model: PDFModel) -> EditableSpan:
    run = next(
        (
            r
            for r in model.block_manager.get_runs(0)
            if "工程資料名稱" in (r.text or "")
        ),
        None,
    )
    assert run is not None, "fixture changed: no 工程資料名稱 run on page 1"
    return run


def test_hvac_label_cell_paragraph_excludes_sibling_cells() -> None:
    if not HVAC_FIXTURE.exists():
        pytest.skip(f"missing optional fixture: {HVAC_FIXTURE}")

    model = PDFModel()
    try:
        model.open_pdf(str(HVAC_FIXTURE))
        model.ensure_page_index_built(1)
        label_run = _hvac_label_run(model)
        para = model.block_manager.find_paragraph_for_run(0, label_run.span_id)

        assert para is not None
        members = [model.block_manager.find_run_by_id(0, rid) for rid in para.run_ids]
        member_text = "".join((run.text or "") for run in members if run is not None)
        for token in FOREIGN_CELL_TOKENS:
            assert token not in member_text, (
                f"paragraph for the 工程資料名稱 cell leaked sibling-cell token {token!r}: "
                f"{member_text!r}"
            )
        assert para.bbox.x1 <= LABEL_CELL_X_LIMIT, (
            f"label-cell paragraph bbox spans the whole row: {tuple(para.bbox)}"
        )
    finally:
        model.close()


def test_hvac_paragraph_mode_hit_does_not_target_the_whole_row() -> None:
    """The consumer path: ``get_text_info_at_point`` in paragraph mode."""
    if not HVAC_FIXTURE.exists():
        pytest.skip(f"missing optional fixture: {HVAC_FIXTURE}")

    model = PDFModel()
    try:
        model.open_pdf(str(HVAC_FIXTURE))
        model.ensure_page_index_built(1)
        model.set_text_target_mode("paragraph")
        label_run = _hvac_label_run(model)

        hit = model.get_text_info_at_point(
            1,
            fitz.Point(
                (label_run.bbox.x0 + label_run.bbox.x1) / 2.0,
                (label_run.bbox.y0 + label_run.bbox.y1) / 2.0,
            ),
        )

        assert hit is not None and hit.target_mode == "paragraph"
        for token in FOREIGN_CELL_TOKENS:
            assert token not in (hit.target_text or ""), (
                f"paragraph-mode hit swallowed sibling cell {token!r}: {hit.target_text!r}"
            )
        assert fitz.Rect(hit.target_bbox).x1 <= LABEL_CELL_X_LIMIT, (
            f"paragraph-mode target rect covers the whole table row: {tuple(hit.target_bbox)}"
        )
    finally:
        model.close()
