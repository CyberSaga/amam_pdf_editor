"""Card B4 (design plan 4.2 "F after S0"): accelerated scanner F equals scanner G on every column.

Red first: ``scan_page(accelerated=True)`` raised NotImplementedError before B4.  F admits a page only inside
its vocabulary (no strings, hex strings, dictionaries, arrays, comments, braces, text, clips, marked content,
colour-space names, inline images); anything else is handed to G for the whole page, so a refusal has the same
class, code and first error.  ``scanner`` says which path ran, so a silent fallback cannot pass the gate.
Tables are compared with ``tobytes()`` (a gs makes line_width NaN; NaN != NaN under array_equal).
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.vector_paths.scan import VectorIndex, VectorPageRefused, VectorScanCancelled, scan_page  # noqa: E402

IDENT6 = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
PAGE = (1.0, 0.0, 0.0, -1.0, 0.0, 792.0)
_TABLES = ("paths", "cubics", "segments", "blocks", "streams")


def _same(a: VectorIndex, b: VectorIndex) -> None:
    for name in _TABLES:
        ta, tb = getattr(a, name), getattr(b, name)
        assert ta.dtype == tb.dtype, name
        assert ta.shape == tb.shape, f"{name}: {ta.shape} != {tb.shape}"
        assert ta.tobytes() == tb.tobytes(), f"table {name} differs"
    assert a.indexed_end == b.indexed_end
    assert a.stopped_at_inline_image == b.stopped_at_inline_image
    assert a.frame == b.frame
    assert a.stream_digests == b.stream_digests
    assert a.nbytes == b.nbytes
    assert a.block_resources == b.block_resources


def _outcome(streams: list[bytes], frame=PAGE, accelerated: bool = False):
    try:
        return scan_page(streams, frame, accelerated=accelerated)
    except VectorPageRefused as exc:
        return exc


def _check(streams: list[bytes], frame=PAGE, expect_scanner: str | None = None) -> None:
    g = _outcome(streams, frame)
    f = _outcome(streams, frame, accelerated=True)
    if isinstance(g, VectorPageRefused):
        assert isinstance(f, VectorPageRefused), "F answered a page G refuses"
        assert (f.code, str(f)) == (g.code, str(g))
        return
    assert isinstance(f, VectorIndex), f"G answered, F refused: {f}"
    _same(f, g)
    assert g.scanner == "G" and g.accelerated is False
    if expect_scanner is not None:
        assert f.scanner == expect_scanner
        assert f.accelerated is (expect_scanner == "F")


# ----------------------------------------------------------------------------- fixtures: admitted (F must run)

ADMITTED = {
    "plain_line": b"10 10 m 90 90 l S",
    "rect_fill": b"10 10 80 80 re f",
    "cubics": b"0 0 m 10 20 30 40 50 60 c 70 80 90 100 v 1 2 3 4 y S",
    "close_and_dot": b"5 5 m h S 1 1 m 2 2 l h S 3 3 m h h S",
    "block_inert": b"q 1 0 0 1 5 5 cm 0 0 m 9 9 l S Q",
    "nested_blocks": b"q 2 0 0 2 0 0 cm q 1 0 0 1 3 3 cm 0 0 m 5 5 l S Q 7 7 m 8 8 l S Q",
    "cm_chain": b"1 0 0 1 10 10 cm 2 0 0 2 0 0 cm 0.5 0.5 m 3 3 l S",
    "rotate": b"q 0.7071 0.7071 -0.7071 0.7071 0 0 cm 0 0 m 100 0 l 100 100 l f Q",
    "width_gs_nan": b"3 w 0 0 m 5 5 l S /GS0 gs 0 0 m 6 6 l S 2 w 0 0 m 7 7 l S",
    "gs_scoped": b"q /GS#41 gs 0 0 m 5 5 l S Q 0 0 m 6 6 l S",
    "impure_between": b"0 0 m 1 w 5 5 l S",
    "open_path_across_q": b"q 0 0 m 9 9 l Q S",
    "paint_without_path": b"S f n 0 0 m 5 5 l S",
    "colours": b"1 0 0 rg 0 0 1 RG 0.5 g 0.2 G 1 1 1 1 k 0 0 0 0 K 4 w 1 J 2 j 3 M 0.5 i /Perceptual ri 0 0 m 5 5 l B",
    "every_paint": b"0 0 m 5 5 l S 0 0 m 5 5 l s 0 0 m 5 5 l f 0 0 m 5 5 l F 0 0 m 5 5 l f* 0 0 m 5 5 l B 0 0 m 5 5 l B* 0 0 m 5 5 l b 0 0 m 5 5 l b* 0 0 m 5 5 l n",
    "numbers": b"1.2345678901234567890 9007199254740993 m 0.1234567890123456789012345678901234567890 -.5 l 1 2 +3. -0 re S",
    "crlf_tabs": b"q\r\n1\t0 0\x0c1 0 0 cm\r0 0 m\n\n9 9 l\r\nS\x00Q",
    "empty": b"",
    "spaces_only": b"  \n ",
    "unclosed_q": b"q 1 0 0 1 4 4 cm 0 0 m 5 5 l S",
    "names_adjacent": b"/GS0 gs/GS1 gs 0 0 m 1 1 l S",
}


@pytest.mark.parametrize("name", sorted(ADMITTED))
def test_f_equals_g_on_admitted_fixtures(name: str) -> None:
    _check([ADMITTED[name]], expect_scanner="F")


@pytest.mark.parametrize("name", sorted(ADMITTED))
@pytest.mark.parametrize("frame", [IDENT6, PAGE, (0.0, 1.0, -1.0, 0.0, 612.0, 0.0), (2.0, 0.0, 0.0, 2.0, -3.0, 4.0)])
def test_f_equals_g_under_every_frame(name: str, frame) -> None:
    _check([ADMITTED[name]], frame, expect_scanner="F")


def test_f_equals_g_across_streams_with_an_open_path_and_a_block() -> None:
    _check([b"q 1 0 0 1 3 3 cm 0 0 m", b"9 9 l S Q", b"5 5 m 6 6 l", b"S"], expect_scanner="F")


def test_f_runs_on_the_cad_shaped_page() -> None:
    body = b"".join(b"q 1 0 0 1 %d %d cm 0 0 m %d 1 l 2 3 l S Q\n" % (i, i, i % 7) for i in range(300))
    _check([body], expect_scanner="F")


# ----------------------------------------------------------------------------- fixtures: not admitted (G runs, same answer)

NOT_ADMITTED = {
    "string": b"BT (hello) Tj ET 0 0 m 5 5 l S",
    "hex": b"<41> Tj 0 0 m 5 5 l S",
    "dict": b"/OC << /A 1 >> BDC 0 0 m 5 5 l S EMC",
    "array": b"[3 2] 0 d 0 0 m 5 5 l S",
    "comment": b"% note\n0 0 m 5 5 l S",
    "clip": b"0 0 5 5 re W n 0 0 m 5 5 l S",
    "bt": b"BT ET 0 0 m 5 5 l S",
    "colour_space": b"/Cs1 cs /Cs1 CS 0 0 m 5 5 l S",
    "scn": b"/P1 scn 0 0 m 5 5 l S",
    "inline_image": b"0 0 m 5 5 l S BI /W 1 ID x EI 0 0 m 1 1 l S",
    "do": b"/X Do 0 0 m 5 5 l S",
    "unknown_operator": b"0 0 m 5 5 l frob S",
}


@pytest.mark.parametrize("name", sorted(NOT_ADMITTED))
def test_unadmitted_pages_are_handed_to_g_whole(name: str) -> None:
    body = NOT_ADMITTED[name]
    _check([body], expect_scanner="G")
    f = scan_page([body], PAGE, accelerated=True)
    assert (f.scanner, f.accelerated) == ("G", False)


# ----------------------------------------------------------------------------- refusals are G's

REFUSED = [
    b"1.2.3 0 m 1 1 l S",
    b"5 5 l S",
    b"Q",
    b"q Q Q",
    b"1 2 3 m 4 5 l S",
    b"1 m 4 5 l S",
    b"0 0 m 5 l S",
    b"1e5 0 m 5 5 l S",
    b"0 0 m 5 5 l ] S",
    b"2147483648.5 0 m 1 1 l S",
    b"1e 0 m 1 1 l S",
    b"3.4e38 0 m 1 1 l S",
    b"340282366920938463463374607431768211456 0 m 1 1 l S",
    b"1000000000000 0 m 1 1 l S",
    b"1 0 0 1 3.4e38 0 cm 0 0 m 1 1 l S",
]


@pytest.mark.parametrize("body", REFUSED, ids=[str(i) for i in range(len(REFUSED))])
def test_refusals_match_g(body: bytes) -> None:
    _check([body])


def test_size_caps_are_g_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    from model.vector_paths import scan as scan_mod

    monkeypatch.setattr(scan_mod, "MAX_PAINTS", 3)
    _check([b"0 0 m 1 1 l S " * 4])
    monkeypatch.setattr(scan_mod, "MAX_SEGMENT_ROWS", 5)
    _check([b"0 0 m 1 1 l 2 2 l 3 3 l 4 4 l 5 5 l 6 6 l S"])


def test_a_cancel_and_a_callback_error_propagate_unchanged() -> None:
    body = b"0 0 m 1 1 l S " * 50
    with pytest.raises(VectorScanCancelled):
        scan_page([body], PAGE, accelerated=True, cancel=lambda: True)

    def boom(done: int, total: int) -> None:
        raise RuntimeError("callback")

    with pytest.raises(RuntimeError, match="callback"):
        scan_page([body], PAGE, accelerated=True, progress=boom)


def test_progress_ends_with_a_terminal_event() -> None:
    body = b"0 0 m 1 1 l S " * 50
    seen: list[tuple[int, int]] = []
    scan_page([body], PAGE, accelerated=True, progress=lambda a, b: seen.append((a, b)))
    assert seen and seen[-1] == (len(body), len(body))


# ----------------------------------------------------------------------------- fuzz (fixed seeds)

_PATH_OPS = [b"m", b"l", b"c", b"v", b"y", b"re", b"h"]
_ARITY = {b"m": 2, b"l": 2, b"c": 6, b"v": 4, b"y": 4, b"re": 4, b"h": 0, b"cm": 6, b"w": 1, b"J": 1, b"j": 1, b"M": 1, b"i": 1,
          b"g": 1, b"G": 1, b"rg": 3, b"RG": 3, b"k": 4, b"K": 4}
_PAINTS = [b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"]
_WS = [b" ", b" ", b" ", b"\n", b"\r\n", b"\t", b"  ", b"\x00", b"\x0c", b"\r"]
_NAMES = [b"/GS0", b"/GS#41", b"/Perceptual", b"/A", b"/G#2f"]


def _num(rng: random.Random, sloppy: bool = True) -> bytes:
    kind = rng.random()
    if kind < 0.5:
        return str(rng.randint(-200, 600)).encode()
    if kind < 0.8:
        return ("%.*f" % (rng.randint(1, 6), rng.uniform(-300, 900))).encode()
    if kind < 0.85:
        return b"." + str(rng.randint(1, 99999)).encode()
    if kind < 0.9:
        return ("%+d." % rng.randint(-50, 50)).encode()
    if kind < 0.95:
        return ("%.*f" % (rng.randint(12, 24), rng.uniform(-5, 5))).encode()
    return str(rng.randint(10**15, 10**18)).encode() if sloppy else b"7"


def _program(seed: int, sloppy: bool) -> list[bytes]:
    rng = random.Random(seed)
    out: list[bytes] = []
    depth = 0
    have_cur = False
    for _ in range(rng.randint(5, 120)):
        r = rng.random()
        if r < 0.10:
            out.append(b"q")
            depth += 1
        elif r < 0.18 and (depth > 0 or sloppy):
            out.append(b"Q")
            depth -= 1
        elif r < 0.30:
            args = [_num(rng, sloppy) for _ in range(6)]
            if rng.random() < 0.7:
                args[:4] = [b"1", b"0", b"0", b"1"]
            out.append(b" ".join(args + [b"cm"]))
        elif r < 0.62:
            op = rng.choice(_PATH_OPS)
            if not have_cur and not sloppy and op in (b"l", b"c", b"v", b"y"):
                op = rng.choice([b"m", b"re"])
            if op in (b"m", b"re"):
                have_cur = True
            out.append(b" ".join([_num(rng, sloppy) for _ in range(_ARITY[op])] + [op]))
        elif r < 0.80:
            have_cur = False
            out.append(rng.choice(_PAINTS))
        elif r < 0.88:
            op = rng.choice([b"w", b"J", b"j", b"M", b"i", b"g", b"G", b"rg", b"RG", b"k", b"K"])
            out.append(b" ".join([_num(rng, sloppy) for _ in range(_ARITY[op])] + [op]))
        elif r < 0.94:
            out.append(rng.choice(_NAMES) + b" " + rng.choice([b"gs", b"ri"]))
        elif sloppy:
            out.append(rng.choice([b"1 2 3 4 m", b"l", b"1 l", b"0 0 m 1 1 l frob", b"5 w w"]))
        else:
            out.append(b"0 0 m 4 4 l S")
    body = b""
    for tok in out:
        body += tok + rng.choice(_WS)
    if rng.random() < 0.3:
        body = body.rstrip()
    # split at arbitrary byte offsets into 1..4 streams
    where = range(len(body) + 1) if sloppy else [i for i, ch in enumerate(body) if ch in b" \r\n\t\x00\x0c"]
    cuts = sorted(rng.sample(list(where), k=min(rng.randint(0, 3), len(where))))
    parts, last = [], 0
    for c in cuts:
        parts.append(body[last:c])
        last = c
    parts.append(body[last:])
    return parts


@pytest.mark.parametrize("seed", range(250))
def test_fuzz_admitted_streams_f_equals_g(seed: int) -> None:
    _check(_program(seed, sloppy=False))


@pytest.mark.parametrize("seed", range(250, 500))
def test_fuzz_sloppy_streams_f_equals_g_or_refuses_like_g(seed: int) -> None:
    _check(_program(seed, sloppy=True))


def test_fuzz_admitted_pages_run_on_f_unless_g_refuses() -> None:
    ran = 0
    for seed in range(60):
        parts = _program(seed, sloppy=False)
        g = _outcome(parts)
        if isinstance(g, VectorIndex):
            f = scan_page(parts, PAGE, accelerated=True)
            assert f.scanner == "F", f"seed {seed} fell back"
            ran += 1
    assert ran >= 20


# ----------------------------------------------------------------------------- Astra review inputs (B4, 2026-11-24)

ASTRA_CASES = [
    [b"2147483584. w"],  # a real token that rounds to 2**31 as float32: G refuses (short branch checks after rounding)
    [b"2147483584.00000000000 w"],  # the same value in 22 characters: G's long branch checks before rounding
    [b"0", b"", b"0 m S"],  # operands in different streams, an empty stream between them
    [b"0 0 m q S Q"],  # a path already open at the q of a leaf block
    [b"0 " * 4096],  # trailing operands at the limit
    [b"0 " * 4097],  # trailing operands over the limit: G refuses (no operator needed)
    [b"0 1 m " + b"0 " * 4097],  # the same after an operator
    [b"/N " * 4097],  # names count as pending operands too
]


@pytest.mark.parametrize("case", ASTRA_CASES, ids=[str(i) for i in range(len(ASTRA_CASES))])
def test_astra_inputs_f_equals_g(case: list[bytes]) -> None:
    _check(case, IDENT6)
