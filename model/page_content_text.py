"""Page text extraction that ignores annotation and widget appearances.

``page.get_text`` runs the whole page, so it also extracts the text drawn by
annotation appearance streams (a FreeText body, a form field's value).  That
text is not part of the page's content stream: the text-edit pipeline must not
index it as an editable block, replay it as a "protected span", or push it down
(F11-ANN-4) -- each of those turns it into real page content that then shows
twice and outlives the annotation.  Annotations are edited through the
annotation tools, never through the page-text index.

Every extraction that feeds the block index, a target lookup, a protected-span
replay or a push-down goes through :func:`content_text` instead.  Selection
copy is content-only as well: the rectangle reader
(``PDFModel.get_text_selection_snapshot``) reads the index and
:func:`content_text`, and only on a page without runs falls back to
``page.get_text("text", clip=)``, which runs the whole page and carries no
boxes; the drag reader (``get_text_selection_snapshot_from_run``) reads the
index alone and returns nothing on such a page.  Extractions that deliberately
describe what is VISIBLE read the whole page: ``text_commit.verify`` through
:func:`visible_text`, and the search tool through :func:`visible_search` for
its hits and ``page.get_text("text", clip=)`` for each hit's context snippet.

Upside-down glyph boxes (GATE16-1): text that reads upright on a ``/Rotate 180``
page is drawn upside down in unrotated space, so its stext line direction is
exactly (-1, 0).  PyMuPDF 1.27's ``JM_char_quad`` handles that direction as a
LEFT-RIGHT MIRROR whenever it re-computes a char quad (always under
``TOOLS.set_small_glyph_heights(True)``, the app's production flag): the
ascender lands on the wrong side of the baseline, so every dict/rawdict/words
box and every ``search_for`` rect sits about 0.64 em off the ink.  The helpers
here reflect exactly those boxes back about their baseline
(:func:`upright_glyph_boxes`); a true mirror (``-1 0 0 1``, upright glyphs) is
left alone.  The option ``"blocks"`` and ``clip=`` text selection are not
corrected (block tuples carry no line identity; clip membership is a plain
overlap test that the mirrored box still meets).

The text page is built exactly like ``Page.get_textpage`` but runs the page
with ``fz_run_page_contents`` (no annotations, no widgets), so its output is
identical to ``page.get_text`` on a page without annotations (rotation, CropBox
and clip included; pinned by ``test_page_content_text``, including a real
multi-page document).
"""
from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import fitz

_DEFAULT_FLAGS: dict[str, int] = {
    "text": fitz.TEXTFLAGS_TEXT,
    "dict": fitz.TEXTFLAGS_DICT,
    "rawdict": fitz.TEXTFLAGS_RAWDICT,
    "words": fitz.TEXTFLAGS_WORDS,
    "blocks": fitz.TEXTFLAGS_BLOCKS,
}


def content_textpage(
    page: fitz.Page,
    flags: int,
    clip: fitz.Rect | tuple[float, float, float, float] | None = None,
) -> fitz.TextPage:
    """A ``TextPage`` of ``page`` content, usable as ``get_text(textpage=)``.

    The same construction as ``Page.get_textpage`` (unrotated space, the
    page's own bound or ``clip`` as the text-page rectangle) except that the
    page is run with ``fz_run_page_contents``, which skips annotations and
    widgets.  A display list is NOT used: replaying one regroups text objects
    and changes line/space segmentation on real documents (probe: three pages
    of ``hvac-dwg.pdf`` extract differently), so index geometry would drift.
    """
    old_rotation = page.rotation
    if old_rotation != 0:
        page.set_rotation(0)
    try:
        fz_page = page.this
        if isinstance(fz_page, fitz.mupdf.PdfPage):
            fz_page = fz_page.super()
        rect = fitz.mupdf.fz_bound_page(fz_page) if clip is None else fitz.JM_rect_from_py(clip)
        raw_page = fitz.mupdf.FzStextPage(rect)
        device = fitz.mupdf.fz_new_stext_device(raw_page, fitz.mupdf.FzStextOptions(flags))
        try:
            fitz.mupdf.fz_run_page_contents(
                fz_page, device, fitz.JM_matrix_from_py(fitz.Matrix(1, 1)), fitz.mupdf.FzCookie()
            )
        finally:
            fitz.mupdf.fz_close_device(device)
    finally:
        if old_rotation != 0:
            page.set_rotation(old_rotation)
    textpage = fitz.TextPage(raw_page)
    textpage.parent = weakref.proxy(page)
    return textpage


def content_text(
    page: fitz.Page,
    option: str = "text",
    *,
    flags: int | None = None,
    clip: fitz.Rect | tuple[float, float, float, float] | None = None,
    textpage: fitz.TextPage | None = None,
) -> Any:
    """``page.get_text(option, ...)`` over the page content only.

    ``flags`` defaults like ``get_text``.  ``clip`` (unrotated space, like
    ``get_text(clip=)``) is supported for ``option="text"`` only.  Pass a
    ``textpage`` from :func:`content_textpage` to extract several options from
    one interpretation (the flags must then be the ones it was built with).
    """
    option = option.lower()
    if option not in _DEFAULT_FLAGS:
        raise ValueError(f"unsupported content text option: {option!r}")
    if clip is not None:
        if option != "text" or textpage is not None or flags not in (None, fitz.TEXTFLAGS_TEXT):
            raise ValueError("clip is supported for plain default-flag 'text' only")
        return page.get_text("text", textpage=content_textpage(page, fitz.TEXTFLAGS_TEXT, clip))
    if textpage is None:
        textpage = content_textpage(page, _DEFAULT_FLAGS[option] if flags is None else flags)
    return upright_glyph_boxes(option, page.get_text(option, textpage=textpage), textpage)


def visible_text(page: fitz.Page, option: str) -> Any:
    """``page.get_text(option)`` (annotations included) with upright glyph boxes.

    For the extractions that describe what is VISIBLE (the text-commit
    verifier).  Same text page as ``page.get_text`` builds itself (default
    flags, no clip, CropBox-bounded extraction).
    """
    option = option.lower()
    if option not in _DEFAULT_FLAGS:
        raise ValueError(f"unsupported visible text option: {option!r}")
    textpage = page.get_textpage(flags=_DEFAULT_FLAGS[option])
    return upright_glyph_boxes(option, page.get_text(option, textpage=textpage), textpage)


_SEARCH_FLAGS = (
    fitz.TEXT_DEHYPHENATE
    | fitz.TEXT_PRESERVE_WHITESPACE
    | fitz.TEXT_PRESERVE_LIGATURES
    | fitz.TEXT_MEDIABOX_CLIP
)


def visible_search(page: fitz.Page, needle: str) -> list[fitz.Rect]:
    """``page.search_for(needle)`` with hit rects on the ink of upside-down text."""
    textpage = page.get_textpage(flags=_SEARCH_FLAGS)
    hits = [fitz.Rect(hit) for hit in page.search_for(needle, textpage=textpage)]
    if not hits:
        return hits
    flipped = _flipped_glyphs(textpage)
    if not flipped.rects:
        return hits
    return [_upright_search_rect(hit, flipped) for hit in hits]


# --- upside-down glyph boxes (GATE16-1) ---------------------------------------

_ORIGIN_DIGITS = 3
_SAME_EDGE = 0.01


@dataclass(frozen=True)
class _FlippedGlyphs:
    """The chars whose PyMuPDF box was mirrored about their baseline."""

    by_origin: dict[tuple[float, float], float]  # char origin -> baseline y
    by_line: dict[tuple[int, int], float]  # (block_no, line_no) -> baseline y
    rects: tuple[tuple[float, float, float, float, float], ...]  # mirrored box + baseline


_NO_FLIPS = _FlippedGlyphs({}, {}, ())
_CACHE_ATTR = "_pdf_editor_flipped_glyphs"


def _origin_key(x: float, y: float) -> tuple[float, float]:
    return (round(float(x), _ORIGIN_DIGITS), round(float(y), _ORIGIN_DIGITS))


def _upside_down(quad: Any) -> bool:
    """Top edge below the bottom edge in fitz (y-down) space."""
    return float(quad.ul.y) + float(quad.ur.y) > float(quad.ll.y) + float(quad.lr.y) + 1e-6


def _flipped_glyphs(textpage: fitz.TextPage) -> _FlippedGlyphs:
    """Walk ``textpage`` for chars PyMuPDF boxes on the wrong side of the baseline.

    A char qualifies when its line direction is exactly (-1, 0) (PyMuPDF's
    mirror branch), MuPDF's own quad is upside down (a 180-degree glyph), and
    the quad PyMuPDF reports is not -- the reported box is then the reflection
    of the right one about the char's baseline.  When PyMuPDF keeps MuPDF's
    quad (flag off and a font with sane metrics) nothing qualifies.
    """
    small = bool(fitz.TOOLS.set_small_glyph_heights())
    cached = getattr(textpage, _CACHE_ATTR, None)
    if cached is not None and cached[0] == small:
        return cached[1]
    by_origin: dict[tuple[float, float], float] = {}
    by_line: dict[tuple[int, int], float] = {}
    rects: list[tuple[float, float, float, float, float]] = []
    for block_no, block in enumerate(textpage.this):
        if block.m_internal.type != fitz.mupdf.FZ_STEXT_BLOCK_TEXT:
            continue
        for line_no, line in enumerate(block):
            raw_line = line.m_internal
            if raw_line.wmode or raw_line.dir.x != -1:
                continue
            for char in line:
                raw = char.m_internal
                if not _upside_down(raw.quad):
                    continue
                # The quad PyMuPDF reports for the char (its own re-computation).
                shown = fitz.JM_char_quad(line, char)
                if _upside_down(shown):
                    continue
                baseline = float(raw.origin.y)
                by_origin[_origin_key(raw.origin.x, raw.origin.y)] = baseline
                by_line.setdefault((block_no, line_no), baseline)
                box = fitz.mupdf.fz_rect_from_quad(shown)
                rects.append((float(box.x0), float(box.y0), float(box.x1), float(box.y1), baseline))
    flipped = _FlippedGlyphs(by_origin, by_line, tuple(rects)) if by_origin else _NO_FLIPS
    setattr(textpage, _CACHE_ATTR, (small, flipped))
    return flipped


def _reflect(bbox: Sequence[float], baseline: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = (float(v) for v in tuple(bbox)[:4])
    return (x0, 2.0 * baseline - y1, x1, 2.0 * baseline - y0)


def _union(boxes: list[Sequence[float]]) -> tuple[float, float, float, float] | None:
    valid = [
        box
        for box in boxes
        if float(box[2]) >= float(box[0]) and float(box[3]) >= float(box[1])
    ]
    if not valid:
        return None
    return (
        min(float(box[0]) for box in valid),
        min(float(box[1]) for box in valid),
        max(float(box[2]) for box in valid),
        max(float(box[3]) for box in valid),
    )


def _is_mirror_line(line: dict[str, Any]) -> bool:
    """Is the dict line's direction exactly (-1, 0), the GATE16-1 trigger?"""
    direction = line.get("dir")
    return bool(direction and float(direction[0]) == -1.0)


def _has_mirror_direction_line(result: dict[str, Any]) -> bool:
    return any(
        _is_mirror_line(line)
        for block in result.get("blocks", [])
        for line in block.get("lines", ()) or ()
    )


def _upright_dict(result: dict[str, Any], flipped: _FlippedGlyphs) -> None:
    for block in result.get("blocks", []):
        block_changed = False
        for line in block.get("lines", ()) or ():
            if not _is_mirror_line(line):
                continue
            line_changed = False
            for span in line.get("spans", ()):
                for char in span.get("chars", ()) or ():
                    baseline = flipped.by_origin.get(_origin_key(*char["origin"]))
                    if baseline is not None:
                        char["bbox"] = _reflect(char["bbox"], baseline)
                baseline = flipped.by_origin.get(_origin_key(*span["origin"]))
                if baseline is not None:
                    span["bbox"] = _reflect(span["bbox"], baseline)
                    line_changed = True
            if line_changed:
                union = _union([span["bbox"] for span in line.get("spans", ())])
                if union is not None:
                    line["bbox"] = union
                    block_changed = True
        if block_changed:
            union = _union([line["bbox"] for line in block.get("lines", ())])
            if union is not None:
                block["bbox"] = union


def _upright_words(words: list[Any], flipped: _FlippedGlyphs) -> list[Any]:
    out: list[Any] = []
    for word in words:
        baseline = flipped.by_line.get((int(word[5]), int(word[6])))
        out.append(word if baseline is None else (*_reflect(word, baseline), *word[4:]))
    return out


def _upright_search_rect(hit: fitz.Rect, flipped: _FlippedGlyphs) -> fitz.Rect:
    for x0, y0, x1, y1, baseline in flipped.rects:
        if (
            abs(hit.y0 - y0) <= _SAME_EDGE
            and abs(hit.y1 - y1) <= _SAME_EDGE
            and hit.x0 < x1
            and x0 < hit.x1
        ):
            return fitz.Rect(_reflect(hit, baseline))
    return hit


def upright_glyph_boxes(
    option: str,
    result: Any,
    textpage: fitz.TextPage | Callable[[], fitz.TextPage],
) -> Any:
    """Reflect PyMuPDF's mirrored boxes of upside-down chars back onto the ink.

    ``result`` is ``get_text(option, textpage=textpage)`` output for
    ``"dict"``, ``"rawdict"`` (corrected in place) or ``"words"`` (a new
    list); other options pass through.  ``textpage`` (or a factory for it)
    must be the text page ``result`` came from.  Dict output without a (-1, 0)
    line returns before the text page is walked.
    """
    option = option.lower()
    if option in ("dict", "rawdict"):
        if not isinstance(result, dict) or not _has_mirror_direction_line(result):
            return result
    elif option != "words" or not result:
        return result
    page_text = textpage() if callable(textpage) else textpage
    flipped = _flipped_glyphs(page_text)
    if not flipped.by_origin:
        return result
    if option == "words":
        return _upright_words(list(result), flipped)
    _upright_dict(result, flipped)
    return result
