"""Put back the turned text a text redaction erased by mistake (S17-WMARK-UNDER).

MuPDF's text redaction removes every glyph whose box touches a redacted point.
For a glyph written off the page axes (a 45-degree "DRAFT" watermark) that box
is the bounding square of a turned em box: a 60 pt glyph's box covers a
60 x 60 pt square, so the redaction points inside a 12 pt word that merely sits
near the watermark's ink also erase watermark glyphs the edit never meant to
touch.  Owner decision (2026-10-12): the watermark is protected; only the old
word's glyphs go.

The redaction rewrites the page's content streams, but keeps every operator in
its place and only drops the erased glyphs (compensating the advance with a
``TJ`` kern).  So the damage can be repaired exactly: the turned text is
written back with its ORIGINAL operator bytes, at the same position in the
same stream, so its text, origins, directions, colour, opacity and z-order are
the source's own.  Nothing is replayed or redrawn.

Two repairs, both from the source bytes of the page's own content streams:

* a top-level ``q ... Q`` block whose every show is turned is written back whole
  (this also brings back a block the redaction emptied because ALL its glyphs
  were hit, e.g. a watermark drawn one glyph per show);
* any other turned ``Tj``/``TJ`` show the redaction changed is written back as
  its original operator.

A turned show inside a form XObject (the redaction filters the form's stream
too) or one that cannot be paired with certainty is left as the redaction made
it; the caller then still sees the glyph as lost and refuses the edit.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from typing import NamedTuple

import fitz

from model.text_commit.dto import StreamReplacement
from model.text_commit.inspect import read_page_streams
from model.text_commit.pdf_lexer import (
    SpliceError,
    TokenKind,
    lex_content_stream,
    splice_stream,
)
from model.text_commit.replay import ShowOp, replay_page_streams

logger = logging.getLogger(__name__)

# Same reading as ``pdf_text_edit._is_axis_aligned_dir``: a direction whose
# smaller component is under this fraction of the larger one lies on an axis.
_AXIS_TOL = 1e-3
_SPLICEABLE = frozenset({"Tj", "TJ"})
_KEY_DIGITS = 3

ShowKey = tuple[object, ...]
PageStreams = list[tuple[int, bytes]]


def read_streams(doc: fitz.Document, page: fitz.Page) -> PageStreams:
    """The page's decoded content streams, in order (capture BEFORE the redaction)."""
    return read_page_streams(doc, page)


def _trm(show: ShowOp) -> tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = show.tm
    a2, b2, c2, d2, e2, f2 = show.ctm
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _is_turned(show: ShowOp) -> bool:
    """True when the show's writing direction is off the page axes."""
    a, b = _trm(show)[:2]
    lo, hi = sorted((abs(a), abs(b)))
    return hi > 1e-9 and lo > _AXIS_TOL * hi


def _key(show: ShowOp) -> ShowKey:
    """What two views of the SAME show agree on: placement and text state."""
    return (
        *(round(v, _KEY_DIGITS) for v in _trm(show)),
        show.font_resource,
        round(show.font_size, _KEY_DIGITS),
        show.render_mode,
        round(show.char_spacing, _KEY_DIGITS),
        round(show.word_spacing, _KEY_DIGITS),
        round(show.hscale, _KEY_DIGITS),
        round(show.rise, _KEY_DIGITS),
    )


class _Block(NamedTuple):
    """One top-level ``q ... Q`` block: a byte range of one decoded stream."""

    stream_xref: int
    start: int
    end: int


def _top_level_blocks(streams: PageStreams) -> list[_Block] | None:
    """The depth-0 ``q ... Q`` blocks of ``streams`` in drawing order; ``None``
    when a stream is unbalanced (a block would span streams)."""
    blocks: list[_Block] = []
    for xref, data in streams:
        depth = 0
        start = 0
        for token in lex_content_stream(data):
            if token.kind is TokenKind.MALFORMED:
                return None
            if token.kind is not TokenKind.OPERATOR:
                continue
            word = data[token.start : token.end]
            if word == b"q":
                if depth == 0:
                    start = token.start
                depth += 1
            elif word == b"Q":
                depth -= 1
                if depth < 0:
                    return None
                if depth == 0:
                    blocks.append(_Block(xref, start, token.end))
        if depth != 0:
            return None
    return blocks


def _group_by_block(blocks: list[_Block], shows: list[ShowOp]) -> dict[int, list[ShowOp]]:
    """``shows`` keyed by the index of the block holding them (outside: absent)."""
    grouped: dict[int, list[ShowOp]] = defaultdict(list)
    for show in shows:
        for index, block in enumerate(blocks):
            if (
                block.stream_xref == show.stream_xref
                and block.start <= show.op_start
                and show.op_end <= block.end
            ):
                grouped[index].append(show)
                break
    return grouped


def restore_turned_shows(
    doc: fitz.Document, page: fitz.Page, before: PageStreams
) -> bool:
    """Write the turned text the redaction changed back to its ``before`` bytes;
    ``True`` when the page was changed.

    ``before``: :func:`read_streams` taken before the redaction.  ``False``
    (page untouched) when the page cannot be read as matching streams, or a
    changed show cannot be paired or spliced with certainty.
    """
    after = read_page_streams(doc, page)
    old = replay_page_streams(before)
    new = replay_page_streams(after)
    if old.malformed or new.malformed or old.refusal_reason or new.refusal_reason:
        return False

    old_bytes = dict(before)
    new_bytes = dict(after)
    old_shows = list(old.shows)
    new_shows = list(new.shows)
    replacements: dict[int, list[StreamReplacement]] = defaultdict(list)

    def replace(xref: int, start: int, end: int, source: bytes) -> None:
        stream = new_bytes[xref]
        replacements[xref].append(
            StreamReplacement(
                stream_xref=xref,
                start=start,
                end=end,
                expected_bytes=stream[start:end],
                replacement_bytes=source,
                expected_stream_digest=hashlib.sha256(stream).hexdigest(),
            )
        )

    # 1. Whole blocks that draw nothing but turned text.
    old_blocks = _top_level_blocks(before)
    new_blocks = _top_level_blocks(after)
    handled_old: set[int] = set()
    handled_new: set[int] = set()
    if old_blocks is not None and new_blocks is not None and len(old_blocks) == len(new_blocks):
        old_in = _group_by_block(old_blocks, old_shows)
        new_in = _group_by_block(new_blocks, new_shows)
        for index, shows in old_in.items():
            if not all(_is_turned(s) for s in shows):
                continue
            keys = {_key(s) for s in shows}
            if any(_key(s) not in keys for s in new_in.get(index, [])):
                continue  # block k of the redacted page is not this block
            was, now = old_blocks[index], new_blocks[index]
            handled_old.update(id(s) for s in shows)
            handled_new.update(id(s) for s in new_in.get(index, []))
            source = old_bytes[was.stream_xref][was.start : was.end]
            if source != new_bytes[now.stream_xref][now.start : now.end]:
                replace(now.stream_xref, now.start, now.end, source)

    # 2. The remaining turned shows, one operator at a time.
    old_by_key: dict[ShowKey, list[ShowOp]] = defaultdict(list)
    new_by_key: dict[ShowKey, list[ShowOp]] = defaultdict(list)
    for show in old_shows:
        if id(show) not in handled_old:
            old_by_key[_key(show)].append(show)
    for show in new_shows:
        if id(show) not in handled_new:
            new_by_key[_key(show)].append(show)
    for key, olds in old_by_key.items():
        if not any(_is_turned(s) for s in olds):
            continue
        news = new_by_key.get(key, [])
        if len(news) != len(olds):
            # The redaction dropped or split a show: no certain pairing.
            logger.debug(
                "turned show restore: %s old vs %s new shows for %s", len(olds), len(news), key
            )
            return False
        for src, cur in zip(olds, news):
            source_op = old_bytes[src.stream_xref][src.op_start : src.op_end]
            current_op = new_bytes[cur.stream_xref][cur.op_start : cur.op_end]
            if source_op == current_op:
                continue
            if src.operator not in _SPLICEABLE or cur.operator not in _SPLICEABLE:
                return False
            replace(cur.stream_xref, cur.op_start, cur.op_end, source_op)
    if not replacements:
        return False

    try:
        patched = {
            xref: splice_stream(new_bytes[xref], reps) for xref, reps in replacements.items()
        }
    except SpliceError as exc:
        logger.debug("turned show restore: splice refused: %s", exc)
        return False
    for xref, data in patched.items():
        doc.update_stream(xref, data)
    return True
