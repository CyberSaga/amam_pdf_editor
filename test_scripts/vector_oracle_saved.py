"""O-struct (mapped form), O-reopen and O-vendor of design plan section 9 (card B1 completion).

All three take a before/after pair and a product-side input given as an argument, never imported:
index rows plus the page frame (the O-scan mapping), a saved file, a vendor document.  They are
registered in ``vector_oracles.calibrate`` through its ``extra_kw`` hook (``kw_for_matrix``).

Not built here (waits for card C1, whose builder has no ``move``): O-reopen's move rows, the
mapping-free O-struct for a move (multiset rule (a), order rule (b)), the product-shaped move forms
(design plan Tolerances, N4) and the builder's move mutants.  The mapped O-struct has a move rule and
is calibrated on twins moved by :func:`moved_page` (a hand-made translated twin, not a builder op).
"""

from __future__ import annotations

import functools
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import fitz
import numpy as np

import model.doc_bytes  # noqa: F401  (D24: the product's save prelude is installed during every round trip)
from test_scripts import vector_fixture_builder as vfb
from test_scripts import vector_independent_expected as vie
from test_scripts import vector_index_rows as vir
from test_scripts import vector_matching as vm
from test_scripts import vector_oracles as vo
from test_scripts.vector_oracle_scan import _item_points, comparable_drawings, scan_alignment

logger = logging.getLogger(__name__)

_FILL = frozenset({"f", "F", "f*"})
_STROKE = frozenset({"S", "s"})
Half = tuple[object, ...]  # (kind, props, shape, coords)


def _kind(op: object) -> str:
    return vo._kind(op)


def _fate(kw: dict[str, object]) -> str:
    return vo._fate(kw)


def _open(data: bytes) -> fitz.Document:
    return fitz.open(stream=data, filetype="pdf")


# --------------------------------------------------------------------------- records


def _decompose(items: Sequence[Sequence[object]]) -> tuple[tuple[object, ...], tuple[float, ...]]:
    """Items to a shape tag (kinds, rectangle orientation) and the flat coordinates (x, y, x, y, ...)."""
    shape: list[object] = []
    coords: list[float] = []
    for it in items:
        kind = it[0]
        shape.append((kind, it[2]) if kind == "re" else (kind,))
        for x, y in _item_points(it):
            coords += [0.0 if x == 0 else x, 0.0 if y == 0 else y]
    return tuple(shape), tuple(coords)


def drawing_halves(d: dict) -> list[Half]:
    """A drawing as its fill half and its stroke half (an ``fs`` drawing has both).  A half carries only
    what its own paint defines: a stand-alone fill has no cap, join or dashes, so the fill half of a
    merged drawing equals the stand-alone fill that survives when the stroke is deleted."""
    shape, coords = _decompose([tuple(it) for it in d["items"]])
    out: list[Half] = []
    kind = d.get("type")
    if kind in ("f", "fs"):
        out.append(("f", vo._norm((d.get("fill"), d.get("fill_opacity"), d.get("even_odd"))), shape, coords))
    if kind in ("s", "fs"):
        props = (d.get("color"), d.get("width"), d.get("dashes"), d.get("stroke_opacity"), d.get("lineCap"), d.get("lineJoin"), d.get("closePath"))
        out.append(("s", vo._norm(props), shape, coords))
    return out


def _halves_match(a: Half, b: Half, tolerant: bool) -> bool:
    if a[:3] != b[:3]:
        return False
    if not tolerant:
        return a[3] == b[3]
    return len(a[3]) == len(b[3]) and all(vm.coordinates_match(x, y) for x, y in zip(a[3], b[3], strict=True))  # type: ignore[arg-type]


def _first_difference(expected: list[Half], got: list[Half], tolerant: bool) -> str:
    if len(expected) != len(got):
        return f"{len(got)} survivor records, expected {len(expected)}"
    for i, (e, g) in enumerate(zip(expected, got, strict=True)):
        if not _halves_match(e, g, tolerant):
            return f"record {i} ({e[0]}) differs from the expected survivor"
    return ""


# --------------------------------------------------------------------------- O-struct, mapped form


def _owner_rows(rows_of_drawing: tuple[int, ...], rows: Sequence[vir.IndexRow], kind: str) -> int:
    """The row that owns a drawing's ``kind`` half: with two rows (a merged fill and stroke) the one whose
    paint is that kind, with one row that row."""
    if len(rows_of_drawing) == 1:
        return rows_of_drawing[0]
    wanted = _FILL if kind == "f" else _STROKE
    for r in rows_of_drawing:
        if rows[r].paint in wanted:
            return r
    return rows_of_drawing[0]


def o_struct_mapped(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Mapped form: take the row-to-drawing mapping O-scan builds on the BEFORE page.  Delete: the new list
    is the old one minus the halves whose rows were selected, same order, same type, colour, width, dashes,
    caps and items, exactly; a merged drawing with one half selected stays as the surviving half's type.
    Move: the selected halves are translated by ``delta`` (row space, mapped through the frame's linear
    part) and nothing else differs, within the one tolerance of D23."""
    kind = _kind(op)
    if kind not in ("delete", "move"):
        raise ValueError(f"no oracle rule for operation {kind!r}")
    rows = kw.get("rows")
    frame = kw.get("frame")
    if rows is None or frame is None:
        raise ValueError("O-struct mapped needs the O-scan rows and the page frame (kw rows=, frame=)")
    selected = frozenset() if _fate(kw) == "rollback" else frozenset(kw.get("selected_rows", ()))  # type: ignore[call-overload]
    old_drawings = comparable_drawings(before)  # the comparable list, as O-scan's mapping is built on it
    al = scan_alignment(old_drawings, rows, frame)  # type: ignore[arg-type]
    if al.violations:
        return [f"O-struct mapped: O-scan could not map the before document: {al.violations[0]}"]
    dx = dy = 0.0
    if kind == "move":
        ux, uy = kw.get("delta", (0.0, 0.0))  # type: ignore[misc]
        a, b, c, d = frame[:4]  # type: ignore[index]
        dx, dy = ux * a + uy * c, ux * b + uy * d
    expected: list[Half] = []
    for di, drawing in enumerate(old_drawings):
        for half in drawing_halves(drawing):
            owner = _owner_rows(al.pairs[di], rows, str(half[0]))  # type: ignore[arg-type]
            if owner in selected:
                if kind == "delete":
                    continue
                coords = tuple(v + (dx if k % 2 == 0 else dy) for k, v in enumerate(half[3]))  # type: ignore[arg-type,union-attr]
                half = (*half[:3], coords)
            expected.append(half)
    got = [h for d in comparable_drawings(after) for h in drawing_halves(d)]
    why = _first_difference(expected, got, tolerant=kind == "move")
    return [f"O-struct mapped: {why}"] if why else []


o_struct_mapped.DOMAIN = frozenset({"PATHS"})  # type: ignore[attr-defined]


def moved_page(page: vfb.PageSpec, selected: Sequence[int], dx: float, dy: float) -> vfb.PageSpec:
    """The page with the selected paths translated by ``(dx, dy)`` in page space (a hand-made move twin).

    Only a stand-alone block path can be moved by changing its own ``cm`` operands; the change is the
    translation seen through the running CTM of the cumulative ``cm``s before it (a path under a 0.5
    scale needs twice the operand shift).
    """
    items = list(page.items)
    running = vfb.IDENT
    for idx, it in enumerate(items):
        if not isinstance(it, vfb.PathSpec):
            continue
        if it.state.shape == "cumulative":
            running = vfb._concat(it.ctm, running)
        if idx not in selected:
            continue
        if it.state.shape != "block" or it.state.block is not None:
            raise ValueError(f"item {idx} is not a stand-alone block path: its move is not a cm operand change")
        ra, rb, rc, rd = running[:4]
        det = ra * rd - rb * rc
        de = (dx * rd - dy * rc) / det
        df = (-dx * rb + dy * ra) / det
        a, b, c, d, e, f = it.ctm
        items[idx] = vfb.replace(it, ctm=(a, b, c, d, e + de, f + df))
    return vfb.replace(page, items=tuple(items))


# --------------------------------------------------------------------------- O-reopen


def save_roundtrip(data: bytes) -> bytes:
    """``save_as`` as the product does it for a secure save: garbage level 1, no clean, no deflate."""
    return _open(data).tobytes(garbage=1)


def _page_attributes(doc: fitz.Document) -> list[tuple[object, ...]]:
    out: list[tuple[object, ...]] = []
    for i in range(len(doc)):
        p = doc[i]
        out.append((p.rotation, tuple(p.mediabox), tuple(p.cropbox), tuple(p.rect), doc.xref_get_key(p.xref, "UserUnit")[1]))
    return out


def poppler_available() -> bool:
    return bool(os.environ.get("PDF_EDITOR_PDFTOPPM"))


# Poppler against MuPDF on the sample twin, 2x, per-pixel threshold 64, measured with the leg as written
# (``-cropbox``, ``-r`` scaled by /UserUnit): the share of differing pixels is 0.241 % at /Rotate 0,
# 0.263 % at 90, 0.266 % at 180, 0.350 % at 270, 0.405 % with an offset CropBox and 0.013 % at /UserUnit 2
# (anti-aliasing).  The same page with its 30 pt filled square missing differs on 2.57 %.  The limit sits
# between the two, 2.5x above the worst measured agreement.
PIXEL_THRESHOLD = 64
MAX_DISAGREE_FRACTION = 0.01


def renders_agree(a: np.ndarray, b: np.ndarray) -> bool:
    """Two renders agree when their sizes differ by at most two pixels and no more than
    ``MAX_DISAGREE_FRACTION`` of the common pixels differ by more than ``PIXEL_THRESHOLD`` in any channel."""
    if abs(a.shape[0] - b.shape[0]) > 2 or abs(a.shape[1] - b.shape[1]) > 2:
        return False
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    diff = np.abs(a[:h, :w, :3].astype(np.int16) - b[:h, :w, :3].astype(np.int16)).max(axis=2)
    return float((diff > PIXEL_THRESHOLD).mean()) <= MAX_DISAGREE_FRACTION


def _poppler_render(data: bytes) -> np.ndarray:
    """Poppler's 2x render of page 0 (``-cropbox``; ``-r`` scaled by /UserUnit, which Poppler ignores)."""
    exe = os.environ["PDF_EDITOR_PDFTOPPM"]
    doc = _open(data)
    uu_text = doc.xref_get_key(doc[0].xref, "UserUnit")[1]
    uu = float(uu_text) if uu_text not in ("null", "") else 1.0
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "page.pdf"
        pdf.write_bytes(data)
        cmd = [exe, "-r", str(144 * uu), "-cropbox", "-f", "1", "-l", "1", "-png", "-singlefile", str(pdf), str(Path(td) / "out")]
        proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)  # noqa: S603
        png = Path(td) / "out.png"
        if proc.returncode != 0 or not png.exists():
            raise RuntimeError(f"pdftoppm failed (exit {proc.returncode})")
        pix = fitz.Pixmap(str(png))
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()


def poppler_compare(poppler_doc: bytes, mupdf_doc: bytes) -> list[str]:
    """Poppler's render of ``poppler_doc`` against MuPDF's render of ``mupdf_doc``.  A no-op leg (``[]``)
    when ``PDF_EDITOR_PDFTOPPM`` is unset; a violation when it is set and Poppler fails."""
    if not poppler_available():
        return []
    try:
        theirs = _poppler_render(poppler_doc)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return [f"O-reopen: the Poppler leg could not run: {exc}"]
    ours = vo._render(_open(mupdf_doc)[0])
    return [] if renders_agree(theirs, ours) else ["O-reopen: Poppler's render of the saved file disagrees with MuPDF's"]


def poppler_agrees(saved: bytes) -> list[str]:
    return poppler_compare(saved, saved)


def o_reopen(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """``save_as`` round trip of the produced bytes, then O-struct and O-pixel against the pre-edit
    document, the page attributes unchanged, and (``PDF_EDITOR_PDFTOPPM`` set) Poppler's render agrees
    with MuPDF's.  ``save_class="A"`` (D16 class A) adds O-bytes across the save and needs the plan's
    ``ranges`` and ``envelopes``; class B pages are judged by structure and pixels only."""
    vo._require_delete(op)  # the move rows wait for card C1 (mapping-free O-struct and O-pixel have no move rule)
    saved = save_roundtrip(after)
    out: list[str] = []
    b, s = _open(before), _open(saved)
    if len(b) != len(s):
        return ["O-reopen: page count changed across the save"]
    if _page_attributes(b) != _page_attributes(s):
        out.append("O-reopen: a page attribute (rotation, box, user unit) changed")
    rest = {k: v for k, v in kw.items() if k != "save_class"}
    out += [m.replace("O-struct", "O-reopen struct") for m in vo.o_struct(op, before, saved, **rest)]
    out += [m.replace("O-pixel", "O-reopen pixel") for m in vo.o_pixel(op, before, saved, **rest)]
    if kw.get("save_class") == "A":
        if "ranges" not in kw or "envelopes" not in kw:
            raise ValueError("O-reopen class A needs the plan's ranges and envelopes (kw ranges=, envelopes=)")
        out += [m.replace("O-bytes", "O-reopen bytes") for m in vo.o_bytes(op, before, saved, **rest)]
    out += poppler_compare(saved, saved)
    return out


o_reopen.DOMAIN = frozenset({"PATHS", "PIXELS_OUTSIDE"})  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- O-vendor


def vendor_from_expected(scene: vfb.Scene, op: vfb.Op, *, jitter: float = 0.0) -> bytes:
    """A synthetic vendor document: the twin with page 0's content streams replaced by the INDEPENDENT
    emitter's post-edit streams (``vector_independent_expected``, not ``vfb.expected``).  ``jitter``
    shifts every x coordinate (a vendor that re-emits coordinates as float32)."""
    page = scene.pages[0]
    emitted = scene
    if jitter:
        items = tuple(
            vfb.replace(it, points=tuple((x + jitter, y) for x, y in it.points)) if isinstance(it, vfb.PathSpec) else it for it in page.items
        )
        emitted = vfb.replace(scene, pages=(vfb.replace(page, items=items), *scene.pages[1:]))
    streams = vie.expected_streams(emitted, op)
    doc = _open(vfb.build(scene))
    xrefs = doc[0].get_contents()
    if len(xrefs) != len(streams):
        raise ValueError("the independent emitter and the twin disagree on the number of content streams")
    for x, body in zip(xrefs, streams, strict=True):
        doc.update_stream(x, body, compress=False)
    return doc.tobytes(garbage=0)


def with_watermark(vendor: bytes, rect: tuple[float, float, float, float]) -> bytes:
    """The vendor's extra group: a filled square at ``rect`` (the frame of ``get_cdrawings``)."""
    doc = _open(vendor)
    page = doc[0]
    page.draw_rect(fitz.Rect(*rect), color=(1, 0, 0), fill=(1, 0, 0), width=1)
    return doc.tobytes(garbage=0)


def _inside(rect: Iterable[float], masks: Sequence[Sequence[float]]) -> bool:
    x0, y0, x1, y1 = (float(v) for v in rect)
    return any(m[0] <= x0 and m[1] <= y0 and x1 <= m[2] and y1 <= m[3] for m in masks)


def _records(data: bytes, masks: Sequence[Sequence[float]]) -> list[vm.Record]:
    out: list[vm.Record] = []
    for d in _open(data)[0].get_cdrawings():
        if masks and _inside(d["rect"], masks):
            continue
        out += [((h[0], h[1], h[2]), h[3]) for h in drawing_halves(d)]  # type: ignore[misc]
    return out


def _unmatched(a: Sequence[vm.Record], b: Sequence[vm.Record], tol: float) -> list[vm.Record]:
    """Records of ``a`` with no partner in ``b`` within ``tol`` on every coordinate (order free, each
    partner used once): the one non-greedy matcher of D23, ``vector_matching.unmatched``."""
    return vm.unmatched(a, b, tol)


def vendor_deleted_set(before: bytes, vendor: bytes, *, tol: float = 0.3, masks: Sequence[Sequence[float]] = ()) -> list[vm.Record]:
    """The vendor's deleted set: records of the before page with no counterpart in the vendor page,
    found by order-free geometric matching (0.3 pt)."""
    return _unmatched(_records(before, masks), _records(vendor, masks), tol)


def o_vendor(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Survivor multisets of the produced document against the vendor document (``vendor=``), after
    masking the vendor's watermark groups (``mask_rects=``, the frame of ``get_cdrawings``): equal
    survivor multisets (D23 matcher), the deleted sets agree at 0.3 pt, and the renders agree under a
    pixel tolerance (``max_diff_fraction``)."""
    vo._require_delete(op)
    vendor = kw.get("vendor")
    if not isinstance(vendor, bytes):
        raise ValueError("O-vendor needs the vendor document (kw vendor=)")
    masks = [tuple(m) for m in kw.get("mask_rects", ())]  # type: ignore[attr-defined]
    out: list[str] = []
    rb, ra, rv = _records(before, masks), _records(after, masks), _records(vendor, masks)
    if not vm.match_multisets(ra, rv):
        out.append(f"O-vendor: survivor multisets differ ({len(ra)} produced records, {len(rv)} vendor records)")
    deleted_v, deleted_n = _unmatched(rb, rv, 0.3), _unmatched(rb, ra, 0.3)
    if len(deleted_v) != len(deleted_n) or _unmatched(deleted_n, deleted_v, 0.3):
        out.append(f"O-vendor: the produced deleted set ({len(deleted_n)}) is not the vendor's ({len(deleted_v)})")
    pa, pv = _open(after)[0], _open(vendor)[0]
    ia, iv = vo._render(pa), vo._render(pv)
    if ia.shape != iv.shape:
        out.append("O-vendor: render sizes differ")
    else:
        keep = np.ones(ia.shape[:2], dtype=bool)
        for m in masks:
            r = fitz.Rect(*m) * pa.rotation_matrix
            r.normalize()
            keep[max(0, int(r.y0 * 2) - 1) : int(r.y1 * 2) + 2, max(0, int(r.x0 * 2) - 1) : int(r.x1 * 2) + 2] = False
        diff = np.abs(ia.astype(np.int16) - iv.astype(np.int16)).max(axis=2) > 32
        frac = float(diff[keep].mean()) if keep.any() else 0.0
        if frac > float(kw.get("max_diff_fraction", 5e-4)):  # type: ignore[arg-type]
            out.append(f"O-vendor: {frac:.4%} of the pixels differ from the vendor's render")
    return out


o_vendor.DOMAIN = frozenset({"PATHS"})  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- calibration hook


@functools.lru_cache(maxsize=256)
def _matrix_kw(scene: vfb.Scene, op: vfb.Op) -> tuple[tuple[str, object], ...]:
    page = scene.pages[0]
    selected = frozenset() if op.fate == "rollback" else vfb._selection(scene, op)
    return (
        ("rows", tuple(vir.rows_from_page(page))),
        ("frame", vir.frame_of(page)),
        ("selected_rows", vir.selected_rows(page, tuple(sorted(selected)))),
        ("vendor", vendor_from_expected(scene, op)),
    )


def kw_for_matrix(scene: vfb.Scene, op: vfb.Op) -> dict[str, object]:
    """Product-side input of the before/after oracles for one calibration cell, from the builder: rows
    derived from the scene, the page frame, the selected rows of the builder's EDITABLE selection (none on
    a rollback) and a vendor document built by the independent emitter."""
    return dict(_matrix_kw(scene, op))


BEFORE_AFTER: dict[str, Callable[..., list[str]]] = {
    "O-struct mapped": o_struct_mapped,
    "O-reopen": o_reopen,
    "O-vendor": o_vendor,
}
