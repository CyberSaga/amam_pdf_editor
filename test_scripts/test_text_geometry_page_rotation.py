"""RED: the model's public text-geometry surface speaks VISUAL (displayed) space.

Every rect/point the view exchanges with the model is in ``page.rect`` /
``page.get_pixmap()`` space (the scene is that space times the render
scale).  The block index is built from ``page.get_text("dict"/"rawdict")``,
which PyMuPDF reports in UNROTATED page space (docs/PITFALLS.md, "get_text
geometry is UNROTATED page space").  On a ``/Rotate 0`` page the two spaces
coincide, so nothing here can be observed there; every assertion below is
therefore run on quarter-turn (and 180) pages against a *pixmap ink* oracle,
never against ``rotation_matrix`` arithmetic (the fix would otherwise be its
own oracle).

Fixture shape mirrors the P3-D manual smoke fixture: one Helvetica ``Tj`` on
a 612x792 page, then ``/Rotate``.  The digits-only word keeps the ink centre
inside a single run and makes the commit replacement advance-neutral.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.geometry import unrotated_to_visual_rect  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import EditTextResult, derive_tier0_preview_target  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, TextCommitSettings  # noqa: E402

WORD = "2024"
REPLACEMENT = "2025"  # Helvetica digits share one advance: Tier 0 eligible


def _write_rotated_pdf(
    path: Path,
    rotation: int,
    text: str = WORD,
    *,
    td_y: int = 672,
    font_size: float = 12,
    upright_on_screen: bool = False,
    leading_run: str | None = None,
    leading_gap: int = 200,
) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    # PDF user space is y-up: 672 from the bottom == 120 pt from the top in
    # the (unrotated) dict space PyMuPDF reports.
    if upright_on_screen:
        # Drawing-sheet layout: the content is turned so the text reads
        # horizontally on screen; its UNROTATED bbox is then as wide as the
        # line is tall.
        tm = "0 -1 1 0" if rotation == 270 else "0 1 -1 0"
        if leading_run is not None:
            # A table row: another cell's run first, then ``text`` further
            # along the same line, so the block is wider than the edited run.
            ops = (
                f"BT /F1 {font_size} Tf {tm} 300 {td_y} Tm ({leading_run}) Tj "
                f"{leading_gap} 0 Td ({text}) Tj ET"
            )
        else:
            ops = f"BT /F1 {font_size} Tf {tm} 300 {td_y} Tm ({text}) Tj ET"
    else:
        ops = f"BT /F1 {font_size} Tf 72 {td_y} Td ({text}) Tj ET"
    doc.update_stream(content_xref, ops.encode("latin-1"))
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    page.set_rotation(rotation)
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _ink_bbox(page: fitz.Page) -> fitz.Rect:
    """Dark-pixel bounds of the rendered page at 72 dpi == visual points."""
    pix = page.get_pixmap(dpi=72)
    samples = bytes(pix.samples)
    n = pix.n
    xs: list[int] = []
    ys: list[int] = []
    for y in range(pix.height):
        row = y * pix.width
        for x in range(pix.width):
            if samples[(row + x) * n] < 200:
                xs.append(x)
                ys.append(y)
    assert xs, "fixture: no dark pixels rendered"
    return fitz.Rect(min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _centre(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)


def _assert_tight(rect: fitz.Rect, ink: fitz.Rect, margin: float = 4.0) -> None:
    """``rect`` must cover ``ink`` and not exceed it by more than ``margin``."""
    assert rect.x0 <= ink.x0 + 1.0 and rect.y0 <= ink.y0 + 1.0, (rect, ink)
    assert rect.x1 >= ink.x1 - 1.0 and rect.y1 >= ink.y1 - 1.0, (rect, ink)
    assert rect.x0 >= ink.x0 - margin and rect.y0 >= ink.y0 - margin, (rect, ink)
    assert rect.x1 <= ink.x1 + margin and rect.y1 <= ink.y1 + margin, (rect, ink)


@pytest.fixture()
def rotated_model(tmp_path, request):
    rotation = request.param
    path = _write_rotated_pdf(tmp_path / f"rot{rotation}.pdf", rotation)
    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", preview="plan", max_tier=0)
    )
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    assert model.doc[0].rotation == rotation
    try:
        yield model, rotation
    finally:
        model.close()


QUARTER = [90, 270]
ALL = [0, 90, 180, 270]


# ----------------------------------------------------------------- hit-test


@pytest.mark.parametrize("rotated_model", ALL, indirect=True)
def test_hit_test_accepts_visual_point_and_returns_visual_bbox(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    hit = model.get_text_info_at_point(1, _centre(ink), allow_fallback=False)

    assert hit is not None, f"visual ink centre {_centre(ink)} must hit the run"
    assert WORD in hit.target_text
    assert _centre(ink) in fitz.Rect(hit.target_bbox)
    _assert_tight(fitz.Rect(hit.target_bbox), ink)


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_hit_test_no_longer_accepts_unrotated_space_points(rotated_model) -> None:
    """Mutation pin: the OLD contract (dict-space point) must now miss."""
    model, _rotation = rotated_model
    dict_bbox = fitz.Rect(model.block_manager.get_runs(0)[0].bbox)
    ink = _ink_bbox(model.doc[0])
    assert _centre(dict_bbox) not in ink, "fixture: dict centre must lie off the ink"

    assert model.get_text_info_at_point(1, _centre(dict_bbox), allow_fallback=False) is None


@pytest.mark.parametrize("rotated_model", ALL, indirect=True)
def test_hit_rotation_is_the_on_screen_glyph_rotation(rotated_model) -> None:
    """Horizontal source text on a /Rotate page reads rotated on screen."""
    model, rotation = rotated_model
    hit = model.get_text_info_at_point(1, _centre(_ink_bbox(model.doc[0])), allow_fallback=False)
    assert hit is not None
    assert int(hit.rotation) == rotation


# ------------------------------------------------------------ outline source


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
@pytest.mark.parametrize("mode", ["run", "paragraph"])
def test_text_targets_for_outlines_are_visual(rotated_model, mode) -> None:
    model, rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    targets = model.get_text_targets(0, mode, blocks_fallback=True)

    assert targets, "one target expected"
    rects = [fitz.Rect(getattr(t, "bbox", None) or getattr(t, "rect")) for t in targets]
    assert any(_centre(ink) in r for r in rects), (rects, ink)
    _assert_tight(rects[0], ink)
    assert int(targets[0].rotation) == rotation
    blocks = model.get_text_blocks(0)
    assert blocks and _centre(ink) in fitz.Rect(blocks[0].rect)


# ------------------------------------------------------ selection surfaces


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_char_context_rects_are_visual(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])
    point = _centre(ink)

    context = model.get_char_context_at_point(1, point)

    assert context is not None, "visual ink centre must resolve a glyph"
    text, hit_index, rects = context
    assert text == WORD
    assert point in fitz.Rect(rects[hit_index])
    union = fitz.Rect(rects[0])
    for r in rects[1:]:
        union.include_rect(r)
    _assert_tight(union, ink)


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_selection_snapshot_and_lines_are_visual(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])
    around = fitz.Rect(ink.x0 - 2, ink.y0 - 2, ink.x1 + 2, ink.y1 + 2)

    text, bounds = model.get_text_selection_snapshot(1, around)
    assert WORD in text
    assert bounds is not None
    _assert_tight(fitz.Rect(bounds), ink)
    assert WORD in model.get_text_in_rect(1, around)

    hit = model.get_text_info_at_point(1, _centre(ink), allow_fallback=False)
    assert hit is not None
    lines_text, line_rects = model.get_text_selection_lines(
        1,
        hit.target_span_id,
        fitz.Point(ink.x1 - 0.5, ink.y1 - 0.5),
        start_point=fitz.Point(ink.x0 + 0.5, ink.y0 + 0.5),
    )
    assert WORD in lines_text
    assert line_rects
    union = fitz.Rect(line_rects[0])
    for r in line_rects[1:]:
        union.include_rect(r)
    _assert_tight(union, ink)

    from_run_text, from_run_bounds = model.get_text_selection_snapshot_from_run(
        1, hit.target_span_id, fitz.Point(ink.x1 - 0.5, ink.y1 - 0.5)
    )
    assert WORD in from_run_text
    assert from_run_bounds is not None and _centre(ink) in fitz.Rect(from_run_bounds)


# ------------------------------------------------------------- write side


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_edit_text_from_visual_hit_commits_at_tier0(rotated_model) -> None:
    """The smoke gate: a click-derived edit on a rotated page is plan-backed."""
    model, _rotation = rotated_model
    ink_before = _ink_bbox(model.doc[0])
    hit = model.get_text_info_at_point(1, _centre(ink_before), allow_fallback=False)
    assert hit is not None

    result = model.edit_text(
        1,
        fitz.Rect(hit.target_bbox),
        REPLACEMENT,
        font=hit.font,
        size=float(hit.size),
        color=tuple(hit.color),
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
    )

    assert result is EditTextResult.SUCCESS, result
    outcome = model.last_commit_outcome
    assert outcome is not None
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH, outcome
    assert outcome.fallback_chain == (), outcome
    assert REPLACEMENT in model.doc[0].get_text("text")
    ink_after = _ink_bbox(model.doc[0])
    assert abs(ink_after.x0 - ink_before.x0) <= 3 and abs(ink_after.y0 - ink_before.y0) <= 3


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_edit_text_resolves_a_visual_rect_without_span_id(rotated_model) -> None:
    """``rect`` alone (no span id) must find the run: the write side derotates."""
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    result = model.edit_text(
        1,
        fitz.Rect(ink),
        REPLACEMENT,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=WORD,
        target_span_id=None,
        target_mode="run",
    )

    assert result is EditTextResult.SUCCESS, result
    assert REPLACEMENT in model.doc[0].get_text("text")


@pytest.mark.parametrize("rotation", QUARTER)
def test_legacy_edit_keeps_place_when_source_sits_near_the_unrotated_bottom(
    tmp_path, rotation
) -> None:
    """The legacy engine's page-bounds clamps must use the UNROTATED page
    bounds: on a quarter-turn page ``page.rect`` has swapped dimensions, so a
    run whose unrotated y exceeds the displayed height was clamped into a
    degenerate insert rect and re-inserted at the page origin.

    ``new_rect`` (the unchanged displayed bbox) forces the htmlbox path,
    which is the one that clamps; the fast ``insert_text`` path does not."""
    path = _write_rotated_pdf(tmp_path / f"legacy{rotation}.pdf", rotation, td_y=100)
    # The subject is the legacy engine.  It was the default when this test
    # was written; since T16-3 the default is tiered, and since UI step 7 a
    # tiered refusal no longer falls back to legacy silently -- select it.
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        ink_before = _ink_bbox(model.doc[0])
        hit = model.get_text_info_at_point(1, _centre(ink_before), allow_fallback=False)
        assert hit is not None

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            new_rect=fitz.Rect(hit.target_bbox),
        )

        assert result is EditTextResult.SUCCESS, result
        assert REPLACEMENT in model.doc[0].get_text("text")
        ink_after = _ink_bbox(model.doc[0])
        assert abs(ink_after.x0 - ink_before.x0) <= 6 and abs(ink_after.y0 - ink_before.y0) <= 6, (
            ink_before,
            ink_after,
        )
    finally:
        model.close()


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_legacy_edit_keeps_place_on_a_rotated_page_with_an_offset_cropbox(
    tmp_path, rotation
) -> None:
    """F15-G4: PyMuPDF's htmlbox places through ``page.transformation_matrix``,
    which drops the CropBox origin once ``/Rotate != 0``, so the legacy
    rebuild drew its text 30-40 pt off the run it replaced (and the edit's
    own verification then rolled it back). Same edit as the test above on a
    page whose CropBox does not start at the MediaBox origin."""
    plain = _write_rotated_pdf(tmp_path / f"crop_src{rotation}.pdf", rotation, td_y=100)
    path = tmp_path / f"crop{rotation}.pdf"
    doc = fitz.open(str(plain))
    doc.xref_set_key(doc[0].xref, "CropBox", "[30 40 580 760]")
    doc.save(str(path), garbage=0)
    doc.close()
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        ink_before = _ink_bbox(model.doc[0])
        hit = model.get_text_info_at_point(1, _centre(ink_before), allow_fallback=False)
        assert hit is not None

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            new_rect=fitz.Rect(hit.target_bbox),
        )

        assert result is EditTextResult.SUCCESS, result
        assert REPLACEMENT in model.doc[0].get_text("text")
        assert WORD not in model.doc[0].get_text("text")
        ink_after = _ink_bbox(model.doc[0])
        assert abs(ink_after.x0 - ink_before.x0) <= 6 and abs(ink_after.y0 - ink_before.y0) <= 6, (
            ink_before,
            ink_after,
        )
    finally:
        model.close()


@pytest.mark.parametrize("user_unit", [2.0, 0.5])
@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_legacy_edit_keeps_place_on_a_rotated_user_unit_page(tmp_path, rotation, user_unit) -> None:
    """F15-G1-UU-ROT: on a rotated ``/UserUnit != 1`` page PyMuPDF's htmlbox page
    matrix drops the scale and ``derotation_matrix`` sizes the quarter turn from
    the unscaled box, so the legacy rebuild drew its text ``UserUnit`` times too
    large and too far from the run it replaced. Same edit as the offset-CropBox
    test above; the MediaBox is cut so the displayed page is still 612 x 792."""
    plain = _write_rotated_pdf(tmp_path / f"uu_src{rotation}.pdf", rotation, td_y=100)
    path = tmp_path / f"uu{rotation}.pdf"
    doc = fitz.open(str(plain))
    doc.xref_set_key(doc[0].xref, "MediaBox", "[0 0 %g %g]" % (612 / user_unit, 792 / user_unit))
    doc.xref_set_key(doc[0].xref, "UserUnit", f"{user_unit:g}")
    doc.save(str(path), garbage=0)
    doc.close()
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        ink_before = _ink_bbox(model.doc[0])
        hit = model.get_text_info_at_point(1, _centre(ink_before), allow_fallback=False)
        assert hit is not None

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            new_rect=fitz.Rect(hit.target_bbox),
        )

        assert result is EditTextResult.SUCCESS, result
        assert REPLACEMENT in model.doc[0].get_text("text")
        assert WORD not in model.doc[0].get_text("text")
        ink_after = _ink_bbox(model.doc[0])
        assert abs(ink_after.x0 - ink_before.x0) <= 6 and abs(ink_after.y0 - ink_before.y0) <= 6, (
            ink_before,
            ink_after,
        )
        assert abs(ink_after.width - ink_before.width) <= 6, (ink_before, ink_after)
    finally:
        model.close()


@pytest.mark.parametrize(
    ("font_size", "shift", "want"),
    [
        (3.75, 40.0, 40.0),
        (4.9, 40.0, 40.0),
        (12.0, 40.0, 40.0),
        # guard: a drop entirely past the page edge still falls back in place
        (3.75, 5000.0, 0.0),
    ],
    ids=["tiny_line", "just_under_5pt", "normal_line", "off_page_falls_back"],
)
@pytest.mark.parametrize("rotation", [90, 270])
def test_legacy_move_of_a_short_line_lands_at_the_dropped_place(
    tmp_path, rotation, font_size, shift, want
) -> None:
    """E2E3-1: the legacy ``new_rect`` apply tested ``clamped_new.width < 5`` on
    the UNROTATED rect.  On a quarter-turn page that width is the VISUAL line
    height, so every line under 5 pt tall (most of a drawing sheet) was treated
    as clamped-to-nothing and silently rebuilt at its old spot."""
    path = _write_rotated_pdf(
        tmp_path / f"move{rotation}.pdf",
        rotation,
        td_y=400,
        font_size=font_size,
        upright_on_screen=True,
    )
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        page = model.doc[0]
        words = page.get_text("words")
        assert words
        before = unrotated_to_visual_rect(page, fitz.Rect(words[0][:4]))
        hit = model.get_text_info_at_point(1, _centre(before), allow_fallback=False)
        assert hit is not None
        moved = fitz.Rect(hit.target_bbox)
        moved.x0 += shift
        moved.x1 += shift

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            new_rect=moved,
        )

        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        landed = [
            unrotated_to_visual_rect(page, fitz.Rect(w[:4]))
            for w in page.get_text("words")
            if w[4] == REPLACEMENT
        ]
        assert landed, page.get_text("text")
        dx = landed[0].x0 - before.x0
        assert abs(dx - want) <= 6.0, f"moved {dx:.2f} pt, wanted {want} (size {font_size})"
    finally:
        model.close()


@pytest.mark.parametrize("mode", ["unmoved_rect", "no_rect"])
@pytest.mark.parametrize("rotation", [90, 270])
def test_legacy_rebuild_of_quarter_turn_drawing_text_keeps_its_place(
    tmp_path, rotation, mode
) -> None:
    """ROT90-UP-1: the legacy vertical branch built ``insert_rect`` from the
    run's top edge down to the page bottom and anchored the first line at the
    right edge.  That only fits text reading DOWN the unrotated page (/Rotate
    270 drawing layout); text reading UP (``dir (0,-1)``, /Rotate 90 layout)
    starts at the BOTTOM of the htmlbox and its first line sits at the LEFT, so
    an unmoved one-character edit landed at the unrotated page bottom (visual
    left edge on /Rotate 90, ~400 pt away).  Oracle: where the replaced word
    lands on screen, from ``get_text("words")``, against where the original
    one was -- same start, same line."""
    path = _write_rotated_pdf(
        tmp_path / f"keep{rotation}.pdf", rotation, td_y=400, upright_on_screen=True
    )
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        page = model.doc[0]
        before = unrotated_to_visual_rect(page, fitz.Rect(page.get_text("words")[0][:4]))
        hit = model.get_text_info_at_point(1, _centre(before), allow_fallback=False)
        assert hit is not None

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            new_rect=fitz.Rect(hit.target_bbox) if mode == "unmoved_rect" else None,
        )

        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        landed = [
            unrotated_to_visual_rect(page, fitz.Rect(w[:4]))
            for w in page.get_text("words")
            if w[4] == REPLACEMENT
        ]
        assert len(landed) == 1, page.get_text("text")
        assert abs(landed[0].x0 - before.x0) <= 4.0, (before, landed[0])
        assert abs(_centre(landed[0]).y - _centre(before).y) <= 4.0, (before, landed[0])
        # full size: the line height came from the unrotated bbox HEIGHT (the text
        # length), so a tight rect shrank the whole run to ~43 %
        assert abs(landed[0].width - before.width) <= 2.0, (before, landed[0])
    finally:
        model.close()


@pytest.mark.parametrize("mode", ["no_rect", "unmoved_rect", "off_page_drag"])
@pytest.mark.parametrize("rotation", [90, 270])
def test_legacy_rebuild_of_quarter_turn_run_in_a_multi_run_block_keeps_its_place(
    tmp_path, rotation, mode
) -> None:
    """F13-VF-1: a quarter-turn table row is ONE PyMuPDF block holding several
    cells' runs.  The legacy vertical branch without ``new_rect`` sized the
    htmlbox from the BLOCK's layout rect instead of the run's reopen anchor,
    so the rebuilt run started at the block's first cell (~200 pt away, over
    the neighbour's text) and the edited cell was left empty.  The drag
    fallback (``new_rect`` clamped to nothing -> "back in place") had the same
    block-for-run substitution.  ROT90-UP-1's fixture has one run per page
    (block == run) and could not see it.  Oracle: where the replaced word
    lands on screen against where it was, and the neighbour run untouched."""
    lead = "ABCD"
    path = _write_rotated_pdf(
        tmp_path / f"row{rotation}.pdf",
        rotation,
        # the edited run sits at unrotated y 400 for both directions
        td_y=200 if rotation == 90 else 600,
        upright_on_screen=True,
        leading_run=lead,
        leading_gap=200,
    )
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        page = model.doc[0]
        blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
        # fixture precondition: one block, two runs, block much longer than the run
        assert len(blocks) == 1, blocks
        spans = [s for line in blocks[0]["lines"] for s in line["spans"]]
        assert [s["text"] for s in spans] == [lead, WORD], spans
        assert fitz.Rect(blocks[0]["bbox"]).height > 3 * fitz.Rect(spans[1]["bbox"]).height

        def _visual_word(pg: fitz.Page, text: str) -> list[fitz.Rect]:
            return [
                unrotated_to_visual_rect(pg, fitz.Rect(w[:4]))
                for w in pg.get_text("words")
                if w[4] == text
            ]

        before = _visual_word(page, WORD)[0]
        lead_before = _visual_word(page, lead)[0]
        hit = model.get_text_info_at_point(1, _centre(before), allow_fallback=False)
        assert hit is not None and hit.target_text == WORD, hit

        new_rect: fitz.Rect | None = None
        if mode == "unmoved_rect":
            new_rect = fitz.Rect(hit.target_bbox)
        elif mode == "off_page_drag":
            new_rect = fitz.Rect(hit.target_bbox)
            new_rect.x0 += 5000.0
            new_rect.x1 += 5000.0

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            new_rect=new_rect,
        )

        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        landed = _visual_word(page, REPLACEMENT)
        assert len(landed) == 1, page.get_text("text")
        assert abs(landed[0].x0 - before.x0) <= 4.0, (before, landed[0])
        assert abs(_centre(landed[0]).y - _centre(before).y) <= 4.0, (before, landed[0])
        assert abs(landed[0].width - before.width) <= 2.0, (before, landed[0])
        # the neighbour cell keeps its text and place, and nothing overprints it
        lead_after = _visual_word(page, lead)
        assert len(lead_after) == 1, page.get_text("text")
        assert abs(lead_after[0].x0 - lead_before.x0) <= 1.0, (lead_before, lead_after[0])
        assert abs(lead_after[0].y0 - lead_before.y0) <= 1.0, (lead_before, lead_after[0])
        assert not landed[0].intersects(lead_before), (landed[0], lead_before)
    finally:
        model.close()


@pytest.mark.parametrize("rotated_model", QUARTER, indirect=True)
def test_preview_target_derives_from_visual_rect_without_span_id(rotated_model) -> None:
    model, _rotation = rotated_model
    ink = _ink_bbox(model.doc[0])

    target = derive_tier0_preview_target(
        model,
        page_num=1,
        rect=fitz.Rect(ink),
        original_text=WORD,
        target_span_id=None,
        target_mode="run",
    )

    assert target is not None
    assert target.text == WORD
    _assert_tight(fitz.Rect(target.bbox), ink)



# ------------------------------------------- upright text on a /Rotate 180 page
#
# GATE16-1: text that reads upright on a /Rotate 180 page is drawn upside down
# in unrotated space (text matrix ``-1 0 0 -1``), so its stext line direction is
# exactly (-1, 0).  PyMuPDF 1.27's ``JM_char_quad`` treats every such line as a
# LEFT-RIGHT MIRROR once ``small_glyph_heights`` is on (the app's production
# flag, set by ``PDFModel.__init__``): the fontsize-tall char box is put on the
# wrong side of the baseline, about 0.64 em off the ink.  Every assertion below
# runs under that production flag against a pixmap-ink oracle.

UPRIGHT_180_GEOMETRIES = {
    "plain": ((0, 0, 612, 792), None),
    "crop": ((0, 0, 612, 792), (30, 40, 580, 760)),
    "negmb": ((-100, -200, 512, 592), None),
}
UPRIGHT_180_SIZE = 20.0


def _write_upright_180_pdf(
    path: Path,
    geometry: str,
    *,
    lines: tuple[str, ...] = (WORD,),
    leading: float = 1.2,
    tm: str = "-1 0 0 -1",
    rotation: int = 180,
) -> Path:
    mediabox, cropbox = UPRIGHT_180_GEOMETRIES[geometry]
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % cropbox)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    size = UPRIGHT_180_SIZE
    ops = []
    for index, text in enumerate(lines):
        # Each following line sits ``leading`` em lower ON SCREEN, i.e. higher
        # in PDF user space once the page is turned 180 degrees.
        y = 500 + index * leading * size
        ops.append(f"BT /F1 {size:g} Tf {tm} 400 {y:g} Tm ({text}) Tj ET")
    doc.update_stream(content_xref, "\n".join(ops).encode("latin-1"))
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    doc.xref_set_key(page.xref, "Rotate", str(rotation))
    doc.save(str(path), garbage=0)
    doc.close()
    return path


@pytest.fixture()
def upright_180_model(tmp_path, request):
    geometry = request.param
    path = _write_upright_180_pdf(tmp_path / f"upright180_{geometry}.pdf", geometry)
    model = PDFModel()
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    assert model.doc[0].rotation == 180
    assert bool(fitz.TOOLS.set_small_glyph_heights()) is True  # the production flag
    try:
        yield model
    finally:
        model.close()


def _union(rects: list[fitz.Rect]) -> fitz.Rect:
    union = fitz.Rect(rects[0])
    for rect in rects[1:]:
        union |= rect
    return union


@pytest.mark.parametrize("upright_180_model", list(UPRIGHT_180_GEOMETRIES), indirect=True)
def test_upright_180_index_run_box_covers_its_ink(upright_180_model) -> None:
    model = upright_180_model
    page = model.doc[0]
    ink = _ink_bbox(page)
    runs = model.block_manager.get_runs(0)
    assert [run.text for run in runs] == [WORD], [run.text for run in runs]
    _assert_tight(unrotated_to_visual_rect(page, fitz.Rect(runs[0].bbox)), ink)


@pytest.mark.parametrize("upright_180_model", list(UPRIGHT_180_GEOMETRIES), indirect=True)
def test_upright_180_click_on_the_ink_hits_the_run(upright_180_model) -> None:
    model = upright_180_model
    ink = _ink_bbox(model.doc[0])
    centre = _centre(ink)
    for point in (centre, fitz.Point(centre.x, ink.y0 + 1.0), fitz.Point(centre.x, ink.y1 - 1.0)):
        hit = model.get_text_info_at_point(1, point, allow_fallback=False)
        assert hit is not None, f"visual ink point {point} (ink {ink}) must hit the run"
        assert hit.target_text == WORD
        _assert_tight(fitz.Rect(hit.target_bbox), ink)


@pytest.mark.parametrize("upright_180_model", list(UPRIGHT_180_GEOMETRIES), indirect=True)
def test_upright_180_content_words_cover_their_ink(upright_180_model) -> None:
    from model.page_content_text import content_text

    page = upright_180_model.doc[0]
    ink = _ink_bbox(page)
    words = [w for w in content_text(page, "words") if w[4] == WORD]
    assert len(words) == 1, words
    _assert_tight(unrotated_to_visual_rect(page, fitz.Rect(words[0][:4])), ink)


@pytest.mark.parametrize("upright_180_model", list(UPRIGHT_180_GEOMETRIES), indirect=True)
def test_upright_180_engine_rawdict_chars_sit_on_their_ink(upright_180_model) -> None:
    """The text-commit engine's glyph boxes (neighbour wall, overprint guard,
    growth zone) come from ``PageInterpretation.rawdict``: they must agree with
    the index box, i.e. lie on the ink, not 0.64 em beside it."""
    from model.text_commit.interpretation import interpret_page

    page = upright_180_model.doc[0]
    ink = _ink_bbox(page)
    interpretation = interpret_page(page)
    try:
        rawdict = interpretation.rawdict()
    finally:
        interpretation.release()
    boxes = [
        fitz.Rect(char["bbox"])
        for block in rawdict["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
        for char in span["chars"]
        if char["c"].strip()
    ]
    assert len(boxes) == len(WORD), boxes
    _assert_tight(unrotated_to_visual_rect(page, _union(boxes)), ink)


@pytest.mark.parametrize("upright_180_model", list(UPRIGHT_180_GEOMETRIES), indirect=True)
def test_upright_180_search_hit_covers_its_ink(upright_180_model) -> None:
    from model.tools.search_tool import SearchTool

    page = upright_180_model.doc[0]
    ink = _ink_bbox(page)
    hits = SearchTool.search_page_in_doc(upright_180_model.doc, 1, WORD)
    assert len(hits) == 1, hits
    _assert_tight(unrotated_to_visual_rect(page, fitz.Rect(hits[0][2])), ink)


def test_text_commit_verify_reads_glyph_boxes_through_the_upright_helper() -> None:
    """Bug-class guard: ``verify.py`` must not read dict/rawdict glyph boxes
    straight from ``page.get_text`` -- on upright text of a /Rotate 180 page
    those are mirrored off the ink under the production flag.  Use
    ``model.page_content_text.visible_text`` (or the corrected interpretation)."""
    import re

    root = Path(__file__).resolve().parents[1]
    source = (root / "model" / "text_commit" / "verify.py").read_text(encoding="utf-8")
    pattern = re.compile(r"""\.get_text\(\s*["'](raw)?dict["']""")
    offenders = [
        f"verify.py:{lineno}: {raw.strip()}"
        for lineno, raw in enumerate(source.splitlines(), 1)
        if pattern.search(raw.split("#", 1)[0])
    ]
    assert not offenders, "\n".join(offenders)


def test_mirrored_text_box_stays_on_its_ink_guard(tmp_path) -> None:
    """Over-correction guard (passes before GATE16-1 too): a true left-right
    mirror (``-1 0 0 1``) has the same (-1, 0) line direction but upright
    glyphs; its PyMuPDF box is right and must not be reflected."""
    path = _write_upright_180_pdf(tmp_path / "mirror.pdf", "plain", tm="-1 0 0 1", rotation=0)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        page = model.doc[0]
        ink = _ink_bbox(page)
        runs = model.block_manager.get_runs(0)
        assert len(runs) == 1, [run.text for run in runs]
        _assert_tight(unrotated_to_visual_rect(page, fitz.Rect(runs[0].bbox)), ink)
    finally:
        model.close()


@pytest.mark.parametrize("geometry", list(UPRIGHT_180_GEOMETRIES))
def test_upright_180_edit_keeps_the_line_below_and_lands_on_the_old_ink(tmp_path, geometry) -> None:
    """End to end: click the upright 180 line, replace it; the new text sits
    where the old ink was and the line 1.2 em below it is untouched."""
    below = "7777"
    path = _write_upright_180_pdf(tmp_path / f"edit180_{geometry}.pdf", geometry, lines=(WORD, below))
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        page = model.doc[0]
        ink_all = _ink_bbox(page)
        # The edited line is the upper one on screen; the other starts 1.2 em lower.
        top_ink = fitz.Rect(ink_all.x0, ink_all.y0, ink_all.x1, ink_all.y0 + UPRIGHT_180_SIZE * 0.7)
        below_clip = fitz.Rect(
            ink_all.x0 - 2, ink_all.y0 + UPRIGHT_180_SIZE * 1.0, ink_all.x1 + 2, ink_all.y1 + 2
        )
        below_before = bytes(page.get_pixmap(dpi=72, clip=below_clip).samples)
        hit = model.get_text_info_at_point(1, _centre(top_ink), allow_fallback=False)
        assert hit is not None and hit.target_text == WORD, (hit, top_ink)

        result = model.edit_text(
            1,
            fitz.Rect(hit.target_bbox),
            REPLACEMENT,
            font=hit.font,
            size=float(hit.size),
            color=tuple(hit.color),
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )

        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        text = page.get_text("text")
        assert REPLACEMENT in text and below in text and WORD not in text, text
        assert bytes(page.get_pixmap(dpi=72, clip=below_clip).samples) == below_before
        ink_after = _ink_bbox(page)
        assert abs(ink_after.y0 - ink_all.y0) <= 2.0 and abs(ink_after.x0 - ink_all.x0) <= 3.0, (
            ink_after,
            ink_all,
        )
    finally:
        model.close()


@pytest.mark.parametrize("small_glyph_heights", [True, False])
@pytest.mark.parametrize("geometry", list(UPRIGHT_180_GEOMETRIES))
def test_upright_180_content_boxes_cover_the_ink_under_either_flag(
    tmp_path, geometry, small_glyph_heights
) -> None:
    """Guard: the correction keys on PyMuPDF's reported quad, not on the flag.
    With the flag off PyMuPDF keeps MuPDF's (right, font-bbox tall) quad and
    nothing may be reflected; with it on the mirrored box must be reflected."""
    from model.page_content_text import content_text

    path = _write_upright_180_pdf(tmp_path / f"flag_{geometry}.pdf", geometry)
    prior = bool(fitz.TOOLS.set_small_glyph_heights())
    doc = fitz.open(str(path))
    try:
        fitz.TOOLS.set_small_glyph_heights(small_glyph_heights)
        page = doc[0]
        ink = _ink_bbox(page)
        for option in ("dict", "rawdict"):
            spans = [
                span
                for block in content_text(page, option)["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
            ]
            assert len(spans) == 1, spans
            box = unrotated_to_visual_rect(page, fitz.Rect(spans[0]["bbox"]))
            margin = 4.0 if small_glyph_heights else UPRIGHT_180_SIZE * 0.45
            _assert_tight(box, ink, margin=margin)
    finally:
        fitz.TOOLS.set_small_glyph_heights(prior)
        doc.close()
