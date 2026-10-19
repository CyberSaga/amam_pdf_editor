"""D-RTL-GROW (owner decision after round 15): a right-to-left run grows LEFT.

When a Hebrew/Arabic word or run gets longer in an edit, its RIGHT edge (the
edge its reading starts at) stays where it was and the word grows to the left;
a shorter word shrinks toward that right edge.  The rule holds on every page
turn (measured in the page's VISUAL space), for every route that redraws an RTL
run (the consented legacy rebuild, a protected neighbour's replay, the
push-down), and the neighbour / margin walls are the ones on the LEFT.  A run
holding both directions follows its paragraph's base direction (the first
strong character of the text block, UAX#9 P2); a run with no RTL letter is
left-to-right and behaves exactly as before.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.pdf_controller import PDFController  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.font_stream_compaction import font_compaction_scope  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import _align_htmlbox_rect, _spans_grow_right_to_left  # noqa: E402
from model.rtl_text import grows_right_to_left  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402
from model.text_edit_refusal import TextEditRefusal, TextEditRefused  # noqa: E402
from view.text_editing import PreviewRenderer  # noqa: E402

SHALOM = "שלום"  # logical order, as typed
OLAM = "עולם"
_EDGE_TOL = 0.25  # pt: float32 glyph boxes on both sides of a translation
_INK_SLACK = 1.0  # pt: a glyph's ink may poke a little outside its advance box


def _accept_rebuild(_chain: tuple[str, ...]) -> bool:
    return True


def _is_hebrew(code: int) -> bool:
    return 0x0590 <= code <= 0x05FF


def _is_latin(code: int) -> bool:
    return 0x41 <= code <= 0x7A


def _model(pdf: Path) -> PDFModel:
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="legacy"))
    model.open_pdf(str(pdf))
    model.ensure_page_index_built(1)
    return model


def _hebrew_runs(model: PDFModel) -> list:
    return [
        r for r in model.block_manager.get_runs(0) if any(_is_hebrew(ord(c)) for c in r.text)
    ]


def _visual_glyphs(page: fitz.Page, keep=_is_hebrew) -> list[tuple[str, fitz.Rect, fitz.Point]]:
    """``(char, visual box, visual origin)`` of the glyphs ``keep`` selects,
    from ``get_texttrace`` (advance boxes), in the page's DISPLAYED space."""
    mat = page.rotation_matrix
    return [
        (chr(ch[0]), fitz.Rect(ch[3]) * mat, fitz.Point(ch[2]) * mat)
        for span in page.get_texttrace()
        for ch in span["chars"]
        if keep(ch[0])
    ]


def _extent(glyphs) -> fitz.Rect:
    rect = fitz.Rect(glyphs[0][1])
    for _c, box, _o in glyphs[1:]:
        rect |= box
    return rect


def _reading(glyphs) -> str:
    """The Hebrew letters as a reader meets them on the displayed page."""
    return "".join(c for c, box, _o in sorted(glyphs, key=lambda g: -g[1].x1))


def _ink_columns(page: fitz.Page, band: fitz.Rect, zoom: float = 3.0) -> list[float]:
    """Visual x (pt) of every pixel column holding ink inside ``band``."""
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    x0 = max(0, int(band.x0 * zoom))
    x1 = min(pix.width, int(band.x1 * zoom) + 1)
    y0 = max(0, int(band.y0 * zoom))
    y1 = min(pix.height, int(band.y1 * zoom) + 1)
    cols = []
    for px in range(x0, x1):
        for py in range(y0, y1):
            if min(pix.pixel(px, py)[:3]) < 128:
                cols.append(px / zoom)
                break
    return cols


def _rtl_pdf(path: Path, rotation: int) -> None:
    """One upright (as displayed) Hebrew word on a page turned by
    ``rotation``, drawn by MuPDF in a right-to-left paragraph, plus a Latin
    label well away from it."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if rotation:
        page.set_rotation(rotation)
    box = fitz.Rect(200, 300, 400, 330) if rotation in (0, 180) else fitz.Rect(280, 300, 310, 500)
    page.insert_htmlbox(box, f'<p dir="rtl">{SHALOM}</p>', css="p{font-size:14pt}", rotate=rotation)
    label = box + ((0, 120, 0, 120) if rotation in (0, 180) else (120, 0, 120, 0))
    page.insert_htmlbox(label, "<p>Below</p>", css="p{font-size:12pt}", rotate=rotation)
    doc.save(str(path), garbage=0)
    doc.close()


def _edit_run(model: PDFModel, run, new_text: str):
    try:
        return model.edit_text(
            1, fitz.Rect(run.bbox) * model.doc[0].rotation_matrix, new_text, font="helv",
            size=float(run.size), original_text=run.text, target_span_id=run.span_id,
            target_mode="run", allow_rebuild=True, confirm_fallback=_accept_rebuild,
        )
    except TextEditRefused as exc:
        return exc


_EDITS = {
    "grow_letter": lambda t: t + "ו",
    "grow_word": lambda t: t + " " + OLAM,
    "shrink": lambda t: t[:-1],
}


@pytest.mark.parametrize("edit", sorted(_EDITS))
@pytest.mark.parametrize("rotation", [0, 90, 180])
def test_rtl_rebuild_keeps_the_right_edge_and_grows_left(
    tmp_path: Path, rotation: int, edit: str
) -> None:
    """Grow and shrink a Hebrew word on an upright, a quarter-turned and a
    half-turned page: the displayed right edge and baseline stay, the left
    edge moves (left when longer, right when shorter), the letters read as
    typed, and no ink lands right of the old right edge."""
    pdf = tmp_path / f"rtl_{rotation}.pdf"
    _rtl_pdf(pdf, rotation)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        page = model.doc[0]
        before = _visual_glyphs(page)
        old = _extent(before)
        # the index run's own box is the same right edge
        run_visual = fitz.Rect(run.bbox) * page.rotation_matrix
        assert run_visual.x1 == pytest.approx(old.x1, abs=_EDGE_TOL), (run_visual, old)
        baseline = before[0][2].y
        new_text = _EDITS[edit](run.text)
        result = _edit_run(model, run, new_text)
        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        after = _visual_glyphs(page)
        assert _reading(after) == new_text.replace(" ", ""), (_reading(after), new_text)
        new = _extent(after)
        assert new.x1 == pytest.approx(old.x1, abs=_EDGE_TOL), (rotation, edit, old, new)
        assert all(abs(o.y - baseline) <= _EDGE_TOL for _c, _b, o in after), (baseline, after)
        if edit == "shrink":
            assert new.x0 > old.x0 + 2.0, (old, new)
        else:
            assert new.x0 < old.x0 - 2.0, (old, new)
        band = fitz.Rect(old.x0 - 80, old.y0, old.x1 + 80, old.y1)
        ink = _ink_columns(page, band)
        assert ink, "nothing drawn"
        assert max(ink) <= old.x1 + _INK_SLACK, (max(ink), old.x1)
        assert min(ink) >= new.x0 - _INK_SLACK, (min(ink), new.x0)
        assert any(g[0] == "B" for g in _visual_glyphs(page, keep=lambda c: chr(c) == "B"))
    finally:
        model.close()


def _neighbour_pdf(path: Path, side: str, gap: float = 4.0) -> fitz.Rect:
    """A Hebrew word (right edge at x=400 on an upright page) with a Latin
    word ``gap`` pt to its ``side``.  Returns the Hebrew word's box."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(
        fitz.Rect(200, 300, 401, 330), f'<p dir="rtl">{SHALOM}</p>', css="p{font-size:14pt}"
    )
    doc.save(str(path), garbage=0)
    doc.close()
    doc = fitz.open(str(path))
    page = doc[0]
    glyphs = _visual_glyphs(page)
    word = _extent(glyphs)
    baseline = glyphs[0][2].y
    font = fitz.Font("helv")
    if side == "left":
        text = "LEFT"
        x = word.x0 - gap - font.text_length(text, fontsize=14)
    else:
        text = "RIGHT"
        x = word.x1 + gap
    page.insert_text((x, baseline), text, fontsize=14, fontname="helv")
    doc.save(str(path) + ".tmp", garbage=0)
    doc.close()
    Path(str(path) + ".tmp").replace(path)
    return word


def _latin_boxes(page: fitz.Page) -> list[fitz.Rect]:
    return [box for _c, box, _o in _visual_glyphs(page, keep=lambda c: 0x41 <= c <= 0x5A)]


@pytest.mark.parametrize("new_tail", [" " + OLAM, " " + OLAM + " " + SHALOM])
def test_rtl_growth_is_walled_by_the_neighbour_on_its_left(tmp_path: Path, new_tail: str) -> None:
    """The text a growing RTL word runs into is on its LEFT: it is shrunk or
    refused there, never drawn over it, and its right edge stays."""
    pdf = tmp_path / "rtl_left_neighbour.pdf"
    old = _neighbour_pdf(pdf, "left")
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        neighbour_before = _latin_boxes(model.doc[0])
        result = _edit_run(model, run, run.text + new_tail)
        page = model.doc[0]
        assert _latin_boxes(page) == neighbour_before, "the untouched neighbour moved"
        if isinstance(result, TextEditRefused):
            assert result.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, result
            assert _extent(_visual_glyphs(page)) == old
            return
        assert result is EditTextResult.SUCCESS, result
        after = _visual_glyphs(page)
        new = _extent(after)
        assert new.x1 == pytest.approx(old.x1, abs=_EDGE_TOL), (old, new)
        wall = max(box.x1 for box in neighbour_before)
        assert all(box.x0 >= wall - _EDGE_TOL for _c, box, _o in after), (wall, after)
        ink = _ink_columns(page, fitz.Rect(wall + _INK_SLACK, old.y0, old.x1 + 60, old.y1))
        assert max(ink) <= old.x1 + _INK_SLACK
    finally:
        model.close()


def test_rtl_growth_is_not_walled_by_text_on_its_right(tmp_path: Path) -> None:
    """Text right of an RTL word is behind its start: a longer word grows
    left at full size and leaves that text alone (it used to be the wall that
    shrank or refused the edit)."""
    pdf = tmp_path / "rtl_right_neighbour.pdf"
    old = _neighbour_pdf(pdf, "right")
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        neighbour_before = _latin_boxes(model.doc[0])
        new_text = run.text + " " + OLAM
        result = _edit_run(model, run, new_text)
        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        assert _latin_boxes(page) == neighbour_before
        after = _visual_glyphs(page)
        new = _extent(after)
        assert new.x1 == pytest.approx(old.x1, abs=_EDGE_TOL), (old, new)
        # full size: the new word is as tall as the old one
        assert new.height == pytest.approx(old.height, abs=_EDGE_TOL)
        assert max(box.x1 for _c, box, _o in after) < min(b.x0 for b in neighbour_before)
    finally:
        model.close()


def test_rtl_growth_stops_at_the_left_page_edge(tmp_path: Path) -> None:
    """Near the left page edge the left margin is the floor: the word is
    wrapped, shrunk or refused, never drawn off the page or rightwards."""
    pdf = tmp_path / "rtl_left_margin.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(
        fitz.Rect(20, 300, 101, 330), f'<p dir="rtl">{SHALOM}</p>', css="p{font-size:14pt}"
    )
    doc.save(str(pdf), garbage=0)
    doc.close()
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        old = _extent(_visual_glyphs(model.doc[0]))
        long_text = " ".join([run.text, OLAM, SHALOM, OLAM, SHALOM])
        result = _edit_run(model, run, long_text)
        page = model.doc[0]
        after = _visual_glyphs(page)
        if isinstance(result, TextEditRefused):
            assert result.reason is TextEditRefusal.TEXT_DOES_NOT_FIT, result
            assert _extent(after) == old
            return
        assert result is EditTextResult.SUCCESS, result
        new = _extent(after)
        assert new.x1 <= old.x1 + _EDGE_TOL, (old, new)
        assert new.x0 >= page.rect.x0, new
        ink = _ink_columns(page, fitz.Rect(0, old.y0 - 2, page.rect.x1, old.y1 + 60))
        assert max(ink) <= old.x1 + _INK_SLACK
    finally:
        model.close()


def test_ltr_rebuild_still_keeps_its_left_edge(tmp_path: Path) -> None:
    """GUARD (passes before the change): a left-to-right word keeps its left
    edge and grows right, whatever the RTL rule does."""
    pdf = tmp_path / "ltr.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(fitz.Rect(200, 300, 400, 330), "<p>Hello</p>", css="p{font-size:14pt}")
    doc.save(str(pdf), garbage=0)
    doc.close()
    model = _model(pdf)
    try:
        run = next(r for r in model.block_manager.get_runs(0) if r.text == "Hello")
        old = _extent(_visual_glyphs(model.doc[0], keep=_is_latin))
        result = _edit_run(model, run, "Hello wide world")
        assert result is EditTextResult.SUCCESS, result
        new = _extent(_visual_glyphs(model.doc[0], keep=_is_latin))
        assert new.x0 == pytest.approx(old.x0, abs=_EDGE_TOL), (old, new)
        assert new.x1 > old.x1 + 20.0
    finally:
        model.close()


# --- the direction rule -----------------------------------------------------------


@pytest.mark.parametrize(
    ("run_text", "paragraph", "expected"),
    [
        (SHALOM, None, True),  # pure RTL
        ("عربي", None, True),  # Arabic letters (bidi class AL)
        (SHALOM + ".", "Hello " + SHALOM + ".", True),  # RTL + neutrals only: RTL
        ("Hello", SHALOM + " Hello", False),  # no RTL letter: unchanged LTR
        ("2026", SHALOM + " 2026", False),  # digits only: unchanged LTR
        ("", SHALOM, False),
        (None, SHALOM, False),
        ("abc" + SHALOM, SHALOM + " abc" + SHALOM, True),  # mixed: RTL paragraph
        ("abc" + SHALOM, "Intro abc" + SHALOM, False),  # mixed: LTR paragraph
        (SHALOM + "abc", "123 " + SHALOM + "abc", True),  # paragraph's first STRONG char
        ("abc" + SHALOM, None, False),  # mixed, no paragraph: the run's own first strong
        (SHALOM + "abc", "", True),
    ],
)
def test_grows_right_to_left_rule(run_text, paragraph, expected) -> None:
    assert grows_right_to_left(run_text, paragraph) is expected


# --- the shared placement measure -------------------------------------------------


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_align_htmlbox_rect_puts_the_right_to_left_end_on_the_anchor(rotate: int) -> None:
    """``_align_htmlbox_rect(rtl=True)`` lands the text's right-to-left START
    (its far end along the LTR writing direction: the right edge upright) on
    the anchor, in every rotation."""
    anchor = fitz.Point(250.0, 400.0)
    css = "span { font-size: 14pt; }\nbody { direction: rtl; }"
    html = f"<span>{SHALOM} {OLAM}</span>"
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        box = fitz.Rect(100, 100, 400, 400) if rotate in (0, 180) else fitz.Rect(150, 200, 350, 600)
        placed = _align_htmlbox_rect(
            page, box, html, css, origin=anchor, rotate=rotate, scale_low=1, rtl=True
        )
        assert placed.width == pytest.approx(box.width) and placed.height == pytest.approx(box.height)
        page.insert_htmlbox(placed, html, css=css, rotate=rotate)
        hebrew = [ch for s in page.get_texttrace() for ch in s["chars"] if _is_hebrew(ch[0])]
        boxes = [fitz.Rect(ch[3]) for ch in hebrew]
        origins = [ch[2] for ch in hebrew]
    finally:
        doc.close()
    assert len(boxes) == 8
    # htmlbox ``rotate`` r turns the text by -r: 0 -> +x, 90 -> -y, 180 -> -x, 270 -> +y
    end = {
        0: max(b.x1 for b in boxes),
        90: min(b.y0 for b in boxes),
        180: min(b.x0 for b in boxes),
        270: max(b.y1 for b in boxes),
    }[rotate]
    along, across = (anchor.x, anchor.y) if rotate in (0, 180) else (anchor.y, anchor.x)
    assert end == pytest.approx(along, abs=0.1), (rotate, end)
    base = {o[1] for o in origins} if rotate in (0, 180) else {o[0] for o in origins}
    assert all(abs(v - across) <= 0.1 for v in base), (rotate, base)


# --- replays: protected neighbours and the push-down ------------------------------


def _condensed_rtl_pdf(path: Path, *, above: str | None = None) -> None:
    """A Hebrew word drawn tighter than its font's advances (char spacing in
    the htmlbox form), so a replay at the natural width is ~4.5 pt wider:
    which of its edges the replay keeps becomes visible."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if above is not None:
        page.insert_text((72, 100), above, fontsize=12, fontname="helv")
    page.insert_htmlbox(
        fitz.Rect(200, 120, 400, 160), f'<p dir="rtl">{SHALOM}</p>', css="p{font-size:14pt}"
    )
    for xref, name, *_rest in page.get_xobjects():
        if name == "fullpage":
            stream = doc.xref_stream(xref)
            doc.update_stream(xref, stream.replace(b"BT", b"BT 1.5 Tc", 1))
    doc.save(str(path), garbage=0)
    doc.close()


def test_protected_rtl_neighbour_replay_keeps_its_right_edge(tmp_path: Path) -> None:
    """A replayed protected Hebrew neighbour is anchored on its right edge
    (the edge its reading starts at), and the in-place validation measures
    that same edge."""
    pdf = tmp_path / "rtl_condensed.pdf"
    _condensed_rtl_pdf(pdf)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        out = fitz.open()
        try:
            page = out.new_page(width=595, height=842)
            with font_compaction_scope(out):
                model._replay_protected_spans(page, [run])
            boxes = [box for _c, box, _o in _visual_glyphs(page)]
            assert len(boxes) == 4
            assert max(b.x1 for b in boxes) == pytest.approx(float(run.bbox.x1), abs=_EDGE_TOL)
            # natural width: the replay is wider than the condensed original, to the left
            assert min(b.x0 for b in boxes) < float(run.bbox.x0) - 2.0
            assert model._validate_protected_spans(page, [run])
        finally:
            out.close()
    finally:
        model.close()


def test_push_down_keeps_a_right_to_left_line_on_its_right_edge(tmp_path: Path) -> None:
    pdf = tmp_path / "rtl_pushdown.pdf"
    _condensed_rtl_pdf(pdf, above="Edited line")
    model = _model(pdf)
    try:
        page = model.doc[0]
        before = _visual_glyphs(page)
        old = _extent(before)
        with font_compaction_scope(model.doc):
            model._push_down_overlapping_text(
                page, fitz.Rect(page.rect), above_y=105.0, new_bottom=170.0,
                edit_x0=60.0, edit_x1=500.0,
            )
        after = _visual_glyphs(page)
        assert len(after) == 4
        new = _extent(after)
        assert new.x1 == pytest.approx(old.x1, abs=_EDGE_TOL), (old, new)
        assert new.y0 > old.y0 + 5.0
        assert _reading(after) == SHALOM
    finally:
        model.close()


@pytest.mark.parametrize("dx", [-30.0, 200.0])
def test_rtl_drag_translates_the_right_edge(tmp_path: Path, dx: float) -> None:
    """A dragged RTL edit is a translation of its START edge (the right
    edge): it lands exactly ``dx`` / 50 pt away, and when the page clamp trims
    the dragged rect at the page edge the right edge goes to the clamped edge
    (on the page), not past it."""
    pdf = tmp_path / "rtl_drag.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        page = model.doc[0]
        before = _visual_glyphs(page)
        old = _extent(before)
        baseline = before[0][2].y
        moved = fitz.Rect(run.bbox) + (dx, 50.0, dx, 50.0)
        result = model.edit_text(
            1, fitz.Rect(run.bbox), run.text + "ו", font="helv", size=float(run.size),
            original_text=run.text, target_span_id=run.span_id, target_mode="run",
            new_rect=moved, allow_rebuild=True, confirm_fallback=_accept_rebuild,
        )
        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        after = _visual_glyphs(page)
        new = _extent(after)
        want_right = min(float(run.bbox.x1) + dx, float(page.rect.x1) - 5.0)
        assert new.x1 == pytest.approx(want_right, abs=_EDGE_TOL), (dx, old, new)
        assert new.x1 <= float(page.rect.x1)
        assert new.x0 < new.x1 - old.width - 2.0  # one letter longer, to the left
        assert all(abs(o.y - (baseline + 50.0)) <= _EDGE_TOL for _c, _b, o in after), after
        assert _reading(after) == run.text + "ו"
    finally:
        model.close()


# --- the live htmlbox preview lays an RTL run out on the same edge (D-RTL-PREVIEW) ---

_PREVIEW_BOX = fitz.Rect(200, 300, 400, 330)  # the box _rtl_pdf draws the word in
_PREVIEW_SCALE = 4.0


def _preview_ink_right_pt(image) -> float:
    """Right edge (pt, inside the box) of the opaque pixels of a preview frame."""
    width, height = image.width(), image.height()
    last = -1
    for px in range(width):
        if any(image.pixelColor(px, py).alpha() > 128 for py in range(height)):
            last = px
    assert last >= 0, "the preview drew nothing"
    return (last + 1) / _PREVIEW_SCALE


def _preview_kwargs() -> dict[str, object]:
    """The ``PreviewRenderer.render`` arguments every preview here shares: the
    word's own box (``_PREVIEW_BOX``) at 14 pt, upright, drawn at 4x."""
    return dict(
        font_name="helv", font_size=14.0, color=(0.0, 0.0, 0.0),
        rect_pt=fitz.Rect(0, 0, _PREVIEW_BOX.width, _PREVIEW_BOX.height),
        rotation=0, render_scale=_PREVIEW_SCALE, line_height=16.8,
    )


def _render_preview(builder, text: str, member_spans):
    renderer = PreviewRenderer(build_preview_html=builder)
    return renderer.render(text=text, member_spans=member_spans, **_preview_kwargs())


def _controller_builder(model: PDFModel):
    stand_in = SimpleNamespace(model=model)

    def build(**kwargs):
        return PDFController.build_insert_preview_html(stand_in, **kwargs)

    return build


def _preview_css(build, text: str, spans) -> str:
    """The CSS the editor's preview markup gets for ``text`` typed over ``spans``."""
    return build(
        text=text, font_size=14.0, color=(0.0, 0.0, 0.0), font_name="helv",
        line_height=16.8, member_spans=spans,
    )[0]


@pytest.mark.parametrize("text", [SHALOM, SHALOM + " " + OLAM])
def test_preview_of_an_rtl_edit_ends_on_the_edge_the_commit_keeps(tmp_path: Path, text: str) -> None:
    """The legacy preview frame of a Hebrew run keeps the box's RIGHT edge, the
    edge the committed rebuild keeps (D-RTL-GROW): the typed word does not
    jump to the left edge of the editor frame."""
    pdf = tmp_path / "rtl_preview.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        result = _edit_run(model, run, text)
        assert result is EditTextResult.SUCCESS, result
        committed_right = max(b.x1 for _c, b, _o in _visual_glyphs(model.doc[0]))
        # the preview is drawn from the unedited index (the editor is still open)
        image = _render_preview(_controller_builder(model), text, [run])
        right = _preview_ink_right_pt(image) + _PREVIEW_BOX.x0
        assert right == pytest.approx(committed_right, abs=_INK_SLACK + 1.0), (right, committed_right)
    finally:
        model.close()


def test_preview_markup_direction_follows_the_edited_run(tmp_path: Path) -> None:
    """Only an edit of a right-to-left run gets the RTL base direction: an
    add_new box (no member runs), a Latin run and a run of digits stay LTR, and
    the direction needs BOTH the run and the typed text to be right-to-left
    (the commit rule, F17-RTL-LATIN)."""
    pdf = tmp_path / "rtl_preview_dir.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (hebrew,) = _hebrew_runs(model)
        latin = next(r for r in model.block_manager.get_runs(0) if r.text.strip() == "Below")
        build = _controller_builder(model)

        assert "direction: rtl" in _preview_css(build, SHALOM, [hebrew])
        assert "direction: rtl" not in _preview_css(build, "abc", [hebrew])  # Latin text: left-to-right
        assert "direction: rtl" not in _preview_css(build, SHALOM, None)  # add_new: no member runs
        assert "direction: rtl" not in _preview_css(build, SHALOM, [])
        assert "direction: rtl" not in _preview_css(build, SHALOM, [latin])
        assert "direction: rtl" not in _preview_css(build, "Below", [latin])
    finally:
        model.close()


def test_preview_renderer_model_shim_lays_out_rtl_too(tmp_path: Path) -> None:
    """The ``PreviewRenderer(model=...)`` compatibility path builds its markup
    from the model's builders; it follows the same direction rule."""
    pdf = tmp_path / "rtl_preview_shim.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        renderer = PreviewRenderer(model=model)
        image = renderer.render(text=SHALOM, member_spans=[run], **_preview_kwargs())
        assert _preview_ink_right_pt(image) == pytest.approx(_PREVIEW_BOX.width, abs=_INK_SLACK + 1.0)
    finally:
        model.close()


def test_preview_frame_cache_does_not_cross_directions(tmp_path: Path) -> None:
    """One renderer serves editor after editor: the cached frame of a Hebrew
    run's text must not be shown for the same text typed into a new box."""
    pdf = tmp_path / "rtl_preview_cache.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        renderer = PreviewRenderer(build_preview_html=_controller_builder(model))
        kwargs = dict(text=SHALOM, **_preview_kwargs())
        rtl_right = _preview_ink_right_pt(renderer.render(member_spans=[run], **kwargs))
        ltr_right = _preview_ink_right_pt(renderer.render(member_spans=None, **kwargs))
        assert rtl_right > _PREVIEW_BOX.width - 3.0
        assert ltr_right < 60.0  # left-aligned: the add_new box
    finally:
        model.close()


# --- the direction follows the text that is DRAWN (F17-RTL-LATIN) ------------------


def _line_text_left_to_right(page: fitz.Page, y0: float, y1: float) -> str:
    """The characters whose box centre lies in ``[y0, y1]`` in visual (left to
    right) order -- what a reader sees on that line."""
    chars = [
        (box.x0, chr(code))
        for span in page.get_texttrace()
        for code, _g, _o, box_t, *_rest in span["chars"]
        for box in [fitz.Rect(box_t)]
        if y0 <= (box.y0 + box.y1) / 2 <= y1
    ]
    return "".join(c for _x, c in sorted(chars))


@pytest.mark.parametrize("new_text", ["Hello world.", "Price (USD)", "v1.2-beta!", "2026."])
def test_rtl_run_retyped_as_latin_is_laid_out_left_to_right(tmp_path: Path, new_text: str) -> None:
    """A Hebrew word retyped as text WITHOUT a right-to-left letter is a
    left-to-right run (``grows_right_to_left``'s first rule): the full stop,
    the exclamation mark and the brackets are drawn where they were typed, and
    the edit is not refused for the mirrored ``)``."""
    pdf = tmp_path / "rtl_to_latin.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        result = _edit_run(model, run, new_text)
        assert result is EditTextResult.SUCCESS, result
        page = model.doc[0]
        assert _line_text_left_to_right(page, 290, 345) == new_text
        assert new_text in page.get_text("text")
    finally:
        model.close()


@pytest.mark.parametrize(
    ("new_text", "expected"),
    [
        (SHALOM + "ו", True),  # still a Hebrew word
        (SHALOM + " " + OLAM, True),
        (SHALOM + ".", True),  # RTL letters plus neutrals only
        (SHALOM + " 2026", True),
        ("Hello world.", False),  # no RTL letter: left-to-right
        ("Price (USD)", False),
        ("2026", False),
        ("", False),
        (SHALOM + " Hello", True),  # mixed: the paragraph being edited is Hebrew
        ("Hello " + SHALOM, True),
    ],
)
def test_edit_direction_is_the_old_run_and_the_new_text(
    tmp_path: Path, new_text: str, expected: bool
) -> None:
    """``_spans_grow_right_to_left`` keeps the old run's direction as the
    anchor (an RTL run keeps its right edge) and asks the rule about the text
    that will be drawn.  ``new_text=None`` is the replay of an existing run."""
    pdf = tmp_path / "rtl_dir_rule.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (run,) = _hebrew_runs(model)
        latin = next(r for r in model.block_manager.get_runs(0) if r.text.strip() == "Below")
        assert _spans_grow_right_to_left(model, [run]) is True
        assert _spans_grow_right_to_left(model, [run], new_text) is expected
        # a Latin run stays left-to-right whatever it is retyped as
        assert _spans_grow_right_to_left(model, [latin], new_text) is False
    finally:
        model.close()


def test_preview_direction_follows_the_typed_text(tmp_path: Path) -> None:
    """The live preview frame uses the commit's rule: typing Latin text into a
    Hebrew run's editor gives the left-to-right frame the commit draws."""
    pdf = tmp_path / "rtl_preview_latin.pdf"
    _rtl_pdf(pdf, 0)
    model = _model(pdf)
    try:
        (hebrew,) = _hebrew_runs(model)
        build = _controller_builder(model)

        assert "direction: rtl" in _preview_css(build, SHALOM + " " + OLAM, [hebrew])
        assert "direction: rtl" not in _preview_css(build, "Hello world.", [hebrew])
        assert "direction: rtl" not in _preview_css(build, "Price (USD)", [hebrew])
        # the frame cache is keyed by the text, so it cannot cross directions
        renderer = PreviewRenderer(build_preview_html=build)
        kwargs = dict(member_spans=[hebrew], **_preview_kwargs())
        rtl_right = _preview_ink_right_pt(renderer.render(text=SHALOM, **kwargs))
        ltr_right = _preview_ink_right_pt(renderer.render(text="Hi", **kwargs))
        assert rtl_right > _PREVIEW_BOX.width - 3.0
        assert ltr_right < 60.0
    finally:
        model.close()
