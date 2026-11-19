"""Card A2 (plans/cad-vector-object-editing-handoff.md): the table probe never
changes the user's document (H1) and its cache is keyed on the page frame (H3)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import fitz
import pytest

from model import table_objects
from model.pdf_model import PDFModel

_PROBE = (
    Path(__file__).resolve().parent.parent
    / "plans"
    / "cad-vector-object-editing-probes"
    / "p17_object_digest_cost.py"
)


def _load_probe():
    spec = importlib.util.spec_from_file_location("p17_object_digest_cost", _PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _draw_table(page: fitz.Page) -> None:
    for r in range(4):
        for c in range(3):
            cell = fitz.Rect(100 + c * 120, 200 + r * 30, 100 + (c + 1) * 120, 200 + (r + 1) * 30)
            page.draw_rect(cell, color=(0, 0, 0), width=1)
            page.insert_text((cell.x0 + 5, cell.y0 + 20), f"R{r}C{c}", fontsize=11)


def _make_annotated_pdf(path: Path) -> Path:
    with fitz.open() as doc:
        for _ in range(3):
            _draw_table(doc.new_page(width=595, height=842))
        doc[0].insert_link(
            {"kind": fitz.LINK_URI, "from": fitz.Rect(100, 100, 200, 120), "uri": "https://example.com"}
        )
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = "f1"
        widget.rect = fitz.Rect(100, 100, 200, 120)
        doc[1].add_widget(widget)
        doc[2].add_text_annot(fitz.Point(120, 120), "note")
        doc.save(path)
    return path


@pytest.fixture
def model():
    m = PDFModel()
    yield m
    m.close()


@pytest.mark.parametrize("page_num", [1, 2, 3])
def test_table_rects_leaves_every_source_object_unchanged(model, tmp_path, page_num):
    probe = _load_probe()
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    before, *_ = probe.digest_table(model.doc)
    rects = table_objects.table_rects(model, page_num)
    after, *_ = probe.digest_table(model.doc)
    assert len(rects) == 1
    assert probe.differing(before, after) == []


def test_scratch_page_bytes_is_a_one_page_pdf_without_annotations(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    data = table_objects.scratch_page_bytes(model.doc, 3)
    with fitz.open(stream=data, filetype="pdf") as copy:
        assert len(copy) == 1
        assert list(copy[0].annots()) == []
    assert len(model.doc) == 3


def test_find_table_rects_returns_tuples_for_a_page():
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        _draw_table(page)
        rects = table_objects.find_table_rects(page)
    assert len(rects) == 1
    assert len(rects[0]) == 4


def test_frame_key_has_the_h3_shape(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    page = model.doc[0]
    key = table_objects.frame_key(model, 1)
    assert key == (
        model.handle_generation,
        1,
        model.content_revision,
        len(model.doc),
        page.rotation,
        tuple(page.cropbox),
        tuple(page.mediabox),
    )


def test_rotate_pages_invalidates_cached_rects(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    table_objects.table_rects(model, 1)
    assert table_objects.cached_table_rects(model, 1) is not None
    model.rotate_pages([1], 90)
    assert table_objects.cached_table_rects(model, 1) is None
    rects = table_objects.table_rects(model, 1)
    expected = fitz.Rect(100, 200, 460, 320) * model.doc[0].rotation_matrix
    assert abs(rects[0].x0 - expected.x0) < 2 and abs(rects[0].y0 - expected.y0) < 2


def test_cached_table_rects_is_none_on_a_miss_and_does_no_work(model, tmp_path, monkeypatch):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))

    def boom(*_a, **_k):
        raise AssertionError("no work allowed")

    monkeypatch.setattr(table_objects, "find_table_rects", boom)
    assert table_objects.cached_table_rects(model, 1) is None


def test_store_table_rects_refuses_a_stale_key(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    key = table_objects.frame_key(model, 1)
    rect = fitz.Rect(1, 2, 3, 4)
    assert table_objects.store_table_rects(model, key, [rect]) is True
    assert table_objects.cached_table_rects(model, 1) == [rect]
    model.rotate_pages([1], 90)
    assert table_objects.store_table_rects(model, key, [rect]) is False
    assert table_objects.cached_table_rects(model, 1) is None


def test_table_rects_out_of_range_is_empty(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    assert table_objects.table_rects(model, 0) == []
    assert table_objects.table_rects(model, 99) == []


# --------------------------------------------------------------------------- D1: handle identity


def _force_id_collision(monkeypatch) -> None:
    # Every handle gets the same id(): the deterministic form of CPython reusing the address of
    # a closed document for the next one (A3 review B2, owner decision D1).
    monkeypatch.setattr(table_objects, "id", lambda _obj: 42, raising=False)


def test_frame_identity_survives_forced_id_reuse(model, tmp_path, monkeypatch):
    _force_id_collision(monkeypatch)
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    first = model._active_session_id
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    table_objects.mark_table_analysis_failed(model, table_objects.frame_key(model, 2))
    assert model.close_session(first) is True
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "b.pdf")))
    assert table_objects.cached_table_rects(model, 1) is None
    assert table_objects.table_analysis_failed(model, 2) is False


def test_snapshot_replacement_drops_an_answer_for_the_old_handle(model, tmp_path, monkeypatch):
    _force_id_collision(monkeypatch)
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    old_key = table_objects.frame_key(model, 1)
    model._restore_doc_from_snapshot(model.doc.tobytes())
    assert table_objects.frame_key(model, 1) != old_key
    assert table_objects.store_table_rects(model, old_key, [fitz.Rect(1, 2, 3, 4)]) is False
    table_objects.mark_table_analysis_failed(model, old_key)
    assert table_objects.table_analysis_failed(model, 1) is False


def test_generation_is_stable_without_a_handle_change(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    generation = model.handle_generation
    model.rotate_pages([1], 90)
    model.doc = model.doc  # re-assigning the same handle is not a replacement
    assert model.handle_generation == generation


def test_switching_tabs_keeps_each_tabs_results(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    first = model._active_session_id
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "b.pdf")), append=True)
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(5, 6, 7, 8)])
    assert model.activate_session(first) is True
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(1, 2, 3, 4)]


def test_retired_generation_results_are_released(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    first = model._active_session_id
    old = model.handle_generation
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    table_objects.mark_table_analysis_failed(model, table_objects.frame_key(model, 2))
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "b.pdf")), append=True)
    assert model.close_session(first) is True  # released on close, not on the next store
    assert all(key[0] != old for key in table_objects._cache(model))
    assert all(key[0] != old for key in table_objects._failed_keys(model))


def test_snapshot_replacement_releases_the_old_handles_results(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    old = model.handle_generation
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    table_objects.mark_table_analysis_failed(model, table_objects.frame_key(model, 2))
    model._restore_doc_from_snapshot(model.doc.tobytes())
    assert model.handle_generation != old
    assert table_objects._cache(model) == {}
    assert table_objects._failed_keys(model) == set()
