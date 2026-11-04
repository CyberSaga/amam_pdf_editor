"""Pure helpers for browse-mode text selection (copy keeps the page's own text).

F16-COPY-2.  The text index splits a line into word runs and owns no space
glyph: the gap between two words (a plain space, a no-break space, a TJ kerning
gap that MuPDF reports as a space) lies outside every run's bbox.  Copying only
the glyphs the runs own therefore dropped every inter-word space, and clipping
the boundary runs "from the pointer onward" assumed every run reads towards
larger coordinates, which is false for right-to-left text and for the
bottom-to-top quarter turn.

F17-COPY-180.  The same model missed the half turn (upright text on a /Rotate
180 page is written towards -x, so every word copied reversed) and right-to-left
text on a quarter turn (its glyphs were put in position order, not logical
order).  The model is now one rule in two places: :func:`reading_sign` says which
way a run reads along its axis in index space (rotation and script), and
:func:`order_run_glyphs` lists a run's glyphs in the order of its ``text`` (the
reading order, logical for right-to-left letters).  Qt-free; no PyMuPDF document
access.
"""

from __future__ import annotations

import fitz

from model.rtl_text import contains_rtl

#: Same reading-axis tolerance ``PDFModel._get_chars_in_run_unrotated`` uses to
#: decide that a glyph belongs to a run; a gap glyph inside it is already part
#: of the run's own glyphs and must not be copied twice.
_RUN_EDGE_TOLERANCE = 0.5


def _rotation(run) -> int:
    return int(getattr(run, "rotation", 0)) % 360


def _axis_sign(rotation: int) -> int:
    """+1 when Latin-like text at ``rotation`` reads towards larger coordinates
    along its axis (0: +x, 90: +y), -1 towards smaller ones (180: -x, 270: -y).
    The one rotation -> direction table of this module."""
    return -1 if rotation % 360 in (180, 270) else 1


def _is_vertical(run) -> bool:
    """Does ``run`` read along y (a quarter turn) rather than along x?"""
    return _rotation(run) in (90, 270)


def _centre(rect: fitz.Rect, vertical: bool) -> float:
    """Midpoint of ``rect`` along y when ``vertical``, else along x."""
    return (rect.y0 + rect.y1) / 2.0 if vertical else (rect.x0 + rect.x1) / 2.0


def reading_sign(run) -> int:
    """+1 when ``run`` reads towards larger coordinates along its reading axis
    in INDEX (unrotated) space, -1 when it reads towards smaller ones.

    Latin-like text reads towards +x at rotation 0, towards +y (top to bottom) at
    90, towards -x at 180 (upright text on a /Rotate 180 page) and towards -y
    (bottom to top) at 270.  A run holding right-to-left letters reads the
    opposite way along the same axis."""
    sign = _axis_sign(_rotation(run))
    return -sign if contains_rtl(getattr(run, "text", "")) else sign


def order_run_glyphs(
    glyphs: list[tuple[str, fitz.Rect]], rotation: int
) -> list[tuple[str, fitz.Rect]]:
    """The ``(glyph, index-space box)`` pairs of ONE run in the order of the
    run's ``text``, so a glyph list and ``run.text`` line up index by index.

    Right-to-left letters keep MuPDF's traversal order, which is LOGICAL at
    every rotation (F15-RTL-ORDER).  Anything else is put in reading order
    along the run's axis -- the direction :func:`reading_sign` names: ascending
    x at 0, ascending y at 90, descending x at 180, descending y at 270.  A
    horizontal run is ordered by line first (so a span wrapped onto two rows
    stays in order), and the rows of a half turn stack upwards."""
    if any(contains_rtl(glyph) for glyph, _box in glyphs):
        return list(glyphs)
    rotation %= 360
    reverse = _axis_sign(rotation) < 0
    if rotation in (90, 270):
        return sorted(glyphs, key=lambda item: item[1].y0, reverse=reverse)
    return sorted(glyphs, key=lambda item: (round(item[1].y0), item[1].x0), reverse=reverse)


def _direction_towards(source, target) -> int:
    """+1 / -1: the way along the reading axis from ``source`` to ``target``
    (their physical order on the page), ``source``'s reading sign when they
    share a centre."""
    vertical = _is_vertical(source)
    delta = _centre(fitz.Rect(target.bbox), vertical) - _centre(fitz.Rect(source.bbox), vertical)
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return reading_sign(source)


def clip_directions(slice_runs: list) -> tuple[int, int]:
    """Directions for clipping the first and the last run of one line's slice
    of the selection: ``(first, last)``, each +1 or -1 along the reading axis
    (towards larger / smaller page coordinates).

    The first run keeps the glyphs from its pointer ONWARD, the last run the
    glyphs from its pointer BACKWARD, where "onward" is the way the selection
    continues: towards the next selected run on the line, or, when the run is
    alone on its slice, along its own reading direction (to the next line).  A
    right-to-left run, or the bottom-to-top quarter turn, therefore clips the
    mirrored way, and a mixed-direction line follows the physical order of its
    runs so the highlighted glyphs and the copied glyphs stay the same set."""
    if len(slice_runs) >= 2:
        return (
            _direction_towards(slice_runs[0], slice_runs[1]),
            _direction_towards(slice_runs[-2], slice_runs[-1]),
        )
    sign = reading_sign(slice_runs[0])
    return sign, sign


def whitespace_chars(rawdict: dict | None) -> list[tuple[str, fitz.Rect]]:
    """Every whitespace glyph of a ``rawdict`` extraction as ``(glyph, bbox)``,
    in MuPDF's traversal order (the page text's own order)."""
    found: list[tuple[str, fitz.Rect]] = []
    if not rawdict:
        return found
    for block in rawdict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    glyph = ch.get("c", "")
                    if glyph and glyph.isspace():
                        found.append((glyph, fitz.Rect(ch.get("bbox"))))
    return found


def whitespace_between_runs(gap_chars: list[tuple[str, fitz.Rect]], left, right) -> list[str]:
    """The whitespace glyphs the page holds between two consecutive runs of one
    visual line (``left`` is read before ``right``; either may be to the other's
    left on screen for right-to-left text).  Returns ``[]`` when the runs touch,
    overlap or the page has no whitespace glyph in the gap."""
    rect_a, rect_b = fitz.Rect(left.bbox), fitz.Rect(right.bbox)
    vertical = _is_vertical(left)
    if vertical:
        a0, a1, b0, b1 = rect_a.y0, rect_a.y1, rect_b.y0, rect_b.y1
        cross_lo, cross_hi = min(rect_a.x0, rect_b.x0), max(rect_a.x1, rect_b.x1)
    else:
        a0, a1, b0, b1 = rect_a.x0, rect_a.x1, rect_b.x0, rect_b.x1
        cross_lo, cross_hi = min(rect_a.y0, rect_b.y0), max(rect_a.y1, rect_b.y1)
    if a1 <= b0:
        gap_lo, gap_hi = a1, b0
    elif b1 <= a0:
        gap_lo, gap_hi = b1, a0
    else:
        return []
    gap_lo += _RUN_EDGE_TOLERANCE
    gap_hi -= _RUN_EDGE_TOLERANCE
    between: list[str] = []
    for glyph, box in gap_chars:
        axis = _centre(box, vertical)
        cross = _centre(box, not vertical)
        if gap_lo < axis < gap_hi and cross_lo <= cross <= cross_hi:
            between.append(glyph)
    return between
