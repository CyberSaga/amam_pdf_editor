"""Task 16-4X S0 (plan §1.4) — production-parity red matrix for
``scripts/audit_tier_coverage.py``.

The audit's per-show classifier used to MIRROR two production admission
gates by folding ``show.mc_depth != 0`` and ``not show.trm_uniform_scaled``
straight into ``UNSUPPORTED_TEXT_STATE`` -- a fold written before Task 13
P1 (default-visible pure ``/OC`` layers admitted via
``marked_content.admit_show_wrappers``) and Task 13 P2 (quarter-turn TRMs
admitted via ``transforms.admission_verdict``).  That made the audit
report every marked-content-wrapped or rotated show as
``unsupported_text_state`` regardless of what production would actually
do with it (measured 2026-09-06: CAD-drawing fixture 28043/28043,
office-report fixture 2237/2237, both ``unsupported_text_state`` -- not
the production verdict).

These tests pin that the classifier now calls the SAME two production
functions instead of re-deriving them: a struct-content ``/P <</MCID>>``
wrapper refuses under its OWN code (``mc_wrapper_not_pure_layer``), and a
default-visible pure ``/OC`` layer -- the one class Task 13 P1 actually
admits -- classifies ``tier0_eligible``.
"""
from __future__ import annotations

import fitz
import pytest

from model.text_commit.dto import RejectReason
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit import plan as plan_mod
from model.text_commit.inspect import read_page_streams
from model.text_commit.plan import PlanRejection, prepare_plan, prepare_tier0_plan
from model.text_commit.replay import replay_page_streams
from model.text_commit.transforms import page_visual_frame_or_none
from scripts import audit_tier_coverage as audit_tier_coverage_mod
from scripts.audit_tier_coverage import _classify_show, audit_document
from test_scripts.type0_fixture_builder import (
    build_identity_h_fixture,
    install_oc_layer,
    wrap_content_in_marked_content,
)

HELLO = "Hello"


def _struct_content_wrapped_doc() -> fitz.Document:
    """One page: a plain literal ``Tj`` wrapped in a struct-content span.

    Pattern of ``test_text_commit_tier0.py::_tier0_doc`` (a raw stream,
    one Helvetica/WinAnsi literal ``Tj``, hand-built resources) with the
    show additionally wrapped in ``/P <</MCID 0>> BDC ... EMC`` -- the
    shape the census (plan §1.2) found on 100% of Office-exported shows.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"/P <</MCID 0>> BDC "
        b"BT /F1 12 Tf 72 700 Td (" + HELLO.encode() + b") Tj ET "
        b"EMC"
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


def _rotated_tm_doc() -> fitz.Document:
    """One literal ``Tj`` under a quarter-turn ``Tm`` (page ``/Rotate`` 0).

    ``replay.ShowOp.trm_uniform_scaled`` is ``False`` for ANY rotation
    (replay's own classification, not the page's ``/Rotate``), so this is
    the discriminator for the TRM fold: the old code folded
    ``not show.trm_uniform_scaled`` straight into
    ``UNSUPPORTED_TEXT_STATE``, while production (Task 13 P2) instead
    proves the combined TM is a cardinal quarter turn via
    ``transforms.admission_verdict`` and admits it. A rotated *page*
    (``/Rotate 90``) would NOT discriminate: the rotation lives in the
    page dict, not the TM, so ``trm_uniform_scaled`` stays ``True`` and
    the old fold would never fire -- the TM itself must carry the turn.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 0 1 -1 0 72 700 Tm (" + HELLO.encode() + b") Tj ET"
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


def test_rotated_tm_is_admitted_via_admission_verdict_not_folded() -> None:
    """A replay-non-uniform (rotated) TM that is nonetheless a cardinal
    quarter turn must classify ``tier0_eligible`` -- proof that the TRM
    check now calls ``admission_verdict`` instead of refusing on
    ``not show.trm_uniform_scaled`` alone (measured: reports
    ``unsupported_text_state`` before this fix, ``tier0_eligible`` after)."""
    doc = _rotated_tm_doc()
    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["shows_total"] == 1
    assert row["reject_reason_counts"] == {}
    assert row["tier0_eligible"] == 1


def test_struct_content_wrapper_reports_its_own_production_code() -> None:
    """A ``/P <</MCID>>`` span must refuse ``mc_wrapper_not_pure_layer``
    -- the code ``admit_show_wrappers`` actually emits for this class --
    never the stale mirror's ``unsupported_text_state``."""
    doc = _struct_content_wrapped_doc()
    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["shows_total"] == 1
    assert row["tier0_eligible"] == 0
    assert row["reject_reason_counts"] == {"mc_wrapper_not_pure_layer": 1}


def test_default_visible_oc_layer_show_is_tier0_eligible() -> None:
    """Task 13 P1's admitted class -- a default-visible pure ``/OC``
    layer wrapping a single hex ``Tj`` -- must classify ``tier0_eligible``
    on the audit too, not fall into ``unsupported_text_state``."""
    fixture = build_identity_h_fixture()
    install_oc_layer(fixture, name="Lyr7Q", label="L7Q", on=True)
    wrap_content_in_marked_content(fixture, "/OC /Lyr7Q BDC")

    try:
        rows = audit_document(fixture.doc)
    finally:
        fixture.doc.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["shows_total"] == 1
    assert row["reject_reason_counts"] == {}
    assert row["tier0_eligible"] == 1


def _two_mc_wrapped_shows_doc() -> fitz.Document:
    """Two shows, each in its OWN ``/P <</MCID n>> BDC ... EMC`` span:
    (i) a MULTI-item array ``[(a) (b)] TJ``; (ii) a mode-2 literal
    ``2 Tr (cd) Tj``. Neither show's own defect (multi-item array,
    non-zero render mode) is about marked content, so the MC wrapper must
    never outrank it in the reason ladder.

    The first show was the single-item ``[(ab)] TJ`` until T16-4X S1
    admitted that shape at the operator gate -- it would now reach
    ``admit_show_wrappers`` and report the WRAPPER code, which is the
    opposite of what these two tests exist to prove. The array keeps the
    same decoded bytes (``ab``) and the same position in the ladder; only
    its item count changed.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td /P <</MCID 0>> BDC "
        b"[(a) (b)] TJ"
        b" EMC ET "
        b"BT /F1 12 Tf 72 680 Td /P <</MCID 1>> BDC "
        b"2 Tr (cd) Tj"
        b" EMC ET"
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


def test_reason_ladder_matches_production_order_for_mc_wrapped_shows() -> None:
    """F2: the audit's reason ladder must rank exactly like production
    (``plan.py::_classify_common`` / ``inspect.py::bind_source_text``) --
    the operator gate (``NOT_SINGLE_LITERAL_TJ``) and the render-mode gate
    (``UNSUPPORTED_TEXT_STATE``) both fire BEFORE ``admit_show_wrappers``,
    so an MC-wrapped array-TJ or mode-2 show must never report
    ``mc_wrapper_not_pure_layer``.

    The expected code per show is PINNED (not just "audit == production"):
    (i) ``[(a) (b)] TJ`` -> ``tj_multi_item_array`` (the array-TJ operator
    gate fires before the wrapper is ever read; it was
    ``not_single_literal_tj`` on a single-item array until T16-4X S1 gave
    the multi-item shape its own code and admitted the single-item one)
    and (ii) ``2 Tr (cd) Tj`` -> ``stroke_bound_too_large`` (the
    render-mode rung's pen proof; it was ``unsupported_text_state`` until
    T16-4 Steps 7-8 admitted mode 2 with a PROVEN pen -- this fixture
    writes no ``w``, so replay's default pen, 1.0 w at 10 M against a
    ``0.5 * 12`` ceiling, is proven too fat). A bare audit-vs-production
    equality would also pass if both sides agreed on the WRONG shared code,
    which is exactly the failure mode this fixture was built to catch.
    """
    doc = _two_mc_wrapped_shows_doc()
    expected = {
        "ab": RejectReason.TJ_MULTI_ITEM_ARRAY,
        "cd": RejectReason.STROKE_BOUND_TOO_LARGE,
    }
    try:
        page = doc[0]
        registry = DocumentFontRegistry(doc)
        streams = read_page_streams(doc, page)
        replay = replay_page_streams(streams, max_decoded_bytes=None)
        frame = page_visual_frame_or_none(page)
        assert frame is not None
        assert len(replay.shows) == 2
        # Fixture sanity: fail loudly on shape drift instead of silently
        # re-pairing show <-> target_text through the zip below.
        assert replay.shows[0].operator == "TJ"
        assert replay.shows[1].operator == "Tj"
        assert replay.shows[1].render_mode == 2

        for show, target_text in zip(replay.shows, ("ab", "cd")):
            _tier, audit_reason = _classify_show(
                doc, page, replay, show, registry, frame
            )

            production = prepare_tier0_plan(
                doc,
                page,
                target_text=target_text,
                replacement_text=target_text[::-1],
                expected_origin=None,
                target_bbox=None,
                registry=registry,
            )
            assert isinstance(production, PlanRejection), (
                f"expected {target_text!r} to be refused by production; "
                f"got {production!r}"
            )
            assert production.reason == expected[target_text], (
                f"target={target_text!r} production={production.reason} "
                f"expected={expected[target_text]}"
            )
            assert audit_reason == production.reason, (
                f"target={target_text!r} audit={audit_reason} "
                f"production={production.reason}"
            )
    finally:
        doc.close()


def _tj_shape_doc(items: bytes) -> fitz.Document:
    """One page whose only show is ``[<items>] TJ`` with /F1 = Helvetica."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 72 700 Td [" + items + b"] TJ ET"
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


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (b"(He) (llo)", RejectReason.TJ_MULTI_ITEM_ARRAY),
        (b"-3000 (Hello)", RejectReason.TJ_LEADING_KERN_UNPROVEN),
        (b"(Hello)", None),
    ],
    ids=["multi_item", "leading_kern", "single_item_admitted"],
)
def test_audit_inherits_the_tj_operator_gate_without_an_audit_edit(
    items: bytes, expected: str | None
) -> None:
    """The audit calls ``plan.tier0_show_gate``, so a slice that moves that
    ladder moves the instrument with it (glyph-coverage plan section 8.6:
    "an audit that mirrors a gate goes stale the day the gate moves").

    The two codes T16-4X S1 introduces are reported by the audit with NO
    change to ``scripts/audit_tier_coverage.py``, and the admitted shape
    becomes Tier 0 headroom -- pinned per shape, not as a bare
    audit-vs-production equality.
    """
    doc = _tj_shape_doc(items)
    try:
        row = audit_document(doc)[0]
        assert row["shows_total"] == 1
        if expected is None:
            assert row["tier0_eligible"] == 1
            assert row["reject_reason_counts"] == {}
        else:
            assert row["tier0_ineligible"] == 1
            assert row["reject_reason_counts"] == {expected: 1}
    finally:
        doc.close()


def _mode2_doc(state: bytes) -> fitz.Document:
    """One page whose only show is ``<state> (Hello) Tj`` at 24 pt.

    24 pt, not 12: the pen ceiling is ``0.5 * font_size`` and replay's
    default pen is ``1.0 w`` at ``10 M``, so a 12 pt page would refuse
    ``stroke_bound_too_large`` before either case under test is reached.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 24 Tf " + state + b" 72 700 Td (Hello) Tj ET"
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


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (b"2 Tr 1 w", None),
        (b"2 Tr 0 w", RejectReason.STROKE_BOUND_UNPROVEN),
    ],
    ids=["proven_pen_is_headroom", "hairline_pen_is_unproven"],
)
def test_audit_inherits_the_render_mode_ladder_without_an_audit_edit(
    state: bytes, expected: str | None
) -> None:
    """T16-4 Steps 7-8, same parity property as the ``TJ`` gate above.

    The audit calls ``plan.tier0_show_gate``, which since this slice owns
    the render-mode ladder AND the mode-2 pen proof -- so a mode-2 show
    with a provable pen becomes Tier 0 headroom, and a ``0 w`` hairline
    reports the new ``stroke_bound_unproven`` code, with NO change to
    ``scripts/audit_tier_coverage.py``.  The audit passes no ``frame``;
    the gate derives one for its own mode-2 rung, which is what lets the
    instrument inherit a gate whose evidence it never held.
    """
    doc = _mode2_doc(state)
    try:
        row = audit_document(doc)[0]
        assert row["shows_total"] == 1
        if expected is None:
            assert row["tier0_eligible"] == 1
            assert row["reject_reason_counts"] == {}
        else:
            assert row["tier0_ineligible"] == 1
            assert row["reject_reason_counts"] == {expected: 1}
    finally:
        doc.close()


def _user_unit_zero_doc() -> fitz.Document:
    """One plain literal ``Tj`` on a page whose ``/UserUnit`` is ``0`` --
    ``transforms.page_visual_frame`` refuses this shape
    (``UnsupportedPageGeometryError``: "/UserUnit is not a usable positive
    scale"), so the page's visual frame can never be proven.
    """
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
    doc.xref_set_key(page.xref, "UserUnit", "0")
    return doc


def test_unprovable_page_frame_refuses_every_show_first() -> None:
    """An unprovable page frame refuses before show-level checks."""
    doc = _user_unit_zero_doc()
    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["shows_total"] == 1
    assert row["tier0_eligible"] == 0
    assert row["tier0_ineligible"] == 1
    assert row["reject_reason_counts"] == {"page_geometry_unsupported": 1}


def _three_shows_one_resource_doc() -> fitz.Document:
    """Three literal ``Tj`` shows on one page, all using font resource
    ``/F1`` -- for T1's per-page-per-resource memoization pin."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + HELLO.encode() + b") Tj "
        b"0 -20 Td (" + HELLO.encode() + b") Tj "
        b"0 -20 Td (" + HELLO.encode() + b") Tj ET"
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


def test_capability_lookup_memoized_per_page_per_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T1: ``registry.capability()`` must be called once per (page,
    font_resource), not once per show -- three shows sharing ``/F1`` must
    cost one digest, not three (model/text_commit/inspect.py's
    ``_cid_show_candidates`` pattern)."""
    doc = _three_shows_one_resource_doc()

    calls: list[str] = []
    real_capability = DocumentFontRegistry.capability

    def _counting_capability(self, page, resource_name):  # noqa: ANN001
        calls.append(resource_name)
        return real_capability(self, page, resource_name)

    monkeypatch.setattr(DocumentFontRegistry, "capability", _counting_capability)

    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert len(calls) == 1, calls
    row = rows[0]
    assert row["shows_total"] == 3
    # The memo must actually be SERVING every show, not just being called
    # once while every other show silently falls back to no capability.
    assert row["tier0_eligible"] == 3
    assert row["reject_reason_counts"] == {}


def _six_shows_two_resources_doc() -> fitz.Document:
    """Six literal ``Tj`` shows over TWO font resources (three each).

    The discriminator the single-resource pin above cannot supply: with one
    resource, ``len(calls) == 1`` also holds for a wrapper that merely
    delegates without remembering anything. Two resources x three shows
    must still cost exactly two lookups.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    body = b""
    for index in range(6):
        resource = b"/F1" if index % 2 == 0 else b"/F2"
        body += (
            resource + b" 12 Tf 0 -20 Td (" + HELLO.encode() + b") Tj "
        )
    stream = b"BT 72 700 Td " + body + b"ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    xrefs = []
    for basefont in ("Helvetica", "Courier"):
        font_xref = doc.get_new_xref()
        doc.update_object(
            font_xref,
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{basefont} "
            "/Encoding /WinAnsiEncoding >>",
        )
        xrefs.append(font_xref)
    doc.xref_set_key(
        page.xref,
        "Resources",
        f"<< /Font << /F1 {xrefs[0]} 0 R /F2 {xrefs[1]} 0 R >> >>",
    )
    return doc


def test_capability_memo_serves_every_resource_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The memo must SUPPRESS repeat lookups, not merely funnel them.

    Added with the ``tier0_show_gate`` extraction: the gate resolves the
    show's font itself, so the memo moved under ``registry.capability``.
    Six shows over two resources must cost exactly two lookups, one per
    resource, and every show must still be classified.
    """
    doc = _six_shows_two_resources_doc()

    calls: list[str] = []
    real_capability = DocumentFontRegistry.capability

    def _counting_capability(self, page, resource_name):  # noqa: ANN001
        calls.append(resource_name)
        return real_capability(self, page, resource_name)

    monkeypatch.setattr(DocumentFontRegistry, "capability", _counting_capability)

    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert sorted(calls) == ["F1", "F2"], calls
    row = rows[0]
    assert row["shows_total"] == 6
    assert row["tier0_eligible"] == 6
    assert row["reject_reason_counts"] == {}


def test_mc_admission_is_skipped_after_an_earlier_structural_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither rejected show reaches MC admission in the shared planner.

    Re-pinned when the show-level ladder was extracted into
    ``plan.tier0_show_gate``: the audit no longer holds its own reference to
    ``admit_show_wrappers``, so the counter goes on the module that now
    calls it. The property under test is unchanged -- the operator and
    render-mode gates fire first, so the wrapper is never read.
    """
    doc = _two_mc_wrapped_shows_doc()

    calls: list[str] = []
    real_admit = plan_mod.admit_show_wrappers

    def _counting_admit(doc_, page_, show_, *, wrappers, emc_underflows):
        calls.append(show_.operator)
        return real_admit(
            doc_, page_, show_, wrappers=wrappers, emc_underflows=emc_underflows
        )

    monkeypatch.setattr(plan_mod, "admit_show_wrappers", _counting_admit)

    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert calls == [], calls

    row = rows[0]
    assert row["shows_total"] == 2
    # Re-pinned again (T16-4 Steps 7-8): the mode-2 show now refuses on the
    # pen proof inside the same rung (default pen too fat at 12 pt), which
    # still fires BEFORE the wrapper is read -- the property under test.
    assert row["reject_reason_counts"] == {
        "tj_multi_item_array": 1,
        "stroke_bound_too_large": 1,
    }


def test_tj_rejected_by_both_tiers_is_not_reported_as_tier1_headroom() -> None:
    """Re-pinned (T16-4X S1): the shape was ``[(Hello)] TJ``, which the
    operator gate now ADMITS (measured: a Tier 0 ``PreparedEdit``), so it
    can no longer stand for "refused by both tiers". A multi-item array is
    the same refusal one rung along -- ``tj_multi_item_array`` instead of
    ``not_single_literal_tj`` -- and the property under test (a both-tier
    refusal is never counted as Tier 1 headroom) is untouched."""
    with _rotated_tm_doc() as doc:
        page = doc[0]
        xref = page.get_contents()[0]
        doc.update_stream(
            xref,
            doc.xref_stream(xref).replace(b"(Hello) Tj", b"[(He) (llo)] TJ"),
        )
        before = doc.xref_stream(xref)
        production = prepare_plan(
            doc, page, target_text=HELLO, replacement_text=HELLO[::-1],
            expected_origin=None, target_bbox=None,
            registry=DocumentFontRegistry(doc), max_tier=1,
        )
        assert isinstance(production, PlanRejection)
        assert production.reason == RejectReason.TJ_MULTI_ITEM_ARRAY
        row = audit_document(doc)[0]
        assert "tier1_candidate" not in row  # category deleted in S0, not zeroed
        assert row["tier0_ineligible"] == 1
        assert row["reject_reason_counts"] == {production.reason: 1}
        assert doc.xref_stream(xref) == before


def test_type0_literal_operand_is_not_structurally_eligible() -> None:
    fixture = build_identity_h_fixture()
    with fixture.doc as doc:
        encoded = fixture.encoded
        literal = b"(" + b"".join(f"\\{value:03o}".encode("ascii") for value in encoded) + b")"
        source = fixture.content_bytes()
        show = replay_page_streams(read_page_streams(doc, fixture.page)).shows[0]
        doc.update_stream(
            fixture.content_xref,
            source[:show.string_start] + literal + source[show.string_end:],
        )
        replay = replay_page_streams(read_page_streams(doc, fixture.page))
        assert replay.shows[0].string_kind == "literal"
        assert fixture.text in fixture.page.get_text()
        production = prepare_plan(
            doc, fixture.page, target_text=fixture.text,
            replacement_text=fixture.text[::-1], expected_origin=None,
            target_bbox=None, registry=DocumentFontRegistry(doc), max_tier=1,
        )
        assert isinstance(production, PlanRejection)
        assert production.reason == RejectReason.NOT_SINGLE_LITERAL_TJ
        row = audit_document(doc)[0]
        assert row["tier0_eligible"] == 0
        assert row["reject_reason_counts"] == {production.reason: 1}


def _plain_tj_doc() -> fitz.Document:
    """One plain Helvetica/WinAnsi literal ``(Hello) Tj`` -- the shape that
    reaches EVERY gate of the show-level ladder without tripping one, so a
    sentinel injected into any gate is the only thing the row can report."""
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


def test_audit_show_ladder_is_the_production_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S1 §8.6: the audit must CALL ``plan.tier0_show_gate``, not mirror it.

    A hand-mirrored ladder goes stale the day a slice moves a gate
    (docs/PITFALLS.md, "an audit that mirrors a gate goes stale"). The only
    mirror-proof pin is behavioural: replace the production function with a
    sentinel refusal and require the audit row to report the sentinel's
    code. A mirror keeps reporting ``tier0_eligible`` and fails.
    """
    doc = _plain_tj_doc()
    sentinel = PlanRejection(RejectReason.SHARED_CONTENT_STREAM, "sentinel")

    def _sentinel_gate(*args: object, **kwargs: object) -> PlanRejection:
        return sentinel

    monkeypatch.setattr(audit_tier_coverage_mod, "tier0_show_gate", _sentinel_gate)

    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["shows_total"] == 1
    assert row["tier0_eligible"] == 0
    assert row["reject_reason_counts"] == {RejectReason.SHARED_CONTENT_STREAM: 1}


def test_audit_trm_exception_is_the_production_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same contract for the replay-uniform TRM exception: the audit must
    call ``inspect.trm_bind_rejection`` (``bind_source_text``'s own
    predicate) rather than keep a copy of its three-line fold."""
    doc = _plain_tj_doc()

    def _sentinel_trm(*args: object, **kwargs: object) -> str:
        return RejectReason.TRM_SINGULAR

    monkeypatch.setattr(audit_tier_coverage_mod, "trm_bind_rejection", _sentinel_trm)

    try:
        rows = audit_document(doc)
    finally:
        doc.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["shows_total"] == 1
    assert row["tier0_eligible"] == 0
    assert row["reject_reason_counts"] == {RejectReason.TRM_SINGULAR: 1}


def _quote_operator_doc() -> fitz.Document:
    """One quote-operator show (``(Hello) '``) after ``14 TL``."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 14 TL 72 700 Td (" + HELLO.encode() + b") ' ET"
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


def test_quote_operator_reports_the_production_operator_code() -> None:
    """Review fold 3: production refuses the quote operators as
    ``UNSUPPORTED_SHOW_OPERATOR`` (plan.py, before the Tj gate); the audit
    folded them into ``NOT_SINGLE_LITERAL_TJ``. Pinned to the production
    code, not to mere audit==production equality."""
    doc = _quote_operator_doc()
    try:
        page = doc[0]
        registry = DocumentFontRegistry(doc)
        replay = replay_page_streams(read_page_streams(doc, page), max_decoded_bytes=None)
        frame = page_visual_frame_or_none(page)
        assert frame is not None
        assert len(replay.shows) == 1 and replay.shows[0].operator == "'"
        show = replay.shows[0]
        _tier, audit_reason = _classify_show(doc, page, replay, show, registry, frame)
        production = prepare_tier0_plan(
            doc, page, target_text=HELLO, replacement_text=HELLO[::-1],
            expected_origin=None, target_bbox=None, registry=registry,
        )
        assert isinstance(production, PlanRejection)
        assert production.reason == RejectReason.UNSUPPORTED_SHOW_OPERATOR
        assert audit_reason == production.reason
    finally:
        doc.close()
