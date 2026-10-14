"""Targeted overlap-edit regression tests."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.edit_commands import EditTextCommand
from model.pdf_model import EditTextResult, PDFModel
from model.text_commit.dto import CommitTier, TextCommitSettings
from model.text_edit_refusal import TextEditRefusal, TextEditRefused


def _accept_rebuild(_chain: tuple[str, ...]) -> bool:
    """UI step 7 (no silent legacy): explicit rebuild consent stub.  The
    tests that use it exercise the rebuild (legacy redact+reinsert) path, which
    a tiered refusal now reaches only with ``allow_rebuild=True`` plus an
    accepting confirm -- the same path they ran before, now consented."""
    return True


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def _make_pdf_exact_overlap(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect = fitz.Rect(120, 140, 320, 180)
    page.insert_textbox(rect, "BOTTOM_KEEP", fontsize=14, fontname="helv", color=(0, 0, 0))
    page.insert_textbox(rect, "TOP_EDIT", fontsize=14, fontname="helv", color=(1, 0, 0))
    doc.save(path)
    doc.close()


def _make_pdf_partial_overlap(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(110, 240, 285, 280),
        "LEFT_KEEP",
        fontsize=12,
        fontname="helv",
        color=(0, 0, 0),
    )
    page.insert_textbox(
        fitz.Rect(210, 250, 380, 290),
        "RIGHT_EDIT",
        fontsize=12,
        fontname="helv",
        color=(0.2, 0.0, 0.7),
    )
    doc.save(path)
    doc.close()


def _make_pdf_vertical_overlap(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    point = fitz.Point(280, 560)
    page.insert_text(point, "VERT_KEEP", fontsize=14, fontname="helv", color=(0, 0, 0), rotate=90)
    page.insert_text(point, "VERT_EDIT", fontsize=14, fontname="helv", color=(1, 0, 0), rotate=90)
    doc.save(path)
    doc.close()


def _assert_contains(page_text: str, token: str) -> None:
    assert _norm(token) in _norm(page_text), (
        f"missing token: {token!r}; page_text={page_text!r}"
    )


def _first_span_with(model: PDFModel, page_idx: int, token: str):
    model.ensure_page_index_built(page_idx + 1)
    probe = _norm(token)
    for span in model.block_manager.get_spans(page_idx):
        if probe in _norm(span.text):
            return span
    return None


def _center(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def test_exact_overlap_edit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "exact_overlap.pdf"
        _make_pdf_exact_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            target = _first_span_with(model, 0, "TOP_EDIT")
            assert target is not None

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="TOP_EDIT_DONE",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "BOTTOM_KEEP")
            _assert_contains(page_text, "TOP_EDIT_DONE")
        finally:
            model.close()


def test_partial_overlap_edit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "partial_overlap.pdf"
        _make_pdf_partial_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            target = _first_span_with(model, 0, "RIGHT_EDIT")
            assert target is not None

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="RIGHT_DONE",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "LEFT_KEEP")
            _assert_contains(page_text, "RIGHT_DONE")
        finally:
            model.close()


def test_overlap_undo_redo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "undo_redo_overlap.pdf"
        _make_pdf_exact_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            target = _first_span_with(model, 0, "TOP_EDIT")
            assert target is not None

            snapshot = model._capture_page_snapshot(0)
            cmd = EditTextCommand(
                model=model,
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="TOP_CMD_EDIT",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                vertical_shift_left=True,
                page_snapshot_bytes=snapshot,
                old_block_id=target.span_id,
                old_block_text=target.text,
                new_rect=None,
                target_span_id=target.span_id,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )
            model.command_manager.execute(cmd)

            t1 = model.doc[0].get_text("text")
            _assert_contains(t1, "BOTTOM_KEEP")
            _assert_contains(t1, "TOP_CMD_EDIT")

            model.command_manager.undo()
            t2 = model.doc[0].get_text("text")
            _assert_contains(t2, "BOTTOM_KEEP")
            _assert_contains(t2, "TOP_EDIT")

            model.command_manager.redo()
            t3 = model.doc[0].get_text("text")
            _assert_contains(t3, "BOTTOM_KEEP")
            _assert_contains(t3, "TOP_CMD_EDIT")
        finally:
            model.close()


def test_vertical_overlap_edit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "vertical_overlap.pdf"
        _make_pdf_vertical_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            target = _first_span_with(model, 0, "VERT_EDIT")
            assert target is not None

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="VERT_DONE",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "VERT_KEEP")
            _assert_contains(page_text, "VERT_DONE")
        finally:
            model.close()


def test_overlap_replay_with_unavailable_font_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "font_fallback_overlap.pdf"
        _make_pdf_exact_overlap(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            spans = model.block_manager.get_spans(0)
            assert len(spans) >= 2

            keep_span = _first_span_with(model, 0, "BOTTOM_KEEP")
            target = _first_span_with(model, 0, "TOP_EDIT")
            assert keep_span is not None and target is not None

            # Simulate extracted embedded/subset font names that are not directly insertable.
            keep_span.font = "ABCDEF+NoSuchEmbeddedFont-Regular"

            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="TOP_EDIT_FALLBACK",
                font=target.font,
                size=max(8, int(round(target.size))),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )

            page_text = model.doc[0].get_text("text")
            _assert_contains(page_text, "BOTTOM_KEEP")
            _assert_contains(page_text, "TOP_EDIT_FALLBACK")
        finally:
            model.close()



# ── F13-VF-2: the rebuild redaction erased untouched words outside the cluster ──
# The overlap cluster is every run touching the TARGET's box.  The redaction
# used the cluster's bounding box, an L-shaped union here ("ASIAN" sits above
# and to the right of "severe"), so it cut the tail of "So-called" (line
# above) and the head of "health" (same line): neither is in the cluster, so
# neither was replayed or checked, and the edit reported SUCCESS.


def _make_pdf_l_shaped_cluster(path: Path, *, foreign_glyph: bool = False) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 100), "So-called", fontsize=12, fontname="helv")
    # Taller font: its box reaches ~0.7 pt into the target's line.
    page.insert_text((100, 100), "ASIAN", fontsize=22, fontname="helv")
    page.insert_text((80, 113.47), "severe", fontsize=12, fontname="helv")
    page.insert_text((125, 113.47), "health", fontsize=12, fontname="helv")
    if foreign_glyph:
        # A big glyph over the first glyph of the replayed neighbour "ASIAN"
        # but clear of the target's box: not in the cluster, and the glyph
        # MuPDF has to erase to remove "A" overlaps it.
        page.insert_text((96, 92), "W", fontsize=30, fontname="helv")
    doc.save(path)
    doc.close()


def _words(page: fitz.Page) -> list[tuple[str, float, float]]:
    return sorted((w[4], round(w[0], 1), round(w[1], 1)) for w in page.get_text("words"))


def _l_shaped_precondition(model: PDFModel):
    """The target run and the sorted texts of its overlap cluster; asserts
    that "So-called" and "health" are outside the cluster but inside its
    bounding box (the finding's geometry)."""
    model.ensure_page_index_built(1)
    runs = {r.text: r for r in model.block_manager.get_runs(0)}
    target = runs["severe"]
    cluster = model.block_manager.find_overlapping_runs(0, fitz.Rect(target.bbox), tol=0.5)
    names = sorted(r.text for r in cluster)
    union = fitz.Rect(target.bbox)
    for run in cluster:
        union |= fitz.Rect(run.bbox)
    for outsider in ("So-called", "health"):
        assert outsider not in names, names
        assert fitz.Rect(runs[outsider].bbox).intersects(union), outsider
    return target, names


def _clip_pixels(page: fitz.Page, rect: fitz.Rect) -> bytes:
    return page.get_pixmap(dpi=144, clip=rect, alpha=False).samples


def test_rebuild_keeps_untouched_words_inside_the_cluster_bounding_box(
    tmp_path: Path,
) -> None:
    # The legacy engine forces the redact + reinsert rebuild; the tiered
    # engine commits this simple Helvetica edit at Tier 0 (no redaction).
    path = tmp_path / "l_shaped_cluster.pdf"
    _make_pdf_l_shaped_cluster(path)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        model.open_pdf(str(path))
        target, names = _l_shaped_precondition(model)
        assert names == ["ASIAN", "severe"], names
        page = model.doc[0]
        words_before = _words(page)
        keep = {w[4]: fitz.Rect(w[:4]) for w in page.get_text("words")}
        pixels_before = {k: _clip_pixels(page, keep[k]) for k in ("So-called", "health")}

        result = model.edit_text(
            page_num=1,
            rect=fitz.Rect(target.bbox),
            new_text="esvere",
            font=target.font,
            size=float(target.size),
            color=target.color,
            original_text=target.text,
            target_span_id=target.span_id,
            allow_rebuild=True,
            confirm_fallback=_accept_rebuild,
        )
        assert result == EditTextResult.SUCCESS
        assert model.last_commit_outcome is not None
        # The rebuild (redact + reinsert) ran: that is the path under test.
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY

        page = model.doc[0]
        words_after = _words(page)
        texts_after = [w[0] for w in words_after]
        assert "esvere" in texts_after and "severe" not in texts_after
        assert "ASIAN" in texts_after
        # The untouched words are whole, in place, and draw the same pixels.
        for word in ("So-called", "health"):
            assert [w for w in words_before if w[0] == word] == [
                w for w in words_after if w[0] == word
            ], (word, words_after)
            assert _clip_pixels(page, keep[word]) == pixels_before[word], word
    finally:
        model.close()


def test_rebuild_refuses_when_the_redaction_would_erase_a_glyph_it_cannot_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "l_shaped_cluster_foreign.pdf"
    _make_pdf_l_shaped_cluster(path, foreign_glyph=True)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        model.open_pdf(str(path))
        target, names = _l_shaped_precondition(model)
        assert "W" not in names and "ASIAN" in names, names
        page = model.doc[0]
        words_before = _words(page)
        stream_before = page.read_contents()

        with pytest.raises(TextEditRefused) as excinfo:
            model.edit_text(
                page_num=1,
                rect=fitz.Rect(target.bbox),
                new_text="esvere",
                font=target.font,
                size=float(target.size),
                color=target.color,
                original_text=target.text,
                target_span_id=target.span_id,
                allow_rebuild=True,
                confirm_fallback=_accept_rebuild,
            )
        assert excinfo.value.reason is TextEditRefusal.UNTOUCHED_TEXT_WOULD_BE_LOST
        page = model.doc[0]
        assert _words(page) == words_before
        assert page.read_contents() == stream_before
        assert model.command_manager._undo_stack == []
    finally:
        model.close()


def _make_pdf_pushdown_with_foreign_block(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((40, 60), "EDITED LINE", fontsize=12, fontname="helv")
    page.insert_text((40, 90), "aaaa bbbb", fontsize=12, fontname="helv")
    page.insert_text((40, 104), "cccc dddd eeee ffff", fontsize=12, fontname="helv")
    # Its own block, not pushed (right of the edit column), but inside the
    # empty corner of the pushed block's bounding box.
    page.insert_text((110, 92), "Z", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_push_down_keeps_a_glyph_of_another_block_inside_the_pushed_box(
    tmp_path: Path,
) -> None:
    """Same class in the overflow push-down: it redacted each pushed block's
    bounding box and re-inserted only that block's spans, so a glyph of
    another block inside that box vanished."""
    path = tmp_path / "pushdown_foreign.pdf"
    _make_pdf_pushdown_with_foreign_block(path)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        page = model.doc[0]
        blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
        pushed = next(b for b in blocks if "aaaa" in b["lines"][0]["spans"][0]["text"])
        z_block = next(b for b in blocks if b["lines"][0]["spans"][0]["text"] == "Z")
        assert z_block is not pushed
        assert fitz.Rect(pushed["bbox"]).contains(fitz.Rect(z_block["bbox"]))
        words_before = _words(page)

        model._push_down_overlapping_text(
            page,
            fitz.Rect(page.rect),
            above_y=77.0,
            new_bottom=120.0,
            edit_x0=40.0,
            edit_x1=90.0,
        )

        words_after = _words(page)
        assert [w for w in words_after if w[0] == "Z"] == [
            w for w in words_before if w[0] == "Z"
        ], words_after
        y_before = next(w[2] for w in words_before if w[0] == "aaaa")
        y_after = next(w[2] for w in words_after if w[0] == "aaaa")
        assert y_after > y_before + 30, (y_before, y_after)
    finally:
        model.close()


def test_owned_glyph_redaction_reports_a_foreign_glyph_drawn_over_an_owned_one() -> None:
    """The guard behind the refusal: a glyph the rewrite does not own, drawn
    over the centre of one it erases, goes too -- and is reported."""
    from model.pdf_text_edit import _page_glyphs, _redact_owned_glyphs

    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 100), "aaaa", fontsize=12, fontname="helv")
        page.insert_text((36, 104), "W", fontsize=30, fontname="helv")
        page.insert_text((40, 160), "keep", fontsize=12, fontname="helv")
        glyphs = _page_glyphs(page)
        owned = [g for g in glyphs if g.key[0] == "a"]
        assert len(owned) == 4
        outcome = _redact_owned_glyphs(page, glyphs, owned, [])
        assert outcome.survivors == []
        assert outcome.lost_foreign == ["W"]
        assert "keep" in page.get_text()
    finally:
        doc.close()


def test_owned_glyph_redaction_erases_only_the_owned_glyphs() -> None:
    from model.pdf_text_edit import _page_glyphs, _redact_owned_glyphs

    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 100), "abc", fontsize=12, fontname="helv")
        page.insert_text((70, 100), "xyz", fontsize=12, fontname="helv")
        glyphs = _page_glyphs(page)
        owned = [g for g in glyphs if g.key[0] in "abc"]
        outcome = _redact_owned_glyphs(page, glyphs, owned, [])
        assert outcome == ([], [])
        assert page.get_text().split() == ["xyz"]
        # Empty input: nothing owned, nothing erased, nothing lost.
        glyphs = _page_glyphs(page)
        assert _redact_owned_glyphs(page, glyphs, [], []) == ([], [])
        assert page.get_text().split() == ["xyz"]
    finally:
        doc.close()


def test_push_down_refuses_when_the_owned_redaction_reports_a_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import model.pdf_text_edit as pte

    path = tmp_path / "pushdown_loss.pdf"
    _make_pdf_pushdown_with_foreign_block(path)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        monkeypatch.setattr(
            pte, "_redact_owned_glyphs", lambda *a, **k: pte._OwnedRedaction([], ["Z"])
        )
        with pytest.raises(TextEditRefused) as excinfo:
            model._push_down_overlapping_text(
                model.doc[0],
                fitz.Rect(model.doc[0].rect),
                above_y=77.0,
                new_bottom=120.0,
                edit_x0=40.0,
                edit_x1=90.0,
            )
        assert excinfo.value.reason is TextEditRefusal.UNTOUCHED_TEXT_WOULD_BE_LOST
    finally:
        model.close()


def _glyph(char: str, origin, bbox, *, size: float = 10.0, direction=(1.0, 0.0)):
    from model.pdf_text_edit import _PageGlyph

    ox, oy = origin
    return _PageGlyph(
        (char, round(ox * 10), round(oy * 10)),
        fitz.Rect(bbox),
        0,
        not char.isspace(),
        (float(ox), float(oy)),
        size,
        direction,
    )


@pytest.mark.parametrize(
    ("direction", "origin", "bbox", "expected"),
    [
        # Horizontal: below the extracted centre, 0.15 em above the baseline.
        # (MSBM10 in GeoTopo.pdf: ascender 0.464 em, descender 0, so MuPDF's
        # box is the lower half of the extracted one and its centre missed.)
        ((1.0, 0.0), (100.0, 200.0), (100.0, 189.0, 108.0, 200.0), (104.0, 198.5)),
        # Rotated 180: "up" is +y in page space.
        ((-1.0, 0.0), (108.0, 200.0), (100.0, 200.0, 108.0, 211.0), (104.0, 201.5)),
        # Upward text (dir (0, -1)): "up" is -x.
        ((0.0, -1.0), (200.0, 108.0), (189.0, 100.0, 200.0, 108.0), (198.5, 104.0)),
    ],
)
def test_glyph_redaction_point_sits_above_the_baseline_inside_the_advance(
    direction, origin, bbox, expected
) -> None:
    from model.pdf_text_edit import _glyph_redact_point

    point = _glyph_redact_point(_glyph("R", origin, bbox, direction=direction))
    assert point.x == pytest.approx(expected[0])
    assert point.y == pytest.approx(expected[1])


def test_a_glyph_re_emitted_one_rounding_step_away_still_counts_as_present() -> None:
    """Removing glyphs from a show re-emits the rest; GeoTopo p2 moved an
    untouched "s" by a rounding step across a 0.1 pt key boundary."""
    from model.pdf_text_edit import _glyphs_still_present

    before = [
        _glyph("s", (518.44, 381.384), (518.4, 372.9, 522.7, 383.8)),
        _glyph("a", (522.67, 381.384), (522.7, 372.9, 528.0, 383.8)),
        _glyph(" ", (528.0, 381.384), (528.0, 372.9, 531.0, 383.8)),
    ]
    after = [
        _glyph("s", (518.46, 381.384), (518.4, 372.9, 522.7, 383.8)),
        # The "a" moved a whole glyph width: that is a different glyph.
        _glyph("a", (530.0, 381.384), (530.0, 372.9, 535.0, 383.8)),
    ]
    assert before[0].key != after[0].key
    present = _glyphs_still_present(before, after)
    assert [g.key[0] for g in present] == ["s"]
    assert _glyphs_still_present([], after) == []
    assert _glyphs_still_present(before, []) == []


def test_owned_glyphs_of_one_line_share_a_strip_that_stops_at_a_foreign_glyph() -> None:
    """One redaction per glyph made a 1300-glyph paragraph take 4.5 s; owned
    glyphs that follow each other on a line share one strip, which must
    never run over a glyph the rewrite does not own."""
    from model.pdf_text_edit import _owned_redaction_rects, _page_glyphs, _redact_owned_glyphs

    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 100), "abc xyz def", fontsize=12, fontname="helv")
        glyphs = _page_glyphs(page)
        assert len({g.line for g in glyphs}) == 1
        xyz = [g for g in glyphs if g.key[0] in "xyz"]
        owned = [g for g in glyphs if g not in xyz]
        rects = _owned_redaction_rects(glyphs, owned)
        assert len(rects) == 2, rects
        for rect in rects:
            assert rect.height <= 0.21
            assert not any(rect.intersects(g.bbox) for g in xyz)
        outcome = _redact_owned_glyphs(page, glyphs, owned, [])
        assert outcome == ([], [])
        assert page.get_text().split() == ["xyz"]
        assert _owned_redaction_rects(glyphs, []) == []
    finally:
        doc.close()

# --------------------------------------------------------------------------
# F17-COL-1 (adversarial round 17): the consented rebuild erases the overlap
# cluster and replays the untouched neighbours it covered.  The replay drew
# them with only (text, size, RGB colour, font): invisible text (3 Tr) came
# back visible, alpha and outline were lost, CMYK / Separation became RGB and
# the neighbour left its optional-content layer -- live and after save.  The
# replay now re-applies each neighbour's own paint state, and so does the
# overflow push-down for the blocks it moves.

_SEPARATION_CS = (
    "[/Separation /PMS#20185 /DeviceCMYK << /FunctionType 2 /Domain [0 1] "
    "/C0 [0 0 0 0] /C1 [0 0.91 0.76 0] /N 1 >>]"
)
_NEIGHBOUR_STATES: dict[str, tuple[bytes, dict[str, str]]] = {
    "invisible": (b"0 g 3 Tr", {}),
    "alpha": (
        b"/GS1 gs 0 0 1 rg",
        {"ExtGState": "<< /GS1 << /Type /ExtGState /ca 0.3 /CA 0.3 >> >>"},
    ),
    "cmyk": (b"0 0.9 0.8 0 k", {}),
    "separation": (b"/CS0 cs 1 scn", {"ColorSpace": f"<< /CS0 {_SEPARATION_CS} >>"}),
    "outline": (b"0 0 1 rg 1 0 0 RG 0.8 w 1 Tr", {}),
    "layer": (b"0 0 1 rg", {}),
}


def _raw_page_pdf(path: Path, body: bytes, resources: dict[str, str], *, layer: bool) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    content = doc.get_new_xref()
    doc.update_object(content, "<<>>")
    doc.update_stream(content, body)
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    font = doc.get_new_xref()
    doc.update_object(
        font, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    res = f"<< /Font << /helv {font} 0 R >> " + "".join(
        f"/{k} {v} " for k, v in resources.items()
    )
    doc.xref_set_key(page.xref, "Resources", res + ">>")
    if layer:
        ocg = doc.add_ocg("Layer1", on=True)
        doc.xref_set_key(page.xref, "Resources/Properties", f"<< /L1 {ocg} 0 R >>")
    doc.save(str(path))
    doc.close()


def _make_pdf_styled_neighbour(path: Path, case: str, *, run_tail: bytes = b"") -> None:
    """Edited "Alpha" (plain red RGB) over an untouched "Gamma" 14 pt below it
    (tight leading: their boxes overlap, so Gamma is replayed) painted in
    ``case``'s state, and a plain line far away."""
    state, resources = _NEIGHBOUR_STATES.get(case, (b"7 Tr", {}))
    gamma = b"q BT /helv 18 Tf " + state + b" 40 106 Td (Gamma) Tj ET " + run_tail + b" Q\n"
    if case == "layer":
        gamma = b"/OC /L1 BDC\n" + gamma + b"EMC\n"
    body = (
        b"q BT /helv 18 Tf 1 0 0 rg 40 120 Td (Alpha) Tj ET Q\n"
        + gamma
        + b"q BT /helv 12 Tf 0 0 0 rg 40 40 Td (Far plain line) Tj ET Q\n"
    )
    _raw_page_pdf(path, body, resources, layer=case == "layer")


def _trace_spans(page: fitz.Page, needle: str) -> list[dict]:
    return [
        sp for sp in page.get_texttrace()
        if needle in "".join(chr(c[0]) for c in sp["chars"])
    ]


def _paint_ops(doc: fitz.Document, page: fitz.Page) -> list[tuple[str, tuple[float, ...]]]:
    from model.text_commit.pdf_lexer import TokenKind, lex_content_stream

    out: list[tuple[str, tuple[float, ...]]] = []
    for xref in list(page.get_contents()) + [x[0] for x in page.get_xobjects()]:
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


def _has_op(ops, name: str, values: tuple[float, ...], tol: float = 0.01) -> bool:
    return any(
        op == name and len(nums) == len(values) and all(abs(a - b) <= tol for a, b in zip(nums, values))
        for op, nums in ops
    )


def _rgb_pixels(page: fitz.Page, rect: fitz.Rect) -> list[tuple[int, int, int]]:
    pm = page.get_pixmap(clip=rect, dpi=144, colorspace=fitz.csRGB, alpha=False)
    s = pm.samples
    return [(s[i], s[i + 1], s[i + 2]) for i in range(0, len(s), 3)]


def _assert_neighbour_paint(doc: fitz.Document, page: fitz.Page, case: str, where: str) -> None:
    spans = _trace_spans(page, "Gamma")
    assert spans, (where, "Gamma is gone")
    box = fitz.Rect(spans[0]["bbox"])
    pixels = _rgb_pixels(page, box)
    ops = _paint_ops(doc, page)
    if case == "invisible":
        assert {sp["type"] for sp in spans} == {3}, (where, spans)
        # The edited red "Alpha" may reach into the box; nothing dark may.
        assert sum(1 for r, g, b in pixels if r < 90 and g < 90 and b < 90) == 0, where
    elif case == "alpha":
        assert all(abs(float(sp["opacity"]) - 0.3) < 0.01 for sp in spans), (where, spans)
        assert sum(1 for r, g, b in pixels if b > 200 and r < 60 and g < 60) == 0, where
    elif case == "cmyk":
        assert _has_op(ops, "k", (0.0, 0.9, 0.8, 0.0)), (where, "CMYK lost")
        assert not _has_op(ops, "rg", (0.937, 0.251, 0.239)), (where, "CMYK -> RGB")
    elif case == "separation":
        assert _has_op(ops, "scn", (1.0,)), (where, "Separation lost")
        assert not _has_op(ops, "rg", (0.937, 0.238, 0.259)), (where, "spot -> RGB")
    elif case == "outline":
        assert {sp["type"] for sp in spans} == {1}, (where, spans)
    elif case == "layer":
        assert all(sp.get("layer") == "Layer1" for sp in spans), (where, spans)
    else:
        raise AssertionError(case)


def _rebuild_alpha(model: PDFModel) -> EditTextResult:
    model.ensure_page_index_built(1)
    runs = model.block_manager.get_runs(0)
    target = next(r for r in runs if (r.text or "").strip() == "Alpha")
    gamma = next(r for r in runs if (r.text or "").strip() == "Gamma")
    cluster = model.block_manager.find_overlapping_runs(0, fitz.Rect(target.bbox), tol=0.5)
    assert gamma.span_id in {r.span_id for r in cluster}, "Gamma must be a replayed neighbour"
    return model.edit_text(
        page_num=1,
        rect=fitz.Rect(target.bbox),
        new_text="Alphaŋ",
        font=target.font,
        size=float(target.size),
        color=tuple(float(c) for c in target.color),
        original_text=target.text,
        target_span_id=target.span_id,
        target_mode="run",
        allow_rebuild=True,
        confirm_fallback=_accept_rebuild,
    )


@pytest.mark.parametrize("case", sorted(_NEIGHBOUR_STATES))
def test_rebuild_replays_an_untouched_neighbour_in_its_own_paint_state(
    tmp_path: Path, case: str
) -> None:
    path = tmp_path / f"styled_neighbour_{case}.pdf"
    _make_pdf_styled_neighbour(path, case)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    try:
        model.open_pdf(str(path))
        assert _rebuild_alpha(model) is EditTextResult.SUCCESS
        assert model.last_commit_outcome.tier is CommitTier.TIER2_LEGACY
        page = model.doc[0]
        _assert_neighbour_paint(model.doc, page, case, "live")
        # The edited run itself was plain red RGB and stays so.
        edited = _trace_spans(page, "Alpha")
        assert edited and all(sp["type"] == 0 for sp in edited)
        assert all(abs(sp["color"][0] - 1.0) < 0.01 and sp["color"][2] < 0.01 for sp in edited)
        saved = tmp_path / f"styled_neighbour_{case}_saved.pdf"
        model.save_as(str(saved))
    finally:
        model.close()
    doc = fitz.open(str(saved))
    try:
        _assert_neighbour_paint(doc, doc[0], case, "after save + reopen")
        if case == "layer":
            box = fitz.Rect(_trace_spans(doc[0], "Gamma")[0]["bbox"])
            ocg = next(x for x, info in doc.get_ocgs().items() if info["name"] == "Layer1")
            doc.set_layer(-1, off=[ocg])
            # MuPDF reads the layer configuration at open: render a reopened copy.
            hidden = fitz.open("pdf", doc.tobytes())
            try:
                blue = sum(
                    1 for r, g, b in _rgb_pixels(hidden[0], box) if b > r + 60 and b > g + 60
                )
            finally:
                hidden.close()
            assert blue == 0, "the replayed neighbour is still drawn with its layer off"
    finally:
        doc.close()


def test_rebuild_refuses_to_replay_a_neighbour_drawn_as_a_clip(tmp_path: Path) -> None:
    """A neighbour drawn as a clipping path (7 Tr: the blue fill after it shows
    only through its glyphs) cannot be replayed faithfully: refused, the page
    unchanged."""
    path = tmp_path / "clip_neighbour.pdf"
    _make_pdf_styled_neighbour(path, "clip", run_tail=b"0 0 1 rg 0 0 400 300 re f")
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="tiered"))
    try:
        model.open_pdf(str(path))
        page = model.doc[0]
        streams_before = [model.doc.xref_stream(x) for x in page.get_contents()]
        with pytest.raises(TextEditRefused) as excinfo:
            _rebuild_alpha(model)
        assert excinfo.value.reason.value == "text_state_not_reproducible"
        assert [model.doc.xref_stream(x) for x in model.doc[0].get_contents()] == streams_before
        assert model.command_manager._undo_stack == []
    finally:
        model.close()


def _make_pdf_pushdown_with_styled_block(path: Path) -> None:
    """The push-down fixture with the pushed block drawn CMYK in a layer."""
    body = (
        b"q BT /helv 12 Tf 0 0 0 rg 40 240 Td (EDITED LINE) Tj ET Q\n"
        b"/OC /L1 BDC\nq BT /helv 12 Tf 0 0.9 0.8 0 k 40 210 Td (aaaa bbbb) Tj "
        b"0 -14 Td (cccc dddd eeee ffff) Tj ET Q\nEMC\n"
    )
    _raw_page_pdf(path, body, {}, layer=True)


def test_push_down_redraws_the_pushed_block_in_its_own_paint_state(tmp_path: Path) -> None:
    """Same class in the overflow push-down: the pushed block was redrawn as
    RGB fill outside its layer."""
    path = tmp_path / "pushdown_styled.pdf"
    _make_pdf_pushdown_with_styled_block(path)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    try:
        model.open_pdf(str(path))
        model.ensure_page_index_built(1)
        page = model.doc[0]
        y_before = next(w[1] for w in page.get_text("words") if w[4] == "aaaa")
        model._push_down_overlapping_text(
            page,
            fitz.Rect(page.rect),
            above_y=77.0,
            new_bottom=120.0,
            edit_x0=40.0,
            edit_x1=90.0,
        )
        page = model.doc[0]
        y_after = next(w[1] for w in page.get_text("words") if w[4] == "aaaa")
        assert y_after > y_before + 30, (y_before, y_after)
        spans = _trace_spans(page, "aaaa") + _trace_spans(page, "cccc")
        assert spans and all(sp.get("layer") == "Layer1" for sp in spans), spans
        ops = _paint_ops(model.doc, page)
        assert _has_op(ops, "k", (0.0, 0.9, 0.8, 0.0)), "pushed block lost its CMYK fill"
        assert not _has_op(ops, "rg", (0.937, 0.251, 0.239)), "pushed block converted to RGB"
    finally:
        model.close()

if __name__ == "__main__":
    test_exact_overlap_edit()
    test_partial_overlap_edit()
    test_overlap_undo_redo()
    test_vertical_overlap_edit()
    test_overlap_replay_with_unavailable_font_fallback()
    print("PASS: overlap text edit regression suite")
