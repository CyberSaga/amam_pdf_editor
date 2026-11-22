"""Calibration of the row-fed oracles of card B1 completion (O-scan, O-flat) and shared cell machinery.

These oracles take product-side input (an index-row list) instead of a before/after pair, so they
cannot run in ``vector_oracles.calibrate``'s mutant matrix.  They are calibrated here with the same
rules (design plan D23 rule A): a *cell* is an input plus the fact kinds it violates.  Whether a cell
is must-kill is decided by a ground-truth comparison written beside the cell (a plain structural
comparison, no alignment, no MuPDF, never an oracle); an oracle runs on a must-kill cell only when the
cell's kinds meet the oracle's ``DOMAIN``; a cell violating a kind no registered oracle covers is a
coverage gap and fails the run; a registered oracle with an empty must-kill column fails the run; a
blind oracle (accepts a must-kill cell) and a paranoid one (rejects a must-pass cell) fail the run.

The oracles that do take a before/after pair (O-struct mapped, O-reopen, O-vendor) are registered in
``vector_oracles.calibrate`` itself (see ``vector_oracle_saved``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import fitz
import numpy as np

from test_scripts import vector_fixture_builder as vfb
from test_scripts import vector_index_rows as vir
from test_scripts import vector_oracle_flat as vof
from test_scripts import vector_oracle_scan as vos
from test_scripts import vector_oracles as vo
from test_scripts.vector_index_rows import IndexRow, chords_with_count, frame_of, reference_chords, row_primitives, rows_from_page

SCAN_ROWS = "SCAN_ROWS"
CHORDS = "CHORDS"
EXTRA_FACT_KINDS = (SCAN_ROWS, CHORDS)
ROW_ORACLES: dict[str, Callable[..., list[str]]] = {"O-scan": vos.o_scan, "O-flat": vof.o_flat}
TOL = 1e-3


@dataclass(frozen=True)
class Cell:
    name: str
    kinds: frozenset[str]  # fact kinds this input violates (ground truth); empty = must pass
    args: dict[str, dict[str, object]] = field(default_factory=dict)  # oracle name -> keyword arguments


def calibrate_cells(cells: Sequence[Cell], oracles: dict[str, Callable[..., list[str]]]) -> vo.Report:
    """Run every oracle on every cell it is responsible for (see the module docstring)."""
    rep = vo.Report()
    for name in oracles:
        rep.must_kill[name] += 0
        rep.must_pass[name] += 0
    for cell in cells:
        rep.cells += 1
        if not cell.kinds:
            for oname, kw in cell.args.items():
                if oname in oracles:
                    rep.must_pass[oname] += 1
                    viol = oracles[oname](**kw)
                    if viol:
                        rep.failures.append(f"{oname} rejects must-pass input {cell.name!r}: {viol[0]}")
            continue
        if not any(set(cell.kinds) & set(fn.DOMAIN) for fn in oracles.values()):  # type: ignore[attr-defined]
            rep.failures.append(f"coverage gap: mutant {cell.name!r} violates {sorted(cell.kinds)} in no oracle's domain")
        for oname, kw in cell.args.items():
            fn = oracles.get(oname)
            if fn is None or not set(cell.kinds) & set(fn.DOMAIN):  # type: ignore[attr-defined]
                continue
            rep.must_kill[oname] += 1
            if not fn(**kw):
                rep.failures.append(f"{oname} is blind to mutant {cell.name!r} (facts differ in {sorted(cell.kinds)})")
    for oname, n in rep.must_kill.items():
        if n == 0:
            rep.failures.append(f"{oname} has an empty must-kill column: it judges nothing")
    return rep


# --------------------------------------------------------------------------- twins


def merged_pair_page() -> vfb.PageSpec:
    """A fill and a stroke of one polygon (MuPDF reports them as one ``fs`` drawing) among other paths."""
    poly = ((10.0, 10.0), (60.0, 20.0), (40.0, 50.0))
    return vfb.PageSpec(
        (
            vfb._p("line", ((5.0, 100.0), (80.0, 120.0)), "S", stroke=(1.0, 0.0, 0.0)),
            vfb._p("poly", poly, "f", fill=(1.0, 0.0, 0.0), width=3.0, stroke=(0.0, 0.0, 1.0)),
            vfb._p("poly", poly, "S", fill=(1.0, 0.0, 0.0), width=3.0, stroke=(0.0, 0.0, 1.0)),
            vfb._p("rect", ((70.0, 70.0), (90.0, 90.0)), "B", fill=(0.0, 1.0, 0.0), stroke=(0.0, 0.0, 0.0)),
            vfb._p("curve", ((100.0, 10.0), (120.0, 60.0), (150.0, 60.0), (170.0, 10.0)), "S"),
        )
    )


def inline_image_page() -> vfb.PageSpec:
    """A path, an inline image, then another path: the index stops at ``BI``, MuPDF does not."""
    image = vfb.RawSpec(b"q 10 0 0 10 100 100 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI Q", vir.INLINE_IMAGE_LABEL)
    return vfb.PageSpec(
        (
            vfb._p("line", ((10.0, 10.0), (60.0, 20.0)), "S"),
            image,
            vfb._p("line", ((20.0, 120.0), (90.0, 150.0)), "S", stroke=(1.0, 0.0, 0.0)),
        )
    )


def form_page_data() -> tuple[vfb.PageSpec, bytes]:
    """Page 0 draws a line, calls ``/Fm0 Do`` (a form that draws a line too), then draws another line."""
    page = vfb.PageSpec(
        (
            vfb._p("line", ((10.0, 10.0), (60.0, 20.0)), "S"),
            vfb.RawSpec(b"/Fm0 Do", "form_do"),
            vfb._p("line", ((20.0, 120.0), (90.0, 150.0)), "S", stroke=(1.0, 0.0, 0.0)),
        )
    )
    return page, add_form(vfb.build(vfb.Scene((page,))))


def add_form(data: bytes) -> bytes:
    """The document with page 0's ``/XObject`` resource ``/Fm0``: a form that draws one blue line."""
    doc = fitz.open(stream=data, filetype="pdf")
    form = doc.get_new_xref()
    doc.update_object(form, "<< /Type /XObject /Subtype /Form /BBox [0 0 200 200] >>")
    doc.update_stream(form, b"0 0 1 RG 5 5 m 190 190 l S\n", compress=False, new=True)
    doc.xref_set_key(doc[0].xref, "Resources/XObject", f"<< /Fm0 {form} 0 R >>")
    return doc.tobytes(garbage=0)


_SHAPES: dict[str, tuple[vfb.Point, ...]] = {
    "cusp": ((0.0, 0.0), (100.0, 100.0), (0.0, 100.0), (100.0, 0.0)),
    "loop": ((0.0, 0.0), (160.0, 160.0), (-60.0, 160.0), (100.0, 0.0)),
    "near_straight": ((0.0, 0.0), (30.0, 0.2), (60.0, -0.2), (90.0, 0.0)),
    "long5000": ((0.0, 0.0), (1500.0, 4000.0), (3500.0, -3000.0), (5000.0, 0.0)),
}
_CMS: dict[str, vfb.Matrix] = {
    "identity": vfb.IDENT,
    "scale": (2.0, 0.0, 0.0, 0.5, 5.0, 5.0),
    "rotate": (0.6, 0.8, -0.8, 0.6, 100.0, 20.0),  # a 3-4-5 rotation: exact in six decimals
    "shear": (1.0, 0.0, 0.5, 1.0, 10.0, 10.0),
}


def curve_twin_pages() -> list[tuple[str, vfb.PageSpec]]:
    """One page per (shape, cm): a cusp, a loop, a near-straight curve and a curve 5,000 pt long, each
    under the identity, a scaling, a rotating and a shearing ``cm`` (the builder's ``curve`` kind)."""
    out: list[tuple[str, vfb.PageSpec]] = []
    for shape, pts in _SHAPES.items():
        for cm_name, cm in _CMS.items():
            out.append((f"{shape}/{cm_name}", vfb.PageSpec((vfb._p("curve", pts, "S", cm),))))
    return out


# --------------------------------------------------------------------------- O-scan cells


def _prims_of(rows: Sequence[IndexRow]) -> list[tuple[tuple[object, ...], ...]]:
    return [tuple(row_primitives(r)) for r in rows if r.paint != "n" and not r.degenerate]


def _pair_paints(rows: Sequence[IndexRow]) -> list[tuple[str, str]]:
    """The paints of every two adjacent painted rows that hold identical primitives (the shape MuPDF
    merges into one ``fs`` drawing when the fill comes first): a plain structural comparison."""
    live = [r for r in rows if r.paint != "n" and not r.degenerate]
    return [(a.paint, b.paint) for a, b in zip(live, live[1:], strict=False) if a.segments == b.segments and a.cubics == b.cubics]


def truth_scan_violated(good: Sequence[IndexRow], mutant: Sequence[IndexRow]) -> bool:
    """Ground truth for a scan mutant: the ordered primitives of the painted, non-degenerate rows differ
    by more than the tolerance, or the paints of an identical-primitive neighbour pair differ (a stroke
    row before a fill row is not what the page's fill-then-stroke drawing was; a plain comparison: no
    alignment, no drawings, no oracle)."""
    if _pair_paints(good) != _pair_paints(mutant):
        return True
    a, b = _prims_of(good), _prims_of(mutant)
    if len(a) != len(b):
        return True
    for ra, rb in zip(a, b, strict=True):
        if len(ra) != len(rb):
            return True
        for pa, pb in zip(ra, rb, strict=True):
            if pa[0] != pb[0] or len(pa) != len(pb):
                return True
            if any(abs(u - w) > TOL for p, q in zip(pa[1:], pb[1:], strict=True) for u, w in zip(p, q, strict=True)):  # type: ignore[arg-type,union-attr]
                return True
    return False


def _shift_row(row: IndexRow, dx: float, dy: float, *, only_first: bool = False) -> IndexRow:
    segs = list(row.segments)
    for i, (x0, y0, x1, y1, fc) in enumerate(segs):
        if only_first and i > 0:
            break
        segs[i] = (x0 + dx, y0 + dy, x1 + dx, y1 + dy, fc)
    cubics = tuple((s, n, tuple(c + (dx if k % 2 == 0 else dy) for k, c in enumerate(co))) for s, n, co in row.cubics)
    return IndexRow(row.paint, tuple(segs), cubics)


def _noise(row: IndexRow, amount: float) -> IndexRow:
    segs = tuple((x0 + amount, y0 - amount, x1 - amount, y1 + amount, fc) for x0, y0, x1, y1, fc in row.segments)
    cubics = tuple((s, n, tuple(c + (amount if k % 2 == 0 else -amount) for k, c in enumerate(co))) for s, n, co in row.cubics)
    return IndexRow(row.paint, segs, cubics)


def _line_to_cubic(row: IndexRow) -> IndexRow:
    x0, y0, x1, y1, _fc = row.segments[0]
    p4 = ((x0, y0), (x0, y0), (x1, y1), (x1, y1))
    chords = reference_chords(p4)
    return IndexRow(row.paint, chords, ((0, len(chords), tuple(v for p in p4 for v in p)),))


def _cubic_to_line(row: IndexRow) -> IndexRow:
    co = row.cubics[0][2]
    return IndexRow(row.paint, ((co[0], co[1], co[6], co[7], False),), ())


def scan_cells(
    name: str,
    page: vfb.PageSpec,
    *,
    scene: vfb.Scene | None = None,
    data: bytes | None = None,
    extra_wrong: dict[str, list[IndexRow]] | None = None,
) -> list[Cell]:
    """Must-pass and must-kill cells of O-scan on one twin page (rows derived from the builder).

    ``scene`` supplies the topology the twin is built with, ``data`` a hand-made twin document, and
    ``extra_wrong`` named row lists to judge as well (for example rows past an inline image)."""
    if data is None:
        data = vfb.build(scene if scene is not None else vfb.Scene((page,)))
    frame = frame_of(page)
    good = rows_from_page(page)

    def cell(label: str, rows: Sequence[IndexRow]) -> Cell:
        kinds = frozenset({SCAN_ROWS}) if truth_scan_violated(good, rows) else frozenset()
        return Cell(f"scan:{name}:{label}", kinds, {"O-scan": {"before": data, "rows": list(rows), "frame": frame}})

    out = [cell("derived rows", good), cell("noise below the tolerance", [_noise(r, 4e-4) for r in good])]
    for label, wrong in (extra_wrong or {}).items():
        out.append(cell(label, wrong))
    deg = IndexRow("S", (), ())
    n = len(good)
    for pos in (0, n // 2, n):
        out.append(cell(f"degenerate row inserted at {pos}", [*good[:pos], deg, *good[pos:]]))
    out.append(
        cell(
            "chords scrambled",
            [
                IndexRow(
                    r.paint,
                    tuple((x0 + 7, y0 - 3, x1 + 9, y1 + 5, True) if fc else (x0, y0, x1, y1, fc) for x0, y0, x1, y1, fc in r.segments),
                    r.cubics,
                )
                for r in good
            ],
        )
    )
    painted = [i for i, r in enumerate(good) if r.paint != "n" and not r.degenerate]
    if not painted:
        return out
    lines = [i for i in painted if len(good[i].segments) == 1 and not good[i].cubics]
    curves = [i for i in painted if good[i].cubics]
    rects = [i for i in painted if len(good[i].segments) == 4 and not good[i].cubics]
    for i in lines[:2]:
        out.append(cell(f"line {i} start moved", [*good[:i], _shift_row(good[i], 0.05, 0.0, only_first=True), *good[i + 1 :]]))
        out.append(cell(f"line {i} replaced by a cubic", [*good[:i], _line_to_cubic(good[i]), *good[i + 1 :]]))
    for i in curves[:2]:
        out.append(cell(f"curve {i} control points moved", [*good[:i], _shift_row(good[i], 0.0, 0.05), *good[i + 1 :]]))
        out.append(cell(f"curve {i} replaced by a line", [*good[:i], _cubic_to_line(good[i]), *good[i + 1 :]]))
    for i in rects[:1]:
        r = good[i]
        segs = list(r.segments)
        x0, y0, x1, y1, fc = segs[0]
        segs[0] = (x0 + 0.05, y0 + 0.05, x1, y1, fc)  # corner 0 as a start point only
        out.append(cell(f"rect {i} corner moved", [*good[:i], IndexRow(r.paint, tuple(segs), r.cubics), *good[i + 1 :]]))
        out.append(cell(f"rect {i} replaced by a line", [*good[:i], IndexRow(r.paint, (r.segments[0],), ()), *good[i + 1 :]]))
    for i in sorted({painted[0], painted[len(painted) // 2], painted[-1]}):
        out.append(cell(f"row {i} dropped", [*good[:i], *good[i + 1 :]]))
    extra = IndexRow("S", ((1.0, 1.0, 2.5, 2.5, False),), ())
    for pos in (0, n // 2, n):
        out.append(cell(f"non-degenerate row inserted at {pos}", [*good[:pos], extra, *good[pos:]]))
    for a, b in zip(painted, painted[1:], strict=False):  # a fill row and a stroke row of one path
        ra, rb = good[a], good[b]
        if ra.segments == rb.segments and ra.cubics == rb.cubics and ra.paint == "f" and rb.paint == "S":
            out.append(cell(f"rows {a} and {b} (a fill and a stroke of one path) in stroke-then-fill order", [*good[:a], rb, ra, *good[b + 1 :]]))
            out.append(cell(f"rows {a} and {b} both fills", [*good[:b], IndexRow("f", rb.segments, rb.cubics), *good[b + 1 :]]))
            out.append(cell(f"rows {a} and {b} both strokes", [*good[:a], IndexRow("S", ra.segments, ra.cubics), *good[a + 1 :]]))
    for a, b in zip(painted[:4], painted[1:5], strict=False):
        sw = list(good)
        sw[a], sw[b] = sw[b], sw[a]
        out.append(cell(f"rows {a} and {b} swapped", sw))
    return out


def domain_cells() -> list[Cell]:
    """The comparable-list domain (G3): rows stop at the first ``BI`` and never hold a form's paths."""
    page = inline_image_page()
    cells = scan_cells(
        "inline_image",
        page,
        extra_wrong={"rows past the inline image": rows_from_page(page, stop_at_inline_image=False)},
    )
    fpage, fdata = form_page_data()
    form_row = IndexRow("S", ((5.0, 5.0, 190.0, 190.0, False),), ())
    cells += scan_cells("form_do", fpage, data=fdata, extra_wrong={"a row for the form's path": [form_row, *rows_from_page(fpage)]})
    return cells


# --------------------------------------------------------------------------- O-flat cells


def _bern(p4: np.ndarray, t: np.ndarray) -> np.ndarray:
    u = 1.0 - t
    w = np.stack([u**3, 3 * u * u * t, 3 * u * t * t, t**3], axis=1)
    return w @ p4


def _dbern(p4: np.ndarray, t: np.ndarray) -> np.ndarray:
    u = 1.0 - t
    d = 3.0 * (p4[1:] - p4[:-1])
    w = np.stack([u * u, 2 * u * t, t * t], axis=1)
    return w @ d


def truth_flat_violated(row: IndexRow, eps: float = vof.EPS) -> bool:
    """Ground truth for a chord list: a gap, a wrong end, a vertex off the curve (multi-start Newton on
    the foot point, Bernstein basis) or a dense sample (8,001 points) farther than epsilon from the chords."""
    start, count, co = row.cubics[0]
    p4 = np.array(co, dtype=float).reshape(4, 2)
    run = row.segments[start : start + count]
    if not run:
        return True
    a = np.array([[s[0], s[1]] for s in run])
    b = np.array([[s[2], s[3]] for s in run])
    tol = vof.vertex_tolerance(p4)  # the oracle's own tolerance function: one definition of "on the curve"
    if len(run) > 1 and (np.linalg.norm(b[:-1] - a[1:], axis=1) > tol).any():
        return True
    if np.linalg.norm(a[0] - p4[0]) > tol or np.linalg.norm(b[-1] - p4[3]) > tol:
        return True
    grid = np.linspace(0.0, 1.0, 8001)
    curve = _bern(p4, grid)
    verts = np.vstack([a, b[-1:]])
    k = 8  # multi-start: the eight best local minima of the coarse distance (a loop has two branches)
    starts = np.empty((len(verts), k))
    for s in range(0, len(verts), 64):
        d = np.linalg.norm(curve[None, :, :] - verts[s : s + 64, None, :], axis=2)
        left = np.concatenate([np.full((len(d), 1), np.inf), d[:, :-1]], axis=1)
        right = np.concatenate([d[:, 1:], np.full((len(d), 1), np.inf)], axis=1)
        pick = np.argpartition(np.where((d <= left) & (d <= right), d, np.inf), k - 1, axis=1)[:, :k]
        starts[s : s + 64] = grid[pick]
    vv = np.repeat(verts, k, axis=0)
    t = starts.ravel()

    def foot(tt: np.ndarray) -> np.ndarray:  # f(t) = (B(t) - v) . B'(t), zero at a foot point
        return ((_bern(p4, tt) - vv) * _dbern(p4, tt)).sum(axis=1)

    for _ in range(40):  # vectorised Newton with a numerical slope
        h = 1e-7
        f0 = foot(t)
        slope = (foot(np.clip(t + h, 0.0, 1.0)) - f0) / h
        step = np.where(np.abs(slope) > 1e-12, f0 / np.where(slope == 0, 1.0, slope), 0.0)
        t = np.clip(t - step, 0.0, 1.0)
    near = np.linalg.norm(_bern(p4, t) - vv, axis=1).reshape(len(verts), k).min(axis=1)
    if (near > tol).any():
        return True
    dev = np.full(len(grid), np.inf)
    for i in range(len(run)):
        ab = b[i] - a[i]
        ln = float(ab @ ab)
        u = np.clip(((curve - a[i]) @ ab) / ln, 0.0, 1.0) if ln > 0 else np.zeros(len(grid))
        dev = np.minimum(dev, np.linalg.norm(curve - (a[i] + u[:, None] * ab), axis=1))
    return bool(dev.max() > eps * (1 + 1e-9))


def flat_cells(name: str, rows: Sequence[IndexRow]) -> list[Cell]:
    """Must-pass and must-kill cells of O-flat for the first cubic row of a twin."""
    row = rows[0]
    _start, _count, co = row.cubics[0]
    p4 = tuple((co[2 * k], co[2 * k + 1]) for k in range(4))

    def mk(label: str, segs: Sequence[tuple[float, ...]]) -> Cell:
        new = IndexRow(row.paint, tuple(segs), ((0, len(segs), co),))  # type: ignore[arg-type]
        kinds = frozenset({CHORDS}) if truth_flat_violated(new) else frozenset()
        return Cell(f"flat:{name}:{label}", kinds, {"O-flat": {"rows": [new]}})

    seg = list(row.segments)
    out = [
        mk("reference chords", seg),
        mk("twice the chords plus one", chords_with_count(p4, 2 * len(seg) + 1)),
        mk("one chord more than the bound", chords_with_count(p4, len(seg) + 1)),
    ]
    mid = len(seg) // 2
    if mid >= 1:
        v = seg[mid - 1]
        nx, ny = -(v[3] - v[1]), v[2] - v[0]
        norm = math.hypot(nx, ny) or 1.0

        def shifted(amount: float) -> list[tuple[float, ...]]:
            dx, dy = amount * nx / norm, amount * ny / norm
            off = list(seg)
            a0, b0, a1, b1, fc = off[mid - 1]
            off[mid - 1] = (a0, b0, a1 + dx, b1 + dy, fc)
            c0, d0, c1, d1, fc2 = off[mid]
            off[mid] = (c0 + dx, d0 + dy, c1, d1, fc2)
            return off

        out.append(mk("a vertex off the curve", shifted(0.05)))
        # the tolerance is one absolute function (1e-6): the cells straddle it at every page scale
        out.append(mk("a vertex 3e-6 off the curve", shifted(3e-6)))
        out.append(mk("a vertex 1e-5 off the curve", shifted(1e-5)))
        out.append(mk("a vertex 5e-7 off the curve", shifted(5e-7)))
    out.append(mk("coarse chord list", chords_with_count(p4, max(1, len(seg) // 4))))
    out.append(mk("coarse chord list, one chord", chords_with_count(p4, 1)))
    if len(seg) > 2:
        out.append(mk("a segment missing", seg[:mid] + seg[mid + 1 :]))
    if len(seg) > 1:
        out.append(mk("the last segment missing", seg[:-1]))
    return out
