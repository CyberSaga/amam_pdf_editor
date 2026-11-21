"""Single-pass scan of a decoded content stream (standard library only; CAD card A5, H17, H18).

``StreamScan`` is a pure function of the decoded bytes, so its cache key is the BLAKE2b of those
bytes: ``add_image_object``, undo, redo and saves need no invalidation hook.  The scanner keeps no
token list; it records, for every ``Do``, the byte spans a splice edit needs.
"""
from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass

_DELIM_BYTES = b"()<>[]{}/%"
_WHITESPACE_BYTES = b" \t\r\n\x0c\x00"
_CONTENT_OPERATORS = {
    "b", "B", "b*", "B*", "BDC", "BI", "BMC", "BT", "BX", "c", "cm", "CS", "cs", "d", "d0", "d1",
    "Do", "DP", "EI", "EMC", "ET", "EX", "f", "F", "f*", "G", "g", "gs", "h", "i", "ID", "j", "J",
    "K", "k", "l", "m", "M", "MP", "n", "q", "Q", "re", "RG", "rg", "ri", "s", "S", "sc", "SC",
    "scn", "SCN", "sh", "T*", "Tc", "Td", "TD", "Tf", "Tj", "TJ", "TL", "Tm", "Tr", "Ts", "Tw",
    "Tz", "v", "w", "W", "W*", "y", "'", "\"",
}

CmValues = tuple[float, float, float, float, float, float]
Span = tuple[int, int]

# The scan cache holds at most this many ``DoRecord`` rows in total (H18, card A5).
SCAN_CACHE_MAX_RECORDS = 200_000

# Failure status the in-process discovery records for a page whose scan set the cache refused
# (D12, P3).  Unlike a child's ``resource_limited`` (which skips the long streams the child could not
# scan), it hides the page's images the in-process scan refused; both name the cause to the user.
INLINE_REFUSED = "resource_limited_inline"


def iter_token_spans(stream: bytes) -> Iterator[tuple[int, int]]:
    """``(start, end)`` of each token ``tokenize_content_stream`` returns, in order."""
    i = 0
    n = len(stream)
    while i < n:
        current = stream[i]
        if current in _WHITESPACE_BYTES:
            i += 1
            continue
        if current == 0x25:  # %
            i += 1
            while i < n and stream[i] not in (0x0D, 0x0A):
                i += 1
            continue
        if current == 0x2F:  # /
            start = i
            i += 1
            while i < n and stream[i] not in _WHITESPACE_BYTES and stream[i] not in _DELIM_BYTES:
                i += 1
            yield start, i
            continue
        if current == 0x28:  # (
            start = i
            i += 1
            depth = 1
            while i < n and depth > 0:
                byte = stream[i]
                if byte == 0x5C:  # backslash
                    i += 2
                    continue
                if byte == 0x28:
                    depth += 1
                elif byte == 0x29:
                    depth -= 1
                i += 1
            yield start, min(i, n)
            continue
        if current == 0x3C:  # <
            start = i
            if i + 1 < n and stream[i + 1] == 0x3C:
                yield start, start + 2
                i += 2
                continue
            i += 1
            while i < n and stream[i] != 0x3E:
                i += 1
            if i < n:
                i += 1
            yield start, i
            continue
        if current == 0x3E and i + 1 < n and stream[i + 1] == 0x3E:  # >>
            yield i, i + 2
            i += 2
            continue
        if current in (0x5B, 0x5D, 0x7B, 0x7D):  # [ ] { }
            yield i, i + 1
            i += 1
            continue
        start = i
        i += 1
        while i < n and stream[i] not in _WHITESPACE_BYTES and stream[i] not in _DELIM_BYTES:
            i += 1
        yield start, i


@dataclass(frozen=True)
class DoRecord:
    name: str  # no slash; "" when the Do has no operand
    do_operator_index: int
    do_span: Span  # [first operand token start, Do token end)
    cm_operator_index: int | None
    cm_span: Span | None  # [first operand token start of that cm, start of the cm token)
    cm_values: CmValues | None
    q_operator_index: int | None
    q_end_operator_index: int | None
    q_span: Span | None  # [first operand token start of the q, Q token end); None when never closed
    q_do_count: int  # every Do inside that q, nested ones included; 0 without a q


@dataclass(frozen=True)
class StreamScan:
    length: int
    operator_count: int
    dos: tuple[DoRecord, ...]


def parse_cm_values(operands: list[bytes] | tuple[bytes, ...]) -> CmValues | None:
    """The last six operands as floats, as ``_cm_values_from_operands`` reads them."""
    if len(operands) < 6:
        return None
    try:
        return tuple(float(raw.decode("latin-1")) for raw in operands[-6:])  # type: ignore[return-value]
    except Exception:
        return None


def scan_stream(stream: bytes) -> StreamScan:
    """One pass over ``iter_token_spans``; the rules of ``discover_native_image_invocations`` and
    ``_q_bounds_by_operator_index``, token for token.  No token list is built."""
    operator_index = -1
    operand_start: int | None = None  # byte start of the first operand since the last operator
    last_operands: list[Span] = []  # at most the last six operand spans
    operand_count = 0
    q_stack: list[int] = []
    # per q operator index: [first operand start, end operator index, end offset, Do count]
    q_info: dict[int, list] = {}
    # per depth: (cm operator index, cm_span, cm_values) of the last cm
    last_cm_by_depth: list[tuple[int, Span, CmValues | None] | None] = [None]
    raw_dos: list[tuple] = []
    for start, end in iter_token_spans(stream):
        text = stream[start:end].decode("latin-1")
        if text not in _CONTENT_OPERATORS:
            if operand_start is None:
                operand_start = start
            operand_count += 1
            last_operands.append((start, end))
            if len(last_operands) > 6:
                del last_operands[0]
            continue
        operator_index += 1
        first = start if operand_start is None else operand_start
        if text == "q":
            q_stack.append(operator_index)
            q_info[operator_index] = [first, None, None, 0]
            last_cm_by_depth.append(None)
        elif text == "Q":
            if q_stack:
                info = q_info[q_stack.pop()]
                info[1] = operator_index
                info[2] = end
            if len(last_cm_by_depth) > 1:
                last_cm_by_depth.pop()
        elif text == "cm":
            values = (
                parse_cm_values([stream[a:b] for a, b in last_operands]) if operand_count >= 6 else None
            )
            last_cm_by_depth[-1] = (operator_index, (first, start), values)
        elif text == "Do":
            name = stream[last_operands[-1][0] : last_operands[-1][1]].decode("latin-1").lstrip("/") if operand_count else ""
            for q_index in q_stack:
                q_info[q_index][3] += 1
            raw_dos.append(
                (name, operator_index, (first, end), last_cm_by_depth[-1], q_stack[-1] if q_stack else None)
            )
        operand_start = None
        last_operands = []
        operand_count = 0
    records: list[DoRecord] = []
    for name, do_index, do_span, cm, q_index in raw_dos:
        q_end_index = q_span = None
        q_count = 0
        if q_index is not None:
            first_q, q_end_index, q_end_offset, q_count = q_info[q_index]
            if q_end_offset is not None:
                q_span = (first_q, q_end_offset)
        records.append(
            DoRecord(
                name=name,
                do_operator_index=do_index,
                do_span=do_span,
                cm_operator_index=cm[0] if cm else None,
                cm_span=cm[1] if cm else None,
                cm_values=cm[2] if cm else None,
                q_operator_index=q_index,
                q_end_operator_index=q_end_index,
                q_span=q_span,
                q_do_count=q_count,
            )
        )
    return StreamScan(length=len(stream), operator_count=operator_index + 1, dos=tuple(records))


def _shift(offset: int, end: int, delta: int) -> int:
    return offset + delta if offset >= end else offset


def derive_after_replace(
    scan: StreamScan, start: int, end: int, new_len: int, new_cm_values: CmValues | None
) -> StreamScan:
    """``scan`` of the stream after bytes ``[start, end)`` (a ``cm_span``) became ``new_len`` bytes."""
    delta = new_len - (end - start)
    records: list[DoRecord] = []
    for rec in scan.dos:
        cm_span = rec.cm_span
        cm_values = rec.cm_values
        if cm_span == (start, end):
            cm_span = (start, start + new_len)
            cm_values = new_cm_values
        elif cm_span is not None:
            cm_span = (_shift(cm_span[0], end, delta), _shift(cm_span[1], end, delta))
        q_span = rec.q_span
        if q_span is not None:
            q_span = (_shift(q_span[0], end, delta), _shift(q_span[1], end, delta))
        records.append(
            DoRecord(
                name=rec.name,
                do_operator_index=rec.do_operator_index,
                do_span=(_shift(rec.do_span[0], end, delta), _shift(rec.do_span[1], end, delta)),
                cm_operator_index=rec.cm_operator_index,
                cm_span=cm_span,
                cm_values=cm_values,
                q_operator_index=rec.q_operator_index,
                q_end_operator_index=rec.q_end_operator_index,
                q_span=q_span,
                q_do_count=rec.q_do_count,
            )
        )
    return StreamScan(length=scan.length + delta, operator_count=scan.operator_count, dos=tuple(records))


def derive_after_remove(
    scan: StreamScan, start: int, end: int, removed_operators: int, new_len: int
) -> StreamScan:
    """``scan`` of the stream after bytes ``[start, end)`` became ``new_len`` bytes and
    ``removed_operators`` operators left.  The range is a ``Do`` or the ``q..Q`` block of one."""
    delta = new_len - (end - start)
    dropped = [r for r in scan.dos if r.do_span[0] >= start and r.do_span[1] <= end]
    if not dropped:
        raise ValueError("the removed range holds no Do record")
    first_removed = min(
        r.q_operator_index
        if r.q_span == (start, end) and r.q_operator_index is not None
        else r.do_operator_index
        for r in dropped
    )
    last_removed = first_removed + removed_operators - 1

    def moved(index: int | None) -> int | None:
        return index - removed_operators if index is not None and index > last_removed else index

    records: list[DoRecord] = []
    for rec in scan.dos:
        if rec in dropped:
            continue
        q_count = rec.q_do_count
        q_idx = rec.q_operator_index
        if (
            q_idx is not None
            and q_idx < first_removed
            and (rec.q_end_operator_index is None or rec.q_end_operator_index > last_removed)
        ):
            q_count -= len(dropped)
        records.append(
            DoRecord(
                name=rec.name,
                do_operator_index=moved(rec.do_operator_index),  # type: ignore[arg-type]
                do_span=(_shift(rec.do_span[0], end, delta), _shift(rec.do_span[1], end, delta)),
                cm_operator_index=moved(rec.cm_operator_index),
                cm_span=None
                if rec.cm_span is None
                else (_shift(rec.cm_span[0], end, delta), _shift(rec.cm_span[1], end, delta)),
                cm_values=rec.cm_values,
                q_operator_index=moved(q_idx),
                q_end_operator_index=moved(rec.q_end_operator_index),
                q_span=None
                if rec.q_span is None
                else (_shift(rec.q_span[0], end, delta), _shift(rec.q_span[1], end, delta)),
                q_do_count=q_count,
            )
        )
    return StreamScan(
        length=scan.length + delta,
        operator_count=scan.operator_count - removed_operators,
        dos=tuple(records),
    )


# ---- cache -----------------------------------------------------------------------------------

_cache: OrderedDict[bytes, StreamScan] = OrderedDict()
_cache_records = 0
# TODO: unbounded (a few dozen bytes per stream); bound it with the cache if it ever matters.
_alias: dict[tuple[bytes, str], bytes] = {}
# Scans that failed in the child, scoped to (handle generation, page number, set key): the set key
# is the ordered distinct content keys of every stream discovery reads on that page.  A failure may
# be transient (child MemoryError, ledger refusal, crash), so it is no fact about the bytes: it dies
# with its handle (CAD card D12 literal).  LRU, ``MAX_FAILED_SETS`` entries; the value is the
# recorded status.
MAX_FAILED_SETS = 256
_failed_sets: OrderedDict[tuple[int, int, tuple[bytes, ...]], str] = OrderedDict()
_INDIRECT_REF = re.compile(r"\d+\s+\d+\s+R")


def content_key(stream: bytes) -> bytes:
    return hashlib.blake2b(stream, digest_size=16).digest()


def scan_size(scan: StreamScan) -> int:
    """What a scan costs the cache: its ``DoRecord`` rows, at least one (an empty scan still holds
    a dict entry)."""
    return max(1, len(scan.dos))


def cached_scan(key: bytes) -> StreamScan | None:
    scan = _cache.get(key)
    if scan is not None:
        _cache.move_to_end(key)
    return scan


def _evict_front(excess: int, protected: frozenset[bytes] | set[bytes]) -> bool:
    """Drop least recently used entries not in ``protected`` until ``excess`` records are free.
    All-or-nothing: ``False`` (nothing evicted) when the unprotected entries cannot free that much."""
    global _cache_records
    victims: list[bytes] = []
    freed = 0
    for key, scan in _cache.items():
        if freed >= excess:
            break
        if key in protected:
            continue
        victims.append(key)
        freed += scan_size(scan)
    if freed < excess:
        return False
    for key in victims:
        _cache_records -= scan_size(_cache.pop(key))
    return True


def store_scan(key: bytes, scan: StreamScan, keep: frozenset[bytes] = frozenset()) -> bool:
    """Keep ``scan`` under ``key``; the least recently used entries go first, never ``keep`` (the
    page's other streams).  ``False`` and nothing stored or evicted when it cannot fit: a scan over
    the record cap is refused, never kept alone (a page must not wait for an answer that cannot be
    stored)."""
    global _cache_records
    size = scan_size(scan)
    if size > SCAN_CACHE_MAX_RECORDS:
        return False
    old = _cache.get(key)
    excess = _cache_records - (scan_size(old) if old is not None else 0) + size - SCAN_CACHE_MAX_RECORDS
    if excess > 0 and not _evict_front(excess, set(keep) | {key}):
        return False
    old = _cache.pop(key, None)
    if old is not None:
        _cache_records -= scan_size(old)
    _cache[key] = scan
    _cache_records += size
    return True


def admit_set(members: dict[bytes, StreamScan]) -> bool:
    """Admit the scans of one page as a set (the chokepoint of every multi-stream store).

    The members together cost more than the cap: nothing is stored and nothing is evicted
    (``False``).  Otherwise cached members become most recently used, new ones are inserted and
    the entries of other pages go from the front; a member is never evicted by its own set."""
    global _cache_records
    if sum(scan_size(scan) for scan in members.values()) > SCAN_CACHE_MAX_RECORDS:
        return False
    for key, scan in members.items():
        if key in _cache:
            _cache.move_to_end(key)
        else:
            _cache[key] = scan
            _cache_records += scan_size(scan)
    excess = _cache_records - SCAN_CACHE_MAX_RECORDS
    if excess > 0:
        _evict_front(excess, set(members))  # always succeeds: the members alone fit
    return True


def clear_scan_cache() -> None:
    global _cache_records
    _cache.clear()
    _alias.clear()
    _failed_sets.clear()
    _cache_records = 0


def alias_usable(dict_text: str) -> bool:
    """The raw-stream alias is valid only when the stream dictionary holds no indirect reference."""
    return _INDIRECT_REF.search(dict_text) is None


def alias_key(raw: bytes, dict_text: str) -> tuple[bytes, str]:
    return (hashlib.blake2b(raw, digest_size=16).digest(), dict_text)


def lookup_alias(alias: tuple[bytes, str]) -> bytes | None:
    return _alias.get(alias)


def store_alias(alias: tuple[bytes, str], key: bytes) -> None:
    _alias[alias] = key


def mark_set_failed(generation: int, page_num: int, set_key: tuple[bytes, ...], reason: str = "") -> None:
    key = (int(generation), int(page_num), tuple(set_key))
    if _failed_sets.get(key) != INLINE_REFUSED:  # a refusal stays: a late child failure of the same set must not lift it
        _failed_sets[key] = reason
    _failed_sets.move_to_end(key)
    while len(_failed_sets) > MAX_FAILED_SETS:
        _failed_sets.popitem(last=False)


def set_failed(generation: int, page_num: int, set_key: tuple[bytes, ...]) -> bool:
    key = (int(generation), int(page_num), tuple(set_key))
    if key not in _failed_sets:
        return False
    _failed_sets.move_to_end(key)
    return True


def failure_reason(generation: int, page_num: int, set_key: tuple[bytes, ...]) -> str | None:
    """The recorded status of a failed set (``""`` when none was given); ``None`` when not failed."""
    return _failed_sets.get((int(generation), int(page_num), tuple(set_key)))


def retire_failed_sets(live_generations: frozenset[int] | set[int]) -> None:
    """Forget the failed sets of every handle not in ``live_generations`` (the model calls this
    whenever a handle is replaced or closed)."""
    for key in [k for k in _failed_sets if k[0] not in live_generations]:
        del _failed_sets[key]


# ---- JSON for the child ----------------------------------------------------------------------


def to_json(scan: StreamScan) -> dict:
    return {
        "length": scan.length,
        "operator_count": scan.operator_count,
        "dos": [
            [
                r.name,
                r.do_operator_index,
                list(r.do_span),
                r.cm_operator_index,
                None if r.cm_span is None else list(r.cm_span),
                None if r.cm_values is None else list(r.cm_values),
                r.q_operator_index,
                r.q_end_operator_index,
                None if r.q_span is None else list(r.q_span),
                r.q_do_count,
            ]
            for r in scan.dos
        ],
    }


def from_json(obj: dict) -> StreamScan:
    dos = []
    for row in obj["dos"]:
        name, do_index, do_span, cm_index, cm_span, cm_values, q_index, q_end, q_span, q_count = row
        dos.append(
            DoRecord(
                name=str(name),
                do_operator_index=int(do_index),
                do_span=(int(do_span[0]), int(do_span[1])),
                cm_operator_index=None if cm_index is None else int(cm_index),
                cm_span=None if cm_span is None else (int(cm_span[0]), int(cm_span[1])),
                cm_values=None if cm_values is None else tuple(float(v) for v in cm_values),  # type: ignore[arg-type]
                q_operator_index=None if q_index is None else int(q_index),
                q_end_operator_index=None if q_end is None else int(q_end),
                q_span=None if q_span is None else (int(q_span[0]), int(q_span[1])),
                q_do_count=int(q_count),
            )
        )
    return StreamScan(length=int(obj["length"]), operator_count=int(obj["operator_count"]), dos=tuple(dos))
