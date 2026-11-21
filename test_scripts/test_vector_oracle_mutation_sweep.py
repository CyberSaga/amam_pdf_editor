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
from collections.abc import Iterator
from pathlib import Path

import fitz
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
MIN_KILLS = 5
ORACLE_ORDER = ("O-rebuild", "O-bytes", "rule B", "O-dict", "O-struct", "O-pixel")
# fact kinds a mutation tag can violate (used for the per-oracle DOMAIN table)
TAG_KINDS: dict[str, frozenset[str]] = {
    "pixel": frozenset({"PATHS", "PIXELS_OUTSIDE", "OUTSIDE_BYTES"}),
    "stream:byte": frozenset({"PATHS", "OUTSIDE_BYTES", "OBJECTS", "PIXELS_OUTSIDE"}),
    "stream:move": frozenset({"PATHS", "OUTSIDE_BYTES", "OBJECTS", "PIXELS_OUTSIDE"}),
    "meta:ranges": frozenset({"OUTSIDE_BYTES"}),
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


def _judge(oracles: dict, before: bytes, mutant: bytes, ctx: dict) -> set[str]:
    """Names of the oracles that reject ``mutant``.  Every oracle runs (none is hidden behind another)."""
    rejected: set[str] = set()
    for name in ORACLE_ORDER:
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
    if ctx["stream_xrefs"]:
        yield "meta:writeset", "declared stream xrefs cleared", {**ctx, "stream_xrefs": frozenset()}, ("rule B",)
    if ctx["new_xrefs"]:
        yield "meta:writeset", "declared new xrefs cleared", {**ctx, "new_xrefs": frozenset()}, ("rule B", "O-rebuild")
        yield "meta:writeset", "edited page's /Contents not declared", {**ctx, "page_xref": -1}, ("rule B",)


def run_sweep(seed_tag: str = "sweep") -> dict[str, object]:
    survivors: list[str] = []
    total = equivalent = allowed = 0
    RAISED[0] = 0
    kills: dict[str, int] = dict.fromkeys(ORACLE_ORDER, 0)
    for sname, scene in vfb.default_scenes():
        for sel in SELECTIONS:
            op = vfb.Op("delete", 0, sel)
            before = vfb.build(scene)
            good, facts = vfb.expected(scene, op)
            ctx = {k: v for k, v in facts.context.items() if k != "scenario_op"}
            ctx["expected"] = good
            declared = frozenset(ctx["stream_xrefs"]) | frozenset(ctx["new_xrefs"])
            rng = random.Random(f"{seed_tag}/{sname}/{sel}")
            base_bytes = fitz.open(stream=good, filetype="pdf").tobytes(garbage=0)  # same writer as the mutants
            base_doc = fitz.open(stream=base_bytes, filetype="pdf")
            strict, relaxed = _canon(base_doc), _canon(base_doc, declared)
            _BASE_BYTES[0] = base_bytes
            gen = [*_token_mutations(base_doc, rng, TOKENS_PER_CASE), *_other_mutations(base_bytes, rng)]
            for tag, desc, data in gen:
                total += 1
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
                rejecters = _judge(vo.ORACLES, before, data, ctx)
                for name in rejecters:
                    if vo.ORACLES[name].DOMAIN & _kinds(tag):  # type: ignore[attr-defined]
                        kills[name] += 1
                if "O-rebuild" not in rejecters:
                    survivors.append(f"{sname}/{sel} {tag}: {desc}")
            for tag, desc, mctx, must in _metadata_mutants(ctx):
                total += 1
                rejecters = _judge(vo.ORACLES, before, good, mctx)
                for name in rejecters:
                    if vo.ORACLES[name].DOMAIN & _kinds(tag):  # type: ignore[attr-defined]
                        kills[name] += 1
                missing = [n for n in must if n.replace("O-rebuild", "O-rebuild") not in rejecters]
                if missing:
                    survivors.append(f"{sname}/{sel} {tag}: {desc} (accepted by {missing})")
    return {"survivors": survivors, "total": total, "equivalent": equivalent, "allowed": allowed, "kills": kills}


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
    weak = {name: n for name, n in res["kills"].items() if n < MIN_KILLS}  # type: ignore[attr-defined]
    assert not weak, f"oracles that reject fewer than {MIN_KILLS} sweep mutants of their own domain: {weak}"


@pytest.mark.parametrize("tag", sorted(ALLOWLIST))
def test_allowlist_entries_state_a_reason(tag: str) -> None:
    assert len(ALLOWLIST[tag]) > 20
