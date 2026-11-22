"""O-scan (design plan section 9, card B1 completion item 1).

For every drawing of the comparable list (``page.get_cdrawings()``) there is an index row whose
primitives match item by item, in order, within the one tolerance function of D23 (``vector_matching``,
1e-3 pt at page scale): a line's two points, a curve's four control points, a rectangle's corners.
Chords flagged ``from_cubic`` are never compared.  Rows without a drawing must all be DEGENERATE (no
segment).  The oracle takes the product's rows as an argument and the page frame (the affine map from
row space to the frame of ``get_cdrawings``); it never imports a scanner.

Decisions of this card, reported to the owner (the design leaves them open):

* A drawing MuPDF merged from two paints (``fs``) pairs with TWO consecutive rows of identical
  primitives (a fill, then a stroke: MuPDF does not merge a stroke followed by a fill), or with one
  row whose paint is ``B``.
* A row whose paint is ``n`` (a clip, ``W n``, or a plain ``n``) has no drawing by construction and is
  skipped like a DEGENERATE row, so such a path with segments is not a violation.  A phantom ``n`` row
  (segments, no path behind it) is NOT rejected: MuPDF reports no drawing for a plain ``n`` path and a
  row carries no ``W`` flag, so a clip item of ``get_cdrawings(extended=True)`` cannot be paired with
  the rows soundly (reported to the owner, card B1 review).
* A DEGENERATE row may pair with a zero-extent drawing (S0-P2); a look-ahead keeps a real zero-length
  line (one segment) with its own row.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field

import fitz

from model.text_commit.pdf_lexer import TokenKind, lex_content_stream
from test_scripts import vector_matching as vm
from test_scripts.vector_index_rows import IndexRow, Point, apply_frame, row_primitives

_FILL_PAINTS = frozenset({"f", "F", "f*"})
_STROKE_PAINTS = frozenset({"S", "s"})
_BOTH_PAINTS = frozenset({"B", "B*", "b", "b*"})


@dataclass
class Alignment:
    pairs: list[tuple[int, ...]] = field(default_factory=list)  # per drawing: the row indices it came from
    violations: list[str] = field(default_factory=list)


def _xy(p: object) -> Point:
    return (float(p[0]), float(p[1]))  # type: ignore[index]


def _quad_points(q: object) -> list[Point]:
    if hasattr(q, "ul"):
        return [_xy(q.ul), _xy(q.ur), _xy(q.ll), _xy(q.lr)]  # type: ignore[attr-defined]
    return [_xy(p) for p in q]  # type: ignore[attr-defined]


def _pt_match(a: Point, b: Point) -> bool:
    return vm.coordinates_match(a[0], b[0]) and vm.coordinates_match(a[1], b[1])


def _same_point_set(a: Sequence[Point], b: Sequence[Point]) -> bool:
    free = list(b)
    for p in a:
        hit = next((i for i, q in enumerate(free) if _pt_match(p, q)), None)
        if hit is None:
            return False
        free.pop(hit)
    return not free


def _item_points(item: Sequence[object]) -> list[Point]:
    """Corners in CYCLE order (each corner adjacent to the next, the last to the first)."""
    kind = item[0]
    if kind in ("l", "c"):
        return [_xy(p) for p in item[1:]]
    if kind == "re":
        r = item[1]
        x0, y0, x1, y1 = (float(v) for v in (r.x0, r.y0, r.x1, r.y1)) if hasattr(r, "x0") else (float(v) for v in r)  # type: ignore[attr-defined]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if kind == "qu":
        ul, ur, ll, lr = _quad_points(item[1])
        return [ul, ur, lr, ll]
    return []


def rect_edges_match(corners: Sequence[Point], lines: Sequence[tuple[Point, Point]]) -> bool:
    """A rectangle item's four edges (corners in cycle order) against a row's four line primitives.

    The row must be a closed chain (each line ends where the next starts, the last where the first
    starts) and its four undirected edges must be the rectangle's four edges, each used once: four
    edges replaced by diagonals, swapped corner pairs or a broken chain fail."""
    if len(corners) != 4 or len(lines) != 4:
        return False
    # Identify every line endpoint with a corner INDEX (within the one tolerance), so the closure test
    # compares indices instead of stacking two tolerances; coincident corners (a zero-extent side)
    # give several candidates and every assignment is tried.
    cands = [[[i for i, c in enumerate(corners) if _pt_match(p, c)] for p in ln] for ln in lines]
    if any(not ends[0] or not ends[1] for ends in cands):
        return False
    want = sorted(tuple(sorted((k, (k + 1) % 4))) for k in range(4))
    for pick in itertools.product(*(itertools.product(*ends) for ends in cands)):
        if any(pick[k][1] != pick[(k + 1) % 4][0] for k in range(4)):
            continue
        if sorted(tuple(sorted(e)) for e in pick) == want:
            return True
    return False


def _zero_extent(drawing: dict) -> bool:
    pts = [p for it in drawing["items"] for p in _item_points(it)]
    if not pts:
        return True
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(xs) - min(xs) <= vm.BASE_TOLERANCE and max(ys) - min(ys) <= vm.BASE_TOLERANCE


def _row_mismatch(row: IndexRow, drawing: dict, frame: Sequence[float]) -> str | None:
    """``None`` when the row's primitives match the drawing's items one by one, else the reason."""
    try:
        prims = row_primitives(row)
    except ValueError as exc:
        return f"malformed row: {exc}"
    mapped = [(p[0], *[apply_frame(frame, q) for q in p[1:]]) for p in prims]  # type: ignore[arg-type]
    j = 0
    for k, item in enumerate(drawing["items"]):
        kind = item[0]
        if kind in ("l", "c"):
            if j >= len(mapped) or mapped[j][0] != kind:
                return f"item {k} is a {kind!r} but the row holds {mapped[j][0]!r}" if j < len(mapped) else f"item {k} has no primitive left in the row"
            want = [_xy(p) for p in item[1:]]
            if len(want) != len(mapped[j]) - 1 or not all(_pt_match(a, b) for a, b in zip(want, mapped[j][1:], strict=True)):  # type: ignore[arg-type]
                return f"item {k} ({kind}) differs from the row's primitive by more than the tolerance"
            j += 1
        elif kind in ("re", "qu"):
            quad = mapped[j : j + 4]
            if len(quad) < 4 or any(m[0] != "l" for m in quad):
                return f"item {k} is a rectangle but the row does not hold four lines at that place"
            want = _item_points(item)
            if not rect_edges_match(want, [(m[1], m[2]) for m in quad]):  # type: ignore[arg-type]
                return f"item {k} (rectangle) edges differ from the row's four lines"
            j += 4
        else:
            return f"item {k} has the unknown kind {kind!r}"
    if j != len(mapped):
        return f"the row holds {len(mapped) - j} more primitive(s) than the drawing"
    return None


def scan_alignment(drawings: Sequence[dict], rows: Sequence[IndexRow], frame: Sequence[float]) -> Alignment:
    """Walk drawings and rows together.  ``pairs[i]`` is the tuple of row indices drawing ``i`` came from;
    a violation stops the walk (the alignment is lost after it)."""
    al = Alignment()
    ri = 0
    n = len(rows)

    def skippable(r: IndexRow) -> bool:
        return r.degenerate or r.paint == "n"

    for di, d in enumerate(drawings):
        while True:
            if ri >= n:
                al.violations.append(f"O-scan: drawing {di} has no row")
                return al
            row = rows[ri]
            if row.paint == "n":
                ri += 1
                continue
            if row.degenerate:
                ahead = next((k for k in range(ri + 1, n) if not skippable(rows[k])), None)
                if ahead is not None and _row_mismatch(rows[ahead], d, frame) is None:
                    ri += 1  # the drawing belongs to a later row: this DEGENERATE row has none
                    continue
                if _zero_extent(d):
                    al.pairs.append((ri,))
                    ri += 1
                    break
                ri += 1
                continue
            why = _row_mismatch(row, d, frame)
            if why is not None:
                al.violations.append(f"O-scan: drawing {di} does not match row {ri}: {why}")
                return al
            want = "fs" if row.paint in _BOTH_PAINTS else "f" if row.paint in _FILL_PAINTS else "s" if row.paint in _STROKE_PAINTS else None
            if want is not None and d.get("type") not in (want, "fs"):  # a merged 'fs' is judged below
                al.violations.append(f"O-scan: drawing {di} is a {d.get('type')!r} drawing but row {ri} paints {row.paint!r}")
                return al
            if d.get("type") == "fs" and row.paint not in _BOTH_PAINTS:
                nxt = next((k for k in range(ri + 1, n) if not skippable(rows[k])), n)  # rows between have no drawing
                # MuPDF merges a fill FOLLOWED BY a stroke of one path; a stroke then a fill stays two drawings
                if nxt >= n or _row_mismatch(rows[nxt], d, frame) is not None or not (
                    row.paint in _FILL_PAINTS and rows[nxt].paint in _STROKE_PAINTS
                ):
                    al.violations.append(f"O-scan: drawing {di} is a merged fill and stroke but rows {ri} and {nxt} are not a fill and a stroke of it")
                    return al
                al.pairs.append((ri, nxt))
                ri = nxt + 1
            else:
                al.pairs.append((ri,))
                ri += 1
            break
    for k in range(ri, n):
        if not skippable(rows[k]):
            al.violations.append(f"O-scan: row {k} has no drawing and is not DEGENERATE")
            break
    return al


def comparable_drawings(data: bytes, page: int = 0) -> list[dict]:
    """The comparable list (design plan section 9, Domain G3): ``get_cdrawings`` of a temporary copy of the
    page whose content is cut at the first ``BI`` token found by the reference lexer (exact up to there),
    closed with the ``Q``s needed to balance, and whose ``/XObject`` resources are each an empty form (a
    missing one would make every ``Do`` a syntax error, and MuPDF gives up a page after 100).  Everything
    else MuPDF draws on the real page (forms, content after the first ``BI``) is the unindexed remainder.
    Pattern and Type 3 font stand-ins are NOT made here (they wait for the P2 measurement)."""
    doc = fitz.open(stream=data, filetype="pdf")
    pg = doc[page]
    content = b"\n".join(doc.xref_stream(x) or b"" for x in pg.get_contents())
    cut, depth = len(content), 0
    do_names: list[str] = []  # every name a ``Do`` before the cut invokes
    last_name = ""
    for t in lex_content_stream(content):
        if t.kind is TokenKind.NAME:
            last_name = content[t.start : t.end].decode("latin-1")
        if t.kind is TokenKind.OPERATOR:
            word = content[t.start : t.end]
            if word == b"BI":
                cut = t.start
                break
            if word == b"Do" and last_name and last_name not in do_names:
                do_names.append(last_name)
            depth += 1 if word == b"q" else -1 if word == b"Q" else 0
    body = content[:cut] + b"\n" + b"Q\n" * max(0, depth)
    new = doc.get_new_xref()
    doc.update_object(new, "<< >>")
    doc.update_stream(new, body, compress=False, new=True)
    doc.xref_set_key(pg.xref, "Contents", f"{new} 0 R")
    # Every XObject is replaced by an EMPTY form under the same name: a missing resource would make each
    # ``Do`` a MuPDF syntax error, and after 100 of them MuPDF ignores the rest of the page.
    stand_in = doc.get_new_xref()
    doc.update_object(stand_in, "<< /Type /XObject /Subtype /Form /BBox [0 0 1 1] >>")
    doc.update_stream(stand_in, b"", compress=False, new=True)
    xobjects = "<<" + " ".join(f"{n} {stand_in} 0 R" for n in do_names) + ">>"
    kind, value = doc.xref_get_key(pg.xref, "Resources")
    if kind == "xref":
        doc.xref_set_key(int(value.split()[0]), "XObject", xobjects)
    else:
        doc.xref_set_key(pg.xref, "Resources/XObject", xobjects)
    return fitz.open(stream=doc.tobytes(garbage=0), filetype="pdf")[page].get_cdrawings()


def o_scan(before: bytes, rows: Sequence[IndexRow], *, frame: Sequence[float], page: int = 0) -> list[str]:
    """Violations (empty = accept).  ``before`` is the twin; the drawings compared are its comparable list
    (:func:`comparable_drawings`), so rows stop at the first inline image like the index does."""
    return scan_alignment(comparable_drawings(before, page), rows, frame).violations


o_scan.DOMAIN = frozenset({"SCAN_ROWS"})  # type: ignore[attr-defined]
