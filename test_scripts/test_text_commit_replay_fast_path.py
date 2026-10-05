"""Replay fast path: provably inert operator spans (critique step 12 latency).

The click-time source-show resolver, the Apply-by-token identity rebind and
every prepare replay the WHOLE page (graphics state carries across streams).
HVAC pages 5/6 are ~1.3 MB of vector drawing -- ~930k tokens of
``q 1 0 0 1 x y cm 0 0 m … l S Q`` -- and only ~70 text shows, so the
per-byte lexer cost ~1.4 s on the GUI thread per cold replay (plan
section 6, G2/T5 latency records).

``lex_content_stream(data, coalesce_inert=True)`` (used only by replay)
collapses spans whose replay effect is provably just "clear the operand
stack" into one ``TokenKind.INERT_RUN`` token:

* a sequence of balanced ``q … Q`` blocks (nested up to three deep) whose
  bodies hold only numbers, path/colour/clip operators and the pen/CTM
  operators ``cm w j M gs`` -- ``Q`` restores everything those touch, and
  every ``cm`` must be preceded
  by six NUMBER tokens (else the reference flags the stream malformed, and
  the fast path refuses the span);
* a top-level run of numbers and path/colour operators that ends at an
  operator token and contains no ``cm``/``gs`` token.

The contract is equality: ``replay_page_streams`` must return the SAME
``PageReplay`` with and without coalescing, on every input.  The reference is
obtained by swapping replay's token source back to the plain lexer.

All fixtures are synthetic; the real-corpus leg is ``needs_fixtures``.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit import pdf_lexer  # noqa: E402
from model.text_commit import replay as replay_module  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402

#: Generous, CI-safe ceiling for a ~1.3 MB path-heavy page (reference: ~1.4 s
#: on the development machine; the fast path measures tens of milliseconds).
LARGE_PAGE_BUDGET_S = 0.4
#: Linear-time guard for ~1 MB adversarial inputs: a quadratic rescan would
#: take minutes, the reference lexer takes about a second.
PATHOLOGICAL_BUDGET_S = 4.0


def _reference_replay(monkeypatch, streams):
    """Replay with the plain lexer (no coalescing): the equality oracle."""
    with monkeypatch.context() as patch:
        patch.setattr(
            replay_module,
            "lex_content_stream",
            lambda data, **_kwargs: pdf_lexer.lex_content_stream(data),
        )
        return replay_page_streams(list(streams), max_decoded_bytes=None)


def _fast_replay(streams):
    return replay_page_streams(list(streams), max_decoded_bytes=None)


def _assert_same(monkeypatch, streams) -> None:
    fast = _fast_replay(streams)
    reference = _reference_replay(monkeypatch, streams)
    assert fast == reference, (streams, fast, reference)


def _hvac_like_stream(blocks: int, *, seed: int = 7) -> bytes:
    """Vector-heavy content shaped like the HVAC drawing pages, plus text."""
    rng = random.Random(seed)
    parts = [
        b"q\n0.06 0 0 0.06 0 0 cm\n521 2134 m\n13522 2134 l\n13522 19152 l\nW n\n"
        b"/OC /MC0 BDC \n6 w 1 j 1 J \n/GS0 gs\n"
    ]
    for index in range(blocks):
        x = rng.randint(100, 14000) + rng.choice((0, 0.5, 0.25))
        y = rng.randint(100, 19000)
        parts.append(f"q 1 0 0 1 {x:g} {y} cm\n0 0 m\n".encode())
        for _ in range(rng.randint(1, 4)):
            parts.append(
                f"{rng.uniform(-60, 60):.3f} {rng.uniform(-60, 60):.3f} l\n".encode()
            )
        if rng.random() < 0.1:
            parts.append(b"2.793 -8.704 12.408 -14.688 23.26 -14.476 c\n")
        parts.append(b"S\nQ\n")
        if index % 400 == 0:
            parts.append(
                f"q\n16.6666667 0 0 16.6666667 0 0 cm\nBT\n0 0 0 rg\n/F1 9 Tf\n"
                f"0 -0.06 0.06 0 {x:g} {y} Tm\n(Label {index}) Tj\nET\nQ\n".encode()
            )
    parts.append(b"EMC \nQ\n")
    return b"".join(parts)


# ------------------------------------------------------------------ red: speed


def test_path_heavy_page_replays_within_budget() -> None:
    """RED before the fast path: ~1.3 MB of q/cm/path/Q blocks took ~1.4 s."""
    data = _hvac_like_stream(16000)
    assert 1_100_000 < len(data) < 1_700_000, len(data)
    best = float("inf")
    replay = None
    for _ in range(3):
        started = time.perf_counter()
        replay = replay_page_streams([(9, data)])
        best = min(best, time.perf_counter() - started)
    assert replay is not None and replay.refusal_reason is None and not replay.malformed
    assert len(replay.shows) == 40
    assert best < LARGE_PAGE_BUDGET_S, f"replay took {best * 1000:.0f} ms"


# ------------------------------------------------------------- red: the lexer


def test_coalescing_lexer_tiles_the_source_and_marks_inert_spans() -> None:
    data = _hvac_like_stream(300)
    tokens = list(lex_content_stream(data, coalesce_inert=True))
    # The lossless tiling invariant still holds.
    assert tokens[0].start == 0 and tokens[-1].end == len(data)
    for previous, current in zip(tokens, tokens[1:]):
        assert previous.end == current.start
    inert = [t for t in tokens if t.kind is TokenKind.INERT_RUN]
    assert inert, "no span was coalesced"
    covered = sum(t.end - t.start for t in inert)
    assert covered > 0.8 * len(data), (covered, len(data))
    for token in inert:
        span = data[token.start : token.end]
        for operator in (b"BT", b"Tj", b"Tf", b"BDC", b"EMC", b"/"):
            assert operator not in span, (operator, span[:120])
    # The default stays the plain lossless lexer (public contract unchanged).
    plain = list(lex_content_stream(data))
    assert all(t.kind is not TokenKind.INERT_RUN for t in plain)


def test_cm_with_too_few_numbers_inside_a_q_block_is_never_coalesced(monkeypatch) -> None:
    """The reference flags ``q 1 2 3 4 5 cm Q`` malformed; coalescing must not hide it."""
    for body in (b"1 2 3 4 5 cm", b"1 2 3 + 4 5 cm", b"1 2 3 1.2.3 5 6 cm", b"cm"):
        streams = [(3, b"q " + body + b" 0 0 m 1 1 l S Q\nBT /F1 9 Tf (a) Tj ET\n")]
        fast = _fast_replay(streams)
        assert fast.malformed is True, body
        _assert_same(monkeypatch, streams)
    tokens = list(lex_content_stream(b"q 1 2 3 4 5 cm Q", coalesce_inert=True))
    assert all(t.kind is not TokenKind.INERT_RUN for t in tokens)


# ------------------------------------------------------- equality (the contract)


_ADVERSARIAL: tuple[tuple[bytes, ...], ...] = (
    (b"q 1 0 0 1 5 5 cm 0 0 m 1 1 l S Q BT /F1 9 Tf 1 0 0 1 5 5 Tm (x) Tj ET",),
    (b"q 1 0 0 1 5 5 0 cm Q BT /F1 9 Tf (x) Tj ET",),  # seven numbers: fine
    (b"1 0 0 1 9 9 cm 0 0 m 1 1 l S BT /F1 9 Tf (x) Tj ET",),  # top-level cm
    (b"0 0 m 1 1 l S gs BT /F1 9 Tf (x) Tj ET",),  # top-level nameless gs
    (b"0 0 m 2 w 1 j 3 M 1 1 l S BT /F1 9 Tf (x) Tj ET",),  # top-level pen ops
    (b"q 2 w 1 j 3 M gs 0 0 m S Q BT /F1 9 Tf (x) Tj ET",),  # restored by Q
    (b"5 6 q 0 0 m S Q (s) Tj",),  # numbers before q
    (b"q 0 0 m 1 1 l S BT /F1 9 Tf (x) Tj ET",),  # q with no Q
    (b"% q 1 0 0 1 0 0 cm 0 0 m S Q\nBT /F1 9 Tf (x) Tj ET",),  # comment
    (b"BT /F1 9 Tf (0 0 m Q q 1 1 l S Q) Tj ET",),  # string holding operators
    (b"BI /W 1 /H 1 /BPC 8 /CS /G ID \x00 q 0 0 m S Q EI q 0 0 m S Q",),  # inline image
    (b"q 0 0 m 1 1 l", b" S Q BT /F1 9 Tf (x) Tj ET"),  # q/Q split across streams
    (b"q 1cm 0 0 m S Q (x) Tj", b"q cmm mcm c m S Q"),
    (b"q 0 0 m S Q Q Q BT /F1 9 Tf (x) Tj ET",),  # unbalanced extra Q
    (b"/OC /P0 BDC q 0 0 m S Q EMC BT (x) Tj ET",),
    (b"q /OC /P0 BDC 0 0 m S EMC Q (x) Tj",),
    (b"BT /F1 9 Tf q 0 0 m S Q (x) Tj T* (y) Tj ET",),  # q inside BT
    (b"[ 1 2 m ] TJ q 0 0 m S Q",),
    (b"1 2 3 4 5 6 q 0 0 m S Q cm (x) Tj",),
    (b"q\n0.06 0 0 0.06 0 0 cm\n1 137 m\n14029 137 l\nW n\n/OC /MC12 BDC\nq\n"
     b"16.6666667 0 0 16.6666667 0 0 cm\nBT\n0 0 0 rg\n/GS0 gs\n/C2_2 94.442 Tf\n"
     b"0 -0.06 0.06 0 41.88 65.22 Tm\n<0037003A>Tj\nET\nQ\nEMC\nQ\n",),
    (b"q\r\n1 0 0 1 2 3 cm\r\n0 0 m\r\n.5 -.5 l\r\n+1. -2. l\r\nS\r\nQ\r\n(x) Tj",),
    (b"q 0 0 m S Q" + b"\x00\x0c" + b"q 0 0 m S Q (x) Tj",),
    (b"q 1 0 0 1 0 0 cm S Qq 0 0 m S Q (x) Tj",),  # 'Qq' is one token
    (b"q 1 1 1 rg 0 0 1 RG 0.5 g 1 G 0 0 0 1 k 1 0 0 0 K 0 0 5 5 re f* B* b* W* n Q",),
    # nested blocks: depth 2 and 3 coalesce, depth 4 falls back
    (b"q 0 -1 1 0 5 5 cm q 1 0 0 1 2 3 cm 0 0 m S Q Q (x) Tj",),
    (b"q 1 0 0 1 0 0 cm q 2 w q 0 0 m S Q 1 1 l S Q Q BT /F1 9 Tf (x) Tj ET",),
    (b"q q q q 0 0 m S Q Q Q Q (x) Tj",),
    (b"q 1 0 0 1 0 0 cm q 1 2 cm 0 0 m S Q Q (x) Tj",),  # malformed inner cm
    (b"q q 0 0 m S Q (x) Tj",),  # unbalanced: inner closes, outer open
    (b"q 0 0 m S Q Q q 1 1 l S Q",),
    (b"q 0 0 m Sq 1 1 l S Q Q",),  # 'Sq' is one word, not a nested q
)


@pytest.mark.parametrize("streams", _ADVERSARIAL, ids=[str(i) for i in range(len(_ADVERSARIAL))])
def test_adversarial_streams_replay_identically(monkeypatch, streams) -> None:
    _assert_same(monkeypatch, [(10 + i, data) for i, data in enumerate(streams)])


_FRAGMENTS: tuple[bytes, ...] = (
    b"q", b"Q", b"cm", b"w", b"j", b"M", b"gs", b"/GS0", b"/F1", b"Tf", b"BT", b"ET",
    b"Tm", b"Td", b"TD", b"T*", b"TL", b"Tc", b"Tw", b"Tz", b"Ts", b"Tr", b"Tj", b"TJ",
    b"'", b'"', b"(ab)", b"<4142>", b"[", b"]", b"<<", b">>", b"/OC", b"BDC", b"BMC",
    b"EMC", b"m", b"l", b"c", b"v", b"y", b"h", b"re", b"S", b"s", b"f", b"f*", b"n",
    b"W", b"W*", b"rg", b"RG", b"g", b"G", b"k", b"K", b"sc", b"scn", b"J", b"i", b"d0",
    b"Do", b"0", b"1", b"-2.5", b".5", b"3.", b"+4", b"1.2.3", b"+", b"1m", b"cmm",
    b"% c\n", b"true", b"null", b"\n", b" ", b"\r\n", b"\t",
)


def _random_stream(rng: random.Random) -> bytes:
    pieces: list[bytes] = []
    for _ in range(rng.randint(1, 60)):
        roll = rng.random()
        if roll < 0.35:
            # a well-formed q-block, sometimes with a malformed cm
            numbers = rng.choice((6, 6, 6, 7, 5, 0))
            pieces.append(
                b"q "
                + b" ".join(str(rng.randint(-9, 9)).encode() for _ in range(numbers))
                + b" cm 0 0 m 1 1 l S Q"
            )
        elif roll < 0.42:
            pieces.append(b"0 0 m 3 4 l 5 6 7 8 9 1 c h S")
        elif roll < 0.5:
            depth = rng.randint(1, 5)
            pieces.append(b"q 1 0 0 1 2 3 cm " * depth + b"0 0 m S" + b" Q" * rng.choice((depth, depth, depth - 1)))
        else:
            pieces.append(rng.choice(_FRAGMENTS))
    sep = (b" ", b"\n", b"  ", b"\r\n")
    out = bytearray()
    for piece in pieces:
        out += piece
        out += rng.choice(sep)
    return bytes(out)


def test_fuzzed_streams_replay_identically(monkeypatch) -> None:
    rng = random.Random(20261002)
    coalesced_runs = 0
    for _ in range(1500):
        count = rng.choice((1, 1, 2, 3))
        streams = [(20 + i, _random_stream(rng)) for i in range(count)]
        for _, data in streams:
            coalesced_runs += sum(
                1
                for token in lex_content_stream(data, coalesce_inert=True)
                if token.kind is TokenKind.INERT_RUN
            )
        _assert_same(monkeypatch, streams)
    assert coalesced_runs > 500, "the fuzz corpus barely exercised the fast path"


# ---------------------------------------------------------- linear-time guards


@pytest.mark.parametrize(
    "data",
    (
        b"1 0 0 1 0 0 cm 0 0 m 1 1 l S\n" * 35000,  # top-level cm splits every run
        b"q 1 0 0 1 0 0 cm\n" + b"0 0 m 1 1 l S\n" * 70000,  # q with no Q
        b"1" * 1_000_000,  # one megabyte-long token
        b"q 1 2 3 4 5 cm 0 0 m S Q\n" * 40000,  # every block refuses (malformed cm)
        b"q 1 0 0 1 0 0 cm 0 0 m S\n" * 40000,  # ever-deeper unclosed nesting
        b"q q q q 0 0 m S Q Q Q Q\n" * 40000,  # nesting one past the limit
    ),
    ids=(
        "top-level-cm",
        "unclosed-q",
        "megabyte-token",
        "malformed-cm-blocks",
        "deep-unclosed",
        "too-deep",
    ),
)
def test_pathological_inputs_stay_linear(monkeypatch, data) -> None:
    """GUARD (labelled): bounded time on inputs that could make a rescan quadratic."""
    started = time.perf_counter()
    fast = _fast_replay([(4, data)])
    elapsed = time.perf_counter() - started
    assert elapsed < PATHOLOGICAL_BUDGET_S, f"{elapsed:.2f} s"
    assert fast == _reference_replay(monkeypatch, [(4, data)])


# ------------------------------------------------------------ real corpus


def _corpus_pdfs() -> list[Path]:
    base = ROOT / "test_files"
    return sorted(base.glob("*.pdf")) if base.is_dir() else []


@pytest.mark.needs_fixtures
def test_every_fixture_page_replays_identically(monkeypatch) -> None:
    pdfs = _corpus_pdfs()
    if not pdfs:
        pytest.skip("test_files/ fixtures are not present")
    pages = 0
    for path in pdfs:
        try:
            doc = fitz.open(str(path))
        except Exception:  # noqa: BLE001 - unreadable fixture is not this test's subject
            continue
        with doc:
            if doc.needs_pass:
                continue
            for page in doc:
                streams = read_page_streams(doc, page)
                if not streams:
                    continue
                if sum(len(data) for _, data in streams) > replay_module.DEFAULT_MAX_REPLAY_BYTES:
                    continue  # refused before lexing in production
                if path.name.startswith("test-large-file") and page.number > 40:
                    continue  # 402 near-identical pages: the first 40 suffice
                _assert_same(monkeypatch, streams)
                pages += 1
    assert pages > 20, pages
