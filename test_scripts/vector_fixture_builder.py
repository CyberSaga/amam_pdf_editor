"""Twin builder for CAD vector editing (card B1; design plan section 9, handoff H6).

A *scene* is an abstract list of paths per page plus a reference topology.  :func:`build` writes
the PDF by hand (explicit object numbers, so topologies can be controlled).  For an operation the
builder also derives the *expected* document and a :class:`Facts` mapping, and for every mutant of
the fixed list the same pair for the wrong scene (rule A).  Facts are computed from the abstract
scene and from byte offsets the builder recorded while emitting; the builder never reads its own
bytes back (a test pins that this module does not import a PDF reader).

Only ``delete`` exists here; move operations and move mutants are added by card C1.

Conventions (decisions of this card, reported to the owner):

* Page space is user space after the path's CTM, y up, unrotated.  Stroke widths are nominal.
* ``Op.fate`` is ``"commit"`` or ``"rollback"``; the rollback mutants are defined on a rollback
  scenario (:func:`scenario_of`).
* ``Facts`` is a dict of the fixed kinds plus a ``context`` attribute with what the oracles need as
  keyword arguments (ranges, envelopes, write set, symbolic xref names).
"""

from __future__ import annotations

import copy
import functools
import hashlib
import math
import zlib
from dataclasses import dataclass, field, replace

import numpy as np

Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]
IDENT: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

PATHS = "PATHS"
OTHER_PAGES = "OTHER_PAGES"
OUTSIDE_BYTES = "OUTSIDE_BYTES"
OBJECTS = "OBJECTS"
PIXELS_OUTSIDE = "PIXELS_OUTSIDE"
DICT = "DICT"
FACT_KINDS = (PATHS, OTHER_PAGES, OUTSIDE_BYTES, OBJECTS, PIXELS_OUTSIDE, DICT)

MUTANT_NAMES = (
    "neighbour deleted too",
    "one selected path kept",
    "block removed where a D17 rule fails",
    "range shifted by one token",
    "write in place on a shared stream",
    "copy skipped with a shared indirect array",
    "/Rotate changed on the edited page",
    "a trailer key changed",
    "a foreign stream changed",
    "restore skipped after a failure",
    "/Contents left repointed after a rollback",
    "extra dictionary key",
    "decoded bytes restored under another filter",
)
_ROLLBACK_MUTANTS = frozenset(
    {
        "restore skipped after a failure",
        "/Contents left repointed after a rollback",
        "decoded bytes restored under another filter",
    }
)

_PAGE_W = 200
_PAGE_H = 200
_WS = b"\x00\t\n\x0c\r "
_COMMIT_DICT_EXCLUDED = frozenset({"Length", "Filter", "DecodeParms", "DL"})


# --------------------------------------------------------------------------- scene model


@dataclass(frozen=True)
class PathState:
    stroke: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fill: tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 1.0
    dash: tuple[float, ...] = ()
    shape: str = "block"  # "block" (q ... Q) or "cumulative" (bare; its cm accumulates)
    block: int | None = None  # paths sharing an id share one q ... Q
    clip: bool = False  # the path carries W n (paint must be "n")
    oc: bool = False  # inside /OC marked content
    gs: bool = False  # a gs runs in the path's state


@dataclass(frozen=True)
class PathSpec:
    kind: str  # "line" | "poly" | "rect" | "curve"
    points: tuple[Point, ...]
    paint: str = "S"  # "S" | "f" | "B" | "n"
    ctm: Matrix = IDENT
    state: PathState = field(default_factory=PathState)


@dataclass(frozen=True)
class RawSpec:
    """Bytes copied into the stream verbatim; draws nothing the facts know about."""

    data: bytes
    label: str = "raw"


@dataclass(frozen=True)
class PageSpec:
    items: tuple[PathSpec | RawSpec, ...] = ()
    rotate: int = 0
    cropbox: tuple[float, float, float, float] | None = None
    userunit: float = 1.0
    split_at: int | None = None  # item index where the second /Contents stream starts


@dataclass(frozen=True)
class Topology:
    second_page_shares: bool = False
    shared_array: bool = False
    form: bool = False
    pattern: bool = False
    ap: bool = False
    orphan: bool = False
    substring_xrefs: bool = False
    indirect_length: bool = False


TOPOLOGY_FLAGS = frozenset(
    {
        "exclusive",
        "two_streams",
        "second_page_shares",
        "shared_array",
        "form",
        "pattern",
        "ap",
        "orphan",
        "substring_xrefs",
        "indirect_length",
    }
)


@dataclass(frozen=True)
class Scene:
    pages: tuple[PageSpec, ...]
    topology: Topology = field(default_factory=Topology)


@dataclass(frozen=True)
class Op:
    kind: str
    page: int
    selected: tuple[int, ...]
    fate: str = "commit"  # "commit" | "rollback"


class Facts(dict):  # type: ignore[type-arg]
    """The fixed fact kinds; ``context`` carries oracle keyword arguments (not facts)."""

    context: dict[str, object]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.context = {}


def facts_diff(a: Facts, b: Facts, kinds: tuple[str, ...] | frozenset[str]) -> list[str]:
    """Kinds (in canonical order) among ``kinds`` on which the two fact sets differ."""
    return [k for k in FACT_KINDS if k in kinds and a.get(k) != b.get(k)]


def is_editable(item: object) -> bool:
    if not isinstance(item, PathSpec):
        return False
    st = item.state
    if item.paint == "n" or st.clip or st.oc:
        return False
    a, b, c, d = item.ctm[:4]
    return abs(a * d - b * c) > 1e-12


def drawing_count(page: PageSpec) -> int:
    return sum(1 for it in page.items if isinstance(it, PathSpec) and it.paint != "n")


# --------------------------------------------------------------------------- geometry (abstract)


def _concat(first: Matrix, then: Matrix) -> Matrix:
    a, b, c, d, e, f = first
    a2, b2, c2, d2, e2, f2 = then
    return (
        a * a2 + b * c2,
        a * b2 + b * d2,
        c * a2 + d * c2,
        c * b2 + d * d2,
        e * a2 + f * c2 + e2,
        e * b2 + f * d2 + f2,
    )


def _apply(m: Matrix, p: Point) -> Point:
    return (p[0] * m[0] + p[1] * m[2] + m[4], p[0] * m[1] + p[1] * m[3] + m[5])


def _r(v: float) -> float:
    out = round(v, 6)
    return 0.0 if out == 0 else out


def _pt(m: Matrix, p: Point) -> tuple[float, float]:
    x, y = _apply(m, p)
    return (_r(x), _r(y))


def _prims(spec: PathSpec, m: Matrix) -> tuple[tuple[object, ...], ...]:
    p = spec.points
    if spec.kind == "line" or spec.kind == "poly":
        return tuple(("l", _pt(m, p[i]), _pt(m, p[i + 1])) for i in range(len(p) - 1))
    if spec.kind == "rect":
        (x0, y0), (x1, y1) = p[0], p[1]
        corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        return (("re", *(_pt(m, c) for c in corners)),)
    if spec.kind == "curve":
        return (("c", *(_pt(m, q) for q in p[:4])),)
    raise ValueError(f"unknown path kind {spec.kind!r}")


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def _records(
    items: tuple[PathSpec | RawSpec, ...],
    removed: frozenset[int] = frozenset(),
    colour_hit: dict[int, float] | None = None,
) -> list[tuple[int, tuple[object, ...]]]:
    """``(item index, record)`` of every drawn path not in ``removed``.

    The running CTM includes removed items: the cm of a deleted cumulative path stays (D7).
    ``colour_hit`` maps an item index to a replacement for the first channel of its first colour
    operator (the abstract damage of the shifted-range mutant).
    """
    running = IDENT
    out: list[tuple[int, tuple[object, ...]]] = []
    for idx, it in enumerate(items):
        if not isinstance(it, PathSpec):
            continue
        if it.state.shape == "cumulative":
            running = _concat(it.ctm, running)
            page_m = running
        else:
            page_m = _concat(it.ctm, running)
        if it.paint == "n" or idx in removed:
            continue
        stroke = it.state.stroke if it.paint in ("S", "B") else None
        fill = it.state.fill if it.paint in ("f", "B") else None
        if colour_hit and idx in colour_hit:
            if stroke is not None:
                stroke = (colour_hit[idx], stroke[1], stroke[2])
            elif fill is not None:
                fill = (colour_hit[idx], fill[1], fill[2])
        width = it.state.width if stroke is not None else None
        dashes = it.state.dash if stroke is not None else ()
        out.append((idx, (it.paint, _prims(it, page_m), stroke, fill, width, dashes)))
    return out


def _record_points(rec: tuple[object, ...]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for prim in rec[1]:  # type: ignore[union-attr]
        pts.extend(prim[1:])  # type: ignore[index]
    return pts


def _width_scales(items: tuple[PathSpec | RawSpec, ...]) -> list[float]:
    """Per drawn path (``_records`` order): the linear scale of its page CTM.  The plan grows the region
    by half the *reported* width, and a reported width is the nominal one in page space."""
    running = IDENT
    out: list[float] = []
    for it in items:
        if not isinstance(it, PathSpec):
            continue
        if it.state.shape == "cumulative":
            running = _concat(it.ctm, running)
            m = running
        else:
            m = _concat(it.ctm, running)
        if it.paint != "n":
            out.append(math.sqrt(abs(m[0] * m[3] - m[1] * m[2])))
    return out


def _grown_bbox(
    rec: tuple[object, ...], scale: float = 1.0, userunit: float = 1.0
) -> tuple[float, float, float, float]:
    """The record's bounding box in user space (y up), grown by half the reported width times the miter
    limit (10) plus 0.5 pt (= 1 px at 2x): the plan's changed-region growth.  MuPDF reports the width
    scaled by /UserUnit and the raster is in points, so the growth is ``userunit`` times the width plus
    0.5 pt, expressed in user units here (``_to_raster`` scales the box by /UserUnit)."""
    pts = _record_points(rec)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    width = (rec[4] or 0.0) * scale  # type: ignore[operator]
    g = (width * userunit / 2.0 * 10.0 + 0.5) / userunit
    return (min(xs) - g, min(ys) - g, max(xs) + g, max(ys) + g)


def _to_raster(page: PageSpec, x: float, y: float) -> tuple[float, float]:
    """A user-space point in the rotated, y-down page frame (points; the raster is 2x of it)."""
    cx0, cy0, cx1, cy1 = page.cropbox if page.cropbox is not None else (0.0, 0.0, float(_PAGE_W), float(_PAGE_H))
    uu = page.userunit
    w, h = (cx1 - cx0) * uu, (cy1 - cy0) * uu
    ux, uy = (x - cx0) * uu, (cy1 - y) * uu
    rot = page.rotate % 360
    if rot == 90:
        return (h - uy, ux)
    if rot == 180:
        return (w - ux, h - uy)
    if rot == 270:
        return (uy, w - ux)
    return (ux, uy)


def region_rects(page: PageSpec, selected_paths: tuple[int, ...]) -> list[tuple[float, float, float, float]]:
    """The changed region of a delete, derived from the builder's own records (never from a reader):
    for each drawing that holds a half of a selected path (``selected_paths`` are painted-path ordinals,
    see ``path_ordinals``), the grown bounding box of the drawing's paths (a merged fill and stroke is one
    drawing, so both its paths count), in raster points."""
    recs = [r for _i, r in _records(page.items)]
    scales = _width_scales(page.items)
    halves = _halves_by_path(page)
    touched = {di for o in selected_paths for di, _k in halves[o]}
    out: list[tuple[float, float, float, float]] = []
    for di in sorted(touched):
        boxes = [_grown_bbox(recs[o], scales[o], page.userunit) for o, hs in enumerate(halves) if any(d == di for d, _k in hs)]
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        a, b = _to_raster(page, x0, y0), _to_raster(page, x1, y1)
        out.append((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
    return out


def region_mask(shape: tuple[int, ...], rects: list[tuple[float, float, float, float]]) -> np.ndarray:
    """True where a 2x raster sample lies outside every rectangle; each is padded by one sample."""
    mask = np.ones(shape[:2], dtype=bool)
    h, w = mask.shape
    for x0, y0, x1, y1 in rects:
        r0, r1 = min(h, max(0, math.floor(y0 * 2) - 1)), min(h, max(0, math.floor(y1 * 2) + 2))
        c0, c1 = min(w, max(0, math.floor(x0 * 2) - 1)), min(w, max(0, math.floor(x1 * 2) + 2))
        mask[r0:r1, c0:c1] = False
    return mask


def _render2x(doc: object, i: int) -> np.ndarray:
    pix = doc[i].get_pixmap(matrix=_fitz().Matrix(2, 2), alpha=False, annots=False)  # type: ignore[index]
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


def _fitz() -> object:
    import fitz  # lazy: only the render digest reads a serialized document back

    return fitz


@functools.lru_cache(maxsize=64)
def _before_shape(before: bytes) -> tuple[int, ...]:
    return tuple(_render2x(_fitz().open(stream=before, filetype="pdf"), 0).shape)  # type: ignore[attr-defined]


def pixel_digest(
    before: bytes, after: bytes, rects: list[tuple[float, float, float, float]]
) -> tuple[str, tuple[str, ...]]:
    """PIXELS_OUTSIDE: SHA-256 of the AFTER page-0 render outside ``rects`` (the whole render, when its
    size differs from the BEFORE one) plus one SHA-256 per other page; 2x, annotations off, no alpha."""
    doc = _fitz().open(stream=after, filetype="pdf")  # type: ignore[attr-defined]
    pa = _render2x(doc, 0)
    shape = _before_shape(before)
    head = hashlib.sha256(repr(pa.shape).encode())
    head.update((pa[region_mask(shape, rects)] if tuple(pa.shape) == shape else pa).tobytes())
    rest = tuple(hashlib.sha256(_render2x(doc, i).tobytes()).hexdigest() for i in range(1, len(doc)))
    return head.hexdigest(), rest


# --------------------------------------------------------------------------- content emission


class _W:
    """A stream writer that records every token offset."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.toks: list[tuple[int, int]] = []

    def tok(self, text: str | bytes) -> tuple[int, int]:
        raw = text.encode("ascii") if isinstance(text, str) else text
        if self.buf and self.buf[-1] not in _WS:
            self.buf += b" "
        start = len(self.buf)
        self.buf += raw
        span = (start, len(self.buf))
        self.toks.append(span)
        return span

    def nl(self) -> None:
        self.buf += b"\n"


@dataclass
class _Mark:
    item: int
    stream: int
    start: int
    end: int
    q_start: int | None
    q_end: int | None
    group: int | None
    first_tok: tuple[int, int]


@dataclass
class _Emit:
    streams: list[bytes]
    marks: dict[int, _Mark]
    groups: dict[int, list[int]]
    tokens: list[list[tuple[int, int]]]


def _num(v: float) -> str:
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _construct(spec: PathSpec) -> list[str]:
    p = spec.points
    if spec.kind in ("line", "poly"):
        toks = [_num(p[0][0]), _num(p[0][1]), "m"]
        for q in p[1:]:
            toks += [_num(q[0]), _num(q[1]), "l"]
        return toks
    if spec.kind == "rect":
        (x0, y0), (x1, y1) = p[0], p[1]
        return [_num(x0), _num(y0), _num(x1 - x0), _num(y1 - y0), "re"]
    if spec.kind == "curve":
        toks = [_num(p[0][0]), _num(p[0][1]), "m"]
        for q in p[1:4]:
            toks += [_num(q[0]), _num(q[1])]
        return toks + ["c"]
    raise ValueError(f"unknown path kind {spec.kind!r}")


def _state_tokens(spec: PathSpec) -> list[str]:
    st = spec.state
    toks: list[str] = []
    if st.gs:
        toks += ["/GS0", "gs"]
    if spec.paint in ("S", "B"):
        toks += [_num(c) for c in st.stroke] + ["RG", _num(st.width), "w"]
        if st.dash:
            toks += ["[" + " ".join(_num(d) for d in st.dash) + "]", "0", "d"]
    if spec.paint in ("f", "B"):
        toks += [_num(c) for c in st.fill] + ["rg"]
    return toks


def _emit_page(page: PageSpec) -> _Emit:
    items = page.items
    writers = [_W()]
    marks: dict[int, _Mark] = {}
    groups: dict[int, list[int]] = {}
    for idx, it in enumerate(items):
        if isinstance(it, PathSpec) and it.state.block is not None:
            groups.setdefault(it.state.block, []).append(idx)
    for gid, members in groups.items():
        if members != list(range(members[0], members[-1] + 1)):
            raise ValueError(f"block {gid} is not made of consecutive items")
        if page.split_at is not None and members[0] < page.split_at <= members[-1]:
            raise ValueError("a block may not straddle the stream split")
    open_group: tuple[int, int] | None = None  # (group id, q start)
    last_close: dict[int, int] = {}
    for idx, it in enumerate(items):
        if page.split_at is not None and idx == page.split_at:
            writers.append(_W())
        w = writers[-1]
        sidx = len(writers) - 1
        if isinstance(it, RawSpec):
            w.tok(it.data)
            w.nl()
            continue
        st = it.state
        gid = st.block
        if st.oc:
            w.tok("/OC")
            w.tok("/MC0")
            w.tok("BDC")
        q_start: int | None = None
        starts_group = gid is not None and groups[gid][0] == idx
        if st.shape == "block":
            if gid is None or starts_group:
                q_start = w.tok("q")[0]
                if gid is not None:
                    open_group = (gid, q_start)
            else:
                assert open_group is not None
                q_start = open_group[1]
            if gid is None or starts_group:
                if it.ctm != IDENT:
                    for v in it.ctm:
                        w.tok(_num(v))
                    w.tok("cm")
        elif it.ctm != IDENT:
            for v in it.ctm:
                w.tok(_num(v))
            w.tok("cm")
        for t in _state_tokens(it):
            w.tok(t)
        construct = _construct(it)
        first = w.tok(construct[0])
        for t in construct[1:]:
            w.tok(t)
        if it.paint == "n":
            w.tok("W")
        end = w.tok("n" if it.paint == "n" else it.paint)[1]
        q_end: int | None = None
        closes = st.shape == "block" and (gid is None or groups[gid][-1] == idx)
        if closes:
            q_end = w.tok("Q")[1]
            if gid is not None:
                last_close[gid] = q_end
        if st.oc:
            w.tok("EMC")
        w.nl()
        marks[idx] = _Mark(idx, sidx, first[0], end, q_start, q_end, gid, first)
    for gid, members in groups.items():
        qs = marks[members[0]].q_start
        qe = last_close[gid]
        for m in members:
            marks[m].q_start, marks[m].q_end = qs, qe
    return _Emit([bytes(w.buf) for w in writers], marks, groups, [w.toks for w in writers])


# --------------------------------------------------------------------------- PDF assembly


@dataclass
class _Obj:
    d: dict[str, str] | None = None
    stream: bytes | None = None
    text: str | None = None  # a non-dictionary object (array, null, integer)


@dataclass
class _Layout:
    objs: dict[int, _Obj]
    trailer: dict[str, str]
    names: dict[int, str]
    streams0: list[int]  # xrefs of the edited page's content streams
    contents_obj: int | None  # xref of an indirect /Contents array, else None
    emit: _Emit
    originals: dict[int, bytes]  # decoded original bytes by stream xref (edited page)
    page0: int = 3


def _dict_text(d: dict[str, str]) -> str:
    return "<< " + " ".join(f"/{k} {v}" for k, v in d.items()) + " >>"


def _serialize(layout: _Layout) -> bytes:
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    top = max(layout.objs)
    for n in range(1, top + 1):
        offsets[n] = len(out)
        o = layout.objs.get(n)
        out += f"{n} 0 obj\n".encode()
        if o is None:
            out += b"null"
        elif o.stream is not None:
            d = dict(o.d or {})
            d.setdefault("Length", str(len(o.stream)))
            out += _dict_text(d).encode("ascii") + b"\nstream\n" + o.stream + b"\nendstream"
        elif o.d is not None:
            out += _dict_text(o.d).encode("ascii")
        else:
            out += (o.text or "null").encode("ascii")
        out += b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {top + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for n in range(1, top + 1):
        out += f"{offsets[n]:010d} 00000 n \n".encode()
    trailer = {"Size": str(top + 1), "Root": "1 0 R", **layout.trailer}
    out += b"trailer\n" + _dict_text(trailer).encode("ascii")
    out += f"\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


_RES = "<< /Font << /F1 10 0 R >> /ExtGState << /GS0 << /LW 1 >> >> /Properties << /MC0 14 0 R >> >>"
_FONT = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def _page_dict(spec: PageSpec, contents: str, parent: int = 2) -> dict[str, str]:
    d = {
        "Type": "/Page",
        "Parent": f"{parent} 0 R",
        "MediaBox": f"[0 0 {_PAGE_W} {_PAGE_H}]",
        "Contents": contents,
        "Resources": _RES,
    }
    if spec.rotate:
        d["Rotate"] = str(spec.rotate)
    if spec.cropbox is not None:
        d["CropBox"] = "[" + " ".join(_num(v) for v in spec.cropbox) + "]"
    if spec.userunit != 1.0:
        d["UserUnit"] = _num(spec.userunit)
    return d


def _referent_keys(t: Topology) -> list[str]:
    keys = []
    if t.form:
        keys.append("form")
    if t.pattern:
        keys.append("pattern")
    if t.ap:
        keys.append("ap")
    return keys


def _has_page1(scene: Scene) -> bool:
    t = scene.topology
    return len(scene.pages) >= 2 or t.second_page_shares or t.shared_array or t.ap or t.substring_xrefs


def _base_layout(scene: Scene) -> _Layout:
    t = scene.topology
    page0 = scene.pages[0]
    emit = _emit_page(page0)
    two = len(emit.streams) == 2
    objs: dict[int, _Obj] = {}
    names: dict[int, str] = {1: "catalog", 2: "pages", 3: "page:0", 5: "S0", 9: "FOREIGN"}
    s0_dict: dict[str, str] = {}
    if t.form or t.ap or t.pattern:
        s0_dict.update({"Type": "/XObject", "Subtype": "/Form", "BBox": f"[0 0 {_PAGE_W} {_PAGE_H}]"})
    if t.pattern:
        s0_dict.update({"PatternType": "1", "PaintType": "1", "TilingType": "1", "XStep": "200", "YStep": "200"})
    if t.indirect_length:
        s0_dict["Length"] = "11 0 R"
        objs[11] = _Obj(text=str(len(emit.streams[0])))
        names[11] = "S0-length"
    objs[5] = _Obj(d=s0_dict, stream=emit.streams[0])
    streams0 = [5]
    originals = {5: emit.streams[0]}
    if two:
        objs[6] = _Obj(d={}, stream=emit.streams[1])
        names[6] = "S1"
        if t.indirect_length:
            objs[6].d["Length"] = "16 0 R"
            objs[16] = _Obj(text=str(len(emit.streams[1])))
            names[16] = "S1-length"
        streams0.append(6)
        originals[6] = emit.streams[1]
    contents_obj: int | None = None
    if t.shared_array:
        contents_obj = 8
        objs[8] = _Obj(text="[" + " ".join(f"{n} 0 R" for n in streams0) + "]")
        names[8] = "ARRAY"
        c0 = "8 0 R"
    elif two:
        c0 = "[" + " ".join(f"{n} 0 R" for n in streams0) + "]"
    else:
        c0 = "5 0 R"
    objs[3] = _Obj(d=_page_dict(page0, c0))
    objs[9] = _Obj(d={}, stream=b"% foreign\n")
    objs[10] = _Obj(text=_FONT)
    objs[14] = _Obj(d={"Type": "/OCG", "Name": "(L)"})
    kids = "3 0 R"
    if _has_page1(scene):
        names[4] = "page:1"
        kids += " 4 0 R"
        own = scene.pages[1] if len(scene.pages) >= 2 else PageSpec()
        own_emit = _emit_page(own)
        own_no = 15 if t.substring_xrefs else 7
        names[own_no] = "P1"
        objs[own_no] = _Obj(d={}, stream=b"".join(own_emit.streams))
        if t.second_page_shares:
            c1 = "5 0 R"
        elif t.shared_array:
            c1 = "8 0 R"
        else:
            c1 = f"{own_no} 0 R"
        p1 = _page_dict(own, c1)
        if t.ap:
            p1["Annots"] = "[13 0 R]"
            objs[13] = _Obj(
                d={"Type": "/Annot", "Subtype": "/Square", "Rect": "[0 0 200 200]", "AP": "<< /N 5 0 R >>"}
            )
            names[13] = "ann"
        if t.form:
            p1["Resources"] = _RES[:-3] + " /XObject << /Fm0 5 0 R >> >>"
        if t.pattern:
            p1["Resources"] = p1["Resources"][:-3] + " /Pattern << /P0 5 0 R >> >>"
        objs[4] = _Obj(d=p1)
    objs[2] = _Obj(d={"Type": "/Pages", "Kids": f"[{kids}]", "Count": str(2 if " 4 " in kids + " " else 1)})
    objs[1] = _Obj(d={"Type": "/Catalog", "Pages": "2 0 R", "Foreign": "9 0 R"})
    if t.orphan:
        objs[12] = _Obj(d={"Type": "/Orphan", "Ref": "5 0 R"})
        names[12] = "orphan"
    if t.substring_xrefs:
        objs[7] = _Obj(d={"Note": "(decoy)"})
    top = max(objs)
    for n in range(1, top + 1):
        objs.setdefault(n, _Obj(text="null"))
    return _Layout(objs, {}, names, streams0, contents_obj, emit, originals)


def build(scene: Scene) -> bytes:
    """The twin's bytes: uncompressed content, direct ``/Length`` unless the topology says not."""
    return _serialize(_base_layout(scene))


# --------------------------------------------------------------------------- plans (ranges)


def _is_ws(data: bytes, i: int) -> bool:
    return 0 <= i < len(data) and data[i] in _WS


def _block_whole(emit: _Emit, page: PageSpec, gid: int, selected: frozenset[int]) -> bool:
    members = emit.groups[gid]
    return all(is_editable(page.items[m]) and m in selected for m in members)


def _whole(emit: _Emit, page: PageSpec, idx: int, selected: frozenset[int]) -> bool:
    """D17 for item ``idx``: its q..Q wrapper goes whole when every member of that block is editable and selected.
    A group is its members; an ungrouped item with its own wrapper is a block of one (a bare cumulative path has no
    wrapper offsets).  Astra review 2026-11-26, from the first product-vs-oracle run."""
    m = emit.marks[idx]
    if m.q_start is None or m.q_end is None:
        return False
    members = emit.groups[m.group] if m.group is not None else (idx,)
    return all(is_editable(page.items[x]) and x in selected for x in members)


def _plan(
    emit: _Emit,
    page: PageSpec,
    selected: frozenset[int],
    *,
    whole_blocks: bool = True,
    tight: bool = False,
) -> dict[int, list[tuple[int, int]]]:
    """The legal plan of D7/D17 for ``selected`` (editable items only): ranges per stream."""
    out: dict[int, list[tuple[int, int]]] = {}
    seen_blocks: set[tuple[int, int | None, int | None]] = set()
    for idx in sorted(selected):
        m = emit.marks[idx]
        data = emit.streams[m.stream]
        if whole_blocks and _whole(emit, page, idx, selected):
            key = (m.stream, m.q_start, m.q_end)
            if key in seen_blocks:
                continue
            seen_blocks.add(key)
            s, e = m.q_start, m.q_end
        else:
            s, e = m.start, m.end
        assert s is not None and e is not None
        if not tight and _is_ws(data, s - 1) and _is_ws(data, e):  # D7: both neighbours (a stream start has none)
            e += 1
        out.setdefault(m.stream, []).append((s, e))
    return {k: _merge(v) for k, v in out.items()}


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(ranges):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _envelopes(
    emit: _Emit, page: PageSpec, selected: frozenset[int]
) -> dict[int, list[tuple[int, int, int, int, bool]]]:
    """Per stream ``(env_start, env_end, own_start, own_end, whole_block)`` for each selected path."""
    out: dict[int, list[tuple[int, int, int, int, bool]]] = {}
    for idx in sorted(selected):
        m = emit.marks[idx]
        data = emit.streams[m.stream]
        whole = _whole(emit, page, idx, selected)
        s, e = (m.q_start, m.q_end) if whole else (m.start, m.end)
        assert s is not None and e is not None
        lead = 1 if _is_ws(data, s - 1) and s > 0 else 0
        trail = 1 if _is_ws(data, e) else 0
        out.setdefault(m.stream, []).append((s - lead, e + trail, m.start, m.end, whole))
    return out


def _cut(data: bytes, ranges: list[tuple[int, int]]) -> bytes:
    out = bytearray()
    pos = 0
    for s, e in sorted(ranges):
        out += data[pos:s]
        pos = e
    out += data[pos:]
    return bytes(out)


def _digest(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8") if not isinstance(p, bytes) else p)
        h.update(b"\x1f")
    return h.hexdigest()[:24]


# --------------------------------------------------------------------------- commit model


def _stream_exclusive(scene: Scene, sidx: int) -> bool:
    """D20b's chain for one stream of the edited page: the page object is unique (always, here), a
    ``/Contents`` array that is an indirect object is referenced once, the stream is referenced once,
    and its dictionary names no indirect object.  The topology flags say who else names which stream:
    only S0 is a form, a pattern, an appearance, shared by page 1 or named by the orphan."""
    t = scene.topology
    if t.shared_array or t.indirect_length:
        return False
    if sidx == 0 and (t.second_page_shares or t.form or t.pattern or t.ap or t.orphan):
        return False
    return True


def _places(scene: Scene, ranges: dict[int, list[tuple[int, int]]], mode: str, has_array: bool) -> dict[int, str]:
    """Where each edited stream is written: ``auto`` follows D20b per stream; the others force it."""
    out: dict[int, str] = {}
    for sidx in ranges:
        if mode == "auto":
            out[sidx] = "inplace" if _stream_exclusive(scene, sidx) else "copy"
        elif mode == "array":
            out[sidx] = "array" if has_array else "copy"
        else:
            out[sidx] = mode
    return out


def _commit(
    layout: _Layout, ranges: dict[int, list[tuple[int, int]]], places: dict[int, str]
) -> tuple[_Layout, dict[str, object]]:
    """Apply ranges the way the product would: each stream in place when exclusive, else a copy."""
    lay = copy.deepcopy(layout)
    info: dict[str, object] = {"inplace": [], "new": [], "array": False}
    refs = list(lay.streams0)
    new_refs = list(refs)
    for sidx, rs in sorted(ranges.items()):
        xref = lay.streams0[sidx]
        data = _cut(layout.originals[xref], rs)
        z = zlib.compress(data, 6)
        if places[sidx] == "inplace":
            obj = lay.objs[xref]
            obj.stream = z
            assert obj.d is not None
            obj.d["Filter"] = "/FlateDecode"
            obj.d.pop("DecodeParms", None)
            obj.d.pop("DL", None)
            obj.d.pop("Length", None)
            info["inplace"].append(xref)  # type: ignore[union-attr]
        else:
            nn = max(lay.objs) + 1
            d = dict(lay.objs[xref].d or {})
            d.pop("Length", None)
            d.pop("DecodeParms", None)
            d.pop("DL", None)
            d["Filter"] = "/FlateDecode"
            lay.objs[nn] = _Obj(d=d, stream=z)
            lay.names[nn] = f"NEW{len(info['new'])}"  # type: ignore[arg-type]
            new_refs[sidx] = nn
            info["new"].append(nn)  # type: ignore[union-attr]
    if info["new"]:
        if all(p == "array" for p in places.values()):
            assert lay.contents_obj is not None
            lay.objs[lay.contents_obj].text = "[" + " ".join(f"{n} 0 R" for n in new_refs) + "]"
            info["array"] = True
        else:
            assert lay.objs[3].d is not None
            multi = len(refs) > 1 or lay.contents_obj is not None
            lay.objs[3].d["Contents"] = (
                "[" + " ".join(f"{n} 0 R" for n in new_refs) + "]" if multi else f"{new_refs[0]} 0 R"
            )
    return lay, info


# --------------------------------------------------------------------------- facts


def _view_removed(scene: Scene, removed: frozenset[int], which: str) -> tuple[tuple[object, ...], ...]:
    """Records of what a referent of S0 (``S0`` only) or of the whole stream list draws."""
    page = scene.pages[0]
    split = page.split_at
    items = page.items if which == "all" or split is None else page.items[:split]
    return tuple(rec for _i, rec in _records(items, removed))


def _object_changes(base: _Layout, after: _Layout) -> set[str]:
    """Symbolic names of objects whose abstract state differs (page object: two halves)."""
    changed: set[str] = set()

    def norm(o: _Obj) -> tuple[object, ...]:
        d = {k: v for k, v in (o.d or {}).items() if k != "Length"}
        return (tuple(sorted(d.items())), o.stream, o.text)

    for n in sorted(set(base.objs) | set(after.objs)):
        a, b = base.objs.get(n), after.objs.get(n)
        name = after.names.get(n) or base.names.get(n) or f"obj{n}"
        if a is None or b is None:
            changed.add(name)
            continue
        if n == base.page0:
            da, db = a.d or {}, b.d or {}
            if da.get("Contents") != db.get("Contents"):
                changed.add("page:0:contents")
            if {k: v for k, v in da.items() if k != "Contents"} != {k: v for k, v in db.items() if k != "Contents"}:
                changed.add("page:0:rest")
            continue
        if norm(a) != norm(b):
            changed.add(name)
    if base.trailer != after.trailer:
        changed.add("trailer")
    return changed


def _refs_of(text: str) -> list[int]:
    toks = text.strip("[]").split()
    return [int(toks[i]) for i in range(0, len(toks), 3)]


def _array_names(lay: _Layout, arr: str) -> tuple[str, ...]:
    return tuple(lay.names.get(n, f"obj{n}") for n in _refs_of(arr))


def _dict_fact(lay: _Layout, *, rollback: bool, orig: _Layout) -> tuple[object, ...]:
    """The ``vector_page_prestate`` normal form of the page's content streams, abstractly.

    Rollback: the ``/Contents`` value, every stream's name, full dictionary (``/Length`` left out)
    and decoded digest.  Commit: the page's stream dictionaries by position, without
    ``/Length /Filter /DecodeParms /DL``; ``/Contents`` itself may legally change (D20).
    """
    d = lay.objs[3].d or {}
    text = d["Contents"]
    if lay.contents_obj is not None and text == f"{lay.contents_obj} 0 R":
        contents: tuple[object, ...] = ("ref", "ARRAY", _array_names(lay, lay.objs[lay.contents_obj].text or ""))
        stream_xrefs = _refs_of(lay.objs[lay.contents_obj].text or "")
    else:
        refs = _refs_of(text)
        contents = ("direct", tuple(lay.names.get(n, f"obj{n}") for n in refs))
        stream_xrefs = refs
    parts = []
    for pos, n in enumerate(stream_xrefs):
        o = lay.objs[n]
        keys = {k: v for k, v in (o.d or {}).items() if k != "Length"}
        if not rollback:
            keys = {k: v for k, v in keys.items() if k not in _COMMIT_DICT_EXCLUDED}
            parts.append((pos, tuple(sorted(keys.items()))))
        else:
            parts.append((lay.names.get(n, f"obj{n}"), tuple(sorted(keys.items())), _decoded_key(o, orig, n)))
    return ((contents if rollback else None), tuple(parts))


def _decoded_key(o: _Obj, orig: _Layout, n: int) -> str:
    """Digest of the decoded bytes of a stream object (the builder knows how it wrote them)."""
    raw = o.stream or b""
    if (o.d or {}).get("Filter") == "/FlateDecode":
        raw = zlib.decompress(raw)
    return _digest(raw)


def _build_facts(
    scene: Scene,
    op: Op,
    base: _Layout,
    after: _Layout,
    *,
    removed: frozenset[int],
    sel: frozenset[int],
    places: dict[int, str],
    ranges: dict[int, list[tuple[int, int]]],
    envs: dict[int, list[tuple[int, int, int, int, bool]]],
    colour_hit: dict[int, float] | None,
    rollback: bool,
    damaged_note: tuple[object, ...] = (),
    declared: str = "inplace",
) -> Facts:
    page = scene.pages[0]
    t = scene.topology
    facts = Facts()
    recs = _records(page.items, removed, colour_hit)
    facts[PATHS] = tuple(r for _i, r in recs) + damaged_note
    others: dict[str, object] = {}
    sees = (t.second_page_shares and places.get(0) == "inplace") or (
        t.shared_array and any(p in ("inplace", "array") for p in places.values())
    )
    s0_removed = removed if places.get(0) == "inplace" else frozenset()
    page1_view_removed = removed if sees else frozenset()
    if len(scene.pages) >= 2 or _has_page1(scene):
        if t.second_page_shares:
            others["page:1"] = _view_removed(scene, page1_view_removed, "s0")
        elif t.shared_array:
            others["page:1"] = _view_removed(scene, page1_view_removed, "all")
        else:
            own = scene.pages[1] if len(scene.pages) >= 2 else PageSpec()
            others["page:1"] = tuple(r for _i, r in _records(own.items))
    for key in _referent_keys(t):
        others[f"{key}:S0"] = _view_removed(scene, s0_removed, "s0")
    facts[OTHER_PAGES] = others
    removed_outside: list[bytes] = []
    kept_selected: list[bytes] = []
    for sidx, e_list in envs.items():
        data = base.emit.streams[sidx]
        cut_ranges = ranges.get(sidx, [])
        for env_s, env_e, own_s, own_e, _whole in e_list:
            for pos in range(own_s, own_e):
                if not any(s <= pos < e for s, e in cut_ranges):
                    kept_selected.append(data[pos : pos + 1])
        for s, e in cut_ranges:
            for pos in range(s, e):
                if not any(es <= pos < ee for es, ee, *_ in e_list):
                    removed_outside.append(data[pos : pos + 1])
    for sidx, cut_ranges in ranges.items():
        if sidx not in envs:
            data = base.emit.streams[sidx]
            for s, e in cut_ranges:
                removed_outside.append(data[s:e])
    facts[OUTSIDE_BYTES] = (_digest(b"".join(removed_outside)), "", _digest(b"".join(kept_selected)))
    changed = _object_changes(base, after)
    allowed = {"page:0:contents"} if not rollback else set()
    info_names = {n for n in after.names.values() if n.startswith("NEW")}
    if not rollback:
        allowed |= info_names
        if declared == "inplace":
            correct = _plan(base.emit, page, sel)
            allowed |= {base.names[base.streams0[s]] for s in correct if _stream_exclusive(scene, s)}
    facts[OBJECTS] = tuple(sorted(changed - allowed))
    # PIXELS_OUTSIDE is a real render digest (owner decision 2026-11-22): the renders of the serialized
    # documents.  Rule A: the region comes from the builder's own records, never from an oracle helper.
    rects = [] if rollback else region_rects(page, path_ordinals(page, op.selected))
    facts[PIXELS_OUTSIDE] = pixel_digest(_serialize(base), _serialize(after), rects) + damaged_note
    facts[DICT] = _dict_fact(after, rollback=rollback, orig=base)
    return facts


def ranges_xrefs(layout: _Layout, ranges: dict[int, list[tuple[int, int]]]) -> set[int]:
    return {layout.streams0[s] for s in ranges}


def _context(
    scene: Scene,
    op: Op,
    base: _Layout,
    after: _Layout,
    ranges: dict[int, list[tuple[int, int]]],
    envs: dict[int, list[tuple[int, int, int, int, bool]]],
    declared_place: str | None = None,
) -> dict[str, object]:
    """Oracle keyword arguments.  The declared write set is what a *correct* commit declares for the
    scene (a mutant's own actions never widen it)."""
    rollback = op.fate == "rollback"
    sel = _selection(scene, replace(op, fate="commit"))
    correct = _plan(base.emit, scene.pages[0], sel)
    force_copy = declared_place == "copy"
    first_new = max(base.objs) + 1
    stream_xrefs: frozenset[int] = frozenset()
    new_xrefs: frozenset[int] = frozenset()
    exclusive = [s for s in correct if _stream_exclusive(scene, s)]
    if not rollback:
        in_place = [] if force_copy else exclusive
        stream_xrefs = frozenset(base.streams0[s] for s in in_place)
        new_xrefs = frozenset(range(first_new, first_new + len(correct) - len(in_place)))
    return {
        "scenario_op": op,
        "scene": scene,
        "ranges": ranges,
        "envelopes": envs,
        "fate": op.fate,
        "xref_names": dict(after.names),
        "page_xref": 3,
        "stream_xrefs": stream_xrefs,
        "new_xrefs": new_xrefs,
        "selected_drawings": drawing_indices(scene.pages[0], op.selected),
        "selected_halves": selected_halves(scene.pages[0], op.selected),
        "edited_xrefs": [base.streams0[s] for s in exclusive] if not rollback else [],
    }


def _painted_items(page: PageSpec) -> list[int]:
    return [i for i, it in enumerate(page.items) if isinstance(it, PathSpec) and it.paint != "n"]


def path_ordinals(page: PageSpec, selected: tuple[int, ...]) -> tuple[int, ...]:
    """Ordinals (in painted-path order) of the selected, editable paths; one path is one ordinal."""
    order = _painted_items(page)
    return tuple(order.index(i) for i in sorted(selected) if i in order and is_editable(page.items[i]))


def _halves_by_path(page: PageSpec) -> list[list[tuple[int, str]]]:
    """Per painted path, its ``(drawing index, "f" or "s")`` halves in MuPDF's drawing order.

    MuPDF merges a fill-only path followed at once by a stroke-only path of the same geometry into one
    ``fs`` drawing (a stroke followed by a fill stays two), so a drawing number is not a path ordinal.
    Rule A: the builder never reads a PDF, so the merge is PREDICTED here from the builder's own records
    (adjacent items, fill then stroke, equal page-space primitives); ``test_vector_fixture_builder``
    checks the prediction against MuPDF's drawings over the scenes and the generator's seeds."""
    recs = _records(page.items)
    out: list[list[tuple[int, str]]] = []
    drawing = -1
    for n, (idx, rec) in enumerate(recs):
        paint = rec[0]
        if n and paint == "S" and recs[n - 1][1][0] == "f" and recs[n - 1][0] + 1 == idx and recs[n - 1][1][1] == rec[1]:
            out.append([(drawing, "s")])  # merged into the previous fill's drawing
            continue
        drawing += 1
        out.append([(drawing, "f")] if paint == "f" else [(drawing, "s")] if paint == "S" else [(drawing, "f"), (drawing, "s")])
    return out


def selected_halves(page: PageSpec, selected: tuple[int, ...]) -> tuple[tuple[int, str], ...]:
    """``(drawing index, "f" or "s")`` of every half the selected, editable paths paint (MuPDF's order)."""
    halves = _halves_by_path(page)
    return tuple(sorted({h for o in path_ordinals(page, selected) for h in halves[o]}))


def drawing_indices(page: PageSpec, selected: tuple[int, ...]) -> tuple[int, ...]:
    """Indices (in MuPDF's drawing order) of the drawings that hold a half of a selected, editable path."""
    return tuple(sorted({di for di, _k in selected_halves(page, selected)}))


def _selection(scene: Scene, op: Op) -> frozenset[int]:
    if op.kind == "move":
        raise NotImplementedError("move is built by card C1")
    if op.kind != "delete":
        raise ValueError(f"unknown operation {op.kind!r}")
    if op.page != 0:
        raise ValueError("only page 0 is edited")
    page = scene.pages[0]
    return frozenset(i for i in op.selected if 0 <= i < len(page.items) and is_editable(page.items[i]))


def _assemble(
    scene: Scene,
    op: Op,
    *,
    ranges_sel: frozenset[int] | None = None,
    removed: frozenset[int] | None = None,
    plan_kwargs: dict[str, bool] | None = None,
    place: str = "auto",
    raw_ranges: dict[int, list[tuple[int, int]]] | None = None,
    colour_hit: dict[int, float] | None = None,
    damaged_note: tuple[object, ...] = (),
    tweak: str | None = None,
    declared: str | None = None,
) -> tuple[bytes, Facts]:
    sel = _selection(scene, op)
    page = scene.pages[0]
    base = _base_layout(scene)
    emit = base.emit
    if op.fate == "rollback":
        return _rollback(scene, op, base, tweak)
    plan_sel = sel if ranges_sel is None else ranges_sel
    ranges = raw_ranges if raw_ranges is not None else _plan(emit, page, plan_sel, **(plan_kwargs or {}))
    gone = sel if removed is None else removed
    places = _places(scene, ranges, place, base.contents_obj is not None)
    after, info = _commit(base, ranges, places)
    if tweak == "rotate":
        d = after.objs[3].d
        assert d is not None
        d["Rotate"] = str((page.rotate + 90) % 360)
    elif tweak == "trailer":
        after.trailer["Marker"] = "(x)"
    elif tweak == "foreign":
        after.objs[9].stream = b"% foreign changed\n"
    elif tweak == "extra_key":
        written = (info["inplace"] or info["new"])  # type: ignore[assignment]
        if written:
            wd = after.objs[written[0]].d  # type: ignore[index]
            assert wd is not None
            wd["Foo"] = "1"
    envs = _envelopes(emit, page, sel)
    facts = _build_facts(
        scene,
        op,
        base,
        after,
        removed=gone,
        sel=sel,
        places=places,
        ranges=ranges,
        envs=envs,
        colour_hit=colour_hit,
        rollback=False,
        damaged_note=damaged_note,
        declared=declared or "inplace",
    )
    data = _serialize(after)
    facts.context.update(_context(scene, op, base, after, ranges, envs, declared))
    return data, facts


def _rollback(scene: Scene, op: Op, base: _Layout, tweak: str | None) -> tuple[bytes, Facts]:
    """The document after a failed commit and its rollback (or one of the faulty variants)."""
    page = scene.pages[0]
    after = copy.deepcopy(base)
    info: dict[str, object] = {"inplace": [], "new": [], "array": False}
    removed: frozenset[int] = frozenset()
    rb_places: dict[int, str] = {}
    sel = _selection(scene, replace(op, fate="commit"))
    ranges_for_commit = _plan(base.emit, page, sel)
    if tweak == "skip_restore":
        rb_places = _places(scene, ranges_for_commit, "auto", False)
        after, info = _commit(base, ranges_for_commit, rb_places)
        removed = sel
    elif tweak == "repoint":
        nn = max(after.objs) + 1
        d = dict(after.objs[5].d or {})
        d.pop("Length", None)
        after.objs[nn] = _Obj(d=d, stream=base.emit.streams[0])
        after.names[nn] = "NEW0"
        after.objs[3].d["Contents"] = f"{nn} 0 R" if len(base.streams0) == 1 and base.contents_obj is None else (  # type: ignore[index]
            "[" + " ".join(f"{nn if i == 0 else n} 0 R" for i, n in enumerate(base.streams0)) + "]"
        )
        info["new"] = [nn]  # type: ignore[assignment]
    elif tweak == "filter":
        obj = after.objs[5]
        obj.stream = zlib.compress(base.emit.streams[0], 6)
        assert obj.d is not None
        obj.d["Filter"] = "/FlateDecode"
        obj.d.pop("Length", None)
    ranges: dict[int, list[tuple[int, int]]] = {}
    envs: dict[int, list[tuple[int, int, int, int, bool]]] = {}
    facts = _build_facts(
        scene,
        op,
        base,
        after,
        removed=removed,
        sel=frozenset(),
        places=rb_places,
        ranges=ranges_for_commit if tweak == "skip_restore" else ranges,
        envs=envs,
        colour_hit=None,
        rollback=True,
    )
    facts.context.update(_context(scene, op, base, after, ranges, envs))
    return _serialize(after), facts


def expected(scene: Scene, op: Op) -> tuple[bytes, Facts]:
    """The correct after-document of ``op`` and its facts (rollback: the restored document)."""
    data, facts = _assemble(scene, op)
    facts.context["expected"] = data
    return data, facts


def scenario_of(name: str, op: Op) -> Op:
    """The operation scenario a mutant is defined on (rollback mutants: a rolled-back delete)."""
    if name not in MUTANT_NAMES:
        raise KeyError(name)
    return replace(op, fate="rollback") if name in _ROLLBACK_MUTANTS else replace(op, fate="commit")


def _neighbour(page: PageSpec, sel: frozenset[int]) -> int | None:
    if not sel:
        return None
    top = max(sel)
    for i in range(top + 1, len(page.items)):
        if is_editable(page.items[i]) and i not in sel:
            return i
    for i in range(min(sel) - 1, -1, -1):
        if is_editable(page.items[i]) and i not in sel:
            return i
    return None


def mutants(scene: Scene, op: Op) -> list[tuple[str, bytes, Facts]]:
    """The 13 fixed mutants of ``op`` on ``scene``, each built on the abstract scene (rule A)."""
    if op.fate != "commit":
        raise ValueError("mutants are defined from a commit operation")
    sel = _selection(scene, op)
    page = scene.pages[0]
    emit = _emit_page(page)
    out: list[tuple[str, bytes, Facts]] = []

    def add(name: str, pair: tuple[bytes, Facts]) -> None:
        out.append((name, pair[0], pair[1]))

    neigh = _neighbour(page, sel)
    ext = sel | ({neigh} if neigh is not None else set())
    add(
        MUTANT_NAMES[0],
        _assemble(scene, op, ranges_sel=frozenset(ext), removed=frozenset(ext)),
    )
    kept = frozenset(sorted(sel)[:-1])
    add(MUTANT_NAMES[1], _assemble(scene, op, ranges_sel=kept, removed=kept))
    # block removed where a D17 rule fails: the first selected path in a block with an unselected member
    broken: dict[int, list[tuple[int, int]]] = {}
    gone: set[int] = set(sel)
    for idx in sorted(sel):
        m = emit.marks[idx]
        if m.group is not None and not _block_whole(emit, page, m.group, sel):
            assert m.q_start is not None and m.q_end is not None
            broken = _plan(emit, page, sel - {idx})
            broken.setdefault(m.stream, []).append((m.q_start, m.q_end))
            broken = {k: _merge(v) for k, v in broken.items()}
            gone |= set(emit.groups[m.group])
            break
    if broken:
        add(MUTANT_NAMES[2], _assemble(scene, op, removed=frozenset(gone), raw_ranges=broken))
    else:
        add(MUTANT_NAMES[2], _assemble(scene, op))
    add(MUTANT_NAMES[3], _shifted(scene, op, sel, emit))
    add(MUTANT_NAMES[4], _assemble(scene, op, place="inplace"))
    add(MUTANT_NAMES[5], _assemble(scene, op, place="array") if scene.topology.shared_array else _assemble(scene, op))
    add(MUTANT_NAMES[6], _assemble(scene, op, tweak="rotate"))
    add(MUTANT_NAMES[7], _assemble(scene, op, tweak="trailer"))
    add(MUTANT_NAMES[8], _assemble(scene, op, tweak="foreign"))
    rb = replace(op, fate="rollback")
    add(MUTANT_NAMES[9], _assemble(scene, rb, tweak="skip_restore"))
    add(MUTANT_NAMES[10], _assemble(scene, rb, tweak="repoint"))
    add(MUTANT_NAMES[11], _assemble(scene, op, tweak="extra_key"))
    add(MUTANT_NAMES[12], _assemble(scene, rb, tweak="filter"))
    return out


def _shifted(scene: Scene, op: Op, sel: frozenset[int], emit: _Emit) -> tuple[bytes, Facts]:
    """The first selected path whose successor is a bare, identity-CTM path is cut one token late."""
    page = scene.pages[0]
    for idx in sorted(sel):
        nxt = idx + 1
        if nxt >= len(page.items):
            continue
        b = page.items[nxt]
        a = page.items[idx]
        if not (
            isinstance(a, PathSpec)
            and isinstance(b, PathSpec)
            and a.state.shape == "cumulative"
            and b.state.shape == "cumulative"
            and b.ctm == IDENT
            and b.paint in ("S", "f", "B")
            and not b.state.oc
            and a.state.block is None
        ):
            continue
        ma, mb = emit.marks[idx], emit.marks[nxt]
        if ma.stream != mb.stream:
            continue
        toks = emit.tokens[ma.stream]
        second = next(t for t in toks if t[0] >= ma.first_tok[1] and t[0] > ma.first_tok[0])
        # the first token of the next item is the first one at or after its recorded state/path start
        first_b = next(t for t in toks if t[0] > ma.end)
        rng = {ma.stream: [(second[0], first_b[1])]}
        x0 = a.points[0][0]
        hit = {nxt: _clamp01(float(_num(x0)))}
        return _assemble(scene, op, raw_ranges=rng, removed=sel, colour_hit=hit)
    return _assemble(scene, op)


def must_pass(scene: Scene, op: Op) -> list[tuple[str, bytes, Facts]]:
    """Correct after-documents in other legal encodings (the must-pass column)."""
    sel = _selection(scene, op)
    out: list[tuple[str, bytes, Facts]] = []
    data, facts = expected(scene, op)
    out.append(("correct", data, facts))
    if op.fate != "commit":
        return out
    page = scene.pages[0]
    emit = _emit_page(page)
    if any(_whole(emit, page, i, sel) for i in sel):
        d, f = _assemble(scene, op, plan_kwargs={"whole_blocks": False})
        out.append(("span only", d, f))
    d, f = _assemble(scene, op, plan_kwargs={"tight": True})
    out.append(("tight whitespace", d, f))
    if any(_stream_exclusive(scene, s) for s in _plan(emit, page, sel)):
        d, f = _assemble(scene, op, place="copy", declared="copy")
        out.append(("copy", d, f))
    return out


# --------------------------------------------------------------------------- scenes


def _p(kind: str, pts: tuple[Point, ...], paint: str = "S", ctm: Matrix = IDENT, **state: object) -> PathSpec:
    return PathSpec(kind, pts, paint, ctm, PathState(**state))  # type: ignore[arg-type]


def sample_items() -> tuple[PathSpec | RawSpec, ...]:
    return (
        _p("line", ((10, 10), (60, 20)), "S", (1, 0, 0, 1, 10, 5), stroke=(1.0, 0.0, 0.0), width=2.0),  # 0
        _p("rect", ((20, 30), (50, 60)), "B", fill=(0.0, 1.0, 0.0), stroke=(0.0, 0.0, 1.0), block=1),  # 1
        _p("line", ((22, 32), (70, 90)), "S", stroke=(0.5, 0.0, 0.5), block=1),  # 2
        _p("curve", ((80, 10), (90, 40), (100, 40), (110, 10)), "S", stroke=(0.0, 0.0, 0.0), shape="cumulative"),  # 3
        _p("line", ((120, 120), (150, 130)), "S", stroke=(0.0, 0.5, 0.5), shape="cumulative"),  # 4
        _p("line", ((130, 20), (170, 30)), "S", (0.5, 0.0, 0.0, 0.5, 20, 20), stroke=(0.2, 0.2, 0.2), shape="cumulative"),  # 5
        _p("line", ((40, 140), (90, 150)), "S", stroke=(0.0, 0.0, 0.0), shape="cumulative"),  # 6
        _p("line", ((5, 190), (190, 190)), "S", oc=True, shape="block"),  # 7 OC: not editable
        _clip_item(),  # 8 clip
        _p("line", ((15, 170), (95, 180)), "S", dash=(4.0, 2.0), gs=True),  # 9
        RawSpec(b"BT /F1 12 Tf 10 100 Td (0 0 m 9 9 l S Q) Tj ET", "text"),  # 10
        RawSpec(b"% 0 0 m 9 9 l S", "comment"),  # 11
    )


def _clip_item() -> PathSpec:
    return PathSpec("rect", ((100.0, 100.0), (180.0, 180.0)), "n", IDENT, PathState(clip=True))


def sample_scene(topology: Topology | None = None) -> Scene:
    items = sample_items()
    other = PageSpec((_p("line", ((5, 5), (95, 95)), "S", stroke=(0.3, 0.3, 0.9)),))
    return Scene((PageSpec(items), other), topology or Topology())


def scene_for_topology(name: str) -> Scene:
    if name not in TOPOLOGY_FLAGS:
        raise KeyError(name)
    if name == "exclusive":
        return sample_scene()
    if name == "two_streams":
        base = sample_scene()
        page = replace(base.pages[0], split_at=5)
        return replace(base, pages=(page, base.pages[1]))
    return sample_scene(Topology(**{name: True}))


def default_scenes() -> list[tuple[str, Scene]]:
    """Every topology the calibration runs on."""
    names = sorted(TOPOLOGY_FLAGS)
    scenes = [(n, scene_for_topology(n)) for n in names]
    base = sample_scene()
    scenes.append(("shares+two_streams", replace(
        sample_scene(Topology(second_page_shares=True)),
        pages=(replace(base.pages[0], split_at=5), base.pages[1]),
    )))
    scenes.append(("shared_array+two_streams", replace(
        sample_scene(Topology(shared_array=True)),
        pages=(replace(base.pages[0], split_at=5), base.pages[1]),
    )))
    return scenes
