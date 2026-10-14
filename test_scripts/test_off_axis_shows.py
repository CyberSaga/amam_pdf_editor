"""S17-WMARK-UNDER: ``model.off_axis_shows`` puts back the turned (watermark)
text a text redaction erased by its glyph box, and only that."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.pdf_text_edit as pte  # noqa: E402
from model.off_axis_shows import read_streams, restore_turned_shows  # noqa: E402
from model.pdf_text_edit import _is_axis_aligned_dir, _page_glyphs, _redact_owned_glyphs  # noqa: E402

PIVOT = fitz.Point(120.0, 350.0)  # the 60 pt glyph boxes hold the word at (110, 300)
GREY = (0.85, 0.85, 0.85)


def _page_with_word(doc: fitz.Document, *, per_glyph: bool = False, via_form: bool = False):
    """``Name:`` and ``John`` on one line, a 45-degree ``DRAFT COPY`` through
    them, a line below."""
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 300), "Name:", fontsize=12, fontname="helv")
    page.insert_text((110, 300), "John", fontsize=12, fontname="helv")
    if via_form:
        mark = fitz.open()
        mark_page = mark.new_page(width=595, height=842)
        mark_page.insert_text(PIVOT, "DRAFT COPY", fontsize=60, fontname="helv", color=GREY,
                              morph=(PIVOT, fitz.Matrix(45)))
        page.show_pdf_page(page.rect, mark, 0)
    elif per_glyph:
        font = fitz.Font("helv")
        along = 0.0
        for ch in "DRAFT COPY":
            where = fitz.Point(
                PIVOT.x + along * math.cos(math.radians(45)),
                PIVOT.y - along * math.sin(math.radians(45)),
            )
            if ch != " ":
                page.insert_text(where, ch, fontsize=60, fontname="helv", color=GREY,
                                 morph=(where, fitz.Matrix(45)))
            along += font.text_length(ch, fontsize=60)
    else:
        page.insert_text(PIVOT, "DRAFT COPY", fontsize=60, fontname="helv", color=GREY,
                         morph=(PIVOT, fitz.Matrix(45)))
    page.insert_text((72, 330), "Next paragraph line", fontsize=12, fontname="helv")
    return page


def _erase_john(page: fitz.Page):
    before = _page_glyphs(page)
    owned = [g for g in before if g.key[0] in "John" and _is_axis_aligned_dir(g.direction)
             and 108.0 < g.origin[0] < 140.0 and 295.0 < g.origin[1] < 305.0]
    assert len(owned) == 4
    return before, owned, _redact_owned_glyphs(page, before, owned, [])


def _turned(page: fitz.Page) -> list[tuple[str, float, float]]:
    return sorted(
        (g.key[0], round(g.origin[0], 1), round(g.origin[1], 1))
        for g in _page_glyphs(page) if not _is_axis_aligned_dir(g.direction)
    )


def _text(page: fitz.Page) -> list[str]:
    return sorted(w[4] for w in page.get_text("words"))


@pytest.mark.parametrize("per_glyph", [False, True])
def test_the_word_goes_and_every_turned_glyph_stays_in_its_own_drawing_order(
    per_glyph: bool,
) -> None:
    """One show for the whole watermark (partly erased, repaired show by show)
    or one show per glyph (erased shows are gone from the stream, repaired as
    blocks): the word is erased, the watermark is as written."""
    doc = fitz.open()
    try:
        page = _page_with_word(doc, per_glyph=per_glyph)
        turned = _turned(page)
        assert len(turned) >= 9
        contents = page.read_contents()
        _, _, outcome = _erase_john(page)
        assert list(outcome.survivors) == [] and list(outcome.lost_foreign) == [], outcome
        assert _turned(page) == turned
        assert "John" not in _text(page) and "Name:" in _text(page)
        assert "line" in _text(page)
        # drawing order: the watermark is still before the line below it
        after = page.read_contents()
        assert after.rindex(b"/helv 60 Tf") < after.rindex(b"Next paragraph line")
        assert contents.count(b"/helv 60 Tf") == after.count(b"/helv 60 Tf")
    finally:
        doc.close()


def test_a_watermark_in_a_form_xobject_is_reported_lost_not_hidden() -> None:
    """The repair reads the page's own streams only: a turned run inside a form
    stays erased, and the chokepoint says so (the edit is then refused)."""
    doc = fitz.open()
    try:
        page = _page_with_word(doc, via_form=True)
        _, _, outcome = _erase_john(page)
        assert list(outcome.survivors) == []
        assert sorted(outcome.lost_foreign) == ["D", "R"], outcome
    finally:
        doc.close()


def test_an_upright_run_lost_with_the_word_is_still_reported() -> None:
    """Horizontal untouched text keeps today's protection: a glyph of it under
    the old word's point is lost -> reported, and the turned text is not what
    decides it."""
    doc = fitz.open()
    try:
        page = _page_with_word(doc)
        page.insert_text((111, 300), "Z", fontsize=12, fontname="helv")
        before = _page_glyphs(page)
        owned = [g for g in before if g.key[0] in "John" and _is_axis_aligned_dir(g.direction)
                 and 108.0 < g.origin[0] < 140.0 and abs(g.origin[0] - 111.0) > 0.5]
        outcome = _redact_owned_glyphs(page, before, owned, [])
        assert "Z" in outcome.lost_foreign, outcome
    finally:
        doc.close()


def test_an_edited_run_that_is_itself_turned_gets_no_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the erased glyphs are turned too the box/ink argument does not hold
    (the word may really overlap another turned run): no repair is tried."""
    calls: list[int] = []
    monkeypatch.setattr(pte, "restore_turned_shows", lambda *a, **k: calls.append(1) or True)
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        where = fitz.Point(100, 400)
        page.insert_text(where, "Turned", fontsize=24, fontname="helv",
                         morph=(where, fitz.Matrix(45)))
        page.insert_text(where, "Mark", fontsize=60, fontname="helv", color=GREY,
                         morph=(where, fitz.Matrix(45)))
        before = _page_glyphs(page)
        owned = [g for g in before if g.size < 30.0 and not _is_axis_aligned_dir(g.direction)]
        assert owned
        _redact_owned_glyphs(page, before, owned, [])
        assert calls == []
    finally:
        doc.close()


def test_a_repair_that_changes_the_ink_count_is_a_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repair that put something twice is no repair: the chokepoint reports it."""
    doc = fitz.open()
    try:
        page = _page_with_word(doc)

        def duplicate(_doc: fitz.Document, target: fitz.Page, _before: object) -> bool:
            target.insert_text(PIVOT, "DRAFT COPY", fontsize=60, fontname="helv", color=GREY,
                               morph=(PIVOT, fitz.Matrix(45)))
            return True

        monkeypatch.setattr(pte, "restore_turned_shows", duplicate)
        _, _, outcome = _erase_john(page)
        assert list(outcome.lost_foreign), outcome
    finally:
        doc.close()


def test_a_page_without_turned_text_is_not_even_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pages that cannot need the repair pay nothing for it."""
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("streams read for a page with no turned text")

    monkeypatch.setattr(pte, "read_streams", boom)
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 100), "abc", fontsize=12, fontname="helv")
        page.insert_text((70, 100), "xyz", fontsize=12, fontname="helv")
        glyphs = _page_glyphs(page)
        owned = [g for g in glyphs if g.key[0] in "abc"]
        outcome = _redact_owned_glyphs(page, glyphs, owned, [])
        assert list(outcome.survivors) == [] and list(outcome.lost_foreign) == []
        assert page.get_text().split() == ["xyz"]
    finally:
        doc.close()


def test_restore_changes_nothing_when_the_streams_are_unchanged() -> None:
    doc = fitz.open()
    try:
        page = _page_with_word(doc)
        before = read_streams(doc, page)
        assert restore_turned_shows(doc, page, before) is False
        assert read_streams(doc, page) == before
    finally:
        doc.close()


_MIXED = (
    b"q BT /helv 12 Tf 1 0 0 1 72 542 Tm [<4e616d653a>]TJ ET "
    b".70711 .70711 -.70711 .70711 383.04374 59.25064 cm "
    b".85 .85 .85 rg BT /helv 60 Tf 1 0 0 1 120 492 Tm [<445241465420434f5059>]TJ ET Q"
)


def _mixed_page(doc: fitz.Document) -> tuple[fitz.Page, int]:
    """One stream, one ``q ... Q`` block holding an upright AND a turned show
    (so only the show-by-show repair applies)."""
    page = doc.new_page(width=595, height=842)
    page.insert_text((10, 10), ".", fontsize=1, fontname="helv")  # /helv resource
    xref = page.get_contents()[0]
    doc.update_stream(xref, _MIXED)
    return page, xref


def test_a_changed_turned_show_in_a_mixed_block_is_written_back_alone() -> None:
    doc = fitz.open()
    try:
        page, xref = _mixed_page(doc)
        before = read_streams(doc, page)
        damaged = _MIXED.replace(b"[<445241465420434f5059>]TJ", b"[-1444.0001(AFT COPY)]TJ")
        doc.update_stream(xref, damaged)
        assert restore_turned_shows(doc, page, before) is True
        assert read_streams(doc, page) == before
    finally:
        doc.close()


def test_restore_declines_when_the_redaction_split_a_turned_show() -> None:
    """A show the redaction cannot be paired with one-to-one is left as it is."""
    doc = fitz.open()
    try:
        page, xref = _mixed_page(doc)
        before = read_streams(doc, page)
        split = _MIXED.replace(
            b"[<445241465420434f5059>]TJ", b"[<44524146>]TJ [<5420434f5059>]TJ"
        )
        doc.update_stream(xref, split)
        current = read_streams(doc, page)
        assert restore_turned_shows(doc, page, before) is False
        assert read_streams(doc, page) == current
    finally:
        doc.close()


def test_a_block_the_redaction_emptied_comes_back_whole() -> None:
    """The redaction leaves ``q Q`` where every glyph of a block was erased."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        page.insert_text((10, 10), ".", fontsize=1, fontname="helv")
        xref = page.get_contents()[0]
        block = (
            b"q .70711 .70711 -.70711 .70711 383.04374 59.25064 cm .85 .85 .85 rg "
            b"BT /helv 60 Tf 1 0 0 1 120 492 Tm [<44>]TJ ET Q "
        )
        upright = b"q BT /helv 12 Tf 1 0 0 1 72 542 Tm [<4e>]TJ ET Q"
        doc.update_stream(xref, block + upright)
        before = read_streams(doc, page)
        doc.update_stream(xref, b"q Q " + upright)
        assert restore_turned_shows(doc, page, before) is True
        assert read_streams(doc, page) == before
    finally:
        doc.close()
