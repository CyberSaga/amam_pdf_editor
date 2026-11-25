"""Card B1: an independent expected-stream emitter (handoff item 4).

``vector_fixture_builder.expected()`` derives the after-document with the same range/splice machinery
(``_plan`` / ``_cut``) the mutants are built from, so a bug in the cut is common to both sides.  This
module derives the post-delete content streams of page 0 from the fixture's *construction record*
only: every token is written once as a piece, tagged with the spans it belongs to (an item's path
span, a block's ``q ... Q`` span); the surviving stream is the concatenation of the pieces whose tags
are not deleted, with D7's one-trailing-whitespace absorption decided on neighbouring pieces.  No byte
offset is computed and no slice of an assembled stream is taken.

Independence rule (pinned by ``test_vector_independent_expected.py``): this module imports nothing
from ``test_scripts`` (no builder, no ``_cut``).  Scene objects are read by attribute only.  The
number format, the path constructors and the state tokens are re-implemented here on purpose, so a
formatting slip is caught by the differential test too.
"""

from __future__ import annotations

_WS = frozenset(b"\x00\t\n\x0c\r ")


def _fmt(v: float) -> str:
    text = ("%.6f" % v).rstrip("0").rstrip(".")  # noqa: UP031 - a different spelling from the builder
    return "0" if text in ("", "-0") else text


def _path_ops(item: object) -> list[str]:
    pts = item.points  # type: ignore[attr-defined]
    kind = item.kind  # type: ignore[attr-defined]
    if kind == "rect":
        (ax, ay), (bx, by) = pts[0], pts[1]
        return [_fmt(ax), _fmt(ay), _fmt(bx - ax), _fmt(by - ay), "re"]
    if kind not in ("line", "poly", "curve"):
        raise ValueError(f"unknown path kind {kind!r}")
    ops = [_fmt(pts[0][0]), _fmt(pts[0][1]), "m"]
    if kind == "curve":
        for x, y in pts[1:4]:
            ops += [_fmt(x), _fmt(y)]
        ops.append("c")
    else:
        for x, y in pts[1:]:
            ops += [_fmt(x), _fmt(y), "l"]
    return ops


def _paint_state(item: object) -> list[str]:
    st = item.state  # type: ignore[attr-defined]
    paint = item.paint  # type: ignore[attr-defined]
    ops: list[str] = []
    if st.gs:
        ops += ["/GS0", "gs"]
    if paint in ("S", "B"):
        ops += [_fmt(c) for c in st.stroke]
        ops += ["RG", _fmt(st.width), "w"]
        if st.dash:
            ops += ["[" + " ".join(_fmt(d) for d in st.dash) + "]", "0", "d"]
    if paint in ("f", "B"):
        ops += [_fmt(c) for c in st.fill]
        ops.append("rg")
    return ops


def _is_path(item: object) -> bool:
    return hasattr(item, "points")


def _deletable(item: object) -> bool:
    if not _is_path(item):
        return False
    st = item.state  # type: ignore[attr-defined]
    if item.paint == "n" or st.clip or st.oc:  # type: ignore[attr-defined]
        return False
    a, b, c, d = item.ctm[:4]  # type: ignore[attr-defined]
    return abs(a * d - b * c) > 1e-12


class _Piece:
    __slots__ = ("data", "spans", "skip_first")

    def __init__(self, data: bytes, spans: frozenset[tuple[str, int]]) -> None:
        self.data = data
        self.spans = spans
        self.skip_first = False


class _Stream:
    def __init__(self) -> None:
        self.pieces: list[_Piece] = []
        self.open: set[tuple[str, int]] = set()

    def _last_byte(self) -> int | None:
        for p in reversed(self.pieces):
            if p.data:
                return p.data[-1]
        return None

    def word(
        self,
        text: str | bytes,
        *,
        begin: tuple[tuple[str, int], ...] = (),
        end: tuple[tuple[str, int], ...] = (),
    ) -> None:
        raw = text.encode("ascii") if isinstance(text, str) else text
        last = self._last_byte()
        if last is not None and last not in _WS:
            self.pieces.append(_Piece(b" ", frozenset(self.open)))
        self.open.update(begin)
        self.pieces.append(_Piece(raw, frozenset(self.open)))
        self.open.difference_update(end)

    def newline(self) -> None:
        self.pieces.append(_Piece(b"\n", frozenset(self.open)))


def _groups(items: tuple[object, ...]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for i, it in enumerate(items):
        if _is_path(it) and it.state.block is not None:  # type: ignore[attr-defined]
            out.setdefault(it.state.block, []).append(i)  # type: ignore[attr-defined]
    return out


def _compose(items: tuple[object, ...], split_at: int | None) -> list[_Stream]:
    groups = _groups(items)
    streams = [_Stream()]
    for idx, it in enumerate(items):
        if split_at is not None and idx == split_at:
            streams.append(_Stream())
        s = streams[-1]
        if not _is_path(it):
            s.word(it.data)  # type: ignore[attr-defined]
            s.newline()
            continue
        st = it.state  # type: ignore[attr-defined]
        gid = st.block
        first_of_group = gid is not None and groups[gid][0] == idx
        last_of_group = gid is not None and groups[gid][-1] == idx
        if st.oc:
            for w in ("/OC", "/MC0", "BDC"):
                s.word(w)
        is_block = st.shape == "block"
        opens = is_block and (gid is None or first_of_group)
        if opens:
            # an ungrouped wrapper is a block of one (D17): it gets its own span tag, so it can be dropped whole
            s.word("q", begin=(("grp", gid if gid is not None else ("w", idx)),))
        if (opens or not is_block) and tuple(it.ctm) != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
            for v in it.ctm:
                s.word(_fmt(v))
            s.word("cm")
        for w in _paint_state(it):
            s.word(w)
        ops = _path_ops(it)
        item_span = ("item", idx)
        s.word(ops[0], begin=(item_span,))
        for w in ops[1:]:
            s.word(w)
        if it.paint == "n":
            s.word("W")
            s.word("n", end=(item_span,))
        else:
            s.word(it.paint, end=(item_span,))
        if is_block and (gid is None or last_of_group):
            s.word("Q", end=(("grp", gid if gid is not None else ("w", idx)),))
        if st.oc:
            s.word("EMC")
        s.newline()
    return streams


def _dropped_spans(items: tuple[object, ...], selected: tuple[int, ...]) -> set[tuple[str, object]]:
    groups = _groups(items)
    chosen = {i for i in selected if 0 <= i < len(items) and _deletable(items[i])}
    drop: set[tuple[str, object]] = set()
    for i in chosen:
        gid = items[i].state.block  # type: ignore[attr-defined]
        if gid is not None and all(m in chosen for m in groups[gid]):
            drop.add(("grp", gid))
        elif gid is None and items[i].state.shape == "block":  # type: ignore[attr-defined]
            drop.add(("grp", ("w", i)))  # a single-path q..Q wrapper is a block of one
        else:
            drop.add(("item", i))
    return drop


def _render(stream: _Stream, drop: set[tuple[str, object]]) -> bytes:
    pieces = stream.pieces
    for span in drop:
        hit = [k for k, p in enumerate(pieces) if span in p.spans]
        if not hit:
            continue
        before, after = hit[0], hit[-1] + 1
        starts_clean = before > 0 and pieces[before - 1].data[-1] in _WS  # D7: a stream start has no byte before the cut
        if starts_clean and after < len(pieces) and pieces[after].data[0] in _WS:
            pieces[after].skip_first = True
    out = bytearray()
    for p in pieces:
        if p.spans & drop:
            continue
        out += p.data[1:] if p.skip_first else p.data
    return bytes(out)


def expected_streams(scene: object, op: object) -> list[bytes]:
    """The content streams of page 0 after ``op`` (a delete) committed, or unchanged on rollback."""
    kind = op.kind  # type: ignore[attr-defined]
    if kind != "delete":
        raise ValueError(f"unsupported operation {kind!r}")
    if op.page != 0:  # type: ignore[attr-defined]
        raise ValueError("only page 0 is edited")
    page = scene.pages[0]  # type: ignore[attr-defined]
    items = tuple(page.items)
    streams = _compose(items, page.split_at)
    if op.fate == "rollback":  # type: ignore[attr-defined]
        return [_render(s, set()) for s in streams]
    drop = _dropped_spans(items, tuple(op.selected))  # type: ignore[attr-defined]
    return [_render(s, drop) for s in streams]
