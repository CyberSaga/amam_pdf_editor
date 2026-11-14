"""``ToUnicodeMap`` lookups are indexed, never a per-code record scan.

Two kinds of test live here:

- RED LIGHT (``test_*_stays_within_budget``): a ToUnicode CMap inside the
  parse budgets (<= 2 MiB, <= 65,536 records) whose matching records sit
  last, or are absent, used to cost one full record walk PER CODE in
  ``decode_cid`` and per character in ``cids_for_char`` -- ~10^9..10^10
  interpreted iterations for ~10^5 codes, on the GUI thread.  Each test
  times the lookups (the lazy index build included) in small chunks and
  fails as soon as the budget is spent, so the old code fails in seconds
  instead of hanging the suite.
- PINS (``test_*_matches_the_record_scan``): the indexed lookups must
  return EXACTLY what the record scan returned -- first-wins precedence,
  char-vs-range precedence by record order, range offset arithmetic,
  unmatched codes, raised exception types, and the reverse lookup's
  order.  The pre-index scan is kept below, verbatim, as the oracle.
  These pass before the fix by construction; they guard the rewrite.
"""
from __future__ import annotations

import dataclasses
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.cid_fonts import (  # noqa: E402
    _MAX_TOUNICODE_BYTES,
    _MAX_TOUNICODE_RECORDS,
    CidCapabilityFailure,
    ToUnicodeMap,
    parse_tounicode_strict,
)

Record = tuple[str, int, int, str]

# ------------------------------------------------- the pre-index oracle


def _scan_decode_cid(records: tuple[Record, ...], cid: int) -> str | None:
    """``ToUnicodeMap.decode_cid`` before the index (verbatim)."""
    for kind, lo, hi, text in records:
        if lo <= cid <= hi:
            if kind == "char":
                return text
            return chr(ord(text) + (cid - lo))
    return None


def _scan_cids_for_char(records: tuple[Record, ...], char: str) -> tuple[int, ...]:
    """``ToUnicodeMap.cids_for_char`` before the index (verbatim)."""
    matches: list[int] = []
    for kind, lo, hi, text in records:
        if kind == "char":
            if text == char and lo not in matches:
                matches.append(lo)
        else:
            offset = ord(char) - ord(text)
            if 0 <= offset <= hi - lo and (lo + offset) not in matches:
                matches.append(lo + offset)
    return tuple(matches)


def _outcome(fn: Callable[[], object]) -> tuple[str, object]:
    """A call's result, or the TYPE of what it raised (both must match)."""
    try:
        return ("returned", fn())
    except Exception as exc:  # the oracle comparison covers raises too
        return ("raised", type(exc))


def _assert_matches_scan(
    records: tuple[Record, ...], codes: list[int], chars: list[str]
) -> None:
    indexed = ToUnicodeMap(records=records)
    for code in codes:
        assert _outcome(lambda: indexed.decode_cid(code)) == _outcome(
            lambda: _scan_decode_cid(records, code)
        ), (records, code)
    for char in chars:
        assert _outcome(lambda: indexed.cids_for_char(char)) == _outcome(
            lambda: _scan_cids_for_char(records, char)
        ), (records, char)


def _probe_chars(records: tuple[Record, ...]) -> list[str]:
    """Every record text, every range destination edge and its +/-1
    neighbours, a multi-char probe, and characters no record maps."""
    probes = {"ff", "\x00", "Z", "\U0010ffff"}
    for kind, lo, hi, text in records:
        probes.add(text)
        if kind != "char" and len(text) == 1:
            first = ord(text)
            last = first + (hi - lo)
            for point in (first - 1, first, (first + last) // 2, last, last + 1):
                if 0 <= point <= 0x10FFFF:
                    probes.add(chr(point))
    return sorted(probes)


# ------------------------------------------------------- equivalence pins

_HAND_MAPS: dict[str, tuple[Record, ...]] = {
    "empty": (),
    "duplicate_char_first_wins": (
        ("char", 5, 5, "A"),
        ("char", 5, 5, "B"),
        ("char", 6, 6, "A"),
    ),
    "char_inside_range_char_first": (
        ("char", 0x12, 0x12, "Q"),
        ("range", 0x10, 0x1F, "a"),
    ),
    "char_inside_range_range_first": (
        ("range", 0x10, 0x1F, "a"),
        ("char", 0x12, 0x12, "Q"),
    ),
    "overlapping_ranges_distinct_offsets": (
        ("range", 0x10, 0x20, "A"),
        ("range", 0x18, 0x30, "a"),
        ("range", 0x00, 0x40, "一"),
    ),
    "overlapping_ranges_same_offset": (
        ("range", 0, 10, "A"),
        ("range", 5, 15, "F"),  # ord("F") - 5 == ord("A") - 0
        ("range", 5, 15, "F"),  # exact duplicate
    ),
    "range_nested_in_range": (
        ("range", 0x100, 0x1FF, "぀"),
        ("range", 0x140, 0x150, "x"),
    ),
    "code_space_edges": (
        ("range", 0xFFF0, 0xFFFF, "一"),
        ("range", 0, 0, "Z"),  # degenerate range
        ("char", 0xFFFF, 0xFFFF, "!"),
        ("char", 0, 0, "?"),
    ),
    "full_code_space_range": (
        ("char", 0x8000, 0x8000, "c"),
        ("range", 0, 0xFFFF, "\U00010000"),
        ("char", 0x8001, 0x8001, "d"),
    ),
    "max_scalar_range": (("range", 0, 0xF, chr(0x10FFF0)),),
    "astral_range": (("range", 0x20, 0x2F, "\U0001f600"),),
    "multichar_destinations_with_range": (
        ("char", 3, 3, "ff"),
        ("char", 4, 4, "ffi"),
        ("range", 5, 6, "f"),
    ),
    "multichar_destinations_chars_only": (
        ("char", 3, 3, "ff"),
        ("char", 4, 4, "f"),
        ("char", 9, 9, "ff"),
    ),
    "char_and_range_share_a_cid": (
        ("range", 0, 9, "0"),
        ("char", 3, 3, "3"),
        ("char", 30, 30, "3"),
    ),
    "reverse_order_is_record_order_not_cid_order": (
        ("char", 9, 9, "x"),
        ("range", 0, 5, "t"),  # "x" at offset 4 -> cid 4
        ("char", 1, 1, "x"),
        ("range", 7, 8, "x"),  # "x" at offset 0 -> cid 7
    ),
    # Shapes the strict parser never emits, pinned so a hand-built map
    # keeps its exact pre-index behaviour (including what it raises).
    "char_record_spanning_codes": (("char", 1, 4, "X"), ("char", 2, 2, "Y")),
    "inverted_record_never_covers": (
        ("range", 5, 3, "A"),
        ("char", 9, 7, "B"),
        ("char", 4, 4, "C"),
    ),
    "range_with_multichar_text": (("char", 1, 1, "a"), ("range", 2, 4, "ab")),
}


@pytest.mark.parametrize("name", sorted(_HAND_MAPS))
def test_hand_maps_matches_the_record_scan(name: str) -> None:
    records = _HAND_MAPS[name]
    codes = list(range(-2, 0x10002))  # every 2-byte code plus out-of-space ints
    _assert_matches_scan(records, codes, _probe_chars(records))


_TEXTS = ("A", "B", "a", "é", "一", "\U0001f600", "ff", "ffi")
_SHIFTS = (0x41, 0x61, 0x4E00)  # shared offsets -> same-offset range groups
_BASES = (0x30, 0x41, 0x4E00, 0x1F600, 0x10FFF0)


def _random_records(rng: random.Random, universe: int, count: int) -> tuple[Record, ...]:
    """Records of the shapes ``parse_tounicode_strict`` emits: ``char``
    with ``lo == hi`` (single or multi-char text), ``range`` with
    ``lo <= hi`` (degenerate included), one non-surrogate base scalar, and
    ``ord(base) + span <= 0x10FFFF``."""
    records: list[Record] = []
    while len(records) < count:
        lo = rng.randrange(universe)
        if rng.random() < 0.45:
            records.append(("char", lo, lo, rng.choice(_TEXTS)))
            continue
        span = 0 if rng.random() < 0.2 else rng.randrange(1 + universe // 4)
        hi = min(universe - 1, lo + span)
        if rng.random() < 0.5:
            base = lo + rng.choice(_SHIFTS)
        else:
            base = rng.choice(_BASES)
        base = min(base, 0x10FFFF - (hi - lo))
        if 0xD800 <= base <= 0xDFFF:
            continue  # a strict UTF-16BE destination is never a lone surrogate
        records.append(("range", lo, hi, chr(base)))
    return tuple(records)


def test_random_small_maps_matches_the_record_scan() -> None:
    """Dense overlaps: up to 24 records over a 64-code window, every code
    of the window (and its outside neighbours) decoded."""
    rng = random.Random(0xF24)
    for _ in range(300):
        records = _random_records(rng, 64, rng.randint(1, 24))
        _assert_matches_scan(records, list(range(-2, 66)), _probe_chars(records))


def test_random_wide_maps_matches_the_record_scan() -> None:
    """Hundreds of records over the full 2-byte code space (a deep range
    index), decoded at every record edge +/-1 and at random codes."""
    rng = random.Random(0x24F)
    for _ in range(8):
        records = _random_records(rng, 0x10000, rng.randint(100, 300))
        codes = {-1, 0, 0xFFFF, 0x10000}
        for _kind, lo, hi, _text in records:
            codes.update((lo - 1, lo, hi, hi + 1))
        codes.update(rng.randrange(0x10000) for _ in range(1500))
        chars = _probe_chars(records)
        chars += [chr(rng.choice(_BASES) + rng.randrange(16)) for _ in range(100)]
        _assert_matches_scan(records, sorted(codes), chars)


def test_index_cache_leaves_value_semantics_untouched() -> None:
    """PIN: the lazily built indexes are not fields -- equality, hash,
    repr and frozenness of the map are exactly the records'."""
    records: tuple[Record, ...] = (("char", 1, 1, "A"), ("range", 2, 5, "b"))
    used, fresh = ToUnicodeMap(records=records), ToUnicodeMap(records=records)
    hash_before, repr_before = hash(used), repr(used)
    assert used.decode_cid(3) == "c"
    assert used.cids_for_char("c") == (3,)
    assert used == fresh
    assert hash(used) == hash(fresh) == hash_before
    assert repr(used) == repr(fresh) == repr_before
    assert dataclasses.fields(used) == dataclasses.fields(fresh)
    assert [field.name for field in dataclasses.fields(used)] == ["records"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        used.records = ()  # type: ignore[misc]


# ------------------------------------------------- red light: timing budget

# The indexed lookups take well under a second here; the record scan needs
# minutes.  The budget is generous for a loaded Windows CI runner.
_BUDGET_S = 4.0
_CHUNK = 128


def _timed(fn: Callable[[Any], object], args: list[Any]) -> list[object]:
    """``[fn(a) for a in args]``, failing as soon as the budget is spent."""
    results: list[object] = []
    start = time.perf_counter()
    for begin in range(0, len(args), _CHUNK):
        results.extend(fn(arg) for arg in args[begin : begin + _CHUNK])
        elapsed = time.perf_counter() - start
        if elapsed > _BUDGET_S:
            pytest.fail(
                f"{min(begin + _CHUNK, len(args))} of {len(args)} lookups took "
                f"{elapsed:.1f} s (budget {_BUDGET_S} s): a per-lookup record scan"
            )
    return results


def _utf16_hex(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def _cmap(chars: list[tuple[int, str]], ranges: list[tuple[int, int, str]]) -> bytes:
    """A ToUnicode CMap body in 100-entry blocks (the spec's block size)."""
    parts: list[str] = []
    for begin in range(0, len(chars), 100):
        block = chars[begin : begin + 100]
        parts.append(f"{len(block)} beginbfchar\n")
        parts.extend(f"<{code:04X}> <{_utf16_hex(text)}>\n" for code, text in block)
        parts.append("endbfchar\n")
    for begin in range(0, len(ranges), 100):
        entries = ranges[begin : begin + 100]
        parts.append(f"{len(entries)} beginbfrange\n")
        parts.extend(
            f"<{lo:04X}> <{hi:04X}> <{_utf16_hex(text)}>\n" for lo, hi, text in entries
        )
        parts.append("endbfrange\n")
    return "".join(parts).encode("ascii")


def _parse_within_budgets(data: bytes) -> ToUnicodeMap:
    assert len(data) <= _MAX_TOUNICODE_BYTES
    parsed = parse_tounicode_strict(data)
    assert not isinstance(parsed, CidCapabilityFailure), parsed
    assert len(parsed.records) <= _MAX_TOUNICODE_RECORDS
    return parsed


def _cjk(code: int) -> str:
    return chr(0x4E00 + code % 0x5000)


_LAST_CHAR_CODES = [(code, _cjk(code)) for code in range(0xFFFF)]  # 0xFFFF unmapped


def test_decode_absent_or_last_char_code_stays_within_budget() -> None:
    """65,535 bfchar records; ~100k codes that map to the LAST record or to
    no record at all (both walked every record per code before the fix)."""
    tounicode = _parse_within_budgets(_cmap(_LAST_CHAR_CODES, []))
    codes = [0xFFFE, 0xFFFF] * 50_000
    results = _timed(tounicode.decode_cid, codes)
    assert results == [_cjk(0xFFFE), None] * 50_000


def test_decode_code_owned_by_a_trailing_range_stays_within_budget() -> None:
    """65,535 bfchar records then one bfrange (parsed last): code 0xFFFF
    is owned by the range, code 0xFFFE by the earlier char record."""
    tounicode = _parse_within_budgets(
        _cmap(_LAST_CHAR_CODES, [(0x8000, 0xFFFF, "A")])
    )
    assert len(tounicode.records) == _MAX_TOUNICODE_RECORDS
    codes = [0xFFFF, 0xFFFE] * 50_000
    results = _timed(tounicode.decode_cid, codes)
    assert results == [chr(0x41 + 0x7FFF), _cjk(0xFFFE)] * 50_000


def test_reverse_lookup_over_many_char_records_stays_within_budget() -> None:
    """The source-reproduction encoder asks ``cids_for_char`` once per
    character of the bound show: 50k characters over 65,535 records."""
    tounicode = _parse_within_budgets(_cmap(_LAST_CHAR_CODES, []))
    last = _cjk(0xFFFE)
    chars = [last, "A"] * 25_000
    results = _timed(tounicode.cids_for_char, chars)
    expected_last = tuple(code for code in range(0xFFFF) if _cjk(code) == last)
    assert results == [expected_last, ()] * 25_000


def test_reverse_lookup_over_same_offset_ranges_stays_within_budget() -> None:
    """65,536 overlapping bfrange entries with ONE shared offset: every
    character resolves to a single CID, so the lookup must not touch all
    of the ranges to produce it."""
    tounicode = _parse_within_budgets(
        _cmap([], [(0, 0xFFFF, "一")] * _MAX_TOUNICODE_RECORDS)
    )
    offsets = [(i * 7919) % 0x10000 for i in range(50_000)]
    chars = [chr(0x4E00 + offset) for offset in offsets]
    results = _timed(tounicode.cids_for_char, chars)
    assert results == [(offset,) for offset in offsets]


def test_reverse_lookup_over_distinct_offset_ranges_stays_within_budget() -> None:
    """32,768 two-code bfrange entries, each with its own offset and a
    disjoint destination block."""
    ranges = [(2 * i, 2 * i + 1, chr(0x10000 + 4 * i)) for i in range(0x8000)]
    tounicode = _parse_within_budgets(_cmap([], ranges))
    picks = [(i * 7919) % 0x8000 for i in range(50_000)]
    chars = [chr(0x10000 + 4 * i + 1) for i in picks]
    results = _timed(tounicode.cids_for_char, chars)
    assert results == [(2 * i + 1,) for i in picks]
