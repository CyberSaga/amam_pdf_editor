"""Red-light matrix for Tier 1's flag-immune background sampling box."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from model.text_commit.verify import (  # noqa: E402
    VerificationFailure,
    capture_page_state,
    verify_tier1_commit,
)
from test_scripts.type0_fixture_builder import (  # noqa: E402
    REPLACEMENT_LONGER,
    Type0Fixture,
    append_page_content,
    build_identity_h_fixture,
    install_image_xobject,
    install_shading_form_xobject,
)


def _target_bbox_visual(fixture: Type0Fixture) -> tuple[float, float, float, float]:
    chars = []
    for block in fixture.page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(char["c"] for char in span["chars"])
                if fixture.text in text:
                    start = text.index(fixture.text)
                    chars = span["chars"][start : start + len(fixture.text)]
                    break
    assert chars
    raw = fitz.Rect(
        min(char["bbox"][0] for char in chars),
        min(char["bbox"][1] for char in chars),
        max(char["bbox"][2] for char in chars),
        max(char["bbox"][3] for char in chars),
    )
    visual = raw * fixture.page.rotation_matrix
    return tuple(float(v) for v in visual)


def _prepare(fixture: Type0Fixture) -> PreparedEdit | PlanRejection:
    return TieredCommitEngine(fixture.doc, max_tier=1).prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_LONGER,
        expected_origin=None,
        target_bbox=_target_bbox_visual(fixture),
    )


def _with_small_glyph_heights(value: bool, callback):
    prior = bool(fitz.TOOLS.set_small_glyph_heights())
    try:
        fitz.TOOLS.set_small_glyph_heights(value)
        return callback()
    finally:
        fitz.TOOLS.set_small_glyph_heights(prior)


@pytest.mark.parametrize("small", [True, False], ids=["flag-on", "flag-off"])
def test_dense_cjk_growth_uses_the_same_metric_background_box(small: bool) -> None:
    fixture = build_identity_h_fixture()
    result = _with_small_glyph_heights(small, lambda: _prepare(fixture))
    assert isinstance(result, PreparedEdit), result
    assert result.has_ink_growth is True
    assert result.background_bbox_page is not None
    fixture.doc.close()


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_dense_cjk_metric_background_box_is_rotation_correct(rotate: int) -> None:
    fixture = build_identity_h_fixture(rotate=rotate)
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PreparedEdit), result
    assert result.background_bbox_page is not None
    fixture.doc.close()


@pytest.mark.parametrize("obstacle", ["vector", "image", "shading"])
def test_growth_zone_ink_stays_rejected_with_metric_sampling(obstacle: str) -> None:
    fixture = build_identity_h_fixture()
    if obstacle == "vector":
        append_page_content(fixture, "q 0 0 0 rg 122 690 6 20 re f Q")
    elif obstacle == "image":
        install_image_xobject(fixture, name="ImB", rgb=(0, 0, 0))
        append_page_content(fixture, "q 6 0 0 20 122 690 cm /ImB Do Q")
    else:
        install_shading_form_xobject(
            fixture, name="ShB", bbox=(122.0, 690.0, 128.0, 710.0)
        )
        append_page_content(fixture, "/ShB Do")
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    fixture.doc.close()


def test_ink_at_the_exact_growth_boundary_stays_rejected() -> None:
    fixture = build_identity_h_fixture()
    append_page_content(fixture, "q 0 0 0 rg 120 690 1 20 re f Q")
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    fixture.doc.close()


def test_white_on_white_target_stays_rejected() -> None:
    fixture = build_identity_h_fixture()
    stream = fixture.content_bytes()
    fixture.doc.update_stream(fixture.content_xref, b"1 1 1 rg " + stream)
    result = _with_small_glyph_heights(True, lambda: _prepare(fixture))
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    assert "ink is not visible" in result.detail
    fixture.doc.close()


def test_none_background_box_keeps_legacy_target_bbox_sampling() -> None:
    fixture = build_identity_h_fixture()

    def exercise() -> VerificationFailure | tuple[str, ...]:
        prepared = _prepare(fixture)
        assert isinstance(prepared, PreparedEdit), prepared
        legacy = dataclasses.replace(prepared, background_bbox_page=None)
        pre_state = capture_page_state(fixture.doc, fixture.page, legacy)
        apply_patchset(
            fixture.doc,
            fixture.page,
            PatchSet(
                page_xref=legacy.page_xref,
                replacements=(legacy.replacement,),
                expected_page_fingerprint=legacy.page_fingerprint,
            ),
        )
        return verify_tier1_commit(fixture.doc, fixture.page, legacy, pre_state)

    result = _with_small_glyph_heights(True, exercise)
    assert isinstance(result, VerificationFailure), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    assert "no majority background colour" in result.detail
    fixture.doc.close()


# ==========================================================================
# Task D (2026-09-29): exact stroke geometry for the occupancy gate.
#
# ``_drawings_intersect_growth`` used to refuse whenever a drawing's PATH
# BBOX overlapped the growth zone.  For a stroke-only path made of straight
# ``l``/``re`` segments that bbox says nothing about ink: an open page frame
# (hvac p5 drawing 77, 3 ``l`` segments) has a bbox covering the whole page
# while its ink is a 0.36pt line along the edges.  The exemption proves the
# STROKED geometry clears the zone (capsule per segment, join discs,
# similarity CTM, solid dash, non-zero width) and keeps the bbox verdict for
# everything it cannot model exactly.  The raster background proof still
# runs on its own afterwards, so every "admitted" case below is a full
# Tier 1 prepare, not an occupancy-only probe.
#
# Geometry (user space): the CJK target spans x 72..120 at baseline 700;
# ``REPLACEMENT_LONGER`` grows it by one 12pt glyph, so the growth zone is
# x ~120..132, y ~689..712.
# ==========================================================================

_OPEN_FRAME = "20 20 m 20 800 l 560 800 l 560 20 l"
_OCCUPANCY_DRAWING = "occupancy: vector drawing intersects growth zone"


def _stroke(ops: str, *, width: float = 1.0, extra: str = "") -> str:
    return f"q 0 0 0 RG {width:g} w {extra} {ops} S Q"


def _prepare_with(content: str, *, rotate: int = 0) -> PreparedEdit | PlanRejection:
    fixture = build_identity_h_fixture(rotate=rotate)
    append_page_content(fixture, content)
    try:
        return _prepare(fixture)
    finally:
        fixture.doc.close()


def _assert_admitted(result: PreparedEdit | PlanRejection) -> None:
    assert isinstance(result, PreparedEdit), result
    assert result.has_ink_growth is True


def _assert_occupancy_refused(result: PreparedEdit | PlanRejection) -> None:
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK, result
    assert result.detail == _OCCUPANCY_DRAWING, result.detail


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_open_stroke_frame_whose_bbox_covers_the_zone_is_admitted(rotate: int) -> None:
    """The hvac p5 drawing 77 shape: open, stroke-only, three ``l``
    segments, bbox ~ the whole page, no segment near the zone.  /Rotate
    pages pin the dict-space vs visual-space mapping of the proof."""
    _assert_admitted(_prepare_with(_stroke(_OPEN_FRAME), rotate=rotate))


def test_open_stroke_frame_commits_and_changes_only_the_target_show() -> None:
    fixture = build_identity_h_fixture()
    append_page_content(fixture, _stroke(_OPEN_FRAME))
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    prepared = engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=REPLACEMENT_LONGER,
        expected_origin=None,
        target_bbox=_target_bbox_visual(fixture),
    )
    assert isinstance(prepared, PreparedEdit), prepared
    before = fixture.content_bytes()
    outcome = engine.commit(prepared)
    assert outcome.status.value == "committed", outcome
    assert "growth_region_blank_pre_edit" in outcome.verified_properties
    replacement = prepared.replacement
    assert fixture.content_bytes() == (
        before[: replacement.start]
        + replacement.replacement_bytes
        + before[replacement.end :]
    )
    fixture.doc.close()


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_same_frame_with_a_segment_crossing_the_zone_is_refused(rotate: int) -> None:
    _assert_occupancy_refused(
        _prepare_with(_stroke(_OPEN_FRAME + " 126 20 l 126 800 l"), rotate=rotate)
    )


@pytest.mark.parametrize("paint", ["f", "B", "b"])
def test_filled_rect_around_the_zone_is_refused(paint: str) -> None:
    """Fill paints the interior: no exemption for ``f``/``B``/``b``,
    even in white (the occupancy gate must report, not the raster proof)."""
    _assert_occupancy_refused(
        _prepare_with(f"q 1 1 1 rg 0 0 0 RG 1 w 60 640 150 120 re {paint} Q")
    )


@pytest.mark.parametrize(
    "ops",
    [
        "60 600 m 200 600 l 220 700 l 130 790 l 40 700 l h",
        "50 650 150 100 re",
    ],
    ids=["closed-pentagon", "closed-re"],
)
def test_closed_stroked_path_whose_interior_contains_the_zone_is_admitted(
    ops: str,
) -> None:
    """``S`` never fills (ISO 32000-1 8.5.3.1: only f/F/f*/B/B*/b/b* paint
    the interior), so a closed stroke-only path's interior is not ink and
    there is no fill-rule question to resolve; the stroked edges and every
    join (including the closing one) are far from the zone."""
    _assert_admitted(_prepare_with(_stroke(ops)))


def test_thick_stroke_whose_half_width_reaches_into_the_zone_is_refused() -> None:
    """The x=138 segment's centreline is ~6pt right of the zone, its 16pt
    stroke reaches 8pt: ink in the zone although the centreline is not."""
    _assert_occupancy_refused(
        _prepare_with(_stroke("20 800 m 138 800 l 138 20 l", width=16.0))
    )


def test_the_same_geometry_with_a_thin_stroke_is_admitted() -> None:
    """Control for the thick case: width, not the centreline, decides."""
    _assert_admitted(_prepare_with(_stroke("20 800 m 138 800 l 138 20 l", width=1.0)))


_MITER_SPIKE = "202 694 m 144 700 l 202 706 l 20 20 m 20 800 l"


def test_miter_join_spike_reaching_into_the_zone_is_refused() -> None:
    """A ~11.8 degree miter join at x=144 with a 4pt stroke and miter limit
    100: the spike's tip reaches ~19pt left, into the zone, although both
    segments' capsules stay ~12pt away."""
    _assert_occupancy_refused(
        _prepare_with(_stroke(_MITER_SPIKE, width=4.0, extra="0 j 100 M"))
    )


@pytest.mark.parametrize("extra", ["1 j", "2 j", "0 j 2 M"], ids=["round", "bevel", "miter-limited"])
def test_the_same_sharp_vertex_without_a_long_miter_is_admitted(extra: str) -> None:
    _assert_admitted(_prepare_with(_stroke(_MITER_SPIKE, width=4.0, extra=extra)))


@pytest.mark.parametrize(
    "content",
    [
        _stroke("20 20 m 20 800 560 800 560 20 c"),
        _stroke(_OPEN_FRAME, extra="[4 2] 0 d"),
        _stroke(_OPEN_FRAME, width=0.0),
        "q 1 0 0 2 0 0 cm 0 0 0 RG 1 w 20 10 m 20 400 l 280 400 l 280 10 l S Q",
        "q 1 0.5 0 1 0 0 cm 0 0 0 RG 1 w 20 10 m 20 700 l 280 700 l 280 10 l S Q",
        _stroke("60 600 m 250 620 l 230 790 l 40 770 l 60 600 l"),
    ],
    ids=["curve", "dashed", "hairline", "anisotropic-cm", "shear-cm", "quad"],
)
def test_strokes_the_exact_proof_cannot_model_keep_the_bbox_verdict(content: str) -> None:
    """Every one of these is far from the zone as ink (the raster proof
    alone would pass) -- yet each keeps today's bbox refusal because the
    exact proof does not model curves, dashes, hairlines, non-similarity
    transforms or PyMuPDF's merged ``qu`` items."""
    _assert_occupancy_refused(_prepare_with(content))


def test_separate_thick_stroke_beside_an_exempted_frame_is_still_refused() -> None:
    """The frame's bbox overlaps the zone, so the exact proof runs; a
    SEPARATE 16pt stroke at x=138 has a centreline path extent ~6pt right of
    the zone but ink reaching 8pt, into it.  The proof must select device
    records by INK reach (path extent inflated by half-width, cap and miter
    bound plus margin), not by path extent, so this stroke is relevant, is
    not clear, and the OCCUPANCY gate refuses -- the raster proof is not the
    only line of defence."""
    _assert_occupancy_refused(
        _prepare_with(
            _stroke(_OPEN_FRAME) + " " + _stroke("138 600 m 138 800 l", width=16.0)
        )
    )


# Task T (2026-09-29): ink-reach relevance.  Each case below has the open
# frame present (its bbox overlap starts the exact proof) plus a SEPARATE
# stroke whose path extent is more than ``_RELEVANCE_SLACK`` from the zone
# while its ink lands inside it.  Before Task T these were admitted by the
# occupancy proof and only the raster proof refused (detail ``raster:``);
# every geometry was checked to put real ink in the zone.
_REACH_HOLES = {
    # 20pt butt-capped line, centreline x=138 (6pt right of the zone's
    # x1=132): the half-width reaches 10pt, into the zone.
    "wide-line": _stroke("138 600 m 138 800 l", width=20.0),
    # 2pt line, miter limit 10, ~11.8 degree vertex at x=136 (4pt away):
    # miter ratio ~9.72 < 10, so the spike tip reaches ~9.7pt left, into the
    # zone, while both segments' capsules stay clear.
    "miter-vertex": _stroke(
        "194 698.66 m 136 704.66 l 194 710.66 l", width=2.0, extra="0 j 10 M"
    ),
    # The same spike with its vertex at x=138 (6pt away) pins the miter
    # factor in the REACH: without it the reach box (1*sqrt2 + 2 + 1 slack
    # = 4.4) would miss, while the tip still lands at x ~128.3, in the zone.
    "miter-vertex-6pt": _stroke(
        "196 698.66 m 138 704.66 l 196 710.66 l", width=2.0, extra="0 j 10 M"
    ),
    # 12pt square-capped line ending at x=135 (3pt away): the cap projects
    # 6pt beyond the endpoint, into the zone.
    "square-cap": _stroke("200 704.66 m 135 704.66 l", width=12.0, extra="2 J"),
}


_REACH_PINS = {
    # Pins sqrt(2) in the REACH: a 40pt square-capped, round-joined line
    # arriving at 45 degrees and ending at visual (156, 137.3), 24pt right of
    # the zone with no vertical offset.  Its leftmost cap corner sits
    # hw*sqrt(2) ~28.3pt left of the endpoint, at x ~127.7, inside the zone;
    # a reach of hw + margin + slack (23) would not select the record.  (With
    # a butt cap the same geometry puts no ink in the zone.)
    "diagonal-square-cap": _stroke(
        "216 764.66 m 156 704.66 l", width=40.0, extra="2 J 1 j"
    ),
    # Pins the margin in the REACH: a separate 1pt round-joined line at
    # x=134.5, centreline 2.5pt from the zone, ink ~2pt clear -- inside the
    # clearance margin, so it must be selected and refused, as the frame's
    # own segment is in ``test_stroke_within_the_clearance_margin_is_refused``.
    "separate-within-margin": _stroke("134.5 600 m 134.5 800 l", width=1.0, extra="1 j"),
}


@pytest.mark.parametrize("stroke", list(_REACH_PINS.values()), ids=list(_REACH_PINS))
def test_ink_reach_terms_select_the_separate_stroke(stroke: str) -> None:
    _assert_occupancy_refused(_prepare_with(_stroke(_OPEN_FRAME) + " " + stroke))


@pytest.mark.parametrize("stroke", list(_REACH_HOLES.values()), ids=list(_REACH_HOLES))
def test_separate_stroke_whose_ink_reaches_the_zone_is_refused_at_occupancy(
    stroke: str,
) -> None:
    _assert_occupancy_refused(_prepare_with(_stroke(_OPEN_FRAME) + " " + stroke))


def test_the_miter_vertex_bevelled_beside_the_frame_is_admitted() -> None:
    """Control for ``miter-vertex``: the same geometry bevelled has no spike,
    its ink stays >2pt clear, so the record is relevant AND proven clear."""
    _assert_admitted(
        _prepare_with(
            _stroke(_OPEN_FRAME)
            + " "
            + _stroke("194 698.66 m 136 704.66 l 194 710.66 l", width=2.0, extra="2 j")
        )
    )


def test_stroke_within_the_clearance_margin_is_refused() -> None:
    """Mutation pin for ``_STROKE_CLEARANCE_MARGIN_PT``: a 1pt vertical
    segment of the frame's OWN path (relevant whatever the margin) with its
    centreline 1.5pt right of the zone.  Its ink (hw 0.5, cap bound ~0.71)
    misses the zone by ~0.8pt, inside the 2pt clearance: refused at
    occupancy.  With a zero margin the proof would admit it."""
    _assert_occupancy_refused(_prepare_with(_stroke(_OPEN_FRAME + " 133.5 672 m 133.5 742 l")))


def test_square_cap_corner_reaching_diagonally_into_the_zone_is_refused() -> None:
    """Mutation pin for the ``sqrt(2)`` cap bound: a 20pt square-capped line
    ending at visual (141, 120.5), 9pt right of and 9pt above the zone's
    top-right corner (132, 129.5).  The endpoint is 12.7pt from the zone --
    more than ``hw + margin`` (12) -- yet the cap's corner sits at
    (131, 130.5), 1pt inside the zone diagonally.  Only the ``hw * sqrt(2)``
    cap radius (16.1 with margin) catches it."""
    _assert_occupancy_refused(
        _prepare_with(
            _stroke(_OPEN_FRAME)
            + " "
            + _stroke("200 721.504 m 141 721.504 l", width=20.0, extra="2 J")
        )
    )


def test_unobservable_stroke_run_keeps_the_bbox_refusal(monkeypatch) -> None:
    import model.text_commit.stroke_occupancy as stroke_occupancy

    monkeypatch.setattr(stroke_occupancy, "collect_stroke_records", lambda page: None)
    _assert_occupancy_refused(_prepare_with(_stroke(_OPEN_FRAME)))


def test_device_records_in_a_different_frame_fail_the_vertex_cross_check(
    monkeypatch,
) -> None:
    """The cross-check is not decoration: records that clear the zone but
    do not coincide with the ``get_drawings`` entry (here the real records
    shifted 50pt right) must not vouch for it."""
    import model.text_commit.stroke_occupancy as stroke_occupancy

    real = stroke_occupancy.collect_stroke_records

    def shifted(page):
        records = real(page)
        assert records is not None
        moved = []
        for record in records:
            subpaths = tuple(
                dataclasses.replace(
                    sub, points=tuple((x + 50.0, y) for x, y in sub.points)
                )
                for sub in record.subpaths
            )
            x0, y0, x1, y1 = record.extent
            moved.append(
                dataclasses.replace(
                    record, subpaths=subpaths, extent=(x0 + 50.0, y0, x1 + 50.0, y1)
                )
            )
        return tuple(moved)

    monkeypatch.setattr(stroke_occupancy, "collect_stroke_records", shifted)
    _assert_occupancy_refused(_prepare_with(_stroke(_OPEN_FRAME)))
