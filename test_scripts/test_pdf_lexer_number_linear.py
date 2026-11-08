from __future__ import annotations

import itertools
import re
import time

from model.text_commit import pdf_lexer, transforms
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream

_OLD_NUMBER_RE = re.compile(rb"\A[+-]?(?:\d+\.?\d*|\.\d+)\Z")
_OLD_TRANSFORM_RE = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$")

_HAND_CASES = [
    b"1", b"-1", b"+.5", b"1.", b".", b"-", b"1.2.3", b"00012", b"1e5", b"",
    b"+", b"+-1", b"-.", b"-.5", b"5.5", b"1\n", b"0" * 50,
]


def _words(alphabet: bytes, max_len: int):
    for n in range(max_len + 1):
        for combo in itertools.product(alphabet, repeat=n):
            yield bytes(combo)


def test_number_classifier_matches_old_regex_exhaustively():
    for word in itertools.chain(_HAND_CASES, _words(b"+-.0123x", 6)):
        assert bool(pdf_lexer._NUMBER_RE.match(word)) == bool(_OLD_NUMBER_RE.match(word)), word


def test_transform_number_regex_matches_old_regex():
    alphabet = b"+-.0123x\n"
    for word in itertools.chain(_HAND_CASES, _words(alphabet, 5)):
        text = word.decode("latin-1")
        assert bool(transforms._PDF_NUMBER_RE.match(text)) == bool(_OLD_TRANSFORM_RE.match(text)), word


def test_long_digit_word_lexes_in_linear_time():
    n = 40_000
    data = b"BT ET\n" + b"0" * n + b"x\n"
    for coalesce in (False, True):
        start = time.perf_counter()
        tokens = list(lex_content_stream(data, coalesce_inert=coalesce))
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"coalesce_inert={coalesce}: {elapsed:.2f}s"
        assert b"".join(data[t.start:t.end] for t in tokens) == data
    plain = list(lex_content_stream(data))
    word = [t for t in plain if t.end - t.start == n + 1]
    assert len(word) == 1 and word[0].kind is TokenKind.OPERATOR


def test_long_digit_word_still_a_number_when_pure():
    data = b"0" * 40_000 + b" "
    tokens = [t for t in lex_content_stream(data) if t.kind is not TokenKind.WHITESPACE]
    assert len(tokens) == 1 and tokens[0].kind is TokenKind.NUMBER


def test_transform_number_regex_is_linear():
    text = "0" * 40_000 + "x"
    start = time.perf_counter()
    assert transforms._PDF_NUMBER_RE.match(text) is None
    assert time.perf_counter() - start < 0.5
