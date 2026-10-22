from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable

import fitz

from model.geometry import visual_to_unrotated_point
from model.text_commit.pdf_lexer import (
    StreamToken,
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    encode_hex_string,
    lex_content_stream,
)
from model.text_commit.transforms import insert_text_page_space
from utils.pdf_object_source import xref_set_key_exact

logger = logging.getLogger(__name__)

# F17-COH-2: every stream the renderer writes is wrapped in a marked-content
# sequence that names its watermark,
#   /Artifact <</Type /Pagination /Subtype /Watermark /PdfEditorWatermark <id>>> BDC ... EMC
# (the PDF's own way to say "this ink is a watermark").  A saved file carries
# the baked ink AND the stored parameters; on reopen the parameters are the one
# source of truth (live overlay, print stamp, next save), so the marked copy is
# taken back out of the live document (``strip_marked_watermarks``).  The mark
# is inside the content, not on the stream dictionary, because
# ``Page.clean_contents`` (the optimizer's content cleanup, other tools) merges
# the page's streams into one and keeps marked content but not stream keys.
WATERMARK_MARK_KEY = b"/PdfEditorWatermark"
_ARTIFACT_TAG = b"/Artifact"
_MARK_CLOSE = b"\nEMC\nQ\n"
_PDF_WHITESPACE = b"\x00\t\n\x0c\r "
# What a marked block may contain to be taken out: the text-and-state operators
# ``insert_text`` writes (and ``clean_contents`` may rewrite them to).  A block
# carrying anything else (images, forms, paths, nested marked content, inline
# images) is not this renderer's ink and is left alone.
_STRIPPABLE_OPERATORS = frozenset({
    b"q", b"Q", b"cm", b"gs", b"BT", b"ET", b"Tf", b"Tm", b"Td", b"TD", b"T*",
    b"Tj", b"TJ", b"'", b'"', b"Tc", b"Tw", b"Tz", b"TL", b"Tr", b"Ts",
    b"w", b"J", b"j", b"M", b"d", b"ri", b"i",
    b"g", b"G", b"rg", b"RG", b"k", b"K", b"cs", b"CS", b"sc", b"SC", b"scn", b"SCN",
})
_SKIPPED_TOKENS = frozenset({TokenKind.WHITESPACE, TokenKind.COMMENT})


def needs_cjk_font(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))


def resolve_watermark_font(font_name: str, text: str) -> str:
    non_cjk_fonts = ("helv", "cour", "Helvetica", "Courier")
    if needs_cjk_font(text) and font_name in non_cjk_fonts:
        return "china-ts"
    return font_name


def apply_watermarks_to_page(page: fitz.Page, watermarks: list[dict]) -> None:
    """Stamp *watermarks* onto *page*.

    The centre, the offsets (``offset_x`` positive right, ``offset_y`` positive
    down) and the angle are the DISPLAYED page's, so a ``/Rotate`` page gets the
    same on-screen watermark as an upright page of the same displayed size
    (F15-G5).  Each stream written for a watermark with an ``id`` is marked
    with that id (F17-COH-2, see ``WATERMARK_MARK_KEY``).
    """
    if not watermarks:
        return

    page_rect = page.rect
    cx = page_rect.width / 2
    cy = page_rect.height / 2
    rotation = int(page.rotation) % 360

    for wm in watermarks:
        text = wm.get("text", "")
        angle = wm.get("angle", 0)
        opacity = max(0.0, min(1.0, wm.get("opacity", 0.5)))
        font_size = wm.get("font_size", 48.0)
        color = wm.get("color", (0.7, 0.7, 0.7))
        font_name = resolve_watermark_font(wm.get("font", "helv"), text)
        offset_x = wm.get("offset_x", 0)
        offset_y = wm.get("offset_y", 0)
        line_spacing = wm.get("line_spacing", 1.3)

        # Centre in the displayed frame (offsets are displayed right/down), then
        # into the UNROTATED frame ``Page.insert_text`` takes coordinates in and
        # draws its glyphs in (the identity at ``/Rotate 0``).
        center = visual_to_unrotated_point(page, fitz.Point(cx + offset_x, cy + offset_y))

        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            continue

        try:
            font = fitz.Font(font_name)
        except Exception:
            font = fitz.Font("china-ts" if needs_cjk_font(text) else "helv")

        line_height = font_size * line_spacing
        total_height = line_height * len(lines)
        # Every line's origin is laid out UNROTATED around the centre: the block
        # is centred on it (line ``i``'s middle sits ``(i + 0.5)`` lines below the
        # block's top, and a cap-height middle is ``0.35 em`` above its baseline)
        # and each line is centred across.  ``insert_text``'s ``morph`` then turns
        # origin AND glyphs about the centre by the on-screen angle plus the
        # page's own ``/Rotate`` (the unrotated frame is turned clockwise on
        # screen, so the glyphs are counter-turned).  The origin must NOT also be
        # pre-turned here: that rotated it by twice the angle (F15-G5-GEOM).
        morph_rad = math.radians(-(angle + rotation))
        mat = fitz.Matrix(math.cos(morph_rad), -math.sin(morph_rad), math.sin(morph_rad), math.cos(morph_rad), 0, 0)

        wm_id = str(wm.get("id") or "")
        for i, line in enumerate(lines):
            line_len = font.text_length(line, fontsize=font_size)
            dx = -line_len / 2
            dy = -total_height / 2 + (i + 0.5) * line_height + font_size * 0.35
            pt = fitz.Point(center.x + dx, center.y + dy)
            streams_before = set(page.get_contents())
            # Page units in, ``/UserUnit`` undone inside (F15-G6): the centre,
            # the font size and the offsets above are all ``page.rect`` units.
            insert_text_page_space(
                page,
                pt,
                line,
                fontsize=font_size,
                fontname=font_name,
                color=color[:3] if len(color) >= 3 else (0.7, 0.7, 0.7),
                morph=(center, mat),
                fill_opacity=opacity,
                stroke_opacity=opacity,
            )
            if wm_id:
                _mark_written_stream(page, streams_before, wm_id)


def apply_watermarks_to_document(doc: fitz.Document, watermarks: list[dict]) -> None:
    for wm in watermarks:
        for page_num in wm.get("pages", []):
            if 1 <= page_num <= len(doc):
                apply_watermarks_to_page(doc[page_num - 1], [wm])


def _mark_written_stream(page: fitz.Page, streams_before: set[int], wm_id: str) -> None:
    """Wrap the stream ``insert_text`` just appended in the watermark's mark.

    ``Shape.commit(overlay=True)`` appends exactly one new stream at the END of
    ``/Contents`` (a ``q`` / ``Q`` pair that balances an open page goes before
    it); nothing new at the end means nothing was drawn.  The mark sits inside
    a ``q`` ... ``Q`` of its own: MuPDF's balance count (``wrap_contents``)
    reports marked content at the top level as an open ``q`` and a stray
    ``Q``, so the next ``insert_text`` on the page would add another wrapping
    pair every time (measured: two more streams per line per save).
    """
    contents = page.get_contents()
    if not contents or contents[-1] in streams_before:
        return
    xref = contents[-1]
    doc = page.parent
    opening = (
        b"q\n"
        + _ARTIFACT_TAG
        + b" <</Type /Pagination /Subtype /Watermark "
        + WATERMARK_MARK_KEY
        + b" "
        + encode_hex_string(wm_id.encode("utf-8"))
        + b">> BDC\n"
    )
    doc.update_stream(xref, opening + (doc.xref_stream(xref) or b"") + _MARK_CLOSE)


def strip_marked_watermarks(doc: fitz.Document, watermarks: Iterable[dict]) -> int:
    """Take this renderer's marked ink of ``watermarks`` back out of ``doc``.

    Only what the stored list will draw again is removed: a block marked with
    watermark ``X`` on a page that ``X``'s own ``pages`` name.  Ink of an id
    the list does not hold, unmarked ink (files saved before the mark existed,
    PITFALLS F15-G5-GEOM) and a marked block that holds more than text-and-
    state operators all stay as page content.  A stream that held nothing but
    marked ink leaves ``/Contents``; a merged stream keeps the rest of its
    content, the parts joined by newlines.
    Returns the number of blocks removed.
    """
    ids_by_page: dict[int, set[str]] = {}
    for wm in watermarks:
        wm_id = str(wm.get("id") or "")
        if not wm_id:
            continue
        for page_num in wm.get("pages", []):
            if isinstance(page_num, int) and 1 <= page_num <= len(doc):
                ids_by_page.setdefault(page_num, set()).add(wm_id)

    removed = 0
    for page_num in sorted(ids_by_page):
        page = doc[page_num - 1]
        wanted = ids_by_page[page_num]
        contents = page.get_contents()
        keep: list[int] = []
        for xref in contents:
            data = doc.xref_stream(xref) or b""
            ranges = _marked_block_ranges(data, wanted) if WATERMARK_MARK_KEY in data else []
            if not ranges:
                keep.append(xref)
                continue
            removed += len(ranges)
            rest = _cut_ranges(data, ranges)
            if rest.strip(_PDF_WHITESPACE):
                doc.update_stream(xref, rest)
                keep.append(xref)
        if len(keep) != len(contents):
            xref_set_key_exact(doc, page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in keep) + "]")
    if removed:
        logger.debug("已移除 %s 段本程式寫入的浮水印（由儲存的參數重新繪製）", removed)
    return removed


def _cut_ranges(data: bytes, ranges: list[tuple[int, int]]) -> bytes:
    parts: list[bytes] = []
    cursor = 0
    for start, end in ranges:
        parts.append(data[cursor:start])
        cursor = end
    parts.append(data[cursor:])
    # Keep the neighbours of a removed block apart (``...Q`` + ``q...``).
    return b"\n".join(part for part in parts if part)


def _marked_block_ranges(data: bytes, wanted: set[str]) -> list[tuple[int, int]]:
    """Byte ranges ``[start, end)`` of the marked watermark blocks of ``wanted``."""
    tokens = [t for t in lex_content_stream(data) if t.kind not in _SKIPPED_TOKENS]
    ranges: list[tuple[int, int]] = []
    operand_start = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind is not TokenKind.OPERATOR:
            index += 1
            continue
        if data[token.start : token.end] == b"BDC":
            mark_id = _mark_id(data, tokens[operand_start:index])
            end_index = _block_end(data, tokens, index + 1) if mark_id in wanted else None
            if end_index is not None:
                start_index = operand_start
                # The ``q`` ... ``Q`` the mark sits in goes with it.
                if (
                    start_index >= 1
                    and end_index + 1 < len(tokens)
                    and _is_operator(data, tokens[start_index - 1], b"q")
                    and _is_operator(data, tokens[end_index + 1], b"Q")
                ):
                    start_index -= 1
                    end_index += 1
                ranges.append((tokens[start_index].start, tokens[end_index].end))
                index = end_index
        index += 1
        operand_start = index
    return ranges


def _is_operator(data: bytes, token: StreamToken, name: bytes) -> bool:
    return token.kind is TokenKind.OPERATOR and data[token.start : token.end] == name


def _mark_id(data: bytes, operands: list[StreamToken]) -> str | None:
    """The id of ``/Artifact <<... /PdfEditorWatermark <id> ...>>``, else None."""
    if (
        len(operands) < 4
        or data[operands[0].start : operands[0].end] != _ARTIFACT_TAG
        or operands[1].kind is not TokenKind.DICT_OPEN
        or operands[-1].kind is not TokenKind.DICT_CLOSE
    ):
        return None
    body = operands[2:-1]
    for key, value in zip(body, body[1:]):
        if key.kind is not TokenKind.NAME or data[key.start : key.end] != WATERMARK_MARK_KEY:
            continue
        raw = data[value.start : value.end]
        try:
            if value.kind is TokenKind.HEXSTRING:
                return decode_hex_string(raw).decode("utf-8")
            if value.kind is TokenKind.STRING:
                return decode_literal_string(raw).decode("utf-8")
        except ValueError:  # includes UnicodeDecodeError
            return None
        return None
    return None


def _block_end(data: bytes, tokens: list[StreamToken], start: int) -> int | None:
    """Index of the ``EMC`` closing a block of text-and-state operators only.

    ``q``/``Q`` and ``BT``/``ET`` must balance inside it, so taking it out
    cannot change the graphics or text state the rest of the page runs in.
    """
    q_depth = 0
    in_text = False
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.kind in (TokenKind.MALFORMED, TokenKind.INLINE_IMAGE_DATA):
            return None
        if token.kind is not TokenKind.OPERATOR:
            continue
        name = data[token.start : token.end]
        if name == b"EMC":
            return index if q_depth == 0 and not in_text else None
        if name not in _STRIPPABLE_OPERATORS:
            return None
        if name == b"q":
            q_depth += 1
        elif name == b"Q":
            q_depth -= 1
            if q_depth < 0:
                return None
        elif name == b"BT":
            if in_text:
                return None
            in_text = True
        elif name == b"ET":
            if not in_text:
                return None
            in_text = False
    return None
