"""RED: a page whose visual frame cannot be derived must be REFUSED, not guessed.

``page_visual_frame`` (Task 15 P4-B2 slice 2) reconstructs MuPDF's own
user-space -> visual chain arithmetically.  On a page whose ``/CropBox`` does
not intersect its ``/MediaBox``, or whose ``/UserUnit`` is zero or negative,
that reconstruction has no ground truth to reproduce: MuPDF substitutes a
612x792 fallback page (MEASURED) while the arithmetic frame produces a
zero-area clip, so every halo, growth band and origin the engine derives from
it would be silently wrong (Codex adversarial review "sol", 2026-09-04,
finding F2).

The fix is a CLASS fix: the frame proves itself against ``page.rect`` before
it is returned and raises
:class:`~model.text_commit.transforms.UnsupportedPageGeometryError` when the
proof fails; every consumer turns that into its own layer's fail-closed
refusal (``PlanRejection`` / ``BindingFailure`` / ``VerificationFailure`` /
``None``), never an exception reaching the UI.

Ink-anchored throughout: the accepted shapes are proven by 72-dpi pixmap ink
(one device pixel == one visual point), and the refused shapes are proven to
render NO ink at all -- which is exactly why MuPDF's fallback box cannot be
mirrored here: there is no ink oracle to validate a mirrored frame against.
Ground truth measured on PyMuPDF 1.27.1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.verify as verify_module  # noqa: E402
from model.pdf_text_edit import _dict_space_to_visual  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    _origin_in_page_space,
    bind_source_text,
    replay_page,
)
from model.text_commit.plan import PlanRejection, prepare_plan  # noqa: E402
from model.text_commit.transforms import (  # noqa: E402
    UnsupportedPageGeometryError,
    page_visual_frame,
    read_rotate_literal,
)
from test_scripts.painter_matrix_fixtures import first_show, set_page_boxes  # noqa: E402
from test_scripts.stream_storage_fixtures import (  # noqa: E402
    REPLACEMENT,
    TARGET,
    open_case,
)
from test_scripts.type0_fixture_builder import build_identity_h_fixture  # noqa: E402

ROTATIONS = (0, 90, 180, 270)

# label -> (mediabox literal, cropbox literal, /UserUnit).  Each of these is a
# page whose clipped CropBox is EMPTY or whose /UserUnit is not a usable
# positive scale; MuPDF falls back to a 612x792 (or zero-area) page that the
# arithmetic frame cannot reproduce.
REFUSED_SHAPES: dict[str, tuple[tuple[float, ...] | None, tuple[float, ...] | None, str | None]] = {
    "disjoint cropbox": ((0, 0, 100, 100), (200, 200, 300, 300), None),
    "edge-touching cropbox": ((0, 0, 100, 100), (100, 100, 300, 300), None),
    "cropbox left of mediabox": ((0, 0, 595, 842), (-500, -500, -100, -100), None),
    "user unit zero": (None, None, "0"),
    "user unit negative": (None, None, "-2"),
}

REFUSED_CELLS = [(shape, rot) for shape in REFUSED_SHAPES for rot in ROTATIONS]

# Shapes the finding SUSPECTED were degenerate but which MuPDF handles
# consistently with the frame (MEASURED) -- they must keep working, or the
# gate is a false-safe on pages that render correctly today.
ACCEPTED_SHAPES: dict[str, tuple[tuple[float, ...] | None, tuple[float, ...] | None, str | None]] = {
    # MuPDF substitutes Letter for a zero-area MediaBox AT THE READER:
    # ``page.mediabox`` itself reads (0, 0, 612, 792), so the frame agrees.
    "zero-area mediabox": ((0, 0, 0, 0), None, None),
    "zero-width mediabox": ((0, 0, 0, 842), None, None),
    # No clamp at any size (MEASURED at 20,000 and 1,000,000 pt).
    "huge mediabox": ((0, 0, 20000, 20000), None, None),
    "enormous mediabox": ((0, 0, 1000000, 1000000), None, None),
}


def _degenerate_page(
    label: str, rotation: int, *, shapes: dict | None = None
) -> fitz.Document:
    """A blank document whose single page carries ``label``'s box shape."""
    mediabox, cropbox, user_unit = (shapes or REFUSED_SHAPES)[label]
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    xref = doc[0].xref
    for key, box in (("MediaBox", mediabox), ("CropBox", cropbox)):
        if box is not None:
            doc.xref_set_key(xref, key, "[" + " ".join(f"{v:g}" for v in box) + "]")
    if user_unit is not None:
        doc.xref_set_key(xref, "UserUnit", user_unit)
    if rotation:
        doc.xref_set_key(xref, "Rotate", str(rotation))
    return doc


def _shaped_tier0_doc(label: str, rotation: int) -> fitz.Document:
    """Fixture case (a) -- a real, bindable Tier 0 page -- reshaped."""
    doc = open_case("a")
    mediabox, cropbox, user_unit = REFUSED_SHAPES[label]
    xref = doc[0].xref
    for key, box in (("MediaBox", mediabox), ("CropBox", cropbox)):
        if box is not None:
            doc.xref_set_key(xref, key, "[" + " ".join(f"{v:g}" for v in box) + "]")
    if user_unit is not None:
        doc.xref_set_key(xref, "UserUnit", user_unit)
    if rotation:
        doc.xref_set_key(xref, "Rotate", str(rotation))
    return doc


def _ink_bbox(page: fitz.Page) -> tuple[int, int, int, int] | None:
    """Dark-pixel bounds at 72 dpi == visual points, or ``None`` for a blank
    rendering."""
    pix = page.get_pixmap(dpi=72, colorspace=fitz.csGRAY, alpha=False)
    table = bytes(1 if value < 200 else 0 for value in range(256))
    packed = bytes(pix.samples).translate(table)
    width, height = pix.width, pix.height
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        row = packed[y * width : (y + 1) * width]
        if 1 not in row:
            continue
        ys.append(y)
        xs.append(row.index(1))
        xs.append(width - 1 - row[::-1].index(1))
    if not xs:
        return None
    irect = tuple(pix.irect)
    return (
        irect[0] + min(xs),
        irect[1] + min(ys),
        irect[0] + max(xs) + 1,
        irect[1] + max(ys) + 1,
    )


@pytest.fixture(autouse=True)
def _font_metric_bboxes():
    """Same process-global pin as ``test_text_commit_visual_frame.py``."""
    prior = bool(fitz.TOOLS.set_small_glyph_heights())
    fitz.TOOLS.set_small_glyph_heights(False)
    try:
        yield
    finally:
        fitz.TOOLS.set_small_glyph_heights(prior)


# ------------------------------------------------- 1. the frame itself


@pytest.mark.parametrize(
    ("shape", "rotation"),
    REFUSED_CELLS,
    ids=[f"{s}@{r}" for s, r in REFUSED_CELLS],
)
def test_page_visual_frame_refuses_unprovable_geometry(shape, rotation):
    """The frame must never return a silently-wrong transform.

    MEASURED: with MediaBox ``[0 0 100 100]`` and CropBox
    ``[200 200 300 300]`` MuPDF renders a 612x792 page while the arithmetic
    clip is empty -- ``base`` would be ``(1, 0, 0, -1, -100, 200)`` over a
    0x0 page box.
    """
    doc = _degenerate_page(shape, rotation)
    try:
        with pytest.raises(UnsupportedPageGeometryError):
            page_visual_frame(doc[0])
    finally:
        doc.close()


@pytest.mark.parametrize("shape", sorted(ACCEPTED_SHAPES))
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_page_visual_frame_admits_the_shapes_mupdf_normalises(shape, rotation):
    """A zero-area or enormous MediaBox is NOT degenerate geometry.

    MEASURED: MuPDF substitutes Letter for a zero-area ``/MediaBox`` at the
    box reader (``page.mediabox`` itself reads ``(0, 0, 612, 792)``), and it
    clamps nothing at 20,000 or 1,000,000 pt -- so ``page.rect`` and the
    frame agree and the page must keep working.  Rejecting these would be a
    false-safe on pages that render correctly today.
    """
    doc = _degenerate_page(shape, rotation, shapes=ACCEPTED_SHAPES)
    try:
        page = doc[0]
        frame = page_visual_frame(page)
        expected = (
            (page.rect.height, page.rect.width)
            if rotation in (90, 270)
            else (page.rect.width, page.rect.height)
        )
        assert (frame.width0, frame.height0) == pytest.approx(expected)
        assert frame.user_unit == 1.0
    finally:
        doc.close()


def test_zero_area_mediabox_still_renders_ink_where_the_frame_says():
    """The ink oracle for the most surprising accepted shape.

    MEASURED: MediaBox ``[0 0 0 0]`` renders the authored glyph run at
    ``(72, 82, 119, 93)`` on the substituted Letter page -- geometry the
    frame reproduces, so a refusal here would break a working page.
    """
    fixture = build_identity_h_fixture()
    try:
        set_page_boxes(fixture, mediabox=(0, 0, 0, 0))
        page = fixture.doc[0]
        frame = page_visual_frame(page)
        assert tuple(frame.base) == tuple(page.transformation_matrix)
        ink = _ink_bbox(page)
        assert ink is not None, "premise: the substituted Letter page renders"
        origin = fitz.Point(*first_show(fixture).origin_user) * frame.visual
        assert ink[0] - 2.0 <= origin.x <= ink[2] + 2.0, (tuple(origin), ink)
        assert ink[1] - 2.0 <= origin.y <= ink[3] + 2.0, (tuple(origin), ink)
    finally:
        fixture.doc.close()


@pytest.mark.parametrize(
    "shape", ["disjoint cropbox", "edge-touching cropbox", "user unit zero"]
)
def test_refused_shapes_render_no_ink_at_all(shape):
    """Why the refused shapes are REFUSED rather than mirrored.

    MuPDF's fallback page renders NOTHING on any of them (MEASURED), so a
    mirrored frame could not be validated against the ink oracle every other
    cell in this suite is anchored on.  Mirroring is not merely riskier here;
    it is untestable.
    """
    fixture = build_identity_h_fixture()
    try:
        mediabox, cropbox, user_unit = REFUSED_SHAPES[shape]
        if mediabox is not None or cropbox is not None:
            set_page_boxes(fixture, mediabox=mediabox, cropbox=cropbox)
        if user_unit is not None:
            fixture.doc.xref_set_key(fixture.page.xref, "UserUnit", user_unit)
        assert _ink_bbox(fixture.doc[0]) is None
    finally:
        fixture.doc.close()


def test_exact_quarter_turn_rotate_values_are_admitted():
    """The values ``page.rotation`` can be trusted for: exact multiples of
    90, including the normalising ones (``-90`` -> 270, ``450`` -> 90)."""
    for literal, expected in (("0", 0), ("90", 90), ("-90", 270), ("450", 90)):
        fixture = build_identity_h_fixture()
        try:
            fixture.doc.xref_set_key(fixture.page.xref, "Rotate", literal)
            page = fixture.doc[0]
            assert page.rotation == expected, literal
            assert page_visual_frame(page).rotation == expected, literal
        finally:
            fixture.doc.close()


@pytest.mark.parametrize("literal", ["45", "89", "91", "135", "225", "90.5"])
def test_non_quarter_turn_rotate_is_refused(literal):
    """A ``/Rotate`` that is not an exact quarter turn is REFUSED.

    MEASURED (1.27.1) and the reason this gate exists at all: MuPDF renders
    such a page at the NEAREST quarter turn, while ``page.rotation`` AND
    ``page.rotation_matrix`` both report ``0``.  So the page draws rotated
    and every Python-level accessor says it is upright -- and for the
    values that round to 180 the page box is not even swapped, so the
    frame's own page-box self-check cannot see it either.  Only the raw
    ``/Rotate`` literal can.
    """
    fixture = build_identity_h_fixture()
    try:
        fixture.doc.xref_set_key(fixture.page.xref, "Rotate", literal)
        with pytest.raises(UnsupportedPageGeometryError):
            page_visual_frame(fixture.doc[0])
    finally:
        fixture.doc.close()


def test_rotate_135_renders_upside_down_while_the_accessors_say_upright():
    """The ink oracle behind the refusal above -- the measurement, not a
    claim: ``/Rotate 135`` places ink EXACTLY where ``/Rotate 180`` does,
    with ``page.rotation == 0`` and an identity ``rotation_matrix``."""
    inks = {}
    for literal in ("0", "135", "180"):
        fixture = build_identity_h_fixture()
        try:
            fixture.doc.xref_set_key(fixture.page.xref, "Rotate", literal)
            page = fixture.doc[0]
            inks[literal] = (
                _ink_bbox(page),
                page.rotation,
                tuple(page.rotation_matrix),
            )
        finally:
            fixture.doc.close()
    assert inks["135"][0] == inks["180"][0] != inks["0"][0]
    assert inks["135"][1] == 0, "page.rotation misreports the effective turn"
    assert inks["135"][2] == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def test_inherited_rotate_is_read_from_the_page_tree():
    """``/Rotate`` is inheritable, and an inherited non-quarter-turn value
    reproduces the same trap (MEASURED) -- so the reader walks ``/Parent``
    rather than reading the page dict alone."""
    for literal, expect_refusal in (("90", False), ("135", True)):
        fixture = build_identity_h_fixture()
        try:
            doc = fixture.doc
            page_xref = fixture.page.xref
            _, parent = doc.xref_get_key(page_xref, "Parent")
            doc.xref_set_key(page_xref, "Rotate", "null")
            doc.xref_set_key(int(parent.split()[0]), "Rotate", literal)
            assert read_rotate_literal(doc, page_xref) == pytest.approx(
                float(literal)
            )
            if expect_refusal:
                with pytest.raises(UnsupportedPageGeometryError):
                    page_visual_frame(doc[0])
            else:
                assert page_visual_frame(doc[0]).rotation == 90
        finally:
            fixture.doc.close()


# ------------------------------------------- 2. every consumer fails closed


@pytest.mark.parametrize(
    ("shape", "rotation"),
    REFUSED_CELLS,
    ids=[f"{s}@{r}" for s, r in REFUSED_CELLS],
)
def test_prepare_plan_rejects_unprovable_page_geometry(shape, rotation):
    """The gate that matters: no plan is ever built on a frame that cannot
    prove itself, and the refusal carries its own stable reason code."""
    doc = _shaped_tier0_doc(shape, rotation)
    try:
        page = doc[0]
        rejection = prepare_plan(
            doc,
            page,
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=None,
            target_bbox=None,
            registry=DocumentFontRegistry(doc),
        )
        assert isinstance(rejection, PlanRejection), rejection
        assert rejection.reason == RejectReason.PAGE_GEOMETRY_UNSUPPORTED
    finally:
        doc.close()


def test_the_same_page_without_the_degenerate_boxes_still_prepares():
    """Control: the gate refuses the GEOMETRY, not the fixture."""
    doc = open_case("a")
    try:
        plan = prepare_plan(
            doc,
            doc[0],
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=None,
            target_bbox=None,
            registry=DocumentFontRegistry(doc),
        )
        assert not isinstance(plan, PlanRejection), plan
    finally:
        doc.close()


def test_bind_source_text_fails_closed_on_unprovable_geometry():
    """``inspect.bind_source_text`` is reachable without the planner (the
    funnel scripts call it directly): it must refuse, not raise."""
    doc = _shaped_tier0_doc("disjoint cropbox", 90)
    try:
        page = doc[0]
        failure = bind_source_text(
            doc,
            page,
            target_text=TARGET,
            expected_origin=None,
            registry=DocumentFontRegistry(doc),
            resolved=None,
        )
        assert failure.reason == RejectReason.PAGE_GEOMETRY_UNSUPPORTED
    finally:
        doc.close()


def test_origin_in_page_space_returns_none_instead_of_raising():
    """``_origin_in_page_space`` is the per-candidate mapper inside the
    binding loop -- a candidate whose origin cannot be mapped is SKIPPED,
    never an exception out of the loop."""
    doc = _shaped_tier0_doc("disjoint cropbox", 0)
    try:
        page = doc[0]
        shows = [
            show
            for show in replay_page(doc, page).shows
            if show.decoded_bytes == TARGET.encode("latin-1")
        ]
        assert shows, "fixture: the target show must still replay"
        assert _origin_in_page_space(page, shows[0]) is None
    finally:
        doc.close()


def test_dict_space_to_visual_returns_none_instead_of_raising():
    """The model-boundary converter feeding ``_Tier0Target``: its caller's
    documented failure path is ``None`` (no Tier 0 target), so the converter
    hands back ``None`` rather than raising into the edit session."""
    doc = _degenerate_page("disjoint cropbox", 90)
    try:
        assert (
            _dict_space_to_visual(
                doc[0], fitz.Point(10.0, 10.0), fitz.Rect(0.0, 0.0, 20.0, 20.0)
            )
            is None
        )
    finally:
        doc.close()


def test_verify_fails_closed_when_the_frame_stops_being_provable(monkeypatch):
    """Belt and braces: ``prepare_plan``'s gate means verification can only
    meet a provable frame, but a verifier that met an unprovable one must
    return a ``VerificationFailure``, never raise through
    ``TieredCommitEngine.commit``'s BaseException boundary."""
    from model.text_commit.engine import TieredCommitEngine

    doc = open_case("a")
    try:
        page = doc[0]
        engine = TieredCommitEngine(doc)
        plan = prepare_plan(
            doc,
            page,
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=None,
            target_bbox=None,
            registry=engine.registry,
        )
        assert not isinstance(plan, PlanRejection), plan
        pre_state = verify_module.capture_page_state(doc, page, plan)

        def raising_frame(_page):
            raise UnsupportedPageGeometryError("injected by test")

        monkeypatch.setattr(verify_module, "page_visual_frame", raising_frame)
        result = verify_module.verify_tier0_commit(doc, page, plan, pre_state)
        assert isinstance(result, verify_module.VerificationFailure), result
        assert result.reason == RejectReason.PAGE_GEOMETRY_UNSUPPORTED
    finally:
        doc.close()


def test_tier1_growth_gates_run_before_the_frame_proof_and_must_fail_closed(
    monkeypatch,
):
    """Tier 1's growth gates run BEFORE ``_verify_patch_postconditions``.

    ``_growth_probe_failure`` -> ``_occupancy_failure`` ->
    ``_growth_rect_in_dict_space`` -> ``_visual_bbox_to_dict_space`` converts
    visual geometry on an ink-growth commit while the frame is still
    unproven, so the F2 gate at the top of ``_verify_patch_postconditions``
    is NOT the chokepoint "both tiers funnel through" for tier 1.  The proof
    has to be hoisted to the top of :func:`verify_tier1_commit` as well, or
    an unprovable frame raises straight through ``TieredCommitEngine``'s
    ``except BaseException`` boundary instead of reverting with a
    ``VerificationFailure``.
    """
    import dataclasses

    from model.text_commit.engine import TieredCommitEngine

    doc = open_case("a")
    try:
        page = doc[0]
        engine = TieredCommitEngine(doc)
        plan = prepare_plan(
            doc,
            page,
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=None,
            target_bbox=None,
            registry=engine.registry,
        )
        assert not isinstance(plan, PlanRejection), plan
        pre_state = verify_module.capture_page_state(doc, page, plan)

        # Force the ink-growth branch on: a verify box wider than the target
        # box is exactly what PreparedEdit.has_ink_growth tests for.
        x0, y0, x1, y1 = plan.target_bbox_page
        grown = dataclasses.replace(plan, verify_bbox_page=(x0, y0, x1 + 12.0, y1))
        assert grown.has_ink_growth

        def raising_frame(_page):
            raise UnsupportedPageGeometryError("injected by test")

        monkeypatch.setattr(verify_module, "page_visual_frame", raising_frame)
        result = verify_module.verify_tier1_commit(doc, page, grown, pre_state)
        assert isinstance(result, verify_module.VerificationFailure), result
        assert result.reason == RejectReason.PAGE_GEOMETRY_UNSUPPORTED
    finally:
        doc.close()
