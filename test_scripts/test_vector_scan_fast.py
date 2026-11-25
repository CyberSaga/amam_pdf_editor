"""Card B4 (design plan 4.2 "F after S0"): accelerated scanner F equals scanner G on every column.

Red first: ``scan_page(accelerated=True)`` raised NotImplementedError before B4.  F admits a page only inside
its vocabulary (the mask stage of 2026-11-25 widened it: see the section below); anything else is handed to G for the whole page, so a refusal has the same
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
    "inline_image": b"0 0 m 5 5 l S BI /W 1 ID x EI 0 0 m 1 1 l S",
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


# ----------------------------------------------------------------------------- the mask stage (B4 follow-up, 2026-11-25)
# F now masks comments, strings, hex strings, dictionaries and arrays and reads the text, marked-content, clip,
# XObject and colour-space operators.  Unknown words are operators (G's rule); BI, true, false and null still go to G.

MASKED = {
    "comment": b"% note\n0 0 m 5 5 l S",
    "comment_between_operands": b"0 0 m % x\n5 5 l S %tail",
    "comment_in_token_run": b"0 0 m 5 5 l%c\nS",
    "string": b"BT (hello) Tj ET 0 0 m 5 5 l S",
    "string_nested_escaped": b"BT (a(b)c\\)d\\\\) Tj () Tj (\\() ' ET 0 0 m 5 5 l S",
    "string_spaced": b"BT (a b  c\n d) Tj ET 0 0 m 5 5 l S",
    "hex": b"BT <41> Tj <> Tj < 4 1 > Tj ET 0 0 m 5 5 l S",
    "tj_array": b"BT [(A) -20 (B) <43>] TJ [] TJ [10] TJ [ ] TJ ET 0 0 m 5 5 l S",
    "text_operators": b"BT /F1 12 Tf 10 20 Td 1 0 0 1 5 5 Tm 14 TL T* 2 Tc 3 Tw 100 Tz 4 Ts (hi) Tj 1 2 (x) \" ET 0 0 m 5 5 l S",
    "dash": b"[3 2] 0 d 0 0 m 5 5 l S [] 0 d 1 1 m 2 2 l S [ 1  2.5 ] 3 d 3 3 m 4 4 l S",
    "dict_bdc": b"/Span <</MCID 0 /K [1 2 <<>>]>> BDC 0 0 m 5 5 l S EMC",
    "oc_section": b"/OC /MC0 BDC 0 0 m 5 5 l S EMC 1 1 m 2 2 l S",
    "oc_encoded": b"/O#43 /MC0 BDC 0 0 m 5 5 l S EMC",
    "oc_nested": b"/OC /A BDC /Span <</A 1>> BDC EMC 0 0 m 5 5 l S EMC 3 3 m 4 4 l S",
    "oc_opened_inside_a_path": b"0 0 m /OC /A BDC 5 5 l EMC S",
    "oc_closed_inside_a_path": b"/OC /A BDC 0 0 m EMC 5 5 l S",
    "bmc": b"/Tag BMC 0 0 m 5 5 l S EMC /OC /A BDC EMC 1 1 m 2 2 l S",
    "emc_unbalanced_open": b"/OC /A BDC 0 0 m 5 5 l S /Tag BMC 1 1 m 2 2 l S",
    "clip_wn": b"0 0 5 5 re W n 0 0 m 5 5 l S",
    "clip_wstar": b"0 0 5 5 re W* f 0 0 m 5 5 l S",
    "clip_stray": b"W 0 0 m 5 5 l S 1 1 m 2 2 l S",
    "clip_stray_before_empty_paint": b"W n 0 0 m 5 5 l S",
    "clip_scoped": b"q 0 0 5 5 re W n 0 0 m 5 5 l S q 1 1 m 2 2 l S Q Q 3 3 m 4 4 l S",
    "clip_inherited_into_child": b"0 0 5 5 re W n q 0 0 m 5 5 l S Q 1 1 m 2 2 l S",
    "clip_after_q": b"q 0 0 5 5 re W n Q 0 0 m 5 5 l S",
    "bt": b"BT ET 0 0 m 5 5 l S",
    "path_inside_text": b"BT 0 0 m 5 5 l S ET 0 0 m 5 5 l S",
    "text_open_across_paint": b"0 0 m BT 5 5 l ET S",
    "text_clip": b"BT 7 Tr (X) Tj ET 0 0 m 5 5 l S",
    "text_clip_mode4": b"BT 4 Tr (X) Tj ET 0 0 m 5 5 l S 1 1 m 2 2 l S",
    "text_clip_empty_string": b"BT 7 Tr () Tj <> Tj [] TJ [10] TJ ET 0 0 m 5 5 l S",
    "text_clip_hex_data": b"BT 5 Tr <41> Tj ET 0 0 m 5 5 l S",
    "text_clip_array_data": b"BT 6 Tr [10 (x)] TJ ET 0 0 m 5 5 l S",
    "text_clip_dropped_by_q": b"BT 7 Tr (X) Tj q Q ET 0 0 m 5 5 l S",
    "text_clip_kept_by_q_open": b"BT 7 Tr (X) Tj q ET Q 0 0 m 5 5 l S",
    "text_clip_tr_scoped": b"BT q 7 Tr Q (X) Tj ET 0 0 m 5 5 l S",
    "text_clip_second_bt": b"BT 7 Tr (X) Tj BT ET 0 0 m 5 5 l S",
    "text_clip_in_scope": b"q BT 7 Tr (X) Tj ET Q 0 0 m 5 5 l S q 1 1 m 2 2 l S Q",
    "text_clip_without_bt": b"7 Tr (X) Tj ET 0 0 m 5 5 l S",
    "text_clip_quote": b"BT 7 Tr (X) ' ET 0 0 m 5 5 l S",
    "text_clip_dquote": b"BT 7 Tr 1 2 (X) \" ET 0 0 m 5 5 l S",
    "do": b"/X Do 0 0 m 5 5 l S q /Im0 Do Q",
    "do_in_path": b"0 0 m /X Do 5 5 l S",
    "colour_space": b"/Cs1 cs /Cs1 CS 0 0 m 5 5 l S",
    "colour_space_device": b"/DeviceRGB cs /DeviceGray CS 0 0 m 5 5 l S /Cs1 cs 1 1 m 2 2 l S /Dev#69ceCMYK cs 3 3 m 4 4 l S",
    "colour_cleared": b"/Cs1 cs /Cs2 CS 0 0 m 5 5 l S 1 g 1 1 m 2 2 l S 0 0 0 RG 3 3 m 4 4 l S",
    "colour_scoped": b"q /Cs1 cs 0 0 m 5 5 l S Q 1 1 m 2 2 l S",
    "scn_pattern": b"/P1 scn 0 0 m 5 5 l S q 1 0 0 /P2 SCN 1 1 m 2 2 l S Q",
    "scn_numbers": b"0.5 0.2 scn 0 0 m 5 5 l S 1 SCN 1 1 m 2 2 l S 1 0 0 sc 0 SC 3 3 m 4 4 l S",
    "block_with_text": b"q BT (x) Tj ET 0 0 m 5 5 l S Q q 1 0 0 1 2 2 cm 0 0 m 5 5 l S Q",
    "block_resources": b"q /GS0 gs /Cs1 cs /Cs2 CS /P1 scn 1 0 /P2#31 SCN 0 0 m 5 5 l S Q q /Cs1 cs Q",
    "block_noninert_ops": b"q /X Do 0 0 m 1 1 l S Q q 0 0 m 1 1 l S [] 0 d Q q 0 0 m 1 1 l S /T BMC EMC Q",
    "unknown_operator": b"0 0 m 5 5 l frob S",
    "unknown_with_operands": b"1 /N (s) [1] <</A 1>> weird 0 0 m 5 5 l S",
    "unknown_long_operator": b"0 0 m 5 5 l sometimeslong S 1 2 EI 3 ID",
    "unknown_inside_path": b"0 0 m 5 5 l Tf 6 6 l S",
    "unknown_block": b"q frob 0 0 m 5 5 l S Q",
    "word_with_digits": b"0 0 m 5 5 l d0 d1 S",
    "stream_split_text": [b"BT 7 Tr (X) Tj", b"ET 0 0 m 5 5 l S"],
    "stream_split_array_boundary": [b"BT [(A) 3] TJ ET", b"0 0 m 5 5 l S"],
    "comment_crosses_streams": [b"0 0 m 5 5 l S %c", b"10 10 m\n20 20 40 40 re f"],
    "comment_ends_at_stream_end": [b"0 0 m 5 5 l S %c\n", b"10 10 m 20 20 l S"],
    "dash_after_cross_stream_cm": [b"q 1 0 0 1 3 3 cm", b"[1] 0 d 0 0 m 5 5 l S Q"],
}


def _streams(v) -> list[bytes]:
    return list(v) if isinstance(v, list) else [v]


@pytest.mark.parametrize("name", sorted(MASKED))
def test_mask_stage_f_equals_g(name: str) -> None:
    assert isinstance(_outcome(_streams(MASKED[name])), VectorIndex), "the fixture must be a page G answers"
    _check(_streams(MASKED[name]), expect_scanner="F")


@pytest.mark.parametrize("name", sorted(MASKED))
@pytest.mark.parametrize("frame", [IDENT6, (0.0, 1.0, -1.0, 0.0, 612.0, 0.0)])
def test_mask_stage_under_other_frames(name: str, frame) -> None:
    assert isinstance(_outcome(_streams(MASKED[name]), frame), VectorIndex)
    _check(_streams(MASKED[name]), frame, expect_scanner="F")


STILL_G = {
    "inline_image": b"0 0 m 5 5 l S BI /W 1 ID x EI 0 0 m 1 1 l S",
    "true_word": b"true foo 0 0 m 5 5 l S",
    "false_word": b"/A false foo 0 0 m 5 5 l S",
    "null_word": b"null foo 0 0 m 5 5 l S",
    "string_across_streams": [b"BT (ab", b"cd) Tj ET 0 0 m 5 5 l S"],
    "hex_across_streams": [b"BT <41", b"42> Tj ET 0 0 m 5 5 l S"],
    "array_across_streams": [b"BT [(A)", b"(B)] TJ ET 0 0 m 5 5 l S"],
    "dict_across_streams": [b"/A <</K 1", b"/V 2>> BDC EMC 0 0 m 5 5 l S"],
}


@pytest.mark.parametrize("name", sorted(STILL_G))
def test_pages_outside_the_mask_stage_still_go_to_g_whole(name: str) -> None:
    streams = _streams(STILL_G[name])
    _check(streams, expect_scanner="G")


MASK_REFUSED = [
    b"BT (abc Tj ET 0 0 m 5 5 l S",  # unterminated string
    b"BT (a(b) Tj ET",  # unbalanced nesting
    b"BT <4g> Tj ET",  # non-hex character
    b"BT <41 Tj ET",  # unterminated hex string
    b"[1 2 3 0 d",  # unterminated array
    b"/A <</K 1 BDC EMC",  # unterminated dictionary
    b"/A <</K>> BDC EMC",  # a key and no value
    b"/A <<1 2>> BDC EMC",  # a key that is not a name
    b"/A <</K 1 ] BDC EMC",  # mismatched closer
    b"0 0 m 5 5 l ) S",
    b"0 0 m 5 5 l > S",
    b"0 0 m 5 5 l { S",
    b"0 0 m 5 5 l } S",
    b"0 0 m 5 5 l < S",
    b"EMC",
    b"/OC /A BDC EMC EMC",
    b"(x) 0 0 m 5 5 l S",
    b"[1] w 0 0 m 5 5 l S",
    b"/N Tj",
    b"Tj",
    b"(a) (b) Tj",
    b"(a) TJ",
    b"7.5 Tr",
    b"8 Tr",
    b"-1 Tr",
    b"/N Tr",
    b"[a] 0 d",
    b"[(a)] 0 d",
    b"[[1]] 0 d",
    b"[1] d",
    b"0 [1] d",
    b"/A 3 BDC",
    b"3 /A BDC",
    b"/A BDC",
    b"/A /B /C BDC",
    b"/A (s) BDC",
    b"/A /B Do",
    b"Do",
    b"1 Do",
    b"/P 1 scn",
    b"1 /P /Q scn",
    b"(x) scn",
    b"/P sc",
    b"1 /P SC",
    b"/A cs /B",
    b"1 cs",
    b"/A /B cs",
    b"1 2 \" ",
    b"1 (x) \"",
    b"(x) 1 2 \"",
    b"1 2 (x) (y) \"",
    b"/N BMC /M",
    b"1 BMC",
    b"BT 1 ET",
    b"1 BT",
    b"1 q",
    b"/A W",
    b"1 W*",
    b"[1 2] 3 4 d",
    b"<< >> 0 d",
]


@pytest.mark.parametrize("body", MASK_REFUSED, ids=[str(i) for i in range(len(MASK_REFUSED))])
def test_mask_stage_refusals_match_g(body: bytes) -> None:
    _check([body])


def test_a_comment_does_not_hide_an_operator_from_the_next_stream() -> None:
    # G joins a comment that ran to the end of one stream with the first line of the next
    _check([b"0 0 m 5 5 l S %c", b"10 10 m\n20 20 l S"], expect_scanner="F")


_NAMES2 = [b"/GS0", b"/Cs1", b"/DeviceRGB", b"/DeviceGray", b"/P1", b"/OC", b"/Span", b"/Dev#69ceCMYK", b"/O#43", b"/X"]
_STRS = [b"(abc)", b"()", b"(a(b)c)", b"(a\\)b)", b"(\\\\)", b"(\\()", b"<41>", b"<>", b"<4 1 4 2>", b"(a\nb)", b"(x y)"]
_UNKNOWN = [b"Tf", b"Td", b"Tm", b"TL", b"T*", b"Tc", b"Tw", b"Tz", b"Ts", b"sh", b"d0", b"d1", b"frob", b"BX", b"EX", b"MP"]


def _string(rng: random.Random, tight: bool) -> bytes:
    s = rng.choice(_STRS)
    return s.replace(b" ", b"").replace(b"\n", b"") if tight else s


def _program2(seed: int, sloppy: bool) -> list[bytes]:
    """Programs over the whole mask-stage vocabulary; non-sloppy streams are cut between tokens."""
    rng = random.Random(seed)
    units: list[bytes] = []
    depth = 0
    mc = 0
    have_cur = False
    for _ in range(rng.randint(8, 150)):
        r = rng.random()
        if r < 0.07:
            units.append(b"q")
            depth += 1
        elif r < 0.13 and (depth > 0 or sloppy):
            units.append(b"Q")
            depth -= 1
        elif r < 0.20:
            args = [_num(rng, sloppy) for _ in range(6)]
            if rng.random() < 0.7:
                args[:4] = [b"1", b"0", b"0", b"1"]
            units.append(b" ".join(args + [b"cm"]))
        elif r < 0.38:
            op = rng.choice(_PATH_OPS)
            if not have_cur and not sloppy and op in (b"l", b"c", b"v", b"y"):
                op = rng.choice([b"m", b"re"])
            if op in (b"m", b"re"):
                have_cur = True
            units.append(b" ".join([_num(rng, sloppy) for _ in range(_ARITY[op])] + [op]))
        elif r < 0.50:
            have_cur = False
            units.append(rng.choice(_PAINTS))
        elif r < 0.54:
            op = rng.choice([b"w", b"J", b"j", b"M", b"i", b"g", b"G", b"rg", b"RG", b"k", b"K"])
            units.append(b" ".join([_num(rng, sloppy) for _ in range(_ARITY[op])] + [op]))
        elif r < 0.58:
            units.append(rng.choice([b"/GS0", b"/GS#41", b"/Perceptual"]) + b" " + rng.choice([b"gs", b"ri"]))
        elif r < 0.62:
            units.append(rng.choice([b"BT", b"ET", b"BT", b"ET"]))
        elif r < 0.66:
            units.append(b"%d Tr" % rng.randint(0, 7) if rng.random() < 0.95 or not sloppy else b"9 Tr")
        elif r < 0.74:
            show = rng.choice([b"Tj", b"'", b"Tj"])
            units.append(_string(rng, not sloppy) + b" " + show)
        elif r < 0.77:
            parts = [rng.choice([_string(rng, not sloppy), b"-20", b"10", b"3.5"]) for _ in range(rng.randint(0, 4))]
            units.append(b"[" + b"".join(parts) + b"] TJ" if not sloppy else b"[" + b" ".join(parts) + b"] TJ")
        elif r < 0.79:
            units.append(b" ".join([_num(rng, False), _num(rng, False), _string(rng, not sloppy), b'"']))
        elif r < 0.82:
            units.append(b" ".join([rng.choice(_UNKNOWN)]))
            if rng.random() < 0.5:
                units[-1] = b" ".join([_num(rng, False) for _ in range(rng.randint(0, 3))] + [units[-1]])
        elif r < 0.85:
            op = rng.choice([b"W", b"W*"])
            units.append(op)
        elif r < 0.89 and (mc > 0 or rng.random() < 0.7 or sloppy):
            k = rng.random()
            if k < 0.35 or mc == 0 and not sloppy:
                tag = rng.choice([b"/OC", b"/Span", b"/O#43"])
                if rng.random() < 0.5:
                    units.append(tag + b" " + rng.choice(_NAMES2) + b" BDC")
                else:
                    units.append(tag + b" <</MCID 0/K[1 2]>> BDC")
                mc += 1
            elif k < 0.5:
                units.append(rng.choice([b"/A", b"/OC"]) + b" BMC")
                mc += 1
            else:
                units.append(b"EMC")
                mc -= 1
        elif r < 0.91:
            units.append(rng.choice(_NAMES2) + b" Do")
        elif r < 0.95:
            op = rng.choice([b"cs", b"CS"])
            units.append(rng.choice(_NAMES2) + b" " + op)
        elif r < 0.97:
            op = rng.choice([b"sc", b"SC", b"scn", b"SCN"])
            nums = b" ".join(_num(rng, False) for _ in range(rng.randint(0, 4)))
            tail = b" " + rng.choice(_NAMES2) if op in (b"scn", b"SCN") and rng.random() < 0.5 else b""
            units.append((nums + tail + b" " + op).strip())
        elif r < 0.985:
            units.append(b"[" + b" ".join(_num(rng, False) for _ in range(rng.randint(0, 3))) + b"] " + _num(rng, False) + b" d")
        elif sloppy:
            units.append(rng.choice([b"(unterminated", b"<4g> Tj", b"1 2 3 4 m", b"EMC", b"] ", b">>", b"% c\n", b"[1 (a) <</A 1>> ] TJ"]))
        else:
            units.append(rng.choice([b"% comment\n", b"%x", b"0 0 m 4 4 l S"]))
    body = b""
    cuts_ok: list[int] = []
    for u in units:
        body += u
        cuts_ok.append(len(body))
        sep = rng.choice(_WS)
        if u.endswith(b"%x") or u.startswith(b"%"):
            sep = b"\n"
        body += sep
        cuts_ok.append(len(body))
    if rng.random() < 0.3:
        body = body.rstrip()
    where = list(range(len(body) + 1)) if sloppy else [c for c in cuts_ok if c <= len(body)]
    cuts = sorted(set(rng.sample(where, k=min(rng.randint(0, 3), len(where)))))
    parts, last = [], 0
    for c in cuts:
        parts.append(body[last:c])
        last = c
    parts.append(body[last:])
    return parts


@pytest.mark.parametrize("seed", range(1000, 1300))
def test_fuzz_mask_stage_f_equals_g(seed: int) -> None:
    _check(_program2(seed, sloppy=False))


@pytest.mark.parametrize("seed", range(2000, 2300))
def test_fuzz_mask_stage_sloppy_f_equals_g_or_refuses_like_g(seed: int) -> None:
    _check(_program2(seed, sloppy=True))


def test_fuzz_mask_stage_pages_run_on_f_unless_g_refuses() -> None:
    ran = 0
    total = 0
    for seed in range(3000, 3060):
        parts = _program2(seed, sloppy=False)
        g = _outcome(parts)
        if isinstance(g, VectorIndex):
            total += 1
            f = scan_page(parts, PAGE, accelerated=True)
            assert f.scanner == "F", f"seed {seed} fell back"
            ran += 1
    assert ran >= 15


def _program3(seed: int) -> list[bytes]:
    """Leaf blocks (q ... Q) holding inert and non-inert operators, resources, a cm or an open path at the edges."""
    rng = random.Random(seed)
    inert = [b"0 0 m 5 5 l S", b"1 0 0 1 3 3 cm", b"2 w", b"/GS0 gs", b"/Cs1 cs", b"/P1 scn", b"1 0 0 rg", b"[3] 0 d", b"/Perceptual ri",
             b"0 0 5 5 re f", b"0 0 m 4 4 l s", b"1 0 0 /P2 SCN"]
    other = [b"n", b"W n", b"BT ET", b"/X Do", b"7 Tr", b"(x) Tj", b"/OC /A BDC", b"EMC", b"/T BMC", b"frob", b"[1] TJ", b"0 0 m 1 1 l n"]
    out: list[bytes] = []
    for _ in range(rng.randint(1, 12)):
        body = [rng.choice(inert) for _ in range(rng.randint(0, 5))]
        if rng.random() < 0.35:
            body.insert(rng.randint(0, len(body)), rng.choice(other))
        if rng.random() < 0.15:
            out.append(b"0 0 m")  # a path open across the q
        out.append(b"q " + b" ".join(body) + b" Q")
    return [b" ".join(out)]


@pytest.mark.parametrize("seed", range(4000, 4150))
def test_fuzz_blocks_f_equals_g(seed: int) -> None:
    _check(_program3(seed))


def test_the_mask_stage_fuzz_reaches_every_flag_and_the_block_columns() -> None:
    bits = 0
    inert = resources = 0
    for seed in [*range(1000, 1100), *range(4000, 4100)]:
        parts = _program2(seed, sloppy=False) if seed < 4000 else _program3(seed)
        if isinstance(_outcome(parts), VectorIndex):
            f = scan_page(parts, PAGE, accelerated=True)
            if f.scanner != "F":
                continue
            for flag in f.paths["flags"].tolist():
                bits |= int(flag)
            inert += int(f.blocks["inert"].sum())
            resources += sum(1 for r in f.block_resources if r)
    for flag in (1, 2, 4, 8, 16, 32, 64, 256):  # CTM_SINGULAR (128) is pinned by its own fixtures
        assert bits & flag, f"the fuzz never produced flag {flag}"
    assert inert >= 20 and resources >= 20


# ----------------------------------------------------------------------------- Astra review of the mask stage (2026-11-25)

SIGNED_ZERO_FRAME = (-1.0, 0.0, -0.0, 1.0, -0.0, 0.0)


@pytest.mark.parametrize("tail", [b"", b"%"])
@pytest.mark.parametrize(
    "body",
    [
        b"0 0 m -0 0 l h 1 0 l S",  # the current point equals the subpath start in value, not in sign: h keeps it
        b"0 0 m -0 0 l h 1 0 1 0 v S",
        b"0 0 m -0 0 l h h 1 0 l S",
        b"-0 0 m 0 0 l h 1 0 l S",
        b"0 0 m 0 -0 l h 1 0 2 0 3 0 c S",
        b"0 0 m 5 5 l h h 1 0 l S",
        b"5 5 m h 1 0 l S",
    ],
)
def test_h_keeps_the_current_point_when_it_equals_the_subpath_start(body: bytes, tail: bytes) -> None:
    _check([body + tail], SIGNED_ZERO_FRAME, expect_scanner="F")


@pytest.mark.parametrize("cap", range(1, 14))
@pytest.mark.parametrize(
    "body",
    [
        b"0 0 0 0 re h",
        b"0 0 0 0 re",
        b"0 0 m 1 1 l 2 2 l S 3 3 m 4 4 l",
        b"0 0 m 1 1 l S 0 0 0 0 re h",
        b"0 0 m 1 2 3 4 5 6 c S 0 0 m 1 1 l 2 2 l",
        b"0 0 0 0 re f 1 1 1 1 re f 5 5 m",
        b"0 0 m 1 1 l h h h",
    ],
)
def test_the_segment_row_cap_counts_pending_primitives_like_g(monkeypatch: pytest.MonkeyPatch, cap: int, body: bytes) -> None:
    from model.vector_paths import scan as scan_mod

    monkeypatch.setattr(scan_mod, "MAX_SEGMENT_ROWS", cap)
    _check([body], IDENT6)
    _check([body + b"%"], IDENT6)


_ZEROS = [b"0", b"-0", b"0.0", b"-0.0", b"1", b"-1", b".0", b"+0"]


def _program4(seed: int) -> list[bytes]:
    """Paths made of signed zeros and h: the current point and the subpath start are equal in value, not in sign."""
    rng = random.Random(seed)
    out: list[bytes] = []
    for _ in range(rng.randint(2, 12)):
        r = rng.random()
        z = lambda n: b" ".join(rng.choice(_ZEROS) for _ in range(n))  # noqa: E731
        if r < 0.25:
            out.append(z(2) + b" m")
        elif r < 0.45:
            out.append(z(2) + b" l")
        elif r < 0.55:
            out.append(z(6) + b" c")
        elif r < 0.60:
            out.append(z(4) + b" v")
        elif r < 0.65:
            out.append(z(4) + b" re")
        elif r < 0.85:
            out.append(b"h")
        else:
            out.append(rng.choice([b"S", b"f", b"B", b"s", b"n"]))
    return [b" ".join(out)]


@pytest.mark.parametrize("seed", range(6000, 6250))
@pytest.mark.parametrize("frame", [SIGNED_ZERO_FRAME, IDENT6, (0.0, -0.0, -0.0, 0.0, -0.0, 0.0)])
def test_fuzz_signed_zero_paths_f_equals_g(seed: int, frame) -> None:
    _check(_program4(seed), frame)


@pytest.mark.parametrize("seed", range(7000, 7120))
def test_fuzz_the_row_cap_at_small_values_f_equals_g(monkeypatch: pytest.MonkeyPatch, seed: int) -> None:
    from model.vector_paths import scan as scan_mod

    rng = random.Random(seed)
    monkeypatch.setattr(scan_mod, "MAX_SEGMENT_ROWS", rng.randint(1, 40))
    _check(_program2(seed, sloppy=False), IDENT6)
    _check(_program4(seed), IDENT6)


@pytest.mark.parametrize("seed", range(8000, 8040))
def test_every_construction_prefix_has_the_same_outcome_under_small_caps(monkeypatch: pytest.MonkeyPatch, seed: int) -> None:
    """The class check Astra named for pending-versus-emitted accounting: G's public outcome at every prefix, caps swept."""
    from model.vector_paths import scan as scan_mod

    rng = random.Random(seed)
    body = b" ".join(_program4(seed)) if seed % 2 else b" ".join(_program2(seed, sloppy=False))
    cuts = [i for i, ch in enumerate(body) if ch == 0x20][:60]
    for cap in (rng.randint(1, 6), rng.randint(6, 30)):
        monkeypatch.setattr(scan_mod, "MAX_SEGMENT_ROWS", cap)
        for c in cuts:
            _check([body[:c]], IDENT6)
