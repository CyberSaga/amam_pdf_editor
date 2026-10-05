"""Lossless PDF content-stream lexer and raw byte-splice writer.

Unlike ``model/pdf_content_ops.py`` (which normalizes: whitespace and
comments are dropped, serialization rejoins tokens), this lexer tiles the
source exactly — every byte, including whitespace and comments, belongs to
exactly one token — so untouched bytes can be proven unchanged.  The
splicer is the only writer: it replaces declared ranges after verifying
expected bytes and the whole-stream digest, and never normalizes.

Do not add a token serializer here; Tier 0 identity depends on its absence.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum, auto

from model.text_commit.dto import StreamReplacement

logger = logging.getLogger(__name__)

_WHITESPACE = b"\x00\t\n\x0c\r "
_DELIMITERS = b"()<>[]{}/%"
_NUMBER_RE = re.compile(rb"\A[+-]?(?:\d+\.?\d*|\.\d+)\Z")
_HEX_DIGITS = frozenset(b"0123456789abcdefABCDEF")


class TokenKind(Enum):
    WHITESPACE = auto()
    COMMENT = auto()
    NUMBER = auto()
    STRING = auto()
    HEXSTRING = auto()
    NAME = auto()
    OPERATOR = auto()
    ARRAY_OPEN = auto()
    ARRAY_CLOSE = auto()
    DICT_OPEN = auto()
    DICT_CLOSE = auto()
    BRACE_OPEN = auto()
    BRACE_CLOSE = auto()
    INLINE_IMAGE_DATA = auto()
    MALFORMED = auto()
    # Only ``lex_content_stream(..., coalesce_inert=True)`` -- the replay's
    # token source -- yields this: one span whose whole replay effect is
    # "clear the operand stack" (see ``_inert_span_end``).  It still tiles.
    INERT_RUN = auto()


@dataclass(frozen=True)
class StreamToken:
    """Half-open byte range ``[start, end)`` of one token in the source."""

    kind: TokenKind
    start: int
    end: int


class SpliceError(ValueError):
    """A replacement cannot be applied safely; no output was produced."""


def _is_regular(byte: int) -> bool:
    return byte not in _WHITESPACE and byte not in _DELIMITERS


def _scan_literal_string(data: bytes, pos: int) -> StreamToken:
    depth = 0
    i = pos
    length = len(data)
    while i < length:
        c = data[i]
        if c == 0x5C:  # backslash escapes the next byte
            i += 2
            continue
        if c == 0x28:  # (
            depth += 1
        elif c == 0x29:  # )
            depth -= 1
            if depth == 0:
                return StreamToken(TokenKind.STRING, pos, i + 1)
        i += 1
    return StreamToken(TokenKind.MALFORMED, pos, length)


def _scan_hex_string(data: bytes, pos: int) -> StreamToken:
    i = pos + 1
    length = len(data)
    malformed = False
    while i < length:
        c = data[i]
        if c == 0x3E:  # >
            kind = TokenKind.MALFORMED if malformed else TokenKind.HEXSTRING
            return StreamToken(kind, pos, i + 1)
        if c not in _HEX_DIGITS and c not in _WHITESPACE:
            malformed = True
        i += 1
    return StreamToken(TokenKind.MALFORMED, pos, length)


def _scan_inline_image_payload(data: bytes, pos: int) -> StreamToken:
    """Payload after ``ID``: ends before an ``EI`` bounded by whitespace."""
    length = len(data)
    search = pos
    while True:
        idx = data.find(b"EI", search)
        if idx == -1:
            return StreamToken(TokenKind.MALFORMED, pos, length)
        prev_ok = idx > 0 and data[idx - 1] in _WHITESPACE
        nxt = idx + 2
        next_ok = nxt >= length or data[nxt] in _WHITESPACE or data[nxt] in _DELIMITERS
        if prev_ok and next_ok and idx >= pos:
            return StreamToken(TokenKind.INLINE_IMAGE_DATA, pos, idx)
        search = idx + 1


# --------------------------------------------------------------------------
# Inert-span coalescing (replay fast path, critique step 12 latency).
#
# HVAC drawing pages are ~1.3 MB of ``q 1 0 0 1 x y cm 0 0 m … l S Q``: ~930k
# tokens, ~70 text shows.  Lexing them byte by byte held the GUI thread
# ~1.4 s per cold replay.  ``coalesce_inert=True`` lets C-level regexes
# claim spans whose ENTIRE replay effect is "clear the operand stack" and
# yields each as one ``INERT_RUN`` token.  Soundness rests on two alphabets:
#
# * every character is whitespace or a regular character (no delimiter, so
#   no string, name, array, dict, comment or inline image can occur and the
#   tokens are exactly the whitespace-separated words);
# * the letters spell only path/colour/clip operators.  Of the operators
#   replay tracks, the top-level letters can spell only ``cm`` and ``gs``
#   (refused there: they change state for good), and the q-block letters add
#   ``w``/``j``/``M`` -- all five are restored by the block's own ``Q``.  No
#   letter set here can spell q/Q (excluded), BT/ET/T*, Tj/TJ/'/", Do,
#   BDC/BMC/EMC (no D/C/T/E/I), BI/ID/EI or true/false/null.
#
# A non-number word is an operator in the reference lexer, and every
# operator replay does not track only clears the operand stack, so the span's
# effect is exactly "clear" -- provided nothing inside flags ``malformed``.
# Inside a q-block only ``cm`` can do that (fewer than six NUMBER operands);
# ``_q_blocks_cm_are_well_formed`` proves every ``cm`` has six, otherwise the
# fast path is switched off for the rest of the stream (the stream is
# malformed anyway, and the plain path is exact).  Contract, pinned by
# ``test_text_commit_replay_fast_path``: replay with and without coalescing
# returns EQUAL ``PageReplay`` objects on every input.
# --------------------------------------------------------------------------
_WS_CLASS = rb"\x00\t\n\x0c\r "
_NONREG_CLASS = _WS_CLASS + rb"()<>\[\]{}/%"
# Letters of m l c v y h re S s f f* F B B* b b* n W W* rg RG g G k K J i.
_TOP_LETTERS = rb"mlcvyhreSsfFBbnWGgKkJiR*"
_TOP_CHARS = _WS_CLASS + rb"0-9.+\-" + _TOP_LETTERS
_Q_CHARS = _TOP_CHARS + rb"wjM"
_TOKEN_END = rb"(?![^" + _NONREG_CLASS + rb"])"

# A run of balanced ``q … Q`` blocks over the q-block alphabet, nested up to
# ``_Q_NESTING`` deep (HVAC wraps each rotated symbol as ``q cm q cm … Q Q``).
# Body = X* (BLOCK X*)* -- unambiguous because no X byte is ``q``.
_Q_NESTING = 3


def _q_block_pattern(depth: int) -> bytes:
    body = rb"[" + _Q_CHARS + rb"]*"
    if depth > 1:
        body += rb"(?:" + _q_block_pattern(depth - 1) + rb"[" + _Q_CHARS + rb"]*)*"
    return (
        rb"(?<![^" + _NONREG_CLASS + rb"])q" + _TOKEN_END
        + body + rb"(?<=[" + _WS_CLASS + rb"])Q" + _TOKEN_END
    )


_Q_BLOCKS_RE = re.compile(
    rb"(?:[" + _WS_CLASS + rb"]*" + _q_block_pattern(_Q_NESTING) + rb")+"
)
# The longest top-level-alphabet prefix, and the inert span inside it, which
# must END at an operator word (trailing numbers belong to the next operator).
_TOP_ALPHABET_RE = re.compile(rb"[" + _TOP_CHARS + rb"]*")
_TOP_SPAN_RE = re.compile(
    rb"[" + _TOP_CHARS + rb"]*[" + _TOP_LETTERS + rb"]" + _TOKEN_END
)
# A standalone ``cm``/``gs`` word: not inert at top level.
_TOP_FORBIDDEN_RE = re.compile(
    rb"(?:cm|gs)(?<![^" + _NONREG_CLASS + rb"]..)" + _TOKEN_END, re.DOTALL
)
# ``cm`` checks run on the REVERSED span: "six NUMBER words right before
# cm" becomes a forward pattern after ``mc``.  ``_REV_NUMBER`` is the exact
# reverse of ``_NUMBER_RE`` (``[+-]?(?:\d+\.?\d*|\.\d+)``).
_REV_NUMBER = rb"(?:(?:[0-9]*\.)?[0-9]+|[0-9]+\.)[+\-]?"
_REV_WORD_END = rb"(?![^" + _WS_CLASS + rb"])"
# A ``cm`` word NOT preceded by six NUMBER words (searched in reverse).
_REV_BAD_CM_RE = re.compile(
    rb"mc(?<![^" + _WS_CLASS + rb"]mc)" + _REV_WORD_END
    + rb"(?!(?:[" + _WS_CLASS + rb"]+" + _REV_NUMBER + _REV_WORD_END + rb"){6})"
)


def _q_blocks_cm_are_well_formed(data: bytes, start: int, end: int) -> bool:
    """Every ``cm`` word in ``data[start:end]`` follows six NUMBER words."""
    span = data[start:end]
    if b"cm" not in span:
        return True
    return _REV_BAD_CM_RE.search(span[::-1]) is None


class _InertSpanScanner:
    """Finds inert spans at operand-list starts; amortized linear per stream.

    A failed top-level attempt never rescans: the alphabet run's end and the
    next forbidden word are cached and reused while ``pos`` stays inside the
    run.  A failed q-block attempt scans at most to the first byte outside
    the q-block alphabet, and only a ``q`` at most ``_Q_NESTING`` levels
    inside it can start another attempt over the same bytes, so each byte is
    scanned O(``_Q_NESTING``) times.
    """

    __slots__ = ("_data", "_enabled", "_run_start", "_run_end", "_forbidden_from", "_forbidden_at")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._enabled = True
        self._run_start = -1
        self._run_end = -1
        self._forbidden_from = -1
        self._forbidden_at = -1

    def span_end(self, pos: int) -> int | None:
        if not self._enabled:
            return None
        data = self._data
        blocks = _Q_BLOCKS_RE.match(data, pos)
        if blocks is not None:
            end = blocks.end()
            if _q_blocks_cm_are_well_formed(data, pos, end):
                return end
            # The reference replay flags this stream malformed; stay exact.
            self._enabled = False
            return None
        return self._top_level_span_end(pos)

    def _top_level_span_end(self, pos: int) -> int | None:
        data = self._data
        if not (self._run_start <= pos < self._run_end):
            self._run_start = pos
            match = _TOP_ALPHABET_RE.match(data, pos)
            self._run_end = match.end() if match is not None else pos
            self._forbidden_from = self._forbidden_at = -1
        run_end = self._run_end
        if run_end <= pos:
            return None
        if not (self._forbidden_from <= pos <= self._forbidden_at):
            hit = _TOP_FORBIDDEN_RE.search(data, pos, min(len(data), run_end + 1))
            self._forbidden_from = pos
            self._forbidden_at = (
                hit.start() if hit is not None and hit.end() <= run_end else run_end
            )
        if self._forbidden_at < run_end:
            span = _TOP_SPAN_RE.match(data, pos, self._forbidden_at)
        else:
            span = _TOP_SPAN_RE.match(data, pos)
        return span.end() if span is not None else None


def lex_content_stream(
    data: bytes, *, coalesce_inert: bool = False
) -> Iterator[StreamToken]:
    """Tile ``data`` into a lazily yielded token stream; never raises.

    Unlexable constructs become ``MALFORMED`` tokens so callers can reject
    the stream instead of guessing.  Invariant: token ranges are contiguous,
    gap-free, and cover the source exactly.

    A generator, not a list (Task 12 P0-B): the list form materialized
    ~0.77 tokens/byte before replay read the first token -- a measured
    72 MB decoded stream became ~54.7M StreamToken objects and ~10 GB of
    RSS.  Callers needing random access wrap it in ``list()`` explicitly.

    ``coalesce_inert`` (replay only) additionally yields provably inert
    spans as single ``INERT_RUN`` tokens; it is attempted only where an
    operand list starts (stream start, after an operator or another span).
    """
    scanner = _InertSpanScanner(data) if coalesce_inert else None
    attempt = scanner is not None
    pos = 0
    length = len(data)
    while pos < length:
        if attempt:
            attempt = False
            span_end = scanner.span_end(pos)  # type: ignore[union-attr]
            if span_end is not None and span_end > pos:
                yield StreamToken(TokenKind.INERT_RUN, pos, span_end)
                pos = span_end
                attempt = True
                continue
        c = data[pos]
        if c in _WHITESPACE:
            end = pos + 1
            while end < length and data[end] in _WHITESPACE:
                end += 1
            token = StreamToken(TokenKind.WHITESPACE, pos, end)
        elif c == 0x25:  # %
            end = pos + 1
            while end < length and data[end] not in b"\r\n":
                end += 1
            token = StreamToken(TokenKind.COMMENT, pos, end)
        elif c == 0x28:  # (
            token = _scan_literal_string(data, pos)
        elif c == 0x3C:  # <
            if pos + 1 < length and data[pos + 1] == 0x3C:
                token = StreamToken(TokenKind.DICT_OPEN, pos, pos + 2)
            else:
                token = _scan_hex_string(data, pos)
        elif c == 0x3E:  # >
            if pos + 1 < length and data[pos + 1] == 0x3E:
                token = StreamToken(TokenKind.DICT_CLOSE, pos, pos + 2)
            else:
                token = StreamToken(TokenKind.MALFORMED, pos, pos + 1)
        elif c == 0x5B:  # [
            token = StreamToken(TokenKind.ARRAY_OPEN, pos, pos + 1)
        elif c == 0x5D:  # ]
            token = StreamToken(TokenKind.ARRAY_CLOSE, pos, pos + 1)
        elif c == 0x7B:  # {
            token = StreamToken(TokenKind.BRACE_OPEN, pos, pos + 1)
        elif c == 0x7D:  # }
            token = StreamToken(TokenKind.BRACE_CLOSE, pos, pos + 1)
        elif c == 0x29:  # stray )
            token = StreamToken(TokenKind.MALFORMED, pos, pos + 1)
        elif c == 0x2F:  # /
            end = pos + 1
            while end < length and _is_regular(data[end]):
                end += 1
            token = StreamToken(TokenKind.NAME, pos, end)
        else:
            end = pos + 1
            while end < length and _is_regular(data[end]):
                end += 1
            raw = data[pos:end]
            if _NUMBER_RE.match(raw):
                token = StreamToken(TokenKind.NUMBER, pos, end)
            else:
                yield StreamToken(TokenKind.OPERATOR, pos, end)
                if raw == b"ID":
                    # One whitespace byte separates ID from the payload.
                    if end < length and data[end] in _WHITESPACE:
                        yield StreamToken(TokenKind.WHITESPACE, end, end + 1)
                        end += 1
                    if end < length:
                        payload = _scan_inline_image_payload(data, end)
                        if payload.end > payload.start:
                            yield payload
                        end = payload.end
                pos = end
                attempt = scanner is not None
                continue
        yield token
        pos = token.end


_STRING_DECODE_ESCAPES = {
    0x6E: b"\n",  # n
    0x72: b"\r",  # r
    0x74: b"\t",  # t
    0x62: b"\b",  # b
    0x66: b"\f",  # f
    0x28: b"(",
    0x29: b")",
    0x5C: b"\\",
}


def decode_literal_string(raw: bytes) -> bytes:
    """Decode a lexed literal-string token (including its parentheses)."""
    if len(raw) < 2 or raw[0] != 0x28 or raw[-1] != 0x29:
        raise ValueError(f"not a literal string token: {raw[:16]!r}")
    body = raw[1:-1]
    out = bytearray()
    i = 0
    length = len(body)
    while i < length:
        c = body[i]
        if c == 0x0D:  # bare CR (or CRLF): one 0x0A, PDF 32000-1 7.3.4.2
            out.append(0x0A)
            i += 1
            if i < length and body[i] == 0x0A:
                i += 1
            continue
        if c != 0x5C:
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= length:
            break  # trailing lone backslash: dropped
        e = body[i]
        if e in _STRING_DECODE_ESCAPES:
            out += _STRING_DECODE_ESCAPES[e]
            i += 1
        elif 0x30 <= e <= 0x37:  # up to three octal digits
            digits = bytearray([e])
            i += 1
            while i < length and len(digits) < 3 and 0x30 <= body[i] <= 0x37:
                digits.append(body[i])
                i += 1
            out.append(int(digits.decode("ascii"), 8) & 0xFF)
        elif e in b"\r\n":  # line continuation: swallow one EOL
            i += 1
            if e == 0x0D and i < length and body[i] == 0x0A:
                i += 1
        else:  # unknown escape: backslash is dropped, byte kept
            out.append(e)
            i += 1
    return bytes(out)


def encode_literal_string(value: bytes) -> bytes:
    """Encode bytes as a literal string token that round-trips exactly."""
    out = bytearray(b"(")
    for c in value:
        if c in (0x28, 0x29, 0x5C):
            out.append(0x5C)
            out.append(c)
        elif c == 0x0A:
            out += b"\\n"
        elif c == 0x0D:
            out += b"\\r"
        else:
            out.append(c)
    out += b")"
    return bytes(out)


def encode_hex_string(value: bytes) -> bytes:
    """Encode bytes as a hex string token that round-trips exactly.

    Task 12 P0-D: Identity-H CID operands keep the hex form on the way
    back out — a literal string could carry the same bytes, but the
    source shape was hex and staying in-kind keeps the splice reviewable
    byte-for-byte against the original operand.
    """
    return b"<" + value.hex().upper().encode("ascii") + b">"


def decode_hex_string(raw: bytes) -> bytes:
    """Decode a lexed hex-string token (including its angle brackets)."""
    if len(raw) < 2 or raw[0] != 0x3C or raw[-1] != 0x3E:
        raise ValueError(f"not a hex string token: {raw[:16]!r}")
    digits = bytes(c for c in raw[1:-1] if c not in _WHITESPACE)
    if any(c not in _HEX_DIGITS for c in digits):
        raise ValueError("invalid hex digit in hex string")
    if len(digits) % 2:
        digits += b"0"
    return bytes.fromhex(digits.decode("ascii"))


def splice_stream(source: bytes, replacements: Sequence[StreamReplacement]) -> bytes:
    """Apply byte-range replacements; all-or-nothing, validated first.

    Offsets refer to the original ``source``.  Raises :class:`SpliceError`
    (no output produced) on: mixed stream xrefs, whole-stream digest
    mismatch, out-of-range or overlapping ranges, or expected-bytes drift.
    """
    if not replacements:
        return source

    xrefs = {r.stream_xref for r in replacements}
    if len(xrefs) != 1:
        raise SpliceError(f"replacements span multiple stream xrefs: {sorted(xrefs)}")

    digest = hashlib.sha256(source).hexdigest()
    for r in replacements:
        if r.expected_stream_digest != digest:
            raise SpliceError(
                f"stream digest mismatch for xref {r.stream_xref}: plan is stale"
            )
    for r in replacements:
        if not (0 <= r.start <= r.end <= len(source)):
            raise SpliceError(
                f"replacement range [{r.start}, {r.end}) out of range "
                f"for stream of {len(source)} bytes"
            )

    ordered = sorted(replacements, key=lambda r: (r.start, r.end))
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start < prev.end:
            raise SpliceError(
                f"replacement ranges overlap: [{prev.start}, {prev.end}) and "
                f"[{nxt.start}, {nxt.end})"
            )
    for r in ordered:
        if source[r.start : r.end] != r.expected_bytes:
            raise SpliceError(
                f"expected bytes mismatch at [{r.start}, {r.end}): "
                "source changed since the plan was prepared"
            )

    parts: list[bytes] = []
    cursor = 0
    for r in ordered:
        parts.append(source[cursor : r.start])
        parts.append(r.replacement_bytes)
        cursor = r.end
    parts.append(source[cursor:])
    return b"".join(parts)
