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
``plans/archive/task16-legacy-path-fidelity.md`` (Log, 2026-09-05).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import pytest

from model import text_block_parsing as tbp
from model.pdf_model import PDFModel
from model.text_block import EditableSpan

HVAC_FIXTURE = Path("test_files/hvac-dwg.pdf")


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
            _span("run-value", 0, 1, (137.18, 131.65, 161.18, 143.65), "甲站"),
        ],
    )

    assert len(paragraphs) == 2, [p.text for p in paragraphs]
    assert paragraphs[0].text == "工程資料名稱"
    assert paragraphs[0].run_ids == ["run-label"]
    assert paragraphs[0].bbox.x1 == pytest.approx(126.36, abs=0.01)
    assert paragraphs[1].text == "甲站"
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


def _rotate(runs: list[EditableSpan], rotation: int) -> list[EditableSpan]:
    dir_vec = {
        90: (0.0, -1.0),
        180: (-1.0, 0.0),
        270: (0.0, 1.0),
    }[rotation]
    return [
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
            dir_vec=dir_vec,
            rotation=rotation,
        )
        for r in runs
    ]


def test_vertical_block_is_never_cell_split() -> None:
    """90/270 blocks keep one paragraph per block: their re-merge path assumes it.

    The two runs sit on *different* PyMuPDF lines with disjoint x-ranges -- the shape
    every real vertical block has, because a vertical MuPDF "line" is a column. An
    earlier revision of this test put both runs on line 0, which collapsed them into a
    single unit before rule (b) ever ran, so it could not observe column grouping.
    """
    rotated = _rotate(
        [
            _span("run-1", 0, 0, (52.56, 131.65, 126.36, 143.65), "縦書き"),
            _span("run-2", 1, 0, (137.18, 131.65, 161.18, 143.65), "本文"),
        ],
        270,
    )

    paragraphs = tbp._build_paragraphs(0, rotated)

    assert len(paragraphs) == 1, [p.text for p in paragraphs]
    assert paragraphs[0].paragraph_id == "pg0_b0_p0"
    assert paragraphs[0].run_ids == ["run-1", "run-2"]


def test_multi_line_vertical_block_needs_no_vertical_re_merge() -> None:
    """Geometry of HVAC page index 4, block 167 (a wrapped vertical project title).

    Rule (b) splits this block into two columns and ``_merge_vertical_paragraphs``
    happens to glue it back together *when the block is parsed alone*, which is why a
    plain ``len() == 1`` assertion cannot see the defect. The paragraph id is the
    tell: ``pg0_vmerge_0`` means the block was shredded and repaired, ``pg0_b0_p0``
    means it was never split. On the real page the repair does not fire (the enlarged
    paragraph population breaks the greedy adjacency chain) and the title stays torn.
    """
    rotated = _rotate(
        [
            _span(
                "run-a", 0, 0, (678.88, 1106.94, 685.62, 1147.41), "乙市丙區甲站", 6.75
            ),
            _span("run-b", 0, 1, (678.88, 1147.41, 685.62, 1154.00), "AI", 6.75),
            _span(
                "run-c", 1, 0, (669.88, 1091.34, 676.62, 1131.82), "超級算力中心", 6.75
            ),
            _span("run-d", 1, 1, (669.88, 1131.82, 676.62, 1144.05), "EPC", 6.75),
            _span("run-e", 1, 2, (669.88, 1144.05, 676.62, 1171.03), "委託工程", 6.75),
        ],
        90,
    )

    paragraphs = tbp._build_paragraphs(0, rotated)

    assert len(paragraphs) == 1, [p.text for p in paragraphs]
    assert paragraphs[0].paragraph_id == "pg0_b0_p0", (
        "the vertical block reached _merge_vertical_paragraphs already split"
    )
    assert paragraphs[0].run_ids == ["run-a", "run-b", "run-c", "run-d", "run-e"]


# --------------------------------------------------------------------------
# Rule (a2): same-baseline re-join
# --------------------------------------------------------------------------


@pytest.mark.parametrize("line_order", [(0, 1, 2), (2, 0, 1), (1, 2, 0), (2, 1, 0)])
def test_same_baseline_merge_reads_left_to_right_whatever_the_line_order(
    line_order: tuple[int, int, int],
) -> None:
    """Invariant pin (passes as written): MuPDF's line numbering must not reorder text.

    ``_merge_same_baseline_units`` walks units in x0 order and each host only ever
    absorbs units to its right, so the composed string is left-to-right no matter
    which PyMuPDF line each fragment arrived on. A refactor that folded units in
    insertion or line order instead would silently scramble prose.
    """
    runs = [
        _span("run-a", line_order[0], 0, (10.0, 10.0, 60.0, 22.0), "alpha"),
        _span("run-b", line_order[1], 0, (90.0, 10.0, 140.0, 22.0), "beta"),
        _span("run-c", line_order[2], 0, (170.0, 10.0, 220.0, 22.0), "gamma"),
    ]

    paragraphs = tbp._build_paragraphs(0, runs)

    # Gaps are 30pt at size 12 = 2.5x, inside _SAME_BASELINE_GAP_RATIO.
    assert len(paragraphs) == 1, [p.text for p in paragraphs]
    assert paragraphs[0].text == "alpha beta gamma"
    assert sorted(paragraphs[0].run_ids) == ["run-a", "run-b", "run-c"]


def test_wide_same_baseline_gap_still_splits_across_lines() -> None:
    """The control for the pin above: 5.0x is a column boundary, not a Td jump."""
    paragraphs = tbp._build_paragraphs(
        0,
        [
            _span("run-a", 0, 0, (10.0, 10.0, 60.0, 22.0), "alpha"),
            _span("run-b", 1, 0, (120.0, 10.0, 170.0, 22.0), "beta"),
        ],
    )

    assert [p.text for p in paragraphs] == ["alpha", "beta"]


# --------------------------------------------------------------------------
# Rule (a2) on 180-degree (upside-down) text
# --------------------------------------------------------------------------


def test_upside_down_block_composes_in_reading_order() -> None:
    """180-degree text advances in -x, so the leftmost fragment is read LAST.

    ``_merge_same_baseline_units`` folds same-baseline units together in a fixed
    horizontal order.  Keying that order on ascending page-x reverses an upside-down
    block: the composed paragraph text -- which is what a paragraph-mode edit
    re-inserts -- comes out backwards.
    """
    runs = _rotate(
        [
            _span("run-first", 0, 0, (50.0, 10.0, 70.0, 22.0), "FIRST"),
            _span("run-second", 1, 0, (20.0, 10.0, 40.0, 22.0), "SECOND"),
        ],
        180,
    )

    paragraphs = tbp._build_paragraphs(0, runs)

    assert len(paragraphs) == 1, [p.text for p in paragraphs]
    assert paragraphs[0].text == "FIRST SECOND"


@pytest.mark.parametrize("line_order", [(0, 1, 2), (2, 0, 1), (1, 2, 0), (2, 1, 0)])
def test_upside_down_same_baseline_merge_ignores_the_line_order(
    line_order: tuple[int, int, int],
) -> None:
    """The 180-degree twin of the rotation-0 ordering pin above.

    ``alpha`` sits at the HIGHEST page-x because -x is the reading direction here, so
    a correct implementation composes ``alpha beta gamma`` whatever line each fragment
    arrived on -- and a page-x-ascending one composes ``gamma beta alpha``.
    """
    runs = _rotate(
        [
            _span("run-a", line_order[0], 0, (170.0, 10.0, 220.0, 22.0), "alpha"),
            _span("run-b", line_order[1], 0, (90.0, 10.0, 140.0, 22.0), "beta"),
            _span("run-c", line_order[2], 0, (10.0, 10.0, 60.0, 22.0), "gamma"),
        ],
        180,
    )

    paragraphs = tbp._build_paragraphs(0, runs)

    # Gaps are 30pt at size 12 = 2.5x, inside _SAME_BASELINE_GAP_RATIO.
    assert len(paragraphs) == 1, [p.text for p in paragraphs]
    assert paragraphs[0].text == "alpha beta gamma"
    assert sorted(paragraphs[0].run_ids) == ["run-a", "run-b", "run-c"]


def test_upside_down_block_is_still_cell_split() -> None:
    """Invariant pin: 180 blocks must NOT join 90/270 in the cell-rule exemption.

    Exempting them would restore the pre-T16-2 composition for a handful of blocks at
    the cost of re-merging every genuinely separate upside-down label -- 84 blocks of
    the HVAC fixture, which is the exact bug T16-2 exists to remove.  Shape taken from
    that fixture (page index 6, block 5): two distinct 'Buffer Tank' equipment labels
    stacked on their own baselines.
    """
    runs = _rotate(
        [
            _span("run-a", 0, 0, (702.40, 100.0, 712.44, 106.0), "Buffer", 6.0),
            _span("run-b", 0, 1, (692.98, 100.0, 701.35, 106.0), "Tank", 6.0),
            _span("run-c", 1, 0, (662.50, 100.0, 672.54, 106.0), "Buffer", 6.0),
            _span("run-d", 1, 1, (653.08, 100.0, 661.45, 106.0), "Tank", 6.0),
        ],
        180,
    )

    paragraphs = tbp._build_paragraphs(0, runs)

    assert [p.text for p in paragraphs] == ["Buffer Tank", "Buffer Tank"], (
        "the two upside-down labels were re-merged into one paragraph"
    )
    assert [p.run_ids for p in paragraphs] == [
        ["run-a", "run-b"],
        ["run-c", "run-d"],
    ]


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


def _hvac_sibling_cell_tokens(model: PDFModel, label_run: EditableSpan) -> list[str]:
    """Texts of the label's raw-block siblings to its right: the other table cells.

    Read from the fixture rather than hardcoded so this file carries none of the
    drawing's project-identifying text.  None of them may share the label's paragraph.
    """
    tokens = [
        run.text
        for run in model.block_manager.get_runs(0)
        if run.block_idx == label_run.block_idx
        and run.span_id != label_run.span_id
        and run.bbox.x0 >= label_run.bbox.x1
        and len(run.text or "") >= 2
    ]
    assert len(tokens) >= 4, f"fixture changed: sibling cells {tokens!r}"
    return tokens


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
        for token in _hvac_sibling_cell_tokens(model, label_run):
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
        for token in _hvac_sibling_cell_tokens(model, label_run):
            assert token not in (hit.target_text or ""), (
                f"paragraph-mode hit swallowed sibling cell {token!r}: {hit.target_text!r}"
            )
        assert fitz.Rect(hit.target_bbox).x1 <= LABEL_CELL_X_LIMIT, (
            f"paragraph-mode target rect covers the whole table row: {tuple(hit.target_bbox)}"
        )
    finally:
        model.close()


# --------------------------------------------------------------------------
# Real-corpus regression: vertical blocks on the HVAC drawing sheets
# --------------------------------------------------------------------------

#: Pages (0-based) of the HVAC fixture that carry rotated drawing-sheet text.
VERTICAL_PAGES = (3, 4, 5, 17)


def _vertical_block_integrity_failures(model: PDFModel, page_idx: int) -> list[str]:
    """Every run of a 90/270 block must land in the same paragraph.

    Vertical blocks bypass the cell rules entirely, so ``_build_paragraphs`` must hand
    ``_merge_vertical_paragraphs`` exactly one paragraph per block.  That function may
    then union whole paragraphs together (pre-existing behaviour), but it can never
    split a block -- so run-to-paragraph membership is the invariant that survives the
    id churn a merge introduces.
    """
    by_block: dict[int, list[str]] = {}
    for run in model.block_manager.get_runs(page_idx):
        if run.rotation in (90, 270):
            by_block.setdefault(run.block_idx, []).append(run.span_id)

    failures: list[str] = []
    for block_idx, run_ids in sorted(by_block.items()):
        homes = set()
        for run_id in run_ids:
            para = model.block_manager.find_paragraph_for_run(page_idx, run_id)
            homes.add(para.paragraph_id if para is not None else None)
        if len(homes) > 1:
            failures.append(
                f"page {page_idx} block {block_idx} -> {sorted(map(str, homes))}"
            )
    return failures


def test_hvac_vertical_blocks_are_never_split_across_paragraphs() -> None:
    if not HVAC_FIXTURE.exists():
        pytest.skip(f"missing optional fixture: {HVAC_FIXTURE}")

    model = PDFModel()
    try:
        model.open_pdf(str(HVAC_FIXTURE))
        failures: list[str] = []
        for page_idx in VERTICAL_PAGES:
            model.ensure_page_index_built(page_idx + 1)
            failures.extend(_vertical_block_integrity_failures(model, page_idx))

        assert not failures, (
            f"{len(failures)} vertical block(s) shredded across paragraphs: "
            f"{failures[:10]}"
        )
    finally:
        model.close()


def test_hvac_vertical_label_does_not_absorb_a_neighbouring_block() -> None:
    """Fragmenting a vertical block feeds orphans to the vertical re-merge sweep.

    HVAC page index 17: block 168 is the label 'D17/D17/D7' and block 1188 is the
    unrelated equipment tag 'AHU 303'.  Splitting 1188 into 'AHU' + '303' let the
    greedy merge union 'AHU' into block 168's label and strand '303', so a
    paragraph-mode edit on 'D17' redacted a run from a different block.
    """
    if not HVAC_FIXTURE.exists():
        pytest.skip(f"missing optional fixture: {HVAC_FIXTURE}")

    model = PDFModel()
    try:
        model.open_pdf(str(HVAC_FIXTURE))
        model.ensure_page_index_built(18)
        para = model.block_manager.find_paragraph_for_run(17, "p17_b168_l0_s0")

        assert para is not None
        assert set(para.run_ids) == {
            "p17_b168_l0_s0",
            "p17_b168_l1_s0",
            "p17_b168_l2_s0",
        }, para.run_ids

        tag = model.block_manager.find_paragraph_for_run(17, "p17_b1188_l0_s0")
        assert tag is not None
        assert set(tag.run_ids) == {"p17_b1188_l0_s0", "p17_b1188_l1_s0"}, tag.run_ids
    finally:
        model.close()


# --------------------------------------------------------------------------
# F16-RTL-RESIDUAL: right-to-left table rows
# --------------------------------------------------------------------------
# A right-to-left run list is numbered in LOGICAL order (F15-RTL-ORDER), so on a
# pure Hebrew line consecutive runs step LEFT.  Rule (a) used to measure
# ``run.x0 - previous.x1`` (always negative there) and never cut an RTL row into
# cells, and rule (a2) / the group order sorted cells by ascending x.

_SHALOM = "שלום"
_OLAM = "עולם"
_BARUCH = "ברוך"
_HABA = "הבא"


def test_rtl_single_line_row_is_cut_into_cells_in_reading_order() -> None:
    """One Hebrew line holding two cells with a column gap: one paragraph per cell.

    Geometry from a synthetic htmlbox row (size 14): the gap between the cells is
    about 160 pt, the word gaps inside a cell are about 4 pt.  The right-hand cell is
    read first, so it is paragraph 0.
    """
    paragraphs = tbp._build_paragraphs(
        0,
        [
            _span("r0", 0, 0, (489.9, 115.0, 519.0, 129.0), _SHALOM, 14.0),
            _span("r1", 0, 1, (455.0, 115.0, 485.9, 129.0), _OLAM, 14.0),
            _span("r2", 0, 2, (271.5, 115.0, 296.7, 129.0), _BARUCH, 14.0),
            _span("r3", 0, 3, (243.9, 115.0, 267.5, 129.0), _HABA, 14.0),
        ],
    )

    assert [p.text for p in paragraphs] == [f"{_SHALOM} {_OLAM}", f"{_BARUCH} {_HABA}"]
    assert [p.run_ids for p in paragraphs] == [["r0", "r1"], ["r2", "r3"]]


def test_rtl_line_with_an_embedded_ltr_phrase_is_not_cut() -> None:
    """Logical neighbours of a bidi line are not visual neighbours.

    ``fox`` (logical 2) is followed by the Hebrew word at the far LEFT of the
    English phrase, 34 pt away: measuring gaps between logical neighbours would cut
    this ordinary sentence in two.  Gaps are measured between VISUAL neighbours.
    """
    paragraphs = tbp._build_paragraphs(
        0,
        [
            _span("h1", 0, 0, (480.0, 10.0, 510.0, 22.0), _SHALOM),
            _span("e1", 0, 1, (434.0, 10.0, 460.0, 22.0), "quick"),
            _span("e2", 0, 2, (464.0, 10.0, 476.0, 22.0), "fox"),
            _span("h2", 0, 3, (395.0, 10.0, 430.0, 22.0), _OLAM),
        ],
    )

    assert [p.text for p in paragraphs] == [f"{_SHALOM} quick fox {_OLAM}"]
    assert paragraphs[0].run_ids == ["h1", "e1", "e2", "h2"]


def test_mostly_ltr_row_with_one_hebrew_cell_keeps_left_to_right_order() -> None:
    """The right-to-left reading order is a block property, not a one-word property."""
    paragraphs = tbp._build_paragraphs(
        0,
        [
            _span("a", 0, 0, (10.0, 10.0, 50.0, 22.0), "Name"),
            _span("b", 0, 1, (200.0, 10.0, 230.0, 22.0), "Qty"),
            _span("c", 0, 2, (400.0, 10.0, 430.0, 22.0), _SHALOM),
        ],
    )

    assert [p.text for p in paragraphs] == ["Name", "Qty", _SHALOM]


@pytest.mark.parametrize("line_order", [(0, 1), (1, 0)])
def test_rtl_same_baseline_merge_reads_right_to_left_whatever_the_line_order(
    line_order: tuple[int, int],
) -> None:
    """Rule (a2) twin for Hebrew: a split RTL line is composed right cell first."""
    paragraphs = tbp._build_paragraphs(
        0,
        [
            _span("right", line_order[0], 0, (200.0, 10.0, 250.0, 22.0), _SHALOM),
            _span("left", line_order[1], 0, (130.0, 10.0, 180.0, 22.0), _OLAM),
        ],
    )

    # The gap is 20 pt at size 12 = 1.7x, inside _SAME_BASELINE_GAP_RATIO.
    assert [p.text for p in paragraphs] == [f"{_SHALOM} {_OLAM}"]
    assert sorted(paragraphs[0].run_ids) == ["left", "right"]


_RTL_ROW_A = f"{_SHALOM} {_OLAM}"
_RTL_ROW_B = f"{_BARUCH} {_HABA}"
_LTR_ROW_A = "Alpha beta"
_LTR_ROW_B = "Gamma delta"


def _make_gap_row_pdf(path: Path, first: str, second: str, rtl: bool) -> None:
    """ONE htmlbox line: cell, a wide em-space gap, cell (so MuPDF keeps it one line)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    direction = ' dir="rtl"' if rtl else ""
    page.insert_htmlbox(
        fitz.Rect(72, 100, 520, 130),
        f'<p{direction} style="font-size:14px">{first}{"&emsp;" * 12}{second}</p>',
    )
    doc.save(str(path), garbage=0)
    doc.close()


def _word_boxes(page: fitz.Page, words: list[str]) -> dict[str, list[tuple[float, ...]]]:
    return {
        word: [tuple(round(v, 1) for v in rect) for rect in page.search_for(word)]
        for word in words
    }


@pytest.mark.parametrize("rtl", [False, True], ids=["ltr-control", "rtl"])
def test_single_line_row_with_a_column_gap_is_cut_into_two_cells(
    tmp_path: Path, rtl: bool
) -> None:
    first, second = (_RTL_ROW_A, _RTL_ROW_B) if rtl else (_LTR_ROW_A, _LTR_ROW_B)
    path = tmp_path / "row.pdf"
    _make_gap_row_pdf(path, first, second, rtl)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        paragraphs = model.block_manager.get_paragraphs(0)

        # Compared without spaces: the index may still show a stray space inside the
        # final-letter word (open item in TODOS F16-RTL-RESIDUAL, run segmentation).
        texts = ["".join(p.text.split()) for p in paragraphs]
        assert texts == ["".join(first.split()), "".join(second.split())], (
            f"row is not cut into cells: {[p.text for p in paragraphs]!r}"
        )
        # Reading order: the right-hand cell comes first in a right-to-left row.
        left, right = sorted(paragraphs, key=lambda p: p.bbox.x0)
        assert left.bbox.x1 + 100.0 < right.bbox.x0
        assert paragraphs[0] is (right if rtl else left)
    finally:
        model.close()


@pytest.mark.parametrize("rtl", [False, True], ids=["ltr-control", "rtl"])
def test_paragraph_edit_of_one_cell_leaves_the_other_cell_in_place(
    tmp_path: Path, rtl: bool
) -> None:
    """Editing cell A of a single-line row must not rebuild cell B (moved +146 pt)."""
    first, second = (_RTL_ROW_A, _RTL_ROW_B) if rtl else (_LTR_ROW_A, _LTR_ROW_B)
    path = tmp_path / "row.pdf"
    _make_gap_row_pdf(path, first, second, rtl)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        model.set_text_target_mode("paragraph")
        # Cell A is the visual right-hand cell for RTL, the left one for LTR.
        click = fitz.Point(505, 122) if rtl else fitz.Point(80, 122)
        hit = model.get_text_info_at_point(1, click, allow_fallback=False)
        assert hit is not None, "no hit in cell A"
        assert second not in hit.target_text, f"hit spans both cells: {hit.target_text!r}"
        other_words = second.split()
        before = _word_boxes(model.doc[0], other_words)
        assert all(before.values()), f"fixture drifted: {before!r}"

        model.edit_text(
            1, fitz.Rect(hit.target_bbox), ("שלום עולמות" if rtl else "Alpha betas"),
            font="helv", size=float(hit.size), original_text=hit.target_text,
            target_span_id=hit.target_span_id, target_mode=hit.target_mode,
            allow_rebuild=True, confirm_fallback=lambda _c: True,
        )

        assert _word_boxes(model.doc[0], other_words) == before
    finally:
        model.close()
