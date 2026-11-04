"""T16-4X S0 F7(b): the page-visual-frame fail-closed adapter has one home.

``page_visual_frame_or_none`` is the single chokepoint every geometry
consumer must go through to turn :func:`page_visual_frame`'s
``UnsupportedPageGeometryError`` into ``None`` -- previously duplicated as
``inspect._page_visual_frame_or_none``,
``scripts.audit_tier_coverage._page_frame_or_none`` and an inline
try/except in ``scripts/measure_tier_funnel.py`` (docs/PITFALLS.md: "an
audit that mirrors a gate goes stale the day the gate moves").
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

from model.text_commit import transforms  # noqa: E402
from model.text_commit.transforms import (  # noqa: E402
    PageVisualFrame,
    page_visual_frame_or_none,
)

HELLO = "Hello"


def _plain_doc() -> fitz.Document:
    """One ordinary page: no ``/CropBox``, no ``/UserUnit`` override."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 72 700 Td (" + HELLO.encode() + b") Tj ET"
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


def _user_unit_zero_doc() -> fitz.Document:
    """Same page, but ``/UserUnit`` is ``0`` --
    :func:`~model.text_commit.transforms.page_visual_frame` refuses this
    shape (``UnsupportedPageGeometryError``: "/UserUnit is not a usable
    positive scale"), so the page's visual frame can never be proven.
    """
    doc = _plain_doc()
    doc.xref_set_key(doc[0].xref, "UserUnit", "0")
    return doc


def test_page_visual_frame_or_none_returns_none_when_unprovable():
    doc = _user_unit_zero_doc()
    try:
        assert page_visual_frame_or_none(doc[0]) is None
    finally:
        doc.close()


def test_page_visual_frame_or_none_returns_frame_for_a_plain_page():
    doc = _plain_doc()
    try:
        frame = page_visual_frame_or_none(doc[0])
        assert isinstance(frame, PageVisualFrame)
    finally:
        doc.close()



# ==========================================================================
# Plan section 2.C -- the narrow reflected-TRM admission (pure functions)
#
# "Reflected" is separated from "degenerate": ``allow_reflection=True``
# skips ONLY the orientation gate, so every degeneracy gate (finite,
# singular via ``|det|``, floor, shear, equal norms) still applies to a
# mirrored matrix.  ``admission_verdict`` admits a mirror only when the
# caller PROVES a fill-only render mode (``render_mode=0``); a caller that
# passes nothing keeps the historical ``trm_reflected`` refusal.
# ==========================================================================




_TRM_REFLECTED = "trm_reflected"
_TRM_SHEARED = "trm_sheared"
_TRM_NON_UNIFORM_SCALE = "trm_non_uniform_scale"
_TRM_SINGULAR = "trm_singular"
_TRM_NON_FINITE = "trm_non_finite"
_TRM_SCALE_BELOW_FLOOR = "trm_scale_below_floor"
_IDENTITY_M = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Mirrors whose visual baseline is CARDINAL on an unrotated page, so a
# missing orientation-blind gate cannot hide behind the direction gate.
_BASELINE_MIRROR = (-1.0, 0.0, 0.0, 1.0)  # baseline runs left
_CROSS_MIRROR = (1.0, 0.0, 0.0, -1.0)  # ascender points down
_QUARTER_MIRROR = (0.0, 1.0, 1.0, 0.0)  # baseline runs up


def _page() -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    return doc, doc.new_page(width=595, height=842)


def _blind(linear: tuple[float, float, float, float]) -> str | None:
    return transforms.shape_reject_reason(linear, allow_reflection=True)


def test_allow_reflection_admits_orthogonal_uniform_mirrors_at_every_scale():
    for s in (1e-3, 1.0, 1e3):
        for linear in (_BASELINE_MIRROR, _CROSS_MIRROR, _QUARTER_MIRROR):
            scaled = (linear[0] * s, linear[1] * s, linear[2] * s, linear[3] * s)
            # Default contract unchanged: orientation still refuses.
            assert transforms.shape_reject_reason(scaled) == _TRM_REFLECTED
            assert _blind(scaled) is None, (linear, s)


def test_allow_reflection_keeps_every_degeneracy_gate():
    for s in (1e-3, 1.0, 1e3):
        # Sheared mirror whose baseline (-1, 0) is still cardinal.
        assert _blind((-s, 0.0, 0.5 * s, s)) == _TRM_SHEARED, s
        # Non-uniform mirror, cardinal baseline.
        assert _blind((-2.0 * s, 0.0, 0.0, s)) == _TRM_NON_UNIFORM_SCALE, s
        # |det| drives the singular gate for a negative determinant too.
        assert _blind((s, 0.0, 0.0, -s * 9e-7)) == _TRM_SINGULAR, s
        assert _blind((s, 0.0, 0.0, -s * 1.1e-6)) == _TRM_NON_UNIFORM_SCALE, s
        # Shear boundary on a mirror: 9e-7 inside, 1.1e-6 outside.
        assert _blind((-s, 0.0, s * 9e-7, s)) is None, s
        assert _blind((-s, 0.0, s * 1.1e-6, s)) == _TRM_SHEARED, s
        # Norm boundary on a mirror.
        assert _blind((-s, 0.0, 0.0, s * (1.0 + 9e-7))) is None, s
        assert (
            _blind((-s, 0.0, 0.0, s * (1.0 + 1.1e-6))) == _TRM_NON_UNIFORM_SCALE
        ), s
    assert _blind((math.nan, 0.0, 0.0, -1.0)) == _TRM_NON_FINITE
    assert _blind((0.0, 0.0, 0.0, 0.0)) == _TRM_SINGULAR
    assert _blind((-5e-7, 0.0, 0.0, 5e-7)) == _TRM_SCALE_BELOW_FLOOR


@pytest.mark.parametrize(
    ("linear", "direction"),
    [
        (_BASELINE_MIRROR, "left"),
        (_CROSS_MIRROR, "right"),
        (_QUARTER_MIRROR, "up"),
    ],
    ids=["baseline_axis", "cross_axis", "quarter_turn"],
)
def test_admission_verdict_admits_a_fill_only_cardinal_mirror(linear, direction):
    doc, page = _page()
    try:
        tm = (linear[0], linear[1], linear[2], linear[3], 200.0, 400.0)
        verdict = transforms.admission_verdict(
            page, tm, _IDENTITY_M, render_mode=0
        )
        assert verdict.reject_reason is None
        assert verdict.reflected is True
        assert verdict.direction == direction
        assert verdict.scale == pytest.approx(1.0)
        # No render-mode evidence: the historical refusal, fail-closed.
        unproven = transforms.admission_verdict(page, tm, _IDENTITY_M)
        assert unproven.reject_reason == _TRM_REFLECTED
        assert unproven.reflected is False and unproven.direction is None
    finally:
        doc.close()


def test_admission_verdict_mirror_on_a_rotate_270_page_runs_down():
    """The measured HVAC shape: baseline-axis mirror (a < 0, d > 0) on a
    /Rotate 270 page -- the baseline runs visual DOWN."""
    doc, page = _page()
    page.set_rotation(270)
    try:
        verdict = transforms.admission_verdict(
            page,
            (-0.06, 0.0, 0.0, 0.06, 700.0, 800.0),
            _IDENTITY_M,
            render_mode=0,
        )
        assert verdict.reject_reason is None
        assert verdict.reflected is True
        assert verdict.direction == "down"
    finally:
        doc.close()


def test_admission_verdict_refuses_mirrors_outside_the_narrow_family():
    doc, page = _page()
    try:
        c30 = math.cos(math.radians(30.0))
        s30 = math.sin(math.radians(30.0))
        refused = {
            "render_mode_2": ((-1.0, 0.0, 0.0, 1.0, 200.0, 400.0), 2),
            "render_mode_1": ((-1.0, 0.0, 0.0, 1.0, 200.0, 400.0), 1),
            "sheared": ((-1.0, 0.0, 0.5, 1.0, 200.0, 400.0), 0),
            "non_uniform": ((-2.0, 0.0, 0.0, 1.0, 200.0, 400.0), 0),
            "oblique": ((c30, s30, s30, -c30, 200.0, 400.0), 0),
        }
        for label, (tm, mode) in refused.items():
            verdict = transforms.admission_verdict(
                page, tm, _IDENTITY_M, render_mode=mode
            )
            assert verdict.reject_reason == _TRM_REFLECTED, label
            assert verdict.reflected is False, label
            assert verdict.direction is None, label
        # Degeneracy keeps its own code ahead of orientation.
        singular = transforms.admission_verdict(
            page, (1.0, 0.0, 0.0, -9e-7, 200.0, 400.0), _IDENTITY_M,
            render_mode=0,
        )
        assert singular.reject_reason == _TRM_SINGULAR
        # A positive-orientation verdict never claims reflection.
        upright = transforms.admission_verdict(
            page, (1.0, 0.0, 0.0, 1.0, 200.0, 400.0), _IDENTITY_M,
            render_mode=0,
        )
        assert upright.reject_reason is None and upright.reflected is False
    finally:
        doc.close()


def test_mirror_split_between_tm_and_ctm_is_judged_combined():
    """A mirror in the CTM times an upright Tm is still a mirror; two
    mirrors cancel into a positive-orientation shape."""
    doc, page = _page()
    try:
        mirrored_ctm = (-1.0, 0.0, 0.0, 1.0, 500.0, 0.0)
        verdict = transforms.admission_verdict(
            page, (1.0, 0.0, 0.0, 1.0, 100.0, 400.0), mirrored_ctm,
            render_mode=0,
        )
        assert verdict.reflected is True and verdict.direction == "left"
        cancelled = transforms.admission_verdict(
            page, (-1.0, 0.0, 0.0, 1.0, 100.0, 400.0), mirrored_ctm
        )
        assert cancelled.reject_reason is None and cancelled.reflected is False
    finally:
        doc.close()

