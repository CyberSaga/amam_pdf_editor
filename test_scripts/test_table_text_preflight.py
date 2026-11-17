"""Card A3b: the no-text preflight of ``find_table_rects`` and its typed failure (pure, no Qt)."""
from __future__ import annotations

import fitz
import pytest

from model import table_objects
from model.pdf_model import PDFModel


def _draw_table(page: fitz.Page, origin=(100, 200), rows: int = 4, cols: int = 3, *, text: bool = True) -> None:
    for r in range(rows):
        for c in range(cols):
            cell = fitz.Rect(
                origin[0] + c * 120, origin[1] + r * 30, origin[0] + (c + 1) * 120, origin[1] + (r + 1) * 30
            )
            page.draw_rect(cell, color=(0, 0, 0), width=1)
            if text:
                page.insert_text((cell.x0 + 5, cell.y0 + 20), f"R{r}C{c}", fontsize=11)


def _scratch(path, build, *, rotation: int = 0, crop: tuple | None = None) -> fitz.Document:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        build(page)
        if crop is not None:
            page.set_cropbox(fitz.Rect(*crop))
        if rotation:
            page.set_rotation(rotation)
        doc.save(path)
    return fitz.open(str(path))


def _sheet_grid(page: fitz.Page) -> None:
    _draw_table(page, origin=(10, 10), rows=26, cols=4, text=True)


def _no_text(page: fitz.Page) -> None:
    _draw_table(page, text=False)


CASES = {
    "plain": (_draw_table, 0, None),
    "rot90": (_draw_table, 90, None),
    "rot270": (_draw_table, 270, None),
    "cropped": (_draw_table, 0, (50, 150, 550, 700)),
    "cropped_rot90": (_draw_table, 90, (50, 150, 550, 700)),
    "cropped_rot270": (_draw_table, 270, (50, 150, 550, 700)),
    "page_sized_grid": (_sheet_grid, 0, None),
    "no_text": (_no_text, 0, None),
}


@pytest.mark.parametrize("name", list(CASES))
def test_preflight_never_changes_a_result(tmp_path, monkeypatch, name):
    build, rotation, crop = CASES[name]
    with _scratch(tmp_path / "a.pdf", build, rotation=rotation, crop=crop) as doc:
        with_preflight = table_objects.find_table_rects(doc[0])
    with _scratch(tmp_path / "b.pdf", build, rotation=rotation, crop=crop) as doc:
        monkeypatch.setattr(table_objects, "page_has_table_text", lambda page: True)
        without = table_objects.find_table_rects(doc[0])
    assert with_preflight == without


def test_textless_table_never_calls_find_tables(tmp_path, monkeypatch):
    def boom(self, *a, **k):
        raise AssertionError("find_tables must not run on a page with no text")

    monkeypatch.setattr(fitz.Page, "find_tables", boom)
    with _scratch(tmp_path / "t.pdf", _no_text) as doc:
        assert table_objects.page_has_table_text(doc[0]) is False
        assert table_objects.find_table_rects(doc[0]) == []


def test_page_with_text_calls_find_tables(tmp_path, monkeypatch):
    calls = []
    real = fitz.Page.find_tables

    def spy(self, *a, **k):
        calls.append(True)
        return real(self, *a, **k)

    monkeypatch.setattr(fitz.Page, "find_tables", spy)
    with _scratch(tmp_path / "t.pdf", _draw_table) as doc:
        assert table_objects.page_has_table_text(doc[0]) is True
        assert len(table_objects.find_table_rects(doc[0])) == 1
    assert calls == [True]


def test_find_tables_returning_none_raises_typed_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(fitz.Page, "find_tables", lambda self, *a, **k: None)
    with _scratch(tmp_path / "t.pdf", _draw_table) as doc:
        with pytest.raises(table_objects.TableDetectionFailed):
            table_objects.find_table_rects(doc[0])


def test_exceptions_propagate_out_of_find_table_rects(tmp_path, monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError("library failure")

    monkeypatch.setattr(fitz.Page, "find_tables", boom)
    with _scratch(tmp_path / "t.pdf", _draw_table) as doc:
        with pytest.raises(RuntimeError):
            table_objects.find_table_rects(doc[0])


def test_table_rects_on_a_raising_scratch_page_stores_nothing(tmp_path, monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError("library failure")

    monkeypatch.setattr(fitz.Page, "find_tables", boom)
    model = PDFModel()
    try:
        with fitz.open() as doc:
            _draw_table(doc.new_page(width=595, height=842))
            doc.save(tmp_path / "m.pdf")
        model.open_pdf(str(tmp_path / "m.pdf"))
        assert table_objects.table_rects(model, 1) == []
        assert table_objects.cached_table_rects(model, 1) is None
    finally:
        model.close()


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_preflight_restores_glyph_heights_rotation_and_mediabox(tmp_path, rotation):
    with _scratch(tmp_path / "t.pdf", _draw_table, rotation=rotation, crop=(50, 150, 550, 700)) as doc:
        page = doc[0]
        before_mediabox = tuple(page.mediabox)
        before_crop = tuple(page.cropbox)
        before_small = bool(fitz.TOOLS.set_small_glyph_heights())
        assert table_objects.page_has_table_text(page) is True
        assert bool(fitz.TOOLS.set_small_glyph_heights()) is before_small
        page = doc[0]
        assert page.rotation == rotation
        assert tuple(page.mediabox) == before_mediabox
        assert tuple(page.cropbox) == before_crop


def test_preflight_restores_state_when_the_text_step_raises(tmp_path, monkeypatch):
    with _scratch(tmp_path / "t.pdf", _draw_table, rotation=90) as doc:
        page = doc[0]
        before_small = bool(fitz.TOOLS.set_small_glyph_heights())

        def boom(self, *a, **k):
            raise RuntimeError("textpage failure")

        monkeypatch.setattr(fitz.Page, "get_textpage", boom)
        with pytest.raises(RuntimeError):
            table_objects.page_has_table_text(page)
        assert bool(fitz.TOOLS.set_small_glyph_heights()) is before_small
        assert doc[0].rotation == 90
