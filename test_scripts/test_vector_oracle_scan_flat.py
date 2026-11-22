"""Card B1 completion, items 1 and 2: O-scan and O-flat, built against the twins and calibrated.

Both oracles take their product-side input as an argument (an index-row list); the rows used here are
derived from the fixture builder's own records, never from a product scanner (none exists yet, card B2).
Must-kill is decided from ground truth computed beside the cell, never by running an oracle.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_index_rows as vir  # noqa: E402
from test_scripts import vector_matching as vm  # noqa: E402
from test_scripts import vector_oracle_extra as voe  # noqa: E402
from test_scripts import vector_oracle_flat as vof  # noqa: E402
from test_scripts import vector_oracle_scan as vos  # noqa: E402


def _pages() -> list[tuple[str, vfb.PageSpec]]:
    base = vfb.sample_scene().pages[0]
    out = [("sample", base)]
    out += [(f"rot{r}", vfb.replace(base, rotate=r)) for r in (90, 180, 270)]
    out.append(("cropbox", vfb.replace(base, cropbox=(10.0, 20.0, 150.0, 190.0))))
    out.append(("userunit2", vfb.replace(base, userunit=2.0)))
    out.append(("merged_pair", voe.merged_pair_page()))
    return out


# ----------------------------------------------------------------------------- O-scan


def test_scan_rows_derived_from_the_builder_pass_on_every_page_frame() -> None:
    for name, page in _pages():
        data = vfb.build(vfb.Scene((page,)))
        rows = vir.rows_from_page(page)
        assert vos.o_scan(data, rows, frame=vir.frame_of(page)) == [], name


def test_scan_alignment_maps_drawings_to_rows_and_pairs_a_merged_fill_and_stroke() -> None:
    page = voe.merged_pair_page()
    data = vfb.build(vfb.Scene((page,)))
    rows = vir.rows_from_page(page)
    al = vos.scan_alignment(fitz.open(stream=data, filetype="pdf")[0].get_cdrawings(), rows, vir.frame_of(page))
    assert al.violations == []
    assert al.pairs[0] == (0,)
    assert al.pairs[1] == (1, 2)  # the 'fs' drawing is the fill row and the stroke row
    assert len(al.pairs) == 4  # line, merged pair, rectangle, curve


def test_scan_must_pass_and_must_kill_cells_over_every_frame() -> None:
    cells = [c for name, page in _pages() for c in voe.scan_cells(name, page)]
    rep = voe.calibrate_cells(cells, {"O-scan": vos.o_scan})
    assert rep.ok, "\n".join(rep.failures[:30])
    assert rep.must_kill["O-scan"] >= 40
    assert rep.must_pass["O-scan"] >= 30


def test_scan_rejects_the_named_mutants_directly() -> None:
    page = vfb.sample_scene().pages[0]
    data = vfb.build(vfb.Scene((page,)))
    frame = vir.frame_of(page)
    rows = vir.rows_from_page(page)
    first = next(i for i, r in enumerate(rows) if r.paint != "n" and r.segments)
    moved = list(rows)
    x0, y0, x1, y1, fc = rows[first].segments[0]
    moved[first] = vir.IndexRow(rows[first].paint, ((x0 + 0.05, y0, x1, y1, fc), *rows[first].segments[1:]), rows[first].cubics)
    assert vos.o_scan(data, moved, frame=frame)
    assert vos.o_scan(data, rows[:first] + rows[first + 1 :], frame=frame)
    assert vos.o_scan(data, [*rows, vir.IndexRow("S", ((1.0, 1.0, 2.0, 2.0, False),), ())], frame=frame)
    swapped = list(rows)
    swapped[first], swapped[first + 1] = swapped[first + 1], swapped[first]
    assert vos.o_scan(data, swapped, frame=frame)
    assert vos.o_scan(data, rows, frame=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0))  # the wrong page frame


def _dihedral_sequences(corners: list[tuple[float, float]]) -> set[tuple[tuple[float, float, float, float], ...]]:
    """Ground truth beside the oracle: the 8 directed edge sequences that trace the same rectangle (4
    start corners, 2 windings).  Anything else changes the geometry.  No oracle, no tolerance."""
    out = set()
    for ring in (corners, corners[::-1]):
        for s in range(4):
            r = ring[s:] + ring[:s]
            out.add(tuple((*r[k], *r[(k + 1) % 4]) for k in range(4)))
    return out


@pytest.mark.parametrize("ctm", [vfb.IDENT, (0.8, 0.6, -0.6, 0.8, 30.0, 10.0)], ids=["axis_aligned", "cm_rotated_quad"])
def test_scan_rect_every_wrong_corner_connection_is_rejected(ctm) -> None:
    """Astra B1 (class: lossy oracle comparison).  Enumerate EVERY way to fill a rectangle row's four line
    slots from the 12 directed corner pairs: each geometry-changing row must be rejected (four edges
    replaced by diagonals, swapped corner pairs, broken chains); each traversal of the same rectangle
    (rotated start, reversed winding) is the same shape and must pass."""
    import itertools

    page = vfb.PageSpec((vfb._p("rect", ((40.0, 50.0), (120.0, 90.0)), "S", ctm),))
    data = vfb.build(vfb.Scene((page,)))
    frame = vir.frame_of(page)
    good = vir.rows_from_page(page)
    assert len(good) == 1 and len(good[0].segments) == 4
    corners = [(s[0], s[1]) for s in good[0].segments]
    drawings = vos.comparable_drawings(data)
    assert len(drawings) == 1
    kind = drawings[0]["items"][0][0]
    # MuPDF keeps an axis-aligned rectangle as one 're' item (start corner and winding are lost: any
    # traversal is the same shape); a cm-rotated one may stay four 'l' items, compared in order.
    assert kind in ("re", "qu", "l")
    same = _dihedral_sequences(corners) if kind != "l" else {tuple((*s[:4],) for s in good[0].segments)}
    if ctm == vfb.IDENT:
        assert kind == "re"
    directed = [(*a, *b) for a in corners for b in corners if a != b]
    assert len(directed) == 12
    wrong = accepted_wrong = rejected_same = 0
    for combo in itertools.product(directed, repeat=4):
        row = vir.IndexRow("S", tuple((*e, False) for e in combo), ())
        accepted = not vos.scan_alignment(drawings, [row], frame).violations
        if combo in same:
            rejected_same += 0 if accepted else 1
        else:
            wrong += 1
            accepted_wrong += 1 if accepted else 0
    assert wrong == 12**4 - len(same)
    assert accepted_wrong == 0, f"{accepted_wrong} geometry-changing rectangle rows were accepted"
    assert rejected_same == 0, "a traversal of the same rectangle was rejected"


def test_scan_the_old_separate_corner_set_comparison_accepted_diagonals() -> None:
    """Records the defect the family above closes: starts-as-a-set plus ends-as-a-set accepts diagonals."""
    c = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
    diagonals = [(c[0], c[2]), (c[1], c[3]), (c[2], c[0]), (c[3], c[1])]
    assert vos._same_point_set(c, [d[0] for d in diagonals]) and vos._same_point_set(c, [d[1] for d in diagonals])
    assert not vos.rect_edges_match(c, diagonals)


def test_o_flat_rejects_non_finite_coordinates_at_every_position() -> None:
    """Astra B3: ``NaN > tolerance`` is False, so NaN geometry slid through every comparison.  Put NaN and
    +/-inf at every coordinate of the cubic's control points and of every chord endpoint."""
    page = vfb.sample_scene().pages[0]
    rows = vir.rows_from_page(page)
    ri = next(i for i, r in enumerate(rows) if r.cubics)
    row = rows[ri]
    assert vof.o_flat([row]) == []
    start, count, coords = row.cubics[0]
    for bad in (math.nan, math.inf, -math.inf):
        for k in range(8):  # control point coordinates
            c = list(coords)
            c[k] = bad
            mutant = vir.IndexRow(row.paint, row.segments, ((start, count, tuple(c)), *row.cubics[1:]))
            assert vof.o_flat([mutant]), f"control coordinate {k} = {bad}"
        for si in range(start, start + count):  # chord endpoints, every slot
            for slot in range(4):
                segs = [list(s) for s in row.segments]
                segs[si][slot] = bad
                mutant = vir.IndexRow(row.paint, tuple(tuple(s) for s in segs), row.cubics)  # type: ignore[arg-type]
                assert vof.o_flat([mutant]), f"chord {si} slot {slot} = {bad}"


def test_scan_accepts_degenerate_rows_and_ignores_chords() -> None:
    page = vfb.sample_scene().pages[0]
    data = vfb.build(vfb.Scene((page,)))
    frame = vir.frame_of(page)
    rows = vir.rows_from_page(page)
    degenerate = vir.IndexRow("S", (), ())
    assert degenerate.degenerate
    with_extra = [degenerate, *rows[:3], degenerate, degenerate, *rows[3:], degenerate]
    assert vos.o_scan(data, with_extra, frame=frame) == []
    wild = []
    for r in rows:
        segs = tuple((x0 + 7, y0 - 3, x1 + 9, y1 + 5, True) if fc else (x0, y0, x1, y1, fc) for x0, y0, x1, y1, fc in r.segments)
        wild.append(vir.IndexRow(r.paint, segs, r.cubics))
    assert vos.o_scan(data, wild, frame=frame) == []


def test_scan_alignment_survives_a_zero_extent_drawing_for_a_degenerate_row() -> None:
    """S0-P2: a DEGENERATE row may still have a zero-extent drawing; the lists then align row for row."""
    page = vfb.PageSpec((vfb._p("line", ((10.0, 10.0), (10.0, 10.0)), "S"), vfb._p("line", ((20.0, 20.0), (40.0, 40.0)), "S")))
    data = vfb.build(vfb.Scene((page,)))
    rows = vir.rows_from_page(page)
    assert not rows[0].degenerate  # a zero-length line still has one segment
    assert vos.o_scan(data, rows, frame=vir.frame_of(page)) == []
    flat = [vir.IndexRow("S", (), ()), *rows]
    assert vos.o_scan(data, flat, frame=vir.frame_of(page)) == []


@pytest.mark.parametrize("calls", [1, 99, 100, 300])
def test_the_comparable_list_survives_any_number_of_do_calls(calls: int) -> None:
    """Emptying /XObject made every ``Do`` a MuPDF syntax error and MuPDF ignores the rest of the page after
    100 of them: the drawings after the calls must stay in the comparable list."""
    page = vfb.PageSpec(
        (
            vfb._p("line", ((10.0, 10.0), (60.0, 20.0)), "S"),
            vfb.RawSpec(b"/Fm0 Do\n" * calls, "forms"),
            vfb._p("line", ((20.0, 120.0), (90.0, 150.0)), "S", stroke=(1.0, 0.0, 0.0)),
        )
    )
    data = voe.add_form(vfb.build(vfb.Scene((page,))))
    drawings = vos.comparable_drawings(data)
    assert len(drawings) == 2, len(drawings)
    rows = vir.rows_from_page(page)
    assert vos.o_scan(data, rows, frame=vir.frame_of(page)) == []


def test_scan_a_row_list_shorter_than_the_drawings_is_rejected() -> None:
    page = vfb.sample_scene().pages[0]
    data = vfb.build(vfb.Scene((page,)))
    assert vos.o_scan(data, [], frame=vir.frame_of(page))


def test_scan_blind_paranoid_and_gap_guards() -> None:
    cells = voe.scan_cells("sample", vfb.sample_scene().pages[0])

    def blind(**_kw: object) -> list[str]:
        return []

    blind.DOMAIN = vos.o_scan.DOMAIN  # type: ignore[attr-defined]
    rep = voe.calibrate_cells(cells, {"O-scan": blind})
    assert any("O-scan is blind" in f for f in rep.failures)

    def paranoid(**_kw: object) -> list[str]:
        return ["always"]

    paranoid.DOMAIN = vos.o_scan.DOMAIN  # type: ignore[attr-defined]
    assert any("rejects must-pass" in f for f in voe.calibrate_cells(cells, {"O-scan": paranoid}).failures)
    idle = voe.calibrate_cells(cells, {"O-scan": vos.o_scan, "O-flat": vof.o_flat})
    assert any("O-flat has an empty must-kill column" in f for f in idle.failures)
    gap = voe.calibrate_cells(cells, {"O-flat": vof.o_flat})
    assert any(f.startswith("coverage gap") for f in gap.failures)


# ----------------------------------------------------------------------------- O-flat


def test_curve_twins_exist_in_the_builder_and_match_mupdf() -> None:
    twins = voe.curve_twin_pages()
    assert {n.split("/")[0] for n, _p in twins} == {"cusp", "loop", "near_straight", "long5000"}
    assert {n.split("/")[1] for n, _p in twins} == {"identity", "scale", "rotate", "shear"}
    for name, page in twins:
        data = vfb.build(vfb.Scene((page,)))
        drawings = fitz.open(stream=data, filetype="pdf")[0].get_cdrawings()
        cubic = vir.rows_from_page(page)[0].cubics[0][2]
        got = next(it for it in drawings[0]["items"] if it[0] == "c")
        frame = vir.frame_of(page)
        for k in range(4):
            fx, fy = got[1 + k]
            ex, ey = vir.apply_frame(frame, (cubic[2 * k], cubic[2 * k + 1]))
            assert vm.coordinates_match(fx, ex) and vm.coordinates_match(fy, ey), (name, k)


def test_the_loop_twin_self_intersects_and_the_cusp_twin_has_a_stationary_point() -> None:
    import numpy as np

    ts = np.linspace(0.0, 1.0, 801)

    def curve(shape: str) -> np.ndarray:
        p = np.array(voe._SHAPES[shape], dtype=float)
        return voe._bern(p, ts)

    loop = curve("loop")
    dist = np.linalg.norm(loop[:, None, :] - loop[None, :, :], axis=2)
    far = np.abs(ts[:, None] - ts[None, :]) > 0.3
    assert dist[far].min() < 0.5
    cusp_speed = np.linalg.norm(voe._dbern(np.array(voe._SHAPES["cusp"], dtype=float), ts), axis=1)
    assert cusp_speed.min() < 1e-6
    assert np.linalg.norm(voe._dbern(np.array(voe._SHAPES["near_straight"], dtype=float), ts), axis=1).min() > 1.0


def test_o_flat_must_pass_and_must_kill_on_every_twin() -> None:
    cells = [c for name, page in voe.curve_twin_pages() for c in voe.flat_cells(name, vir.rows_from_page(page))]
    rep = voe.calibrate_cells(cells, {"O-flat": vof.o_flat})
    assert rep.ok, "\n".join(rep.failures[:30])
    assert rep.must_kill["O-flat"] >= 3 * 16
    assert rep.must_pass["O-flat"] >= 16


def test_reference_chords_follow_the_design_formula() -> None:
    p = ((0.0, 0.0), (100.0, 100.0), (0.0, 100.0), (100.0, 0.0))
    chords = vir.reference_chords(p, 0.01)
    m = max(math.dist((p[0][0] - 2 * p[1][0] + p[2][0], p[0][1] - 2 * p[1][1] + p[2][1]), (0, 0)),
            math.dist((p[1][0] - 2 * p[2][0] + p[3][0], p[1][1] - 2 * p[2][1] + p[3][1]), (0, 0)))
    assert len(chords) == math.ceil(math.sqrt(0.75 * m / 0.01))


def test_o_flat_direct_mutants() -> None:
    page = dict(voe.curve_twin_pages())["loop/shear"]
    rows = vir.rows_from_page(page)
    assert vof.o_flat(rows) == []
    seg = list(rows[0].segments)
    mid = len(seg) // 2
    off = list(seg)
    x0, y0, x1, y1, fc = off[mid]
    off[mid] = (x0, y0, x1 + 0.05, y1, fc)  # a vertex off the curve (and a gap in the chain)
    assert vof.o_flat([vir.IndexRow(rows[0].paint, tuple(off), rows[0].cubics)])
    gap = seg[:mid] + seg[mid + 1 :]
    cubic = rows[0].cubics[0]
    assert vof.o_flat([vir.IndexRow(rows[0].paint, tuple(gap), ((cubic[0], cubic[1] - 1, cubic[2]),))])
    coarse = [seg[0][:2] + seg[-1][2:4] + (True,)]
    assert vof.o_flat([vir.IndexRow(rows[0].paint, tuple(coarse), ((0, 1, cubic[2]),))])


def test_o_flat_uses_one_absolute_vertex_tolerance_at_every_scale() -> None:
    """A vertex 3e-6 or 1e-5 pt off a 5,000 pt curve is a defect (ground truth is 1e-6 absolute); the oracle
    must not widen its tolerance with the page scale, and ground truth must use the oracle's function."""
    import numpy as np

    page = dict(voe.curve_twin_pages())["long5000/identity"]
    p4 = np.array(voe._SHAPES["long5000"], dtype=float)
    assert vof.vertex_tolerance(p4) == vof.VERTEX_TOL == 1e-6
    assert vof.vertex_tolerance(p4 * 100.0) == 1e-6
    row = vir.rows_from_page(page)[0]
    assert vof.o_flat([row]) == []
    mid = len(row.segments) // 2
    for amount, rejected in ((3e-6, True), (1e-5, True), (5e-7, False)):
        seg = list(row.segments)
        a0, b0, a1, b1, fc = seg[mid - 1]
        c0, d0, c1, d1, fc2 = seg[mid]
        v = seg[mid - 1]
        nx, ny = -(v[3] - v[1]), v[2] - v[0]
        norm = math.hypot(nx, ny)
        dx, dy = amount * nx / norm, amount * ny / norm
        seg[mid - 1] = (a0, b0, a1 + dx, b1 + dy, fc)
        seg[mid] = (c0 + dx, d0 + dy, c1, d1, fc2)
        got = vof.o_flat([vir.IndexRow(row.paint, tuple(seg), row.cubics)])
        assert bool(got) is rejected, (amount, got)


def test_o_flat_accepts_equal_parameter_vertices_of_any_chord_count_above_the_bound() -> None:
    """A finer chord list (more vertices on the curve) is still correct."""
    page = dict(voe.curve_twin_pages())["cusp/rotate"]
    row = vir.rows_from_page(page)[0]
    p4 = tuple((row.cubics[0][2][2 * k], row.cubics[0][2][2 * k + 1]) for k in range(4))
    finer = vir.chords_with_count(p4, len(row.segments) * 2 + 1)
    assert vof.o_flat([vir.IndexRow(row.paint, finer, ((0, len(finer), row.cubics[0][2]),))]) == []


def test_o_flat_rejects_a_chord_run_not_flagged_from_cubic_and_a_malformed_row() -> None:
    page = dict(voe.curve_twin_pages())["near_straight/identity"]
    row = vir.rows_from_page(page)[0]
    unflagged = tuple((a, b, c, d, False) for a, b, c, d, _f in row.segments)
    assert vof.o_flat([vir.IndexRow(row.paint, unflagged, row.cubics)])
    assert vof.o_flat([vir.IndexRow(row.paint, row.segments, ((0, len(row.segments) + 3, row.cubics[0][2]),))])


@pytest.mark.parametrize("name", ["cusp/identity", "long5000/shear"])
def test_o_flat_runs_in_a_bounded_time(name: str) -> None:
    import time

    page = dict(voe.curve_twin_pages())[name]
    rows = vir.rows_from_page(page)
    start = time.perf_counter()
    assert vof.o_flat(rows) == []
    assert time.perf_counter() - start < 20.0


# ----------------------------------------------------------------------------- comparable list, topologies, joint registry


def test_scan_runs_against_the_comparable_list_not_the_whole_page() -> None:
    cells = voe.domain_cells()
    rep = voe.calibrate_cells(cells, {"O-scan": vos.o_scan})
    assert rep.ok, "\n".join(rep.failures[:10])
    assert rep.must_kill["O-scan"] >= 10
    page = voe.inline_image_page()
    data = vfb.build(vfb.Scene((page,)))
    whole = fitz.open(stream=data, filetype="pdf")[0].get_cdrawings()
    comparable = vos.comparable_drawings(data)
    assert len(whole) == 2 and len(comparable) == 1  # MuPDF draws past the BI, the comparable list does not
    fpage, fdata = voe.form_page_data()
    assert len(fitz.open(stream=fdata, filetype="pdf")[0].get_cdrawings()) == 3  # the form's line too
    assert len(vos.comparable_drawings(fdata)) == 2


def test_scan_must_pass_on_every_default_topology() -> None:
    cells = []
    for name, scene in vfb.default_scenes():
        cells += voe.scan_cells(name, scene.pages[0], scene=scene)
    rep = voe.calibrate_cells(cells, {"O-scan": vos.o_scan})
    assert rep.ok, "\n".join(rep.failures[:10])


def test_joint_row_oracle_registry_runs_the_real_guards() -> None:
    cells = [c for name, page in _pages() for c in voe.scan_cells(name, page)]
    cells += [c for name, page in voe.curve_twin_pages()[:4] for c in voe.flat_cells(name, vir.rows_from_page(page))]
    rep = voe.calibrate_cells(cells, voe.ROW_ORACLES)
    assert rep.ok, "\n".join(rep.failures[:10])
    assert set(rep.must_kill) == {"O-scan", "O-flat"} and all(n > 0 for n in rep.must_kill.values())
    assert voe.ROW_ORACLES["O-scan"].DOMAIN == {"SCAN_ROWS"} and voe.ROW_ORACLES["O-flat"].DOMAIN == {"CHORDS"}
