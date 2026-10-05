"""Structural-gate rejection tests for the Tier 0 planner (plan Task 6).

``test_text_commit_tier0.py`` varies only the *request* (replacement text,
style/geometry overrides), so every gate that depends on the *shape of the
content stream* was unreachable from it: a mutation audit deleted the
``mc_depth`` and ``render_mode``/``rise``/invalid-``hscale`` gates and the whole
suite stayed green.  This module closes that hole by varying the document
instead — one purpose-built raw content stream per gate.

Two rules make these tests mutation-proof rather than merely green:

* ``RejectReason.UNSUPPORTED_TEXT_STATE`` has four emission sites and
  ``FONT_FACE_UNAVAILABLE`` has two, so pinning the reason alone would let
  a test survive deletion of its own gate by tripping a neighbour.  Every
  test also pins a short, stable substring of ``PlanRejection.detail``.
* Every fixture must reach its gate, not trip an earlier one.  Each test
  asserts the replayed ``ShowOp`` really carries the intended off-nominal
  field *and nothing else* (:func:`_assert_only_off_nominal`), and replays
  a positive control — the same stream with the off-nominal construct
  removed — proving the fixture is otherwise a clean Tier 0 candidate.
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

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import page_fingerprint, replay_page  # noqa: E402
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    ShowGateAdmission,
    prepare_tier0_plan,
    tier0_show_gate,
)
from model.text_commit.replay import ShowOp  # noqa: E402
from model.text_commit.transforms import page_visual_frame  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    document_object_snapshot,
)

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral
LEAD_IN = "Lead-in"  # distinct bytes: never collides with TARGET when matching

# The nominal (Tier-0-eligible) value of every ShowOp field the planner or
# the binder gates on, in the order they are checked.
_NOMINAL: dict[str, object] = {
    "origin_reliable": True,  # inspect.py G6 -> UNTRACKED_ADVANCE
    "in_bt": True,  # inspect.py G5 -> UNSUPPORTED_TEXT_STATE
    "trm_uniform_scaled": True,  # inspect.py G7 -> trm_* admission (Task 13 P2)
    # A single-item "TJ"/"array" is equally admissible since T16-4X S1, and
    # a multi-item one refuses TJ_MULTI_ITEM_ARRAY; the TJ fixtures below
    # therefore declare BOTH fields off-nominal rather than widening this
    # isolation reference, which exists to pin one admitted shape.
    "operator": "Tj",  # plan.py    -> NOT_SINGLE_LITERAL_TJ
    # "hex" is equally admissible since 2026-08-01; every fixture here is
    # literal, so one nominal value still suffices.
    "string_kind": "literal",  # plan.py    -> NOT_SINGLE_LITERAL_TJ
    # Since T16-4 Steps 7-8 mode 2 is admissible too, with a proven stroke
    # pen; the fixtures here write no ``w``, so their default pen refuses
    # STROKE_BOUND_TOO_LARGE at 12 pt.  One nominal value still suffices --
    # this reference pins the one mode every fixture here shares.
    "render_mode": 0,  # plan.py G2 -> the render-mode ladder
    "rise": 0.0,  # plan.py G3 -> UNSUPPORTED_TEXT_STATE
    "hscale": 100.0,  # isolation reference; positive finite values are admitted
    "mc_depth": 0,  # plan.py G1 -> MC_* taxonomy admission (Task 13 P1)
}


def _stream_doc(stream: bytes) -> fitz.Document:
    """One page whose only content is ``stream``, with /F1 = Helvetica.

    Same xref surgery as ``test_text_commit_tier0._tier0_doc``; only the
    content-stream bytes vary, so the font resource and page shape stay a
    known-good Tier 0 baseline in every fixture.
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
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _plan(doc: fitz.Document) -> PreparedEdit | PlanRejection:
    """Run the planner and assert it left the live document untouched.

    ``expected_origin``/``target_bbox`` are deliberately ``None``: the
    off-nominal fixtures need not be renderable by MuPDF's own extractor
    (no font selected, text outside BT/ET), and binding is byte-level, so
    passing rawdict geometry would couple these tests to rendering rather
    than to the gate under test.
    """
    page = doc[0]
    fingerprint_before = page_fingerprint(doc, page)
    xrefs_before = doc.xref_length()
    result = prepare_tier0_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=None,
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
    )
    assert page_fingerprint(doc, page) == fingerprint_before  # read-only
    assert doc.xref_length() == xrefs_before
    return result


def _plan_at(
    doc: fitz.Document, origin_user: tuple[float, float]
) -> PreparedEdit | PlanRejection:
    """:func:`_plan` with an explicit expected origin, in the space the
    binder compares against (``origin_user x frame.visual``).

    Needed only by fixtures that deliberately carry a same-bytes twin,
    where an origin-free bind would refuse ``AMBIGUOUS_MATCH`` before the
    gate under test is reached.
    """
    page = doc[0]
    fingerprint_before = page_fingerprint(doc, page)
    point = fitz.Point(*origin_user) * page_visual_frame(page).visual
    result = prepare_tier0_plan(
        doc,
        page,
        target_text=TARGET,
        replacement_text=REPLACEMENT,
        expected_origin=(float(point.x), float(point.y)),
        target_bbox=None,
        registry=DocumentFontRegistry(doc),
    )
    assert page_fingerprint(doc, page) == fingerprint_before  # read-only
    return result


def _target_show(doc: fitz.Document) -> ShowOp:
    """The replayed show op the binder will select for ``TARGET``.

    Guards against the three false greens that would make a gate test pass
    for the wrong reason: a stream the replay flags malformed
    (MALFORMED_STREAM), a target that never shows up (NO_MATCH), and a
    duplicated target (AMBIGUOUS_MATCH) — all of which are checked before
    any structural gate.
    """
    replay = replay_page(doc, doc[0])
    assert not replay.malformed, "fixture stream must replay cleanly"
    matches = [s for s in replay.shows if s.decoded_bytes == TARGET.encode("latin-1")]
    assert len(matches) == 1, f"expected 1 {TARGET!r} show op, got {len(matches)}"
    return matches[0]


def _assert_only_off_nominal(show: ShowOp, *off_nominal: str) -> None:
    """Exactly ``off_nominal`` differ from Tier 0's nominal text state.

    The anti-false-green guard: it proves the fixture trips the gate under
    test and no other, so the test cannot stay green through deletion of
    its own gate by falling into a neighbouring gate that shares the same
    :class:`RejectReason`.
    """
    for name, nominal in _NOMINAL.items():
        actual = getattr(show, name)
        if name in off_nominal:
            assert actual != nominal, f"{name} was meant to be off-nominal"
        else:
            assert actual == nominal, f"{name} drifted to {actual!r}, breaks isolation"


def _assert_control_plans_cleanly(stream: bytes) -> None:
    """The fixture minus its off-nominal construct is a Tier 0 candidate."""
    doc = _stream_doc(stream)
    show = _target_show(doc)
    _assert_only_off_nominal(show)
    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), f"control fixture rejected: {prepared}"
    doc.close()


# ------------------------------------------------- plan.py structural gates


def test_planner_rejects_marked_content_target():
    """G1: a Tj inside a NON-admissible wrapper is not patchable in place.

    Task 13 P1 replaced the blanket UNSUPPORTED_TEXT_STATE refusal with
    the taxonomy admission: this /P <</MCID 0>> wrapper is structure
    content, so the gate still refuses — now with its own stable code
    (the admissible pure-/OC-layer path is pinned in
    test_text_commit_mc_admission.py).
    """
    doc = _stream_doc(
        b"/P <</MCID 0>> BDC BT /F1 12 Tf 72 700 Td ("
        + TARGET.encode()
        + b") Tj ET EMC"
    )
    show = _target_show(doc)
    assert show.mc_depth == 1
    _assert_only_off_nominal(show, "mc_depth")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.MC_WRAPPER_NOT_PURE_LAYER
    assert "struct_content" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


# ------------------------------------------- T16-4X S1: the TJ operator gate


def _tj_stream(items: bytes) -> bytes:
    return b"BT /F1 12 Tf 72 700 Td [" + items + b"] TJ ET"


def test_single_item_tj_array_reaches_the_gates_behind_the_operator_gate():
    """S1: ``[(text)] TJ`` is admitted at the operator gate.

    Formerly ``not_single_literal_tj``: the array operator was refused
    before any gate behind it could be measured (tandem plan E3).  The
    admitted candidate splices the INNER item only.
    """
    doc = _stream_doc(_tj_stream(b"(" + TARGET.encode() + b")"))
    show = _target_show(doc)
    assert show.operator == "TJ"
    assert show.string_kind == "array"
    assert show.array_item_count == 1
    _assert_only_off_nominal(show, "operator", "string_kind")

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    stream = doc.xref_stream(doc[0].get_contents()[0])
    assert stream[prepared.replacement.start : prepared.replacement.end] == (
        b"(" + TARGET.encode() + b")"
    )
    # The brackets and the operator keyword are NOT part of the splice.
    assert stream[prepared.replacement.start - 1 : prepared.replacement.start] == b"["
    assert stream[prepared.replacement.end : prepared.replacement.end + 4] == b"] TJ"
    doc.close()


def test_multi_item_tj_array_is_refused_with_its_own_code():
    """A second string item means kerns between items that a single-item
    splice cannot compensate — S4's problem, and a DISTINCT gate, so it
    gets its own code rather than reusing ``NOT_SINGLE_LITERAL_TJ``."""
    doc = _stream_doc(_tj_stream(b"(Price ) (2024)"))
    before = document_object_snapshot(doc)
    show = _target_show(doc)
    assert show.array_item_count == 2

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.TJ_MULTI_ITEM_ARRAY
    assert "2" in rejection.detail
    assert document_object_snapshot(doc) == before
    doc.close()

    # Positive control: the same fixture with the second item removed is a
    # Tier 0 candidate (``_assert_control_plans_cleanly`` cannot be reused —
    # its isolation guard still calls ``Tj`` the only nominal operator).
    control = _stream_doc(_tj_stream(b"(" + TARGET.encode() + b")"))
    assert isinstance(_plan(control), PreparedEdit)
    control.close()


def test_leading_kern_single_item_tj_is_refused():
    """A kern BEFORE the item displaces the ink from ``origin_user``, which
    ``_painter_core_quad`` and the ``target_bbox`` fallback both assume is
    where the ink starts — so a same-bytes twin sitting at the DISPLACED
    position would be measured against the wrong core (a false safe)."""
    # -3000 thousandths at 12 pt moves the ink +36 pt; the twin sits there.
    doc = _stream_doc(
        b"BT /F1 12 Tf 72 700 Td [-3000 (" + TARGET.encode() + b")] TJ "
        b"1 0 0 1 108 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    before = document_object_snapshot(doc)
    replay = replay_page(doc, doc[0])
    matches = [
        s for s in replay.shows if s.decoded_bytes == TARGET.encode("latin-1")
    ]
    assert len(matches) == 2, "fixture must carry the displaced same-bytes twin"
    target, twin = matches
    assert target.operator == "TJ" and target.array_item_count == 1
    assert twin.origin_user[0] == 108.0

    rejection = _plan_at(doc, target.origin_user)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.TJ_LEADING_KERN_UNPROVEN
    assert "kern" in rejection.detail
    assert document_object_snapshot(doc) == before, (
        "a refusal must leave the document alone"
    )
    doc.close()


def test_trailing_kern_single_item_tj_is_admitted():
    """Kerns AFTER the item are admitted: their bytes are outside the
    spliced range, so they are byte-identical pre/post and the consumed
    advance they contribute is unchanged."""
    doc = _stream_doc(_tj_stream(b"(" + TARGET.encode() + b") -3000"))
    show = _target_show(doc)
    assert show.array_item_count == 1

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    stream = doc.xref_stream(doc[0].get_contents()[0])
    assert stream[prepared.replacement.start : prepared.replacement.end] == (
        b"(" + TARGET.encode() + b")"
    )
    assert stream[prepared.replacement.end : prepared.replacement.end + 10] == (
        b" -3000] TJ"
    )
    doc.close()


def test_tj_item_relex_failure_has_its_own_code(monkeypatch):
    """The inner range must re-lex to the recorded operand.  When it does
    not, the failure is an INTEGRITY failure of its own, never papered over
    as the operator-scope code (glyph-coverage plan section 4, S1)."""
    import model.text_commit.plan as plan_mod

    doc = _stream_doc(_tj_stream(b"(" + TARGET.encode() + b")"))
    before = document_object_snapshot(doc)
    monkeypatch.setattr(plan_mod, "tj_item_spans", lambda stream, show: None)

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.TJ_ITEM_RELEX_FAILED
    assert document_object_snapshot(doc) == before
    doc.close()


def test_planner_rejects_nonzero_render_mode():
    """G2: a non-fill render mode is refused unless its pen is proven.

    RE-PINNED (T16-4 Steps 7-8) to its new measured outcome.  Mode 2 is no
    longer refused for BEING mode 2 -- it is admitted when the stroke pen
    is proven (``test_text_commit_stroke_admission.py``).  This fixture
    writes no ``w``, so it carries replay's DEFAULT pen (width 1.0, miter
    limit 10.0), and at 12 pt ``1.0 * 10 > 0.5 * 12``: the pen is proven
    and proven too fat, which is its own code.  The gate is still G2's --
    the same rung, one branch further along.
    """
    doc = _stream_doc(b"BT /F1 12 Tf 2 Tr 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.render_mode == 2
    _assert_only_off_nominal(show, "render_mode")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.STROKE_BOUND_TOO_LARGE
    assert "render_mode=2" in rejection.detail
    # 1.0 * max(10.0, 0.5) / (0.5 * 12) = 1.667
    assert "1.667" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_nonzero_text_rise():
    """G3: a raised/lowered baseline (superscript run) is not Tier 0."""
    doc = _stream_doc(b"BT /F1 12 Tf 3 Ts 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.rise == 3.0
    _assert_only_off_nominal(show, "rise")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "rise=3.0" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_admits_positive_horizontal_scale_and_rejects_invalid_values():
    """G4: positive finite Tz is admitted; zero, negative, and inf refuse."""
    doc = _stream_doc(b"BT /F1 12 Tf 80 Tz 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.hscale == 80.0
    _assert_only_off_nominal(show, "hscale")

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    doc.close()

    for operand in (b"0", b"-80", b"1" + b"0" * 400):
        invalid = _stream_doc(
            b"BT /F1 12 Tf " + operand + b" Tz 72 700 Td ("
            + TARGET.encode() + b") Tj ET"
        )
        rejection = _plan(invalid)
        assert isinstance(rejection, PlanRejection), rejection
        assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
        assert "not a positive finite horizontal scale" in rejection.detail
        invalid.close()


@pytest.mark.parametrize(
    ("state", "reason", "detail"),
    [
        # RE-PINNED (T16-4 Steps 7-8): a bare ``2 Tr`` at 12 pt now reaches
        # the pen proof and refuses on the pen (default pen 1.0 w / 10 M
        # against a 0.5*12 ceiling), not on the mode.  The property under
        # test is unchanged -- a positive ``Tz`` must not MASK the residual
        # text-state gate -- and the detail still names the mode.
        (b"2 Tr", RejectReason.STROKE_BOUND_TOO_LARGE, "render_mode=2"),
        (b"1 Tr", RejectReason.UNSUPPORTED_TEXT_STATE, "render_mode=1"),
        (b"3 Ts", RejectReason.UNSUPPORTED_TEXT_STATE, "rise=3.0"),
    ],
)
def test_positive_hscale_does_not_mask_residual_text_state_gates(
    state: bytes, reason: str, detail: str
) -> None:
    doc = _stream_doc(
        b"BT /F1 12 Tf 80 Tz "
        + state
        + b" 72 700 Td ("
        + TARGET.encode()
        + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.hscale == 80.0

    rejection = _plan(doc)

    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == reason
    assert detail in rejection.detail
    doc.close()


def test_positive_hscale_does_not_mask_shared_content_stream_gate() -> None:
    doc = fitz.open()
    page0_xref = doc.new_page(width=595, height=842).xref
    page1_xref = doc.new_page(width=595, height=842).xref
    stream = (
        b"BT /F1 12 Tf 80 Tz 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page0_xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page1_xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    resources = f"<< /Font << /F1 {font_xref} 0 R >> >>"
    doc.xref_set_key(page0_xref, "Resources", resources)
    doc.xref_set_key(page1_xref, "Resources", resources)
    show = _target_show(doc)
    assert show.hscale == 80.0
    assert show.stream_xref == content_xref

    rejection = _plan(doc)

    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.SHARED_CONTENT_STREAM
    assert "1 other page" in rejection.detail
    doc.close()


def test_positive_hscale_does_not_mask_multi_item_tj_gate() -> None:
    """Re-pinned (T16-4X S1): the code was ``NOT_SINGLE_LITERAL_TJ`` until
    the multi-item array got its own gate.  What this test pins is
    unchanged — an admitted ``Tz`` must not swallow the operator gate."""
    doc = _stream_doc(
        b"BT /F1 12 Tf 80 Tz 72 700 Td [(Price ) (2024)] TJ ET"
    )
    show = _target_show(doc)
    assert show.hscale == 80.0
    assert show.operator == "TJ"
    assert show.string_kind == "array"
    assert show.array_item_count == 2

    rejection = _plan(doc)

    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.TJ_MULTI_ITEM_ARRAY
    assert "2 string items" in rejection.detail
    doc.close()


@pytest.mark.parametrize(
    ("operator", "prefix", "detail"),
    [
        ("'", b"14 TL ", "T*"),
        ('"', b"14 TL 1.5 0.25 ", "Tw/Tc"),
    ],
)
def test_positive_hscale_does_not_mask_quote_operator_gates(
    operator: str, prefix: bytes, detail: str
) -> None:
    stream = (
        b"BT /F1 12 Tf 80 Tz 72 700 Td "
        + prefix
        + b"("
        + TARGET.encode()
        + b") "
        + operator.encode()
        + b" ET"
    )
    doc = _stream_doc(stream)
    show = _target_show(doc)
    assert show.hscale == 80.0
    assert show.operator == operator

    rejection = _plan(doc)

    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_SHOW_OPERATOR
    assert detail in rejection.detail
    doc.close()


def test_planner_rejects_show_op_with_no_font_selected():
    """G8: a Tj with no preceding Tf has no face to measure advance with."""
    doc = _stream_doc(b"BT 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.font_resource is None
    assert show.font_size == 0.0
    _assert_only_off_nominal(show)  # only the font selection is off-nominal

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.FONT_FACE_UNAVAILABLE
    # Distinguishes this gate from the resource-lookup gate below, which
    # also fires FONT_FACE_UNAVAILABLE (and would swallow this case:
    # capability(page, None) is None too).
    assert "no font selected" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_font_resource_missing_from_page_resources():
    """G9: Tf names /F9, but the page's /Resources /Font only defines /F1."""
    doc = _stream_doc(b"BT /F9 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET")
    show = _target_show(doc)
    assert show.font_resource == "F9"  # non-None: passes the G8 gate
    _assert_only_off_nominal(show)

    registry = DocumentFontRegistry(doc)
    assert registry.capability(doc[0], "F9") is None
    assert registry.capability(doc[0], "F1") is not None  # the page itself is sound

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.FONT_FACE_UNAVAILABLE
    assert "not resolvable" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


# ---------------------------------------------- inspect.py structural gates


def test_planner_rejects_show_op_outside_bt_et():
    """G5: text shown with no enclosing BT/ET block."""
    doc = _stream_doc(b"/F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj")
    show = _target_show(doc)
    assert show.in_bt is False
    _assert_only_off_nominal(show, "in_bt")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNSUPPORTED_TEXT_STATE
    assert "outside BT/ET" in rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )


def test_planner_rejects_origin_that_depends_on_a_preceding_advance():
    """G6: a second Tj with no repositioning op between the two.

    The target's origin is then the first show's *consumed advance*, which
    the replay does not compute — so the byte range cannot be corroborated
    against page geometry and the plan must refuse.
    """
    doc = _stream_doc(
        b"BT /F1 12 Tf 72 700 Td ("
        + LEAD_IN.encode()
        + b") Tj ("
        + TARGET.encode()
        + b") Tj ET"
    )
    replay = replay_page(doc, doc[0])
    assert not replay.malformed
    assert len(replay.shows) == 2
    # The FIRST show is reliable (Td set the origin); only the second one,
    # which is the target, inherits an untracked advance.
    assert replay.shows[0].origin_reliable is True
    assert replay.shows[0].decoded_bytes == LEAD_IN.encode("latin-1")

    show = _target_show(doc)
    assert show.seq == 1
    assert show.origin_reliable is False
    _assert_only_off_nominal(show, "origin_reliable")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.UNTRACKED_ADVANCE
    assert "preceding show operator" in rejection.detail
    doc.close()

    # Control: the same two shows, with a Td between them.
    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 72 700 Td ("
        + LEAD_IN.encode()
        + b") Tj 0 -14 Td ("
        + TARGET.encode()
        + b") Tj ET"
    )


def test_planner_accepts_uniformly_scaled_text_matrix():
    """G7 (relaxed 2026-08-01): the TeX/dvips idiom is a Tier 0 candidate.

    ``/F1 1 Tf`` with ``10 0 0 10 ... Tm`` renders at 10pt with a *uniform,
    axis-aligned, positive* scale — visually indistinguishable from
    ``/F1 10 Tf``.  The equal-advance proof is scale-invariant (both sides
    are measured in text space and multiplied by the same factor), so this
    shape is admitted; rotation, shear, and reflection are not, and are
    pinned by the two tests below.

    This test was ``test_planner_rejects_uniformly_scaled_text_matrix``
    before the relaxation; it is revised rather than deleted so the
    fixture's isolation guarantee (:func:`_assert_only_off_nominal`) keeps
    covering the same content-stream shape.
    """
    doc = _stream_doc(
        b"BT /F1 1 Tf 10 0 0 10 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.tm == (10.0, 0.0, 0.0, 10.0, 72.0, 700.0)
    assert show.ctm == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # scale is in Tm, not cm
    assert show.font_size == 1.0  # float, per the size-stays-float rule
    assert show.trm_uniform_scale == pytest.approx(10.0)
    _assert_only_off_nominal(show)  # nothing is off-nominal any more

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.font_size == 1.0  # the Tf size, not the effective size
    doc.close()


# Task 13 P2: the blanket G7 refusal became the fail-closed quarter-turn
# admission — every off-axis shape keeps its own stable ``trm_*`` code
# from the transforms gate chain (oblique rotations die at the DIRECTION
# gate, shears at the orthogonality gate).
@pytest.mark.parametrize(
    ("label", "text_matrix", "expected_reason"),
    [
        (
            "rotation_45",
            b"0.7071 0.7071 -0.7071 0.7071",  # b and c both set
            RejectReason.TRM_ROTATION_NOT_QUARTER_TURN,
        ),
        ("shear_b", b"1 0.5 0 1", RejectReason.TRM_SHEARED),  # only b set
        ("shear_c", b"1 0 0.5 1", RejectReason.TRM_SHEARED),  # only c set
    ],
)
def test_planner_rejects_off_axis_text_matrix(label, text_matrix, expected_reason):
    """G7: oblique rotation and shear keep ``a == d > 0`` but are not
    admissible — each with its own code, never a blanket refusal."""
    doc = _stream_doc(
        b"BT /F1 12 Tf " + text_matrix + b" 72 700 Tm ("
        + TARGET.encode()
        + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.tm[0] == pytest.approx(show.tm[3])  # the a == d guard is happy
    assert show.tm[0] > 0.0  # so is the a > 0 guard
    assert show.trm_uniform_scale is None
    _assert_only_off_nominal(show, "trm_uniform_scaled")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == expected_reason
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )


# Task 13 P2: a TRUE reflection (negative determinant) stays fail-closed
# with its own code, while the point reflection (= a 180° rotation, det >
# 0) and the 90° rotation are now ADMITTED as quarter-turn candidates —
# the fallback bbox rides the transformed baseline, so "upside-down"
# text plans correctly instead of being refused wholesale
# (test_text_commit_trm_admission.py pins the full admission story).
# Plan section 2.C (2026-09-29): the binder now ADMITS an orthogonal uniform
# fill-only mirror with a cardinal baseline; this Helvetica fixture is still
# refused because its advance is face-derived (no /Widths), which is not an
# exact equal-advance proof -- the planner's exact-widths gate owns it.
def test_planner_rejects_mirror_text_matrix():
    """G7: a mirror without an exact width proof keeps its own code."""
    doc = _stream_doc(
        b"BT /F1 1 Tf -10 0 0 10 300 400 Tm ("  # a == -d: det < 0
        + TARGET.encode()
        + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.tm[0] <= 0.0
    assert show.trm_uniform_scale is None
    _assert_only_off_nominal(show, "trm_uniform_scaled")

    rejection = _plan(doc)
    assert isinstance(rejection, PlanRejection), rejection
    assert rejection.reason == RejectReason.TRM_REFLECTED
    assert "declares the widths" in rejection.detail, rejection.detail
    doc.close()

    _assert_control_plans_cleanly(
        b"BT /F1 1 Tf 10 0 0 10 300 400 Tm (" + TARGET.encode() + b") Tj ET"
    )


@pytest.mark.parametrize(
    ("label", "text_matrix"),
    [
        ("point_reflection", b"-10 0 0 -10"),  # 180° turn × 10: det > 0
        ("rotation_90", b"0 10 -10 0"),  # quarter turn × 10
    ],
)
def test_planner_admits_quarter_turn_text_matrix(label, text_matrix):
    """Task 13 P2: the quarter-turn family PLANS (was a G7 refusal)."""
    doc = _stream_doc(
        b"BT /F1 1 Tf " + text_matrix + b" 300 400 Tm ("
        + TARGET.encode()
        + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.trm_uniform_scale is None  # replay's Tier 0 idiom flag only
    result = _plan(doc)
    assert isinstance(result, PreparedEdit), result
    assert result.growth_direction in ("right", "left", "up", "down")
    doc.close()


def test_planner_still_admits_replay_uniform_boundary_residuals():
    """Review F2 (red-first): the pre-P2 admitted set stays admitted.

    ``0.000001`` residuals sit exactly ON replay's absolute tolerance
    (``abs(b) > 1e-6`` is False), so the show is ``trm_uniform_scaled``
    and was bound and planned before P2.  The quarter-turn admission's
    RELATIVE shear check would refuse it (|a·c + b·d| = 2e-6 > rel·scale²
    ≈ 1e-6), so the new gate must never run for replay-uniform shows —
    axis-aligned Tier 0/1 behavior stays byte-identical.
    """
    doc = _stream_doc(
        b"BT /F1 1 Tf 1 0.000001 0.000001 1 300 400 Tm ("
        + TARGET.encode()
        + b") Tj ET"
    )
    show = _target_show(doc)
    assert show.trm_uniform_scale is not None  # replay says uniform
    result = _plan(doc)
    assert isinstance(result, PreparedEdit), result
    # The sliver rides the axis path: no cardinal slug is claimed for it.
    assert result.growth_direction is None
    doc.close()


# ------------------------------------------------- fallback target geometry


def _rendered_span_bbox(doc: fitz.Document) -> tuple[float, float, float, float]:
    """MuPDF's own page-space bbox for the target — an independent oracle."""
    for block in doc[0].get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if TARGET in "".join(ch["c"] for ch in span["chars"]):
                    return tuple(span["bbox"])
    raise AssertionError("target span not rendered")


def test_fallback_target_bbox_follows_the_text_matrix_scale():
    """No caller bbox + a scaled Tm: the halo must be in PAGE space.

    ``_advance`` measures in *text* space, so at ``a == d == 0.5`` the
    fallback bbox derived straight from it is twice as wide and twice as
    tall as the glyphs actually painted.  An over-wide halo is the
    dangerous direction: ``verify`` asserts raster identity *outside* it,
    so corruption in the inflated margin is a false ACCEPT.
    """
    doc = _stream_doc(
        b"BT /F1 24 Tf 0.5 0 0 0.5 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    page = doc[0]
    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    text_space_advance = capability.string_width(TARGET, 24.0)
    assert text_space_advance is not None

    prepared = _plan(doc)  # _plan passes target_bbox=None
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page

    assert x1 - x0 == pytest.approx(0.5 * text_space_advance, abs=0.01)
    assert y1 - y0 == pytest.approx(0.5 * 24.0 * 1.35, abs=0.01)
    # Origin (72, 700) in user space is (72, 142) in MuPDF page space.
    assert x0 == pytest.approx(72.0, abs=0.01)
    assert y0 == pytest.approx(142.0 - 0.5 * 24.0, abs=0.01)

    # Independent oracle: MuPDF's own layout of the same stream.
    rx0, _, rx1, _ = _rendered_span_bbox(doc)
    assert x0 == pytest.approx(rx0, abs=1.0)
    assert x1 == pytest.approx(rx1, abs=1.0)
    doc.close()


def test_fallback_target_bbox_includes_the_page_user_unit_scale():
    """No caller bbox + ``/UserUnit != 1``: the page scale counts too.

    MuPDF folds ``/UserUnit`` into ``page.rect`` and
    ``page.transformation_matrix`` (2.0 at ``/UserUnit 2``), so
    ``binding.origin_page`` already carries that factor while ``_advance``
    and ``font_size`` are still text space.  Applying only the Tm scale
    leaves the halo off by the ``/UserUnit`` factor: here the net page
    scale is ``0.5 * 2 == 1`` and the glyphs are full size, so a half-size
    halo makes ``verify`` V0c report the replacement "not extractable at
    the target" and reject a valid edit.
    """
    doc = _stream_doc(
        b"BT /F1 24 Tf 0.5 0 0 0.5 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    doc.xref_set_key(doc[0].xref, "UserUnit", "2")
    page = doc[0]  # re-fetch: the page's transform is read when it is loaded
    matrix = page.transformation_matrix
    assert math.hypot(matrix.a, matrix.b) == pytest.approx(
        2.0
    ), "fixture: /UserUnit did not reach the page transform"

    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    text_space_advance = capability.string_width(TARGET, 24.0)
    assert text_space_advance is not None

    prepared = _plan(doc)  # _plan passes target_bbox=None
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page

    # Net page scale is 0.5 (Tm) * 2 (/UserUnit) == 1: full-size glyphs.
    assert x1 - x0 == pytest.approx(text_space_advance, abs=0.01)
    assert y1 - y0 == pytest.approx(24.0 * 1.35, abs=0.01)
    # Origin (72, 700) in user space is (144, 284) in MuPDF page space.
    assert x0 == pytest.approx(144.0, abs=0.01)
    assert y0 == pytest.approx(284.0 - 24.0, abs=0.01)

    # Independent oracle: MuPDF's own layout of the same stream.
    rx0, _, rx1, _ = _rendered_span_bbox(doc)
    assert x0 == pytest.approx(rx0, abs=1.0)
    assert x1 == pytest.approx(rx1, abs=1.0)
    doc.close()


def test_fallback_target_bbox_is_not_inflated_by_a_sub_unit_user_unit():
    """The *dangerous* direction of the same defect: an inflated halo.

    ``/UserUnit 0.5`` halves the page transform, so ``2 0 0 2 Tm`` again
    nets to page scale 1.  Ignoring the page factor scales the halo by 2 on
    each axis -- 4x the area -- and verification cannot catch that: V0d
    proves raster identity only *outside* the halo, so the inflated margin
    absorbs corruption instead of reporting it.  Pinning both directions
    also pins the multiply: dividing by the page scale passes the
    ``/UserUnit 2`` case above and fails here.
    """
    doc = _stream_doc(
        b"BT /F1 24 Tf 2 0 0 2 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    doc.xref_set_key(doc[0].xref, "UserUnit", "0.5")
    page = doc[0]  # re-fetch: the page's transform is read when it is loaded
    matrix = page.transformation_matrix
    assert math.hypot(matrix.a, matrix.b) == pytest.approx(
        0.5
    ), "fixture: /UserUnit did not reach the page transform"

    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    text_space_advance = capability.string_width(TARGET, 24.0)
    assert text_space_advance is not None

    prepared = _plan(doc)  # _plan passes target_bbox=None
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page

    # Net page scale is 2 (Tm) * 0.5 (/UserUnit) == 1 again.
    assert x1 - x0 == pytest.approx(text_space_advance, abs=0.01)
    assert y1 - y0 == pytest.approx(24.0 * 1.35, abs=0.01)
    # Origin (72, 700) in user space is (36, 71) in MuPDF page space.
    assert x0 == pytest.approx(36.0, abs=0.01)
    assert y0 == pytest.approx(71.0 - 24.0, abs=0.01)

    # Independent oracle: MuPDF's own layout of the same stream.
    rx0, _, rx1, _ = _rendered_span_bbox(doc)
    assert x0 == pytest.approx(rx0, abs=1.0)
    assert x1 == pytest.approx(rx1, abs=1.0)
    doc.close()


def test_fallback_target_bbox_is_unchanged_at_unit_scale():
    """Control: the scale correction must be a no-op at ``a == d == 1``."""
    doc = _stream_doc(
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    capability = DocumentFontRegistry(doc).capability(doc[0], "F1")
    assert capability is not None
    advance = capability.string_width(TARGET, 12.0)

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page
    assert x1 - x0 == pytest.approx(advance, abs=0.01)
    assert y1 - y0 == pytest.approx(12.0 * 1.35, abs=0.01)
    doc.close()


@pytest.mark.parametrize("rotation", [90, 270])
def test_fallback_target_bbox_follows_page_rotate(rotation):
    """No caller bbox + ``/Rotate 90/270``: shape must follow the visual matrix.

    ``page.transformation_matrix`` alone omits /Rotate in PyMuPDF; the
    fallback must also apply the page frame's quarter turn so the halo
    matches pixmap ink (vertical under 90/270). Building from unrotated
    ``origin_page`` along page-x leaves a horizontal halo while glyphs run
    vertically in visual space. This page is uncropped at ``/UserUnit`` 1,
    the one shape where PyMuPDF's own matrices still agree with the frame;
    rotated CROPPED and ``/UserUnit`` pages are pinned against pixmap ink
    in ``test_text_commit_visual_frame.py``.
    """
    doc = _stream_doc(
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (" + TARGET.encode() + b") Tj ET"
    )
    doc[0].set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    doc = fitz.open("pdf", data)
    page = doc[0]
    assert page.rotation == rotation

    capability = DocumentFontRegistry(doc).capability(page, "F1")
    assert capability is not None
    advance = capability.string_width(TARGET, 12.0)
    assert advance is not None
    # Analytic oracle: same user-space construction the planner must use,
    # mapped through the full visual matrix (not rawdict — glyph ink ≠ the
    # 1.0/0.35 ascent/descent heuristic).
    user = fitz.Rect(72.0, 700.0 - 0.35 * 12.0, 72.0 + advance, 700.0 + 12.0)
    frame = page_visual_frame(page)
    assert tuple(frame.visual) == tuple(
        page.transformation_matrix * page.rotation_matrix
    ), "premise: the chains agree on an uncropped /UserUnit-1 page"
    expected = user * frame.visual

    prepared = _plan(doc)
    assert isinstance(prepared, PreparedEdit), prepared
    x0, y0, x1, y1 = prepared.target_bbox_page
    assert x0 == pytest.approx(expected.x0, abs=0.05)
    assert y0 == pytest.approx(expected.y0, abs=0.05)
    assert x1 == pytest.approx(expected.x1, abs=0.05)
    assert y1 == pytest.approx(expected.y1, abs=0.05)
    # Orientation: under 90/270 the advance runs along a visual axis where
    # height dominates width (the broken formula keeps width >> height).
    assert (y1 - y0) > (x1 - x0)

    # Independent: first dark pixmap pixels must sit inside the halo.
    pix = page.get_pixmap(dpi=72)
    samples = bytes(pix.samples)
    n = pix.n
    found = False
    for y in range(pix.height):
        for x in range(pix.width):
            i = (y * pix.width + x) * n
            if samples[i] < 200:
                assert x0 - 2.0 <= x <= x1 + 2.0
                assert y0 - 2.0 <= y <= y1 + 2.0
                found = True
                break
        if found:
            break
    assert found, "fixture: no dark pixmap pixels found"
    doc.close()


def test_reject_reason_growth_outside_page_constant_exists():
    """GROWTH_OUTSIDE_PAGE is a defined RejectReason constant."""
    assert hasattr(RejectReason, "GROWTH_OUTSIDE_PAGE")
    assert RejectReason.GROWTH_OUTSIDE_PAGE == "growth_outside_page"


# ------------------------------------------- the extracted show-level ladder


@pytest.mark.parametrize(
    ("label", "stream"),
    [
        ("render_mode_2", b"BT /F1 12 Tf 2 Tr 72 700 Td (" + TARGET.encode()
         + b") Tj ET"),
        ("array_tj", b"BT /F1 12 Tf 72 700 Td [(Price ) (2024)] TJ ET"),
    ],
)
def test_tier0_show_gate_is_the_classifier_ladder(label, stream):
    """T16-4X S1 §8.6: ``plan.tier0_show_gate`` IS the ladder that
    ``_classify_common`` runs, not a second copy of it.

    Called directly on the same show ``prepare_tier0_plan`` binds, it must
    return the identical code AND the identical detail string — the audit
    instrument reports whatever this function says, so a divergence here is
    exactly the "audit mirrors a gate" staleness the extraction removes.
    The control leg proves an admissible show yields the capability rather
    than a rejection, so the pin cannot pass by refusing everything.
    """
    doc = _stream_doc(stream)
    page = doc[0]
    show = _target_show(doc)
    replay = replay_page(doc, page)

    admission = tier0_show_gate(
        doc,
        page,
        show,
        wrappers=replay.wrappers_for(show),
        emc_underflows=replay.mc_emc_underflows,
        registry=DocumentFontRegistry(doc),
    )
    production = _plan(doc)

    assert isinstance(production, PlanRejection), production
    assert isinstance(admission, PlanRejection), admission
    assert admission.reason == production.reason
    assert admission.detail == production.detail
    doc.close()


def test_tier0_show_gate_admits_the_clean_control_with_its_capability():
    """The admitted arm returns ``ShowGateAdmission`` carrying the same
    capability ``_classify_common`` continues with."""
    doc = _stream_doc(b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET")
    page = doc[0]
    show = _target_show(doc)
    replay = replay_page(doc, page)
    registry = DocumentFontRegistry(doc)

    admission = tier0_show_gate(
        doc,
        page,
        show,
        wrappers=replay.wrappers_for(show),
        emc_underflows=replay.mc_emc_underflows,
        registry=registry,
    )

    assert isinstance(admission, ShowGateAdmission), admission
    assert admission.capability is registry.capability(page, "F1")
    assert isinstance(_plan(doc), PreparedEdit)
    doc.close()
