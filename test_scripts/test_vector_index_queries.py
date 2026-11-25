"""Card B5 (design plan Step 4): model/vector_paths/index.py queries.  Red first.

Fill topology and CLIPPED follow plans/b5-fill-topology-clipped-design.md (owner 11-25: segments.subpath is the
fill topology; one-sided 0.0025 pt cubic allowance for fill clicks; CLIPPED stays "any active clip").
Rectangles are in unrotated page space (the model maps a visual marquee before calling).  A click uses the
centre of its rectangle; touch and contain with an empty rectangle select nothing.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.vector_paths import index as qi  # noqa: E402
from model.vector_paths.scan import PathFlag, scan_page  # noqa: E402

IDENT6 = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _scan(s: str):
    return scan_page([s.encode("ascii")], IDENT6)


def _click(idx, x: float, y: float, tol: float = 0.0):
    return qi.select(idx, (x, y, x, y), tol, "click")


def _hits(mask) -> list[int]:
    return [int(i) for i in np.flatnonzero(mask)]


@pytest.fixture(params=[65536, 3], ids=["batch-default", "batch-3-edges"])
def small_batches(request, monkeypatch):
    """Every fill fixture also runs with a tiny edge batch, so a batch break falls inside and between contours."""
    monkeypatch.setattr(qi, "EDGE_BATCH", request.param)
    return request.param


# --------------------------------------------------------------------------- fill topology

OUTER = "0 0 20 20 re "


@pytest.mark.parametrize(
    "stream, point, nonzero, evenodd",
    [
        (OUTER + "5 5 10 10 re", (10, 10), True, False),  # same-direction nested ring
        (OUTER + "5 5 10 10 re", (2, 2), True, True),
        (OUTER + "5 5 m 5 15 l 15 15 l 15 5 l h", (10, 10), False, False),  # reversed inner ring: a hole for both
        (OUTER + "5 5 m 5 15 l 15 15 l 15 5 l h", (2, 2), True, True),
        ("10 19 m 15 2 l 2 13 l 18 13 l 5 2 l h", (10, 10), True, False),  # self-intersecting star: centre
        ("10 19 m 15 2 l 2 13 l 18 13 l 5 2 l h", (10, 16), True, True),  # a tip
        ("10 19 m 15 2 l 2 13 l 18 13 l 5 2 l h", (1, 1), False, False),
        ("0 0 m 12 0 l 12 12 l", (9, 4), True, True),  # open subpath: fill closes it
        ("0 0 m 12 0 l 12 12 l", (4, 9), False, False),
        ("0 0 m 12 0 l 12 12 l", (5, 5), True, True),  # on the implicit closing diagonal
        ("0 0 m 12 0 l 12 12 l", (6, 0), True, True),  # on a horizontal edge
        ("0 0 m 12 0 l 12 12 l", (12, 12), True, True),  # on a vertex
        ("0 0 m 12 0 l 12 12 l", (-1, 0), False, False),  # on the extension of a horizontal edge
        ("0 0 4 4 re 12 0 4 4 re", (2, 2), True, True),  # two disjoint contours
        ("0 0 4 4 re 12 0 4 4 re", (14, 2), True, True),
        ("0 0 4 4 re 12 0 4 4 re", (8, 2), False, False),  # the gap between them
        ("0 0 4 4 re 4 0 m 8 0 l 8 4 l 4 4 l h", (6, 2), True, True),  # contours sharing an edge are not joined
    ],
)
def test_fill_inside_rules(small_batches, stream, point, nonzero, evenodd):
    for op, expected in (("f", nonzero), ("F", nonzero), ("f*", evenodd)):
        idx = _scan(f"{stream} {op}")
        assert bool(_click(idx, *point).any()) is expected, (stream, op, point)


@pytest.mark.parametrize("op", ["B", "b"])
def test_nonzero_and_evenodd_follow_the_combined_paint(op):
    stream = OUTER + "5 5 10 10 re"
    assert _click(_scan(f"{stream} B"), 10, 10).any()
    assert not _click(_scan(f"{stream} B*"), 10, 10).any()
    assert not _click(_scan(f"{stream} b*"), 10, 10).any()
    assert _click(_scan(f"{stream} {op}"), 10, 10).any()


def test_open_subpath_closing_edge_is_fill_only():
    assert not _click(_scan("0 w 0 0 m 12 0 l 12 12 l S"), 5, 5).any()
    assert _click(_scan("0 0 m 12 0 l 12 12 l f"), 5, 5).any()


def test_cubic_sliver_is_hit_inside_and_missed_outside():
    idx = _scan("0 0 m 1 .009 2 .009 3 0 c h f")
    assert _click(idx, 1.5, 0.003).any(), "a true interior point of a painted sliver must hit"
    assert not _click(idx, 1.5, 0.015).any()
    assert not _click(idx, 1.5, -0.015).any()


@pytest.mark.parametrize("paint", ["S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"])
def test_each_paint_code_picks_what_it_paints(paint):
    stream = f"10 w 0 0 m 40 0 l 40 40 l 0 40 l {paint}"
    idx = _scan(stream)
    editable = bool(int(idx.paths["flags"][0]) & int(PathFlag.EDITABLE))
    strokes = paint in ("S", "s", "B", "B*", "b", "b*")
    fills = paint in ("f", "F", "f*", "B", "B*", "b", "b*")
    if paint == "n":
        assert not editable
        assert not _click(idx, 0, 20).any() and not _click(idx, 20, 20).any()
        return
    assert editable
    assert bool(_click(idx, 20, 20).any()) is fills  # deep inside: fill only
    assert bool(_click(idx, 43, 20).any()) is strokes  # beside the right side, inside a 10 pt stroke, outside the fill
    assert not _click(idx, 60, 20).any()  # outside everything


def test_stroke_only_picks_by_centreline_widened_to_half_width():
    idx = _scan("20 w 0 10 m 100 10 l S")
    assert _click(idx, 50, 19).any() and not _click(idx, 50, 21).any()
    assert not _click(idx, 50, 21, tol=2.0).any()  # radius is max(tolerance, half width), not the sum
    assert _click(idx, 50, 21, tol=11.5).any()


def test_click_is_topmost_and_a_fill_beats_a_lower_stroke():
    idx = _scan("0 0 20 20 re f 0 0 20 20 re f")
    assert _hits(_click(idx, 10, 10)) == [1]
    idx = _scan("4 w 0 10 m 20 10 l S 0 0 20 20 re f")
    assert _hits(_click(idx, 10, 10)) == [1]
    idx = _scan("0 0 20 20 re f 4 w 0 10 m 20 10 l S")
    assert _hits(_click(idx, 10, 10)) == [1]


def test_click_nothing_beyond_tolerance_and_empty_page():
    idx = _scan("0 w 0 0 m 10 0 l S")
    assert not _click(idx, 5, 1, tol=0.5).any()
    assert _click(idx, 5, 0.4, tol=0.5).any()
    assert not qi.select(_scan(""), (0, 0, 0, 0), 1.0, "click").any()


# --------------------------------------------------------------------------- marquee

FRAME_RECT = "0 w 0 0 100 100 re S"


def test_touch_inside_a_large_frame_does_not_select_it_but_crossing_does():
    idx = _scan(FRAME_RECT)
    assert not qi.select(idx, (20, 20, 80, 80), 0.0, "touch").any()
    assert qi.select(idx, (90, 40, 110, 60), 0.0, "touch").any()


def test_fill_counts_through_its_outline_only_in_touch():
    idx = _scan("0 0 100 100 re f")
    assert not qi.select(idx, (20, 20, 80, 80), 0.0, "touch").any()
    assert qi.select(idx, (-5, 40, 5, 60), 0.0, "touch").any()


def test_touch_takes_a_path_wholly_inside_and_contain_needs_the_box_inside():
    idx = _scan("0 w 10 10 m 20 20 l S")
    assert qi.select(idx, (0, 0, 30, 30), 0.0, "touch").any()
    assert qi.select(idx, (0, 0, 30, 30), 0.0, "contain").any()
    assert qi.select(idx, (15, 0, 30, 30), 0.0, "touch").any()
    assert not qi.select(idx, (15, 0, 30, 30), 0.0, "contain").any()


def test_wide_stroke_is_selected_only_when_the_marquee_reaches_its_centreline():
    idx = _scan("20 w 0 50 m 100 50 l S")
    assert not qi.select(idx, (40, 55, 60, 70), 0.0, "touch").any()
    assert qi.select(idx, (40, 45, 60, 70), 0.0, "touch").any()


def test_a_marquee_inside_a_dash_gap_selects_the_path():
    idx = _scan("0 w [2 20] 0 d 0 0 m 100 0 l S")
    assert qi.select(idx, (5, -1, 10, 1), 0.0, "touch").any()


def test_curve_marquee_uses_the_curve_not_the_control_polygon():
    idx = _scan("0 w 0 0 m 0 100 100 100 100 0 c S")  # apex at y = 75
    assert not qi.select(idx, (40, 75.5, 60, 90), 0.0, "touch").any()  # 0.5 pt outside the true extent, inside the control polygon
    assert qi.select(idx, (40, 74, 60, 90), 0.0, "touch").any()


@pytest.mark.parametrize("rect", [(5, 5, 5, 5), (5, 5, 5, 9), (9, 5, 5, 9), (500, 500, 600, 600), (-600, -600, -500, -500)])
@pytest.mark.parametrize("mode", ["touch", "contain"])
def test_zero_size_and_off_page_rectangles_select_nothing(rect, mode):
    assert not qi.select(_scan("0 0 20 20 re f 0 w 0 0 m 30 30 l S"), rect, 0.0, mode).any()


def test_non_editable_rows_are_never_selected():
    idx = _scan("/OC /x BDC 0 w 0 0 m 30 0 l S EMC 0 w 0 5 m 30 5 l S")
    assert int(idx.paths["flags"][0]) & int(PathFlag.IN_OC)
    for mode in ("touch", "contain"):
        assert _hits(qi.select(idx, (-1, -1, 40, 10), 0.0, mode)) == [1]
    assert _hits(_click(idx, 10, 0, tol=1.0)) == []


def _brute_touch(idx, rect):
    x0, y0, x1, y1 = rect
    out = np.zeros(len(idx.paths), dtype=bool)
    s = idx.segments
    for i, p in enumerate(idx.paths):
        if not int(p["flags"]) & int(PathFlag.EDITABLE):
            continue
        for j in range(int(p["seg_start"]), int(p["seg_start"]) + int(p["seg_count"])):
            ax, ay, bx, by = (float(s[j][k]) for k in ("x0", "y0", "x1", "y1"))
            t0, t1, dx, dy = 0.0, 1.0, bx - ax, by - ay
            ok = True
            for pp, qq in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
                if pp == 0:
                    if qq < 0:
                        ok = False
                        break
                else:
                    r = qq / pp
                    if pp < 0:
                        t0 = max(t0, r)
                    else:
                        t1 = min(t1, r)
                    if t0 > t1:
                        ok = False
                        break
            if ok:
                out[i] = True
                break
    return out


def test_fast_path_equals_the_plain_segment_test_on_random_rectangles():
    rng = random.Random(1125)
    parts = []
    for _ in range(60):
        x, y = rng.uniform(0, 400), rng.uniform(0, 400)
        kind = rng.choice("lcr")
        if kind == "l":
            parts.append(f"0 w {x:.3f} {y:.3f} m {x + rng.uniform(-60, 60):.3f} {y + rng.uniform(-60, 60):.3f} l S")
        elif kind == "c":
            c = [rng.uniform(-50, 50) for _ in range(6)]
            parts.append(f"0 w {x:.3f} {y:.3f} m {x + c[0]:.3f} {y + c[1]:.3f} {x + c[2]:.3f} {y + c[3]:.3f} {x + c[4]:.3f} {y + c[5]:.3f} c S")
        else:
            parts.append(f"{x:.3f} {y:.3f} {rng.uniform(1, 80):.3f} {rng.uniform(1, 80):.3f} re f")
    idx = _scan(" ".join(parts))
    for _ in range(200):
        a, b = rng.uniform(-20, 420), rng.uniform(-20, 420)
        rect = (a, b, a + rng.uniform(0.5, 150), b + rng.uniform(0.5, 150))
        got = qi.select(idx, rect, 0.0, "touch")
        want = _brute_touch(idx, rect)
        assert np.array_equal(got, want), rect


# --------------------------------------------------------------------------- CLIPPED

CLIP = "q 0 0 5 5 re W n 0 w 0 5 m 80 5 l S Q 0 w 0 20 m 80 20 l S"


def test_clipped_row_is_selectable_by_its_constructed_geometry_and_the_setter_is_not():
    idx = _scan(CLIP)
    assert [int(f) for f in idx.paths["flags"]] == [4, 9, 1]
    assert _hits(_click(idx, 50, 5)) == [1]  # the part the clip hides still hits: constructed geometry
    assert _hits(qi.select(idx, (40, 0, 60, 10), 0.0, "touch")) == [1]
    assert _hits(qi.select(idx, (-1, -1, 90, 30), 0.0, "contain")) == [1, 2]  # whole constructed bbox
    assert _hits(qi.select(idx, (-1, -1, 6, 6), 0.0, "touch")) == [1]  # never the SETS_CLIP row 0


# --------------------------------------------------------------------------- combine, summary, segments


def test_combine_replace_add_toggle():
    old = np.array([True, False, True, False])
    new = np.array([False, True, True, False])
    assert qi.combine(old, new, "replace").tolist() == [False, True, True, False]
    assert qi.combine(old, new, "add").tolist() == [True, True, True, False]
    assert qi.combine(old, new, "toggle").tolist() == [True, True, False, False]
    assert old.tolist() == [True, False, True, False]  # inputs untouched


def test_summary_counts_selected_skipped_and_bbox():
    idx = _scan("/OC /x BDC 0 w 0 0 m 30 0 l S EMC 0 w 10 10 m 20 40 l S 0 w 50 50 m 60 70 l S")
    mask = np.array([True, True, False])
    selected, skipped, bbox = qi.summary(idx, mask)
    assert (selected, skipped) == (1, 1)  # the IN_OC row is skipped, never counted as selected
    assert bbox is not None and bbox[0] <= 10 and bbox[1] <= 10 and bbox[2] >= 20 and bbox[3] >= 40
    assert qi.summary(idx, np.zeros(3, dtype=bool)) == (0, 0, None)


def test_selected_segments_are_float32_k_by_4_of_the_selected_rows_only():
    idx = _scan("0 w 1 2 m 3 4 l S 0 w 5 6 m 7 8 l S")
    seg = qi.selected_segments(idx, np.array([False, True]))
    assert seg.dtype == np.float32 and seg.shape == (1, 4)
    assert seg[0].tolist() == [5.0, 6.0, 7.0, 8.0]
    assert qi.selected_segments(idx, np.zeros(2, dtype=bool)).shape == (0, 4)


def test_bad_mode_and_bad_mask_are_refused():
    idx = _scan("0 w 0 0 m 1 1 l S")
    with pytest.raises(ValueError):
        qi.select(idx, (0, 0, 1, 1), 0.0, "lasso")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        qi.combine(np.zeros(2, dtype=bool), np.zeros(3, dtype=bool), "add")
