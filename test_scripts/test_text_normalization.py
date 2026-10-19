from __future__ import annotations

from model.text_normalization import (
    normalize_text,
    normalized_similarity,
    strip_unrenderable_controls,
    token_coverage_ratio,
)


def test_normalize_strips_whitespace():
    assert normalize_text("hello  world") == "helloworld"


def test_normalize_lowercases():
    assert normalize_text("Hello") == "hello"


def test_normalize_expands_fi_ligature():
    assert normalize_text("\ufb01re") == "fire"


def test_normalize_expands_ff_ligature():
    assert normalize_text("\ufb00") == "ff"


def test_normalize_empty():
    assert normalize_text("") == ""


def test_similarity_identical():
    assert normalized_similarity("abc", "abc") == 1.0


def test_similarity_one_empty():
    assert normalized_similarity("abc", "") == 0.0


def test_similarity_substring():
    assert normalized_similarity("hello", "say hello world") == 1.0


def test_token_coverage_full():
    assert token_coverage_ratio("hello world", normalize_text("hello world")) == 1.0


def test_token_coverage_empty_source():
    assert token_coverage_ratio("", "anything") == 1.0


def test_token_coverage_no_match():
    assert token_coverage_ratio("xyz abc", normalize_text("unrelated")) == 0.0


# ---- F16-PASTE-1: strip_unrenderable_controls --------------------------------------


def test_strip_controls_removes_c0_c1_del_and_noncharacters():
    assert strip_unrenderable_controls("a\x00b\x01c\x0bd\x0ce\x1ff\x7fg\x85h\x9fi\ufffej\uffffk") == "abcdefghijk"


def test_strip_controls_keeps_tab_newline_and_text():
    assert strip_unrenderable_controls("a\tb\nc 中文 \U0001f600 ‍") == "a\tb\nc 中文 \U0001f600 ‍"


def test_strip_controls_folds_carriage_returns_to_newlines():
    assert strip_unrenderable_controls("a\r\nb\rc\n\rd") == "a\nb\nc\n\nd"


def test_strip_controls_empty_and_none():
    assert strip_unrenderable_controls("") == ""
    assert strip_unrenderable_controls(None) == ""


def test_strip_controls_removes_the_object_replacement_character():
    """F16-PASTE-2: an image in pasted HTML is U+FFFC in ``toPlainText()``; it is an
    inline-object anchor, not text, and htmlbox draws it as a dashed "OBJ" box."""
    assert strip_unrenderable_controls("Logo \ufffc X") == "Logo  X"
    assert strip_unrenderable_controls("\ufffc\ufffc") == ""


def test_strip_controls_is_idempotent():
    once = strip_unrenderable_controls("x\x00\r\ny")
    assert strip_unrenderable_controls(once) == once
