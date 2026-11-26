"""Card B7 step 7 (plans/b7-design-astra.md section 5), model half: the movable subset and the presentation DTO.
Red first.

Owner 11-26: a selection that holds rows the user cannot move is not refused as a whole; supports_move is true when
a movable subset exists, delete still covers every selected row, and the view draws movable and fixed rows apart.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.object_requests import VectorSelectionQuery  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.vector_paths.scan import PathFlag, scan_page  # noqa: E402
from utils.vector_selection_dto import VectorGeometry, VectorSelectionPresentation  # noqa: E402

# row 0 plain, row 1 the clip setter (not editable), row 2 CLIPPED, row 3 PAGE_ANCHORED (gs)
BODY = (
    b"0 0 0 RG 1 w 20 370 m 120 370 l S "
    b"q 0 0 300 400 re W n 1 w 20 350 m 120 350 l S Q "
    b"/GS0 gs 1 w 20 330 m 120 330 l S"
)


def _model(tmp_path: Path, body: bytes = BODY) -> PDFModel:
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((5, 5), " ")
    doc.update_stream(page.get_contents()[0], body)
    path = tmp_path / "m.pdf"
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    return model


def _all(model: PDFModel):
    return model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))


def test_the_fixture_has_the_flags_the_tests_rely_on(tmp_path):
    model = _model(tmp_path)
    flags = [int(f) for f in model.vector_index(1).paths["flags"]]
    editable = int(PathFlag.EDITABLE)
    assert flags[0] & editable and not flags[1] & editable
    assert flags[2] & int(PathFlag.CLIPPED) and flags[2] & editable
    assert flags[3] & int(PathFlag.PAGE_ANCHORED) and flags[3] & editable


def test_a_mixed_selection_can_still_move_its_movable_part_and_delete_everything(tmp_path):
    info = _all(_model(tmp_path))
    assert (info.count, info.movable_count) == (3, 1)
    assert info.supports_move is True and info.supports_delete is True


def test_a_selection_of_only_fixed_rows_cannot_move_but_can_be_deleted(tmp_path):
    model = _model(tmp_path)
    _all(model)
    streams = model.vector_index(1)
    # pick only the two fixed rows through a marquee that touches y=350 and y=330 but not y=370
    info = model.vector_select(VectorSelectionQuery(1, (0, 400 - 355, 300, 400 - 325), 0.0, "touch", "replace"))
    assert (info.count, info.movable_count) == (2, 0)
    assert info.supports_move is False and info.supports_delete is True
    del streams


def test_an_empty_selection_supports_nothing(tmp_path):
    model = _model(tmp_path)
    info = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "clear", "replace"))
    assert (info.count, info.movable_count, info.supports_move, info.supports_delete) == (0, 0, False, False)


def test_the_presentation_splits_geometry_into_movable_and_fixed(tmp_path):
    model = _model(tmp_path)
    info = _all(model)
    shown = model.vector_selection_presentation()
    assert isinstance(shown, VectorSelectionPresentation)
    assert (shown.page_num, shown.token, shown.count, shown.movable_count) == (1, info.token, 3, 1)
    assert (shown.supports_move, shown.supports_delete, shown.skipped) == (True, True, info.skipped)
    assert shown.visual_bbox == info.bbox
    assert isinstance(shown.movable_geometry, VectorGeometry) and isinstance(shown.fixed_geometry, VectorGeometry)
    assert shown.movable_geometry.segments.shape == (1, 4) and shown.fixed_geometry.segments.shape == (2, 4)
    assert shown.movable_geometry.dots.shape == (0, 2) and shown.fixed_geometry.dots.shape == (0, 2)
    for geometry in (shown.movable_geometry, shown.fixed_geometry):
        assert geometry.segments.dtype == np.float32 and geometry.segments.flags["C_CONTIGUOUS"]
        assert not geometry.segments.flags["WRITEABLE"] and not geometry.dots.flags["WRITEABLE"]
    both = np.concatenate([shown.movable_geometry.segments, shown.fixed_geometry.segments])
    flat = model.vector_selection_segments()
    assert sorted(map(tuple, both.tolist())) == sorted(map(tuple, flat.tolist()))  # same lines, only split


def test_the_presentation_is_none_without_a_selection_and_after_a_stale_index(tmp_path):
    model = _model(tmp_path)
    assert model.vector_selection_presentation() is None
    _all(model)
    model.__dict__["_vector_indexes"].clear()
    assert model.vector_selection_presentation() is None


def test_the_dto_module_imports_no_model_and_no_qt_widgets():
    import ast

    tree = ast.parse((REPO_ROOT / "utils" / "vector_selection_dto.py").read_text(encoding="utf-8-sig"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
    assert not [n for n in names if n.startswith(("model", "PySide6.QtWidgets"))], names


def test_the_info_dataclass_keeps_movable_count_last_and_defaulted_for_old_callers():
    from model.object_requests import VectorSelectionInfo

    info = VectorSelectionInfo(1, 1, b"", 0, 0, None, supports_move=False, supports_delete=False)
    assert info.movable_count == 0
    with pytest.raises(Exception):  # noqa: B017
        info.movable_count = 3  # type: ignore[misc]  # frozen


DOT_BODY = (
    b"1 J 8 w 20 20 m 20 20 l 50 50 m h S "  # row 0: a movable dot row (mixed: a zero-length segment and a dot)
    b"q 0 0 300 400 re W n 1 J 8 w 100 100 m 100 100 l 120 120 m h S Q"  # row 2: the same, but clipped
)


def test_dots_travel_in_the_presentation_in_visual_coordinates_split_like_the_lines(tmp_path):
    model = _model(tmp_path, DOT_BODY)
    info = _all(model)
    assert (info.count, info.movable_count) == (2, 1)
    shown = model.vector_selection_presentation()
    assert shown.movable_geometry.dots.shape == (1, 2) and shown.fixed_geometry.dots.shape == (1, 2)
    from model.geometry import unrotated_to_visual_point

    movable_dot = unrotated_to_visual_point(model.doc[0], fitz.Point(50, 350))  # the scan frame flips y: PDF (50, 50) is (50, 350)
    fixed_dot = unrotated_to_visual_point(model.doc[0], fitz.Point(120, 280))
    assert shown.movable_geometry.dots[0].tolist() == pytest.approx([movable_dot.x, movable_dot.y], abs=1e-3)
    assert shown.fixed_geometry.dots[0].tolist() == pytest.approx([fixed_dot.x, fixed_dot.y], abs=1e-3)
    assert shown.movable_geometry.dots.dtype == np.float32 and not shown.movable_geometry.dots.flags["WRITEABLE"]


def test_a_replaced_index_never_lends_its_selection_to_the_new_one(tmp_path):
    """Astra review a: same page, same row count, another index: the old mask must not be combined."""
    model = _model(tmp_path)
    first = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    assert first.count == 3
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))  # a fresh index object, equal rows
    info = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "clear", "add"))
    assert (info.count, info.movable_count, info.supports_move) == (0, 0, False)
    model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    info = model.vector_select(VectorSelectionQuery(1, (500, 500, 501, 501), 0.0, "touch", "add"))
    assert info.count == 0  # nothing carried over from the replaced index


def test_info_and_presentation_agree_on_skipped_for_the_same_token(tmp_path):
    model = _model(tmp_path, b"/OC /x BDC 0 w 0 0 m 30 0 l S EMC 0 w 10 10 m 20 40 l S")
    info = model.vector_select(VectorSelectionQuery(1, (-1, 300, 100, 410), 0.0, "touch", "replace"))
    assert info.skipped == 1
    shown = model.vector_selection_presentation()
    assert shown.skipped == info.skipped and shown.token == info.token


def test_the_selection_readers_refuse_a_mask_of_a_replaced_index(tmp_path):
    model = _model(tmp_path)
    _all(model)
    assert model.vector_selection_mask() is not None and model.vector_selection_segments().shape[0] == 3
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))  # equal rows, another object
    assert model.vector_selection_mask() is None
    assert model.vector_selection_segments().shape == (0, 4)
    assert model.vector_selection_presentation() is None
    _all(model)
    assert not model.vector_selection_mask().flags["WRITEABLE"]  # callers get a read-only view


def test_install_warms_the_query_arrays_and_the_lru_counts_them(tmp_path):
    from model.vector_paths import index as qi

    model = _model(tmp_path)
    index = model.vector_index(1)
    assert "editable" in index.__dict__.get("_query_cache", {}) and qi.resident_bytes(index) > 0
    model._VECTOR_CACHE_BYTES = index.nbytes + 1  # room for the tables alone, not for their query arrays
    streams, frame = model.vector_page_source(1)
    second = scan_page(list(streams), frame)
    model.install_vector_index(1, second)
    model.install_vector_index(2, scan_page(list(streams), frame))
    assert model.vector_index(1) is None  # evicted: resident bytes were counted
