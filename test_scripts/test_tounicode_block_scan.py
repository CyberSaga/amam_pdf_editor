"""ToUnicode block scan in ``parse_tounicode_strict`` (CWE-1333).

The strict parser used to find its ``bfchar`` / ``bfrange`` blocks with two
lazy ``re.findall`` scans, ``(\\d+)\\s+beginbfchar(.*?)endbfchar`` and its
``bfrange`` twin.  For every counted ``begin`` with no ``end`` after it the
lazy body walked to the end of the buffer, so a 2 MiB stream of repeated
``1 beginbfchar `` (a few KB once Flate-compressed) froze the GUI thread for
many minutes.  These tests pin that the linear replacement is fast on those
inputs AND returns exactly what the legacy scans returned: the parse result
must not change for any input, including truncated streams whose valid
prefix the legacy ``findall`` kept.
"""
from __future__ import annotations

import random
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.cid_fonts as cid_fonts  # noqa: E402
from model.text_commit.cid_fonts import (  # noqa: E402
    _MAX_TOUNICODE_BYTES,
    CidCapabilityFailure,
    ToUnicodeMap,
    parse_tounicode_strict,
)
from model.text_commit.dto import RejectReason  # noqa: E402

# The legacy scans, kept verbatim as the equivalence oracle.
_LEGACY_SCANS = {
    b"beginbfchar": re.compile(rb"(\d+)\s+beginbfchar(.*?)endbfchar", re.DOTALL),
    b"beginbfrange": re.compile(
        rb"(\d+)\s+beginbfrange(.*?)endbfrange", re.DOTALL
    ),
}
_FAMILIES = (
    (b"beginbfchar", b"endbfchar"),
    (b"beginbfrange", b"endbfrange"),
)
_NO_RECORDS = "no bfchar or bfrange records"
_TIME_BOUND_SECONDS = 1.0


def _legacy_blocks(data: bytes, begin: bytes, end: bytes) -> list[tuple[bytes, bytes]]:
    return _LEGACY_SCANS[begin].findall(data)


def _up_to_budget(prefix: bytes, unit: bytes) -> bytes:
    """``prefix`` plus as many ``unit`` repeats as fit the 2 MiB budget: one
    byte over and the parser refuses on size before any scan runs."""
    data = prefix + unit * ((_MAX_TOUNICODE_BYTES - len(prefix)) // len(unit))
    assert len(data) <= _MAX_TOUNICODE_BYTES
    assert len(data) > _MAX_TOUNICODE_BYTES - len(unit)
    return data


# Inputs the legacy scans took seconds (10k repeats, the 30k-digit runs) to
# many minutes (the ~2 MiB streams) on.  None holds a complete block.
_SLOW_INPUTS = {
    "bfchar_10k": b"1 beginbfchar " * 10_000,
    "bfrange_10k": b"1 beginbfrange " * 10_000,
    "bfchar_2mib": _up_to_budget(b"", b"1 beginbfchar "),
    "bfrange_2mib": _up_to_budget(b"", b"1 beginbfrange "),
    "mixed_2mib": _up_to_budget(b"", b"1 beginbfchar 2 beginbfrange "),
    "uncounted_2mib": _up_to_budget(b"", b"beginbfchar beginbfrange "),
    "digits_30k": b"1" * 30_000,
    "digits_30k_bfchar": b"1" * 30_000 + b" beginbfchar <0001> <0041>",
    "digits_30k_bfrange": b"1" * 30_000 + b" beginbfrange <0001> <0002> <0041>",
}


@pytest.mark.parametrize("case", sorted(_SLOW_INPUTS))
def test_unterminated_blocks_are_refused_in_linear_time(case: str) -> None:
    data = _SLOW_INPUTS[case]
    started = time.perf_counter()
    result = parse_tounicode_strict(data)
    elapsed = time.perf_counter() - started
    assert elapsed < _TIME_BOUND_SECONDS, (case, elapsed)
    # Same verdict and detail as the legacy findall scans: a counted begin
    # with no end is dropped, so these streams hold no block at all.
    assert isinstance(result, CidCapabilityFailure), (case, result)
    assert result.reason == RejectReason.TYPE0_TOUNICODE_UNPARSEABLE
    assert result.detail == _NO_RECORDS, (case, result.detail)


def test_bare_exploit_stream_keeps_the_no_records_detail() -> None:
    result = parse_tounicode_strict(b"1 beginbfchar ")
    assert result == CidCapabilityFailure(
        RejectReason.TYPE0_TOUNICODE_UNPARSEABLE, _NO_RECORDS
    )


@pytest.mark.parametrize(
    ("stream", "records"),
    [
        (
            b"1 beginbfchar <0001> <0041> endbfchar\n1 beginbfchar <0002> <00",
            (("char", 1, 1, "A"),),
        ),
        (
            b"1 beginbfrange <0010> <0011> <0058> endbfrange\n"
            b"1 beginbfrange <0020> <00",
            (("range", 0x10, 0x11, "X"),),
        ),
        (
            b"1 beginbfchar <0001> <0041> endbfchar\n"
            b"1 beginbfrange <0010> <0011> <0058> endbfrange\n"
            b"1 beginbfchar <0002> <0042>\n1 beginbfrange <0020>",
            (("char", 1, 1, "A"), ("range", 0x10, 0x11, "X")),
        ),
    ],
    ids=["bfchar", "bfrange", "both"],
)
def test_valid_prefix_survives_an_unterminated_tail(
    stream: bytes, records: tuple[tuple[str, int, int, str], ...]
) -> None:
    """The legacy findall kept every block before a counted begin that never
    ends; a damaged tail must not turn an accepted CMap into a refusal."""
    result = parse_tounicode_strict(stream)
    assert result == ToUnicodeMap(records=records), result


def test_valid_prefix_survives_a_2mib_unterminated_tail_in_linear_time() -> None:
    data = _up_to_budget(
        b"1 beginbfchar <0001> <0041> endbfchar\n", b"1 beginbfchar "
    )
    started = time.perf_counter()
    result = parse_tounicode_strict(data)
    elapsed = time.perf_counter() - started
    assert elapsed < _TIME_BOUND_SECONDS, elapsed
    assert result == ToUnicodeMap(records=(("char", 1, 1, "A"),)), result


_HAND_CASES = (
    b"",
    b"1 beginbfchar",
    b"beginbfchar <0001> <0041> endbfchar",  # uncounted
    b"1beginbfchar <0001> <0041> endbfchar",  # no whitespace
    b"1 2 beginbfchar <0001> <0041> endbfchar",  # count is the last run
    b"x12\t\r\n\x0b\x0c beginbfchar <0001> endbfchar",
    b"1\x00beginbfchar <0001> endbfchar",  # NUL is PDF, not regex, space
    b"1\xa0beginbfchar <0001> endbfchar",
    b"endbfchar 1 beginbfchar <0001> <0041>",  # end before begin
    b"1 beginbfchar 1 beginbfchar <01> endbfchar endbfchar",  # nested begin
    b"beginbfchar 1 beginbfchar x endbfchar 1 beginbfchar",
    b"1 beginbfchar a endbfchar1 beginbfchar b endbfchar",
    b"1 beginbfchar a endbfchar 2 beginbfchar b endbfchar 3 beginbfchar c",
    b"1 beginbfrange a endbfrange 1 beginbfchar b endbfrange endbfchar",
    b"1 beginbfchar a endbfrange 1 beginbfrange b endbfchar",
    b"007 beginbfrange <0001> <0002> <0041> endbfrange",
)

# Weighted token soup: both keyword families and their terminators,
# near-misses, digits glued to keywords, regex and non-regex whitespace, and
# real records so some streams parse.  No terminator is ever forced on.
_TOKENS = (
    b"beginbfchar", b"endbfchar", b"beginbfrange", b"endbfrange",
    b"1 beginbfchar", b"2 beginbfchar", b"1 beginbfrange", b"2 beginbfrange",
    b"1 beginbfchar <0001> <0041> endbfchar",
    b"1 beginbfrange <0010> <0011> <0058> endbfrange",
    b"1 beginbfrange <0010> <0011> [<0041> <0042>] endbfrange",
    b"beginbfcha", b"bfchar", b"endbfran", b"begin", b"end", b"rbfchar",
    b"1beginbfchar", b"2beginbfrange",
    b"0", b"1", b"1", b"2", b"12", b"007", b"9",
    b" ", b" ", b"  ", b"\t", b"\n", b"\r", b"\r\n", b"\x0b", b"\x0c",
    b"\x00", b"\xa0", b"\x85", b"\x1c",
    b"<0001>", b"<0002>", b"<0041>", b"<0042>", b"<00 43>", b"<00",
    b"[", b"]", b"x", b"/Foo", b"%c\n", b"%",
)


def _random_streams(count: int) -> list[bytes]:
    rng = random.Random(20261104)
    return [
        b"".join(rng.choice(_TOKENS) for _ in range(rng.randint(0, 40)))
        for _ in range(count)
    ]


def _has_unterminated_tail(data: bytes, begin: bytes) -> bool:
    """A counted begin after the last legacy match: findall dropped it."""
    ends = [m.end() for m in _LEGACY_SCANS[begin].finditer(data)]
    tail = data[ends[-1] if ends else 0:]
    return re.search(rb"\d\s+" + begin, tail) is not None


def test_block_scan_matches_the_legacy_findall_exactly() -> None:
    from model.text_commit.cid_fonts import _cmap_blocks

    streams = list(_HAND_CASES) + _random_streams(4000)
    coverage = {
        (begin, kind): 0
        for begin, _end in _FAMILIES
        for kind in ("blocks", "unterminated", "blocks_and_unterminated")
    }
    for data in streams:
        for begin, end in _FAMILIES:
            expected = _legacy_blocks(data, begin, end)
            assert _cmap_blocks(data, begin, end) == expected, (data, begin)
            unterminated = _has_unterminated_tail(data, begin)
            coverage[(begin, "blocks")] += bool(expected)
            coverage[(begin, "unterminated")] += unterminated
            coverage[(begin, "blocks_and_unterminated")] += bool(
                expected and unterminated
            )
    # The soup must actually exercise blocks, dropped tails, and both at once.
    assert all(hits >= 100 for hits in coverage.values()), coverage


def test_parse_result_matches_the_legacy_scans_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from model.text_commit.cid_fonts import _cmap_blocks  # noqa: F401

    streams = list(_HAND_CASES) + _random_streams(4000)
    current = [parse_tounicode_strict(data) for data in streams]
    monkeypatch.setattr(cid_fonts, "_cmap_blocks", _legacy_blocks)
    legacy = [parse_tounicode_strict(data) for data in streams]
    for data, got, want in zip(streams, current, legacy):
        assert got == want, data
    parsed = sum(isinstance(result, ToUnicodeMap) for result in legacy)
    assert parsed >= 50, parsed
