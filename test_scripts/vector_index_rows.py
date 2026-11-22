"""Index rows as the oracles of card B1 see them, derived from the fixture builder's own records.

The product's index (design plan section 4.1) holds a paths table, a segments table (``x0 y0 x1 y1``,
``from_cubic``) and a cubics table (eight control coordinates plus the run of chord segments).  An
:class:`IndexRow` is one path's slice of those tables.  Card B2 will produce them from a scanner;
until then the calibration derives them here from the scene's abstract paths and the builder's own
geometry (never from MuPDF and never from a scanner), so an oracle never judges its own input.

Coordinates of a row are in unrotated user space (y up); :func:`frame_of` is the affine map from that
space to the frame of ``page.get_cdrawings()`` (y down, unrotated, UserUnit applied, CropBox origin).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from test_scripts import vector_fixture_builder as vfb

Segment = tuple[float, float, float, float, bool]  # x0 y0 x1 y1 from_cubic
Cubic = tuple[int, int, tuple[float, ...]]  # seg_start, seg_count (within the row), 8 coordinates
Point = tuple[float, float]


@dataclass(frozen=True)
class IndexRow:
    paint: str  # "S" | "f" | "B" | "n" (the paint class of the path)
    segments: tuple[Segment, ...]
    cubics: tuple[Cubic, ...] = ()

    @property
    def degenerate(self) -> bool:
        """The design's DEGENERATE flag: the path has no segment."""
        return not self.segments


def row_primitives(row: IndexRow) -> list[tuple[object, ...]]:
    """The row's ordered primitives: ``("l", p0, p1)`` and ``("c", p0, p1, p2, p3)``.

    A cubic's chord run is replaced by the cubic itself; a ``from_cubic`` segment outside every cubic
    run, or a run outside the row, is a malformed row (``ValueError``).
    """
    starts: dict[int, Cubic] = {}
    for cub in row.cubics:
        s, n, coords = cub
        if n < 1 or s < 0 or s + n > len(row.segments) or len(coords) != 8 or s in starts:
            raise ValueError(f"cubic run ({s}, {n}) does not fit a row of {len(row.segments)} segments")
        starts[s] = cub
    out: list[tuple[object, ...]] = []
    i = 0
    while i < len(row.segments):
        if i in starts:
            _s, n, c = starts[i]
            out.append(("c", (c[0], c[1]), (c[2], c[3]), (c[4], c[5]), (c[6], c[7])))
            i += n
            continue
        x0, y0, x1, y1, from_cubic = row.segments[i]
        if from_cubic:
            raise ValueError(f"segment {i} is flagged from_cubic but belongs to no cubic run")
        out.append(("l", (x0, y0), (x1, y1)))
        i += 1
    return out


def frame_of(page: vfb.PageSpec) -> vfb.Matrix:
    """Row space (user space, y up) to the frame of ``get_cdrawings`` (unrotated, y down)."""
    cx0, _cy0, _cx1, cy1 = page.cropbox if page.cropbox is not None else (0.0, 0.0, float(vfb._PAGE_W), float(vfb._PAGE_H))
    uu = page.userunit
    return (uu, 0.0, 0.0, -uu, -cx0 * uu, cy1 * uu)


def apply_frame(frame: vfb.Matrix, p: Point) -> Point:
    return vfb._apply(frame, p)


def _bernstein(p4: Sequence[Point], t: float) -> Point:
    u = 1.0 - t
    w = (u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t)
    return (sum(w[k] * p4[k][0] for k in range(4)), sum(w[k] * p4[k][1] for k in range(4)))


def chords_with_count(p4: Sequence[Point], n: int) -> tuple[Segment, ...]:
    """``n`` equal-parameter chords of the cubic, vertices evaluated on the curve."""
    pts = [p4[0]] + [_bernstein(p4, i / n) for i in range(1, n)] + [p4[3]]
    return tuple((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], True) for i in range(n))


def reference_chord_count(p4: Sequence[Point], eps: float = 0.01) -> int:
    """Design plan 4.1: ``n = ceil(sqrt(0.75 * M / eps))``, ``M`` the larger second difference."""
    d1 = math.hypot(p4[0][0] - 2 * p4[1][0] + p4[2][0], p4[0][1] - 2 * p4[1][1] + p4[2][1])
    d2 = math.hypot(p4[1][0] - 2 * p4[2][0] + p4[3][0], p4[1][1] - 2 * p4[2][1] + p4[3][1])
    return max(1, math.ceil(math.sqrt(0.75 * max(d1, d2) / eps)))


def reference_chords(p4: Sequence[Point], eps: float = 0.01) -> tuple[Segment, ...]:
    return chords_with_count(p4, reference_chord_count(p4, eps))


INLINE_IMAGE_LABEL = "inline_image"


def rows_from_page(page: vfb.PageSpec, *, eps: float = 0.01, stop_at_inline_image: bool = True) -> list[IndexRow]:
    """One row per path of the page in stream order (clip paths, paint ``n``, included).

    The index stops at the first inline image (``BI``, design plan D14/H13), so rows end at the first
    ``RawSpec`` labelled ``inline_image`` unless ``stop_at_inline_image`` is False (a deliberately
    wrong row list)."""
    running = vfb.IDENT
    rows: list[IndexRow] = []
    for it in page.items:
        if stop_at_inline_image and isinstance(it, vfb.RawSpec) and it.label == INLINE_IMAGE_LABEL:
            break
        if not isinstance(it, vfb.PathSpec):
            continue
        if it.state.shape == "cumulative":
            running = vfb._concat(it.ctm, running)
            page_m = running
        else:
            page_m = vfb._concat(it.ctm, running)
        segs: list[Segment] = []
        cubics: list[Cubic] = []
        for prim in vfb._prims(it, page_m):
            kind, pts = prim[0], prim[1:]
            if kind == "l":
                segs.append((*pts[0], *pts[1], False))  # type: ignore[misc]
            elif kind == "re":
                for k in range(4):
                    a, b = pts[k], pts[(k + 1) % 4]
                    segs.append((*a, *b, False))  # type: ignore[misc]
            else:
                chords = reference_chords(pts, eps)  # type: ignore[arg-type]
                cubics.append((len(segs), len(chords), tuple(v for p in pts for v in p)))  # type: ignore[attr-defined]
                segs.extend(chords)
        rows.append(IndexRow(it.paint, tuple(segs), tuple(cubics)))
    return rows


def selected_rows(page: vfb.PageSpec, selected_items: Sequence[int]) -> frozenset[int]:
    """Row indices of the given item indices (rows count the page's paths only, in order)."""
    row_of: dict[int, int] = {}
    n = 0
    for idx, it in enumerate(page.items):
        if isinstance(it, vfb.PathSpec):
            row_of[idx] = n
            n += 1
    return frozenset(row_of[i] for i in selected_items if i in row_of)
