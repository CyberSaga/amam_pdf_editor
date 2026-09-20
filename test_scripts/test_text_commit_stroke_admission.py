"""T16-4 Steps 7-8: the render-mode ladder and the mode-2 stroke-pen proof.

Red-first contract for the gate that admits ``render_mode == 2``
(fill-then-stroke, the Office "synthetic bold" shape) at Tier 0 when — and
only when — the stroke pen is PROVEN, and that names every other non-fill
mode in its own refusal (``plans/task16-4-tandem-bold-commit.md`` D7/D8,
§Fail-closed gates; ``plans/task16-4-glyph-coverage-expansion.md`` §4 S1,
which amends mode 3 to "refused until S7").

Two conventions here are deliberate:

* the reason codes are spelled as LITERALS, never as ``RejectReason``
  attributes (the ``dto.py`` note at the Task 12 P0-D block: a rename in
  ``dto.py`` must FAIL these tests, never silently follow them).  One
  constant-identity test pins the attribute names separately.
* the zero-mutation oracle is ``document_object_snapshot``, not
  ``doc.tobytes()``: ``tobytes`` is nondeterministic across calls in this
  repo (trailer ``/ID`` churn, see ``type0_fixture_builder``), and the
  per-xref serialization it replaces it with is strictly stronger — it also
  sees the resource and ExtGState objects these fixtures add.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, replay_page  # noqa: E402
from model.text_commit.patch import PatchSet, apply_patchset  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_plan,
    prepare_tier0_plan,
)
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from test_scripts.type0_fixture_builder import (  # noqa: E402
    document_object_snapshot,
)

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral

# Every fixture shows at 24 pt unless it says otherwise.  The size is
# load-bearing, not cosmetic: the pen bound is ``abs(w) * max(M, 1.0) >
# 0.5 * font_size``, and replay's DEFAULT pen (``w`` absent) is
# ``width=1.0``, ``miter_limit=10.0`` — ratio ``10 / (0.5 * size)``.  At
# 12 pt that default already exceeds the bound (the re-pinned
# ``2 Tr``-at-12 pt fixtures elsewhere refuse ``stroke_bound_too_large``);
# at 24 pt it passes with headroom, so these fixtures measure the gate
# under test rather than the default pen.
SIZE = 24.0


def _doc(stream: bytes, *, extgstate: str | None = None) -> fitz.Document:
    """One page whose only content is ``stream``, with /F1 = Helvetica.

    ``extgstate`` is the SERIALIZED ``/ExtGState`` sub-dictionary written
    into the page's ``/Resources`` (e.g. ``"<< /GS1 12 0 R >>"``).
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
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
    resources = f"<< /Font << /F1 {font_xref} 0 R >>"
    if extgstate is not None:
        resources += f" /ExtGState {extgstate}"
    resources += " >>"
    doc.xref_set_key(page.xref, "Resources", resources)
    return doc


def _gs_doc(body: str, *, stream: bytes, name: str = "GS1") -> fitz.Document:
    """``stream`` on a page whose ``/ExtGState /<name>`` is ``body``."""
    doc = _doc(stream)
    gs_xref = doc.get_new_xref()
    doc.update_object(gs_xref, body)
    page = doc[0]
    font_xref = page.get_fonts(full=True)[0][0]
    doc.xref_set_key(
        page.xref,
        "Resources",
        f"<< /Font << /F1 {font_xref} 0 R >> "
        f"/ExtGState << /{name} {gs_xref} 0 R >> >>",
    )
    return doc


def _show_stream(
    body: bytes, *, size: float = SIZE, prefix: bytes = b"", suffix: bytes = b""
) -> bytes:
    """``body`` is the text state written between ``Tf`` and ``Td``."""
    return (
        prefix
        + b"BT /F1 "
        + f"{size:g}".encode("ascii")
        + b" Tf "
        + body
        + b" 72 700 Td ("
        + TARGET.encode()
        + b") Tj ET"
        + suffix
    )


def _plan(doc: fitz.Document) -> PreparedEdit | PlanRejection:
    return prepare_tier0_plan(
        doc,
        doc[0],
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
    )


def _refuse(doc: fitz.Document) -> PlanRejection:
    """Plan, assert a refusal, and assert the document was not touched."""
    before = document_object_snapshot(doc)
    result = _plan(doc)
    assert isinstance(result, PlanRejection), result
    assert document_object_snapshot(doc) == before, (
        "a refusal must leave the document byte-identical"
    )
    return result


def _assert_gs_in_scope(doc: fitz.Document, name: str) -> None:
    """The target show really applied ``name`` -- without this, an
    "ExtGState changed nothing" assertion would pass just as well if replay
    never captured the name at all (the E8 branch under test would be
    vacuous)."""
    shows = [
        show
        for show in replay_page(doc, doc[0]).shows
        if show.decoded_bytes == TARGET.encode("latin-1")
    ]
    assert len(shows) == 1, f"expected 1 target show, got {len(shows)}"
    assert shows[0].extgstate_names == (name,), shows[0].extgstate_names


def _admit(doc: fitz.Document) -> PreparedEdit:
    result = _plan(doc)
    assert isinstance(result, PreparedEdit), result
    return result


# ------------------------------------------------------------ the headline


def test_mode_two_with_a_proven_pen_is_admitted() -> None:
    """The retargeted T16-4 goal: ``2 Tr`` with a provable pen is Tier 0.

    Refused ``unsupported_text_state`` before this slice — the single gate
    that made every Office synthetic-bold show uncommittable.
    """
    doc = _doc(_show_stream(b"2 Tr 1 w"))
    try:
        prepared = _admit(doc)
        # The splice covers the string operand only, so ``2 Tr`` and the
        # ``w`` operand (both before ``op_start``) survive by construction.
        stream = doc.xref_stream(doc[0].get_contents()[0])
        assert stream[prepared.replacement.start : prepared.replacement.end] == (
            b"(" + TARGET.encode() + b")"
        )
        assert b"2 Tr 1 w" in stream
    finally:
        doc.close()


def test_mode_zero_is_still_admitted() -> None:
    """Control: splitting the ladder must not disturb the fill mode."""
    doc = _doc(_show_stream(b""))
    try:
        _admit(doc)
    finally:
        doc.close()


# ------------------------------------------------ the named-mode refusals


@pytest.mark.parametrize(
    ("mode", "phrase"),
    [
        (1, "has no fill leg"),
        (3, "refused until S7"),
        (4, "clipping path"),
        (5, "clipping path"),
        (6, "clipping path"),
        (7, "clipping path"),
    ],
)
def test_non_admitted_render_modes_are_refused_by_name(
    mode: int, phrase: str
) -> None:
    """D7: each mode gets its OWN branch and names itself in the detail.

    A refusal that only happens to fall through a neighbouring branch is
    exactly what D7 forbids ("named, never incidental"), so the mode number
    is pinned in the detail alongside the code — and modes 4-7 additionally
    state the hazard that separates them from 1 and 3: they add the glyph
    outlines to the CLIPPING PATH, a persistent state effect on everything
    painted afterwards.
    """
    doc = _doc(_show_stream(f"{mode:d} Tr 1 w".encode("ascii")))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "unsupported_text_state"
        assert f"render_mode={mode}" in rejection.detail
        assert phrase in rejection.detail
    finally:
        doc.close()


def test_an_undefined_render_mode_operand_is_refused_by_number() -> None:
    """Replay records ``Tr``'s operand as a plain int, so a malformed
    stream can present a mode outside 0-7.  The ladder's last rung catches
    it by number -- the rung most likely to look dead and be dropped."""
    doc = _doc(_show_stream(b"9 Tr 1 w"))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "unsupported_text_state"
        assert "render_mode=9" in rejection.detail
        assert "not a defined" in rejection.detail
    finally:
        doc.close()


def test_nonzero_rise_is_refused_before_the_pen_is_read() -> None:
    """The rise gate survives the split of the old combined condition: a
    raised baseline refuses even when the pen itself would prove."""
    doc = _doc(_show_stream(b"2 Tr 1 w 3 Ts"))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "unsupported_text_state"
        assert "rise=3.0" in rejection.detail
    finally:
        doc.close()


# --------------------------------------------------------- the pen proof


def test_zero_pen_width_is_unproven() -> None:
    """``0 w`` renders device-thinnest, which a half-pen bound understates,
    so the pen is not provable and the show is refused."""
    doc = _doc(_show_stream(b"2 Tr 0 w"))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
        assert "render_mode=2" in rejection.detail
    finally:
        doc.close()


def test_pen_wider_than_half_the_font_size_is_refused() -> None:
    """``abs(w) * max(M, 1.0) > 0.5 * font_size`` refuses: a halo that fat
    leaves V0d proving nothing.  The detail carries the ratio."""
    doc = _doc(_show_stream(b"2 Tr 3 w"))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_too_large"
        # 3 * 10 / (0.5 * 24) = 2.5
        assert "2.5" in rejection.detail
    finally:
        doc.close()


def test_the_miter_limit_participates_in_the_bound() -> None:
    """The bound is ``w * max(M, 1.0)``, not ``w`` alone: the same pen
    admits under ``10 M`` and refuses under ``25 M``."""
    admitted = _doc(_show_stream(b"2 Tr 0.5 w 10 M"))
    refused = _doc(_show_stream(b"2 Tr 0.5 w 25 M"))
    try:
        _admit(admitted)  # 0.5 * 10 = 5 <= 12
        rejection = _refuse(refused)  # 0.5 * 25 = 12.5 > 12
        assert rejection.reason == "stroke_bound_too_large"
    finally:
        admitted.close()
        refused.close()


def test_the_documented_fixture_ratio_passes() -> None:
    """The office fixture's own shape: pen ``0.40114`` at ``14.04`` pt,
    ratio ``0.40114 * 10 / (0.5 * 14.04) == 0.571`` — 43% headroom
    (§Fail-closed gates).  Pinned so nobody tightens the bound past the
    only document that motivates the feature."""
    doc = _doc(_show_stream(b"2 Tr 0.40114 w", size=14.04))
    try:
        _admit(doc)
    finally:
        doc.close()


# ------------------------------------------------------------- ExtGState


def test_extgstate_without_pen_keys_leaves_the_pen_unchanged() -> None:
    """E8's branch, and the fixture's exclusive path: an ExtGState that
    declares no ``/LW``, ``/LJ`` or ``/ML`` leaves the pen exactly as the
    stream set it.  A blanket "any gs in scope => unprovable" rule would
    silently kill the feature."""
    doc = _gs_doc(
        "<< /Type /ExtGState /BM /Normal /ca 1 >>",
        stream=_show_stream(b"2 Tr 1 w", prefix=b"q /GS1 gs ", suffix=b" Q"),
    )
    try:
        _assert_gs_in_scope(doc, "GS1")
        prepared = _admit(doc)
        assert _outset_per_side(prepared, _mode0_twin_bbox()) == pytest.approx(
            0.5, abs=1e-6
        )
    finally:
        doc.close()


def test_extgstate_line_width_before_a_w_operand_does_not_survive_it() -> None:
    """RE-PINNED (T16-4 S1 review H1) — old name/outcome below.

    This test was ``test_extgstate_line_width_is_applied`` and pinned an
    outset of ``0.2``: ``/LW 0.4`` was applied over the stream's ``1 w``
    *regardless of which executed last*.  The fixture's ``gs`` runs in the
    ``q`` prefix, i.e. BEFORE the ``1 w`` in the body, so the renderer's pen
    is the ``w``'s 1.0 and the honest outset is ``0.5``.  ``/LW`` applied
    over a LATER ``w`` was the defect: it under-stated the pen, defeating
    the ``stroke_bound_too_large`` ceiling and shrinking the duplicate-gate
    outset.  The applied-``/LW`` coverage the old pin carried now lives in
    ``test_w_before_extgstate_proves_the_extgstate_pen``, which orders the
    two the other way and still measures ``0.2``.
    """
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 0.4 >>",
        stream=_show_stream(b"2 Tr 1 w", prefix=b"q /GS1 gs ", suffix=b" Q"),
    )
    try:
        _assert_gs_in_scope(doc, "GS1")
        prepared = _admit(doc)
        assert _outset_per_side(prepared, _mode0_twin_bbox()) == pytest.approx(
            0.5, abs=1e-6
        )
    finally:
        doc.close()


def test_extgstate_line_width_over_the_bound_before_a_w_is_overwritten() -> None:
    """RE-PINNED (T16-4 S1 review H1) — old name/outcome below.

    This test was ``test_extgstate_line_width_over_the_bound_is_refused``
    and asserted ``stroke_bound_too_large`` for ``/LW 3`` at 24 pt.  Its
    ``gs`` runs before the body's ``1 w``, so under the ordered pen proof
    the ``w`` overwrites ``/LW`` and the pen really is 1.0 — ``1 * 10 <=
    0.5 * 24`` admits.  The over-the-bound refusal it used to carry moved
    to ``test_extgstate_line_width_over_the_bound_after_a_w_is_refused``,
    where the ``gs`` runs LAST and the fat ``/LW`` is the rendered pen.
    """
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 3 >>",
        stream=_show_stream(b"2 Tr 1 w", prefix=b"q /GS1 gs ", suffix=b" Q"),
    )
    try:
        _assert_gs_in_scope(doc, "GS1")
        prepared = _admit(doc)
        assert _outset_per_side(prepared, _mode0_twin_bbox()) == pytest.approx(
            0.5, abs=1e-6
        )
    finally:
        doc.close()


def test_extgstate_line_width_over_the_bound_after_a_w_is_refused() -> None:
    """``/LW 3`` at 24 pt, applied LAST: ``3 * 10 > 0.5 * 24``.

    Carries the refusal the re-pinned test above used to assert, on the
    operator order that actually renders the fat pen.
    """
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 3 >>", stream=_show_stream(b"2 Tr 1 w /GS1 gs")
    )
    try:
        _assert_gs_in_scope(doc, "GS1")
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_too_large"
    finally:
        doc.close()


def test_extgstate_pen_key_of_the_wrong_type_is_unproven() -> None:
    """``/LW true`` is not a number.  ``bool`` is an ``int`` subclass in
    Python, so a naive numeric check would read it as width ``1.0``."""
    doc = _gs_doc(
        "<< /Type /ExtGState /LW true >>",
        stream=_show_stream(b"2 Tr 1 w", prefix=b"q /GS1 gs ", suffix=b" Q"),
    )
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
    finally:
        doc.close()


def test_dangling_extgstate_reference_is_unproven() -> None:
    """The resource NAMES an object that cannot be read: unprovable."""
    doc = _doc(
        _show_stream(b"2 Tr 1 w", prefix=b"q /GS1 gs ", suffix=b" Q"),
        extgstate="<< /GS1 9999 0 R >>",
    )
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
    finally:
        doc.close()


def test_extgstate_name_absent_from_the_resource_dict_is_unproven() -> None:
    """The stream applies ``/GS2``; the page declares only ``/GS1``.  What
    that ``gs`` did to the pen is not knowable, so the pen is not proven."""
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 0.4 >>",
        stream=_show_stream(b"2 Tr 1 w", prefix=b"q /GS2 gs ", suffix=b" Q"),
    )
    try:
        _assert_gs_in_scope(doc, "GS2")
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
    finally:
        doc.close()


def test_no_extgstate_resource_dict_at_all_is_unproven() -> None:
    """A ``gs`` on a page with no ``/ExtGState`` resource dict: same."""
    doc = _doc(_show_stream(b"2 Tr 1 w", prefix=b"q /GS1 gs ", suffix=b" Q"))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
    finally:
        doc.close()


# ------------------------------------------------ the honest fallback bbox


def _mode0_twin_bbox() -> tuple[float, float, float, float]:
    """The fallback ``target_bbox_page`` of the mode-0 twin of every
    fixture here: same page, same origin, same size, no stroke."""
    doc = _doc(_show_stream(b""))
    try:
        return _admit(doc).target_bbox_page
    finally:
        doc.close()


def _outset_per_side(
    prepared: PreparedEdit, base: tuple[float, float, float, float]
) -> float:
    """The one outset ``prepared``'s bbox grew by on all four sides."""
    x0, y0, x1, y1 = prepared.target_bbox_page
    bx0, by0, bx1, by1 = base
    grown = (bx0 - x0, by0 - y0, x1 - bx1, y1 - by1)
    assert grown[0] == pytest.approx(grown[1], abs=1e-9)
    assert grown[0] == pytest.approx(grown[2], abs=1e-9)
    assert grown[0] == pytest.approx(grown[3], abs=1e-9)
    return grown[0]


def test_the_fallback_bbox_grows_by_the_honest_outset_only() -> None:
    """D4: the fallback ``target_bbox`` (the V0d halo) grows by the HONEST
    bound ``w/2 * sigma_max`` — never the miter-factored conservative one,
    which at ``M = 10`` would be ten times as wide and erode V0d's exempt
    region (E7: the fixture's own miter bound already exceeds the 2.0 pt
    halo margin)."""
    doc = _doc(_show_stream(b"2 Tr 1 w"))
    try:
        assert _outset_per_side(_admit(doc), _mode0_twin_bbox()) == pytest.approx(
            0.5, abs=1e-6
        )
    finally:
        doc.close()


def test_the_fallback_bbox_outset_follows_the_w_operand() -> None:
    """Replay's default pen is ``1.0``; a fixture that never writes ``w``
    would prove nothing about reading the operator.  ``0.5 w`` grows the
    fallback by ``0.25``, not ``0.5``."""
    doc = _doc(_show_stream(b"2 Tr 0.5 w"))
    try:
        assert _outset_per_side(_admit(doc), _mode0_twin_bbox()) == pytest.approx(
            0.25, abs=1e-6
        )
    finally:
        doc.close()


def test_a_caller_supplied_target_bbox_is_not_outset() -> None:
    """Only the FALLBACK is grown: a caller-supplied bbox already reflects
    rendered ink (it comes from the extractor), so outsetting it again
    would double-count the pen.

    The supplied box is the mode-0 twin's OWN fallback bbox, so this test
    and ``test_the_fallback_bbox_grows_by_the_honest_outset_only`` differ in
    exactly one variable: same page, same show, same box -- one supplied,
    one derived.  A box picked at random elsewhere on the page would pass
    even if the outset were unreachable for an unrelated reason.
    """
    doc = _doc(_show_stream(b"2 Tr 1 w"))
    try:
        supplied = _mode0_twin_bbox()
        prepared = prepare_tier0_plan(
            doc,
            doc[0],
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=None,
            target_bbox=supplied,
            registry=DocumentFontRegistry(doc),
        )
        assert isinstance(prepared, PreparedEdit), prepared
        assert prepared.target_bbox_page == supplied
    finally:
        doc.close()


# ------------------------------------------------------------- the codes


def test_the_two_new_reason_codes_exist_with_their_wire_strings() -> None:
    """Both are NEW names (``dto.py`` forbids reusing a code that already
    has emission sites); the literals above are the wire contract."""
    assert RejectReason.STROKE_BOUND_UNPROVEN == "stroke_bound_unproven"
    assert RejectReason.STROKE_BOUND_TOO_LARGE == "stroke_bound_too_large"


# ============================== T16-4 Step 9: the duplicate-painter gate ===
#
# D4's CONSERVATIVE site.  ``target_bbox`` above is the honest bound, where
# an over-bound erodes V0d's halo; here the direction of error is the
# opposite one — an UNDER-bound admits a same-bytes twin that paints over
# the edit and leaves a pixel-identical ghost.  So this bound carries the
# miter factor ``max(M, 1.0)`` the honest one must never carry.
#
# These fixtures are SIMPLE-font on purpose.  ``duplicate_source_painter_
# detail``'s exact glyph-ink arm needs a CID target, and
# ``_painter_glyph_ink`` refuses every non-fill render mode (that refusal is
# S3's, deliberately untouched here), so a CID mode-2 target returns
# "cannot prove target placement" before any twin is measured — a refusal,
# not the false safe Step 9 is about.  A Helvetica target skips the exact
# arm entirely and lands on ``_painter_core_quad`` -> ``target_core``, which
# is the branch the conservative outset has to reach.

# Visual space (the frame flips y on this 842-high page), so the FIRST
# painter is addressed and the twin never binds.
_TARGET_ORIGIN = (72.0, 842.0 - 700.0)


def _twin_doc(body: bytes, *, gap: float) -> fitz.Document:
    """The target at ``(72, 700)`` plus a same-bytes twin ``gap`` pt clear.

    ``body`` is the text state of the TARGET only: the twin is reset to
    ``0 Tr`` before it paints, so the fixture states its own render mode
    instead of inheriting the target's (render mode is graphics state and
    persists across shows).

    ``gap`` is the horizontal clearance between the target's un-outset
    advance core and the twin's, measured with MuPDF's own base-14 text
    length rather than with the planner's advance — an independent oracle
    for the one number the whole comparison turns on.
    """
    advance = fitz.get_text_length(TARGET, fontname="helv", fontsize=SIZE)
    twin_x = 72.0 + advance + gap
    stream = (
        b"BT /F1 "
        + f"{SIZE:g}".encode("ascii")
        + b" Tf "
        + body
        + b" 1 0 0 1 72 700 Tm ("
        + TARGET.encode()
        + b") Tj 0 Tr 1 0 0 1 "
        + f"{twin_x:.4f}".encode("ascii")
        + b" 700 Tm ("
        + TARGET.encode()
        + b") Tj ET"
    )
    return _doc(stream)


def _plan_twin(doc: fitz.Document) -> PreparedEdit | PlanRejection:
    return prepare_tier0_plan(
        doc,
        doc[0],
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=_TARGET_ORIGIN,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
    )


def _refuse_twin(doc: fitz.Document) -> PlanRejection:
    before = document_object_snapshot(doc)
    result = _plan_twin(doc)
    assert isinstance(result, PlanRejection), result
    assert document_object_snapshot(doc) == before, (
        "a refusal must leave the document byte-identical"
    )
    return result


def _admit_twin(doc: fitz.Document) -> PreparedEdit:
    result = _plan_twin(doc)
    assert isinstance(result, PreparedEdit), result
    return result


def test_a_stroked_target_core_is_outset_before_the_twin_overlap_test() -> None:
    """The false safe Step 9 closes, demonstrated then fixed.

    The twin's core sits 0.1 pt clear of the target's UN-outset advance
    core, so the un-outset comparison calls the two disjoint and ADMITS —
    while the target is stroked with a ``1 w`` pen whose ink reaches 0.5 pt
    past that core on a plain join and, on an acute miter vertex, 4.54x
    further (E6).  Either way the twin is painted on top of the edit.

    Outsetting ``target_core`` by the CONSERVATIVE bound
    (``w/2 * max(M, 1.0) * sigma_max`` = ``0.5 * 10 * 1`` = 5.0 pt here)
    makes the overlap 4.9 pt and the gate refuses — with the EXISTING
    string, no new code and no new reason: the outset moves the boundary,
    it does not add a verdict.
    """
    doc = _twin_doc(b"2 Tr 1 w", gap=0.1)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter overlaps target core by "
            "4.900pt x 14.400pt"
        ), rejection.detail
    finally:
        doc.close()


def test_a_fill_mode_target_core_is_not_outset() -> None:
    """The control that makes the test above about the STROKE.

    Byte for byte the same geometry with no ``2 Tr``: no pen is proven, no
    outset is applied, and the 0.1 pt clearance still admits exactly as it
    does today.  Without this, a bound that outset every target's core
    would pass the stroked test and silently refuse half the corpus.
    """
    doc = _twin_doc(b"", gap=0.1)
    try:
        _admit_twin(doc)
    finally:
        doc.close()


def test_a_fill_mode_target_keeps_todays_core_overlap_string() -> None:
    """The other half of the control: a fill-mode target whose twin really
    does overlap still refuses with the same string and the same measured
    numbers it produced before this slice (1.0 pt of overlap, 0.6 em of
    core height)."""
    doc = _twin_doc(b"", gap=-1.0)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter overlaps target core by "
            "1.000pt x 14.400pt"
        ), rejection.detail
    finally:
        doc.close()


def test_miter_factor_is_load_bearing_at_the_duplicate_gate() -> None:
    """Half the pen is NOT the bound: E6's ``M`` overshoots it by 4.54x.

    The twin sits 2.0 pt clear of the un-outset core.  Half-pen alone
    (``1 w`` -> 0.5 pt) calls that disjoint; the miter-factored bound
    (``0.5 * max(M, 1.0)`` with ``M`` = 10 -> 5.0 pt) refuses by 3.0 pt.

    2.0 pt is chosen so the difference is not academic: at this pen E6's
    worst measured miter vertex paints 4.54 x 0.5 = 2.27 pt past the core,
    i.e. PAST the twin — real ink, on the shape the half-pen bound would
    have admitted.  ``M`` = 10 is the pinned factor, an order of magnitude
    above that 4.54x, which is why the plan keeps ``max(miterlimit, 1.0)``
    rather than a constant calibrated on a probe of ``H`` (1.00x).
    """
    doc = _twin_doc(b"2 Tr 1 w 10 M", gap=2.0)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter overlaps target core by "
            "3.000pt x 14.400pt"
        ), rejection.detail
    finally:
        doc.close()


def test_a_round_join_collapses_the_bound_back_to_half_the_pen() -> None:
    """The same pen and the same 2.0 pt clearance under ``1 j``.

    A round join has no miter to overshoot (E6 measured round ``A``/``V``
    within one rendering pixel of exactly half-pen), so the factor is 1.0,
    the outset is 0.5 pt, and this twin is provably clear.  Pinned so the
    conservative bound cannot quietly become "always multiply by M" — that
    would refuse every round-joined stroked page for nothing.
    """
    doc = _twin_doc(b"2 Tr 1 w 10 M 1 j", gap=2.0)
    try:
        _admit_twin(doc)
    finally:
        doc.close()


# =================================== T16-4 Step 10: the Tier 1 fence ======


SHORTER = "Price 202"  # one digit narrower: forces ADVANCE_MISMATCH


def test_a_mode_two_target_is_refused_at_tier_1() -> None:
    """Tier 0's mode-2 admission does not extend to Tier 1.

    Tier 0 splices the string operand alone, so ``2 Tr`` and the ``w``
    operand — both before ``op_start`` — survive by construction, and the
    honest outset above bounds the stroked ink for V0d.  Tier 1 proves
    neither: it transplants the whole operator and verifies through
    ``_grown_verify_bbox`` and ``background_bbox_page``, two boxes derived
    from the metric quad with no pen term at all, over ink that escapes
    them by the pen.  The fence refuses instead of widening them.
    """
    doc = _doc(_show_stream(b"2 Tr 1 w"))
    try:
        before = document_object_snapshot(doc)
        tier0 = prepare_tier0_plan(
            doc,
            doc[0],
            target_text=TARGET,
            replacement_text=SHORTER,
            expected_origin=None,
            target_bbox=None,
            registry=DocumentFontRegistry(doc),
        )
        assert isinstance(tier0, PlanRejection), tier0
        assert tier0.reason == "advance_mismatch", tier0.reason
        result = prepare_plan(
            doc,
            doc[0],
            target_text=TARGET,
            replacement_text=SHORTER,
            expected_origin=None,
            target_bbox=None,
            registry=DocumentFontRegistry(doc),
            max_tier=1,
        )
        assert isinstance(result, PlanRejection), (
            "Tier 1 built a "
            f"{type(result).__name__} at tier {getattr(result, 'tier', None)!r} "
            "for a render_mode=2 target"
        )
        assert result.reason == "unsupported_text_state"
        assert "render_mode=2" in result.detail
        assert document_object_snapshot(doc) == before, (
            "a refusal must leave the document byte-identical"
        )
    finally:
        doc.close()


def test_a_fill_mode_target_still_escalates_to_tier_1() -> None:
    """The fence is keyed on the render mode, not on the escalation.

    Same page, same advance mismatch, no ``2 Tr``: Tier 1 still builds its
    candidate.  A blanket refusal at the top of ``_build_tier1`` would pass
    the test above and silently delete the tier.
    """
    doc = _doc(_show_stream(b""))
    try:
        result = prepare_plan(
            doc,
            doc[0],
            target_text=TARGET,
            replacement_text=SHORTER,
            expected_origin=None,
            target_bbox=None,
            registry=DocumentFontRegistry(doc),
            max_tier=1,
        )
        assert isinstance(result, PreparedEdit), result
        assert result.tier == CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    finally:
        doc.close()


# ============================ T16-4 Step 11: end to end, Phase A ==========
#
# Everything above stops at ``prepare``.  This section drives the PRODUCTION
# entry the controller uses -- ``TieredCommitEngine.prepare`` then
# ``.commit`` -- through a mode-2 page and proves, on the committed
# document, the four facts Step 11 names: the bold operators survive at
# their original offsets, the rendered stroke outset is unchanged, the
# preview token is the commit token, and the patch reverts byte-identically.
#
# ``E2E_REPLACEMENT`` is deliberately NOT the module's ``REPLACEMENT``:
# "Price 2024" -> "Price 2054" changes the *third* digit, so every extreme
# of the rendered ink box (left ``P``, right ``4``, the round letters that
# overshoot the baseline, the ``P``/``i`` tops) is painted by an UNCHANGED
# glyph.  The outset comparison then measures the pen, not the difference
# between two digit outlines.  Both strings are advance-neutral in helv
# (every digit is 556/1000).

E2E_REPLACEMENT = "Price 2054"
E2E_DOWNSTREAM = "Downstream line stays"

# Half the ``1 w`` pen is 0.5 pt; at zoom 64 that is 32 device pixels.
_ZOOM = 64.0
_HALF_PEN_PX = 32


def _e2e_stream(body: bytes) -> bytes:
    """The target show with text state ``body``, plus a mode-0 neighbour.

    The second show is what makes V0c's ``nontarget_geometry_unchanged``
    gate non-vacuous: with a single show on the page the non-target origin
    set is empty and the comparison proves nothing.  It is reset to
    ``0 Tr`` first -- render mode is graphics state and would otherwise be
    inherited from the target.
    """
    return (
        b"BT /F1 "
        + f"{SIZE:g}".encode("ascii")
        + b" Tf "
        + body
        + b" 72 700 Td ("
        + TARGET.encode()
        + b") Tj 0 Tr 0 -40 Td ("
        + E2E_DOWNSTREAM.encode()
        + b") Tj ET"
    )


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _engine_prepare(
    doc: fitz.Document,
    engine: TieredCommitEngine,
    *,
    replacement: str = E2E_REPLACEMENT,
    supply_geometry: bool = False,
) -> PreparedEdit | PlanRejection:
    """Prepare through the production engine entry, as the controller does."""
    page = doc[0]
    origin: tuple[float, float] | None = None
    bbox: tuple[float, float, float, float] | None = None
    if supply_geometry:
        span = _span(page, TARGET)
        origin = tuple(float(v) for v in span["origin"])  # type: ignore[assignment]
        bbox = tuple(float(v) for v in span["bbox"])  # type: ignore[assignment]
    return engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=origin,
        target_bbox=bbox,
    )


def test_a_mode_two_page_commits_at_tier0_keeping_tr_and_w_at_their_offsets() -> None:
    """The "bold silently vanishes" regression pin, at the byte level.

    D2's whole safety argument is that ``2 Tr`` and the ``w`` operand sit
    BEFORE ``op_start``, so a string-operand splice cannot touch them.  This
    proves it on the COMMITTED document and at fixed OFFSETS -- a substring
    search would still pass if the operators had moved, and moving them is
    exactly what a whole-operator rewrite would do.

    The fact itself is already proven inside the engine by V0a
    (``verify.py`` ~617-642 re-diffs ``post[:start]`` against ``pre[:start]``
    index-aligned, and every non-target stream whole), which is why this
    slice adds NO new verify.py arm: the property is asserted here and the
    V0a certificate it comes from is asserted alongside it.
    """
    doc = _doc(_e2e_stream(b"2 Tr 1 w"))
    try:
        page = doc[0]
        stream_xref = page.get_contents()[0]
        before = doc.xref_stream(stream_xref)
        tr_at = before.index(b"2 Tr")
        w_at = before.index(b"1 w")

        engine = TieredCommitEngine(doc)
        prepared = _engine_prepare(doc, engine)
        assert isinstance(prepared, PreparedEdit), prepared
        assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert prepared.splice_kind == "string_token"

        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.COMMITTED, outcome
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        # The V0a certificate this test declines to duplicate in verify.py.
        assert "stream_identity_outside_range" in outcome.verified_properties
        assert "target_operator_reproven" in outcome.verified_properties

        after = doc.xref_stream(stream_xref)
        assert after != before, "the commit must actually have changed the stream"
        assert after[tr_at : tr_at + 4] == b"2 Tr", "the render mode moved or vanished"
        assert after[w_at : w_at + 3] == b"1 w", "the pen operand moved or vanished"
        # Spelled once more as a whole prefix: everything before the splice
        # is byte-identical AND index-aligned, so no earlier operator moved.
        assert after[: prepared.replacement.start] == before[: prepared.replacement.start]
        assert E2E_REPLACEMENT in doc[0].get_text()
    finally:
        doc.close()


def _pixel_doc(body: bytes) -> fitz.Document:
    """A SMALL page carrying the target show alone, for the raster probe.

    Two deliberate differences from :func:`_e2e_stream`'s page.  It is
    140x40 pt, not 595x842: at zoom 64 the full page would be a 2-gigapixel
    pixmap, and the measurement needs only the glyph run.  And it carries no
    neighbour show, so the tight ink bbox belongs to the target alone --
    with the downstream line on the page the right and bottom extremes are
    ITS ink, identical in both documents, and the measured outset collapses
    to zero on those sides for a reason that has nothing to do with the pen.
    V0c's non-target gate is exercised by the neighbour-bearing page in
    :func:`test_a_mode_two_page_commits_at_tier0_keeping_tr_and_w_at_their_offsets`.
    """
    doc = fitz.open()
    page = doc.new_page(width=140, height=40)
    stream = (
        b"BT /F1 "
        + f"{SIZE:g}".encode("ascii")
        + b" Tf "
        + body
        + b" 10 12 Td ("
        + TARGET.encode()
        + b") Tj ET"
    )
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


def _ink_bbox_and_digest(
    doc: fitz.Document,
) -> tuple[tuple[int, int, int, int], str]:
    """Tight pixel bbox of all non-white ink at ``_ZOOM``, AA DISABLED.

    Anti-aliasing is a process-global MuPDF setting, so it is restored in a
    ``finally`` -- leaking AA-off would change the raster of every other
    test in the suite, V0d's own pins included.  Greyscale with AA off is
    strictly two-valued (0 or 255), so ``lstrip``/``rstrip`` of ``b"\\xff"``
    finds each row's ink extent at C speed instead of per-pixel Python.

    The digest is returned alongside so a caller can prove the raster
    actually CHANGED across a commit: an "outset unchanged" assertion is
    satisfied just as well by a page that did not move at all.
    """
    previous = fitz.mupdf.ll_fz_aa_level()
    fitz.TOOLS.set_aa_level(0)
    try:
        pix = doc[0].get_pixmap(
            matrix=fitz.Matrix(_ZOOM, _ZOOM), colorspace=fitz.csGRAY, alpha=False
        )
    finally:
        fitz.TOOLS.set_aa_level(previous)
    data = pix.samples
    stride, width, height = pix.stride, pix.width, pix.height
    x0, y0, x1, y1 = width, height, -1, -1
    for y in range(height):
        row = data[y * stride : y * stride + width]
        left = row.lstrip(b"\xff")
        if not left:
            continue
        x0 = min(x0, width - len(left))
        x1 = max(x1, len(row.rstrip(b"\xff")) - 1)
        y0 = min(y0, y)
        y1 = max(y1, y)
    assert x1 >= 0, "the page rendered no ink at all"
    return (x0, y0, x1, y1), hashlib.sha256(data).hexdigest()


def _outset_px(
    stroked: tuple[int, int, int, int], filled: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """How far the stroked ink reaches past its ``0 Tr`` twin, per side."""
    return (
        filled[0] - stroked[0],
        filled[1] - stroked[1],
        stroked[2] - filled[2],
        stroked[3] - filled[3],
    )


def test_the_rendered_stroke_outset_is_unchanged_by_the_commit() -> None:
    """The pixel-level half of the regression pin (Step 11).

    Byte identity of ``2 Tr``/``w`` proves the OPERATORS survived; it does
    not prove the rasterizer still paints the stroke.  So the stroked page
    is measured against a ``0 Tr`` twin -- same page, same font, same
    origin, same size -- before and after both are committed with the same
    advance-neutral replacement, and the per-side outset must be the same
    four numbers.

    Two guards keep it from passing vacuously: the outset must be NON-ZERO
    on every side both times (a vanished stroke gives ``0 == 0``), and the
    stroked page's raster digest must CHANGE across the commit (an edit
    that never landed leaves every number identical for the wrong reason).

    The measured outset is ``(31, 32, 33, 32)``: half of a ``1 w`` pen is
    0.5 pt = 32 px at zoom 64, +-1 px of grid quantization on the left and
    the miter vertex of the final glyph on the right (plan E6 records the
    same one-pixel quantization floor at zoom 48).
    """
    stroked = _pixel_doc(b"2 Tr 1 w")
    filled = _pixel_doc(b"")
    try:
        pre_stroked, pre_digest = _ink_bbox_and_digest(stroked)
        pre_filled, _ = _ink_bbox_and_digest(filled)
        outset_pre = _outset_px(pre_stroked, pre_filled)
        assert all(value > 0 for value in outset_pre), outset_pre
        assert all(abs(value - _HALF_PEN_PX) <= 1 for value in outset_pre), outset_pre

        for doc in (stroked, filled):
            engine = TieredCommitEngine(doc)
            prepared = _engine_prepare(doc, engine)
            assert isinstance(prepared, PreparedEdit), prepared
            outcome = engine.commit(prepared)
            assert outcome.status is CommitStatus.COMMITTED, outcome

        post_stroked, post_digest = _ink_bbox_and_digest(stroked)
        post_filled, _ = _ink_bbox_and_digest(filled)
        assert post_digest != pre_digest, (
            "the stroked page's raster did not change: the commit did not land, "
            "so an unchanged outset proves nothing"
        )
        outset_post = _outset_px(post_stroked, post_filled)
        assert all(value > 0 for value in outset_post), outset_post
        assert outset_post == outset_pre, (outset_pre, outset_post)
    finally:
        stroked.close()
        filled.close()


def test_the_preview_token_is_the_commit_token_for_a_mode_two_target() -> None:
    """Cross-slice invariant 2: preview and commit consume ONE candidate.

    The preview renderer plans on a session snapshot and the engine plans on
    the live document; if the mode-2 admission read anything that differs
    between the two (a pen resolved from a document handle, say), the tokens
    would diverge and the controller's cache would miss silently -- falling
    back to legacy, which is exactly the path that drops the stroke leg.

    Order matters: the token folds the page fingerprint, and committing
    moves it, so the preview token is taken BEFORE anything is applied.
    """
    doc = _doc(_e2e_stream(b"2 Tr 1 w"))
    try:
        page = doc[0]
        span = _span(page, TARGET)
        bbox = tuple(float(value) for value in span["bbox"])
        origin = tuple(float(value) for value in span["origin"])

        session = open_preview_session(doc, 0, "stroke-e2e")
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        try:
            result = renderer.render(
                PlanPreviewRequest(
                    session_key="stroke-e2e",
                    generation=1,
                    target_text=TARGET,
                    replacement_text=E2E_REPLACEMENT,
                    expected_origin=origin,
                    target_bbox=bbox,
                    clip_rect=bbox,
                    render_scale=1.0,
                )
            )
        finally:
            renderer.close()
        assert result.reject_reason is None, result.reject_reason
        assert result.plan_token is not None
        assert isinstance(result.prepared, PreparedEdit)
        assert result.prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

        engine = TieredCommitEngine(doc)
        prepared = _engine_prepare(doc, engine, supply_geometry=True)
        assert isinstance(prepared, PreparedEdit), prepared
        assert prepared.token == result.plan_token
    finally:
        doc.close()


def test_applied_patch_revert_restores_the_mode_two_stream_byte_identically() -> None:
    """Cross-slice invariant 3, on the shape this slice admits.

    ``AppliedPatch.revert`` restores the captured raw storage, so the
    reverted stream must equal the pre-commit bytes EXACTLY -- not merely
    decode to the same content.  Undo/redo inherits this (D2); a stroke
    that came back as a re-encoded stream would still lose its offsets.
    """
    doc = _doc(_e2e_stream(b"2 Tr 1 w"))
    try:
        page = doc[0]
        stream_xref = page.get_contents()[0]
        before = doc.xref_stream(stream_xref)

        engine = TieredCommitEngine(doc)
        prepared = _engine_prepare(doc, engine)
        assert isinstance(prepared, PreparedEdit), prepared

        applied = apply_patchset(
            doc,
            doc[0],
            PatchSet(
                page_xref=prepared.page_xref,
                replacements=(prepared.replacement,),
                expected_page_fingerprint=prepared.page_fingerprint,
            ),
        )
        assert doc.xref_stream(stream_xref) != before
        assert applied.revert(doc) is True
        assert doc.xref_stream(stream_xref) == before
        assert page_fingerprint(doc, doc[0]) == prepared.page_fingerprint
    finally:
        doc.close()


# Every refusal this module measures, as (id, builder).  Enumerated from the
# cases above rather than from a lettered list: the plan's Step 11 names
# "S1-c/S1-d/S1-e", which appear nowhere in either plan file, so the honest
# reading is "every stroke refusal this slice can produce".
_REFUSAL_CASES: tuple[tuple[str, str], ...] = (
    ("render_mode_1", "unsupported_text_state"),
    ("render_mode_3", "unsupported_text_state"),
    ("render_mode_4", "unsupported_text_state"),
    ("render_mode_5", "unsupported_text_state"),
    ("render_mode_6", "unsupported_text_state"),
    ("render_mode_7", "unsupported_text_state"),
    ("render_mode_9", "unsupported_text_state"),
    ("nonzero_rise", "unsupported_text_state"),
    ("zero_pen", "stroke_bound_unproven"),
    ("pen_too_wide", "stroke_bound_too_large"),
    ("miter_too_wide", "stroke_bound_too_large"),
    ("extgstate_lw_too_wide", "stroke_bound_too_large"),
    ("extgstate_lw_wrong_type", "stroke_bound_unproven"),
    ("extgstate_dangling_xref", "stroke_bound_unproven"),
    ("extgstate_name_absent", "stroke_bound_unproven"),
    ("extgstate_no_resource_dict", "stroke_bound_unproven"),
    ("twin_overlaps_outset_core", "duplicate_source_painter"),
    ("twin_inside_the_miter_bound", "duplicate_source_painter"),
    # T16-4 S1 review H1/H2/H3: the ordered pen proof's own refusals.
    ("extgstate_before_w_over_the_bound", "stroke_bound_too_large"),
    ("negative_join", "stroke_bound_unproven"),
    ("undefined_join", "stroke_bound_unproven"),
    ("zero_miter_limit", "stroke_bound_unproven"),
    ("malformed_w", "stroke_bound_unproven"),
    ("malformed_j", "stroke_bound_unproven"),
    ("malformed_m", "stroke_bound_unproven"),
    ("nameless_gs", "stroke_bound_unproven"),
)


def _refusal_doc(case: str) -> tuple[fitz.Document, bool]:
    """Build one refusal fixture; the flag says whether it is a twin page."""
    if case.startswith("render_mode_"):
        mode = case.rsplit("_", 1)[1]
        return _doc(_show_stream(f"{mode} Tr 1 w".encode("ascii"))), False
    if case == "nonzero_rise":
        return _doc(_show_stream(b"2 Tr 1 w 3 Ts")), False
    if case == "zero_pen":
        return _doc(_show_stream(b"2 Tr 0 w")), False
    if case == "pen_too_wide":
        return _doc(_show_stream(b"2 Tr 3 w")), False
    if case == "miter_too_wide":
        return _doc(_show_stream(b"2 Tr 0.5 w 25 M")), False
    if case == "negative_join":
        return _doc(_show_stream(b"2 Tr 1 w 10 M -1 j")), False
    if case == "undefined_join":
        return _doc(_show_stream(b"2 Tr 1 w 5 j")), False
    if case == "zero_miter_limit":
        return _doc(_show_stream(b"2 Tr 1 w 0 M")), False
    if case == "malformed_w":
        return _doc(_show_stream(b"2 Tr 1 w w")), False
    if case == "malformed_j":
        return _doc(_show_stream(b"2 Tr 1 w 10 M 1 j (x) j")), False
    if case == "malformed_m":
        return _doc(_show_stream(b"2 Tr 1 w /Name M")), False
    if case == "nameless_gs":
        return _doc(_show_stream(b"2 Tr 1 w gs")), False
    gs_stream = _show_stream(b"2 Tr 1 w", prefix=b"q /GS1 gs ", suffix=b" Q")
    if case == "extgstate_lw_too_wide":
        # H1: the ``/LW`` must run LAST to be the rendered pen -- the
        # gs-first spelling this row used to build now admits (see the
        # re-pinned ``..._before_a_w_is_overwritten``).
        return (
            _gs_doc(
                "<< /Type /ExtGState /LW 3 >>",
                stream=_show_stream(b"2 Tr 1 w /GS1 gs"),
            ),
            False,
        )
    if case == "extgstate_before_w_over_the_bound":
        return (
            _gs_doc(
                "<< /Type /ExtGState /LW 0.1 >>",
                stream=_show_stream(b"/GS1 gs 5 w 2 Tr"),
            ),
            False,
        )
    if case == "extgstate_lw_wrong_type":
        return _gs_doc("<< /Type /ExtGState /LW true >>", stream=gs_stream), False
    if case == "extgstate_dangling_xref":
        return _doc(gs_stream, extgstate="<< /GS1 9999 0 R >>"), False
    if case == "extgstate_name_absent":
        return (
            _gs_doc(
                "<< /Type /ExtGState /LW 0.4 >>",
                stream=_show_stream(
                    b"2 Tr 1 w", prefix=b"q /GS2 gs ", suffix=b" Q"
                ),
            ),
            False,
        )
    if case == "extgstate_no_resource_dict":
        return _doc(gs_stream), False
    if case == "twin_overlaps_outset_core":
        return _twin_doc(b"2 Tr 1 w", gap=0.1), True
    if case == "twin_inside_the_miter_bound":
        return _twin_doc(b"2 Tr 1 w 10 M", gap=2.0), True
    raise AssertionError(f"unknown refusal case {case!r}")


@pytest.mark.parametrize(("case", "reason"), _REFUSAL_CASES, ids=[c for c, _ in _REFUSAL_CASES])
def test_every_stroke_refusal_leaves_the_document_byte_identical(
    case: str, reason: str
) -> None:
    """Step 11's closing sweep, and §Fail-closed gates' standing rule.

    Each case above already asserts zero mutation inside its own helper;
    this collects them into ONE named obligation so a future refusal added
    without that assertion is visible as a missing row rather than as a
    silent gap.

    The oracle is ``document_object_snapshot`` (per-xref serialization), not
    ``doc.tobytes()``: this repo records ``tobytes`` as nondeterministic
    across calls (trailer ``/ID`` churn), and the per-xref snapshot is
    strictly stronger -- it also sees the ExtGState and font objects these
    fixtures add.  Same obligation as
    ``test_text_commit_boundaries.py``'s, a better instrument.
    """
    doc, is_twin = _refusal_doc(case)
    try:
        before = document_object_snapshot(doc)
        result = _plan_twin(doc) if is_twin else _plan(doc)
        assert isinstance(result, PlanRejection), result
        assert result.reason == reason, result
        assert document_object_snapshot(doc) == before, (
            f"refusal {case!r} mutated the document"
        )
    finally:
        doc.close()


# ================== T16-4 S1 review H1/H2/H3: the ordered pen proof ========
#
# The S1 review reproduced three planner-side defects end to end -- every one
# of them went through ``TieredCommitEngine.prepare``/``.commit`` and came
# back COMMITTED, so post-commit verification is not a second net:
#
# H1  ``_resolve_stroke_pen`` applied a present ``/LW``/``/LJ``/``/ML`` over
#     the stream-recorded ``w``/``j``/``M`` regardless of which executed
#     LAST, because replay recorded three scalars and a name tuple and lost
#     the ORDER.  S1's replay slice added ``ShowOp.pen_events``, the ordered
#     log; the planner now replays it from the PDF defaults.
# H2  the conservative factor was ``max(miter_limit, 0.5)`` -- below the
#     geometric ``w/2`` every stroke reaches -- and treated every join other
#     than 0 as non-miter, although only 1 (round) and 2 (bevel) are.
# H3  a malformed ``w``/``j``/``M`` operand left the previous value standing,
#     so a stream that renders miter was proved as round.


def test_extgstate_before_w_proves_the_w_pen() -> None:
    """H1's headline: ``/GS1 gs 5 w 2 Tr`` renders the 5.0 pen.

    ``/GS1`` carries ``/LW 0.1``, so the pre-fix proof read width 0.1 and
    admitted (``0.1 * 10 <= 0.5 * 24``) a page whose rendered pen is 5.0 --
    the ``stroke_bound_too_large`` ceiling defeated, and the duplicate-gate
    outset 0.5 pt instead of 25 pt.  The gs-LESS twin page is the oracle:
    same operators minus the ``gs``, and the two refusals must be the SAME
    code with the SAME measured ratio.
    """
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 0.1 >>", stream=_show_stream(b"/GS1 gs 5 w 2 Tr")
    )
    twin = _doc(_show_stream(b"5 w 2 Tr"))
    try:
        _assert_gs_in_scope(doc, "GS1")
        rejection = _refuse(doc)
        twin_rejection = _refuse(twin)
        assert rejection.reason == "stroke_bound_too_large"
        assert twin_rejection.reason == "stroke_bound_too_large"
        # 5 * 10 / (0.5 * 24) = 4.167
        assert "4.167x" in rejection.detail, rejection.detail
        assert rejection.detail == twin_rejection.detail
    finally:
        doc.close()
        twin.close()


def test_w_before_extgstate_proves_the_extgstate_pen() -> None:
    """The other direction, so the fix is ORDER and not "the w always wins".

    ``2 Tr 5 w /GS1 gs`` with ``/LW 0.4``: the ``gs`` runs last, so the pen
    is 0.4 and the honest fallback outset is 0.2 -- the number the re-pinned
    ``..._before_a_w_operand_does_not_survive_it`` used to assert on the
    opposite operator order.  Without this half, "ignore every ExtGState"
    would pass the test above and silently kill E8's branch.
    """
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 0.4 >>", stream=_show_stream(b"2 Tr 5 w /GS1 gs")
    )
    try:
        _assert_gs_in_scope(doc, "GS1")
        prepared = _admit(doc)
        assert _outset_per_side(prepared, _mode0_twin_bbox()) == pytest.approx(
            0.2, abs=1e-6
        )
    finally:
        doc.close()


def test_negative_join_takes_the_miter_factor() -> None:
    """H2: ``-1 j`` is not a round join, and MuPDF renders it as MITER.

    The fixture is the miter-load-bearing duplicate-gate one
    (``test_miter_factor_is_load_bearing_at_the_duplicate_gate``: ``2 Tr 1 w
    10 M`` with the twin 2.0 pt clear, which refuses because the conservative
    outset is 5.0 pt) with ``-1 j`` appended.  Before the fix the negative
    operand read as "not join 0", collapsed the factor to 1.0, shrank the
    outset to 0.5 pt and ADMITTED the twin -- over ink a miter vertex paints
    2.27 pt past the core (E6).

    The refusal code is ``stroke_bound_unproven``, not the
    ``duplicate_source_painter`` its ``0 j`` sibling produces: an undefined
    join is renderer-defined, so ``_prove_stroke_pen`` refuses the pen before
    any twin is measured.  That is the STRONGER of the two verdicts (it
    refuses the page with no twin at all), and the miter factor itself is
    pinned for join ``-1`` in ``test_text_commit_stroke_bounds.py``.
    """
    doc = _twin_doc(b"2 Tr 1 w 10 M -1 j", gap=2.0)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "stroke_bound_unproven"
        assert "render_mode=2" in rejection.detail
        assert "line join -1" in rejection.detail, rejection.detail
    finally:
        doc.close()


def test_undefined_join_in_a_proven_pen_is_refused() -> None:
    """``5 j`` is outside ``{0, 1, 2}``: what it paints is renderer-defined.

    MuPDF was measured rendering ``5 j`` (and an ExtGState ``/LJ 5``) as
    bevel/round, but that is one renderer's choice on an undefined operand,
    not a contract a fail-closed bound may rest on.
    """
    doc = _doc(_show_stream(b"2 Tr 1 w 5 j"))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
        assert "render_mode=2" in rejection.detail
        assert "line join 5" in rejection.detail, rejection.detail
    finally:
        doc.close()


def test_zero_miter_limit_is_refused_not_halved() -> None:
    """H2: ``1 w 0 M`` gave an outset of 0.25 pt, half the rendered ink.

    A stroke always reaches ``w/2`` per side, so the old ``max(M, 0.5)``
    floor was BELOW the geometric minimum.  ``M < 1`` is spec-illegal
    anyway (ISO 32000-1 8.5.2), so the pen is refused rather than floored:
    the conservative helper keeps a 1.0 floor for its instrument callers,
    and the admission path never sees the value at all.
    """
    doc = _doc(_show_stream(b"2 Tr 1 w 0 M"))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
        assert "render_mode=2" in rejection.detail
        assert "0.0" in rejection.detail, rejection.detail
    finally:
        doc.close()


def test_zero_miter_limit_no_longer_admits_a_twin_inside_the_half_pen() -> None:
    """The false safe the halved floor produced, at the duplicate gate.

    The twin sits 0.3 pt clear of the target's un-outset core -- inside the
    0.5 pt a ``1 w`` stroke reaches on ANY join -- and the old
    ``max(0.0, 0.5) = 0.5`` factor outset the core by only 0.25 pt and
    admitted it.
    """
    doc = _twin_doc(b"2 Tr 1 w 0 M", gap=0.3)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "stroke_bound_unproven"
    finally:
        doc.close()


@pytest.mark.parametrize(
    ("body", "operator"),
    [
        pytest.param(b"2 Tr 1 w w", "w", id="w-without-operand"),
        pytest.param(b"2 Tr 1 w 10 M 1 j (x) j", "j", id="j-with-a-string"),
        pytest.param(b"2 Tr 1 w /Name M", "M", id="M-with-a-name"),
        pytest.param(b"2 Tr 1 w gs", "gs", id="gs-without-a-name"),
    ],
)
def test_malformed_pen_operands_refuse_the_pen(body: bytes, operator: str) -> None:
    """H3: a malformed operand is not a value the planner may guess.

    Replay is deliberately tolerant (it never flags the stream malformed for
    a pen operator), and it used to leave the PREVIOUS value standing, so
    ``1 w 10 M 1 j (x) j`` reported a round join while MuPDF resets to 0 and
    renders MITER -- factor 1.0 instead of 10, committed false-safe.  A
    malformed ``w`` was worse: it walked straight past the explicit ``0 w``
    hairline refusal carrying whatever width happened to precede it.

    Replay now parks the scalar on a sentinel and logs ``(op, None)``; the
    planner refuses on the EVENT, because a later ``gs`` carrying ``/LW``
    would overwrite the sentinel and erase the signal.  MuPDF's own
    reset-to-zero is not mimicked: the planner must refuse, not guess one
    renderer's recovery.
    """
    doc = _doc(_show_stream(body))
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
        assert "render_mode=2" in rejection.detail
        assert f"malformed {operator} operand" in rejection.detail, rejection.detail
    finally:
        doc.close()


def test_a_malformed_operand_is_not_erased_by_a_later_extgstate() -> None:
    """The sentinel is clobberable; the ordered EVENT is not.

    ``1 w w /GS1 gs`` with ``/GS1 << /LW 0.4 >>``: reading the scalar would
    see 0.4 (the ExtGState overwrote the ``nan``) and admit.  Reading
    ``pen_events`` sees ``("w", None)`` before the ``gs`` and refuses -- on
    exactly the pages H1 is about.
    """
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 0.4 >>", stream=_show_stream(b"2 Tr 1 w w /GS1 gs")
    )
    try:
        rejection = _refuse(doc)
        assert rejection.reason == "stroke_bound_unproven"
        assert "malformed w operand" in rejection.detail, rejection.detail
    finally:
        doc.close()

# ================================================== T16-4X S1 review M1:
# ``page_fingerprint`` must cover the ExtGState the pen proof reads.
#
# The pen a mode-2 admission is proved against can live entirely inside
# ``/Resources /ExtGState`` -- and until this fix the fingerprint folded the
# FONT resource table and nothing else about resources, so rewriting
# ``/GS1``'s ``/LW`` from a provable 0.2 to an unprovable 4 left the digest
# byte-identical.  A ``PreparedEdit`` cached across that rewrite (preview
# session, undo/redo, a controller that plans then waits) therefore committed
# a splice whose stroke bound had been measured against a pen the page no
# longer has.


def _gs_doc_and_xref(
    body: str, *, stream: bytes, name: str = "GS1"
) -> tuple[fitz.Document, int]:
    """:func:`_gs_doc`, returning the ExtGState object's xref as well."""
    doc = _gs_doc(body, stream=stream, name=name)
    kind, value = doc.xref_get_key(doc[0].xref, f"Resources/ExtGState/{name}")
    assert kind == "xref", (kind, value)
    return doc, int(value.split()[0])


# ``2 Tr 1 w /GS1 gs``: the ``gs`` runs LAST, so ``/LW`` IS the rendered pen
# (the H1 ordering fix).  0.2 x max(10, 1) = 2.0 against a 12.0 ceiling
# admits; 4 x 10 = 40 does not.
_M1_STREAM = _show_stream(b"2 Tr 1 w /GS1 gs")
_M1_PROVABLE = "<< /Type /ExtGState /LW 0.2 /ML 10 >>"
_M1_UNPROVABLE = "<< /Type /ExtGState /LW 4 /ML 10 >>"


def test_rewriting_an_extgstate_pen_key_moves_the_page_fingerprint() -> None:
    """The digest itself, stated before any plan is involved.

    ``/GS1`` is an INDIRECT object, so the page dictionary, its
    ``/Resources`` and the ``/ExtGState`` sub-dictionary are all
    byte-identical across this rewrite -- only the referenced object's
    content moves.  That is the same shape the font fold already covers with
    its one-level indirect walk, and the reason a fold of the NAME->reference
    mapping alone would not be enough.
    """
    doc, gs_xref = _gs_doc_and_xref(_M1_PROVABLE, stream=_M1_STREAM)
    try:
        before = page_fingerprint(doc, doc[0])
        doc.update_object(gs_xref, _M1_UNPROVABLE)
        assert page_fingerprint(doc, doc[0]) != before
    finally:
        doc.close()


def test_a_non_pen_extgstate_key_also_moves_the_fingerprint() -> None:
    """The fold is of the OBJECT, not of a pen-key allowlist: an ExtGState
    key this slice does not read today still goes stale, because the next
    gate to read one must not inherit a digest that was already blind to
    it."""
    doc, gs_xref = _gs_doc_and_xref(_M1_PROVABLE, stream=_M1_STREAM)
    try:
        before = page_fingerprint(doc, doc[0])
        doc.update_object(
            gs_xref, "<< /Type /ExtGState /LW 0.2 /ML 10 /ca 0.5 >>"
        )
        assert page_fingerprint(doc, doc[0]) != before
    finally:
        doc.close()


def test_repointing_an_extgstate_name_moves_the_fingerprint() -> None:
    """The NAME -> object binding is folded too: swapping which object a
    name resolves to changes what every ``gs`` under that name does, even
    when both objects already existed."""
    doc, gs_xref = _gs_doc_and_xref(_M1_PROVABLE, stream=_M1_STREAM)
    try:
        other = doc.get_new_xref()
        doc.update_object(other, _M1_UNPROVABLE)
        before = page_fingerprint(doc, doc[0])
        doc.xref_set_key(doc[0].xref, "Resources/ExtGState/GS1", f"{other} 0 R")
        assert page_fingerprint(doc, doc[0]) != before
        assert gs_xref != other
    finally:
        doc.close()


def test_an_empty_extgstate_table_folds_exactly_like_no_table_at_all() -> None:
    """The byte-identity clause of the design: the ExtGState digest is
    folded AFTER every existing component and contributes NOTHING when the
    page declares no ExtGState names, so every fingerprint pin taken on a
    page without one stays valid to the byte."""
    plain = _doc(_show_stream(b"2 Tr 1 w"))
    empty = _doc(_show_stream(b"2 Tr 1 w"), extgstate="<< >>")
    try:
        assert page_fingerprint(plain, plain[0]) == page_fingerprint(
            empty, empty[0]
        )
    finally:
        plain.close()
        empty.close()


def test_an_inherited_extgstate_table_is_folded_like_a_page_local_one() -> None:
    """``/Resources`` is inheritable, so the fold walks ``/Parent`` exactly
    as the pen proof's own resolver does -- otherwise a document that keeps
    its ExtGState on the page tree gets no staleness cover at all."""
    doc, gs_xref = _gs_doc_and_xref(_M1_PROVABLE, stream=_M1_STREAM)
    try:
        page = doc[0]
        kind, resources = doc.xref_get_key(page.xref, "Resources")
        assert kind == "dict"
        kind, parent = doc.xref_get_key(page.xref, "Parent")
        assert kind == "xref"
        parent_xref = int(parent.split()[0])
        doc.xref_set_key(parent_xref, "Resources", resources)
        doc.xref_set_key(page.xref, "Resources", "null")
        # The premise, asserted rather than assumed: the page really does
        # reach its ExtGState through the parent now.
        assert doc.xref_get_key(page.xref, "Resources")[0] == "null"
        before = page_fingerprint(doc, page)
        doc.update_object(gs_xref, _M1_UNPROVABLE)
        assert page_fingerprint(doc, doc[0]) != before
    finally:
        doc.close()


def test_the_fingerprint_and_the_pen_proof_read_the_same_extgstate_table() -> None:
    """Drift guard.  ``inspect`` cannot import ``plan`` (``plan`` imports
    ``inspect``), so the two resolvers are separate code; this pins that they
    agree on the same page, including through an inherited ``/Resources``.
    """
    from model.text_commit.inspect import _effective_extgstate
    from model.text_commit.plan import _extgstate_resources

    doc, _gs_xref = _gs_doc_and_xref(_M1_PROVABLE, stream=_M1_STREAM)
    try:
        page = doc[0]
        folded = _effective_extgstate(doc, page)
        resolved = _extgstate_resources(doc, page)
        assert folded is not None and resolved is not None
        assert set(folded) == set(resolved) == {"GS1"}

        kind, resources = doc.xref_get_key(page.xref, "Resources")
        parent_xref = int(doc.xref_get_key(page.xref, "Parent")[1].split()[0])
        doc.xref_set_key(parent_xref, "Resources", resources)
        doc.xref_set_key(page.xref, "Resources", "null")
        page = doc[0]
        assert set(_effective_extgstate(doc, page) or {}) == set(
            _extgstate_resources(doc, page) or {}
        ) == {"GS1"}
    finally:
        doc.close()


def test_a_cached_mode_two_plan_is_refused_after_its_extgstate_is_rewritten() -> None:
    """The end-to-end consequence, which is what makes M1 a finding rather
    than a fingerprint nicety.

    Before the fix this exact sequence COMMITTED: the plan measured a 0.2 pt
    pen, the page was rewritten to a 4 pt one, the fingerprint still matched,
    and the splice landed against a stroke bound the page no longer
    justified.  Both halves are pinned -- a FRESH prepare refuses the
    rewritten page outright, and the CACHED plan is refused as stale rather
    than applied.
    """
    doc, gs_xref = _gs_doc_and_xref(_M1_PROVABLE, stream=_M1_STREAM)
    try:
        prepared = _admit(doc)
        stream_xref = doc[0].get_contents()[0]
        before = doc.xref_stream(stream_xref)

        doc.update_object(gs_xref, _M1_UNPROVABLE)

        fresh = _plan(doc)
        assert isinstance(fresh, PlanRejection), fresh
        assert fresh.reason == "stroke_bound_too_large"

        engine = TieredCommitEngine(doc)
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.STALE_PLAN, outcome
        assert doc.xref_stream(stream_xref) == before
    finally:
        doc.close()

# ============================================== T16-4X S1 review M2: the
# TWIN side of the same outset.
#
# Step 9 grew ``target_core`` by the target's own proven pen.  It left every
# TWIN measured by its bare advance core -- so a FILL-mode target beside a
# same-bytes twin painting at ``2 Tr 5 w 10 M`` was called disjoint at a
# 0.1 pt clearance, while the twin's rendered stroke ink reaches 0.208 pt
# INTO the target core (measured; the gate's own tolerance is 0.05 pt).
# Nothing about the target is wrong there: the ink that lands on the edit is
# the twin's, and the twin's pen was simply never read.  S1 put the pen
# fields on every ``ShowOp``, so the symmetric outset is now available.


def _stroked_twin_stream(twin_body: bytes, *, gap: float) -> bytes:
    """A FILL-mode target at ``(72, 700)`` plus a twin in ``twin_body``.

    The mirror image of :func:`_twin_doc`: there the target carried the
    render mode and the twin was reset to ``0 Tr``; here the target paints
    in the default fill mode (no ``Tr`` precedes it) and the twin states its
    own.  ``gap`` is again the clearance between the two UN-outset advance
    cores, measured with MuPDF's own base-14 text length.
    """
    advance = fitz.get_text_length(TARGET, fontname="helv", fontsize=SIZE)
    twin_x = 72.0 + advance + gap
    return (
        b"BT /F1 "
        + f"{SIZE:g}".encode("ascii")
        + b" Tf 1 0 0 1 72 700 Tm ("
        + TARGET.encode()
        + b") Tj "
        + twin_body
        + b" 1 0 0 1 "
        + f"{twin_x:.4f}".encode("ascii")
        + b" 700 Tm ("
        + TARGET.encode()
        + b") Tj ET"
    )


def _stroked_twin_doc(twin_body: bytes, *, gap: float) -> fitz.Document:
    return _doc(_stroked_twin_stream(twin_body, gap=gap))


# ``5 w 10 M`` -> conservative outset ``(5/2) * max(10, 1) * 1`` = 25.0 pt,
# so a twin this wide reaches the target core from any of these clearances.
_M2_TWIN = b"2 Tr 5 w 10 M"


@pytest.mark.parametrize(
    ("gap", "overlap"),
    [(0.1, "24.900"), (1.0, "24.000"), (3.0, "22.000")],
)
def test_a_stroked_twin_is_outset_before_the_core_overlap_test(
    gap: float, overlap: str
) -> None:
    """All three clearances ADMITTED before this fix.

    The refusal is the EXISTING core-overlap verdict with the EXISTING
    string -- the twin's outset moves where the boundary is, it does not add
    a reason code or a sentence.  The depths are pinned exactly, so an
    outset applied with the wrong factor (half-pen instead of the miter
    bound, say) fails here with a number rather than passing quietly.
    """
    doc = _stroked_twin_doc(_M2_TWIN, gap=gap)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter overlaps target core by "
            f"{overlap}pt x 14.400pt"
        ), rejection.detail
    finally:
        doc.close()


def test_a_fill_mode_twin_carrying_a_pen_is_not_outset() -> None:
    """The control that makes the test above about the RENDER MODE.

    The same ``5 w 10 M`` pen, the same 0.1 pt clearance -- but the twin
    paints at ``0 Tr``, so it strokes nothing and its core is compared
    un-outset, exactly as before this fix.  Without this, an outset keyed on
    "the show mentions a pen" rather than on "the show strokes" would refuse
    every page that sets a line width before its text.
    """
    doc = _stroked_twin_doc(b"0 Tr 5 w 10 M", gap=0.1)
    try:
        _admit_twin(doc)
    finally:
        doc.close()


def test_a_stroked_twin_far_from_the_target_is_still_admissible() -> None:
    """The outset is a BOUND, not a blanket refusal of stroked twins: 30 pt
    of clearance is more than the 25 pt this pen can reach, and the gate
    still admits."""
    doc = _stroked_twin_doc(_M2_TWIN, gap=30.0)
    try:
        _admit_twin(doc)
    finally:
        doc.close()


@pytest.mark.parametrize("mode", [1, 3, 4, 5, 6, 7])
def test_a_twin_in_a_mode_the_ladder_does_not_admit_is_refused(mode: int) -> None:
    """Every non-fill mode other than 2 has no outset the planner can
    compute -- mode 1 paints stroke-only ink the advance core does not bound
    at all, and 4-7 additionally put the glyphs in the CLIPPING PATH, whose
    effect on everything painted afterwards no per-show box describes.  The
    twin is 30 pt clear, i.e. far enough that even the mode-2 bound would
    admit it, so this pins the MODE and not the distance.

    Reuses the existing "cannot prove target placement" string, per the
    design: an unprovable twin makes the target's placement relative to it
    unprovable, and no new vocabulary is invented for it.
    """
    doc = _stroked_twin_doc(f"{mode:d} Tr 1 w".encode("ascii"), gap=30.0)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter cannot prove target placement"
        ), rejection.detail
    finally:
        doc.close()


@pytest.mark.parametrize(
    "twin_body",
    [
        b"2 Tr 0 w",  # hairline: device-thinnest, not bounded by half of it
        b"2 Tr 1 w w",  # malformed operand: replay records ``("w", None)``
        b"2 Tr 1 w /GSMISSING gs",  # a name the page does not declare
    ],
    ids=["hairline", "malformed_w", "undeclared_extgstate"],
)
def test_a_mode_two_twin_whose_pen_is_unprovable_is_refused(
    twin_body: bytes,
) -> None:
    """A pen that cannot be read is not a bound.  Same ordered proof as the
    target's (``_resolve_stroke_pen`` plus the visual-outset guard), same
    fail-closed answer, and again at 30 pt of clearance so the refusal is
    about the pen rather than the geometry."""
    doc = _stroked_twin_doc(twin_body, gap=30.0)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter cannot prove target placement"
        ), rejection.detail
    finally:
        doc.close()


def test_a_mode_two_twin_takes_its_extgstate_pen_in_order() -> None:
    """The twin's pen is resolved by the SAME ordered replay as the
    target's, ExtGState included: ``1 w`` then ``/GS1 gs`` with
    ``/LW 5 /ML 10`` renders the 5 pt pen, so the twin's outset is 25 pt and
    a 3 pt clearance is refused -- where reading the stream's ``1 w`` alone
    (outset 5 pt) would have admitted it.
    """
    doc = _gs_doc(
        "<< /Type /ExtGState /LW 5 /ML 10 >>",
        stream=_stroked_twin_stream(b"2 Tr 1 w /GS1 gs", gap=3.0),
    )
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter overlaps target core by "
            "22.000pt x 14.400pt"
        ), rejection.detail
    finally:
        doc.close()


@pytest.mark.parametrize("mode", [1, 3, 4, 5, 6, 7])
def test_an_unboundable_twin_that_already_overlaps_keeps_the_older_string(
    mode: int,
) -> None:
    """ORDER.  The unprovable-twin refusal runs AFTER the un-outset
    comparison, never instead of it.

    Outsetting can only GROW the twin's core, so it is monotone on the
    overlap predicate: a twin the bare boxes already refuse is refused
    whichever order the two run in, and the only thing the order decides is
    WHICH sentence the caller reads.  Running the placement refusal first
    would replace every older, more specific verdict on an unboundable twin
    -- the core-overlap measurement here, and the "cannot prove exact
    extent ... can reach the target core" reach string on the CID
    population -- with a blanket sentence that says less.

    The twin here overlaps the target's advance core by 2 pt before any
    outset is applied, so the measured core-overlap string wins and the
    twin's unboundable mode never has to be reported.  Its far-away sibling
    (30 pt clear, above) still returns the placement string, which is the
    half of the pair that closes the M2 false safe.
    """
    doc = _stroked_twin_doc(f"{mode:d} Tr 1 w".encode("ascii"), gap=-2.0)
    try:
        rejection = _refuse_twin(doc)
        assert rejection.reason == "duplicate_source_painter"
        assert rejection.detail == (
            "identical source painter overlaps target core by "
            "2.000pt x 14.400pt"
        ), rejection.detail
    finally:
        doc.close()

# ================================== T16-4X S1 review L2: the cross-slice
# invariants on the OTHER admitted grammar.
#
# Invariants 2 (preview token == commit token) and 3 (``AppliedPatch.revert``
# restores the stream byte-identically) were pinned for mode 2 only on a
# whole-operand ``Tj`` target.  S1 also admits a single-item ``TJ`` array,
# spliced at its INNER item -- a range that starts and ends inside the
# array's brackets -- and neither invariant had a pin on that shape.  The
# risk each one covers is specific to the inner range: a token built from
# the operator range instead of the item range would collide across two
# different edits to the same array, and a revert that restored the operator
# range would put back bytes the patch never took.


def _e2e_tj_stream(body: bytes) -> bytes:
    """:func:`_e2e_stream`'s page with the target shown as ``[(...)] TJ``.

    Same neighbour show (so V0c's non-target origin gate is non-vacuous),
    same reset to ``0 Tr`` before it, same 24 pt size.  Only the target's
    operator changes -- which is the whole point: the splice lands inside
    the array instead of over a whole string operand.
    """
    return (
        b"BT /F1 "
        + f"{SIZE:g}".encode("ascii")
        + b" Tf "
        + body
        + b" 72 700 Td [("
        + TARGET.encode()
        + b")] TJ 0 Tr 0 -40 Td ("
        + E2E_DOWNSTREAM.encode()
        + b") Tj ET"
    )


def _tj_inner_item_span(doc: fitz.Document) -> tuple[int, int]:
    """The byte range of the target array's ONE string item.

    Re-lexed from the stream through the production helper rather than found
    with ``bytes.index``: the assertions below are about the range the
    planner spliced, and an independent search would agree with a wrong
    range just as happily as with a right one.
    """
    from model.text_commit.glyph_boxes import tj_item_spans

    stream_xref = doc[0].get_contents()[0]
    stream = doc.xref_stream(stream_xref)
    shows = [
        show
        for show in replay_page(doc, doc[0]).shows
        if show.decoded_bytes == TARGET.encode("latin-1")
    ]
    assert len(shows) == 1, f"expected 1 target show, got {len(shows)}"
    assert shows[0].operator == "TJ", shows[0].operator
    spans = tj_item_spans(stream, shows[0])
    assert spans is not None
    items = [span for span in spans if span.kind == "string"]
    assert len(items) == 1, items
    # Non-vacuity, asserted once here for every pin below: the item range is
    # STRICTLY inside the operator range, so "the splice/token/revert used
    # the operator range instead" is a state these tests can actually
    # distinguish -- on a whole-operand ``Tj`` target the two ranges share
    # their string bytes and the distinction would be untestable.
    assert shows[0].op_start < items[0].start
    assert items[0].end < shows[0].op_end
    return items[0].start, items[0].end


def test_a_mode_two_tj_inner_item_commit_touches_only_that_item() -> None:
    """The premise the two invariants below are asserted against.

    ``Price 2024`` -> ``Price 2025`` is advance-neutral AND equal-length, so
    the committed stream must differ from the pre-commit one at exactly the
    inner item's bytes: identical before ``item_start``, identical from
    ``item_end`` on, different in between.  Anything wider is a whole-
    operator rewrite wearing a Tier 0 label.
    """
    doc = _doc(_e2e_tj_stream(b"2 Tr 1 w"))
    try:
        stream_xref = doc[0].get_contents()[0]
        before = doc.xref_stream(stream_xref)
        item_start, item_end = _tj_inner_item_span(doc)

        engine = TieredCommitEngine(doc)
        prepared = _engine_prepare(doc, engine)
        assert isinstance(prepared, PreparedEdit), prepared
        assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        assert prepared.splice_kind == "string_token"
        assert (prepared.replacement.start, prepared.replacement.end) == (
            item_start,
            item_end,
        )

        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.COMMITTED, outcome
        after = doc.xref_stream(stream_xref)
        assert len(after) == len(before), "the fixture is not length-neutral"
        assert after[:item_start] == before[:item_start]
        assert after[item_end:] == before[item_end:]
        assert after[item_start:item_end] != before[item_start:item_end]
        assert b"2 Tr 1 w" in after
        assert E2E_REPLACEMENT in doc[0].get_text()
    finally:
        doc.close()


def test_the_preview_token_is_the_commit_token_for_a_tj_inner_item_target() -> None:
    """Cross-slice invariant 2 on the inner-item grammar.

    The preview renderer plans on a session snapshot and the engine plans on
    the live document.  The token folds the splice COORDINATES, so on this
    shape it folds the inner range -- and a session whose re-lex of the
    array landed anywhere else would produce a different token and miss the
    controller's cache silently, falling back to legacy, which is the path
    that drops the stroke leg.

    Taken BEFORE anything is applied: the token folds the page fingerprint
    and committing moves it.
    """
    doc = _doc(_e2e_tj_stream(b"2 Tr 1 w"))
    try:
        page = doc[0]
        span = _span(page, TARGET)
        bbox = tuple(float(value) for value in span["bbox"])
        origin = tuple(float(value) for value in span["origin"])
        item_span = _tj_inner_item_span(doc)

        session = open_preview_session(doc, 0, "stroke-tj-e2e")
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        try:
            result = renderer.render(
                PlanPreviewRequest(
                    session_key="stroke-tj-e2e",
                    generation=1,
                    target_text=TARGET,
                    replacement_text=E2E_REPLACEMENT,
                    expected_origin=origin,
                    target_bbox=bbox,
                    clip_rect=bbox,
                    render_scale=1.0,
                )
            )
        finally:
            renderer.close()
        assert result.reject_reason is None, result.reject_reason
        assert result.plan_token is not None
        assert isinstance(result.prepared, PreparedEdit)
        assert result.prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        # The preview really did splice the inner item, not the operator.
        assert (
            result.prepared.replacement.start,
            result.prepared.replacement.end,
        ) == item_span

        engine = TieredCommitEngine(doc)
        prepared = _engine_prepare(doc, engine, supply_geometry=True)
        assert isinstance(prepared, PreparedEdit), prepared
        assert prepared.token == result.plan_token
    finally:
        doc.close()


def test_applied_patch_revert_restores_a_tj_inner_item_splice_byte_identically() -> None:
    """Cross-slice invariant 3 on the inner-item grammar.

    This is the engine's FAILED-VERIFICATION path (``AppliedPatch.revert``,
    which restores the captured RAW stream storage), not
    ``build_reversal_patchset``'s forward-inverse pair -- the two are
    different mechanisms and only this one runs when verification refuses a
    commit that was already applied.  The restored stream must equal the
    pre-commit bytes EXACTLY, and the fingerprint with it: an array that
    came back re-encoded would still move every offset after it.
    """
    doc = _doc(_e2e_tj_stream(b"2 Tr 1 w"))
    try:
        page = doc[0]
        stream_xref = page.get_contents()[0]
        before = doc.xref_stream(stream_xref)
        item_start, item_end = _tj_inner_item_span(doc)

        engine = TieredCommitEngine(doc)
        prepared = _engine_prepare(doc, engine)
        assert isinstance(prepared, PreparedEdit), prepared
        assert (prepared.replacement.start, prepared.replacement.end) == (
            item_start,
            item_end,
        )

        applied = apply_patchset(
            doc,
            doc[0],
            PatchSet(
                page_xref=prepared.page_xref,
                replacements=(prepared.replacement,),
                expected_page_fingerprint=prepared.page_fingerprint,
            ),
        )
        patched = doc.xref_stream(stream_xref)
        assert patched != before
        # The applied state itself differs ONLY inside the item, so a revert
        # that restored a wider range would be restoring bytes it never
        # touched -- the failure mode this pin exists for.
        assert patched[:item_start] == before[:item_start]
        assert patched[item_end:] == before[item_end:]

        assert applied.revert(doc) is True
        assert doc.xref_stream(stream_xref) == before
        assert page_fingerprint(doc, doc[0]) == prepared.page_fingerprint
    finally:
        doc.close()
