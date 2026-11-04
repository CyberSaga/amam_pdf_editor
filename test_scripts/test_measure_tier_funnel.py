"""Production-parity pins for ``scripts/measure_tier_funnel.py`` (T16-4X S0).

The funnel used to MIRROR two production stages instead of calling them,
and both mirrors went stale (plan
``plans/task16-4-glyph-coverage-expansion.md`` §1.1 and §1.4):

* the bind mirror omitted ``bind_source_text``'s CID leg, so every CJK
  target was counted ``undecodable_target`` (623/1265 of the 2026-09-06
  sample);
* the plan mirror ran ``prepare_tier0_plan``'s gates in a non-production
  order and folded ``mc_depth != 0`` into ``unsupported_text_state``,
  i.e. it predated the Task 13 P1 marked-content admission and never
  called ``admit_show_wrappers``.

These tests hold the script to the production calls: the funnel's
bind-stage and plan-stage verdicts must equal what
``model.text_commit.inspect.bind_source_text`` and
``model.text_commit.plan.prepare_tier0_plan`` say about the same target.

(T16-4X S0 F6: the funnel itself now calls
``plan.prepare_plan(..., max_tier=0, evidence_cache=...)`` rather than
``prepare_tier0_plan`` directly, to reuse one replay per page across
samples instead of re-replaying per sample. ``max_tier=0`` makes the two
calls verdict-equivalent (plan.py ~1596-1600), so ``_production_plan_reasons``
below deliberately keeps calling ``prepare_tier0_plan`` -- an independent
oracle, not the code path under test -- rather than switching to
``prepare_plan`` too, which would let both sides drift together silently.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "test_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "test_scripts"))

import model.pdf_text_edit as pdf_text_edit  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PlanRejection, prepare_tier0_plan  # noqa: E402
from scripts import measure_tier_funnel  # noqa: E402
from type0_fixture_builder import CJK_TEXT, build_identity_h_fixture  # noqa: E402

TARGET = "Hello"
PALINDROME = "aba"


def _simple_font_doc(body: bytes) -> fitz.Document:
    """One page whose whole content stream is ``body`` (Helvetica ``/F1``).

    Same hand-authored shape as ``test_text_commit_tier0.py::_tier0_doc``:
    PyMuPDF's own writers never emit a bare ``Tj``, so the operator shapes
    this suite measures have to be written by hand.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, body)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _marked_content_doc(show_op: bytes) -> fitz.Document:
    """``show_op`` wrapped in a ``/P <</MCID 0>> BDC`` structure wrapper."""
    return _simple_font_doc(
        b"BT /F1 12 Tf 72 700 Td /P <</MCID 0>> BDC " + show_op + b" EMC ET"
    )


def _resolve_targets(doc: fitz.Document, page_idx: int = 0) -> list:
    """The funnel's own resolve stage, so the target text/origin/bbox handed
    to the production call is identical to the funnel's."""
    model = measure_tier_funnel._StubModel(doc)
    runs = model.block_manager.get_runs(page_idx)
    samples, _lines, _runs = measure_tier_funnel._line_and_run_samples(runs, 30, 60)
    targets = []
    for member_ids in samples:
        resolve_result = measure_tier_funnel._build_resolve_result(runs, member_ids)
        target = measure_tier_funnel._tier0_target_from_resolve(
            model, page_idx, resolve_result
        )
        if target is not None:
            targets.append(target)
    return targets


def _production_plan_reasons(doc: fitz.Document) -> list[str | None]:
    """``prepare_tier0_plan``'s verdict per resolved target, reversed
    replacement -- ``None`` where it accepts.  Only ``.reason`` is read:
    ``.detail`` can carry a basefont name (§10 privacy).

    Deliberately calls ``prepare_tier0_plan`` directly, NOT
    ``plan.prepare_plan`` (what the funnel itself calls since F6) -- this
    is the independent oracle, and switching it to the same entry point
    the funnel uses would let both sides drift together silently instead
    of proving they agree."""
    registry = DocumentFontRegistry(doc)
    page = doc[0]
    reasons: list[str | None] = []
    for target in _resolve_targets(doc):
        result = prepare_tier0_plan(
            doc,
            page,
            target_text=target.text,
            replacement_text=target.text[::-1],
            expected_origin=target.origin,
            target_bbox=target.bbox,
            registry=registry,
        )
        reasons.append(result.reason if isinstance(result, PlanRejection) else None)
    return reasons


@pytest.mark.parametrize(
    "show_op",
    [b"[(Hello)] TJ", b"(Hello) Tj"],
    ids=["array_tj", "literal_tj"],
)
def test_plan_stage_reason_equals_production_classifier(show_op: bytes) -> None:
    """The funnel's plan-stage reason == ``prepare_tier0_plan``'s reason.

    ``array_tj`` is the shape §1.1 measured (both sides say
    ``not_single_literal_tj`` today -- the pin is the equality, not the
    code).  ``literal_tj`` is where the stale mirror diverges: production
    reaches ``admit_show_wrappers`` and refuses the ``/P`` structure
    wrapper by name, while the mirror folds ``mc_depth != 0`` into
    ``unsupported_text_state`` (§1.4).
    """
    doc = _marked_content_doc(show_op)
    try:
        row = measure_tier_funnel.measure_document(doc, 30, 60)
        funnel = row["funnel"]
        expected = _production_plan_reasons(doc)
        assert funnel["samples_total"] == len(expected) == 2
        assert funnel["bind_survivors"] == 2, funnel["bind_fail_reasons"]
        assert expected[0] is not None and set(expected) == {expected[0]}
        assert funnel["plan_fail_reasons"] == {expected[0]: 2}
        assert funnel["plan_survivors"] == 0
    finally:
        doc.close()


def test_bind_stage_runs_the_production_cid_leg() -> None:
    """A CJK target must not count as ``undecodable_target``.

    ``bind_source_text`` decodes Type0/Identity-H shows through the
    registry's ToUnicode evidence; the funnel's mirror had no registry, so
    every CJK target failed at the latin-1 gate (§1.1's 623/1265).
    """
    doc = build_identity_h_fixture().doc
    try:
        row = measure_tier_funnel.measure_document(doc, 30, 60)
        funnel = row["funnel"]
        assert funnel["samples_total"] == 2
        assert "undecodable_target" not in funnel["bind_fail_reasons"]
        assert funnel["bind_survivors"] == 2, funnel["bind_fail_reasons"]
        assert CJK_TEXT  # the fixture's target really is non-latin-1
    finally:
        doc.close()


def test_palindromic_target_is_bucketed_not_a_plan_failure() -> None:
    """A reversed replacement equals its source only for a palindrome; that
    trips ``NO_CHANGE`` -- production's FIRST, request-level gate -- which
    is a property of the probe, not of the document, so it gets its own
    bucket and (review fold 3) leaves the funnel before bind, in the same
    position production would refuse it."""
    doc = _simple_font_doc(
        b"BT /F1 12 Tf 72 700 Td (" + PALINDROME.encode() + b") Tj ET"
    )
    try:
        row = measure_tier_funnel.measure_document(doc, 30, 60)
        funnel = row["funnel"]
        assert funnel["resolve_survivors"] == 2
        assert funnel["palindrome_skipped"] == 2
        assert funnel["bind_survivors"] == 0
        assert funnel["bind_fail_reasons"] == {}
        assert funnel["plan_attempted"] == 0
        assert funnel["plan_fail_reasons"] == {}
        assert funnel["plan_survivors"] == 0
    finally:
        doc.close()


def test_reversed_replacement_reaches_and_passes_the_advance_gate() -> None:
    """The accept branch, and the premise the whole probe rests on.

    An unwrapped literal ``Tj`` is the one shape on this corpus that gets
    past the operator gate, so it is the only place the reversed
    replacement can be shown to survive ``_build_tier0``'s advance-equality
    check.  Reversing preserves the glyph multiset and the space count, so
    the /Widths sum and the ``Tc``/``Tw`` terms are identical and
    ``ADVANCE_MISMATCH`` cannot fire -- if that premise were wrong the code
    would show up here and nowhere else (every corpus sample dies at
    ``not_single_literal_tj`` first).
    """
    doc = _simple_font_doc(b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET")
    try:
        row = measure_tier_funnel.measure_document(doc, 30, 60)
        funnel = row["funnel"]
        assert funnel["bind_survivors"] == 2, funnel["bind_fail_reasons"]
        assert funnel["palindrome_skipped"] == 0
        assert funnel["plan_attempted"] == 2
        assert funnel["plan_fail_reasons"] == {}
        assert funnel["plan_survivors"] == 2
        assert _production_plan_reasons(doc) == [None, None]
    finally:
        doc.close()


def _frame_unprovable_doc(target_text: str) -> fitz.Document:
    """One plain literal ``Tj`` on a page whose ``/Rotate`` is ``45`` --
    ``transforms.page_visual_frame`` refuses this shape
    (``UnsupportedPageGeometryError``: "/Rotate 45 is not an exact quarter
    turn"), so the page's visual frame can never be proven. Unlike a zero
    ``/UserUnit`` (which MuPDF renders with NO ink at all, so
    ``page.get_text``/``TextBlockManager`` extraction finds nothing either),
    MuPDF renders a non-quarter-turn ``/Rotate`` page at the nearest quarter
    turn (MEASURED, ``transforms.py`` 253) -- text extraction still
    succeeds, so the resolve stage still produces a real target and this
    fixture actually exercises the bind stage's frame gate rather than
    dying earlier at resolve. ``target_text`` is written into the stream so
    the resolve stage's target IS the real show content; the point under
    test is not the target's own matchability but that a frame-unprovable
    page is refused before ``bind_source_text`` is ever asked to find a
    candidate.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 72 700 Td (" + target_text.encode() + b") Tj ET"
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
    doc.xref_set_key(page.xref, "Rotate", "45")
    return doc


def test_frame_unprovable_page_refuses_before_bind_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T16-4X S0: production (``plan.py`` ~917-920) proves the page's visual
    frame BEFORE any candidate is matched; ``bind_source_text`` only reaches
    that same ``PAGE_GEOMETRY_UNSUPPORTED`` gate AFTER a byte-matching
    candidate is found (``inspect.py`` 1047-1057). The funnel must mirror
    the planner: every sample of a frame-unprovable page counts under
    ``bind_fail[page_geometry_unsupported]`` WITHOUT ever calling
    ``bind_source_text`` -- calling it here would let a non-matching target
    mis-report ``no_match`` instead of the planner's real verdict.

    The frame-unprovable fixture's own resolve stage also refuses (its
    ``_dict_space_to_visual`` gate is the very same ``page_visual_frame``
    proof), so ``_tier0_target_from_resolve`` is monkeypatched to hand back
    a real target whose text does NOT byte-match anything in the page's
    content stream -- exactly the shape that would silently mis-report
    ``no_match`` if ``bind_source_text`` were (wrongly) still called.
    """
    doc = _frame_unprovable_doc(TARGET)
    try:
        non_matching_target = pdf_text_edit._Tier0Target(
            "does-not-byte-match-any-show",
            (72.0, 700.0),
            (72.0, 690.0, 200.0, 710.0),
            1,
        )
        monkeypatch.setattr(
            measure_tier_funnel,
            "_tier0_target_from_resolve",
            lambda *a, **k: non_matching_target,
        )

        called = []
        real_bind = measure_tier_funnel.bind_source_text

        def _counting_bind(*args: object, **kwargs: object) -> object:
            called.append(1)
            return real_bind(*args, **kwargs)  # pragma: no cover - must not run

        monkeypatch.setattr(measure_tier_funnel, "bind_source_text", _counting_bind)
        row = measure_tier_funnel.measure_document(doc, 30, 60)

        funnel = row["funnel"]
        assert called == [], "bind_source_text must not be called on an unprovable frame"
        assert funnel["resolve_survivors"] > 0
        assert funnel["bind_survivors"] == 0
        assert funnel["bind_fail_reasons"] == {
            RejectReason.PAGE_GEOMETRY_UNSUPPORTED: funnel["resolve_survivors"]
        }

        # Same code the real planner reports for the identical target.
        registry = DocumentFontRegistry(doc)
        page = doc[0]
        result = prepare_tier0_plan(
            doc,
            page,
            target_text=non_matching_target.text,
            replacement_text=non_matching_target.text[::-1],
            expected_origin=non_matching_target.origin,
            target_bbox=non_matching_target.bbox,
            registry=registry,
        )
        assert isinstance(result, PlanRejection)
        assert result.reason == RejectReason.PAGE_GEOMETRY_UNSUPPORTED
    finally:
        doc.close()


def test_census_replay_built_from_one_stream_read_per_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F6 (this slice): the census replay is built from
    ``capture_page_streams``'s OWN snapshot streams rather than a second,
    independent ``read_page_streams`` call -- one read of the document's
    decoded content stream per page, not two. ``read_page_streams`` is the
    actual read (``capture_page_streams`` calls it internally to build the
    snapshot); before this fix the funnel called it a SECOND time per page
    for the census.

    ``TextBlockManager.get_runs`` is monkeypatched to return no runs, which
    skips the (a) edit-level funnel's own per-sample ``prepare_plan`` calls
    entirely (each of THOSE also calls ``capture_page_streams`` internally,
    by production design -- see the module docstring's F6 paragraph -- so
    counting reads through them would conflate that separate, expected
    per-sample cost with the one-read-per-page count this test isolates).
    """
    import model.text_commit.inspect as inspect_module
    from model.text_block import TextBlockManager

    doc = _simple_font_doc(b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET")
    try:
        monkeypatch.setattr(TextBlockManager, "get_runs", lambda self, page_idx: [])

        calls = []
        real_read = inspect_module.read_page_streams

        def _counting_read(*args: object, **kwargs: object) -> object:
            calls.append(1)
            return real_read(*args, **kwargs)

        monkeypatch.setattr(inspect_module, "read_page_streams", _counting_read)
        measure_tier_funnel.measure_document(doc, 30, 60)
        assert calls == [1] * doc.page_count
    finally:
        doc.close()


def test_json_records_the_production_plan_stage_and_stays_private(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Methodology fields describe what actually ran, and the payload still
    carries counts and reason codes only -- no document text, no path."""
    doc = _marked_content_doc(b"(Hello) Tj")
    pdf_path = tmp_path / "funnel_probe_fixture.pdf"
    doc.save(str(pdf_path))
    doc.close()

    assert measure_tier_funnel.main([str(pdf_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    methodology = payload["methodology"]
    assert methodology["plan_stage"] == (
        "production_prepare_plan_max_tier0_reversed_replacement"
    )
    assert methodology["bind_stage"] == "production_bind_source_text_with_registry"
    assert methodology["identity_replacement"] is False

    blob = json.dumps(payload)
    assert TARGET not in blob
    assert "funnel_probe_fixture" not in blob
    assert str(tmp_path) not in blob
    assert payload["per_document"][0]["doc_index"] == 0


def test_palindrome_on_a_frame_unprovable_page_is_bucketed_like_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review fold 3: production's FIRST gate is ``NO_CHANGE`` (request-level,
    ``plan.py`` ~877), ahead of the widget and frame gates. A palindromic
    target on a frame-unprovable page must therefore land in
    ``palindrome_skipped`` -- never in ``bind_fail[page_geometry_unsupported]``
    -- otherwise the funnel's bucket order is a hand-mirror that disagrees
    with the planner it claims to call."""
    doc = _frame_unprovable_doc(PALINDROME)
    try:
        target = pdf_text_edit._Tier0Target(
            PALINDROME, (72.0, 700.0), (72.0, 690.0, 200.0, 710.0), 1
        )
        monkeypatch.setattr(
            measure_tier_funnel, "_tier0_target_from_resolve", lambda *a, **k: target
        )
        row = measure_tier_funnel.measure_document(doc, 30, 60)
        funnel = row["funnel"]
        assert funnel["resolve_survivors"] > 0
        assert funnel["palindrome_skipped"] == funnel["resolve_survivors"]
        assert funnel["bind_fail_reasons"] == {}
        assert funnel["plan_attempted"] == 0
    finally:
        doc.close()
