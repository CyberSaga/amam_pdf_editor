"""T16-4 Steps 3-4: the stroke-outset geometry helpers, red-first.

Two pure helpers feed the Phase A/B stroke ladder (``plans/
task16-4-tandem-bold-commit.md`` D4/D5): ``transforms.sigma_max`` (the exact
largest singular value of a 2x2 linear map) and ``plan._stroke_outset_visual``
(the stroke pen's outset in VISUAL points, at either the HONEST or the
CONSERVATIVE bound). Neither is wired into any gate yet -- this module pins
only the helpers themselves, against the plan's E5/E6/E7 evidence.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.plan import StrokePen, _stroke_outset_visual  # noqa: E402
from model.text_commit.replay import ShowOp  # noqa: E402
from model.text_commit.transforms import page_visual_frame, sigma_max  # noqa: E402

_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _page(*, user_unit: float | None = None, rotate: int | None = None) -> fitz.Document:
    """One synthetic page, no content stream needed -- ``page_visual_frame``
    reads only the page geometry dict."""
    doc = fitz.open()
    doc.new_page(width=200.0, height=300.0)
    page = doc[0]
    if user_unit is not None:
        doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
    if rotate is not None:
        page.set_rotation(rotate)
    return doc


def _show(
    *,
    ctm: tuple[float, float, float, float, float, float] = _IDENTITY,
    tm: tuple[float, float, float, float, float, float] = _IDENTITY,
    hscale: float = 100.0,
) -> ShowOp:
    """A minimal hand-built ``ShowOp``. Only ``ctm``/``tm``/``hscale`` vary
    across these tests -- every other field is placeholder evidence
    ``_stroke_outset_visual`` never reads."""
    return ShowOp(
        seq=0,
        operator="Tj",
        stream_xref=1,
        op_start=0,
        op_end=0,
        string_start=0,
        string_end=0,
        string_kind="literal",
        array_item_count=1,
        decoded_bytes=b"",
        font_resource="/F1",
        font_size=12.0,
        tm=tm,
        ctm=ctm,
        trm_uniform_scale=1.0,
        origin_user=(0.0, 0.0),
        origin_reliable=True,
        char_spacing=0.0,
        word_spacing=0.0,
        hscale=hscale,
        leading=0.0,
        rise=0.0,
        render_mode=2,
        in_bt=True,
        gs_depth=0,
        mc_depth=0,
    )


# ---------------------------------------------------------------- E5 (ctm)


def test_stroke_outset_scales_with_the_ctm_and_not_with_the_text_matrix():
    doc = _page()
    try:
        frame = page_visual_frame(doc[0])
        pen = StrokePen(width=3.0, line_join=1, miter_limit=10.0)  # round join

        baseline = _stroke_outset_visual(
            _show(ctm=_IDENTITY, tm=_IDENTITY),
            frame=frame,
            pen=pen,
            conservative=False,
        )
        assert baseline is not None

        # cm 2 0 0 2 doubles it.
        doubled_ctm = _stroke_outset_visual(
            _show(ctm=(2.0, 0.0, 0.0, 2.0, 0.0, 0.0), tm=_IDENTITY),
            frame=frame,
            pen=pen,
            conservative=False,
        )
        assert doubled_ctm == pytest.approx(2.0 * baseline)

        # Tm 2 0 0 2 does not move it: the CTM is identity again.
        doubled_tm = _stroke_outset_visual(
            _show(ctm=_IDENTITY, tm=(2.0, 0.0, 0.0, 2.0, 0.0, 0.0)),
            frame=frame,
            pen=pen,
            conservative=False,
        )
        assert doubled_tm == pytest.approx(baseline)

        # Tz 200 (hscale) does not move it either.
        tz_200 = _stroke_outset_visual(
            _show(ctm=_IDENTITY, tm=_IDENTITY, hscale=200.0),
            frame=frame,
            pen=pen,
            conservative=False,
        )
        assert tz_200 == pytest.approx(baseline)
    finally:
        doc.close()


# ------------------------------------------------------ E5 (UserUnit/Rotate)


def test_stroke_outset_carries_user_unit_and_rotate():
    plain = _page()
    doubled = _page(user_unit=2.0)
    rotated = _page(rotate=90)
    try:
        pen = StrokePen(width=3.0, line_join=1, miter_limit=10.0)
        show = _show()

        plain_frame = page_visual_frame(plain[0])
        doubled_frame = page_visual_frame(doubled[0])
        rotated_frame = page_visual_frame(rotated[0])

        baseline = _stroke_outset_visual(
            show, frame=plain_frame, pen=pen, conservative=False
        )
        via_user_unit = _stroke_outset_visual(
            show, frame=doubled_frame, pen=pen, conservative=False
        )
        via_rotate = _stroke_outset_visual(
            show, frame=rotated_frame, pen=pen, conservative=False
        )

        assert baseline is not None
        # /UserUnit 2 doubles it, the same way a 2 0 0 2 cm does.
        assert via_user_unit == pytest.approx(2.0 * baseline)
        # /Rotate 90 (an exact quarter turn) leaves it unchanged.
        assert via_rotate == pytest.approx(baseline)
    finally:
        plain.close()
        doubled.close()
        rotated.close()


# --------------------------------------------------- sigma_max vs max|elem|


def test_sigma_max_exceeds_mupdf_max_elem_under_rotation_and_shear():
    """Pins the deliberate divergence from
    ``scripts/painter_geometry.stroke_expansion``'s ``max(|a|,|b|,|c|,|d|)``
    (MuPDF's ``fz_matrix_max_expansion``), which ``docs/PITFALLS.md`` (around
    line 2917) records as UNDER-bounding the true stretch. T16-4 D5: this is
    reconciled by TEST, not by import -- ``stroke_expansion`` itself stays on
    the MuPDF-measured formula unchanged (see
    ``test_p4b2_oracles.py::test_bboxlog_stroke_text_rect_is_o1_union_plus_stroke_expansion``),
    and nobody should "fix" one formula toward the other.
    """
    # 45-degree rotation: every element 0.70711..., sigma_max is exactly 1.0
    # (the pen is stretched by 1.0, not shrunk by max|elem|).
    root_half = math.sqrt(2.0) / 2.0
    rotation = (root_half, root_half, -root_half, root_half)
    max_elem_rotation = max(abs(v) for v in rotation)
    assert sigma_max(rotation) == pytest.approx(1.0)
    assert max_elem_rotation < sigma_max(rotation)
    assert max_elem_rotation == pytest.approx(root_half)

    # Shear (1, 1, 0, 1): sigma_max is the golden ratio, 1.618...
    shear = (1.0, 1.0, 0.0, 1.0)
    max_elem_shear = max(abs(v) for v in shear)
    golden_ratio = (1.0 + math.sqrt(5.0)) / 2.0
    assert sigma_max(shear) == pytest.approx(golden_ratio)
    assert sigma_max(shear) > max_elem_shear
    assert max_elem_shear == pytest.approx(1.0)


# --------------------------------------------------------- E6 (miter factor)


def test_conservative_bound_carries_the_miter_factor_only_for_miter_joins():
    doc = _page()
    try:
        frame = page_visual_frame(doc[0])
        show = _show()
        half_pen_scaled = 2.0 * sigma_max((1.0, 0.0, 0.0, -1.0))  # width 4 / 2

        miter = _stroke_outset_visual(
            show,
            frame=frame,
            pen=StrokePen(width=4.0, line_join=0, miter_limit=5.0),
            conservative=True,
        )
        round_join = _stroke_outset_visual(
            show,
            frame=frame,
            pen=StrokePen(width=4.0, line_join=1, miter_limit=5.0),
            conservative=True,
        )
        bevel_join = _stroke_outset_visual(
            show,
            frame=frame,
            pen=StrokePen(width=4.0, line_join=2, miter_limit=5.0),
            conservative=True,
        )

        assert miter == pytest.approx(5.0 * half_pen_scaled)
        assert round_join == pytest.approx(1.0 * half_pen_scaled)
        assert bevel_join == pytest.approx(1.0 * half_pen_scaled)

        # The honest bound (conservative=False) never carries the miter
        # factor, even for a miter join.
        honest_miter = _stroke_outset_visual(
            show,
            frame=frame,
            pen=StrokePen(width=4.0, line_join=0, miter_limit=5.0),
            conservative=False,
        )
        assert honest_miter == pytest.approx(1.0 * half_pen_scaled)

        # RE-PINNED (T16-4 S1 review H2).  The old pin here asserted
        # ``0.5 * half_pen_scaled`` for ``M = 0``, i.e. a floor of
        # ``max(miter_limit, 0.5)``.  That is BELOW the geometric minimum: a
        # stroke always reaches ``w/2`` per side whatever the join does, so a
        # factor under 1.0 under-states the ink itself (measured: ``1 w 0 M``
        # gave an outset of 0.25 pt against a rendered expansion of 0.5 pt).
        # The floor is now 1.0.  A spec-illegal ``M < 1`` (ISO 32000-1 8.5.2
        # requires ``M >= 1``) never reaches the ceiling test either --
        # ``_prove_stroke_pen`` refuses it ``stroke_bound_unproven`` -- so
        # this helper's floor is the defence in depth for the instrument
        # call sites, not the admission path.
        floored_miter = _stroke_outset_visual(
            show,
            frame=frame,
            pen=StrokePen(width=4.0, line_join=0, miter_limit=0.0),
            conservative=True,
        )
        assert floored_miter == pytest.approx(1.0 * half_pen_scaled)
    finally:
        doc.close()


# ------------------------------------- T16-4 S1 review H2 (the join classes)


def test_the_conservative_factor_treats_every_undefined_join_as_miter():
    """H2: only 1 (round) and 2 (bevel) are non-miter.

    MuPDF renders a NEGATIVE join operand (``-1 j``) as MITER, so the old
    ``pen.line_join == 0`` test collapsed the conservative bound 10x on a
    stream that paints a miter vertex -- the false-SAFE direction D4 forbids
    at the duplicate-painter gate.  The fail-closed rule is the complement:
    every join NOT in ``{1, 2}`` takes the miter factor, whatever the
    renderer happens to do with an undefined value (``5 j`` and an ExtGState
    ``/LJ 5`` were measured rendering bevel/round in MuPDF -- renderer
    behaviour on an undefined operand, not a contract).

    The factor is ``max(miter_limit, 1.0)``, never below the geometric
    half-pen the stroke always reaches.
    """
    doc = _page()
    try:
        frame = page_visual_frame(doc[0])
        show = _show()
        half_pen_scaled = 2.0 * sigma_max((1.0, 0.0, 0.0, -1.0))  # width 4 / 2

        def outset(line_join: int, miter_limit: float = 5.0) -> float | None:
            return _stroke_outset_visual(
                show,
                frame=frame,
                pen=StrokePen(
                    width=4.0, line_join=line_join, miter_limit=miter_limit
                ),
                conservative=True,
            )

        # Miter (0) and every undefined join take max(M, 1.0).
        assert outset(0) == pytest.approx(5.0 * half_pen_scaled)
        assert outset(-1) == pytest.approx(5.0 * half_pen_scaled)
        assert outset(5) == pytest.approx(5.0 * half_pen_scaled)
        # Round and bevel are the only two that collapse to half the pen.
        assert outset(1) == pytest.approx(1.0 * half_pen_scaled)
        assert outset(2) == pytest.approx(1.0 * half_pen_scaled)
        # The 1.0 floor applies to every join that takes the factor.
        assert outset(0, miter_limit=0.5) == pytest.approx(1.0 * half_pen_scaled)
        assert outset(-1, miter_limit=0.5) == pytest.approx(1.0 * half_pen_scaled)
        # The honest bound is 1.0 for every join, undefined ones included.
        assert _stroke_outset_visual(
            show,
            frame=frame,
            pen=StrokePen(width=4.0, line_join=-1, miter_limit=5.0),
            conservative=False,
        ) == pytest.approx(1.0 * half_pen_scaled)
    finally:
        doc.close()


# ------------------------------------------------------ degenerate refusals


@pytest.mark.parametrize(
    ("width", "line_join", "miter_limit", "ctm", "conservative"),
    [
        pytest.param(0.0, 1, 10.0, _IDENTITY, False, id="zero-width"),
        pytest.param(math.nan, 1, 10.0, _IDENTITY, False, id="nan-width"),
        pytest.param(4.0, 0, math.nan, _IDENTITY, False, id="nan-miterlimit"),
        # The conservative twin of the row above, and NOT redundant with it:
        # only this one reaches the factor, where ``max(nan, 1.0)`` returns
        # ``nan`` (Python's ``max`` keeps the first argument when the
        # comparison is false).  Without the finite guard the conservative
        # bound would come back ``nan``, which is not ``None`` -- so the
        # duplicate gate would outset ``target_core`` by ``nan`` and call
        # every twin disjoint.  ``_prove_stroke_pen`` refuses a non-finite
        # ``M`` before admission, but this helper is also called from
        # ``duplicate_source_painter_detail`` and from the instruments with
        # pens no gate proved.
        pytest.param(
            4.0, 0, math.nan, _IDENTITY, True, id="nan-miterlimit-conservative"
        ),
        pytest.param(
            4.0, 1, 10.0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), False, id="zero-ctm"
        ),
    ],
)
def test_stroke_outset_refuses_degenerate_pens(
    width, line_join, miter_limit, ctm, conservative
):
    doc = _page()
    try:
        frame = page_visual_frame(doc[0])
        result = _stroke_outset_visual(
            _show(ctm=ctm),
            frame=frame,
            pen=StrokePen(width=width, line_join=line_join, miter_limit=miter_limit),
            conservative=conservative,
        )
        assert result is None
    finally:
        doc.close()
