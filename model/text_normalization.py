from __future__ import annotations

import difflib
import re

from utils.text_chars import split_unrenderable

# Whitespace normalizer — strips all whitespace for comparison.
_RE_WS_STRIP = re.compile(r'\s+')

# Unicode ligature → decomposed character mapping.
# PyMuPDF's insert_htmlbox renders ligature substitutions (e.g. fi→ﬁ),
# so get_text() extraction diverges from the original string.
# This table expands them before any text comparison.
_LIGATURE_MAP = {
    '\ufb00': 'ff',   # ﬀ
    '\ufb01': 'fi',   # ﬁ
    '\ufb02': 'fl',   # ﬂ
    '\ufb03': 'ffi',  # ﬃ
    '\ufb04': 'ffl',  # ﬄ
    '\ufb05': 'st',   # ﬅ (long s + t)
    '\ufb06': 'st',   # ﬆ
}


def expand_ligatures(text: str) -> str:
    """``text`` with every ligature of ``_LIGATURE_MAP`` expanded to its letters."""
    for lig, expanded in _LIGATURE_MAP.items():
        if lig in text:
            text = text.replace(lig, expanded)
    return text


def strip_unrenderable_controls(text: str | None) -> str:
    """``text`` without the characters ``insert_htmlbox`` / ``insert_text`` cannot draw.

    MuPDF's HTML engine stops at an embedded NUL (every character after it is
    silently dropped) and draws every other C0/C1 control code, DEL and
    noncharacter as a replacement glyph (U+0239 in the text layer); form feed
    renders as a space and vertical tab as the glyph.  U+FFFC (an inline-object
    anchor, what a pasted image leaves behind) is drawn as a dashed "OBJ" box
    and kept in the text layer (F16-PASTE-2).  None of them has a
    visible form, so they are removed at the one place user text enters a drawn
    textbox / watermark instead of being committed lossy or truncated
    (F16-PASTE-1).  Line breaks stay: CR LF and a lone CR become LF (the HTML
    engine already drew them as breaks); tab and LF are kept.  Idempotent.  The character
    set lives in ``utils.text_chars`` (shared with the inline editor's paste notice).
    """
    return split_unrenderable(text)[0]


def normalize_text(text: str) -> str:
    """Strip whitespace, lowercase, expand Unicode ligatures for text comparison.

    PyMuPDF's insert_htmlbox rendering substitutes letter combinations with
    Unicode ligatures (e.g. fi→ﬁ), causing get_text() extraction to diverge
    from the original string. This function normalizes both sides before
    comparison.
    """
    if not text:
        return ""
    # Drop unstable extraction artifacts and normalize common punctuation variants.
    result = (
        expand_ligatures(text)
        .replace("\ufffd", "")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return _RE_WS_STRIP.sub('', result).lower()


def is_unchanged_text(current: str, requested: str) -> bool:
    """True when ``requested`` is the text already on the page.

    The "is this edit a no-op" gate.  Deliberately NOT ``normalize_text``:
    that comparator is a search/verification fuzz (lowercase, every
    whitespace stripped, curly quotes folded, ZWSP/BOM dropped) and using it
    here silently dropped edits the commit engine writes ("Price 2024" ->
    "PRICE 2024", a straight -> curly apostrophe, a doubled or removed
    space, an inserted ZWSP).  Only extraction artifacts are forgiven:
    ligature glyphs (extraction returns ``fi`` for ``ﬁ``) and U+FFFD.  Any
    other difference is an edit the engine must see.
    """
    return _strip_extraction_artifacts(current) == _strip_extraction_artifacts(requested)


def _strip_extraction_artifacts(text: str | None) -> str:
    if not text:
        return ""
    return expand_ligatures(text).replace("\ufffd", "")


def normalized_similarity(left: str, right: str) -> float:
    """Similarity score on normalized strings (0..1).

    Returns 1.0 if either string contains the other as a substring (after
    normalization), otherwise falls back to difflib SequenceMatcher ratio.
    """
    norm_left = normalize_text(left)
    norm_right = normalize_text(right)
    if not norm_left and not norm_right:
        return 1.0
    if not norm_left or not norm_right:
        return 0.0
    if norm_left in norm_right or norm_right in norm_left:
        return 1.0
    return difflib.SequenceMatcher(None, norm_left, norm_right).ratio()


def token_coverage_ratio(source_text: str, haystack_norm: str) -> float:
    """Return token hit ratio (0..1) using normalized token containment with 1-char tolerance.

    Splits source_text on whitespace, normalizes each token, and counts how
    many appear in the pre-normalized haystack_norm. A one-character prefix/
    suffix truncation is allowed to absorb minor OCR/extraction drift.
    """
    if not source_text:
        return 1.0
    if not haystack_norm:
        return 0.0
    raw_tokens = [tok for tok in re.split(r"\s+", source_text) if tok]
    tokens = [normalize_text(tok) for tok in raw_tokens]
    tokens = [tok for tok in tokens if tok]
    if not tokens:
        return 1.0
    hit = 0
    for tok in tokens:
        if tok in haystack_norm:
            hit += 1
            continue
        if len(tok) >= 4 and (tok[1:] in haystack_norm or tok[:-1] in haystack_norm):
            hit += 1
    return hit / len(tokens)
