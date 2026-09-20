"""Red-light tests for the lossless content-stream lexer and raw splicer.

Plan Task 2 (plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md):
the lexer must record exact source byte ranges including whitespace and
comments (no normalization), and the splicer must refuse to produce output
unless every replacement's expected bytes and stream digest match.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import StreamReplacement  # noqa: E402
from model.text_commit.pdf_lexer import (  # noqa: E402
    SpliceError,
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    encode_literal_string,
    lex_content_stream,
    splice_stream,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _kinds(tokens) -> list[TokenKind]:
    return [t.kind for t in tokens]


def _nontrivia(tokens):
    return [
        t
        for t in tokens
        if t.kind not in (TokenKind.WHITESPACE, TokenKind.COMMENT)
    ]


def _reassemble(source: bytes, tokens) -> bytes:
    return b"".join(source[t.start : t.end] for t in tokens)


# ---------------------------------------------------------------- lexing


def test_tokens_tile_source_exactly():
    source = (
        b"q 1 0 0 1 72 700 cm % transform\n"
        b"BT /F1 12.5 Tf (Hello \\(World\\)) Tj ET\n"
        b"[(A) -120 (V)] TJ <48 65 6C> Tj Q"
    )
    tokens = list(lex_content_stream(source))
    assert _reassemble(source, tokens) == source
    # offsets are contiguous and gap-free
    pos = 0
    for token in tokens:
        assert token.start == pos
        assert token.end > token.start
        pos = token.end
    assert pos == len(source)


def test_whitespace_and_comments_are_trivia_tokens():
    source = b"BT\n% a comment ( with parens\n(Txt) Tj\r\nET"
    tokens = list(lex_content_stream(source))
    assert TokenKind.COMMENT in _kinds(tokens)
    assert TokenKind.WHITESPACE in _kinds(tokens)
    comment = next(t for t in tokens if t.kind == TokenKind.COMMENT)
    assert source[comment.start : comment.end] == b"% a comment ( with parens"
    ops = [source[t.start : t.end] for t in _nontrivia(tokens)]
    assert ops == [b"BT", b"(Txt)", b"Tj", b"ET"]


def test_literal_string_nesting_and_escapes():
    source = b"(outer (nested) more) Tj (esc \\) close) Tj"
    tokens = _nontrivia(lex_content_stream(source))
    assert tokens[0].kind == TokenKind.STRING
    assert source[tokens[0].start : tokens[0].end] == b"(outer (nested) more)"
    assert tokens[2].kind == TokenKind.STRING
    assert source[tokens[2].start : tokens[2].end] == b"(esc \\) close)"


def test_literal_string_decode_escapes():
    assert decode_literal_string(b"(Hello)") == b"Hello"
    assert decode_literal_string(b"(a\\(b\\))") == b"a(b)"
    assert decode_literal_string(b"(tab\\there)") == b"tab\there"
    assert decode_literal_string(b"(oct\\101)") == b"octA"
    assert decode_literal_string(b"(nl\\\njoin)") == b"nljoin"  # line continuation
    # Backslash-EOL continuation swallows the EOL and emits no byte, for
    # all three EOL spellings (PDF 32000-1 7.3.4.2).
    assert decode_literal_string(bytes([0x28, 0x61, 0x5C, 0x0D, 0x62, 0x29])) == b"ab"
    assert decode_literal_string(bytes([0x28, 0x61, 0x5C, 0x0D, 0x0A, 0x62, 0x29])) == b"ab"
    assert decode_literal_string(b"(back\\\\slash)") == b"back\\slash"
    assert decode_literal_string(b"(bare\\q)") == b"bareq"  # unknown escape drops backslash


def test_literal_string_bare_eol_collapses_to_one_lf():
    """A bare (unescaped) CR, LF or CRLF inside a literal is one 0x0A byte

    (PDF 32000-1 7.3.4.2). Measured 2026-09-06 against MuPDF 1.27.1's own
    lexer via ``page.get_text`` (see the parametrised page-level test
    below); this pins the same contract at the decoder's own boundary.
    """
    assert decode_literal_string(bytes([0x28, 0x61, 0x0D, 0x62, 0x29])) == b"a\nb"
    assert decode_literal_string(bytes([0x28, 0x61, 0x0D, 0x0A, 0x62, 0x29])) == b"a\nb"
    # A bare LF followed by a bare CR is two independent EOL markers, not
    # one CRLF pair (order matters: CR only swallows a *following* LF).
    assert decode_literal_string(bytes([0x28, 0x61, 0x0A, 0x0D, 0x62, 0x29])) == b"a\n\nb"
    # Already-correct control case: a lone bare LF was never the defect.
    assert decode_literal_string(bytes([0x28, 0x61, 0x0A, 0x62, 0x29])) == b"a\nb"


def _eol_probe_doc(literal_body: bytes) -> fitz.Document:
    """A page shaped exactly like ``test_text_commit_tier0.py::_tier0_doc``

    whose first ``Tj`` literal is ``literal_body`` (parens excluded,
    verbatim — the caller supplies any raw backslash/CR/LF bytes).
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + literal_body + b") Tj "
        b"0 -40 Td (Downstream line stays) Tj ET"
    )
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


@pytest.mark.parametrize(
    ("case_id", "literal_body"),
    [
        # Three divergent cases (2026-09-06 measurement against MuPDF
        # 1.27.1): the repo decoder kept raw 0x0D bytes where MuPDF
        # collapses to a single 0x0A.
        ("bare_cr", bytes([0x61, 0x0D, 0x62])),
        ("bare_crlf", bytes([0x61, 0x0D, 0x0A, 0x62])),
        ("bare_lf_then_bare_cr", bytes([0x61, 0x0A, 0x0D, 0x62])),
        # Three backslash-EOL continuation forms: must produce no byte.
        ("continuation_cr", bytes([0x61, 0x5C, 0x0D, 0x62])),
        ("continuation_lf", bytes([0x61, 0x5C, 0x0A, 0x62])),
        ("continuation_crlf", bytes([0x61, 0x5C, 0x0D, 0x0A, 0x62])),
        # MuPDF-judged control case: a lone bare LF was already correct;
        # pinning it here proves the fix does not regress it.
        ("bare_lf", bytes([0x61, 0x0A, 0x62])),
    ],
)
def test_decode_literal_string_matches_mupdf_eol_handling(case_id, literal_body):
    doc = _eol_probe_doc(literal_body)
    try:
        extracted = doc[0].get_text("text")
    finally:
        doc.close()
    decoded = decode_literal_string(b"(" + literal_body + b")")
    expected = decoded.decode("latin-1") + "\nDownstream line stays\n"
    assert extracted == expected, (
        f"{case_id}: decode_literal_string({literal_body!r}) == {decoded!r} "
        f"is not corroborated by MuPDF's own extraction: {extracted!r} != {expected!r}"
    )


def test_literal_string_encode_roundtrip():
    for value in (b"Hello", b"a(b)c", b"back\\slash", b"m\xc3\xa9tier", b"\x00\x01"):
        encoded = encode_literal_string(value)
        assert decode_literal_string(encoded) == value


def test_hex_string_lexing_and_decoding():
    source = b"<48 65\n6C6C6F> Tj"
    tokens = _nontrivia(lex_content_stream(source))
    assert tokens[0].kind == TokenKind.HEXSTRING
    assert source[tokens[0].start : tokens[0].end] == b"<48 65\n6C6C6F>"
    assert decode_hex_string(b"<48656C6C6F>") == b"Hello"
    assert decode_hex_string(b"<48656C6C6F7>") == b"Hello\x70"  # odd digit pads 0


def test_dict_tokens_are_not_hex_strings():
    source = b"<< /Type /Page /Kids [3 0 R] >>"
    tokens = _nontrivia(lex_content_stream(source))
    assert tokens[0].kind == TokenKind.DICT_OPEN
    assert tokens[-1].kind == TokenKind.DICT_CLOSE
    names = [t for t in tokens if t.kind == TokenKind.NAME]
    assert [source[t.start : t.end] for t in names[:2]] == [b"/Type", b"/Page"]


def test_array_with_kerning_numbers():
    source = b"[(A) -120 (V) 33.5 (T)] TJ"
    tokens = _nontrivia(lex_content_stream(source))
    kinds = [t.kind for t in tokens]
    assert kinds == [
        TokenKind.ARRAY_OPEN,
        TokenKind.STRING,
        TokenKind.NUMBER,
        TokenKind.STRING,
        TokenKind.NUMBER,
        TokenKind.STRING,
        TokenKind.ARRAY_CLOSE,
        TokenKind.OPERATOR,
    ]
    assert source[tokens[-1].start : tokens[-1].end] == b"TJ"


def test_operator_variants_and_numbers():
    source = b"BT .5 -4. +3 Ts T* (x) ' (y) \" ET"
    tokens = _nontrivia(lex_content_stream(source))
    raw = [source[t.start : t.end] for t in tokens]
    assert b"T*" in raw
    assert b"'" in raw
    assert b'"' in raw
    numbers = [source[t.start : t.end] for t in tokens if t.kind == TokenKind.NUMBER]
    assert numbers == [b".5", b"-4.", b"+3"]


def test_inline_image_payload_is_one_token():
    payload = b"\x00\xff(\x29\\ei EI-not-end "
    source = b"BI /W 2 /H 2 /BPC 8 /CS /G ID " + payload + b"EI Q"
    tokens = list(lex_content_stream(source))
    assert _reassemble(source, tokens) == source
    data = [t for t in tokens if t.kind == TokenKind.INLINE_IMAGE_DATA]
    assert len(data) == 1
    ops = [
        source[t.start : t.end]
        for t in _nontrivia(lex_content_stream(source))
        if t.kind == TokenKind.OPERATOR
    ]
    assert ops[-1] == b"Q"


def test_malformed_unterminated_string_flagged_not_raised():
    source = b"BT (never closed"
    tokens = list(lex_content_stream(source))
    assert _reassemble(source, tokens) == source
    assert tokens[-1].kind == TokenKind.MALFORMED


def test_malformed_stray_close_delimiter():
    source = b"(x) > Tj"
    tokens = _nontrivia(lex_content_stream(source))
    assert TokenKind.MALFORMED in [t.kind for t in tokens]


def test_exact_offsets_for_target_string():
    source = b"BT /F1 12 Tf 72 700 Td (Hello World) Tj ET"
    tokens = lex_content_stream(source)
    target = next(t for t in tokens if t.kind == TokenKind.STRING)
    assert source[target.start : target.end] == b"(Hello World)"


# ---------------------------------------------------------------- splicing


def _replacement(
    source: bytes,
    start: int,
    end: int,
    new: bytes,
    *,
    xref: int = 7,
    digest: str | None = None,
    expected: bytes | None = None,
) -> StreamReplacement:
    return StreamReplacement(
        stream_xref=xref,
        start=start,
        end=end,
        expected_bytes=source[start:end] if expected is None else expected,
        replacement_bytes=new,
        expected_stream_digest=_digest(source) if digest is None else digest,
    )


def test_splice_preserves_all_bytes_outside_range():
    before = b"BT (Hello World) Tj ET"
    start, end = before.index(b"(Hello World)"), before.index(b"(Hello World)") + len(
        b"(Hello World)"
    )
    replacement = b"(Jello World)"
    after = splice_stream(before, [_replacement(before, start, end, replacement)])
    assert after[:start] == before[:start]
    assert after[start : start + len(replacement)] == replacement
    assert after[start + len(replacement) :] == before[end:]


def test_splice_multiple_replacements_use_original_offsets():
    before = b"(one) Tj (two) Tj (three) Tj"
    spans = [(before.index(t), before.index(t) + len(t)) for t in (b"(one)", b"(three)")]
    after = splice_stream(
        before,
        [
            _replacement(before, spans[0][0], spans[0][1], b"(ONE-LONGER)"),
            _replacement(before, spans[1][0], spans[1][1], b"(3)"),
        ],
    )
    assert after == b"(ONE-LONGER) Tj (two) Tj (3) Tj"


def test_splice_rejects_digest_mismatch():
    before = b"(abc) Tj"
    with pytest.raises(SpliceError, match="digest"):
        splice_stream(before, [_replacement(before, 0, 5, b"(x)", digest="0" * 64)])


def test_splice_rejects_expected_bytes_mismatch():
    before = b"(abc) Tj"
    with pytest.raises(SpliceError, match="expected bytes"):
        splice_stream(before, [_replacement(before, 0, 5, b"(x)", expected=b"(zzz)")])


def test_splice_rejects_overlapping_replacements():
    before = b"(abcdef) Tj"
    with pytest.raises(SpliceError, match="overlap"):
        splice_stream(
            before,
            [
                _replacement(before, 0, 5, b"(x)"),
                _replacement(before, 4, 8, b"(y)"),
            ],
        )


def test_splice_rejects_out_of_range():
    before = b"(abc) Tj"
    with pytest.raises(SpliceError, match="range"):
        splice_stream(before, [_replacement(before, 0, 99, b"(x)", expected=b"")])


def test_splice_rejects_mixed_stream_xrefs():
    before = b"(one) Tj (two) Tj"
    with pytest.raises(SpliceError, match="xref"):
        splice_stream(
            before,
            [
                _replacement(before, 0, 5, b"(x)", xref=7),
                _replacement(before, 9, 14, b"(y)", xref=8),
            ],
        )


def test_splice_empty_replacement_list_is_identity():
    before = b"BT (Hello) Tj ET"
    assert splice_stream(before, []) == before


def test_stream_replacement_is_immutable():
    replacement = StreamReplacement(
        stream_xref=1,
        start=0,
        end=1,
        expected_bytes=b"a",
        replacement_bytes=b"b",
        expected_stream_digest="00",
    )
    with pytest.raises(AttributeError):
        replacement.start = 5  # type: ignore[misc]
