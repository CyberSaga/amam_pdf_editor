"""Grammar-based twin generator for card B1 (design plan section 9, "Fixtures for both").

``random_scene(seed)`` draws a ``vector_fixture_builder.Scene`` from a small grammar: stand-alone
``q ... Q`` blocks with a ``cm``, multi-paint blocks (members contiguous, one shared ``cm``), cumulative
bare paths whose ``cm`` accumulates, clips, ``/OC`` marked-content groups, text objects and comments,
fill / stroke / fill-and-stroke paints, a fill and a stroke of one path as two adjacent items (MuPDF
merges the pair into one drawing), dash arrays, ``gs`` states, an optional second content stream and
one of the builder's reference topologies (shared array, second-page share, form, pattern, appearance,
orphan, substring xrefs, indirect length; two streams come from the split).  ``random_ops(scene, seed)`` draws random delete selections
among the editable paths.  Everything is seeded and reproducible; coordinates sit on an integer grid
and every ``cm`` is a translation, a uniform scale or an exact 3-4-5 rotation, so the builder's six
decimal formatting is lossless.

Limit, stated: nested ``q`` and a path split across ``BDC``/``EMC`` are not expressible in the scene
model; the builder emits one block level per path group.
"""

from __future__ import annotations

import random

from test_scripts import vector_fixture_builder as vfb

MAX_ITEMS = 12
_PALETTE = (0.0, 0.25, 0.5, 0.75, 1.0)
_WIDTHS = (0.5, 1.0, 2.0, 3.0)
_DASHES = ((4.0, 2.0), (2.0, 2.0))
_TOPOLOGIES = (
    vfb.Topology(),
    vfb.Topology(),
    vfb.Topology(second_page_shares=True),
    vfb.Topology(shared_array=True),
    vfb.Topology(indirect_length=True),
    vfb.Topology(form=True),
    vfb.Topology(pattern=True),
    vfb.Topology(ap=True),
    vfb.Topology(orphan=True),
    vfb.Topology(substring_xrefs=True),
)


def _colour(rng: random.Random) -> tuple[float, float, float]:
    return (rng.choice(_PALETTE), rng.choice(_PALETTE), rng.choice(_PALETTE))


def _ctm(rng: random.Random, *, cumulative: bool = False, scale_ok: bool = True) -> vfb.Matrix:
    roll = rng.random()
    if roll < 0.45:
        return vfb.IDENT
    e, f = float(rng.randint(-20, 40)), float(rng.randint(-20, 40))
    if cumulative:
        e, f = float(rng.randint(2, 12)), float(rng.randint(2, 12))
        if scale_ok and roll > 0.9:
            return (0.5, 0.0, 0.0, 0.5, e, f)
        return (1.0, 0.0, 0.0, 1.0, e, f)
    if roll < 0.7:
        return (1.0, 0.0, 0.0, 1.0, e, f)
    if roll < 0.9:
        s = rng.choice((0.5, 2.0, 0.75))
        return (s, 0.0, 0.0, s, e, f)
    return (0.6, 0.8, -0.8, 0.6, e, f)


def _pts(rng: random.Random, kind: str) -> tuple[vfb.Point, ...]:
    def p() -> vfb.Point:
        return (float(rng.randint(5, 190)), float(rng.randint(5, 190)))

    if kind == "line":
        a = p()
        b = p()
        while b == a:
            b = p()
        return (a, b)
    if kind == "poly":
        return tuple(p() for _ in range(rng.randint(3, 4)))
    if kind == "rect":
        x0, y0 = float(rng.randint(5, 150)), float(rng.randint(5, 150))
        return ((x0, y0), (x0 + rng.randint(4, 40), y0 + rng.randint(4, 40)))
    return tuple(p() for _ in range(4))  # curve


def _state(rng: random.Random, paint: str, **extra: object) -> vfb.PathState:
    return vfb.PathState(
        stroke=_colour(rng),
        fill=_colour(rng),
        width=rng.choice(_WIDTHS),
        dash=rng.choice(_DASHES) if paint in ("S", "B") and rng.random() < 0.3 else (),
        gs=rng.random() < 0.15,
        **extra,  # type: ignore[arg-type]
    )


def _path(rng: random.Random, ctm: vfb.Matrix, *, shape: str = "block", block: int | None = None, oc: bool = False) -> vfb.PathSpec:
    kind = rng.choice(("line", "poly", "rect", "curve"))
    paint = rng.choices(("S", "f", "B"), weights=(5, 2, 2))[0]
    if kind == "line":
        paint = "S"  # a filled single segment draws nothing
    return vfb.PathSpec(kind, _pts(rng, kind), paint, ctm, _state(rng, paint, shape=shape, block=block, oc=oc))


def _pair(rng: random.Random) -> list[vfb.PathSpec]:
    """A fill and a stroke of ONE path as two bare path items (MuPDF merges a fill followed by a stroke into
    one ``fs`` drawing; a stroke followed by a fill stays two)."""
    kind = rng.choice(("poly", "rect", "curve"))  # a filled single segment draws nothing
    pts, ctm = _pts(rng, kind), _ctm(rng)
    state = _state(rng, "S")
    fill, stroke = vfb.PathSpec(kind, pts, "f", ctm, state), vfb.PathSpec(kind, pts, "S", ctm, state)
    return [fill, stroke] if rng.random() < 0.7 else [stroke, fill]


def random_scene(seed: int) -> vfb.Scene:
    """A seeded scene: 4 to ``MAX_ITEMS`` items on page 0, a one-line page 1, one topology."""
    rng = random.Random(f"scene/{seed}")
    target = rng.randint(6, MAX_ITEMS - 1)  # room for the one editable path a scene is guaranteed
    items: list[vfb.PathSpec | vfb.RawSpec] = []
    next_block = 1
    scaled = False
    while len(items) < target:
        kind = rng.choices(("path", "group", "cumulative", "clip", "oc", "text", "comment", "pair"), weights=(6, 2, 3, 1, 1, 1, 1, 2))[0]
        if kind == "path":
            items.append(_path(rng, _ctm(rng)))
        elif kind == "pair" and len(items) + 2 <= MAX_ITEMS:
            items.extend(_pair(rng))
        elif kind == "group" and len(items) + 3 <= MAX_ITEMS:
            ctm = _ctm(rng)
            for _ in range(rng.randint(2, 3)):
                items.append(_path(rng, ctm, block=next_block))
            next_block += 1
        elif kind == "cumulative":
            ctm = _ctm(rng, cumulative=True, scale_ok=not scaled)
            scaled = scaled or ctm[0] != 1.0
            items.append(_path(rng, ctm, shape="cumulative"))
        elif kind == "clip":
            x0, y0 = float(rng.randint(5, 120)), float(rng.randint(5, 120))
            items.append(vfb.PathSpec("rect", ((x0, y0), (x0 + 70.0, y0 + 60.0)), "n", vfb.IDENT, vfb.PathState(clip=True)))
        elif kind == "oc":
            items.append(_path(rng, vfb.IDENT, oc=True))
        elif kind == "text":
            items.append(vfb.RawSpec(f"BT /F1 12 Tf {rng.randint(5, 150)} {rng.randint(5, 150)} Td (0 0 m 9 9 l S Q) Tj ET".encode(), "text"))
        elif kind == "comment":
            items.append(vfb.RawSpec(b"% 0 0 m 9 9 l S", "comment"))
    if not any(vfb.is_editable(i) for i in items):
        items.insert(rng.randint(0, len(items)), _path(rng, vfb.IDENT))
    split = None
    if len(items) > 3 and rng.random() < 0.4:
        cand = rng.randint(2, len(items) - 1)
        a, b = items[cand - 1], items[cand]
        inside = isinstance(a, vfb.PathSpec) and isinstance(b, vfb.PathSpec) and b.state.block is not None and a.state.block == b.state.block
        split = None if inside else cand
    other = vfb.PageSpec((vfb.PathSpec("line", ((5.0, 5.0), (95.0, 95.0)), "S", vfb.IDENT, vfb.PathState(stroke=(0.3, 0.3, 0.9))),))
    page = vfb.PageSpec(tuple(items), split_at=split)
    return vfb.Scene((page, other), rng.choice(_TOPOLOGIES))


PERTURBATIONS = (
    "split_operand",  # a stream boundary falls between an operand and its operator
    "extra_operands",  # more operands than the operator takes
    "stray_w",  # a W with no path open, then a path that is not a clip
    "w_n",  # W n with no path open
    "tr_reset",  # text shown under a clip mode, Tr reset to 0 before ET
    "escaped_names",  # /OC and the device colour spaces spelled with #xx
    "dict_split",  # an inline property dictionary spans two streams
    "wrong_kind",  # a name or an array where a number is needed
    "cm_mid_path",  # a cm between construction operators
)
_RECORDS = (
    b"0 0 m 40 0 l 40 40 l S",
    b"10 10 60 40 re f",
    b"5 5 m 20 60 50 60 70 5 c B",
    b"90 90 m 150 120 l S",
    b"100 20 40 40 re S",
    b"20 100 m 60 100 l 60 140 l h f",
)


def perturbed_streams(seed: int) -> tuple[list[bytes], str]:
    """``(streams, perturbation)``: a few valid path records with ONE malformed or boundary-hostile perturbation.

    Page-space expectations are not recorded: the scanner must either refuse the page or agree with MuPDF
    (O-scan) and keep every survivor intact when an EDITABLE row is cut out the D7 way.
    """
    rng = random.Random(f"perturb/{seed}")
    kind = PERTURBATIONS[seed % len(PERTURBATIONS)]
    recs = [rng.choice(_RECORDS) for _ in range(rng.randint(3, 6))]
    at = rng.randint(0, len(recs))

    def join(parts: list[bytes]) -> bytes:
        return b" ".join(parts) + b" "

    if kind == "split_operand":
        toks = join(recs).split()
        k = rng.randint(1, len(toks) - 1)
        return [b" ".join(toks[:k]), b" " + b" ".join(toks[k:]) + b" "], kind
    if kind == "extra_operands":
        i = rng.randrange(len(recs))
        recs[i] = b"7 " + recs[i]
        return [join(recs)], kind
    if kind == "stray_w":
        recs.insert(at, b"W")
        return [join(recs)], kind
    if kind == "w_n":
        recs.insert(at, rng.choice((b"W n", b"W* n", b"q W n Q")))
        return [join(recs)], kind
    if kind == "tr_reset":
        recs.insert(at, b"BT 7 Tr (x) Tj 0 Tr ET")
        return [join(recs)], kind
    if kind == "escaped_names":
        recs.insert(at, b"/O#43 /L BDC")
        recs.insert(min(at + 2, len(recs)), b"EMC")
        recs.insert(0, b"/Device#52GB cs")
        return [join(recs)], kind
    if kind == "dict_split":
        head, tail = join(recs[:at]), join(recs[at:])
        return [head + b"/OC <</A (x) /B <41>", b" >> BDC " + tail + b"EMC"], kind
    if kind == "wrong_kind":
        i = rng.randrange(len(recs))
        recs[i] = rng.choice((b"/N", b"[1 2]")) + b" " + recs[i]
        return [join(recs)], kind
    recs.insert(at + 1 if at < len(recs) else at, b"1 0 0 1 3 4 cm")  # cm_mid_path
    return [b" ".join(recs[:2]) + b" 0 0 m 20 0 l 1 0 0 1 10 10 cm 20 20 l S " + b" ".join(recs[2:])], kind


def random_ops(scene: vfb.Scene, seed: int, count: int = 2) -> list[vfb.Op]:
    """``count`` distinct random delete selections among the editable paths of page 0."""
    rng = random.Random(f"ops/{seed}")
    editable = [i for i, it in enumerate(scene.pages[0].items) if vfb.is_editable(it)]
    out: list[vfb.Op] = []
    for _ in range(count * 4):
        sel = tuple(sorted(rng.sample(editable, rng.randint(1, min(3, len(editable))))))
        op = vfb.Op("delete", 0, sel)
        if op not in out:
            out.append(op)
        if len(out) == count:
            break
    return out
