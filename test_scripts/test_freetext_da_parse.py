"""``AnnotationTool._freetext_style`` parses a FreeText ``/DA`` in linear time.

The ``/DA`` string comes straight from the opened PDF.  The original patterns
(``-?\\d*\\.?\\d+`` with two digit quantifiers, ``/(\\S+)`` tried at every
slash) backtracked cubically on a long digit run, quadratically on a long
non-space run and as a high power of the token length on number tokens
before a failing tail, so a few-KB ``/DA`` froze the GUI thread during a text
edit or redaction (F12).  The rewrite must give the same result as the
original for every ``/DA``; ``_reference_freetext_style`` keeps the original.
"""

from __future__ import annotations

import logging
import random
import re
import time

import fitz
import pytest

from model.tools.annotation_tool import AnnotationTool

logger = logging.getLogger(__name__)

# The three patterns of the base revision, verbatim.
_OLD_SIZE_RE = r"(-?\d*\.?\d+)\s+Tf(?!\w)"
_OLD_FONT_RE = r"/(\S+)\s+-?\d*\.?\d+\s+Tf(?!\w)"
_OLD_COLOUR_RE = r"((?:-?\d*\.?\d+\s+){1,4})(rg|g|k)(?!\w)"

# Generous for the linear parser (about 2 ms on these inputs); the original
# took 2.5-5.5 s on each of them when this test was written.
_TIME_BOUND_S = 0.5

_NONE = {"fontsize": None, "fontname": None, "text_color": None, "rotate": 0}


def _reference_freetext_style(doc: fitz.Document, xref: int) -> dict:
    """The base revision's ``_freetext_style`` body, pattern literals hoisted above."""
    style: dict = {"fontsize": None, "fontname": None, "text_color": None, "rotate": 0}
    try:
        kind, da = doc.xref_get_key(xref, "DA")
        if kind == "string":
            size = re.search(_OLD_SIZE_RE, da)
            if size and float(size.group(1)) > 0:
                style["fontsize"] = float(size.group(1))
            font = re.search(_OLD_FONT_RE, da)
            if font:
                style["fontname"] = font.group(1)
            # The last colour operator before the text wins.
            operators = list(re.finditer(_OLD_COLOUR_RE, da))
            if operators:
                values = tuple(float(v) for v in operators[-1].group(1).split())
                if len(values) == {"g": 1, "rg": 3, "k": 4}[operators[-1].group(2)]:
                    style["text_color"] = values
        kind, rotate = doc.xref_get_key(xref, "Rotate")
        if kind == "int":
            style["rotate"] = int(rotate) % 360
    except Exception as exc:
        logger.warning("_reference_freetext_style: xref %s: %s", xref, exc)
    return style


@pytest.fixture(scope="module")
def freetext():
    doc = fitz.open()
    page = doc.new_page()
    annot = page.add_freetext_annot(fitz.Rect(10, 10, 200, 60), "x")
    xref = annot.xref
    assert doc.xref_get_key(xref, "Rotate") == ("null", "null")
    yield doc, xref
    doc.close()


def _set_da(doc: fitz.Document, xref: int, da: str) -> None:
    """Store ``da`` as a UTF-16BE hex string, which PyMuPDF hands back unchanged."""
    doc.xref_set_key(xref, "DA", "<FEFF" + da.encode("utf-16-be").hex() + ">")
    assert doc.xref_get_key(xref, "DA") == ("string", da)


def _assert_same_as_reference(doc: fitz.Document, xref: int) -> dict:
    got = AnnotationTool._freetext_style(doc, xref)
    want = _reference_freetext_style(doc, xref)
    # repr also separates -0.0 from 0.0 and int from float.
    assert repr(got) == repr(want)
    return got


# ── (a) pathological /DA strings finish in linear time ──────────────────────

_PATHOLOGICAL = [
    pytest.param("0" * 1200, _NONE, id="long-digit-run"),
    pytest.param(
        "0" * 1200 + " /Helv 9 Tf 1 0 0 rg",
        {"fontsize": 9.0, "fontname": "Helv", "text_color": (1.0, 0.0, 0.0), "rotate": 0},
        id="long-digit-run-then-valid-da",
    ),
    pytest.param("-" + "0" * 750 + "." + "0" * 750, _NONE, id="long-signed-decimal-run"),
    pytest.param("/" * 30000, _NONE, id="long-slash-run"),
    pytest.param(
        "/" * 30000 + " x /F1 12 Tf",
        {"fontsize": 12.0, "fontname": "F1", "text_color": None, "rotate": 0},
        id="long-slash-run-then-valid-da",
    ),
    pytest.param("/a" * 20000, _NONE, id="long-non-space-run"),
    pytest.param(" ".join(["1" * 30] * 4) + " x", _NONE, id="number-tokens-failing-tail"),
    pytest.param(
        " ".join(["1" * 30] * 4) + " x 0.5 g",
        {"fontsize": None, "fontname": None, "text_color": (0.5,), "rotate": 0},
        id="number-tokens-failing-tail-then-g",
    ),
]


@pytest.mark.parametrize(("da", "expected"), _PATHOLOGICAL)
def test_pathological_da_parses_within_time_bound(freetext, da: str, expected: dict) -> None:
    doc, xref = freetext
    _set_da(doc, xref, da)
    start = time.perf_counter()
    style = AnnotationTool._freetext_style(doc, xref)
    elapsed = time.perf_counter() - start
    assert elapsed < _TIME_BOUND_S, f"_freetext_style took {elapsed:.3f} s on a {len(da)}-char /DA"
    assert style == expected


@pytest.mark.parametrize("unit", ["0", "/", "/a", "-5", ".5", "1.", "1 ", "1 1 1 1 x ", "/a 1 Tg "])
def test_parse_time_stays_bounded_as_the_da_doubles(freetext, unit: str) -> None:
    """Each shape repeated to 1 KB, 2 KB, ... 256 KB stays under the bound.

    Doubling makes a super-linear parser fail at the first size it cannot
    finish in time instead of hanging on a huge input.
    """
    doc, xref = freetext
    for step in range(9):
        da = unit * ((1024 << step) // len(unit))
        _set_da(doc, xref, da)
        start = time.perf_counter()
        AnnotationTool._freetext_style(doc, xref)
        elapsed = time.perf_counter() - start
        assert elapsed < _TIME_BOUND_S, f"{unit!r} x {len(da)} chars: {elapsed:.3f} s"


# ── (b) same result as the original for every /DA ───────────────────────────

_HAND_CASES = [
    "",
    "0 g /Helv 11 Tf",
    "1 0 0 rg /Helv 9 Tf",
    "/Helv 9.0 Tf 0 0 1 rg",
    "1 0 0 rg\n/Helv 12 Tf\n",
    # numbers: signs, leading/trailing dots, junk inside the token
    "1.2.3 Tf",
    "1-2 Tf",
    "--1 Tf",
    "+1 Tf",
    "0. Tf",
    "5. Tf",
    ".5 Tf",
    "-.5 Tf",
    "0 Tf",
    "-0 Tf",
    "-1 Tf",
    "1e5 Tf",
    "x9 Tf",
    "- 9 Tf",
    ". 9 Tf",
    "9 Tfx",
    "9 Tf_",
    "9 Tf/",
    "9 Tf",
    "9\tTf",
    "9\nTf",
    "9 Tf",
    "9　Tf",
    "9Tf",
    "١٢ Tf",
    "-١.٥ Tf",
    # font names: the first slash of the leftmost workable token wins
    "/A/B 3 Tf",
    "x/A 3 Tf",
    "// 3 Tf",
    "/ 3 Tf",
    "/A/ 2 Tf",
    "/A 1 Tf /B 2 Tf",
    "/A x /B 2 Tf",
    "/A /B 2 Tf",
    "/A 2.5.1 Tf",
    "/A -2 Tf",
    "/A +2 Tf",
    "/A .5 Tf",
    "/A 5. Tf",
    "/A\t\n 7 \tTf",
    "/A 7 Tfa /B 8 Tf",
    "/é 7 Tf",
    # colour operators: the last match of finditer wins
    "1 0 0 rg 0.5 g",
    "0.5 g 1 0 0 rg",
    "0 0 1 rg 1 0 0 rg",
    "1 0 0 0 0 rg",
    "1 0 0 0 k",
    "1 0 rg",
    "1 0 0 rgb",
    "1 0 0 RG",
    "0 g1",
    "0 g/",
    "-0 g",
    "x1 0 0 rg",
    "1.5.5 0 0 rg",
    "- 1 g",
    "1 2 3 4 5 6 rg",
    "1 2 3 4 5 6 rg 0 g",
    ".5 .5 .5 rg",
    "5. 0 0 rg",
    "0.25 0.5 0.75 0 k /F 3 Tf",
    "1 1 1 1 1 1 1 1 1 1 x 0 g",
    "١ g",
    "1 0 0 rg0 g",
    "1 0 0 rg 0 g 0 0 0 1 k",
    "0 g 1 0 0 rg",
]


@pytest.mark.parametrize("da", _HAND_CASES)
def test_hand_cases_match_the_original_parser(freetext, da: str) -> None:
    doc, xref = freetext
    _set_da(doc, xref, da)
    _assert_same_as_reference(doc, xref)


@pytest.mark.parametrize(
    ("da", "expected"),
    [
        ("1 0 0 rg /Helv 9 Tf", {"fontsize": 9.0, "fontname": "Helv", "text_color": (1.0, 0.0, 0.0), "rotate": 0}),
        ("1.2.3 Tf", {**_NONE, "fontsize": 2.3}),
        ("1e5 Tf", {**_NONE, "fontsize": 5.0}),
        ("0. Tf", _NONE),
        ("-.5 Tf", _NONE),
        ("/A/B 3 Tf", {**_NONE, "fontsize": 3.0, "fontname": "A/B"}),
        ("x/A 3 Tf", {**_NONE, "fontsize": 3.0, "fontname": "A"}),
        ("/A 1 Tf /B 2 Tf", {**_NONE, "fontsize": 1.0, "fontname": "A"}),
        ("1 0 0 rg 0.5 g", {**_NONE, "text_color": (0.5,)}),
        ("1 0 0 0 0 rg", _NONE),
        ("1.5.5 0 0 rg", {**_NONE, "text_color": (5.5, 0.0, 0.0)}),
    ],
)
def test_hand_cases_pin_the_leftmost_and_last_match_choices(freetext, da: str, expected: dict) -> None:
    doc, xref = freetext
    _set_da(doc, xref, da)
    assert _assert_same_as_reference(doc, xref) == expected


@pytest.mark.parametrize(
    "raw",
    ["/Helv", "12", "[1 0 0]", "null"],
    ids=["name", "int", "array", "null"],
)
def test_non_string_da_falls_back_like_the_original(freetext, raw: str) -> None:
    doc, xref = freetext
    doc.xref_set_key(xref, "DA", raw)
    assert doc.xref_get_key(xref, "DA")[0] != "string"
    assert _assert_same_as_reference(doc, xref) == _NONE


_NUMBERS = [
    "0", "1", "9", "12", "007", "-1", "-0", "0.", "5.", ".5", "-.5", "1.5", "-1.25", "1..5", "--1",
    "1-2", "+1", "5.5.5", "1e5", ".", "-", "-.", "١", "-١.٢", "0.0.0", "x1", "1x",
]
_OPERATORS = ["Tf", "rg", "g", "k", "Tfx", "Tf_", "rgb", "gs", "kk", "K", "RG", "G", "Tj", "re"]
_NAMES = ["/Helv", "/F1", "/A/B", "/", "//", "/a.b", "/1", "x/A", "/A/", "/é"]
_JUNK = ["x", "[", "]", "(", ")", "\\", "<<", "BT", "_"]
_SEPARATORS = [" ", " ", " ", " ", "  ", "\t", "\n", "\r", "\r\n", "\x0b", "\x0c", " ", "　", ""]
_CHARS = "0123456789.-+/ \t\n\x0b\x0cTfrgkx_١ "


def _random_token_da(rng: random.Random) -> str:
    parts: list[str] = []
    for _ in range(rng.randint(0, 6)):
        shape = rng.random()
        if shape < 0.35:  # a colour operator, sometimes with the wrong arity
            parts += [rng.choice(_NUMBERS) for _ in range(rng.randint(0, 6))]
            parts.append(rng.choice(["rg", "g", "k", rng.choice(_OPERATORS)]))
        elif shape < 0.65:  # a font operator
            parts += [rng.choice(_NAMES), rng.choice(_NUMBERS), rng.choice(["Tf", rng.choice(_OPERATORS)])]
        else:
            parts.append(rng.choice(_NUMBERS + _OPERATORS + _NAMES + _JUNK))
    return "".join(part + rng.choice(_SEPARATORS) for part in parts)


def _random_char_da(rng: random.Random) -> str:
    return "".join(rng.choice(_CHARS) for _ in range(rng.randint(0, 40)))


def test_seeded_random_da_strings_match_the_original_parser(freetext) -> None:
    doc, xref = freetext
    rng = random.Random(20261104)
    hits = {"fontsize": 0, "fontname": 0, "text_color": 0}
    size_mid_token = font_mid_token = colour_multi = 0
    for i in range(6000):
        da = _random_token_da(rng) if i % 2 else _random_char_da(rng)
        _set_da(doc, xref, da)
        got = _assert_same_as_reference(doc, xref)
        for key in hits:
            hits[key] += got[key] is not None
        size = re.search(_OLD_SIZE_RE, da)
        size_mid_token += bool(size and size.start() > 0 and not da[size.start() - 1].isspace())
        font = re.search(_OLD_FONT_RE, da)
        font_mid_token += bool(font and font.start() > 0 and not da[font.start() - 1].isspace())
        colour_multi += len(list(re.finditer(_OLD_COLOUR_RE, da))) > 1
    # The comparison is not vacuous: every field is parsed, and leftmost
    # matches that start inside a token and repeated operators both occur.
    assert min(hits.values()) >= 300, hits
    assert size_mid_token >= 50, size_mid_token
    assert font_mid_token >= 20, font_mid_token
    assert colour_multi >= 100, colour_multi
