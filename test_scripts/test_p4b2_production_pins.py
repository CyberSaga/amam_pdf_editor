"""P4-B2: the two defect families the exact painter geometry had to close.

**These were characterization pins and strict-xfail twins; slice 3b closed
them, so they are now plain passing rejection tests.**  The two
``..._is_a_false_admit_at_the_frozen_tip`` characterizations were DELETED in
the same commit: production no longer admits these shapes, so a test
asserting that it does would be a lie, and the ``strict=True`` xfails that
guarded against a silent recovery have done their job and become the
assertions below.

Every case is a genuine false admit at the frozen P4-B1 tip, proven two
ways at once:

1. the two painters' single-painter rasters overlap (the twin paints on
   top of the target, so a commit leaves a ghost);
2. ``prepare_plan`` used to return a ``PreparedEdit`` anyway.

The cases are the P4-B1 final review's F1≡F3 ``/W`` continuum
(``plans/archive/2026-09-01-p4b1-final-review-verdict.md``: ``/W 0`` and ``/W 1``
same-bytes twins admit at every offset because the exact-extent quad treats
a declared advance as an ink bound) and the rev-2 plan's R5 core-band
counterexample (``_painter_reach`` keeps a 0.6-em band on both sides, so
``second_dy = ±7.3`` at 12 pt is disjoint in bands and overlapping in ink).

Both families now refuse with the slice-3b glyph-ink string: the declared
advance moves the cursor and bounds NOTHING, and the 0.6-em band is gone in
favour of the outline the font actually carries.  The wider composition
lives in ``test_p4b2_admission_gate.py``, which imports :data:`W_CASES`,
:data:`CORE_BAND_CASES` and :func:`_prepare_and_overlap` from here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_plan,
)
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    painters_overlap_pixels,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    FONTSIZE,
    REPLACEMENT,
    SOURCE,
    _build_second_show_doc,
)

# ``/W`` continuum: a declared advance of 0 (F1) and of 1/1000 em (the
# verifier's sweep) on a cloned font dictionary, with the clone's
# CIDToGIDMap either identical (same_font is True, F3 route) or distinct
# (same_font is None, F1 route), at the four offsets the review swept.
W_CASES = [
    pytest.param(width, distinct, offset, id=f"W{width}-{'distinct' if distinct else 'same'}-{offset:+.1f}")
    for width in (0, 1)
    for distinct in (False, True)
    for offset in (-2.0, -1.0, 1.0, 2.0)
]

# Core band: 0.6 em = 7.2 pt at 12 pt; ±7.3 leaves the bands 0.1 pt apart.
CORE_BAND_CASES = [
    pytest.param(dy, id=f"dy{dy:+.1f}") for dy in (-7.3, 7.3)
]


def _w_kwargs(width: int, distinct: bool, offset: float) -> dict:
    return {
        "offset": offset,
        "second_resource": "F_CLONE",
        "second_clone_font": True,
        "second_clone_width": width,
        "second_clone_distinct_cidtogid": distinct,
    }


def _core_band_kwargs(dy: float) -> dict:
    return {"offset": 1.0, "second_dy": dy}


def _prepare_and_overlap(**kwargs) -> tuple[PreparedEdit | PlanRejection, int]:
    """Production verdict and single-painter raster overlap for one page."""
    fixture, expected_origin = _build_second_show_doc(**kwargs)
    try:
        overlap = painters_overlap_pixels(fixture)
        result = prepare_plan(
            fixture.doc,
            fixture.page,
            target_text=SOURCE,
            replacement_text=REPLACEMENT,
            expected_origin=expected_origin,
            target_bbox=None,
            registry=DocumentFontRegistry(fixture.doc),
            max_tier=1,
        )
    finally:
        fixture.doc.close()
    return result, overlap


# --------------------------------------------------------------------------
# The rejections slice 3b's exact painter geometry produces.  Each asserts
# the raster ground truth FIRST, so a fixture that stopped overlapping
# cannot let the verdict assertion pass for the wrong reason.

# The detail the glyph-ink arm emits; measurements only, never document text.
GLYPH_INK = "identical source painter's glyph ink overlaps the target ink by"


@pytest.mark.parametrize(("width", "distinct", "offset"), W_CASES)
def test_w_continuum_twin_is_rejected(
    width: int, distinct: bool, offset: float
) -> None:
    """F1≡F3: a declared advance is not an ink bound (verdict doc, 'F1 and
    F3 are one defect').  ``/W 0`` gave a zero-width exact quad and ``/W 1``
    a 0.024 pt one, and both read as disjoint under ``overlap_x > 0.05``;
    the glyphs they paint are 12 pt wide whatever the table says."""
    result, overlap = _prepare_and_overlap(**_w_kwargs(width, distinct, offset))
    assert overlap > 0, "the twin must paint on the target for this to be a pin"
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert GLYPH_INK in result.detail


@pytest.mark.parametrize("dy", CORE_BAND_CASES)
def test_core_band_twin_is_rejected(dy: float) -> None:
    """R5: the reach fallback and the exact quad both kept a 0.6-em core
    band in y (``_painter_core_quad``), so a twin one band-height away read
    as 'disjoint' while its ascenders and descenders overlapped the
    target's ink.  The outline box is 0.91 em tall here, so it does not."""
    result, overlap = _prepare_and_overlap(**_core_band_kwargs(dy))
    assert overlap > 0, "the twin must paint on the target for this to be a pin"
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert GLYPH_INK in result.detail


# --------------------------------------------------------------------------
# Positive control: the raster oracle itself distinguishes a genuinely
# disjoint twin from an overlapping one, so ``overlap > 0`` above is not a
# rendering artefact.


def test_raster_oracle_control_disjoint_twin_has_no_overlap() -> None:
    fixture, _ = _build_second_show_doc(offset=len(SOURCE) * FONTSIZE + 4.0)
    try:
        assert painters_overlap_pixels(fixture) == 0
    finally:
        fixture.doc.close()


def test_raster_oracle_control_coincident_twin_overlaps_fully() -> None:
    fixture, _ = _build_second_show_doc(offset=0.0)
    try:
        from test_scripts.painter_matrix_fixtures import single_painter_masks

        first, second = single_painter_masks(fixture)
        assert first.ink_pixels > 0
        assert first.overlap_pixels(second) == first.ink_pixels
    finally:
        fixture.doc.close()
