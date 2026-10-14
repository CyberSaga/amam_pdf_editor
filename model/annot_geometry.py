"""Annotation ``/Rect`` geometry through the page frame (F15-G2-ANNOT, F15-G1-UU-ANNOT).

Three PyMuPDF behaviours are NOT interchangeable on a ``/Rotate``d page
(MEASURED, 1.27.1, MediaBox [0 0 300 400] + ``/UserUnit 2``):

* ``page.add_*_annot(rect)`` reads ``rect`` in TRUE unrotated page space, the
  ``/UserUnit``-scaled space of ``model.geometry`` (``visual_to_unrotated_*``).
  ``page.derotation_matrix`` drops ``/UserUnit``, so a rect mapped with it inks
  at (428, 48, 492, 82) instead of (28, 48, 92, 82).
* ``Annot.rect`` / ``Annot.set_rect`` map ``/Rect`` through that same
  ``/UserUnit``-less derotation, so they neither read back what ``add_*_annot``
  wrote nor place ink where the rect says (``set_rect`` of a true rect drew
  nothing at all).
* The raw ``/Rect`` array is exact: PDF user space, y up.

So every annotation consumer reads the raw ``/Rect`` through the frame
(``annot_page_rect``) and writes it back raw (``set_annot_page_rect``) wherever
the frame can be proven; ``Annot.rect`` / ``set_rect`` stay the fallbacks for a
page whose frame cannot be proven (a non-quarter ``/Rotate``, an empty clipped
CropBox, an unusable ``/UserUnit``) and for an unrotated page, where they are
exact.
"""

from __future__ import annotations

import logging
import math

import fitz

from model.pdf_content_ops import AffineMatrix, affine_invert, affine_point, page_user_space_matrix

logger = logging.getLogger(__name__)


def user_to_page_matrix(page: fitz.Page) -> AffineMatrix:
    """PDF user space -> TRUE unrotated page space, for raw annotation geometry.

    ``page_user_space_matrix`` is the model's one chokepoint for it
    (``PageVisualFrame.base``: the ``/UserUnit`` scale, the y flip and the
    clipped CropBox origin).  ``page.transformation_matrix`` is no
    substitute: once ``/Rotate != 0`` it drops the CropBox/MediaBox origin
    and ``/UserUnit``.  Only when the frame cannot be proven is MuPDF's own
    matrix used.
    """
    matrix = page_user_space_matrix(page)
    if matrix is not None:
        return matrix
    logger.warning("annotation geometry: page frame cannot be proven, using page.transformation_matrix")
    tm = page.transformation_matrix
    return (float(tm.a), float(tm.b), float(tm.c), float(tm.d), float(tm.e), float(tm.f))


def pdf_number(value: float) -> str:
    """A PDF number literal for ``value`` (5 decimals, no exponent, no ``-0``)."""
    text = f"{value:.5f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def read_raw_rect(doc: fitz.Document, xref: int) -> list[float] | None:
    """The ``/Rect`` array of *xref* as four finite floats, or None when absent/invalid."""
    kind, value = doc.xref_get_key(xref, "Rect")
    if kind != "array":
        return None
    try:
        numbers = [float(v) for v in value.strip()[1:-1].split()]
    except ValueError:
        return None
    if len(numbers) != 4 or not all(math.isfinite(v) for v in numbers):
        return None
    return numbers


def raw_rect_to_page(page: fitz.Page, numbers: list[float], matrix: AffineMatrix | None = None) -> fitz.Rect:
    """A raw ``/Rect`` (``[x0 y0 x1 y1]`` in user space) as a page-space rect.

    A caller mapping many annotations passes the page's ``matrix`` (from
    ``user_to_page_matrix``) once instead of re-deriving the frame each time.
    """
    if matrix is None:
        matrix = user_to_page_matrix(page)
    x0, y0, x1, y1 = numbers
    corners = [affine_point(matrix, x, y) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))


def annot_page_rect(page: fitz.Page, annot: fitz.Annot, matrix: AffineMatrix | None = None) -> fitz.Rect:
    """``annot``'s rect in TRUE unrotated page space.

    The raw ``/Rect`` goes through the page frame; ``Annot.rect`` is the
    fallback for a missing or unreadable ``/Rect``.
    """
    try:
        numbers = read_raw_rect(page.parent, annot.xref)
    except Exception as exc:
        logger.warning("annot_page_rect: xref %s /Rect unreadable: %s", annot.xref, exc)
        numbers = None
    if numbers is None:
        return fitz.Rect(annot.rect)
    return raw_rect_to_page(page, numbers, matrix)


def set_annot_page_rect(page: fitz.Page, annot: fitz.Annot, rect: fitz.Rect) -> None:
    """Make ``annot``'s ``/Rect`` the TRUE unrotated page-space ``rect``.

    ``Annot.set_rect`` is used on an unrotated page (exact there) and when the
    frame cannot be proven.  On a ``/Rotate``d page the rect is mapped back to
    user space through the frame and written raw: ``set_rect`` goes through the
    ``/UserUnit``-less derotation (see the module doc).  The caller's
    ``update()`` regenerates the appearance, as after ``set_rect``.
    """
    matrix = page_user_space_matrix(page) if int(page.rotation) % 360 != 0 else None
    if matrix is None:
        annot.set_rect(rect)
        return
    to_user = affine_invert(matrix)
    r = fitz.Rect(rect)
    corners = [affine_point(to_user, x, y) for x, y in ((r.x0, r.y0), (r.x1, r.y0), (r.x0, r.y1), (r.x1, r.y1))]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    numbers = " ".join(pdf_number(v) for v in (min(xs), min(ys), max(xs), max(ys)))
    page.parent.xref_set_key(annot.xref, "Rect", f"[{numbers}]")
