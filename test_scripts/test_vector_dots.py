"""Card B7 step 3 + 4 (plans/b7-design-astra.md section 2): the sparse table of stand-alone round-cap dots.  Red first.

A closed zero-length subpath ('x y m h') in a path that also draws something paints a round-cap dot (MuPDF probe,
Astra 11-26: a lone 'm h S' paints nothing).  Owner 11-26: store them in a sparse table so a click can pick them.
Table: VectorIndex.dots, dtype [path i4, subpath i4, x f8, y f8] (subpath = the dot's ordinal in its path), in
unrotated page space.  Only dots whose cap is KNOWN to be round (an explicit '1 J', restored by Q) are stored: an
unresolved gs is never guessed round (the model-side /LC resolution is a later step).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.vector_paths import index as qi  # noqa: E402
from model.vector_paths import transport  # noqa: E402
from model.vector_paths.scan import PathFlag, scan_page  # noqa: E402

IDENT6 = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
DOT = "1 J 8 w 20 20 m 20 20 l 50 50 m h S"


def _scan(s: str, *, fast: bool = False):
    return scan_page([s.encode("ascii")], IDENT6, accelerated=fast)


def _rows(idx):
    return [(int(r["path"]), int(r["subpath"]), float(r["x"]), float(r["y"])) for r in idx.dots]


BOTH = pytest.mark.parametrize("fast", [False, True], ids=["G", "F"])


@BOTH
def test_a_round_cap_dot_in_a_drawing_path_is_stored(fast):
    idx = _scan(DOT, fast=fast)
    assert idx.scanner == ("F" if fast else "G")
    assert idx.dots.dtype.names == ("path", "subpath", "x", "y") and idx.dots.dtype.itemsize == 24
    assert _rows(idx) == [(0, 0, 50.0, 50.0)]


@BOTH
@pytest.mark.parametrize(
    "stream",
    [
        DOT.replace("1 J ", ""),  # butt cap (the default): no ink at a zero-length subpath
        "2 J 8 w 20 20 m 20 20 l 50 50 m h S",  # square cap: not a round dot
        "1 J 8 w 50 50 m h S",  # MuPDF paints a lone 'm h' path as nothing
        "1 J /G0 gs 8 w 20 20 m 20 20 l 50 50 m h S",  # gs may reset the cap: never guessed round
        "1 J 8 w 20 20 m 20 20 l 50 50 m h f",  # fill-only: a dot has no area
        "1 J 8 w 20 20 m 20 20 l 50 50 m h n",
        "q 1 J Q 8 w 20 20 m 20 20 l 50 50 m h S",  # the cap was restored by Q
    ],
)
def test_no_dot_is_stored_without_a_known_round_cap_a_drawing_path_and_a_stroke(fast, stream):
    assert len(_scan(stream, fast=fast).dots) == 0


@BOTH
def test_dots_are_ordered_by_path_then_ordinal_and_q_keeps_the_cap(fast):
    idx = _scan("q 1 J 8 w 0 0 m 0 0 l 10 10 m h 12 12 m h S Q 1 J 8 w 40 40 m 40 40 l 60 60 m h S", fast=fast)
    assert _rows(idx) == [(0, 0, 10.0, 10.0), (0, 1, 12.0, 12.0), (1, 0, 60.0, 60.0)]


@BOTH
def test_a_ctm_moves_the_dot_into_page_space(fast):
    idx = _scan("q 2 0 0 2 100 0 cm 1 J 8 w 0 0 m 0 0 l 10 10 m h S Q", fast=fast)
    assert _rows(idx) == [(0, 0, 120.0, 20.0)]


def test_both_scanners_write_byte_identical_dot_tables():
    for stream in (
        DOT,
        "q 1 J 8 w 0 0 m 0 0 l 10 10 m h 12 12 m h S Q 1 J 8 w 40 40 m 40 40 l 60 60 m h S",
        "q 2 0 0 2 100 0 cm 1 J 8 w 0 0 m 0 0 l 10 10 m h S Q",
        "1 J 4 w 0 0 m 5 5 l 9 9 m h B 6 w 30 30 m 30 30 l 31 31 m h S",
    ):
        assert _scan(stream).dots.tobytes() == _scan(stream, fast=True).dots.tobytes(), stream


@BOTH
def test_the_bbox_of_a_mixed_row_still_covers_its_dots(fast):
    idx = _scan(DOT, fast=fast)
    assert idx.paths["bbox"][0][0] <= 20 and idx.paths["bbox"][0][2] >= 50


# ---- click, touch, contain ---------------------------------------------------------------------
def _click(idx, x, y, tol=0.0):
    return [int(i) for i in np.flatnonzero(qi.select(idx, (x, y, x, y), tol, "click"))]


@BOTH
def test_a_click_on_the_dot_selects_its_row_within_half_the_line_width(fast):
    idx = _scan(DOT, fast=fast)
    assert _click(idx, 50, 50) == [0]
    assert _click(idx, 53.9, 50) == [0]  # 8 w -> radius 4
    assert _click(idx, 54.5, 50) == []
    assert _click(idx, 35, 35) == []  # between the segment and the dot: nothing there


@BOTH
def test_the_tolerance_widens_the_dot_hit(fast):
    idx = _scan(DOT, fast=fast)
    assert _click(idx, 57, 50, 0.0) == [] and _click(idx, 57, 50, 8.0) == [0]


@BOTH
def test_the_topmost_row_wins_between_a_dot_and_other_geometry(fast):
    below = "0 w 40 50 m 60 50 l S "
    above = "1 J 8 w 20 20 m 20 20 l 50 50 m h S "
    idx = _scan(below + above, fast=fast)
    assert _click(idx, 50, 50, 1.0) == [1]  # the later row is on top
    idx = _scan(above + below, fast=fast)
    assert _click(idx, 50, 50, 1.0) == [1]  # the line (row 1) is on top now
    assert _click(idx, 50, 53.5, 0.0) == [0]  # only the dot reaches here


@BOTH
def test_a_dot_in_a_row_that_is_not_editable_is_not_selected_and_counts_as_skipped(fast):
    idx = _scan("/OC /x BDC " + DOT + " EMC", fast=fast)
    assert not int(idx.paths["flags"][0]) & int(PathFlag.EDITABLE)
    mask, skipped = qi.select_counting_skipped(idx, (50, 50, 50, 50), 0.0, "click")
    assert not mask.any() and skipped == 1


@BOTH
def test_touch_and_contain_use_the_row_bbox_which_includes_the_dot(fast):
    idx = _scan(DOT, fast=fast)
    assert list(np.flatnonzero(qi.select(idx, (45, 45, 60, 60), 0.0, "touch"))) == [0]
    assert list(np.flatnonzero(qi.select(idx, (10, 10, 70, 70), 0.0, "contain"))) == [0]
    assert list(np.flatnonzero(qi.select(idx, (45, 45, 49, 49), 0.0, "contain"))) == []


def test_an_index_without_dots_takes_the_old_fast_path():
    idx = _scan("0 w 0 0 m 30 0 l S")
    assert len(idx.dots) == 0 and _click(idx, 10, 0, 1.0) == [0]


# ---- memory, transport --------------------------------------------------------------------------
@BOTH
def test_nbytes_counts_the_dots_table(fast):
    idx = _scan(DOT, fast=fast)
    parts = (idx.paths, idx.cubics, idx.segments, idx.blocks, idx.streams, idx.dots)
    assert idx.nbytes == sum(int(t.nbytes) for t in parts) and idx.dots.nbytes == 24


@BOTH
def test_transport_round_trips_the_dots(tmp_path, fast):
    idx = _scan(DOT, fast=fast)
    transport.save_index(idx, tmp_path / "i.npy")
    back = transport.load_index(tmp_path / "i.npy")
    assert back.dots.tobytes() == idx.dots.tobytes() and back.nbytes == idx.nbytes


def test_transport_refuses_a_dot_that_names_a_missing_path(tmp_path):
    idx = _scan(DOT)
    idx.dots["path"][0] = 5
    transport.save_index(idx, tmp_path / "bad.npy")
    with pytest.raises(ValueError):
        transport.load_index(tmp_path / "bad.npy")


def test_transport_refuses_an_unsorted_or_non_finite_dot_table(tmp_path):
    idx = _scan("q 1 J 8 w 0 0 m 0 0 l 10 10 m h 12 12 m h S Q 1 J 8 w 40 40 m 40 40 l 60 60 m h S")
    swapped = idx.dots.copy()
    swapped[[0, 2]] = swapped[[2, 0]]
    idx.dots = swapped
    transport.save_index(idx, tmp_path / "unsorted.npy")
    with pytest.raises(ValueError):
        transport.load_index(tmp_path / "unsorted.npy")
    idx = _scan(DOT)
    idx.dots["x"][0] = float("nan")
    transport.save_index(idx, tmp_path / "nan.npy")
    with pytest.raises(ValueError):
        transport.load_index(tmp_path / "nan.npy")


# ---- the whole chain on a real page: click the dot, delete it, the ink is gone ----------------------
def test_click_and_delete_a_dot_row_removes_its_ink(tmp_path):
    import fitz

    from model.object_requests import VectorSelectionQuery
    from model.pdf_model import PDFModel
    from model.vector_paths.edit import plan_delete

    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((5, 5), " ")
    keep = b"0 0 1 RG 1 w 200 300 m 280 300 l S "
    doc.update_stream(page.get_contents()[0], keep + b"1 0 0 RG 1 J 12 w 20 20 m 20 20 l 150 150 m h S")
    path = tmp_path / "dot.pdf"
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    assert len(model.vector_index(1).dots) == 1

    def ink(x: float, y: float) -> int:  # visual coordinates, 2x gray render
        pix = model.doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False)
        return int(pix.pixel(int(x * 2), int(y * 2))[0])

    assert ink(150, 250) < 200  # the dot is on the page: PDF (150, 150) is visual (150, 250)
    info = model.vector_select(VectorSelectionQuery(1, (150, 250, 150, 250), 1.0, "click", "replace"))
    assert info.count == 1 and info.supports_delete and info.movable_count == 1
    index, mask, decoded = model.vector_plan_inputs(info.token)
    result = model.commit_vector_plan(plan_delete(index, mask, decoded), info.token)
    assert result is not None
    assert ink(150, 250) > 240  # gone
    assert ink(240, 100) < 200  # the other line is untouched
