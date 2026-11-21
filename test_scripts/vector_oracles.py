"""Oracles of design plan section 9 (card B1), plus the calibration engine.

Each oracle is ``oracle(op, before, after, **kw) -> list[str]`` (violations; empty = accept).  ``op``
is an operation object with a ``kind`` attribute or the kind string; an oracle raises
``ValueError`` on an operation it has no rule for (today only ``"delete"``; move rows arrive with
card C1).  ``before`` and ``after`` are PDF bytes.  Each oracle has a ``DOMAIN`` frozenset of fact
kinds (the facts of ``vector_fixture_builder`` it is responsible for).

Independent sources: MuPDF drawings and renders, ``lex_content_stream`` (the reference lexer; no
code shared with any scanner) and the runtime digest functions of ``model.vector_paths.commit_state``
(the same functions the product calls, so the oracle and the runtime check cannot drift).

Not built here (stated scope reading): O-scan, O-flat, O-reopen and O-vendor need the B2 index, a
saved file or the sample; O-struct's mapped form needs O-scan's mapping.
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.text_commit.pdf_lexer import TokenKind, lex_content_stream  # noqa: E402
from model.vector_paths.commit_state import WriteSet, digest_table, exact_dict_items, undeclared  # noqa: E402
from utils.pdf_object_source import xref_object_exact  # noqa: E402

FACT_KINDS = ("PATHS", "OTHER_PAGES", "OUTSIDE_BYTES", "OBJECTS", "PIXELS_OUTSIDE", "DICT")
_COMMIT_DICT_EXCLUDED = frozenset({"Length", "Filter", "DecodeParms", "DL"})
_CONSTRUCT = frozenset({b"m", b"l", b"c", b"v", b"y", b"h", b"re"})
_PAINT = frozenset({b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"})
_BLOCK_OPS = frozenset(
    {b"cm", b"w", b"J", b"j", b"M", b"d", b"ri", b"i", b"gs", b"g", b"G", b"rg", b"RG", b"k", b"K"}
    | {b"cs", b"CS", b"sc", b"SC", b"scn", b"SCN"}
) | _CONSTRUCT | _PAINT


def _kind(op: object) -> str:
    return op if isinstance(op, str) else str(getattr(op, "kind", ""))


def _fate(kw: dict[str, object]) -> str:
    return str(kw.get("fate", "commit"))


def _require_delete(op: object) -> None:
    if _kind(op) != "delete":
        raise ValueError(f"no oracle rule for operation {_kind(op)!r} (move rows arrive with card C1)")


def _domain(*kinds: str) -> Callable[[Callable[..., list[str]]], Callable[..., list[str]]]:
    def wrap(fn: Callable[..., list[str]]) -> Callable[..., list[str]]:
        fn.DOMAIN = frozenset(kinds)  # type: ignore[attr-defined]
        return fn

    return wrap


def _doc(data: bytes) -> fitz.Document:
    return fitz.open(stream=data, filetype="pdf")


# --------------------------------------------------------------------------- shared readers


def _norm(value: object) -> object:
    if isinstance(value, float):  # exact: a delete compares survivors exactly (design plan section 9)
        return 0.0 if value == 0 else value
    if isinstance(value, fitz.Point):
        return (_norm(value.x), _norm(value.y))
    if isinstance(value, fitz.Rect):
        return (_norm(value.x0), _norm(value.y0), _norm(value.x1), _norm(value.y1))
    if isinstance(value, fitz.Quad):
        return tuple(_norm(p) for p in (value.ul, value.ur, value.ll, value.lr))
    if isinstance(value, (list, tuple)):
        return tuple(_norm(v) for v in value)
    return value


def _records(page: fitz.Page) -> list[tuple[object, ...]]:
    """MuPDF drawings, a fill-and-stroke drawing split into a fill and a stroke record."""
    out: list[tuple[object, ...]] = []
    for d in page.get_drawings():
        items = _norm([tuple(it) for it in d["items"]])
        common = (items, d.get("lineCap"), d.get("lineJoin"), d.get("closePath"), d.get("even_odd"))
        kind = d.get("type")
        if kind in ("f", "fs"):
            out.append(("f", _norm(d.get("fill")), None, None, None, *common))
        if kind in ("s", "fs"):
            out.append(("s", None, _norm(d.get("color")), _norm(d.get("width")), _norm(d.get("dashes")), *common))
    return out


def _page_records(doc: fitz.Document, first: int = 0, last: int | None = None) -> list[list[tuple[object, ...]]]:
    return [_records(doc[i]) for i in range(first, len(doc) if last is None else last)]


def _selected_records(doc: fitz.Document, indices: Iterable[int]) -> list[tuple[object, ...]]:
    """Records of the selected drawings (indices in MuPDF's drawing order)."""
    drawings = doc[0].get_drawings()
    out: list[tuple[object, ...]] = []
    wanted = set(indices)
    for i, d in enumerate(drawings):
        if i in wanted:
            out.extend(_records_of_one(d))
    return out


def _records_of_one(d: dict) -> list[tuple[object, ...]]:
    items = _norm([tuple(it) for it in d["items"]])
    common = (items, d.get("lineCap"), d.get("lineJoin"), d.get("closePath"), d.get("even_odd"))
    out: list[tuple[object, ...]] = []
    kind = d.get("type")
    if kind in ("f", "fs"):
        out.append(("f", _norm(d.get("fill")), None, None, None, *common))
    if kind in ("s", "fs"):
        out.append(("s", None, _norm(d.get("color")), _norm(d.get("width")), _norm(d.get("dashes")), *common))
    return out


def _render(page: fitz.Page) -> np.ndarray:
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False, annots=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


def _is_subsequence(small: list[object], big: list[object]) -> bool:
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def _stream_xrefs(doc: fitz.Document) -> list[int]:
    return list(doc[0].get_contents())


def _exact_items(doc: fitz.Document, x: int) -> tuple[tuple[str, str], ...]:
    """A dictionary's byte-exact (key, printed value) pairs, key order ignored (escapes not decoded)."""
    text = xref_object_exact(doc, x)
    items = exact_dict_items(text)
    return tuple(sorted(items)) if items is not None else (("", " ".join(text.split())),)


def _prestate(doc: fitz.Document, *, storage: bool) -> tuple[object, ...]:
    """``vector_page_prestate`` normal form (storage=True) or the commit form (storage=False)."""
    px = doc.page_xref(0)
    contents = dict(_exact_items(doc, px)).get("/Contents") if storage else None
    parts = []
    for x in _stream_xrefs(doc):
        keys = {k: v for k, v in _exact_items(doc, x) if k != "/Length"}
        if not storage:
            keys = {k: v for k, v in keys.items() if k[1:] not in _COMMIT_DICT_EXCLUDED}
        decoded = hashlib.sha256(doc.xref_stream(x) or b"").hexdigest() if storage else None
        parts.append((tuple(sorted(keys.items())), decoded))
    return (contents, tuple(parts))


# --------------------------------------------------------------------------- O-struct


@_domain("PATHS")
def o_struct(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Mapping-free, full-page check for delete (design plan section 9, O-struct)."""
    _require_delete(op)
    b, a = _doc(before), _doc(after)
    old, new = _records(b[0]), _records(a[0])
    selected = Counter() if _fate(kw) == "rollback" else Counter(_selected_records(b, kw.get("selected_drawings", ())))  # type: ignore[arg-type]
    out: list[str] = []
    if not _is_subsequence(new, old):
        out.append("O-struct: the new list is not an order-preserving subsequence of the old one")
    diff = Counter(old) - Counter(new)
    extra = Counter(new) - Counter(old)
    if diff != selected or extra:
        out.append(
            f"O-struct: removed {sum(diff.values())} records (expected {sum(selected.values())}), "
            f"{sum(extra.values())} new or changed"
        )
    return out


# --------------------------------------------------------------------------- O-pixel


@_domain("PIXELS_OUTSIDE")
def o_pixel(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Pixels outside the changed region are identical (MuPDF's own rectangles, never the index)."""
    _require_delete(op)
    b, a = _doc(before), _doc(after)
    out: list[str] = []
    if len(b) != len(a):
        return ["O-pixel: page count changed"]
    rects: list[tuple[float, float, float, float]] = []
    if _fate(kw) != "rollback":
        drawings = b[0].get_drawings()
        for i in kw.get("selected_drawings", ()):  # type: ignore[attr-defined]
            d = drawings[i]
            # get_drawings is in the unrotated frame, the raster in the rotated one
            r = fitz.Rect(d["rect"]) * b[0].rotation_matrix
            r.normalize()
            g = (d.get("width") or 0.0) / 2.0 * 10.0 + 0.5
            rects.append((r.x0 - g, r.y0 - g, r.x1 + g, r.y1 + g))
    pb, pa = _render(b[0]), _render(a[0])
    if pb.shape != pa.shape:
        return ["O-pixel: page 0 render size changed"]
    mask = np.ones(pb.shape[:2], dtype=bool)
    for x0, y0, x1, y1 in rects:
        h, w = mask.shape  # clip both ends to the raster: a negative end index would wrap around
        r0, r1 = min(h, max(0, int(y0 * 2) - 1)), min(h, max(0, int(y1 * 2) + 2))
        c0, c1 = min(w, max(0, int(x0 * 2) - 1)), min(w, max(0, int(x1 * 2) + 2))
        mask[r0:r1, c0:c1] = False
    if (pb[mask] != pa[mask]).any():
        out.append("O-pixel: pixels changed outside the changed region on page 0")
    for i in range(1, len(b)):
        if not np.array_equal(_render(b[i]), _render(a[i])):
            out.append(f"O-pixel: page {i} changed")
    return out


# --------------------------------------------------------------------------- O-bytes


def _tokens(data: bytes) -> list[tuple[TokenKind, int, int]]:
    return [(t.kind, t.start, t.end) for t in lex_content_stream(data)]


_FREE = (TokenKind.WHITESPACE, TokenKind.COMMENT)


def _locality(
    ranges: dict[int, list[tuple[int, int]]], envelopes: dict[int, list[tuple[int, int, int, int, bool]]]
) -> list[str]:
    out: list[str] = []
    for sidx, rs in ranges.items():
        envs = sorted((e[0], e[1]) for e in envelopes.get(sidx, []))
        union: list[tuple[int, int]] = []
        for s, e in envs:
            if union and s <= union[-1][1]:
                union[-1] = (union[-1][0], max(union[-1][1], e))
            else:
                union.append((s, e))
        for s, e in rs:
            if not any(us <= s and e <= ue for us, ue in union):
                out.append(f"O-bytes: range ({s}, {e}) of stream {sidx} lies outside the selected paths' envelopes")
    for sidx, envs_list in envelopes.items():
        rs = ranges.get(sidx, [])
        for _es, _ee, os_, oe, _w in envs_list:
            if not any(s <= os_ and oe <= e for s, e in rs):
                out.append(f"O-bytes: a selected path's own bytes ({os_}, {oe}) of stream {sidx} are not covered")
    return out


def _end_open(data: bytes, toks: list[tuple[TokenKind, int, int]], start: bool) -> bool:
    state = start
    for k, a, z in toks:
        if k is TokenKind.OPERATOR:
            word = data[a:z]
            if word in _CONSTRUCT:
                state = True
            elif word in _PAINT or word == b"n":
                state = False
    return state


def _bytes_units(
    before: bytes, toks: list[tuple[TokenKind, int, int]], s: int, e: int, start_open: bool = False
) -> list[str]:
    """Checks 2, 4 and 5 for one range: alignment, units, open-path bit."""
    out: list[str] = []
    body = [(k, a, z) for k, a, z in toks if k not in _FREE]
    starts = {a for _k, a, _z in toks} | {len(before)}
    ends = {z for _k, _a, z in toks} | {0}
    if s not in starts or e not in ends:
        out.append(f"O-bytes: range ({s}, {e}) is not aligned to token boundaries")
        return out
    # open-path bit before and after every non-free token of the old stream
    open_before: dict[int, bool] = {}
    open_after: dict[int, bool] = {}
    state = start_open
    for k, a, z in body:
        open_before[a] = state
        word = before[a:z]
        if k is TokenKind.OPERATOR:
            if word in _CONSTRUCT:
                state = True
            elif word in _PAINT or word == b"n":
                state = False
        open_after[a] = state
    inside = [(k, a, z) for k, a, z in body if a >= s and z <= e]
    i = 0
    while i < len(inside):
        k, a, z = inside[i]
        word = before[a:z]
        if k is TokenKind.OPERATOR and word == b"q":
            if open_before[a]:
                out.append("O-bytes: a removed block starts with an open path")
            depth = 0
            j = i
            while j < len(inside):
                kj, aj, zj = inside[j]
                wj = before[aj:zj]
                if kj is TokenKind.OPERATOR:
                    if wj == b"q":
                        depth += 1
                        if depth > 1:
                            out.append("O-bytes: a removed block holds a nested q")
                    elif wj == b"Q":
                        depth -= 1
                        if depth == 0:
                            break
                    elif wj not in _BLOCK_OPS:
                        out.append(f"O-bytes: operator {wj!r} is not on the block allowlist")
                elif kj not in (TokenKind.NUMBER, TokenKind.NAME, TokenKind.ARRAY_OPEN, TokenKind.ARRAY_CLOSE):
                    out.append("O-bytes: a token kind outside the block allowlist")
                j += 1
            else:
                out.append("O-bytes: an unbalanced q in a removed range")
                break
            if open_before[inside[j][1]] or open_after[inside[j][1]]:
                out.append("O-bytes: a removed block ends with an open path")
            i = j + 1
            continue
        # a path span: operands and construction operators up to one paint operator
        if open_before[a]:
            out.append("O-bytes: a removed path span starts with an open path")
        j = i
        closed = False
        while j < len(inside):
            kj, aj, zj = inside[j]
            wj = before[aj:zj]
            if kj is TokenKind.OPERATOR:
                if wj in _PAINT:
                    closed = True
                    break
                if wj not in _CONSTRUCT:
                    out.append(f"O-bytes: operator {wj!r} inside a removed path span")
                    break
            elif kj is not TokenKind.NUMBER:
                out.append("O-bytes: a non-number operand inside a removed path span")
                break
            j += 1
        if not closed:
            out.append("O-bytes: a removed range does not end at a paint operator")
            break
        if open_after[inside[j][1]]:
            out.append("O-bytes: a removed path span ends with an open path")
        i = j + 1
    return out


@_domain("OUTSIDE_BYTES")
def o_bytes(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Checks 0 (locality), 1 to 5 of O-bytes for delete; ``ranges`` and ``envelopes`` from the plan."""
    _require_delete(op)
    b, a = _doc(before), _doc(after)
    ranges: dict[int, list[tuple[int, int]]] = kw.get("ranges", {})  # type: ignore[assignment]
    envelopes: dict[int, list[tuple[int, int, int, int, bool]]] = kw.get("envelopes", {})  # type: ignore[assignment]
    out = _locality(ranges, envelopes)
    bx, ax = _stream_xrefs(b), _stream_xrefs(a)
    for sidx in sorted(set(ranges) | set(envelopes)):
        if not 0 <= sidx < len(bx):
            out.append(f"O-bytes: range or envelope for nonexistent stream index {sidx}")
    for sidx, rs_ in ranges.items():
        if 0 <= sidx < len(bx):
            size = len(b.xref_stream(bx[sidx]) or b"")
            out += [f"O-bytes: range ({s_}, {e_}) outside stream {sidx} of {size} bytes" for s_, e_ in rs_ if not 0 <= s_ <= e_ <= size]
    if len(bx) != len(ax):
        return [*out, f"O-bytes: stream count changed {len(bx)} -> {len(ax)}"]
    carry = False  # a path under construction continues into the next content stream
    for sidx, (xb, xa) in enumerate(zip(bx, ax, strict=True)):
        old, new = b.xref_stream(xb) or b"", a.xref_stream(xa) or b""
        rs = sorted(ranges.get(sidx, []))
        pos = 0
        expected_new = bytearray()
        for s, e in rs:
            expected_new += old[pos:s]
            pos = e
        expected_new += old[pos:]
        if bytes(expected_new) != new:
            out.append(f"O-bytes: stream {sidx}: the old stream with the ranges cut out is not the new stream")
            continue
        toks = _tokens(old)
        for s, e in rs:
            out += _bytes_units(old, toks, s, e, carry)
        carry = _end_open(old, toks, carry)
        old_body = [
            (k, old[x:y]) for k, x, y in toks if k not in _FREE and not any(s <= x and y <= e for s, e in rs)
        ]
        new_toks = _tokens(new)
        new_body = [(k, new[x:y]) for k, x, y in new_toks if k not in _FREE]
        if any(k is TokenKind.MALFORMED for k, _w in new_body):
            out.append("O-bytes: the new stream lexes with a MALFORMED token")
        if old_body != new_body:
            out.append(f"O-bytes: stream {sidx}: token lists differ outside the ranges")
    return out


# --------------------------------------------------------------------------- O-dict


@_domain("DICT")
def o_dict(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Commit: stream dictionaries equal the old ones except Length/Filter/DecodeParms/DL.

    Rollback: the full ``vector_page_prestate`` normal form is unchanged.
    """
    _require_delete(op)
    b, a = _doc(before), _doc(after)
    storage = _fate(kw) == "rollback"
    pb, pa = _prestate(b, storage=storage), _prestate(a, storage=storage)
    if pb != pa:
        return [f"O-dict: page prestate differs ({'rollback' if storage else 'commit'} form)"]
    return []


# --------------------------------------------------------------------------- rule B


@_domain("OBJECTS", "OTHER_PAGES")
def rule_b(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Permitted-write diff over every object, and other pages' drawings (D23 rule B)."""
    _require_delete(op)
    b, a = _doc(before), _doc(after)
    if _fate(kw) == "rollback":
        ws = WriteSet(-1, frozenset(), frozenset())
    else:
        ws = WriteSet(
            int(kw.get("page_xref", -1)),  # type: ignore[call-overload]
            frozenset(kw.get("stream_xrefs", ())),  # type: ignore[call-overload]
            frozenset(kw.get("new_xrefs", ())),  # type: ignore[call-overload]
        )
    out = [f"rule B: object {x} changed outside the declared write set" for x in undeclared(digest_table(b), digest_table(a), ws)]
    if len(b) == len(a) and _page_records(b, 1) != _page_records(a, 1):
        out.append("rule B: another page's drawings changed")
    return out


# --------------------------------------------------------------------------- O-rebuild


@_domain(*FACT_KINDS)
def o_rebuild(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
    """Total oracle on twins: ``after`` equals the builder's expected document (design plan section 9)."""
    _require_delete(op)
    expected = kw.get("expected")
    if not isinstance(expected, bytes):
        raise ValueError("O-rebuild needs the builder's expected document (kw expected=)")
    e, a = _doc(expected), _doc(after)
    out: list[str] = []
    if len(e) != len(a):
        return ["O-rebuild: page count differs"]
    if _page_records(e) != _page_records(a):
        out.append("O-rebuild: drawings differ from the expected document")
    for i in range(len(e)):
        if not np.array_equal(_render(e[i]), _render(a[i])):
            out.append(f"O-rebuild: render of page {i} differs")
    bl = _doc(before).xref_length()
    for x in range(1, min(bl, e.xref_length(), a.xref_length())):
        if e.xref_is_stream(x) and (
            e.xref_get_key(x, "Subtype")[1] == "/Form" or e.xref_get_key(x, "PatternType")[0] != "null"
        ):
            if (e.xref_stream(x) or b"") != (a.xref_stream(x) or b""):
                out.append(f"O-rebuild: decoded bytes of form/pattern/appearance stream {x} differ")
    # locality and the ACTUAL cut: the supplied ranges are verified against the source bytes
    out += [m.replace("O-bytes", "O-rebuild envelope") for m in o_bytes(op, before, after, **kw)]
    rollback = _fate(kw) == "rollback"
    limit = bl
    et, at = digest_table(e), digest_table(a)
    edited = frozenset(kw.get("edited_xrefs", ())) if not rollback else frozenset()  # type: ignore[call-overload]
    declared_new = frozenset(kw.get("new_xrefs", ())) if not rollback else frozenset()  # type: ignore[call-overload]
    ws = WriteSet(-1 if rollback else int(kw.get("page_xref", -1)), edited, declared_new)  # type: ignore[call-overload]
    # a copy in one document and an in-place write in the other differ in the edited streams only;
    # objects created by a commit (xref >= the old length) are judged by drawings, pixels and bytes
    # every object the after-document has beyond the old length must be declared, whatever the expected has
    new_objects = {x for x in {*at.entries, *at.containers, *at.pages} if x >= limit}
    out += [f"O-rebuild: new object {x} is not in the declared write set" for x in sorted(new_objects - declared_new)]
    for x in undeclared(et, at, ws):
        if x >= limit and x in declared_new:
            continue
        out.append(f"O-rebuild: object {x} differs from the expected document")
    if _prestate(e, storage=rollback) != _prestate(a, storage=rollback):
        out.append("O-rebuild: stream dictionaries or /Contents differ from the expected document")
    return out


ORACLES: dict[str, Callable[..., list[str]]] = {
    "O-rebuild": o_rebuild,
    "O-struct": o_struct,
    "O-pixel": o_pixel,
    "O-bytes": o_bytes,
    "O-dict": o_dict,
    "rule B": rule_b,
}


# --------------------------------------------------------------------------- calibration


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    must_kill: Counter[str] = field(default_factory=Counter)  # oracle -> must-kill cells run
    must_pass: Counter[str] = field(default_factory=Counter)  # oracle -> must-pass inputs run
    violated: dict[str, int] = field(default_factory=dict)  # mutant -> cells where facts differ
    cells: int = 0

    @property
    def ok(self) -> bool:
        return not self.failures

    def equivalent_everywhere(self) -> list[str]:
        """Mutants no topology made violate any fact (the stop-rule report)."""
        return sorted(name for name, n in self.violated.items() if n == 0)


def calibrate(
    vfb: object,
    scenes: list[tuple[str, object]],
    ops_for: Callable[[object], list[object]],
    oracles: dict[str, Callable[..., list[str]]],
) -> Report:
    """Run every oracle on every must-kill cell and every must-pass input (pure; oracles injected).

    Must-kill is decided from facts only (``facts_diff`` of the mutant against the correct facts of
    its scenario, inside the oracle's DOMAIN); no oracle is run to decide it.
    """
    rep = Report()
    for name in oracles:
        rep.must_kill[name] += 0
        rep.must_pass[name] += 0
    for mname in vfb.MUTANT_NAMES:  # type: ignore[attr-defined]
        rep.violated.setdefault(mname, 0)
    for sname, scene in scenes:
        before = vfb.build(scene)  # type: ignore[attr-defined]
        for op in ops_for(scene):
            tag = f"{sname}/{op.selected}"  # type: ignore[attr-defined]
            for pname, pdata, pfacts in [
                *vfb.must_pass(scene, op),  # type: ignore[attr-defined]
                *vfb.must_pass(scene, vfb.replace(op, fate="rollback")),  # type: ignore[attr-defined]
            ]:
                rb = pfacts.context["fate"] == "rollback"
                pctx = dict(pfacts.context)
                pctx["expected"] = vfb.expected(scene, pctx["scenario_op"])[0]  # type: ignore[attr-defined]
                for oname, fn in oracles.items():
                    rep.must_pass[oname] += 1
                    viol = fn(pctx["scenario_op"], before, pdata, **{k: v for k, v in pctx.items() if k != "scenario_op"})
                    if viol:
                        rep.failures.append(f"{oname} rejects must-pass input {pname!r}{' (rollback)' if rb else ''} on {tag}: {viol[0]}")
            for mname, mdata, mfacts in vfb.mutants(scene, op):  # type: ignore[attr-defined]
                rep.cells += 1
                sop = vfb.scenario_of(mname, op)  # type: ignore[attr-defined]
                good = vfb.expected(scene, sop)[1]  # type: ignore[attr-defined]
                kinds = vfb.facts_diff(good, mfacts, vfb.FACT_KINDS)  # type: ignore[attr-defined]
                if not kinds:
                    continue
                rep.violated[mname] += 1
                if not any(set(kinds) & set(fn.DOMAIN) for fn in oracles.values()):  # type: ignore[attr-defined]
                    rep.failures.append(f"coverage gap: mutant {mname!r} violates {kinds} in no oracle's domain ({tag})")
                for oname, fn in oracles.items():
                    if not set(kinds) & set(fn.DOMAIN):  # type: ignore[attr-defined]
                        continue
                    rep.must_kill[oname] += 1
                    ctx = dict(mfacts.context)
                    ctx["expected"] = vfb.expected(scene, sop)[0]  # type: ignore[attr-defined]
                    if not fn(sop, before, mdata, **{k: v for k, v in ctx.items() if k != "scenario_op"}):
                        rep.failures.append(f"{oname} is blind to mutant {mname!r} on {tag} (facts differ in {kinds})")
    for oname, n in rep.must_kill.items():
        if n == 0:
            rep.failures.append(f"{oname} has an empty must-kill column: it judges nothing")
    return rep
