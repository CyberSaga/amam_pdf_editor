"""Tables as deletable objects (docs/to_Update.md line 34, owner decision 2026-11-05).

A ruled table is one OBJECT in 操作物件 mode: click selects its frame, Delete
removes its text and ruling lines as one undoable step.  Cell text stays
ordinary text for the edit-text tool.  Tables are not movable/resizable.  A
"table" covering most of the page (a CAD sheet frame) is never an object.
"""
from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from model import table_objects
from model.object_requests import DeleteObjectRequest
from model.pdf_model import PDFModel

TABLE = fitz.Rect(100, 200, 460, 320)


def _draw_table(page: fitz.Page, origin=(100, 200), rows: int = 4, cols: int = 3) -> None:
    x0, y0 = origin
    for r in range(rows):
        for c in range(cols):
            cell = fitz.Rect(x0 + c * 120, y0 + r * 30, x0 + (c + 1) * 120, y0 + (r + 1) * 30)
            page.draw_rect(cell, color=(0, 0, 0), width=1)
            page.insert_text((cell.x0 + 5, cell.y0 + 20), f"R{r}C{c}", fontsize=11)


def _make_pdf(path: Path, *, rotation: int = 0) -> Path:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        _draw_table(page)
        page.insert_text((100, 180), "Caption above", fontsize=11)
        page.insert_text((100, 345), "Text below", fontsize=11)
        page.draw_line((100, 600), (460, 600), color=(0, 0, 0), width=1)  # unrelated rule
        page.set_rotation(rotation)
        doc.save(path)
    return path


@pytest.fixture
def model():
    m = PDFModel()
    yield m
    m.close()


def _visual(page: fitz.Page, point: fitz.Point) -> fitz.Point:
    return point * page.rotation_matrix


def test_click_inside_a_ruled_table_hits_a_table_object(model, tmp_path):
    model.open_pdf(str(_make_pdf(tmp_path / "t.pdf")))
    info = model.get_object_info_at_point(1, fitz.Point(170, 245))
    assert info is not None and info.object_kind == "table"
    assert info.supports_delete is True
    assert info.supports_move is False and info.supports_rotate is False
    assert abs(info.bbox.x0 - TABLE.x0) < 2 and abs(info.bbox.y1 - TABLE.y1) < 2


def test_click_outside_the_table_hits_nothing(model, tmp_path):
    model.open_pdf(str(_make_pdf(tmp_path / "t.pdf")))
    assert model.get_object_info_at_point(1, fitz.Point(120, 177)) is None
    assert model.get_object_info_at_point(1, fitz.Point(300, 600)) is None


def test_rotated_page_table_is_hit_at_its_visual_position(model, tmp_path):
    model.open_pdf(str(_make_pdf(tmp_path / "r.pdf", rotation=90)))
    page = model.doc[0]
    info = model.get_object_info_at_point(1, _visual(page, fitz.Point(170, 245)))
    assert info is not None and info.object_kind == "table"
    expected = TABLE * page.rotation_matrix
    assert abs(info.bbox.x0 - expected.x0) < 2 and abs(info.bbox.y0 - expected.y0) < 2


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_table_detection_never_modifies_the_document(model, tmp_path, rotation):
    """``Page.find_tables`` resets rotation/mediabox on rotated pages and does not
    restore a CropBox exactly; a click that only hit-tests must change nothing."""
    path = tmp_path / "crop.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        _draw_table(page)
        page.set_cropbox(fitz.Rect(20, 30, 575, 812))
        page.set_rotation(rotation)
        doc.save(path)
    model.open_pdf(str(path))
    page = model.doc[0]
    before = (tuple(page.rect), tuple(page.cropbox), tuple(page.mediabox), page.rotation, page.read_contents())
    edits = model.edit_count

    model.get_object_info_at_point(1, fitz.Point(5, 5))  # miss: falls through to table detection
    model.get_object_info_at_point(1, _visual(page, fitz.Point(170, 245)))

    page = model.doc[0]
    after = (tuple(page.rect), tuple(page.cropbox), tuple(page.mediabox), page.rotation, page.read_contents())
    assert after == before
    assert model.edit_count == edits


def test_page_sized_grid_is_not_a_table_object(model, tmp_path):
    path = tmp_path / "frame.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        _draw_table(page, origin=(10, 10), rows=27, cols=4)
        doc.save(path)
    model.open_pdf(str(path))
    assert model.get_object_info_at_point(1, fitz.Point(100, 300)) is None


@pytest.mark.parametrize("rotation", [0, 90])
def test_deleting_a_table_removes_its_text_and_rules_only(model, tmp_path, rotation):
    model.open_pdf(str(_make_pdf(tmp_path / "d.pdf", rotation=rotation)))
    page = model.doc[0]
    info = model.get_object_info_at_point(1, _visual(page, fitz.Point(170, 245)))
    assert info is not None

    assert model.delete_object(
        DeleteObjectRequest(object_id=info.object_id, object_kind="table", page_num=1)
    ) is True

    page = model.doc[0]
    text = page.get_text()
    assert "R0C0" not in text and "R3C2" not in text
    assert "Caption above" in text and "Text below" in text
    inside = [d for d in page.get_drawings() if fitz.Rect(d["rect"]).intersects(TABLE)]
    assert inside == []
    assert any(abs(fitz.Rect(d["rect"]).y0 - 600) < 2 for d in page.get_drawings())  # unrelated rule kept
    assert model.get_object_info_at_point(1, _visual(page, fitz.Point(170, 245))) is None


def test_deleting_a_table_that_is_gone_is_refused(model, tmp_path):
    model.open_pdf(str(_make_pdf(tmp_path / "g.pdf")))
    request = DeleteObjectRequest(object_id="table:1:0.00,0.00,10.00,10.00", object_kind="table", page_num=1)
    assert model.delete_object(request) is False
    assert "R0C0" in model.doc[0].get_text()


def _pump(ms: int = 200) -> None:
    app = QApplication.instance()
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_controller_table_delete_is_one_undo_step_and_objects_mode_offers_it(qapp, tmp_path, monkeypatch):
    from controller.pdf_controller import PDFController
    from test_scripts.qt_teardown import dispose_pdf_view
    from view.pdf_view import PDFView

    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    m = PDFModel()
    view = PDFView()
    controller = PDFController(m, view)
    view.controller = controller
    controller.activate()
    try:
        controller.open_pdf(str(_make_pdf(tmp_path / "u.pdf")))
        view.resize(1200, 900)
        view.show()
        _pump(500)
        view.set_mode("objects")
        _pump(100)
        scene = view._doc_rect_to_scene_rect(0, fitz.Rect(165, 240, 175, 250)).center()
        pos = view.graphics_view.mapFromScene(scene)
        mgr = view._ensure_object_selection_manager()
        # A3: the first lookup on a cold page is pending; the child's answer warms the cache.
        assert mgr._resolve_object_info_for_context_menu_pos(pos) == "pending"
        for _ in range(600):
            if table_objects.cached_table_rects(m, 1) is not None:
                break
            _pump(50)
        resolved = mgr._resolve_object_info_for_context_menu_pos(pos)
        assert resolved is not None and resolved[1].object_kind == "table"

        info = resolved[1]
        controller.delete_object(DeleteObjectRequest(object_id=info.object_id, object_kind="table", page_num=1))
        _pump(200)
        assert "R1C1" not in m.doc[0].get_text()
        controller.undo()
        _pump(200)
        assert "R1C1" in m.doc[0].get_text()
    finally:
        dispose_pdf_view(view, controller, m)


# --- D4: a batch resolves every table before its first mutation -------------------------

def _two_table_pdf(path: Path, *, pages: int = 1) -> Path:
    with fitz.open() as doc:
        for _ in range(pages):
            page = doc.new_page(width=595, height=842)
            _draw_table(page)
            _draw_table(page, origin=(100, 450), rows=3, cols=3)
            page.insert_text((100, 345), "Text below", fontsize=11)
        doc.save(path)
    return path


def _table_requests(model: PDFModel, page_num: int) -> list[DeleteObjectRequest]:
    out = []
    for point in (fitz.Point(170, 245), fitz.Point(170, 465)):
        info = model.get_object_info_at_point(page_num, point)
        assert info is not None and info.object_kind == "table"
        out.append(DeleteObjectRequest(object_id=info.object_id, object_kind="table", page_num=page_num))
    return out


def _spy_analysis(monkeypatch, model: PDFModel) -> list[int]:
    seen: list[int] = []
    real = table_objects.find_table_rects

    def spy(page):
        seen.append(int(model.edit_count))
        return real(page)

    monkeypatch.setattr(table_objects, "find_table_rects", spy)
    return seen


def test_batch_tables_never_analyse_after_first_mutation(model, tmp_path, monkeypatch):
    model.open_pdf(str(_two_table_pdf(tmp_path / "b.pdf", pages=2)))
    requests = _table_requests(model, 1) + _table_requests(model, 2)
    start = int(model.edit_count)
    seen = _spy_analysis(monkeypatch, model)

    assert model.delete_objects_atomic(requests) is True

    assert [c for c in seen if c != start] == []
    for page in model.doc:
        assert "R0C0" not in page.get_text() and "R2C2" not in page.get_text()
        assert "Text below" in page.get_text()


def test_batch_with_a_cold_frame_still_resolves_before_the_first_mutation(model, tmp_path, monkeypatch):
    model.open_pdf(str(_two_table_pdf(tmp_path / "c.pdf")))
    requests = _table_requests(model, 1)
    table_objects._cache(model).clear()  # cold cache: resolution must analyse, but up front
    start = int(model.edit_count)
    seen = _spy_analysis(monkeypatch, model)

    assert model.delete_objects_atomic(requests) is True

    assert seen and set(seen) == {start}
    assert "R0C0" not in model.doc[0].get_text()


def test_batch_with_an_unresolvable_table_mutates_nothing(model, tmp_path):
    model.open_pdf(str(_two_table_pdf(tmp_path / "i.pdf")))
    good = _table_requests(model, 1)
    bad = DeleteObjectRequest(object_id="table:1:0.00,0.00,10.00,10.00", object_kind="table", page_num=1)
    before = model.doc[0].read_contents()
    start = int(model.edit_count)

    assert model.delete_objects_atomic([*good, bad]) is False

    assert int(model.edit_count) == start
    assert model.doc[0].read_contents() == before
    assert "R0C0" in model.doc[0].get_text()


def test_batch_with_a_malformed_table_id_mutates_nothing(model, tmp_path):
    model.open_pdf(str(_two_table_pdf(tmp_path / "m.pdf")))
    good = _table_requests(model, 1)
    bad = DeleteObjectRequest(object_id="table:garbage", object_kind="table", page_num=1)
    start = int(model.edit_count)

    assert model.delete_objects_atomic([*good, bad]) is False

    assert int(model.edit_count) == start
    assert "R0C0" in model.doc[0].get_text()


def test_empty_batch_is_refused_without_mutation(model, tmp_path):
    model.open_pdf(str(_two_table_pdf(tmp_path / "e.pdf")))
    start = int(model.edit_count)
    assert model.delete_objects_atomic([]) is False
    assert int(model.edit_count) == start


def test_duplicate_table_selection_is_deleted_once(model, tmp_path, monkeypatch):
    model.open_pdf(str(_two_table_pdf(tmp_path / "d2.pdf")))
    first, second = _table_requests(model, 1)
    start = int(model.edit_count)
    seen = _spy_analysis(monkeypatch, model)

    assert model.delete_objects_atomic([first, first, second]) is True

    assert [c for c in seen if c != start] == []
    assert "R0C0" not in model.doc[0].get_text() and "R2C2" not in model.doc[0].get_text()


def test_overlapping_tables_delete_every_original_region(model, tmp_path, monkeypatch):
    model.open_pdf(str(_two_table_pdf(tmp_path / "o.pdf")))
    first, second = _table_requests(model, 1)
    # A second selection overlapping the first: both original regions go, and no
    # remaining table is searched for in between.
    overlap = fitz.Rect(table_objects.parse_table_object_id(first.object_id)[1])
    overlap.y1 += 30
    overlapping = DeleteObjectRequest(
        object_id=table_objects.table_object_id(1, overlap), object_kind="table", page_num=1
    )
    monkeypatch.setattr(
        table_objects, "matching_table", lambda m, p, rect, tolerance=1.0: fitz.Rect(rect)
    )
    start = int(model.edit_count)
    seen = _spy_analysis(monkeypatch, model)

    assert model.delete_objects_atomic([first, overlapping, second]) is True

    assert [c for c in seen if c != start] == []
    assert "R0C0" not in model.doc[0].get_text() and "R2C2" not in model.doc[0].get_text()


def test_mixed_batch_with_an_unusable_member_rolls_tables_back(model, tmp_path, monkeypatch):
    model.open_pdf(str(_two_table_pdf(tmp_path / "x.pdf")))
    table_a, table_b = _table_requests(model, 1)
    start = int(model.edit_count)
    seen = _spy_analysis(monkeypatch, model)
    missing_image = DeleteObjectRequest(object_id="image:none", object_kind="native_image", page_num=1)

    assert model.delete_objects_atomic([table_a, missing_image, table_b]) is False

    assert [c for c in seen if c != start] == []
    assert int(model.edit_count) == start
    assert "R0C0" in model.doc[0].get_text() and "R2C2" in model.doc[0].get_text()
