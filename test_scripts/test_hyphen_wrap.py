"""D-HYPHEN-WRAP (owner decision after round 15, TODOS F14-VF4-WRAP-REFLOW hyphen part).

When an edit wraps at the right-hand neighbour (F13-VF-4 cap, F14-VF4-WRAP),
a word may break AFTER an existing hyphen (``Two-Colunm`` on ``multicolumn.pdf``
becomes ``Two-`` / ``Colunm``), the hyphen staying at the end of the first
line.  Only at an existing U+002D / U+2010; U+2011 is NO-BREAK and never
breaks; no hyphen is ever inserted; a word without a hyphen keeps shrinking /
being refused; a hyphen that opens a word is not a break (it would leave a
line of just ``-``).  Paragraph reflow is NOT part of this.

The tests read the SAVED and reopened file: extracted lines and glyph
positions (``get_texttrace``), not the markup.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import _RebuildRolledBack  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402
from model.text_edit_refusal import TextEditRefusal  # noqa: E402

MULTICOLUMN = (
    ROOT / "test_files" / "sample-files-main" / "026-latex-multicolumn" / "multicolumn.pdf"
)
_HYPHENS = (0x2D, 0x2010)
_EDIT_X = 72.0
_EDIT_Y = 700.0
_FIXED = ("NEXT", "Below line", "second line untouched")
_ENGINES = ["legacy", "tiered"]


def _accept_rebuild(_chain: tuple[str, ...]) -> bool:
    return True


def _synthetic_pdf(path: Path, *, gap: float = 30.0, same_block: bool = False) -> float:
    """``ab`` (Helvetica 14), the untouched red run ``NEXT`` ``gap`` pt after it
    and a line below: a separate block 40 pt lower (``Below line``) or, with
    ``same_block``, the paragraph's own next line 17 pt lower (no room to wrap,
    the push-down never moves it).  Returns the neighbour's left edge."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    edit_w = fitz.Font("helv").text_length("ab", fontsize=14)
    next_x = _EDIT_X + edit_w + gap
    page.insert_text((_EDIT_X, _EDIT_Y), "ab", fontsize=14, fontname="helv")
    page.insert_text((next_x, _EDIT_Y), "NEXT", fontsize=10, fontname="helv", color=(1, 0, 0))
    if same_block:
        page.insert_text(
            (_EDIT_X, _EDIT_Y + 17), "second line untouched", fontsize=14, fontname="helv"
        )
        blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
        assert len(blocks) == 1, "premise: the line below belongs to the edited block"
    else:
        page.insert_text((_EDIT_X, _EDIT_Y + 40), "Below line", fontsize=14, fontname="helv")
    doc.save(str(path), garbage=0)
    doc.close()
    return next_x


def _edit(pdf: Path, old: str, new: str, engine: str):
    """Rebuild-edit the run ``old``; returns ``(outcome, saved_path)``."""
    model = PDFModel(text_commit_settings=TextCommitSettings(engine=engine))
    model.open_pdf(str(pdf))
    model.ensure_page_index_built(1)
    try:
        run = next(r for r in model.block_manager.get_runs(0) if r.text == old)
        try:
            outcome: object = model.edit_text(
                1, fitz.Rect(run.bbox), new, font=run.font, size=float(run.size),
                original_text=old, target_span_id=run.span_id, target_mode="run",
                allow_rebuild=True, confirm_fallback=_accept_rebuild,
            )
        except _RebuildRolledBack as exc:
            outcome = exc
        saved = pdf.with_name(pdf.stem + "_saved.pdf")
        model.save_as(str(saved))
        return outcome, saved
    finally:
        model.close()


def _lines(pdf: Path, *, skip: tuple[str, ...] = _FIXED, ymax: float = 10_000.0):
    """``(text, bbox)`` of the page's lines except the fixed ones, top to bottom."""
    doc = fitz.open(str(pdf))
    try:
        out = []
        for block in doc[0].get_text("dict")["blocks"]:
            for line in block.get("lines", ()):
                text = "".join(s["text"] for s in line["spans"]).strip()
                box = fitz.Rect(line["bbox"])
                if text and text not in skip and box.y0 < ymax:
                    out.append((text, box))
        return sorted(out, key=lambda t: (round(t[1].y0, 1), t[1].x0))
    finally:
        doc.close()


def _fixed_rect(pdf: Path, text: str) -> fitz.Rect:
    doc = fitz.open(str(pdf))
    try:
        for block in doc[0].get_text("dict")["blocks"]:
            for line in block.get("lines", ()):
                for span in line["spans"]:
                    if span["text"].strip() == text:
                        return fitz.Rect(span["bbox"])
    finally:
        doc.close()
    raise AssertionError(f"{text!r} not on the page")


def _glyphs(pdf: Path, y0: float, y1: float, x0: float = -1.0, x1: float = 10_000.0):
    """``(code, origin)`` of every glyph whose origin lies in the box, in
    drawing order (``get_texttrace``)."""
    doc = fitz.open(str(pdf))
    try:
        return [
            (ch[0], fitz.Point(ch[2]))
            for span in doc[0].get_texttrace()
            for ch in span["chars"]
            if y0 <= ch[2][1] <= y1 and x0 <= ch[2][0] < x1
        ]
    finally:
        doc.close()


def _text_of(glyphs) -> str:
    return "".join(chr(code) for code, _o in glyphs)


# ---------------------------------------------------------------------------
# multicolumn.pdf: the owner's case
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not MULTICOLUMN.exists(), reason="test_files multicolumn.pdf missing")
@pytest.mark.parametrize("engine", _ENGINES)
def test_multicolumn_title_wraps_at_its_hyphen(tmp_path: Path, engine: str) -> None:
    """``Two-Column`` -> ``Two-Colunm`` (a wider substitute word against the
    untouched ``Document``) becomes ``Two-`` / ``Colunm``: the hyphen ends the
    first line, the second line starts at the same x, the neighbour has not
    moved and nothing is drawn over it; the saved file says the same."""
    pdf = tmp_path / "multicolumn.pdf"
    shutil.copy(MULTICOLUMN, pdf)
    before_document = _fixed_rect(pdf, "Document")
    outcome, saved = _edit(pdf, "Two-Column", "Two-Colunm", engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    # The title block: everything left of ``Document`` above the author line.
    title = [
        (t, b) for t, b in _lines(saved, skip=_FIXED, ymax=200.0) if b.x0 < before_document.x0 - 5
    ]
    assert [t for t, _b in title] == ["Two-", "Colunm"], title
    first, second = title[0][1], title[1][1]
    assert abs(first.x0 - second.x0) < 0.5, "the wrapped line starts at the title's x"
    assert second.y0 >= first.y1 - 1.0, "the second line sits below the first"
    assert first.x1 <= before_document.x0 + 0.5, "the first line stays left of Document"
    assert second.x1 <= before_document.x0 + 0.5
    moved = _fixed_rect(saved, "Document")
    assert all(abs(a - b) < 0.01 for a, b in zip(moved, before_document)), "the neighbour moved"
    left = _glyphs(saved, first.y0, second.y1, x1=before_document.x0 - 1)
    assert _text_of(left) == "Two-Colunm", "no character added or lost, no hyphen inserted"
    assert [c for c, _o in left].count(0x2D) == 1
    # The hyphen is the last glyph of the first line.
    line1_y = min(o.y for _c, o in left)
    line1 = [c for c, o in left if abs(o.y - line1_y) < 1.0]
    assert chr(line1[-1]) == "-", line1


# ---------------------------------------------------------------------------
# Synthetic line against a neighbour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", _ENGINES)
@pytest.mark.parametrize("hyphen", ["-", "‐"])
def test_hyphenated_word_wraps_after_its_hyphen_against_a_neighbour(
    tmp_path: Path, engine: str, hyphen: str
) -> None:
    """``ab`` -> ``ab-cdefghij`` (U+002D or U+2010) cannot stay on the line
    before ``NEXT``: it breaks after the hyphen, nothing is inserted or lost,
    ``NEXT`` stays, and the block below is pushed clear of the second line."""
    pdf = tmp_path / "hy.pdf"
    next_x = _synthetic_pdf(pdf)
    below_before = _fixed_rect(pdf, "Below line")
    outcome, saved = _edit(pdf, "ab", f"ab{hyphen}cdefghij", engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    lines = _lines(saved)
    assert [t for t, _b in lines] == [f"ab{hyphen}", "cdefghij"], lines
    first, second = lines[0][1], lines[1][1]
    assert abs(first.x0 - second.x0) < 0.5
    assert second.y0 >= first.y1 - 1.0
    assert first.x1 <= next_x + 0.5, "the first line must stay left of NEXT"
    assert _fixed_rect(saved, "NEXT").x0 == pytest.approx(next_x, abs=0.5)
    below = _fixed_rect(saved, "Below line")
    assert below.y0 >= second.y1 - 0.5, "Below line overlaps the wrapped line"
    assert below.y0 >= below_before.y0 - 0.5
    glyphs = _glyphs(saved, first.y0, second.y1, x1=next_x - 0.5)
    assert _text_of(glyphs) == f"ab{hyphen}cdefghij"
    assert sum(1 for c, _o in glyphs if c in _HYPHENS) == 1, "a hyphen was inserted"


@pytest.mark.parametrize("engine", _ENGINES)
def test_every_hyphen_may_break_but_none_is_added(tmp_path: Path, engine: str) -> None:
    """A word with several hyphens breaks only after them: every line but the
    last ends with a hyphen the user typed, and the glyphs read as typed."""
    pdf = tmp_path / "many.pdf"
    next_x = _synthetic_pdf(pdf)
    typed = "ab-cd-ef-gh-ij-kl"
    outcome, saved = _edit(pdf, "ab", typed, engine)
    assert outcome is EditTextResult.SUCCESS, outcome
    lines = _lines(saved)
    assert len(lines) >= 2, lines
    assert "".join(t for t, _b in lines) == typed
    assert all(t.endswith("-") for t, _b in lines[:-1]), lines
    assert all(b.x1 <= next_x + 0.5 for _t, b in lines), "a line runs into NEXT"
    top, bottom = lines[0][1].y0, lines[-1][1].y1
    assert _text_of(_glyphs(saved, top, bottom, x1=next_x - 0.5)) == typed
    assert _fixed_rect(saved, "Below line").y0 >= bottom - 0.5


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_non_breaking_hyphen_never_breaks(tmp_path: Path, engine: str) -> None:
    """U+2011 is NO-BREAK: ``ab`` -> ``ab`` U+2011 ``cdefghij`` stays on its line
    (shrunk, at most to 50 %) or is refused; there is never a line ending in it."""
    pdf = tmp_path / "nbh.pdf"
    next_x = _synthetic_pdf(pdf)
    outcome, saved = _edit(pdf, "ab", "ab‑cdefghij", engine)
    if isinstance(outcome, EditTextResult):
        assert outcome is EditTextResult.SUCCESS, outcome
        lines = _lines(saved)
        assert len(lines) == 1, f"a non-breaking hyphen was broken: {lines}"
        assert lines[0][0].replace("‑", "") == "abcdefghij"
        assert lines[0][1].x1 <= next_x + 0.5
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
        assert [t for t, _b in _lines(saved)] == ["ab"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_word_without_a_hyphen_keeps_shrinking_or_refusing(
    tmp_path: Path, engine: str
) -> None:
    """GUARD: no hyphen, no break -- ``ab`` -> ``abcdefghijk`` stays on one line
    (shrunk) or is refused, exactly as before the hyphen decision."""
    pdf = tmp_path / "nohy.pdf"
    next_x = _synthetic_pdf(pdf)
    outcome, saved = _edit(pdf, "ab", "abcdefghijk", engine)
    if isinstance(outcome, EditTextResult):
        lines = _lines(saved)
        assert [t for t, _b in lines] == ["abcdefghijk"], lines
        assert lines[0][1].x1 <= next_x + 0.5
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_first_segment_that_does_not_fit_is_not_broken(tmp_path: Path, engine: str) -> None:
    """GUARD: when even ``ab-`` is wider than the room before ``NEXT`` there is
    no break point that helps: shrink to one line or refuse, never overprint."""
    pdf = tmp_path / "tight.pdf"
    next_x = _synthetic_pdf(pdf, gap=0.0)
    outcome, saved = _edit(pdf, "ab", "ab-cdefghij", engine)
    # ``ab`` and ``NEXT`` abut, so they extract as one line: drop NEXT's letters.
    lines = [(t.replace("NEXT", ""), b) for t, b in _lines(saved) if t != "NEXT"]
    if isinstance(outcome, EditTextResult):
        assert "".join(t for t, _b in lines) == "ab-cdefghij"
        edit_glyphs = _glyphs(saved, 650.0, 725.0, x1=next_x - 0.5)
        assert _text_of(edit_glyphs) == "ab-cdefghij", "glyphs run into NEXT"
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
        assert [t for t, _b in lines] == ["ab"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_no_room_below_means_no_break_even_at_a_hyphen(tmp_path: Path, engine: str) -> None:
    """GUARD (F14-VF4-WRAP): the paragraph's next line is 17 pt below and is not
    moved, so a second line has no room; the hyphenated word stays on its
    line (shrunk) or is refused -- it is never drawn over the next line."""
    pdf = tmp_path / "noroom.pdf"
    next_x = _synthetic_pdf(pdf, same_block=True)
    below_before = _fixed_rect(pdf, "second line untouched")
    outcome, saved = _edit(pdf, "ab", "ab-cdefghij", engine)
    assert _fixed_rect(saved, "second line untouched") == below_before
    if isinstance(outcome, EditTextResult):
        lines = _lines(saved)
        assert [t for t, _b in lines] == ["ab-cdefghij"], lines
        assert lines[0][1].x1 <= next_x + 0.5
        assert lines[0][1].y1 <= below_before.y0 + 1.0
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_hyphen_that_opens_the_word_is_not_a_break(tmp_path: Path, engine: str) -> None:
    """``ab`` -> ``-abcdefghij``: a break after the leading hyphen would leave a
    line of just ``-``.  The word stays whole (one shrunk line) or is refused."""
    pdf = tmp_path / "lead.pdf"
    next_x = _synthetic_pdf(pdf)
    outcome, saved = _edit(pdf, "ab", "-abcdefghij", engine)
    lines = _lines(saved)
    assert "-" not in [t for t, _b in lines], f"a lone hyphen line: {lines}"
    if isinstance(outcome, EditTextResult):
        assert outcome is EditTextResult.SUCCESS, outcome
        assert [t for t, _b in lines] == ["-abcdefghij"], lines
        assert lines[0][1].x1 <= next_x + 0.5
    else:
        assert outcome.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, outcome
        assert [t for t, _b in lines] == ["ab"]


def test_a_hyphen_opening_the_word_does_not_stop_a_later_hyphen_breaking(
    tmp_path: Path,
) -> None:
    """``-ab-cdefghij``: the leading hyphen is glued to ``ab``, the second one
    still breaks (``-ab-`` / ``cdefghij``)."""
    pdf = tmp_path / "lead2.pdf"
    next_x = _synthetic_pdf(pdf)
    outcome, saved = _edit(pdf, "ab", "-ab-cdefghij", "legacy")
    assert outcome is EditTextResult.SUCCESS, outcome
    lines = _lines(saved)
    assert [t for t, _b in lines] == ["-ab-", "cdefghij"], lines
    assert lines[0][1].x1 <= next_x + 0.5


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_soft_hyphen_is_not_turned_into_a_drawn_hyphen(tmp_path: Path, engine: str) -> None:
    """GUARD (never insert a hyphen): MuPDF draws a hyphen where it breaks at a
    soft hyphen.  The edit must not end with a hyphen the user never typed."""
    pdf = tmp_path / "soft.pdf"
    _synthetic_pdf(pdf)
    outcome, saved = _edit(pdf, "ab", "ab­cdefghij", engine)
    glyphs = _glyphs(saved, 0.0, 10_000.0)
    assert not any(c in _HYPHENS for c, _o in glyphs), "a hyphen was drawn"
    if not isinstance(outcome, EditTextResult):
        assert [t for t, _b in _lines(saved)] == ["ab"]


# ---------------------------------------------------------------------------
# The markup: one chokepoint shared by the commit and the live preview
# ---------------------------------------------------------------------------


def _wrap_box(html: str, width: float) -> list[str] | None:
    """Lines MuPDF lays ``html`` out in a ``width`` pt wide box; ``None`` when
    it does not fit unshrunk."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        spare, _scale = page.insert_htmlbox(
            fitz.Rect(50, 50, 50 + width, 250), html,
            css="span { font-size: 14px; }", scale_low=1,
        )
        if spare < 0:
            return None
        words = sorted(page.get_text("words"), key=lambda w: (round(w[1]), w[0]))
        rows: dict[int, list[str]] = {}
        for w in words:
            rows.setdefault(round(w[1]), []).append(w[4])
        return [" ".join(v) for _k, v in sorted(rows.items())]
    finally:
        doc.close()


@pytest.fixture()
def html_model():
    model = PDFModel()
    try:
        yield model
    finally:
        model.close()


def test_markup_of_a_leading_hyphen_word_cannot_break_after_the_hyphen(html_model) -> None:
    """The one place the break is decided: ``-Columnnnn`` that does not fit is
    reported as not fitting; it does not become ``-`` / ``Columnnnn``."""
    inner = html_model._convert_text_to_html("x-Columnnnn", 14.0, (0, 0, 0), latin_font="helv")
    lead = html_model._convert_text_to_html("-Columnnnn", 14.0, (0, 0, 0), latin_font="helv")
    broken = [
        rows for rows in (_wrap_box(lead, float(w)) for w in range(40, 140, 2))
        if rows is not None and len(rows) > 1
    ]
    assert not broken, f"the leading hyphen was broken: {broken[:1]}"
    # ... while an inner hyphen still breaks (the decision itself).
    wrapped = [r for r in (_wrap_box(inner, float(w)) for w in range(40, 140, 2)) if r]
    assert ["x-", "Columnnnn"] in wrapped, wrapped


def test_markup_of_numbers_and_bullets_is_unchanged(html_model) -> None:
    """GUARD: only a hyphen that opens a word and is followed by a non-digit
    gets the no-break wrapper; ``-5``, ``- item`` and ``ab-cd`` stay as they were."""
    for text in ("-5", "- item", "ab-cd", "a -- b", "--", "-"):
        html = html_model._convert_text_to_html(text, 14.0, (0, 0, 0), latin_font="helv")
        assert "nowrap" not in html, (text, html)
    marked = html_model._convert_text_to_html("-abc", 14.0, (0, 0, 0), latin_font="helv")
    assert "nowrap" in marked


def test_multi_style_markup_has_the_same_rule(html_model) -> None:
    """The paragraph-mode builder goes through the same rule."""
    span = SimpleNamespace(
        text="ab", color=(0.0, 0.0, 0.0), bbox=fitz.Rect(0, 0, 10, 10),
        block_idx=0, line_idx=0, span_idx=0,
    )
    assert "nowrap" in html_model._build_multi_style_html("-abc", [span], (0.0, 0.0, 0.0))
    assert "nowrap" not in html_model._build_multi_style_html("ab-cd", [span], (0.0, 0.0, 0.0))
