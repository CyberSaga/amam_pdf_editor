"""AC-1 — character-level browse-mode text selection.

The legacy selection worked at run/line granularity: any drag highlighted whole
runs. These tests pin the character-level behaviour: the selection is clipped to
the characters between the cursor-start and cursor-end points, the copied text
matches the highlight, and multi-line drags produce a partial first line, full
middle lines and a partial last line.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from model.pdf_model import PDFModel
from model.selection_text import (
    clip_directions,
    reading_sign,
    whitespace_between_runs,
    whitespace_chars,
)


def _make_text_pdf(path: Path, text: str, *, fontsize: float = 20.0) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((40, 60), text, fontsize=fontsize, fontname="helv")
    doc.save(path)
    doc.close()


def _first_run(model: PDFModel):
    model.ensure_page_index_built(1)
    runs = model.block_manager.get_runs(0)
    assert runs, "expected at least one run"
    return runs[0]


def test_get_chars_in_run_returns_per_character_boxes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chars.pdf"
        _make_text_pdf(path, "HELLO")
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            run = _first_run(model)
            chars = model.get_chars_in_run(1, run.span_id)
            assert "".join(c for c, _ in chars).replace(" ", "") == "HELLO"
            # Boxes must be ordered left-to-right and non-degenerate.
            xs = [rect.x0 for _, rect in chars]
            assert xs == sorted(xs)
            assert all(rect.width > 0 for _, rect in chars)
        finally:
            model.close()


def test_same_run_drag_selects_only_character_range() -> None:
    """AC-1b: dragging within a run selects only the chars between the two points,
    not the whole run, and the copied text matches (AC-1e)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "single.pdf"
        _make_text_pdf(path, "ABCDEFGH")
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            run = _first_run(model)
            chars = model.get_chars_in_run(1, run.span_id)
            assert len(chars) >= 6
            # Start just left of char index 2 (C), end just right of char index 4 (E).
            start_rect = chars[2][1]
            end_rect = chars[4][1]
            start_pt = fitz.Point(start_rect.x0 + 0.5, (start_rect.y0 + start_rect.y1) / 2)
            end_pt = fitz.Point(end_rect.x1 - 0.5, (end_rect.y0 + end_rect.y1) / 2)

            text, rects = model.get_text_selection_lines(
                1, run.span_id, end_pt, start_pt
            )
            assert text == "CDE", f"expected 'CDE', got {text!r}"
            assert len(rects) == 1
            full_run_width = fitz.Rect(run.bbox).width
            assert rects[0].width < full_run_width * 0.9
        finally:
            model.close()


def test_same_run_drag_is_order_independent() -> None:
    """Dragging right-to-left selects the same characters as left-to-right."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rev.pdf"
        _make_text_pdf(path, "ABCDEFGH")
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            run = _first_run(model)
            chars = model.get_chars_in_run(1, run.span_id)
            left = fitz.Point(chars[2][1].x0 + 0.5, (chars[2][1].y0 + chars[2][1].y1) / 2)
            right = fitz.Point(chars[4][1].x1 - 0.5, (chars[4][1].y0 + chars[4][1].y1) / 2)
            # Press at the right end, drag to the left.
            text, _ = model.get_text_selection_lines(1, run.span_id, left, right)
            assert text == "CDE"
        finally:
            model.close()


def test_cross_run_same_line_clips_both_boundaries() -> None:
    """AC-1c: a drag across two runs on the same visual line clips the start run
    and the end run, with one highlight rect for the line."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tworun.pdf"
        doc = fitz.open()
        page = doc.new_page(width=500, height=200)
        page.insert_text((40, 60), "ALPHA", fontsize=20.0, fontname="helv")
        page.insert_text((200, 60), "BETA", fontsize=20.0, fontname="cour")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            assert len(runs) == 2
            run_a, run_b = runs[0], runs[1]
            chars_a = model.get_chars_in_run(1, run_a.span_id)
            chars_b = model.get_chars_in_run(1, run_b.span_id)
            assert "".join(c for c, _ in chars_a) == "ALPHA"
            assert "".join(c for c, _ in chars_b) == "BETA"

            # Start inside ALPHA at char 2 (P), end inside BETA after char 1 (E).
            start_pt = fitz.Point(chars_a[2][1].x0 + 0.5, (chars_a[2][1].y0 + chars_a[2][1].y1) / 2)
            end_pt = fitz.Point(chars_b[1][1].x1 - 0.5, (chars_b[1][1].y0 + chars_b[1][1].y1) / 2)

            text, rects = model.get_text_selection_lines(1, run_a.span_id, end_pt, start_pt)
            assert text == "PHABE", f"expected 'PHABE', got {text!r}"
            assert len(rects) == 1
        finally:
            model.close()


def test_multi_run_selection_fetches_rawdict_once(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rawdict_once.pdf"
        doc = fitz.open()
        page = doc.new_page(width=500, height=200)
        page.insert_text((40, 60), "ALPHA", fontsize=20.0, fontname="helv")
        page.insert_text((200, 60), "BETA", fontsize=20.0, fontname="cour")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            assert len(runs) == 2
            run_a, run_b = runs[0], runs[1]
            chars_a = model.get_chars_in_run(1, run_a.span_id)
            chars_b = model.get_chars_in_run(1, run_b.span_id)
            start_pt = fitz.Point(chars_a[2][1].x0 + 0.5, (chars_a[2][1].y0 + chars_a[2][1].y1) / 2)
            end_pt = fitz.Point(chars_b[1][1].x1 - 0.5, (chars_b[1][1].y0 + chars_b[1][1].y1) / 2)

            real_get_text = fitz.Page.get_text
            calls = {"rawdict": 0}

            def counting_get_text(self, *args, **kwargs):
                option = kwargs.get("option")
                if option is None and args:
                    option = args[0]
                if option == "rawdict":
                    calls["rawdict"] += 1
                return real_get_text(self, *args, **kwargs)

            monkeypatch.setattr(fitz.Page, "get_text", counting_get_text)

            text, _ = model.get_text_selection_lines(1, run_a.span_id, end_pt, start_pt)
            assert text == "PHABE"
            assert calls["rawdict"] == 1
        finally:
            model.close()


def test_multi_line_drag_partial_first_full_middle_partial_last() -> None:
    """AC-1d: across visual lines — partial first, full middle, partial last."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi.pdf"
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        # Three separate lines at distinct y positions.
        page.insert_text((40, 60), "FIRSTLINE", fontsize=20.0, fontname="helv")
        page.insert_text((40, 100), "MIDDLELINE", fontsize=20.0, fontname="helv")
        page.insert_text((40, 140), "LASTLINE", fontsize=20.0, fontname="helv")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            assert len(runs) >= 3
            first_run = runs[0]
            last_run = runs[-1]
            first_chars = model.get_chars_in_run(1, first_run.span_id)
            last_chars = model.get_chars_in_run(1, last_run.span_id)

            # Start mid-way through the first line, end mid-way through the last.
            start_pt = fitz.Point(
                first_chars[3][1].x0,
                (first_chars[3][1].y0 + first_chars[3][1].y1) / 2,
            )
            end_pt = fitz.Point(
                last_chars[3][1].x1,
                (last_chars[3][1].y0 + last_chars[3][1].y1) / 2,
            )
            text, rects = model.get_text_selection_lines(
                1, first_run.span_id, end_pt, start_pt
            )
            lines = text.split("\n")
            assert len(lines) == 3, f"expected 3 lines, got {lines!r}"
            # First line is clipped from char 3 → end; last line clipped to char 3.
            assert lines[0] == "STLINE", f"first line: {lines[0]!r}"
            assert lines[1] == "MIDDLELINE", f"middle line: {lines[1]!r}"
            assert lines[2] == "LAST", f"last line: {lines[2]!r}"
            assert len(rects) == 3
        finally:
            model.close()


# --- F16-COPY-1: a line drawn as ONE text show (the most common PDF line) ---
# Run mode collapses a proven single show into one edit target whose
# ``target_span_id`` is the show's FIRST word.  Browse selection must still
# resolve each point to the word actually under it; resolving it to the
# show's first word copied only "Invoice" for a whole-line drag and nothing
# at all for a drag from "number" to "today".  Comparisons ignore
# whitespace: inter-word spacing in copied text is a separate concern.

_SHOW_LINES = (
    "Invoice number 4711 due today",
    "Second line of plain text",
    "Third line ends here",
)


def _make_show_lines_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for idx, line in enumerate(_SHOW_LINES):
        page.insert_text((72, 100 + 30 * idx), line, fontname="helv", fontsize=14)
    doc.save(path)
    doc.close()


def _word_rect(path: Path, word: str) -> fitz.Rect:
    with fitz.open(str(path)) as doc:
        hits = doc[0].search_for(word)
    assert hits, f"fixture word {word!r} not found"
    return fitz.Rect(hits[0])


def _mid_y(rect: fitz.Rect) -> float:
    return (rect.y0 + rect.y1) / 2.0


def _mid_point(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2.0, _mid_y(rect))


def _open_show_model(tmp: str) -> tuple[PDFModel, Path]:
    path = Path(tmp) / "show_lines.pdf"
    _make_show_lines_pdf(path)
    model = PDFModel()
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model, path


def _grouped_hit(model: PDFModel, point: fitz.Point):
    """The press-time hit, as the View gets it; asserts the grouped path."""
    hit = model.get_text_info_at_point(1, point, allow_fallback=False)
    assert hit is not None
    assert len(hit.member_span_ids) > 1, "fixture must exercise a proven multi-word show"
    return hit


def _view_start_span_id(hit) -> str:
    # What view/text_selection.py stores as the drag's start run.
    return getattr(hit, "hit_span_id", None) or hit.target_span_id


def test_grouped_show_whole_line_drag_copies_every_word() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, path = _open_show_model(tmp)
        try:
            inv = _word_rect(path, "Invoice")
            today = _word_rect(path, "today")
            y = _mid_y(inv)
            hit = _grouped_hit(model, fitz.Point(inv.x0 + 1, y))
            text, rects = model.get_text_selection_lines(
                1, _view_start_span_id(hit), fitz.Point(today.x1 - 1, y), fitz.Point(inv.x0 - 0.5, y)
            )
            assert text == "Invoice number 4711 due today", f"got {text!r}"
            assert len(rects) == 1
        finally:
            model.close()


def test_grouped_show_mid_line_drag_copies_dragged_words_both_directions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, path = _open_show_model(tmp)
        try:
            number = _word_rect(path, "number")
            today = _word_rect(path, "today")
            y = _mid_y(number)
            start = fitz.Point(number.x0 + 1, y)
            end = fitz.Point(today.x1 - 1, y)
            start_hit = _grouped_hit(model, start)
            end_hit = _grouped_hit(model, end)
            # Forward, with the EDIT target id (the show's first word) as the
            # start run: the model must still start at the word under the press.
            text, rects = model.get_text_selection_lines(1, start_hit.target_span_id, end, start)
            assert text == "number 4711 due today", f"forward got {text!r} rects={rects!r}"
            assert len(rects) == 1
            # Reverse drag (press on "today", release on "number").
            text, rects = model.get_text_selection_lines(1, _view_start_span_id(end_hit), start, end)
            assert text == "number 4711 due today", f"reverse got {text!r} rects={rects!r}"
            assert len(rects) == 1
            assert rects[0].x0 >= number.x0 - 1.0, "highlight must not start before the dragged word"
        finally:
            model.close()


def test_grouped_show_three_line_drag_keeps_last_line_to_end_word() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, path = _open_show_model(tmp)
        try:
            inv = _word_rect(path, "Invoice")
            ends = _word_rect(path, "ends")
            hit = _grouped_hit(model, fitz.Point(inv.x0 + 1, _mid_y(inv)))
            text, rects = model.get_text_selection_lines(
                1,
                _view_start_span_id(hit),
                fitz.Point(ends.x1 - 0.5, _mid_y(ends)),
                fitz.Point(inv.x0 - 0.5, _mid_y(inv)),
            )
            lines = text.split("\n")
            assert lines == [
                "Invoice number 4711 due today",
                "Second line of plain text",
                "Third line ends",
            ], f"got {text!r}"
            assert len(rects) == 3
        finally:
            model.close()


def test_grouped_show_snapshot_from_run_resolves_end_word() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, path = _open_show_model(tmp)
        try:
            number = _word_rect(path, "number")
            today = _word_rect(path, "today")
            y = _mid_y(number)
            hit = _grouped_hit(model, fitz.Point(number.x0 + 1, y))
            text, bounds = model.get_text_selection_snapshot_from_run(
                1, _view_start_span_id(hit), fitz.Point(today.x1 - 1, y)
            )
            assert text == "number 4711 due today", f"got {text!r}"
            assert bounds is not None and bounds.x1 >= today.x1 - 1.0
        finally:
            model.close()


def test_grouped_show_char_context_resolves_word_under_point() -> None:
    """Numeric-token double-click reads the glyphs of the word under the
    point, not of the show's first word (which made it silently fail)."""
    with tempfile.TemporaryDirectory() as tmp:
        model, path = _open_show_model(tmp)
        try:
            seven = _word_rect(path, "4711")
            point = fitz.Point(seven.x0 + seven.width * 0.6, _mid_y(seven))
            _grouped_hit(model, point)
            context = model.get_char_context_at_point(1, point)
            assert context is not None, "char context lost on a later word of a show"
            text, hit_index, rects = context
            assert "4711" in text, f"got {text!r}"
            assert text[hit_index] in "4711"
            assert fitz.Rect(rects[hit_index]).contains(point)
        finally:
            model.close()


def test_grouped_show_selection_after_an_edit_still_resolves_word_under_point() -> None:
    """After an edit the show's reopen anchor (keyed by the whole group) wins
    the hit-test; browse selection and char context must still read the word
    under the point, not the anchor's first member."""
    with tempfile.TemporaryDirectory() as tmp:
        model, _path = _open_show_model(tmp)
        try:
            page = model.doc[0]
            number = fitz.Rect(page.search_for("number")[0])
            hit = _grouped_hit(model, fitz.Point(number.x0 + 2, _mid_y(number)))
            result = model.edit_text(
                page_num=1,
                rect=hit.target_bbox,
                new_text="Invoice number 4711 due tomorrow",
                font=hit.font,
                size=hit.size,
                color=hit.color,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode="run",
                source_ref=hit.source_ref,
            )
            assert str(getattr(result, "name", result)).endswith("SUCCESS"), result
            model.ensure_page_index_built(1)
            page = model.doc[0]
            number = fitz.Rect(page.search_for("number")[0])
            due = fitz.Rect(page.search_for("due")[0])
            seven = fitz.Rect(page.search_for("4711")[0])
            y = _mid_y(number)
            start = fitz.Point(number.x0 + 1, y)
            end = fitz.Point(due.x1 - 1, y)
            start_hit = _grouped_hit(model, start)
            text, rects = model.get_text_selection_lines(1, _view_start_span_id(start_hit), end, start)
            assert text == "number 4711 due", f"got {text!r} rects={rects!r}"
            context = model.get_char_context_at_point(1, fitz.Point(seven.x0 + seven.width * 0.6, y))
            assert context is not None, "char context lost on a later word after an edit"
            assert "4711" in context[0], f"got {context[0]!r}"
        finally:
            model.close()


# --- F16-COPY-2: copied text keeps the page's inter-word gaps, RTL reads logically ---

_NBSP = chr(0xA0)
_COMBINING_LINE = "cafe" + chr(0x301) + " nai" + chr(0x308) + "ve"
_NBSP_LINE = "10" + _NBSP + "kg item"
_HEBREW_LINE = "שלום עולם"
_MIXED_LINE = "Total: 42 שקל"

_GAP_LINES = {
    "combining": _COMBINING_LINE,
    "nbsp": _NBSP_LINE,
    "hebrew": _HEBREW_LINE,
    "mixed": _MIXED_LINE,
}
# ... plus the TJ-kerned line ``_make_gap_lines_pdf`` writes by hand.
_GAP_EXPECTED = {**_GAP_LINES, "kerned": "Kerned gap words"}


def _make_gap_lines_pdf(path: Path) -> dict[str, fitz.Rect]:
    """One htmlbox line per case plus a pdfTeX-style line whose word gaps are
    TJ kerning (no space glyph in the content stream)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rects: dict[str, fitz.Rect] = {}
    y = 80.0
    for key, text in _GAP_LINES.items():
        rect = fitz.Rect(72, y, 520, y + 30)
        page.insert_htmlbox(rect, f'<p style="font-size:16px">{text}</p>')
        rects[key] = rect
        y += 50
    page.insert_text((72, 800), ".", fontname="helv", fontsize=4)
    new_xref = doc.get_new_xref()
    doc.update_object(new_xref, "<<>>")
    doc.update_stream(new_xref, f"BT /helv 14 Tf 72 {842 - (y + 20)} Td [(Kerned) -350 (gap) -350 (words)] TJ ET".encode())
    contents = page.get_contents()
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in [*contents, new_xref]) + "]")
    rects["kerned"] = fitz.Rect(72, y, 520, y + 30)
    doc.save(path)
    doc.close()
    return rects


def _drag_whole_line(model: PDFModel, rect: fitz.Rect, *, right_to_left: bool) -> tuple[str, str, list]:
    """Press/release over the line as the View would; returns (copied text,
    page text of the same line, highlight rects)."""
    page = model.doc[0]
    words = [fitz.Rect(w[:4]) for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(rect)]
    assert words, "fixture line not found"
    box = fitz.Rect(words[0])
    for word in words[1:]:
        box |= word
    y = _mid_y(box)
    left, right = fitz.Point(box.x0 + 1, y), fitz.Point(box.x1 - 1, y)
    start, end = (right, left) if right_to_left else (left, right)
    hit = model.get_text_info_at_point(1, start, allow_fallback=False)
    assert hit is not None, "no browse hit under the press point"
    text, rects = model.get_text_selection_lines(1, _view_start_span_id(hit), end, start)
    return text, page.get_text("text", clip=box).strip(), rects


@pytest.mark.parametrize("right_to_left", [False, True])
@pytest.mark.parametrize("key", ["kerned", "nbsp", "combining", "hebrew", "mixed"])
def test_whole_line_drag_copies_the_page_text_including_gaps(key: str, right_to_left: bool) -> None:
    """A drag over a whole line copies what ``page.get_text`` reads: the gap
    between word runs is a space glyph in MuPDF's text (a TJ kerning gap, a
    no-break space, a plain space) that no run owns, and right-to-left words
    come out in LOGICAL order, whichever way the user dragged."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gap_lines.pdf"
        rects = _make_gap_lines_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            text, page_text, line_rects = _drag_whole_line(model, rects[key], right_to_left=right_to_left)
            expected = _GAP_EXPECTED[key]
            assert page_text == expected, f"fixture drifted: {page_text!r}"
            assert text == expected, f"copied {text!r}, page reads {page_text!r}"
            assert len(line_rects) == 1
        finally:
            model.close()


def test_rtl_partial_drag_selects_a_logical_substring_in_both_directions() -> None:
    """Dragging from the middle of the first Hebrew word to the middle of the
    second copies the logical text between the two points (not nothing, not a
    mirrored string), for a right-to-left and a left-to-right drag alike."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gap_lines.pdf"
        rects = _make_gap_lines_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            page = model.doc[0]
            shalom = fitz.Rect(page.search_for("שלום", clip=rects["hebrew"])[0])
            olam = fitz.Rect(page.search_for("עולם", clip=rects["hebrew"])[0])
            y = _mid_y(shalom)
            right_mid = fitz.Point(shalom.x0 + shalom.width * 0.5, y)
            left_mid = fitz.Point(olam.x0 + olam.width * 0.5, y)
            hit_right = model.get_text_info_at_point(1, right_mid, allow_fallback=False)
            hit_left = model.get_text_info_at_point(1, left_mid, allow_fallback=False)
            assert hit_right is not None and hit_left is not None
            rtl_text, _ = model.get_text_selection_lines(1, _view_start_span_id(hit_right), left_mid, right_mid)
            ltr_text, _ = model.get_text_selection_lines(1, _view_start_span_id(hit_left), right_mid, left_mid)
            assert rtl_text == ltr_text
            assert rtl_text in _HEBREW_LINE, f"not a logical substring: {rtl_text!r}"
            assert " " in rtl_text and 4 <= len(rtl_text) <= 8, f"got {rtl_text!r}"
            assert rtl_text.split(" ")[0] and rtl_text.split(" ")[1], f"got {rtl_text!r}"
        finally:
            model.close()


@pytest.mark.parametrize("fitz_rotate", [90, 270])
def test_vertical_run_cross_run_drag_follows_the_reading_direction(fitz_rotate: int) -> None:
    """A quarter-turn line reads along y, downwards for one turn and upwards
    for the other; the boundary runs are clipped from the pointer ONWARD in
    that direction, and the gap glyph between the two words is kept."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "vertical.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=400)
        origin = (100, 350) if fitz_rotate == 90 else (100, 40)
        page.insert_text(origin, "ABCDEFGH ijklmnop", fontsize=20, fontname="helv", rotate=fitz_rotate)
        doc.save(path)
        doc.close()
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.ensure_page_index_built(1)
            runs = model.block_manager.get_runs(0)
            assert len(runs) == 2, [r.text for r in runs]
            first, second = runs
            chars_a = model.get_chars_in_run(1, first.span_id)
            chars_b = model.get_chars_in_run(1, second.span_id)
            assert "".join(c for c, _ in chars_a) == "ABCDEFGH"
            assert "".join(c for c, _ in chars_b) == "ijklmnop"
            press, release = _mid_point(chars_a[2][1]), _mid_point(chars_b[3][1])
            forward, _ = model.get_text_selection_lines(1, first.span_id, release, press)
            backward, _ = model.get_text_selection_lines(1, second.span_id, press, release)
            assert forward == "CDEFGH ijkl", f"forward {forward!r}"
            assert backward == "CDEFGH ijkl", f"backward {backward!r}"
        finally:
            model.close()


# --- F17-COPY-180: the reading-direction model covers every page rotation ---------
#
# F16-COPY-2 taught the clip about right-to-left text and the 270 degree turn but
# left the half turn out, and kept the glyph list of a quarter-turn run in
# position order even when it holds right-to-left letters.  A page's /Rotate
# changes nothing about what the user reads, so every drag below is described by
# its on-screen position and must copy the same text at /Rotate 0, 90, 180, 270.

_ROTATIONS = [0, 90, 180, 270]
_UPRIGHT_ROWS = {
    "latin": ("alpha bravo", "charlie delta"),
    "hebrew": ("שלום עולם", "גדול טוב"),
}
_UPRIGHT_LINE = {"latin": "Hello brave new world", "hebrew": "שלום עולם גדול"}
# What a /Rotate 0 page copies (the guard ids pin these); the others must agree.
_UPRIGHT_EXPECTED = {
    "latin": {
        "full": "Hello brave new world",
        "across": "ve ne",
        "within": "rav",
        "first": ("Hello", 0),
        "second": ("brave", 4),
    },
    "hebrew": {
        "full": "שלום עולם גדול",
        "across": "ום עו",
        "within": "ול",
        "first": ("גדול", 3),
        "second": ("עולם", 0),
    },
}
_UPRIGHT_TWO_ROW_EXPECTED = {"latin": "vo\ncha", "hebrew": "לם\nגד"}


def _make_upright_rows_pdf(path: Path, rows: tuple[str, ...], page_rotation: int) -> None:
    """Rows of text that read upright on screen whatever the page's /Rotate
    (the content is turned with the page, as a scanner or a CAD export does)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if page_rotation:
        page.set_rotation(page_rotation)
    for index, text in enumerate(rows):
        shown = fitz.Rect(100, 300 + index * 40, 500, 330 + index * 40)
        box = shown * page.derotation_matrix
        box.normalize()
        page.insert_htmlbox(box, f"<p>{text}</p>", css="p{font-size:14pt}", rotate=page_rotation)
    doc.save(path, garbage=0)
    doc.close()


def _open_upright_model(tmp: str, rows: tuple[str, ...], page_rotation: int) -> PDFModel:
    path = Path(tmp) / f"upright_{page_rotation}.pdf"
    _make_upright_rows_pdf(path, rows, page_rotation)
    model = PDFModel()
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    return model


def _displayed_words(model: PDFModel) -> list[tuple[object, fitz.Rect]]:
    """(run, DISPLAYED rect) per word, leftmost on screen first.  The rect is
    mapped with the page's own rotation matrix, not the model's helper."""
    page = model.doc[0]
    words = [(run, fitz.Rect(run.bbox) * page.rotation_matrix) for run in model.block_manager.get_runs(0)]
    return sorted(words, key=lambda item: (round(item[1].y0 / 20.0), item[1].x0))


def _drag_copy(model: PDFModel, start: fitz.Point, end: fitz.Point) -> str:
    """Press at ``start`` and release at ``end`` (displayed space), as the View does."""
    hit = model.get_text_info_at_point(1, start, allow_fallback=False)
    assert hit is not None, f"no browse hit under the press point {start}"
    text, _rects = model.get_text_selection_lines(1, _view_start_span_id(hit), end, start)
    return text


@pytest.mark.parametrize("key", ["latin", "hebrew"])
@pytest.mark.parametrize("rotation", _ROTATIONS)
def test_upright_line_copies_the_same_text_on_every_page_rotation(key: str, rotation: int) -> None:
    """Whole-line, word-to-word and within-word drags, in both directions, and
    the double-click char context all agree with the /Rotate 0 page."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _open_upright_model(tmp, (_UPRIGHT_LINE[key],), rotation)
        try:
            page = model.doc[0]
            assert " ".join(page.get_text("text").split()) == _UPRIGHT_LINE[key], "fixture drifted"
            words = _displayed_words(model)
            assert len(words) == 3 + (key == "latin"), [run.text for run, _rect in words]
            y = _mid_y(words[0][1])
            left, right = words[0][1].x0 + 0.5, words[-1][1].x1 - 0.5
            second, third = words[1][1], words[2][1]
            mid2 = fitz.Point((second.x0 + second.x1) / 2, y)
            mid3 = fitz.Point((third.x0 + third.x1) / 2, y)
            quarter = fitz.Point(second.x0 + second.width * 0.25, y)
            three_quarters = fitz.Point(second.x0 + second.width * 0.75, y)
            context_first = model.get_char_context_at_point(1, fitz.Point(words[0][1].x0 + 2, y))
            context_second = model.get_char_context_at_point(1, fitz.Point(second.x1 - 2, y))
            got = {
                "full": _drag_copy(model, fitz.Point(left, y), fitz.Point(right, y)),
                "full reversed": _drag_copy(model, fitz.Point(right, y), fitz.Point(left, y)),
                "across": _drag_copy(model, mid2, mid3),
                "across reversed": _drag_copy(model, mid3, mid2),
                "within": _drag_copy(model, quarter, three_quarters),
                "within reversed": _drag_copy(model, three_quarters, quarter),
                "first": None if context_first is None else context_first[:2],
                "second": None if context_second is None else context_second[:2],
            }
            want = _UPRIGHT_EXPECTED[key]
            assert got == {
                "full": want["full"],
                "full reversed": want["full"],
                "across": want["across"],
                "across reversed": want["across"],
                "within": want["within"],
                "within reversed": want["within"],
                "first": want["first"],
                "second": want["second"],
            }, f"/Rotate {rotation} copies differently from /Rotate 0"
        finally:
            model.close()


@pytest.mark.parametrize("key", ["latin", "hebrew"])
@pytest.mark.parametrize("rotation", _ROTATIONS)
def test_upright_two_line_drag_clips_each_boundary_word_on_every_page_rotation(key: str, rotation: int) -> None:
    """A drag from the middle of the last word of one row to the middle of the
    first word of the next: each boundary row is a ONE-run slice, so the clip
    direction is the run's own reading direction (rotation and script)."""
    first_row, second_row = _UPRIGHT_ROWS[key]
    start_word = first_row.split()[-1]
    end_word = second_row.split()[0]
    with tempfile.TemporaryDirectory() as tmp:
        model = _open_upright_model(tmp, _UPRIGHT_ROWS[key], rotation)
        try:
            shown = {run.text: rect for run, rect in _displayed_words(model)}
            start, end = _mid_point(shown[start_word]), _mid_point(shown[end_word])
            forward = _drag_copy(model, start, end)
            backward = _drag_copy(model, end, start)
            want = _UPRIGHT_TWO_ROW_EXPECTED[key]
            assert (forward, backward) == (want, want), f"/Rotate {rotation} copies differently from /Rotate 0"
        finally:
            model.close()


@pytest.mark.parametrize("key", ["latin", "hebrew"])
@pytest.mark.parametrize("rotation", _ROTATIONS)
def test_upright_line_run_level_snapshots_read_the_same_on_every_page_rotation(key: str, rotation: int) -> None:
    """The coarse (whole-run / whole-line) copy paths join run and line texts, so
    they never needed the glyph order; pinned so they stay rotation-blind."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _open_upright_model(tmp, (_UPRIGHT_LINE[key],), rotation)
        try:
            words = _displayed_words(model)
            first_run, first_rect = words[0]
            last_run, last_rect = words[-1]
            y = _mid_y(first_rect)
            around = fitz.Rect(first_rect.x0 - 2, first_rect.y0 - 1, last_rect.x1 + 2, first_rect.y1 + 1)
            rect_text, _bounds = model.get_text_selection_snapshot(1, around)
            forward, _ = model.get_text_selection_snapshot_from_run(
                1, first_run.span_id, fitz.Point(last_rect.x1 - 1, y)
            )
            backward, _ = model.get_text_selection_snapshot_from_run(
                1, last_run.span_id, fitz.Point(first_rect.x0 + 1, y)
            )
            assert (rect_text, forward, backward) == (_UPRIGHT_LINE[key],) * 3
        finally:
            model.close()


@pytest.mark.parametrize("key", ["latin", "hebrew"])
@pytest.mark.parametrize("rotation", _ROTATIONS)
def test_run_glyphs_follow_the_run_text_on_every_page_rotation(key: str, rotation: int) -> None:
    """``get_chars_in_run`` pairs the run's text with its glyph boxes index by
    index: the glyphs read in the run's own order, which on an upright page is
    left to right for Latin and right to left for Hebrew."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _open_upright_model(tmp, (_UPRIGHT_LINE[key],), rotation)
        try:
            for run, _rect in _displayed_words(model):
                chars = model.get_chars_in_run(1, run.span_id)
                assert "".join(glyph for glyph, _box in chars) == run.text
                centres = [(box.x0 + box.x1) / 2.0 for _glyph, box in chars]
                assert centres == sorted(centres, reverse=(key == "hebrew")), f"{run.text!r} {centres}"
        finally:
            model.close()


def _fake_run(x0: float, x1: float, text: str = "w", rotation: int = 0):
    return SimpleNamespace(bbox=fitz.Rect(x0, 10, x1, 22), text=text, rotation=rotation)


@pytest.mark.parametrize(
    ("rotation", "rtl", "expected"),
    [
        (0, False, 1),
        (90, False, 1),
        (180, False, -1),
        (270, False, -1),
        (0, True, -1),
        (90, True, -1),
        (180, True, 1),
        (270, True, 1),
    ],
)
def test_reading_sign_covers_every_rotation_and_script(rotation: int, rtl: bool, expected: int) -> None:
    """The way a run reads along its axis in index space: the quarter and half
    turns point the Latin reading axis, right-to-left script mirrors it."""
    run = _fake_run(0, 30, text="שלום" if rtl else "w", rotation=rotation)
    assert reading_sign(run) == expected
    assert clip_directions([run]) == (expected, expected)


def test_selection_text_helpers_edges() -> None:
    # empty / missing extraction: no gap glyphs, nothing to insert
    assert whitespace_chars(None) == []
    assert whitespace_chars({}) == []
    space = (" ", fitz.Rect(30, 10, 34, 22))
    assert whitespace_chars(
        {"blocks": [{"lines": [{"spans": [{"chars": [{"c": "a", "bbox": (0, 10, 5, 22)}, {"c": " ", "bbox": tuple(space[1])}]}]}]}]}
    ) == [space]
    left, right = _fake_run(0, 30), _fake_run(34, 60)
    assert whitespace_between_runs([space], left, right) == [" "]
    # reading order reversed on screen (right-to-left): same glyph, found either way
    assert whitespace_between_runs([space], right, left) == [" "]
    # touching or overlapping runs have no gap; a glyph on another line is not theirs
    assert whitespace_between_runs([space], _fake_run(0, 34), right) == []
    assert whitespace_between_runs([space], _fake_run(0, 40), _fake_run(30, 60)) == []
    assert whitespace_between_runs([(" ", fitz.Rect(30, 90, 34, 102))], left, right) == []
    assert whitespace_between_runs([], left, right) == []
    # a gap glyph within the run-edge tolerance is the run's own glyph already
    assert whitespace_between_runs([(" ", fitz.Rect(29.8, 10, 30.6, 22))], left, right) == []
    # clip directions: physical order of the slice, else the run's reading direction
    assert clip_directions([left, right]) == (1, 1)
    assert clip_directions([right, left]) == (-1, -1)
    assert clip_directions([_fake_run(0, 30, text="שלום")]) == (-1, -1)
    assert clip_directions([left]) == (1, 1)
    assert clip_directions([_fake_run(0, 30, rotation=270)]) == (-1, -1)
    assert clip_directions([_fake_run(0, 30, rotation=90)]) == (1, 1)
    # F17-COPY-180: the half turn reads towards smaller x; two runs of it follow
    # their physical order like any other (the first read is the right-hand one)
    assert clip_directions([_fake_run(0, 30, rotation=180)]) == (-1, -1)
    assert clip_directions([_fake_run(34, 60, rotation=180), _fake_run(0, 30, rotation=180)]) == (-1, -1)
