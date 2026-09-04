"""P4-B2 slice 3b: exact painter geometry in the duplicate-painter gate.

The gate no longer treats a DECLARED ADVANCE as an ink bound for the CID
population.  For a Type0 target whose twin is also a Type0 font this file
pins the composition of plan §3.2 "Gate":

1. a non-CID target or twin keeps the pre-slice advance/reach path verbatim;
2. a twin with ``render_mode != 0`` is ambiguous and falls to reach;
3. the target's ink is the union of the source AND replacement glyph boxes
   placed by the target's own cursor replay;
4. the twin's ink comes from ITS OWN program and replay (``TJ`` kerns
   re-lexed from the stream), and any ambiguous glyph falls to reach;
5. an aggregate AABB prefilter, then every (target glyph, twin glyph) pair.

Every geometric claim here is anchored to the raster oracle
(``painter_matrix_fixtures.painters_overlap_pixels``): a cell that says
"admissible" also proves the two single-painter renders share NO pixel, and
a cell that says "refused" proves they do.  The gate is never the only
witness for its own verdict.

**Value cells run the same page twice.**  A caller that hands the gate no
``GlyphBoxCache`` keeps the pre-slice behaviour verbatim — that is the
documented meaning of the ``glyph_boxes=None`` default — so the ``exact``
and ``no-cache`` arms of one build ARE the before/after comparison, with no
frozen-tip characterization pin to go stale.

**Cells labelled PIN passed before the implementation** (CLAUDE.md §5.1):
the simple-font clone and the unreliable-origin target are refusals the
pre-slice code already produced, and they are here to prove the exact arm
does not disturb them.  Everything else was red.

The ``/W`` continuum and the R5 core band live in
``test_p4b2_production_pins.py``, which this file deliberately does not
duplicate.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    duplicate_source_painter_detail,
    prepare_plan,
)
from model.text_commit.transforms import (  # noqa: E402
    map_text_quad_to_visual,
    page_visual_frame,
)
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    replay_shows,
    set_page_boxes,
    set_user_unit,
    single_painter_masks,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    FONTSIZE,
    REPLACEMENT,
    SOURCE,
    SOURCE_WIDTH,
    _build_second_show_doc,
    _simple_metric_clone_plan,
)
from test_scripts.type0_fixture_builder import Type0Fixture  # noqa: E402

# The three detail strings this slice's composition can produce.
GLYPH_INK = "identical source painter's glyph ink overlaps the target ink by"
REACH = (
    "identical source painter cannot prove exact extent, and its bounded "
    "ink can reach the target core"
)
TARGET_UNPROVEN = "identical source painter cannot prove target placement"
CORE_OVERLAP = "identical source painter overlaps target core by"


# ------------------------------------------------------------------ harness


def _visual_origin(fixture: Type0Fixture) -> tuple[float, float]:
    """The FIRST painter's origin in the space ``bind_source_text`` matches.

    Re-derived from the page's own visual frame rather than captured from
    the pristine document, so a cell that rotates, crops or rescales the
    page after building still addresses the target and not the twin.
    """
    visual = page_visual_frame(fixture.page).visual
    ox, oy = fixture.origin
    return (
        visual.a * ox + visual.c * oy + visual.e,
        visual.b * ox + visual.d * oy + visual.f,
    )


def _clip(fixture: Type0Fixture, *, pad: float = 40.0) -> tuple[float, float, float, float]:
    """A render window around BOTH painters, in visual space.

    ``painter_matrix_fixtures.two_painter_clip`` reads the authored origin
    as if it were page space, which is wrong the moment ``/Rotate``,
    ``/CropBox`` or ``/UserUnit`` moves it; every corner here rides the same
    chokepoint the gate uses.
    """
    page = fixture.page
    frame = page_visual_frame(page)
    xs: list[float] = []
    ys: list[float] = []
    for show in replay_shows(fixture):
        for tx in (-4.0, 40.0):
            quad = map_text_quad_to_visual(
                page, show.tm, show.ctm, (tx, -14.0, tx, 26.0), frame=frame
            )
            xs += [quad[0], quad[2]]
            ys += [quad[1], quad[3]]
    rect = page.rect
    return (
        max(rect.x0, min(xs) - pad),
        max(rect.y0, min(ys) - pad),
        min(rect.x1, max(xs) + pad),
        min(rect.y1, max(ys) + pad),
    )


@dataclasses.dataclass(frozen=True)
class Outcome:
    result: PreparedEdit | PlanRejection
    overlap: int
    target_ink: int
    twin_ink: int

    @property
    def detail(self) -> str:
        assert isinstance(self.result, PlanRejection), self.result
        return self.result.detail


Build = Callable[[], tuple[Type0Fixture, tuple[float, float]]]


def _run(build: Build, *, exact: bool = True) -> Outcome:
    """Raster ground truth and the production verdict for one page.

    ``exact=False`` disables the glyph-box cache, which is exactly what a
    caller that passes no cache gets: the pre-slice advance/reach gate.
    """
    fixture, _ = build()
    try:
        first, second = single_painter_masks(fixture, clip=_clip(fixture))
        registry = DocumentFontRegistry(fixture.doc)
        if not exact:
            registry.glyph_boxes = None  # type: ignore[assignment]
        result = prepare_plan(
            fixture.doc,
            fixture.page,
            target_text=SOURCE,
            replacement_text=REPLACEMENT,
            expected_origin=_visual_origin(fixture),
            target_bbox=None,
            registry=registry,
            max_tier=1,
        )
    finally:
        fixture.doc.close()
    return Outcome(result, first.overlap_pixels(second), first.ink_pixels, second.ink_pixels)


def _two(**kwargs) -> Build:
    return lambda: _build_second_show_doc(**kwargs)


def _post(build: Build, edit: Callable[[Type0Fixture], None]) -> Build:
    def _run_build() -> tuple[Type0Fixture, tuple[float, float]]:
        fixture, origin = build()
        edit(fixture)
        return fixture, origin

    return _run_build


def _insert_between_painters(raw: str) -> Callable[[Type0Fixture], None]:
    """Text-state operators that apply to the TWIN only."""

    def _edit(fixture: Type0Fixture) -> None:
        stream = fixture.content_bytes()
        marker = b"> Tj /"
        assert stream.count(marker) == 1, "not a two-painter page"
        fixture.doc.update_stream(
            fixture.content_xref,
            stream.replace(marker, b"> Tj " + raw.encode("ascii") + b" /", 1),
        )

    return _edit


def _shear_ctm_around_the_twin() -> Callable[[Type0Fixture], None]:
    """Close the target's ``BT`` and paint the twin under a 2x2 shear CTM.

    The translation cancels the shear at the twin's own baseline, so the
    twin stays where it was authored and only its outline leans.
    """

    def _edit(fixture: Type0Fixture) -> None:
        stream = fixture.content_bytes()
        marker = b"> Tj /"
        assert stream.count(marker) == 1 and stream.endswith(b" ET")
        edited = stream.replace(marker, b"> Tj ET q 1 0 0.5 1 -350 0 cm BT /", 1)
        fixture.doc.update_stream(fixture.content_xref, edited + b" Q")

    return _edit


def _rotate_crop_and_rescale(degrees: int) -> Callable[[Type0Fixture], None]:
    """Slice 2's frame under load: a quarter turn over an OFFSET CropBox at
    ``/UserUnit 2``, the shape PyMuPDF's own matrices get wrong."""

    def _edit(fixture: Type0Fixture) -> None:
        fixture.doc.xref_set_key(fixture.page.xref, "Rotate", str(degrees))
        set_page_boxes(fixture, cropbox=(20.0, 30.0, 500.0, 800.0))
        set_user_unit(fixture, 2.0)

    return _edit


# ------------------------------------- (b) value: a wide /W over narrow ink


def test_wide_declared_width_over_narrow_glyphs_is_admitted() -> None:
    """The twin declares ``/W 1500`` (36 pt of advance) but paints 29.5 pt
    of ink, and sits far enough left that only the DECLARED extent reaches
    the target.  The advance quad refuses; the glyph boxes admit."""
    build = _two(
        offset=-32.0,
        second_resource="F_CLONE",
        second_clone_font=True,
        second_clone_width=1500,
    )
    exact = _run(build)
    assert exact.overlap == 0, "the raster oracle must call these disjoint"
    assert exact.target_ink > 0 and exact.twin_ink > 0
    assert isinstance(exact.result, PreparedEdit), exact.result
    without_cache = _run(build, exact=False)
    assert isinstance(without_cache.result, PlanRejection), without_cache.result
    assert CORE_OVERLAP in without_cache.detail


# ------------------------------------------- (c) TJ twins, cursor-replayed


def test_tj_twin_leading_kern_that_reaches_the_target_is_refused_by_ink() -> None:
    """A ``+6000`` leading kern drags the twin 72 pt left, onto the target.
    The re-lexed kern places it exactly; the ink boxes then refuse."""
    outcome = _run(
        _two(
            offset=SOURCE_WIDTH + 50.0,
            second_operator="TJ",
            second_leading_kern=6000.0,
        )
    )
    assert outcome.overlap > 0
    assert isinstance(outcome.result, PlanRejection), outcome.result
    assert outcome.result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert GLYPH_INK in outcome.detail


def test_tj_twin_leading_kern_that_stays_clear_is_admitted() -> None:
    """The same shape with a ``+4000`` kern lands 3 pt clear of the target.
    Reach cannot tell the two apart (it bounds ``TJ`` in both directions);
    the replayed cursor can."""
    build = _two(
        offset=SOURCE_WIDTH + 50.0,
        second_operator="TJ",
        second_leading_kern=4000.0,
    )
    exact = _run(build)
    assert exact.overlap == 0
    assert exact.twin_ink > 0
    assert isinstance(exact.result, PreparedEdit), exact.result
    without_cache = _run(build, exact=False)
    assert isinstance(without_cache.result, PlanRejection), without_cache.result
    assert REACH in without_cache.detail


# --------------------------------------- (d) non-fill render modes go reach


@pytest.mark.parametrize("mode", [1, 2, 7])
def test_non_fill_render_mode_twin_falls_to_the_reach_path(mode: int) -> None:
    """``Tr 1`` and ``Tr 2`` add a CTM-scaled pen the outline box does not
    carry, and ``Tr 7`` adds a clip whose effect on later ink this gate
    cannot see.  None of the three is an ink bound, so the twin is
    ambiguous and the reach bound decides — never the glyph boxes."""
    outcome = _run(_post(_two(offset=1.0), _insert_between_painters(f"{mode:d} Tr")))
    assert isinstance(outcome.result, PlanRejection), outcome.result
    assert outcome.result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert outcome.detail == REACH
    assert GLYPH_INK not in outcome.detail


# ------------------------------------------------- (e) simple fonts: PIN


def test_simple_font_metric_clone_is_byte_identical() -> None:
    """PIN.  The exact arm addresses the CID population only; a simple-font
    target must reach the pre-slice string unchanged, character for
    character."""
    result = _simple_metric_clone_plan()
    assert isinstance(result, PlanRejection), result
    assert result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert result.detail.startswith(CORE_OVERLAP)
    assert GLYPH_INK not in result.detail


# ------------------------------------- (f) an unprovable target origin: PIN


def test_target_with_an_unreliable_origin_keeps_todays_failure_string() -> None:
    """PIN.  A target whose recorded origin is not where its ink starts can
    place neither an advance quad nor a glyph box, and the exact arm must
    not invent one: the pre-slice target-placement string still wins, and
    it wins BEFORE any twin is measured."""
    fixture, _ = _build_second_show_doc(offset=1.2)
    try:
        shows = replay_shows(fixture)
        registry = DocumentFontRegistry(fixture.doc)
        capability = registry.capability(fixture.page, shows[0].font_resource or "")
        assert capability is not None and capability.cid is not None
        blinded = dataclasses.replace(shows[0], origin_reliable=False)
        detail = duplicate_source_painter_detail(
            fixture.page,
            blinded,
            target_text=SOURCE,
            target_capability=capability,
            source_advance=SOURCE_WIDTH,
            registry=registry,
            shows=shows,
        )
    finally:
        fixture.doc.close()
    assert detail == TARGET_UNPROVEN


# ---------------- (g) raster-verified: never admitted while rasters overlap

OVERLAPPING_SHAPES = [
    pytest.param(_post(_two(offset=1.0), _insert_between_painters("50 Tz")), id="tz50"),
    pytest.param(_post(_two(offset=1.0), _insert_between_painters("150 Tz")), id="tz150"),
    pytest.param(_two(offset=1.0, second_rise=3.0), id="ts+3"),
    pytest.param(_two(offset=1.0, second_rise=-3.0), id="ts-3"),
    pytest.param(_post(_two(offset=1.0), _rotate_crop_and_rescale(90)), id="rotate90"),
    pytest.param(_post(_two(offset=1.0), _rotate_crop_and_rescale(270)), id="rotate270"),
    pytest.param(
        _two(offset=0.0, second_matrix="0.7071 0.7071 -0.7071 0.7071 78 696"),
        id="tm45",
    ),
    pytest.param(
        _post(_two(offset=1.2), _shear_ctm_around_the_twin()), id="shear-ctm"
    ),
]


@pytest.mark.parametrize("build", OVERLAPPING_SHAPES)
def test_overlapping_rasters_are_never_admitted(build: Build) -> None:
    outcome = _run(build)
    assert outcome.overlap > 0, "the oracle must see the twin paint on the target"
    assert isinstance(outcome.result, PlanRejection), outcome.result
    assert outcome.result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER


@pytest.mark.parametrize("build", OVERLAPPING_SHAPES)
def test_overlapping_rasters_are_refused_by_the_glyph_ink_arm(build: Build) -> None:
    """Stronger than the safety cell above: these are all fill-mode CID
    twins, so the EXACT arm must own the refusal.  A reach-path string here
    would mean the exact arm quietly went ambiguous and the safety cell
    passed for the wrong reason."""
    outcome = _run(build)
    assert GLYPH_INK in outcome.detail, outcome.detail


# --------------------------- the twin's own rise places its ink, exactly


def test_a_twin_raised_clear_of_the_target_is_admitted() -> None:
    """BEHAVIOUR CHANGE (slice 3b).  ``_painter_core_quad`` enveloped the
    baseline and the rise-shifted core together because the target box was
    a crude 0.6-em band: translating the candidate alone would have opened
    a false-admit band at ``rise >= 0.6*Tfs``.  With BOTH sides bounded by
    real outlines that approximation is gone, the twin's own ``Ts`` places
    its ink where MuPDF paints it, and a twin two em above the target is
    provably disjoint — which the raster oracle confirms."""
    build = _two(offset=1.0, second_rise=2.0 * FONTSIZE)
    exact = _run(build)
    assert exact.overlap == 0
    assert exact.target_ink > 0 and exact.twin_ink > 0
    assert isinstance(exact.result, PreparedEdit), exact.result
    without_cache = _run(build, exact=False)
    assert isinstance(without_cache.result, PlanRejection), without_cache.result


def test_a_rise_that_cancels_a_baseline_offset_still_refuses() -> None:
    """The other half of the same change: a twin whose ``Ts`` puts it back
    ON the target baseline must still be refused, now by its ink."""
    outcome = _run(_two(offset=1.2, second_dy=-7.2, second_rise=7.2))
    assert outcome.overlap > 0
    assert isinstance(outcome.result, PlanRejection), outcome.result
    assert GLYPH_INK in outcome.detail


# ------------------- a singular text matrix collapses the reach band too


@pytest.mark.parametrize("mode", [1, 2])
def test_a_stroked_twin_under_a_singular_text_matrix_is_refused(mode: int) -> None:
    """The reach bound's y band is only a band while the map is invertible.

    A rank-1 ``Tm`` (``1 0 0 0``) sends every text-space y to one line, so
    the reach quad maps to a SEGMENT and every strict overlap in y measures
    zero — "provably disjoint" for a twin that paints an 8 pt pen bar
    straight across the target.  Surfaced by the production arm of the
    falsification matrix (``collapsed-tm-stroke-tr1/tr2``); it predates this
    slice and is a false safe in the baseline and reach arms alike.
    """
    outcome = _run(
        _post(
            _two(offset=1.0, second_matrix="1 0 0 0 73 700"),
            _insert_between_painters(f"{mode:d} Tr 8 w"),
        )
    )
    assert outcome.overlap > 0, "the pen bar must cross the target"
    assert isinstance(outcome.result, PlanRejection), outcome.result
    assert outcome.result.reason == RejectReason.DUPLICATE_SOURCE_PAINTER
    assert "cannot prove disjoint placement" in outcome.detail


def test_a_filled_twin_under_a_singular_text_matrix_is_still_admitted() -> None:
    """The tightening must not collapse into "refuse every singular twin".

    A rank-1 ``Tm`` with the SAME placement and no stroke paints nothing at
    all — every outline collapses to a zero-area path, which MuPDF fills
    with no pixels (measured: the twin's ink mask is empty).  The exact arm
    proves that from the glyph boxes and admits; only the ambiguous stroked
    form falls to the now-tightened reach bound.  Both halves of the split
    are asserted, so a blanket refusal would fail here.
    """
    outcome = _run(_two(offset=1.0, second_matrix="1 0 0 0 73 700"))
    assert outcome.twin_ink == 0, "a filled collapsed outline paints nothing"
    assert outcome.overlap == 0
    assert isinstance(outcome.result, PreparedEdit), outcome.result


# ------------------------------------------------------- (i) privacy


def test_the_overlap_detail_never_carries_document_text() -> None:
    """§10 privacy: the new string is measurements only — no glyph, no
    character, no resource name, and ASCII throughout."""
    outcome = _run(_two(offset=1.2))
    detail = outcome.detail
    assert GLYPH_INK in detail
    assert detail.isascii(), detail
    for char in SOURCE + REPLACEMENT:
        assert char not in detail
    assert "F0" not in detail and "F_CLONE" not in detail


# ------------------------- the units the boxes are expressed in are served


def test_the_cache_serves_the_units_per_em_of_the_program_it_parsed() -> None:
    """The unit→text scale must come from the SAME program pass the boxes
    came from: a capability's ``units_per_em`` was read at build time, and
    mixing it with boxes re-parsed from the current bytes would scale real
    ink by a stale em."""
    fixture, _ = _build_second_show_doc(offset=1.2)
    try:
        registry = DocumentFontRegistry(fixture.doc)
        show = replay_shows(fixture)[0]
        capability = registry.capability(fixture.page, show.font_resource or "")
        assert capability is not None and capability.cid is not None
        served = registry.glyph_boxes.units_per_em(fixture.doc, capability.cid)
        assert served == capability.cid.glyphs.units_per_em
        assert served is not None and 16 <= served <= 16384
        registry.glyph_boxes.clear()
        assert registry.glyph_boxes.units_per_em(fixture.doc, capability.cid) == served
    finally:
        fixture.doc.close()
