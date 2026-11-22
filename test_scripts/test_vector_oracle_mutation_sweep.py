"""Automated mutation-kill check for the B1 oracles (class check; Astra rounds 1 to 3).

Calibration by named mutants cannot prove oracle strength: every review round found another false
accept.  This sweep takes the CORRECT after-document of each scene and selection, applies seeded
single-site mutations to it (tokens of every object, stream bytes, added and dropped objects, trailer
and page keys, rendered-state tokens), decides semantic equivalence independently of the oracles and
of ``commit_state`` and STRICTER than every oracle (byte-exact printed tokens: names with their ``#xx``
escapes, strings and hex strings verbatim, stream storage keys and raw bytes; only dictionary key order
and insignificant whitespace are normalised) and requires O-rebuild, the total oracle, to reject every
mutant that is not equivalent.  Every oracle runs on every mutant and the rejecters are recorded; each
oracle must reject at least ``MIN_KILLS`` mutants of its own DOMAIN.  A second family mutates the
metadata handed to the oracles (ranges, envelopes, stream indices, write set) while the bytes stay
correct.  Survivors fail the run.  Only the allowlist (a class with a reason) is an escape.
"""

from __future__ import annotations

import random
import re
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import fitz
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_oracles as vo  # noqa: E402
from utils.pdf_object_source import xref_object_exact  # noqa: E402

TOKENS_PER_CASE = 120
SELECTIONS = ((1, 2), (3,))
_STORAGE_KEYS = frozenset({"Length", "Filter", "DecodeParms", "DL"})
_TOK = re.compile(r"\((?:\\.|[^\\()])*\)|<<|>>|\[|\]|/[^\s/<>\[\]()%]*|[^\s/<>\[\]()%]+")
_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

# Classes of mutation proven equivalent for every oracle's stated domain.  Each entry: tag -> reason.
ALLOWLIST: dict[str, str] = {
    "contents-spelling": (
        "a different spelling of the edited page's /Contents reference that resolves to the same streams "
        "(for example a changed generation number): a commit declares the /Contents entry as writable"
    ),
    "storage-declared": (
        "a storage-only change (Length, Filter, DecodeParms, DL) of a stream the edit DECLARED, decoded "
        "bytes unchanged: D20's post-check allows exactly these keys to differ after a commit"
    ),
}
# (oracle, mutation tag) -> reason: a mutation class an oracle is NOT required to reject although its
# DOMAIN meets the violated fact.  Every entry is a known equivalent of that oracle's own contract.
MISSED_ALLOWLIST: dict[tuple[str, str], str] = {
    ("O-vendor", "token:num1e-6"): (
        "the vendor leg compares drawings within the D23 vendor tolerance of 0.3 pt (vector_matching.unmatched), "
        "so a 1e-6 pt change is below the oracle's own resolution by design"
    ),
}
MIN_KILLS = 5
ORACLE_ORDER = ("O-rebuild", "O-bytes", "rule B", "O-dict", "O-struct", "O-pixel")
# fact kinds a mutation tag can violate (used for the per-oracle DOMAIN table)
TAG_KINDS: dict[str, frozenset[str]] = {
    "pixel": frozenset({"PATHS", "PIXELS_OUTSIDE", "OUTSIDE_BYTES"}),
    "stream:byte": frozenset({"PATHS", "OUTSIDE_BYTES", "OBJECTS", "PIXELS_OUTSIDE"}),
    "stream:move": frozenset({"PATHS", "OUTSIDE_BYTES", "OBJECTS", "PIXELS_OUTSIDE"}),
    "meta:ranges": frozenset({"OUTSIDE_BYTES"}),
    "meta:envelope": frozenset({"OUTSIDE_BYTES"}),
    "meta:writeset": frozenset({"OBJECTS"}),
}
DEFAULT_KINDS = frozenset({"OBJECTS", "DICT", "OTHER_PAGES"})


def _kinds(tag: str) -> frozenset[str]:
    for prefix, kinds in TAG_KINDS.items():
        if tag.startswith(prefix):
            return kinds
    return DEFAULT_KINDS



_CANON_TOKEN = re.compile(r"<<|>>|<[0-9A-Fa-f\s]*>|\((?:\\.|[^\\()])*\)|/[^\s/<>\[\]()%]*|\[|\]|[^\s/<>\[\]()%]+")


def _pairs(text: str) -> tuple[tuple[str, str], ...] | None:
    """Top-level (key, value) token strings of a printed dictionary, byte-exact, sorted by key."""
    toks = _CANON_TOKEN.findall(text)
    if not toks or toks[0] != "<<" or toks[-1] != ">>":
        return None
    out: list[tuple[str, str]] = []
    i, last = 1, len(toks) - 1
    while i < last:
        key = toks[i]
        i += 1
        value: list[str] = []
        depth = 0
        while i < last:
            t = toks[i]
            value.append(t)
            i += 1
            if t in ("<<", "["):
                depth += 1
            elif t in (">>", "]"):
                depth -= 1
            if depth == 0:
                if t.isdigit() and i + 1 < last + 1 and toks[i : i + 2] and toks[i].isdigit() and toks[i + 1 : i + 2] == ["R"]:
                    value += [toks[i], "R"]
                    i += 2
                break
        out.append((key, " ".join(value)))
    return tuple(sorted(out))


def _canon(doc: fitz.Document, declared: frozenset[int] = frozenset()) -> tuple[object, ...]:
    """Strict canonical form: printed tokens byte-exact (no escape decoding), raw stream bytes and
    storage keys included.  For a stream in ``declared`` (a stream the edit may rewrite) only the
    decoded bytes and the non-storage keys count, as the commit post-check allows."""
    out: list[object] = [len(doc)]
    for x in range(1, doc.xref_length()):
        try:
            text = xref_object_exact(doc, x)
            items = _pairs(text)
            stream = doc.xref_is_stream(x)
            body: object = items if items is not None else " ".join(text.split())
            if stream and x in declared and items is not None:
                body = tuple(kv for kv in items if kv[0][1:] not in _STORAGE_KEYS)
            if stream and x in declared:
                payload: object = doc.xref_stream(x)
            elif stream:
                payload = (doc.xref_stream_raw(x), doc.xref_stream(x))
            else:
                payload = None
            out.append((x, body, payload))
        except Exception:  # noqa: BLE001 - an unreadable object is part of the canonical form
            out.append((x, "unreadable"))
    trailer = _pairs(xref_object_exact(doc, -1)) or ()
    out.append(tuple(kv for kv in trailer if kv[0] not in ("/ID", "/Size")))
    return tuple(out)


def _same_but_contents_spelling(base: fitz.Document, mutant: fitz.Document) -> bool:
    """Only the printed /Contents value of page 0 differs and both resolve to the same streams."""

    def without_contents(doc: fitz.Document) -> tuple[object, ...]:
        px = doc.page_xref(0)
        items = _pairs(xref_object_exact(doc, px)) or ()
        rest = _canon(doc)
        return (tuple(kv for kv in items if kv[0] != "/Contents"), [e for e in rest if not (isinstance(e, tuple) and e[:1] == (px,))])

    return without_contents(base) == without_contents(mutant) and base[0].get_contents() == mutant[0].get_contents()


def _rewrite_object(doc: fitz.Document, x: int, text: str) -> None:
    stream = doc.xref_is_stream(x)
    raw = doc.xref_stream_raw(x) if stream else None
    flt = re.search(r"/Filter\s*(/\w+|\[[^\]]*\])", text)
    doc.update_object(x, text)
    if raw is not None:
        doc.update_stream(x, raw, compress=False, new=True)
        if flt:
            doc.xref_set_key(x, "Filter", flt.group(1))


def _token_mutations(doc: fitz.Document, rng: random.Random, n: int) -> Iterator[tuple[str, str, bytes]]:
    sites = []
    for x in range(1, doc.xref_length()):
        try:
            text = xref_object_exact(doc, x)  # escapes kept, so #xx names are mutated too
        except Exception:  # noqa: BLE001
            continue
        for m in _TOK.finditer(text):
            sites.append((x, text, m))
    rng.shuffle(sites)
    made = 0
    for x, text, m in sites:
        if made >= n:
            break
        tok = m.group(0)
        if tok in ("<<", ">>", "[", "]"):
            continue
        options: list[tuple[str, str]] = []
        if _NUMBER.match(tok):
            v = float(tok)
            options += [("num1e-6", f"{v + 1e-6:.7f}"), ("num1", f"{v + 1:.7f}")]
        if tok.startswith("/") and len(tok) > 1:
            options.append(("name2str", f"({tok[1:]})"))
        if tok.startswith("(") and tok.endswith(")") and " " not in tok:
            options.append(("str2name", "/" + tok[1:-1]))
        options += [("del", ""), ("dup", tok + " " + tok)]
        options.append(("type", rng.choice(["7", "/Z", "(z)", "[1]", "true", "1 0 R"])))
        tag, repl = rng.choice(options)
        new_text = text[: m.start()] + repl + text[m.end() :]
        d = fitz.open(stream=_BASE_BYTES[0], filetype="pdf")
        try:
            _rewrite_object(d, x, new_text)
            data = d.tobytes(garbage=0)
        except Exception:  # noqa: BLE001 - not a serialisable mutant
            continue
        made += 1
        yield f"token:{tag}", f"obj {x}: {tok!r} -> {repl!r}", data


_BASE_BYTES: list[bytes] = [b""]


def _other_mutations(good: bytes, rng: random.Random) -> Iterator[tuple[str, str, bytes]]:
    def fresh() -> fitz.Document:
        return fitz.open(stream=good, filetype="pdf")

    streams = [x for x in range(1, fresh().xref_length()) if fresh().xref_is_stream(x)]
    d = fresh()
    x = rng.choice(streams)
    body = bytearray(d.xref_stream(x) or b"x")
    pos = rng.randrange(len(body))
    body[pos] = body[pos] + 1 if 32 <= body[pos] < 125 else 48
    d.update_stream(x, bytes(body), compress=False)
    yield "stream:byte", f"stream {x} byte {pos}", d.tobytes(garbage=0)
    d = fresh()
    a, b = rng.sample(streams, 2)
    da, db = d.xref_stream(a) or b"", d.xref_stream(b) or b""
    if da:
        d.update_stream(a, da[:-1], compress=False)
        d.update_stream(b, da[-1:] + db, compress=False)
        yield "stream:move", f"last byte of {a} to start of {b}", d.tobytes(garbage=0)
    for _ in range(2):  # recompress a stream whose decoded bytes stay the same
        d = fresh()
        x = rng.choice(streams)
        d.update_stream(x, d.xref_stream(x) or b"", compress=True)
        yield "storage:recompress", f"stream {x} stored again", d.tobytes(garbage=0)
    d = fresh()
    n = d.get_new_xref()
    d.update_object(n, "<< /Junk 123 >>")
    yield "obj:add", "new object /Junk 123", d.tobytes(garbage=0)
    d = fresh()
    victim = rng.choice([x for x in range(1, d.xref_length()) if x not in (1, 2)])
    d.update_object(victim, "null")
    yield "obj:drop", f"object {victim} -> null", d.tobytes(garbage=0)
    d = fresh()
    d.xref_set_key(-1, "Marker", "(x)")
    yield "trailer", "trailer /Marker", d.tobytes(garbage=0)
    d = fresh()
    d.xref_set_key(d.page_xref(0), "Rotate", "90")
    yield "page:rotate", "/Rotate 90", d.tobytes(garbage=0)
    d = fresh()
    d.xref_set_key(d.page_xref(0), "CropBox", "[1 1 190 190]")
    yield "page:box", "CropBox", d.tobytes(garbage=0)
    # rendered-state tokens of the edited page's content
    for tag, pattern, repl in (
        ("pixel:colour", r"(\d(?:\.\d+)?) (\d(?:\.\d+)?) (\d(?:\.\d+)?) (RG|rg)", r"1 1 0 \4"),
        ("pixel:width", r"(\d+(?:\.\d+)?) w\b", r"7 w"),
    ):
        d = fresh()
        for cx in d[0].get_contents():
            text = (d.xref_stream(cx) or b"").decode("latin-1")
            new, count = re.subn(pattern, repl, text, count=1)
            if count:
                d.update_stream(cx, new.encode("latin-1"), compress=False)
                yield tag, f"{tag} in stream {cx}", d.tobytes(garbage=0)
                break
    d = fresh()
    cx = d[0].get_contents()[0]
    d.update_stream(cx, b"0 0 5 5 re W n " + (d.xref_stream(cx) or b""), compress=False)
    yield "pixel:clip", "clip at the start of the first content stream", d.tobytes(garbage=0)


def _drawings_of(doc: fitz.Document, first: int, last: int | None = None) -> list[list[tuple[object, ...]]]:
    """An independent, deliberately plain reader of what MuPDF draws per page (B2): one tuple per
    ``get_drawings`` entry with its type, paints, width and path items (numbers rounded to 3 places).
    It shares no code with ``vector_oracles._records`` (the reader the oracles and the O-rebuild
    rule use), so the PATHS and OTHER_PAGES facts are not derived by the code under test."""

    def num(value: object) -> object:
        if isinstance(value, float):
            return round(value, 3)
        if isinstance(value, (fitz.Point, fitz.Rect, fitz.Quad)):
            return tuple(round(float(v), 3) for v in (value if isinstance(value, fitz.Rect) else _flat(value)))
        if isinstance(value, (tuple, list)):
            return tuple(num(v) for v in value)
        return value

    pages = []
    stop = len(doc) if last is None else last
    for index in range(first, stop):
        pages.append(
            [
                (
                    d.get("type"),
                    num(d.get("fill")),
                    num(d.get("color")),
                    num(d.get("width")),
                    bool(d.get("even_odd")),
                    num(d.get("fill_opacity")),
                    num(d.get("stroke_opacity")),
                    d.get("dashes"),
                    num(d.get("lineCap")),
                    num(d.get("lineJoin")),
                    d.get("closePath"),
                    tuple(num(item) for item in d.get("items", ())),
                )
                for d in doc[index].get_drawings()
            ]
        )
    return pages


def _flat(shape: object) -> list[float]:
    if isinstance(shape, fitz.Point):
        return [shape.x, shape.y]
    return [c for p in (shape.ul, shape.ur, shape.ll, shape.lr) for c in (p.x, p.y)]  # type: ignore[attr-defined]


class _BaseFacts:
    """What the CORRECT after-document looks like, read once per cell, so each mutant's violated fact
    kinds can be derived by comparison, with no oracle run (Astra B2, the facts-based Rule A of
    ``vector_oracles.calibrate``).  The comparisons use MuPDF, the byte-exact canonical form of this
    module, an independent drawing reader (``_drawings_of``) and the shared render reader, never an
    oracle function.  PATHS and OTHER_PAGES use ``_drawings_of``, not ``vo._page_records``, the code
    the O-rebuild rule and the oracles read paths with."""

    def __init__(self, doc: fitz.Document, before: bytes, ctx: dict) -> None:
        self.doc = doc
        self.before = before
        self.selected = tuple(ctx.get("selected_drawings", ()))
        self.page_xref = int(ctx.get("page_xref", -1))
        self.stream_xrefs = frozenset(ctx.get("stream_xrefs", ()))
        self.new_xrefs = frozenset(ctx.get("new_xrefs", ()))
        canon = _canon(doc)
        self.entries = {e[0]: e for e in canon[1:-1] if isinstance(e, tuple) and e and isinstance(e[0], int)}
        self.trailer = canon[-1]
        self.contents = list(doc[0].get_contents())
        self.decoded = [doc.xref_stream(x) or b"" for x in self.contents]
        self.dicts = [self._content_dict(doc, x) for x in self.contents]
        self.records = _drawings_of(doc, 0, 1)
        self.other_records = _drawings_of(doc, 1)
        self.render = vo._render(doc[0])
        self.other_render = [vo._render(doc[i]) for i in range(1, len(doc))]
        self.mask = vo._before_mask(before, self.selected, False)

    @staticmethod
    def _content_dict(doc: fitz.Document, x: int) -> tuple[tuple[str, str], ...]:
        pairs = _pairs(xref_object_exact(doc, x)) or ()
        return tuple(kv for kv in pairs if kv[0][1:] not in _STORAGE_KEYS)

    @staticmethod
    def _body_without_length(entry: tuple) -> tuple:
        x, body, payload = entry[0], entry[1], entry[2] if len(entry) > 2 else None
        if payload is not None and isinstance(body, tuple):  # a stream: the digest strips the top-level /Length
            body = tuple(kv for kv in body if kv[0] != "/Length")
        return (x, body, payload)

    def _page_keys(self, entry: tuple | None) -> object:
        if entry is None or not isinstance(entry[1], tuple):
            return entry
        return tuple(kv for kv in entry[1] if kv[0] not in ("/Contents", "/Length"))

    def violated(self, mdoc: fitz.Document) -> frozenset[str]:
        """The fact kinds in which ``mdoc`` differs from the correct after-document (in the sense of the
        stated write set), independently of every oracle."""
        kinds: set[str] = set()
        mcanon = _canon(mdoc)
        mentries = {e[0]: e for e in mcanon[1:-1] if isinstance(e, tuple) and e and isinstance(e[0], int)}
        if mcanon[-1] != self.trailer:
            kinds.add("OBJECTS")
        for x in set(self.entries) | set(mentries):
            b, m = self.entries.get(x), mentries.get(x)
            if b == m:
                continue
            if b is not None and m is not None and self._body_without_length(b) == self._body_without_length(m):
                continue
            if x in self.new_xrefs or (x in self.stream_xrefs and b is not None and m is not None):
                continue
            if x == self.page_xref and self._page_keys(b) == self._page_keys(m):
                continue
            kinds.add("OBJECTS")
            break
        mcontents = list(mdoc[0].get_contents())
        mdecoded = [mdoc.xref_stream(x) or b"" for x in mcontents]
        if len(mcontents) != len(self.contents) or mdecoded != self.decoded:
            kinds.add("OUTSIDE_BYTES")
        if len(mcontents) != len(self.contents) or [self._content_dict(mdoc, x) for x in mcontents] != self.dicts:
            kinds.add("DICT")
        if _drawings_of(mdoc, 0, 1) != self.records:
            kinds.add("PATHS")
        if len(mdoc) != len(self.doc) or _drawings_of(mdoc, 1) != self.other_records:
            kinds.add("OTHER_PAGES")
        pm = vo._render(mdoc[0])
        if len(mdoc) != len(self.doc) or pm.shape != self.render.shape:
            kinds.add("PIXELS_OUTSIDE")
        else:
            if (pm[self.mask] != self.render[self.mask]).any() or any(
                not np.array_equal(vo._render(mdoc[i + 1]), r) for i, r in enumerate(self.other_render)
            ):
                kinds.add("PIXELS_OUTSIDE")
        return frozenset(kinds)


def _judge(oracles: dict, before: bytes, mutant: bytes, ctx: dict, order: tuple[str, ...] = ORACLE_ORDER) -> set[str]:
    """Names of the oracles that reject ``mutant``.  Every oracle runs (none is hidden behind another)."""
    rejected: set[str] = set()
    for name in order:
        try:
            if oracles[name]("delete", before, mutant, **ctx):
                rejected.add(name)
        except Exception:  # noqa: BLE001 - an oracle that cannot read the mutant cannot accept it
            RAISED[0] += 1
            rejected.add(name)
    return rejected


RAISED: list[int] = [0]


def _metadata_mutants(ctx: dict) -> Iterator[tuple[str, str, dict, tuple[str, ...]]]:
    """Wrong metadata with correct bytes: (tag, description, mutated ctx, oracles that must reject)."""
    ranges, envs = ctx["ranges"], ctx["envelopes"]
    first = sorted(ranges)[0]
    yield (
        "meta:ranges",
        "range and envelope for the nonexistent stream index 999",
        {**ctx, "ranges": {**ranges, 999: [(0, 1)]}, "envelopes": {**envs, 999: [(0, 1, 0, 1, False)]}},
        ("O-bytes", "O-rebuild"),
    )
    s0, e0 = ranges[first][0]
    yield (
        "meta:ranges",
        "first range shifted by one byte",
        {**ctx, "ranges": {**ranges, first: [(s0 + 1, e0 + 1), *ranges[first][1:]]}},
        ("O-bytes", "O-rebuild"),
    )
    yield (
        "meta:ranges",
        "the edited stream's ranges dropped",
        {**ctx, "ranges": {k: v for k, v in ranges.items() if k != first}},
        ("O-bytes", "O-rebuild"),
    )
    yield (
        "meta:ranges",
        "a range beyond the end of the stream",
        {**ctx, "ranges": {**ranges, first: [(0, 10**9)]}},
        ("O-bytes", "O-rebuild"),
    )
    yield from _envelope_widening_mutants(ctx)
    if ctx["stream_xrefs"]:
        yield "meta:writeset", "declared stream xrefs cleared", {**ctx, "stream_xrefs": frozenset()}, ("rule B",)
    if ctx["new_xrefs"]:
        yield "meta:writeset", "declared new xrefs cleared", {**ctx, "new_xrefs": frozenset()}, ("rule B", "O-rebuild")
        yield "meta:writeset", "edited page's /Contents not declared", {**ctx, "page_xref": -1}, ("rule B",)


def _envelope_widening_mutants(ctx: dict) -> Iterator[tuple[str, str, dict, tuple[str, ...]]]:
    """An over-wide selection envelope with otherwise correct cuts: the ranges and the bytes stay right,
    one envelope grows beyond what its path (plus one adjoining whitespace byte) can justify."""
    envs = ctx["envelopes"]
    for sidx in sorted(envs):
        for k, (es, ee, os_, oe, whole) in enumerate(envs[sidx]):
            for label, (nes, nee) in (
                ("start by 1", (es - 1, ee)),
                ("end by 1", (es, ee + 1)),
                ("start by 2 (inside a preceding two-character operator)", (es - 2, ee)),
                ("start by 2 and end by 2", (es - 2, ee + 2)),
                ("both sides by 3", (es - 3, ee + 3)),
                ("start to the stream start", (0, ee)),
                ("end far beyond the path", (es, ee + 40)),
            ):
                if nes < 0 or (nes, nee) == (es, ee):
                    continue
                widened = [*envs[sidx][:k], (nes, nee, os_, oe, whole), *envs[sidx][k + 1 :]]
                yield (
                    "meta:envelope",
                    f"stream {sidx} envelope {k} ({es}, {ee}) widened: {label}",
                    {**ctx, "envelopes": {**envs, sidx: widened}},
                    ("O-bytes", "O-rebuild"),
                )


def run_sweep(
    seed_tag: str = "sweep",
    *,
    scenes: list[tuple[str, vfb.Scene]] | None = None,
    selections: tuple[tuple[int, ...], ...] | Callable[[vfb.Scene], tuple[tuple[int, ...], ...]] | None = None,
    tokens: int | None = None,
    extra: dict | None = None,
    extra_kw: object = None,
    wrap: dict[str, Callable[..., list[str]]] | None = None,
) -> dict[str, object]:
    """The sweep.  ``scenes``, ``selections`` (a tuple, or a function of the scene) and ``tokens`` default to
    the twelve topologies, ``SELECTIONS`` and ``TOKENS_PER_CASE``; ``extra`` registers more oracles (name ->
    function, each with a DOMAIN) and ``extra_kw(scene, op)`` supplies their product-side input.  An extra
    oracle is judged on the mutants whose tag meets its DOMAIN (the only ones it is counted on); the six run
    on every mutant as before."""
    survivors: list[str] = []
    missed: list[str] = []
    total = equivalent = allowed = unjudged = 0
    RAISED[0] = 0
    oracles = {**vo.ORACLES, **(extra or {})}
    for name, replacement in (wrap or {}).items():  # a probe may replace an oracle (it keeps the DOMAIN)
        replacement.DOMAIN = oracles[name].DOMAIN  # type: ignore[attr-defined]
        oracles[name] = replacement
    order = (*ORACLE_ORDER, *(extra or {}))
    kills: dict[str, int] = dict.fromkeys(order, 0)

    def order_for(tag: str) -> tuple[str, ...]:
        return (*ORACLE_ORDER, *(n for n in (extra or {}) if oracles[n].DOMAIN & _kinds(tag)))  # type: ignore[attr-defined]

    for sname, scene in vfb.default_scenes() if scenes is None else scenes:
        sels = SELECTIONS if selections is None else selections(scene) if callable(selections) else selections
        for sel in sels:
            op = vfb.Op("delete", 0, sel)
            before = vfb.build(scene)
            good, facts = vfb.expected(scene, op)
            ctx = {**(extra_kw(scene, op) if extra_kw else {}), **{k: v for k, v in facts.context.items() if k != "scenario_op"}}  # type: ignore[operator]
            ctx["expected"] = good
            declared = frozenset(ctx["stream_xrefs"]) | frozenset(ctx["new_xrefs"])
            rng = random.Random(f"{seed_tag}/{sname}/{sel}")
            base_bytes = fitz.open(stream=good, filetype="pdf").tobytes(garbage=0)  # same writer as the mutants
            base_doc = fitz.open(stream=base_bytes, filetype="pdf")
            strict, relaxed = _canon(base_doc), _canon(base_doc, declared)
            _BASE_BYTES[0] = base_bytes
            gen = [*_token_mutations(base_doc, rng, TOKENS_PER_CASE if tokens is None else tokens), *_other_mutations(base_bytes, rng)]
            try:
                facts_of_base: _BaseFacts | None = _BaseFacts(base_doc, before, ctx)
            except Exception:  # noqa: BLE001 - a scene the fact reader cannot judge enforces nothing beyond O-rebuild
                facts_of_base = None
            for tag, desc, data in gen:
                total += 1
                mdoc = None
                try:
                    mdoc = fitz.open(stream=data, filetype="pdf")
                    if _canon(mdoc) == strict:
                        equivalent += 1
                        continue
                    if _canon(mdoc, declared) == relaxed:
                        allowed += 1  # ALLOWLIST["storage-declared"]
                        continue
                    if _same_but_contents_spelling(base_doc, mdoc):
                        allowed += 1  # ALLOWLIST["contents-spelling"]
                        continue
                except Exception:  # noqa: BLE001
                    pass
                # Must-kill is read from the mutant's own differences (never from an oracle's answer): every
                # oracle whose DOMAIN meets a violated fact kind must reject it.  A mutant the fact reader
                # cannot open or judge is one an oracle cannot read either (raising counts as rejecting).
                violated: frozenset[str] | None = None
                if facts_of_base is not None and mdoc is not None:
                    try:
                        violated = facts_of_base.violated(mdoc)
                    except Exception:  # noqa: BLE001
                        violated = None
                if violated is None:
                    unjudged += 1
                    violated = frozenset()
                order_m = (*ORACLE_ORDER, *(n for n in (extra or {}) if oracles[n].DOMAIN & (violated or _kinds(tag))))  # type: ignore[attr-defined]
                rejecters = _judge(oracles, before, data, ctx, order_m)
                for name in order_m:
                    if oracles[name].DOMAIN & violated:  # type: ignore[attr-defined]
                        if name in rejecters:
                            kills[name] += 1
                        elif (name, tag) not in MISSED_ALLOWLIST:
                            missed.append(f"{name} accepted {tag} ({'/'.join(sorted(violated))}) {sname}/{sel}: {desc}")
                if "O-rebuild" not in rejecters:
                    survivors.append(f"{sname}/{sel} {tag}: {desc}")
            for tag, desc, mctx, must in _metadata_mutants(ctx):
                total += 1
                rejecters = _judge(oracles, before, good, mctx, order_for(tag))
                for name in rejecters:
                    if oracles[name].DOMAIN & _kinds(tag):  # type: ignore[attr-defined]
                        kills[name] += 1
                missing = [n for n in must if n.replace("O-rebuild", "O-rebuild") not in rejecters]
                if missing:
                    survivors.append(f"{sname}/{sel} {tag}: {desc} (accepted by {missing})")
    return {
        "survivors": survivors,
        "total": total,
        "equivalent": equivalent,
        "allowed": allowed,
        "kills": kills,
        "missed": missed,
        "unjudged": unjudged,
    }


def test_no_non_equivalent_mutation_of_a_correct_edit_survives_every_oracle() -> None:
    start = time.perf_counter()
    res = run_sweep()
    elapsed = time.perf_counter() - start
    survivors: list[str] = res["survivors"]  # type: ignore[assignment]
    print(
        f"\nsweep: {res['total']} mutants, {res['equivalent']} equivalent, {res['allowed']} allowlisted, "
        f"{RAISED[0]} rejections by raising, {len(survivors)} survivors, kills {res['kills']}, {elapsed:.1f} s"
    )
    assert res["total"] > 300  # type: ignore[operator]
    by_tag: dict[str, int] = {}
    for s in survivors:
        tag = s.split(": ")[0].split(" ", 1)[1]
        by_tag[tag] = by_tag.get(tag, 0) + 1
    assert not survivors, f"{len(survivors)} surviving mutants {by_tag}:\n" + "\n".join(survivors[:40])
    missed: list[str] = res["missed"]  # type: ignore[assignment]
    assert not missed, f"{len(missed)} in-domain mutants accepted by an oracle responsible for them:\n" + "\n".join(missed[:40])
    assert res["unjudged"] <= 0.05 * res["total"], f"too many mutants the fact reader could not judge: {res['unjudged']}"  # type: ignore[operator]
    weak = {name: n for name, n in res["kills"].items() if n < MIN_KILLS}  # type: ignore[attr-defined]
    assert not weak, f"oracles that reject fewer than {MIN_KILLS} sweep mutants of their own domain: {weak}"


def _hiding_one_rejection(fn: Callable[..., list[str]]) -> Callable[..., list[str]]:
    """``fn`` with its FIRST genuine rejection suppressed (the Astra reviewer's probe)."""
    state = {"hidden": 0}

    def wrapped(*args: object, **kw: object) -> list[str]:
        out = fn(*args, **kw)
        if out and not state["hidden"]:
            state["hidden"] = 1
            return []
        return out

    wrapped.state = state  # type: ignore[attr-defined]
    return wrapped


@pytest.mark.parametrize("name", ORACLE_ORDER)
def test_the_sweep_fails_when_any_one_oracle_hides_one_genuine_rejection(name: str) -> None:
    """Astra B2 (class: aggregate-only oracle judgement).  The kill floor is an aggregate, so a single
    suppressed must-kill cell must fail the run by itself, whatever the other oracles kill."""
    probe = _hiding_one_rejection(vo.ORACLES[name])
    scenes = vfb.default_scenes()[:2]
    res = run_sweep("probe", scenes=scenes, selections=((1, 2),), tokens=60, wrap={name: probe})
    assert probe.state["hidden"] == 1, f"{name} rejected nothing in the probe scenes, the probe proves nothing"  # type: ignore[attr-defined]
    assert res["survivors"] or res["missed"], f"hiding one {name} rejection did not fail the sweep"
    # and the unmodified oracle passes the same cells (the failure above is the suppression's)
    clean = run_sweep("probe", scenes=scenes, selections=((1, 2),), tokens=60)
    assert not clean["survivors"] and not clean["missed"]


def test_a_whole_block_envelope_cannot_start_inside_a_two_character_operator() -> None:
    """B1 review finding 2: an envelope starting at the ``G`` of ``RG`` was accepted as a whole block."""
    old = b"0 0 1 RG\nq 0 0 m 5 5 l S Q\n"
    q = old.index(b"q")
    ce = old.index(b"Q") + 1
    own_s, own_e = old.index(b"0 0 m"), old.index(b"S") + 1
    assert not vo._envelope_shape(old, 0, [(q, ce, own_s, own_e, True)])  # exact block: fine
    assert not vo._envelope_shape(old, 0, [(q - 1, ce + 1, own_s, own_e, True)])  # one ws byte each side
    for es in (q - 2, q - 3, own_s):  # mid-token starts (the G of RG, the 1 of "1 RG", the first path byte)
        assert vo._envelope_shape(old, 0, [(es, ce, own_s, own_e, True)]), es
    # a start on a word that is not q, even at a token boundary
    assert vo._envelope_shape(old, 0, [(old.index(b"RG"), ce, own_s, own_e, True)])


def test_the_independent_drawing_reader_agrees_with_the_oracle_reader_on_equality() -> None:
    """B2: PATHS / OTHER_PAGES are read by ``_drawings_of``, not by ``vo._page_records``.  The two readers
    must call two documents equal or different alike, over rebuilt-equal and differing drawings."""
    bodies = [
        "0 0 1 rg 10 10 50 30 re f",
        "0 0 1 rg 10 10 50 30 re f",  # rebuilt equal
        "0 0 1 rg 12 10 50 30 re f",  # moved
        "0 1 0 rg 10 10 50 30 re f",  # other colour
        "1 w 10 10 m 60 40 l S",
        "2 w 10 10 m 60 40 l S",  # other width
        "1 w 10 10 m 60 41 l S",  # other end point
        "",  # nothing drawn
        "[3] 0 d 1 w 10 10 m 60 40 l S",  # dash only
        "1 J 1 w 10 10 m 60 40 l S",  # cap only
        "1 j 1 w 10 10 m 60 40 l S",  # join only
        "1 w 10 10 m 60 40 l h S",  # closePath only
    ]
    docs = []
    for body in bodies:
        doc = fitz.open()
        page = doc.new_page(width=200, height=100)
        page.draw_rect(fitz.Rect(0, 0, 1, 1))  # gives the page a content stream; replaced below
        doc.update_stream(int(page.get_contents()[0]), body.encode())
        docs.append(doc)
    try:
        for i, a in enumerate(docs):
            for j, b in enumerate(docs):
                mine = _drawings_of(a, 0) == _drawings_of(b, 0)
                oracle = vo._page_records(a, 0) == vo._page_records(b, 0)
                assert mine == oracle, (i, j, mine, oracle)
                assert mine == (i == j or {i, j} == {0, 1}), (i, j)
    finally:
        for doc in docs:
            doc.close()


@pytest.mark.parametrize("tag", sorted(ALLOWLIST))
def test_allowlist_entries_state_a_reason(tag: str) -> None:
    assert len(ALLOWLIST[tag]) > 20


@pytest.mark.parametrize("key", sorted(MISSED_ALLOWLIST))
def test_missed_allowlist_entries_state_a_reason(key: tuple[str, str]) -> None:
    assert len(MISSED_ALLOWLIST[key]) > 20
