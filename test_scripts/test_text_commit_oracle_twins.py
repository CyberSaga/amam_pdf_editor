"""ORACLE twins (slice I0b, stage S3a): the growth-zone and neighbour-glyph helpers, judged on synthetic pages.

CI lane, no marker: every document is built at run time.  The runner lives in
``test_scripts/frontier_twins.py`` (``twin_runs`` / ``judge`` / ``run_oracle_twin``), the helpers in
``test_scripts/true_text_acceptance_helpers.py``; plan section 4 holds the twin table.

Red-first record (stage S3a).  The helpers were first written as stubs (``growth_zone_checks`` returning
``(0, None)``, both ``check_*`` returning ``None``); the behaviour reds are the growth ``expected fail,
got pass`` on vi, viii, viii-b and x, the neighbours ones on vi, viii, viii-b and xii, the delegation spy
(rederive still had its own body), the parity ``glyphs:`` / ``oracle raised ValueError`` rows and the six
neighbour unit tests through their fail legs.  Red by import (attribute) only, labelled as such below:
the registry test, the four non-vacuity tests and the Q12 test.  The reds are pasted in
``plans/true-text-i0b.md``'s running log.

Red-first record (stage S3b).  Stubs first (the four ``check_*`` returning ``None``, ``glyph_identity_inputs``
returning ``((), ())``): the behaviour reds are the 16 ``test_oracle_twin`` ids (``expected fail, got pass`` for
i-v, ``passed without checking any glyph`` for the guards and vi-xii), the seven-kind matrix, the unavailable
cases U2/U3/U4/U6/U7 (``DID NOT RAISE``) and the two forgery tests.  Red by import (attribute) only: the registry
test (17 ids), the non-vacuity pairs for the four new names and the id list in
``test_text_commit_frontier_twins.py``.  Written WITH the helper, not red-first: the split-stream refusal pin,
``no_outline``, U1, U5, the contradicting-inputs test and the premise tests (which pin Step 0 numbers).

Red-first record (stage S8, D11).  Written before ``growth_zone_checks`` rendered its copy first (it counted the
growth-zone glyphs, a ``rawdict`` with ``TEXT_PRESERVE_IMAGES``, and rendered after): the raster-input red
``test_growth_oracle_judges_the_same_raster_as_the_commit`` (both shapes: the oracle's pixmap digest was the
post-extraction render, not the commit-time pre-state's) and the verdict red
``test_growth_oracle_gives_the_commit_verdict_on_an_image_backed_target`` (both shapes: ``no sampling point ...``
where prepare and commit both say ``growth probe region ... is uniform but is not the target's own background
colour``).  The glyph-count guard was green before and after.  Written after the fix (refuter fold-in), red on its
mutants only: the call-order guard ``test_growth_oracle_renders_its_copy_once_before_any_extraction`` (the count-first
order, the product branch without ``observed=``, the experiment branch rendering again after the count) and
``test_growth_oracle_reports_a_refused_render_before_an_unprovable_slice`` (the count-first order said ``oracle raised
ValueError``).  The reds and the probe table are pasted in ``plans/true-text-i0b.md``'s running log.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import sys
from io import BytesIO
from pathlib import Path

import fitz
import numpy as np
import pytest
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.page_content_text import visible_text  # noqa: E402
from model.text_commit import transforms, verify  # noqa: E402
from model.text_commit.dto import CommitStatus, RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.cid_fonts import read_embedded_font_program  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit, _grown_verify_bbox  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402
from model.text_commit.patch import build_transplant_replacement  # noqa: E402
from model.text_commit.pdf_lexer import splice_stream  # noqa: E402
from model.text_commit.stroke_occupancy import strokes_provably_clear  # noqa: E402
from scripts import evidence_rederive as rd  # noqa: E402
from test_scripts import frontier_twins  # noqa: E402
from test_scripts import painter_matrix_fixtures as pmf  # noqa: E402
from test_scripts import simple_font_fixture_builder as sfb  # noqa: E402
from test_scripts import stream_storage_fixtures as ssf  # noqa: E402
from test_scripts import true_text_acceptance_helpers as helpers  # noqa: E402
from test_scripts import type0_fixture_builder as tb  # noqa: E402
from test_scripts.true_text_corpus import CorpusCase  # noqa: E402

SPECS = {spec.twin_id: spec for spec in frontier_twins.ORACLE_TWINS}
_ADAPTER_TARGETS = {
    "growth": "check_growth_zone_was_blank",
    "neighbours": "check_neighbour_glyphs_unchanged",
    "stream_range": "check_target_stream_changed_only_within",
    "wrapper": "check_wrapper_bytes_unchanged",
    "counts": "check_show_and_operator_counts_equal",
    "glyph_identity": "check_glyph_identity",
}


@pytest.fixture(scope="module")
def oracle_runs(tmp_path_factory):
    """Every twin's runs, built once per module (the non-vacuity tests judge them repeatedly)."""
    runs = {
        spec.twin_id: frontier_twins.twin_runs(spec, tmp_path_factory.mktemp(f"twin-{spec.twin_id}"))
        for spec in frontier_twins.ORACLE_TWINS
    }
    yield runs
    for twin_runs in runs.values():
        frontier_twins.close_runs(twin_runs)


# ----------------------------------------------------------------------------------------------
# the twins and the runner's own guards
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("spec", frontier_twins.ORACLE_TWINS, ids=lambda spec: spec.twin_id)
def test_oracle_twin(spec, tmp_path):
    assert frontier_twins.run_oracle_twin(spec, tmp_path) == []


def test_oracle_twin_registry_is_well_formed():
    """Red by import only (the registry did not exist): names, paths and heads are coherent."""
    ids = [spec.twin_id for spec in frontier_twins.ORACLE_TWINS]
    assert len(ids) == len(set(ids)) == 18
    for spec in frontier_twins.ORACLE_TWINS:
        assert not spec.must_fail & spec.must_pass, spec.twin_id
        assert (spec.must_fail | spec.must_pass) <= set(frontier_twins.ORACLE_HELPERS), spec.twin_id
        assert spec.paths and spec.paths <= {"product", "experiment"}, spec.twin_id
        assert ("experiment" in spec.paths) == (spec.experiment is not None), spec.twin_id
        assert ("product" in spec.paths) == (spec.product_expected is not None), spec.twin_id
        for name, head in spec.detail_heads:
            assert head
            assert name == "product" or name in spec.must_fail, (spec.twin_id, name)
            assert name != "product" or "product" in spec.paths, (spec.twin_id, name)
        # a crashing core yields ``oracle raised <Type>``, which counts as an expected fail unless a head is pinned
        assert spec.must_fail <= {name for name, _ in spec.detail_heads}, spec.twin_id
    assert set(frontier_twins.ORACLE_HELPERS) == set(_ADAPTER_TARGETS)


@pytest.mark.parametrize("name", sorted(_ADAPTER_TARGETS))
def test_a_no_op_helper_turns_every_must_fail_twin_red(name, monkeypatch, oracle_runs):
    """Red by import only.  Non-vacuity: with the helper stubbed to pass, every twin that needs it to fail is red."""
    monkeypatch.setattr(helpers, _ADAPTER_TARGETS[name], lambda *args, **kwargs: None)
    specs = [spec for spec in frontier_twins.ORACLE_TWINS if name in spec.must_fail]
    assert specs
    for spec in specs:
        mismatches = frontier_twins.judge(spec, oracle_runs[spec.twin_id])
        assert any(f"/{name}:" in mismatch for mismatch in mismatches), (spec.twin_id, mismatches)


@pytest.mark.parametrize("name", sorted(_ADAPTER_TARGETS))
def test_an_always_failing_helper_turns_every_must_pass_twin_red(name, monkeypatch, oracle_runs):
    """Red by import only.  The mirror: with the helper stubbed to fail, every twin that needs it to pass is red."""
    monkeypatch.setattr(helpers, _ADAPTER_TARGETS[name], lambda *args, **kwargs: "stub: fail")
    specs = [spec for spec in frontier_twins.ORACLE_TWINS if name in spec.must_pass]
    assert specs
    for spec in specs:
        mismatches = frontier_twins.judge(spec, oracle_runs[spec.twin_id])
        assert any(f"/{name}:" in mismatch for mismatch in mismatches), (spec.twin_id, mismatches)


# ----------------------------------------------------------------------------------------------
# premise tests: the twins test what they claim
# ----------------------------------------------------------------------------------------------
def test_twin_vii_exercises_the_stroke_proof(oracle_runs):
    """(vii) passes because the page-frame stroke overlaps the growth strip's box and is PROVABLY clear."""
    (run,) = oracle_runs["vii"]
    prepared = run.prepared
    assert prepared is not None and prepared.has_ink_growth
    with helpers._measurement_copy(run.source) as copy:
        page = copy[0]
        zone = verify._growth_zone_rect(prepared.target_bbox_page, prepared.effective_verify_bbox)
        assert zone is not None
        growth_dict = verify._growth_rect_in_dict_space(page, zone)
        overlapping = [
            drawing
            for drawing in page.get_drawings()
            if verify._rects_overlap(fitz.Rect(drawing["rect"]), growth_dict)
        ]
        assert overlapping, "the frame stroke must overlap the growth zone's box, or the proof is not exercised"
        assert strokes_provably_clear(
            page,
            overlapping,
            zone,
            to_visual=run.frame.quarter_turn,
            margin=verify._STROKE_CLEARANCE_MARGIN_PT,
        )
        assert verify._drawings_intersect_growth(page, zone) is False


def test_twin_viii_b_locates_through_the_frame(oracle_runs, monkeypatch):
    """(viii-b) is one odd page (/UserUnit 2, an offset CropBox, /Rotate 90): the located box is the frame box."""
    (run,) = oracle_runs["viii-b"]
    assert run.frame.user_unit == 2.0
    assert run.frame.rotation == 90
    doc = fitz.open("pdf", run.source.tobytes())
    try:
        resource = helpers._shows(doc, 0)[0].font_resource
        with helpers._measurement_copy(doc) as copy:
            trace = helpers._trace_for(copy[0], helpers._shows(doc, 0)[0], tb.CJK_TEXT)
        seen: dict = {}
        real_prepare = TieredCommitEngine.prepare

        def spy(self, page, **kwargs):
            seen.update(kwargs)
            return real_prepare(self, page, **kwargs)

        monkeypatch.setattr(TieredCommitEngine, "prepare", spy)
        case = CorpusCase(
            page_index=0,
            show_seq=0,
            original=tb.CJK_TEXT,
            replacement=tb.REPLACEMENT_LONGER,
            font_resource=resource,
            basefont="fixture",
        )
        helpers._prepare(TieredCommitEngine(doc, max_tier=1), doc, case)
    finally:
        doc.close()
    assert seen["target_bbox"] == tuple(fitz.Rect(trace["bbox"]) * run.frame.quarter_turn)
    assert fitz.Rect(seen["target_bbox"]).intersects(run.source[0].rect)


# ----------------------------------------------------------------------------------------------
# rederive consumption: one core, parity with rederive's own built-in oracle
# ----------------------------------------------------------------------------------------------
def _growth_context(run, *, x_pre: float | None = 0.0, k_inner: float | None = 0.0) -> rd.OracleContext:
    return rd.OracleContext(
        source_doc=run.source,
        after_doc=run.after,
        page_index=0,
        show=run.before_show,
        frame=run.frame,
        target_bbox_visual=run.target_vis,
        verify_bbox_visual=run.verify_vis,
        adv_old=run.adv_old,
        prepared=None,
        case={},
        x_pre=x_pre,
        k_inner=k_inner,
    )


def _helper_growth(run, *, x_pre: float | None = 0.0, k_inner: float | None = 0.0) -> str | None:
    return helpers.check_growth_zone_was_blank(
        run.source,
        0,
        run.before_show,
        run.frame,
        run.target_vis,
        run.verify_vis,
        run.adv_old,
        prepared=None,
        x_pre=x_pre,
        k_inner=k_inner,
    )


@pytest.fixture(scope="module")
def blank_run(tmp_path_factory):
    spec = dataclasses.replace(
        SPECS["vi"], twin_id="parity-blank", build=lambda: tb.build_identity_h_fixture().doc
    )
    runs = frontier_twins.twin_runs(spec, tmp_path_factory.mktemp("parity-blank"))
    yield runs[0]
    frontier_twins.close_runs(runs)


def test_parity_growth_oracle_reports_the_glyphs_in_the_zone(oracle_runs):
    (run,) = oracle_runs["vi"]
    detail = _helper_growth(run)
    assert detail is not None and detail.startswith("glyphs: ")
    assert detail == rd.assert_growth_zone_was_blank(_growth_context(run))


def test_parity_growth_oracle_passes_a_blank_zone(blank_run):
    assert blank_run.verify_vis != blank_run.target_vis
    assert _helper_growth(blank_run) is None
    assert rd.assert_growth_zone_was_blank(_growth_context(blank_run)) is None


def test_product_shape_growth_oracle_checks_the_background_quad(oracle_runs):
    """Twin vii in product shape: a perturbed ``adv_old`` makes the metric quad differ from the prepared one."""
    (run,) = oracle_runs["vii"]
    assert run.prepared is not None

    def growth(adv_old: float) -> str | None:
        return helpers.check_growth_zone_was_blank(
            run.source,
            0,
            run.before_show,
            run.frame,
            run.target_vis,
            run.verify_vis,
            adv_old,
            prepared=run.prepared,
            x_pre=0.0,
            k_inner=0.0,
        )

    assert growth(run.adv_old) is None
    assert growth(run.adv_old + 0.5) == "background: the prepared quad differs from the metric quad"


def test_parity_growth_oracle_is_not_applicable_without_growth(oracle_runs):
    (run,) = oracle_runs["vi"]
    flat = dataclasses.replace(run, verify_vis=run.target_vis)
    assert _helper_growth(flat) is None
    assert rd.assert_growth_zone_was_blank(_growth_context(flat)) is None


def test_parity_growth_oracle_refuses_an_unprovable_slice_origin(oracle_runs):
    (run,) = oracle_runs["vi"]
    for terms in ({"x_pre": None}, {"k_inner": None}):
        assert _helper_growth(run, **terms) == "oracle raised ValueError"
        assert rd.assert_growth_zone_was_blank(_growth_context(run, **terms)) == "oracle raised ValueError"


def test_rederive_growth_checks_delegates_to_the_helper_core(oracle_runs, monkeypatch):
    """The rederive wrapper owns ctx unpacking and the ``_ascii`` boundary; the body is the helper's core."""
    (run,) = oracle_runs["vi"]
    calls: list[tuple] = []
    detail = "raster: " + "x" * 400 + "é"

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return 3, detail

    monkeypatch.setattr(helpers, "growth_zone_checks", spy)
    ctx = _growth_context(run)
    glyphs, got = rd._growth_checks(ctx)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (run.source, 0, run.before_show, run.frame, run.target_vis, run.verify_vis, run.adv_old)
    assert kwargs == {"prepared": None, "x_pre": 0.0, "k_inner": 0.0}
    assert glyphs == 3
    assert got == rd._ascii(detail) and len(got) == 300
    monkeypatch.setattr(helpers, "growth_zone_checks", lambda *args, **kwargs: (0, None))
    assert rd._growth_checks(ctx) == (0, None)


# ----------------------------------------------------------------------------------------------
# S8 (D11, red first, 2026-10-29): the growth core renders its copy at 96 dpi before it counts, as the product's
# snapshots are (prepare: capture_page_state renders first; commit: observe_page).  Probe K0/K2 in the plan's log.
# ----------------------------------------------------------------------------------------------
#: K0: the live-store test's 628 px noise image, far from the target: a rawdict extraction (TEXT_PRESERVE_IMAGES decodes
#: it at full resolution) changes the next 96 dpi render of the same document; the product commits Tier 1 growth unforced.
_NOISE_PLACEMENT = "q 128 0 0 128 380 100 cm /ImN Do Q"
#: K2: a 1 px 8 bpc DeviceGray checkerboard under the target, 9 pt past it on the left, above and below (where the
#: background reference points sample) and stopping 0.5 pt short of its right edge, so it misses the growth strip and the
#: image-occupancy gate stays silent.  198 x 104 px over 56.5 x 30 pt is 1.3 x two decodes per rendered pixel: a
#: non-power-of-two decimation, where the post-extraction render differs from the fresh one inside the read set.
_CHECKER_SIZE = (198, 104)
_CHECKER_PLACEMENT = "q 56.5 0 0 30 63 688.567 cm /ImB Do Q"


def _noise_page(**build) -> tb.Type0Fixture:
    fixture = tb.build_identity_h_fixture(**build)
    tb.install_noise_image_xobject(fixture, name="ImN")
    tb.append_page_content(fixture, _NOISE_PLACEMENT)
    return fixture


def _image_backed_target() -> tb.Type0Fixture:
    fixture = tb.build_identity_h_fixture()
    width, height = _CHECKER_SIZE
    doc = fixture.doc
    xref = doc.get_new_xref()
    doc.update_object(
        xref,
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceGray "
        "/BitsPerComponent 8 >>",
    )
    doc.update_stream(xref, bytes(255 * ((x + y) % 2) for y in range(height) for x in range(width)), compress=True)
    tb._set_page_xobject(fixture, "ImB", f"{xref} 0 R")
    tb.append_page_content(fixture, _CHECKER_PLACEMENT)
    return fixture


def _growth_arguments(fixture: tb.Type0Fixture) -> dict:
    return {
        "target_text": fixture.text,
        "replacement_text": tb.REPLACEMENT_LONGER,
        **frontier_twins.located_arguments(fixture.doc, fixture.text),
    }


def _growth_oracle(source: fitz.Document, prepared: PreparedEdit, shape: str) -> str | None:
    """The growth oracle on ``source`` with the product's own boxes, in product (``prepared``) or experiment shape."""
    return helpers.check_growth_zone_was_blank(
        source,
        0,
        helpers._shows(source, 0)[0],
        helpers.visual_frame(source[0]),
        prepared.target_bbox_page,
        prepared.effective_verify_bbox,
        prepared.source_advance,
        prepared=prepared if shape == "product" else None,
        x_pre=0.0,
        k_inner=0.0,
    )


def _digest_96(page: fitz.Page) -> str:
    return hashlib.sha256(page.get_pixmap(dpi=verify._VERIFY_DPI).samples).hexdigest()


@pytest.mark.parametrize("shape", ["product", "experiment"])
def test_growth_oracle_judges_the_same_raster_as_the_commit(shape, monkeypatch):
    """The raster-input property (S8 red): every ``_growth_probe_failure`` call is recorded with the digest of the pixmap it
    reads; the oracle's one call must read the commit-time pre-state's raster (the product's own, at the gate it feeds;
    nothing re-implemented).  Page-wide, not image-under-target: the image here is far from every read region, so the
    verdict is ``None`` in either order and only the raster input tells the orders apart.  The premise (a rawdict
    extraction changes the next 96 dpi render of the same document) is measured in-test."""
    fixture = _noise_page()
    try:
        data = fixture.doc.tobytes()
        with fitz.open("pdf", data) as cold, fitz.open("pdf", data) as warm:
            fresh = _digest_96(cold[0])
            visible_text(warm[0], "rawdict")
            assert _digest_96(warm[0]) != fresh, "premise: the extraction changes the next render"
        seen: dict[str, list] = {}
        phase = ["prepare"]
        real = verify._growth_probe_failure

        def spy(state, **kwargs):
            seen.setdefault(phase[0], []).append(
                (hashlib.sha256(state.pixmap_samples).hexdigest(), state.pixmap_meta)
            )
            return real(state, **kwargs)

        monkeypatch.setattr(verify, "_growth_probe_failure", spy)
        engine = TieredCommitEngine(fixture.doc, max_tier=1)
        prepared = engine.prepare(fixture.page, **_growth_arguments(fixture))
        assert isinstance(prepared, PreparedEdit) and prepared.has_ink_growth, prepared
        with fitz.open("pdf", data) as source:
            phase[0] = "oracle"
            detail = _growth_oracle(source, prepared, shape)
        phase[0] = "commit"
        assert engine.commit(prepared).status is CommitStatus.COMMITTED
        assert seen["prepare"][-1] == seen["commit"][-1], "premise: the product judges one raster on both paths"
        assert seen["oracle"] == [seen["commit"][-1]]
        assert detail is None
    finally:
        fixture.doc.close()


def _count_then_render_detail(data: bytes, prepared: PreparedEdit) -> str | None:
    """The pre-S8 order, emulated on a fresh copy: the rawdict extraction first, then the 96 dpi render the gate reads."""
    with fitz.open("pdf", data) as copy:
        page = copy[0]
        visible_text(page, "rawdict")
        pix = page.get_pixmap(dpi=verify._VERIFY_DPI)
        state = verify.PageState(
            streams=(),
            fonts=(),
            annots=(),
            nontarget_origins=(),
            pixmap_samples=bytes(pix.samples),
            pixmap_meta=(pix.width, pix.height, pix.stride, pix.n),
        )
        failure = verify._growth_probe_failure(
            state,
            target_bbox=prepared.target_bbox_page,
            verify_bbox=prepared.effective_verify_bbox,
            background_bbox=prepared.background_bbox_page,
            page=page,
            doc=copy,
        )
    return None if failure is None else failure.detail


@pytest.mark.parametrize("shape", ["product", "experiment"])
def test_growth_oracle_gives_the_commit_verdict_on_an_image_backed_target(shape, monkeypatch):
    """The verdict red (S8; probe K2, a detail flip, never pass/fail): the product refuses the unforced prepare and, forced
    past the prepare gate, FAILS the commit with one ``background:`` detail; the oracle must report that same detail.  The
    experiment shape compares with the unforced refusal, the product shape with the commit outcome (the patch reverted).
    Premise asserted in-test: the count-then-render order gives another detail on this page."""
    fixture = _image_backed_target()
    try:
        data = fixture.doc.tobytes()
        arguments = _growth_arguments(fixture)
        refusal = TieredCommitEngine(fixture.doc, max_tier=1).prepare(fixture.page, **arguments)
        assert isinstance(refusal, PlanRejection), refusal
        assert refusal.reason == RejectReason.GROWTH_REGION_NOT_BLANK and refusal.detail.startswith("background: ")
        engine = TieredCommitEngine(fixture.doc, max_tier=1)
        with monkeypatch.context() as forced:
            forced.setattr(verify, "_growth_probe_failure", lambda *args, **kwargs: None)
            prepared = engine.prepare(fixture.page, **arguments)
        assert isinstance(prepared, PreparedEdit) and prepared.has_ink_growth, prepared
        assert prepared.background_bbox_page is not None
        assert _count_then_render_detail(data, prepared) not in (None, refusal.detail), "premise: the order matters here"
        with fitz.open("pdf", data) as source:
            detail = _growth_oracle(source, prepared, shape)
        if shape == "experiment":
            assert detail == refusal.detail
        else:
            before = fixture.content_bytes()
            outcome = engine.commit(prepared)
            assert outcome.status is CommitStatus.FAILED, outcome
            assert outcome.degraded_reason == refusal.detail, "premise: prepare and commit give one verdict"
            assert fixture.content_bytes() == before
            assert detail == outcome.degraded_reason
    finally:
        fixture.doc.close()


def test_growth_zone_glyph_count_does_not_depend_on_a_prior_render():
    """Guard, not a red (green before and after S8): the count reads rawdict characters (metric boxes, never image tiles),
    so moving the 96 dpi render ahead of it cannot move a ``glyphs:`` detail.  The tail's first glyph sits in the zone."""
    fixture = _noise_page(tail_text=tb.TAIL_TEXT)
    try:
        data = fixture.doc.tobytes()
        with fitz.open("pdf", data) as source:
            show = helpers._shows(source, 0)[0]
            target = frontier_twins.located_arguments(source, fixture.text)["target_bbox"]
            _rep, adv_old, adv_new = frontier_twins.e_kern(source, show, fixture.text, tb.REPLACEMENT_LONGER)
            growth = max(0.0, adv_new - adv_old) * (show.hscale / 100.0)
            grown = _grown_verify_bbox(source[0], show, target, growth, frame=helpers.visual_frame(source[0]))
        with fitz.open("pdf", data) as as_is, fitz.open("pdf", data) as rendered_first:
            count = verify.count_growth_zone_glyphs(as_is[0], target_bbox=target, verify_bbox=grown)
            rendered_first[0].get_pixmap(dpi=verify._VERIFY_DPI)
            after_render = verify.count_growth_zone_glyphs(rendered_first[0], target_bbox=target, verify_bbox=grown)
        assert after_render == count > 0, (count, after_render)
    finally:
        fixture.doc.close()


def _prepared_noise_growth(fixture: tb.Type0Fixture) -> PreparedEdit:
    prepared = TieredCommitEngine(fixture.doc, max_tier=1).prepare(fixture.page, **_growth_arguments(fixture))
    assert isinstance(prepared, PreparedEdit) and prepared.has_ink_growth, prepared
    return prepared


@pytest.mark.parametrize("shape", ["product", "experiment"])
def test_growth_oracle_renders_its_copy_once_before_any_extraction(shape, monkeypatch):
    """Guard (S8 refuter fold-in, written after the fix; red on the mutants below): during one oracle call the copy's
    first page call is the 96 dpi render, and it is the only render.  Raster equality cannot see a second render after
    the count: render, rawdict, render again reproduces the fresh raster on all 206 probe constructions (MuPDF 1.27 finds
    the exact-level image tile first), so this pins what that equivalence rests on.  Red on the count-first order (M1),
    on the product branch without ``observed=`` (M2) and on the experiment branch rendering again after the count (M3)."""
    fixture = _noise_page()
    try:
        data = fixture.doc.tobytes()
        prepared = _prepared_noise_growth(fixture)
        events: list[tuple] = []
        get_pixmap, get_textpage = fitz.Page.get_pixmap, fitz.Page.get_textpage

        def recorded_pixmap(self, *args, **kwargs):
            events.append(("get_pixmap", kwargs.get("dpi")))
            return get_pixmap(self, *args, **kwargs)

        def recorded_textpage(self, *args, **kwargs):
            events.append(("get_textpage",))
            return get_textpage(self, *args, **kwargs)

        with fitz.open("pdf", data) as source:
            show, frame = helpers._shows(source, 0)[0], helpers.visual_frame(source[0])
            with monkeypatch.context() as recording:
                recording.setattr(fitz.Page, "get_pixmap", recorded_pixmap)
                recording.setattr(fitz.Page, "get_textpage", recorded_textpage)
                detail = helpers.check_growth_zone_was_blank(
                    source,
                    0,
                    show,
                    frame,
                    prepared.target_bbox_page,
                    prepared.effective_verify_bbox,
                    prepared.source_advance,
                    prepared=prepared if shape == "product" else None,
                    x_pre=0.0,
                    k_inner=0.0,
                )
        assert detail is None
        assert events[0] == ("get_pixmap", verify._VERIFY_DPI), events
        assert [event for event in events if event[0] == "get_pixmap"] == [events[0]], events
        assert ("get_textpage",) in events[1:], "premise: the glyph count extracts from the copy after the render"
    finally:
        fixture.doc.close()


class _RenderRefused(RuntimeError):
    """Stands in for MuPDF refusing the 96 dpi render (``FzErrorSystem`` on a ``/UserUnit 75000`` page, rawdict fine)."""


@pytest.mark.parametrize("shape", ["product", "experiment"])
def test_growth_oracle_reports_a_refused_render_before_an_unprovable_slice(shape, monkeypatch):
    """The exception order since S8 (refuter fold-in): the render is the first raise site, ahead of the glyph count and of
    the ``ValueError`` for a ``None`` slice term, as the product's prepare and commit render before they count.  The
    count-first order reported ``oracle raised ValueError`` here; both orders fail closed."""
    fixture = _noise_page()
    try:
        data = fixture.doc.tobytes()
        prepared = _prepared_noise_growth(fixture)

        def refuse(self, *args, **kwargs):
            raise _RenderRefused("simulated render failure")

        with fitz.open("pdf", data) as source:
            show, frame = helpers._shows(source, 0)[0], helpers.visual_frame(source[0])
            with monkeypatch.context() as refusing:
                refusing.setattr(fitz.Page, "get_pixmap", refuse)
                detail = helpers.check_growth_zone_was_blank(
                    source,
                    0,
                    show,
                    frame,
                    prepared.target_bbox_page,
                    prepared.effective_verify_bbox,
                    prepared.source_advance,
                    prepared=prepared if shape == "product" else None,
                    x_pre=None,
                    k_inner=0.0,
                )
        assert detail == "oracle raised _RenderRefused"
    finally:
        fixture.doc.close()


_REDERIVE_ORACLE = {
    "growth": "assert_growth_zone_was_blank",
    "stream_range": "assert_target_stream_changed_only_within",
    "wrapper": "assert_wrapper_bytes_unchanged",
    "counts": "assert_show_and_operator_counts_equal",
    "neighbours": "assert_neighbour_glyphs_unchanged",
    "glyph_identity": "assert_glyph_identity",
}


def _rederive_context(run) -> rd.OracleContext:
    """The context rederive builds for this document pair: the record carries only what an adapter may read (the kind, the
    replacement claim and, on the experiment path, the splice), the target is the whole show and the sink starts empty."""
    rep = run.replacement
    mutation = None
    if run.prepared is None:
        mutation = {
            "changes": [
                {
                    "stream_xref": rep.stream_xref,
                    "start": rep.start,
                    "end_old": rep.end,
                    "new_operand_bytes_hex": bytes(rep.replacement_bytes).hex(),
                }
            ]
        }
    return rd.OracleContext(
        source_doc=run.source,
        after_doc=run.after,
        page_index=0,
        show=run.before_show,
        frame=run.frame,
        target_bbox_visual=run.target_vis,
        verify_bbox_visual=run.verify_vis,
        adv_old=run.adv_old,
        prepared=run.prepared,
        case={"kind": "positive", "corpus_case": {"replacement": run.replacement_text}, "mutation": mutation},
        x_pre=0.0,
        k_inner=0.0,
        target_span=(0, 0),
        sink={},
    )


@pytest.mark.parametrize("spec", frontier_twins.ORACLE_TWINS, ids=lambda spec: spec.twin_id)
def test_rederive_adapters_agree_with_the_twin_judge(spec, oracle_runs):
    """D18: rederive's six adapters give the twin judge's verdict, and carry the pinned detail heads, on every run of every
    ORACLE twin (the judge's two vacuity skips apply: no growth zone, no wrapper)."""
    judged = 0
    for run in oracle_runs[spec.twin_id]:
        if isinstance(run, frontier_twins.Refusal):
            continue
        ctx = _rederive_context(run)
        for name in sorted(spec.must_fail | spec.must_pass):
            if name == "growth" and tuple(run.verify_vis) == tuple(run.target_vis):
                continue
            if name == "wrapper" and not replay_page_streams(helpers.page_streams(run.source, 0)).wrappers_for(run.before_show):
                continue
            ctx.sink.clear()
            detail = rd._run_oracle(rd.DEFAULT_ORACLES[_REDERIVE_ORACLE[name]], ctx)
            label = f"{spec.twin_id}/{run.path}/{name}"
            if name in spec.must_fail:
                assert detail is not None, f"{label}: expected fail, got pass"
                assert all(head in detail for head_name, head in spec.detail_heads if head_name == name), (label, detail)
            else:
                assert detail is None, (label, detail)
            judged += 1
    assert judged > 0, spec.twin_id


# ----------------------------------------------------------------------------------------------
# neighbour helper unit tests (documents built in memory; no saveIncr)
# ----------------------------------------------------------------------------------------------
def _documents(build, new_stream_of) -> tuple[fitz.Document, fitz.Document]:
    """``(source, after)``: the built page and a copy whose show stream is ``new_stream_of(source, show)``."""
    built = build()
    data = built.tobytes()
    built.close()
    source = fitz.open("pdf", data)
    show = helpers._shows(source, 0)[0]
    after = fitz.open("pdf", data)
    after.update_stream(show.stream_xref, new_stream_of(source, show))
    return source, after


def _kern_splice(target: str, replacement: str):
    def new_stream(source, show):
        rep, _, _ = frontier_twins.e_kern(source, show, target, replacement)
        return splice_stream(source.xref_stream(show.stream_xref), [rep])

    return new_stream


def _neighbours(source, after, *, kind="positive", pre=0, post=0, code_bytes=None, measurements=None, **kwargs):
    before_show, after_show = helpers._shows(source, 0)[0], helpers._shows(after, 0)[0]
    if code_bytes is None:
        code_bytes = frontier_twins._code_bytes(source, before_show)
    edited = [helpers.edited_show(before_show, after_show, code_bytes=code_bytes, pre=pre, post=post)]
    return helpers.check_neighbour_glyphs_unchanged(
        source,
        after,
        0,
        edited,
        kind=kind,
        frame=helpers.visual_frame(source[0]),
        measurements=measurements,
        **kwargs,
    )


def test_neighbours_check_in_show_successors_of_a_slice_target():
    """``(ABCDEF) Tj`` -> ``[(ABXYZ) 600 (EF)] TJ``: slice target CD (pre 2, post 2), successors E, F held in place by K.

    Deviation from the s3a spec's wording: its pass leg ran as a judged kind, but holding E in place under a
    three-glyph replacement makes Z overprint E, so the pass leg runs as ``negative`` (overlap not judged)
    and the judged kind is asserted to report that overlap alone."""

    def splice(kern: str):
        def new_stream(source, show):
            stream = source.xref_stream(show.stream_xref)
            return splice_stream(
                stream,
                [build_transplant_replacement(stream, show, f"[(ABXYZ) {kern} (EF)] TJ".encode("ascii"))],
            )

        return new_stream

    build = lambda: sfb.build_embedded_simple_fixture("winansi", "ABCDEF").doc  # noqa: E731
    source, after = _documents(build, splice("600"))
    try:
        edited = helpers.edited_show(
            helpers._shows(source, 0)[0], helpers._shows(after, 0)[0], code_bytes=1, pre=2, post=2
        )
        assert (edited.pre, edited.n_old, edited.n_new, edited.post) == (2, 2, 3, 2)
        # K = 600 holds E and F where they were, so the third new glyph overprints E by construction:
        # the position legs pass, and a judged kind reports exactly the overlap and nothing else
        measurements: dict = {}
        assert _neighbours(source, after, kind="negative", pre=2, post=2, measurements=measurements) is None
        assert measurements["glyphs_paired"] == 4 and measurements["max_inshow_dev"] <= 1e-6
        assert _neighbours(source, after, pre=2, post=2) == "neighbours: overlap: 1 glyph(s)"
    finally:
        source.close()
        after.close()
    source, after = _documents(build, splice("0"))  # no compensation: E and F move a whole glyph
    try:
        detail = _neighbours(source, after, kind="negative", pre=2, post=2)
        assert detail is not None and detail.startswith("neighbours: ")
        assert "inshow_moved: 2 glyph(s)" in detail
    finally:
        source.close()
        after.close()


def test_neighbours_skip_tounicode_continuation_items():
    """A two-codepoint ToUnicode entry adds a gid -1 item that must not shift the pairing."""

    def build():
        fixture = tb.build_identity_h_fixture()
        pmf.map_cid_to_two_codepoints(fixture, tb.cid_for("好"))
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE))
    try:
        with helpers._measurement_copy(source) as copy:
            items = [item for span in copy[0].get_texttrace() for item in span["chars"]]
        assert any(item[1] < 0 for item in items), "premise: the before trace holds a gid -1 continuation item"
        assert _neighbours(source, after) is None
        before_show, after_show = helpers._shows(source, 0)[0], helpers._shows(after, 0)[0]
        miscounted = helpers.EditedShow(0, before_show, after_show, 5, 4)  # the continuation item counted
        detail = helpers.check_neighbour_glyphs_unchanged(
            source, after, 0, [miscounted], kind="positive", frame=helpers.visual_frame(source[0])
        )
        assert detail is not None and detail.startswith("neighbours: pairing")
    finally:
        source.close()
        after.close()


def test_neighbours_pair_form_xobject_glyphs_positionally():
    """Glyphs drawn by a Form XObject have no ShowOp: they pair by position and must not move."""

    def build():
        fixture = tb.build_identity_h_fixture()
        pmf.install_text_form_xobject(
            fixture, name="Fm0", text=tb.TAIL_TEXT, fontsize=12.0, origin=(72.0, 500.0)
        )
        tb.append_page_content(fixture, "/Fm0 Do")
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_LONGER))
    try:
        assert _neighbours(source, after, kind="negative") is None
        form_xref = next(
            xref
            for xref in range(1, after.xref_length())
            if after.xref_is_stream(xref) and b"1 0 0 1 72 500 Tm" in (after.xref_stream(xref) or b"")
        )
        form_stream = after.xref_stream(form_xref)
        for moved in (b"73 500 Tm", b"72.001 500 Tm"):  # a whole point, then a thousandth: exact, no tolerance
            after.update_stream(form_xref, form_stream.replace(b"72 500 Tm", moved))
            detail = _neighbours(source, after, kind="negative")
            assert detail is not None and "untouched_moved:" in detail, moved
    finally:
        source.close()
        after.close()


def test_neighbours_overlap_fails_only_for_judged_kinds():
    spec = SPECS["vi"]
    source, after = _documents(spec.build, _kern_splice(spec.target, spec.replacement))
    try:
        for kind in ("negative", "census"):
            assert _neighbours(source, after, kind=kind) is None, kind
        for kind in ("positive", "control", "canary"):
            detail = _neighbours(source, after, kind=kind)
            assert detail is not None and "overlap: 1 glyph(s)" in detail, (kind, detail)
        with pytest.raises(ValueError):
            _neighbours(source, after, kind="no-such-kind")
    finally:
        source.close()
        after.close()


def test_neighbours_ink_landed_leg_turns_through_the_frame():
    """On a /Rotate 270 page, white painted over the new text fails ``ink_not_landed``; the clean edit passes."""

    def build():
        return tb.build_identity_h_fixture(rotate=270).doc

    new_stream = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)
    source, after = _documents(build, new_stream)
    try:
        measurements: dict = {}
        assert _neighbours(source, after, measurements=measurements) is None
        assert measurements["target_glyphs_ink_checked"] == 4
        assert measurements["min_ink_after_px_6x"] > 0
        stream = after.xref_stream(helpers._shows(after, 0)[0].stream_xref)
        after.update_stream(
            helpers._shows(after, 0)[0].stream_xref, stream + b" q 1 g 70 690 52 20 re f Q"
        )
        detail = _neighbours(source, after)
        assert detail is not None and "ink_not_landed:" in detail
    finally:
        source.close()
        after.close()


def test_neighbours_refuse_a_misaligned_pairing():
    spec = SPECS["vi"]
    source, after = _documents(spec.build, _kern_splice(spec.target, spec.replacement))
    try:
        before_show, after_show = helpers._shows(source, 0)[0], helpers._shows(after, 0)[0]
        frame = helpers.visual_frame(source[0])
        honest = helpers.EditedShow(0, before_show, after_show, 4, 5)
        assert helpers.check_neighbour_glyphs_unchanged(source, after, 0, [honest], kind="negative", frame=frame) is None
        crooked = helpers.EditedShow(0, before_show, after_show, 4, 6)  # one glyph too many on the after side
        detail = helpers.check_neighbour_glyphs_unchanged(source, after, 0, [crooked], kind="negative", frame=frame)
        assert detail is not None and detail.startswith("neighbours: pairing")
    finally:
        source.close()
        after.close()


def test_neighbours_target_moved_leg():
    """Extra to the spec's six (written with the helper): the first target glyph's origin must not move."""

    def new_stream(source, show):
        spliced = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)(source, show)
        assert b"1 0 0 1 72 700 Tm" in spliced
        return spliced.replace(b"1 0 0 1 72 700 Tm", b"1 0 0 1 73 700 Tm")

    source, after = _documents(lambda: tb.build_identity_h_fixture().doc, new_stream)
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None and "target_moved: 1 run(s)" in detail
    finally:
        source.close()
        after.close()


@pytest.mark.parametrize("rotate", [0, 270])
def test_neighbours_gid_and_ink_legs_catch_a_swapped_neighbour(rotate):
    """Extra to the spec's six: a neighbour redrawn as other glyphs in the same place changes gid and ink.

    Run unrotated and on /Rotate 270 (the rotation of ten of the historic fourteen): the ink leg's pixel boxes
    go through ``frame.quarter_turn``, and dropping it only shows on a rotated page."""
    tail_hex = tb.encode_cids(tb.TAIL_TEXT).hex().upper().encode("ascii")
    other_hex = tb.encode_cids(tb.REPLACEMENT_EQUAL_ADVANCE[:2]).hex().upper().encode("ascii")

    def new_stream(source, show):
        spliced = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)(source, show)
        assert tail_hex in spliced
        return spliced.replace(tail_hex, other_hex)

    source, after = _documents(
        lambda: tb.build_identity_h_fixture(tail_text=tb.TAIL_TEXT, rotate=rotate).doc, new_stream
    )
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None
        assert "gid_mismatch: 2 glyph(s)" in detail and "ink_changed: 2 glyph(s)" in detail
        assert "untouched_moved" not in detail
    finally:
        source.close()
        after.close()


def _coincident_second_show(fixture) -> None:
    """A second, separate show drawn at the first show's origin with the same text (fill+stroke style)."""
    hex_text = tb.encode_cids(tb.CJK_TEXT).hex().upper()
    tb.append_page_content(
        fixture, f"BT /{fixture.resource_name} 12 Tf 1 0 0 1 72 700 Tm <{hex_text}> Tj ET"
    )


def test_neighbours_pair_a_coincident_unedited_show_as_untouched():
    """Two shows share one origin: the edited one is show 0, the other must stay a PAIRED neighbour.

    Before the fix every glyph within 0.02 pt of the edited origin counted as another emission of the edited
    show, so the second show was zipped in as a target run and never checked."""

    def build():
        fixture = tb.build_identity_h_fixture()
        _coincident_second_show(fixture)
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE))
    try:
        measurements: dict = {}
        # the new glyphs overprint the untouched copy by construction: overlap is not judged for a negative row
        assert _neighbours(source, after, kind="negative", measurements=measurements) is None
        assert measurements["glyphs_paired"] == 4 and measurements["target_glyphs_after"] == 4
    finally:
        source.close()
        after.close()


def test_neighbours_catch_a_rewritten_coincident_show():
    other_hex = tb.encode_cids(tb.REPLACEMENT_EQUAL_ADVANCE).hex().upper().encode("ascii")
    original_hex = tb.encode_cids(tb.CJK_TEXT).hex().upper().encode("ascii")

    def build():
        fixture = tb.build_identity_h_fixture()
        _coincident_second_show(fixture)
        return fixture.doc

    def new_stream(source, show):
        spliced = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)(source, show)
        assert original_hex in spliced  # the second show, untouched by the splice
        return spliced.replace(original_hex, other_hex)

    source, after = _documents(build, new_stream)
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None and "gid_mismatch: 2 glyph(s)" in detail  # the last two glyphs are shared by both texts
    finally:
        source.close()
        after.close()


def test_neighbours_refuse_an_unmatched_coincident_glyph_count():
    """A Form XObject glyph at the edited origin has no ShowOp: the count cannot be matched to shows."""

    def build():
        fixture = tb.build_identity_h_fixture()
        pmf.install_text_form_xobject(
            fixture, name="Fm0", text=tb.TAIL_TEXT, fontsize=12.0, origin=(72.0, 700.0)
        )
        tb.append_page_content(fixture, "/Fm0 Do")
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE))
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None and detail.startswith("neighbours: pairing")
    finally:
        source.close()
        after.close()


def test_neighbours_check_a_shrinking_slice_with_held_successors_as_positive():
    """``(ABCDEF)`` -> ``[(ABX) -600 (EF)] TJ``: a SHORTER slice with E, F held in place passes a judged kind."""
    build = lambda: sfb.build_embedded_simple_fixture("winansi", "ABCDEF").doc  # noqa: E731

    def new_stream(source, show):
        stream = source.xref_stream(show.stream_xref)
        return splice_stream(stream, [build_transplant_replacement(stream, show, b"[(ABX) -600 (EF)] TJ")])

    source, after = _documents(build, new_stream)
    try:
        edited = helpers.edited_show(
            helpers._shows(source, 0)[0], helpers._shows(after, 0)[0], code_bytes=1, pre=2, post=2
        )
        assert (edited.n_old, edited.n_new) == (2, 1)
        measurements: dict = {}
        assert _neighbours(source, after, pre=2, post=2, measurements=measurements) is None
        assert measurements["overlap_glyphs"] == 0 and measurements["glyphs_paired"] == 4
        assert measurements["max_inshow_dev"] <= 1e-6
    finally:
        source.close()
        after.close()


# ----------------------------------------------------------------------------------------------
# Q12: the in-show residual formula (a pure function in S3a; S4 applies it)
# ----------------------------------------------------------------------------------------------
def test_q12_inshow_residual_matches_the_measured_rows():
    """Red by import only (the function did not exist).  Half-up on the float32 width, per MuPDF."""
    kwargs = {"font_size": 10.0, "hscale": 100.0, "trm_scale": 1.0, "user_unit": 1.0}
    # 600.7 -> 600.4: r(600.7) = +0.3, r(600.4) = -0.4, so -0.7 width units = -0.007 pt at 10 pt
    assert helpers.q12_inshow_residual_pt([600.7], [600.4], **kwargs) == pytest.approx(-0.007, abs=1e-12)
    # float32(600.49999) is 600.5, which rounds UP: r = +0.50001 (a float64 floor would give -0.49999)
    kilo = {"font_size": 1000.0, "hscale": 100.0, "trm_scale": 1.0, "user_unit": 1.0}
    assert helpers.q12_inshow_residual_pt([], [600.49999], **kilo) == pytest.approx(0.50001, abs=1e-9)
    # the scale factors: Tz, the text/CTM scale and /UserUnit all multiply
    scaled = {"font_size": 10.0, "hscale": 50.0, "trm_scale": 0.5, "user_unit": 2.0}
    assert helpers.q12_inshow_residual_pt([600.7], [600.4], **scaled) == pytest.approx(-0.007 * 0.5 * 0.5 * 2.0, abs=1e-12)
    assert helpers.q12_inshow_residual_pt([600.0], [600.0], **kwargs) == 0.0
    with pytest.raises(ValueError):
        helpers.q12_inshow_residual_pt([None], [600.0], **kwargs)


# the S4 in-show construction: fractional widths that MuPDF integerises (C, D -> 600 each: -0.4 and -0.4 units; X, Y -> 600:
# -0.2 and -0.1), so the replacement XY is 0.5 width units NARROWER in the fractional view the product computes its kern from
# and EQUAL in the integer view MuPDF draws with: K = -0.5 then pushes E and F right by exactly 0.5 units
Q12_WIDTHS = {"C": 600.4, "D": 600.4, "X": 600.2, "Y": 600.1}
Q12_REPLACEMENT_OPERAND = b"[(ABXY) -0.5 (EF)] TJ"


Q12_UPWARD_TM = b"0 1 -1 0 300 200 Tm"  # a text matrix turned a quarter: the baseline runs up the page


def q12_documents(
    user_unit: int,
    *,
    rotate: int = 0,
    operand: bytes = Q12_REPLACEMENT_OPERAND,
    widths: dict[str, float] = Q12_WIDTHS,
    media_box: tuple[float, float, float, float] | None = None,
    text_matrix: bytes | None = None,
) -> tuple[fitz.Document, fitz.Document]:
    """``(source, after)``: ``(ABCDEF) Tj`` at 100 pt over ``widths`` (:data:`Q12_WIDTHS`) on a page with the given
    ``/UserUnit`` (and ``/Rotate``, ``/MediaBox``, or the builder's ``10 700 Td`` replaced by ``text_matrix``), and the
    copy whose show became ``operand`` (``[(ABXY) -0.5 (EF)] TJ``: slice target CD, pre 2, post 2)."""

    def build() -> fitz.Document:
        fixture = sfb.build_embedded_simple_fixture(
            "winansi", "ABCDEF", fontsize=100.0, origin=(10, 700), widths=widths
        )
        page = fixture.doc[0]
        if user_unit != 1:
            fixture.doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
        if rotate:
            fixture.doc.xref_set_key(page.xref, "Rotate", str(rotate))
        if media_box is not None:
            fixture.doc.xref_set_key(page.xref, "MediaBox", "[" + " ".join(f"{v:g}" for v in media_box) + "]")
        if text_matrix is not None:
            (xref,) = page.get_contents()
            content = fixture.doc.xref_stream(xref)
            assert content.count(b"10 700 Td") == 1, content.count(b"10 700 Td")
            fixture.doc.update_stream(xref, content.replace(b"10 700 Td", text_matrix))
        return fixture.doc

    def new_stream(source: fitz.Document, show) -> bytes:
        stream = source.xref_stream(show.stream_xref)
        return splice_stream(stream, [build_transplant_replacement(stream, show, operand)])

    return _documents(build, new_stream)


def q12_prediction_pt(source: fitz.Document, user_unit: float) -> float:
    """The residual formula for the CD -> XY slice, with the widths the product capability reads."""
    show = helpers._shows(source, 0)[0]
    capability = DocumentFontRegistry(source).capability(source[0], show.font_resource)
    return helpers.q12_inshow_residual_pt(
        [capability.width_of_code(code) for code in b"CD"],
        [capability.width_of_code(code) for code in b"XY"],
        font_size=show.font_size,
        hscale=show.hscale,
        trm_scale=float(math.hypot(*transforms.combined_linear(show.tm, show.ctm)[:2])),
        user_unit=user_unit,
    )


@pytest.mark.parametrize("user_unit", [1, 2])
def test_q12_residual_predicts_the_in_show_shift_on_a_user_unit_page(user_unit):
    """S4 observation pin (written before any adapter; green on its first run, so it was never red).  The texttrace
    shift of the first successor E is the formula at the page's own ``/UserUnit`` within 1e-4 pt (+0.05 pt at unit 1,
    +0.1 pt at unit 2) and is far from the other unit's prediction, so a formula that ignored ``/UserUnit`` could not
    pass the unit-2 page.  Never fit the formula to this number (S3): a red here is a stop."""
    source, after = q12_documents(user_unit)
    try:
        assert helpers.visual_frame(source[0]).user_unit == float(user_unit)
        with helpers._measurement_copy(source) as copy_before, helpers._measurement_copy(after) as copy_after:
            before, later = helpers._flatten_trace(copy_before[0]), helpers._flatten_trace(copy_after[0])
        assert len(before) == len(later) == 6
        assert [glyph.origin for glyph in before[:4]] == [glyph.origin for glyph in later[:4]]  # A, B, and the targets' start
        shift = later[4].origin[0] - before[4].origin[0]  # E, unrotated page: along the baseline is +x
        assert later[4].origin[1] == before[4].origin[1]
        assert shift == pytest.approx(q12_prediction_pt(source, float(user_unit)), abs=1e-4)
        assert shift == pytest.approx(0.05 * user_unit, abs=1e-4)
        other = 2.0 if user_unit == 1 else 1.0
        assert abs(shift - q12_prediction_pt(source, other)) >= 1e-2
    finally:
        source.close()
        after.close()


# ----------------------------------------------------------------------------------------------
# S5 (red first, 2026-10-28): the ink leg judges an in-show successor at its expected shifted position
# ----------------------------------------------------------------------------------------------
def _q12_neighbours(source, after, *, residual: float, measurements=None, kind="negative", **kwargs):
    return _neighbours(
        source,
        after,
        kind=kind,
        pre=2,
        post=2,
        inshow_tolerance=1e-4,
        inshow_residual_pt=residual,
        measurements=measurements,
        **kwargs,
    )


def _count_page_renders(monkeypatch) -> list:
    """Every ``fitz.Page.get_pixmap`` call: the two plain renders plus one compensated render per distinct shift.  The
    ``_ink_pixels`` crops go through the display list and are not counted."""
    calls: list = []
    real = fitz.Page.get_pixmap

    def counted(self, *args, **kwargs):
        calls.append(kwargs.get("matrix"))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", counted)
    return calls


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
@pytest.mark.parametrize("user_unit", [1, 2])
def test_neighbours_ink_leg_compares_a_shifted_successor_at_its_expected_position(monkeypatch, user_unit, rotate):
    """Q12 construction: E and F legitimately move by the residual (+0.05 pt per page unit along the baseline).  At unit 2
    the 0.2 px shift re-renders them, and the S4 ink leg (plain renders, before boxes) reported ``ink_changed: 2 glyph(s)``
    (PITFALLS).  S5: a successor pixel counts only when it also differs on the AFTER page rendered with the compensating
    translation (-residual along its baseline direction, through ``frame.quarter_turn``), so the honest row passes;
    rotations 90, 180 and 270 catch a shift vector that forgot the turn (180 also exercises a negative visual shift).
    The render count proves which path ran: unit 2 reaches the compensated render (3 renders), unit 1 (0.1 px, no pixel
    moves) stays on the plain renders (2) and is a regression guard only."""
    calls = _count_page_renders(monkeypatch)
    source, after = q12_documents(user_unit, rotate=rotate)
    try:
        measurements: dict = {}
        detail = _q12_neighbours(source, after, residual=0.05 * user_unit, measurements=measurements)
        assert detail is None, detail
        assert measurements["max_inshow_dev"] < 1e-4
        # the leg considered both successors (non-report key: NEIGHBOUR_REPORT_KEYS stay)
        assert measurements["inshow_glyphs_ink_checked"] == 2
        assert measurements["glyphs_paired"] == 4
        assert len(calls) == (3 if user_unit == 2 else 2)
    finally:
        source.close()
        after.close()


def test_neighbours_ink_leg_follows_a_turned_text_matrix(monkeypatch):
    """The same construction under ``0 1 -1 0 300 200 Tm`` (the baseline runs up the page, base-space direction (0, -1)):
    the shift follows the glyph's own ``direction``, not a hard-coded (1, 0).  Premise asserted first; the render count
    proves the compensated path ran."""
    calls = _count_page_renders(monkeypatch)
    source, after = q12_documents(2, text_matrix=Q12_UPWARD_TM)
    try:
        with helpers._measurement_copy(source) as copy_before:
            flat = helpers._flatten_trace(copy_before[0])
        assert len(flat) == 6 and abs(flat[4].direction[0]) < 1e-6 and abs(abs(flat[4].direction[1]) - 1.0) < 1e-6
        measurements: dict = {}
        detail = _q12_neighbours(source, after, residual=0.1, measurements=measurements)
        assert detail is None, detail
        assert measurements["max_inshow_dev"] < 1e-4 and measurements["inshow_glyphs_ink_checked"] == 2
        assert len(calls) == 3
    finally:
        source.close()
        after.close()


def test_neighbours_ink_leg_accepts_a_compensated_render_one_pixel_short(monkeypatch):
    """A page whose zoomed width is fractional (595.025 pt at unit 2 = 2380.1 px) loses its partial last column to the
    translation (MEASURED: 2380 columns for 2381); the missing edge counts as unchanged and the honest row passes.  A
    pixmap off by more, or with a moved origin (a negative shift of half a pixel pushes the page's own left edge to
    device x = 1), is the returned ``frame:`` detail."""
    calls = _count_page_renders(monkeypatch)
    source, after = q12_documents(2, media_box=(0, 0, 595.025, 842))
    try:
        measurements: dict = {}
        detail = _q12_neighbours(source, after, residual=0.1, measurements=measurements)
        assert detail is None, detail
        assert measurements["inshow_glyphs_ink_checked"] == 2 and len(calls) == 3
        with helpers._measurement_copy(after) as copy:
            plain = helpers._pixmap_array(copy[0])
            assert plain.shape[1] == 2381
            same = helpers._compensated_difference(plain, copy[0], (0.0, 0.0))
            assert isinstance(same, np.ndarray) and same.shape == plain.shape[:2] and not same.any()
            short = helpers._compensated_difference(plain, copy[0], (0.1, 0.0))
            assert isinstance(short, np.ndarray) and short.shape == plain.shape[:2]
            # a grid four rows taller than the page can fill: beyond the edge strip a 0.2 px shift may lose (2 rows)
            taller = np.concatenate([plain, plain[:4]], axis=0)
            assert helpers._compensated_difference(taller, copy[0], (0.1, 0.0)) == "compensated raster size differs"
            # a moved origin: the pixmap is inside the size window, only the origin check can refuse it
            assert helpers._compensated_difference(plain, copy[0], (-0.5, 0.0)) == "compensated raster size differs"
    finally:
        source.close()
        after.close()


def test_neighbours_ink_leg_renders_once_per_distinct_shift(monkeypatch):
    """Render count: the two plain renders plus ONE compensated render for the Q12 row at unit 2 (both successors share
    the shift), and only the two plain renders when the residual is 0."""
    calls = _count_page_renders(monkeypatch)
    source, after = q12_documents(2)
    try:
        assert _q12_neighbours(source, after, residual=0.1) is None
        assert len(calls) == 3
        calls.clear()
        _q12_neighbours(source, after, residual=0.0)  # the verdict (inshow_moved) is not the point: no compensated render
        assert len(calls) == 2
    finally:
        source.close()
        after.close()


def test_neighbours_ink_leg_follows_a_negative_residual(monkeypatch):
    """Widths C, D = 600.1 and X, Y = 600.4: the fractional view makes XY 0.6 units wider, the kern +0.6 holds E and F there,
    and MuPDF's integer view moves them LEFT by 0.6 units (-0.06 pt per page unit).  Premise asserted through the formula;
    the render count proves the compensated path ran."""
    calls = _count_page_renders(monkeypatch)
    widths = {"C": 600.1, "D": 600.1, "X": 600.4, "Y": 600.4}
    source, after = q12_documents(2, widths=widths, operand=b"[(ABXY) 0.6 (EF)] TJ")
    try:
        assert q12_prediction_pt(source, 2.0) == pytest.approx(-0.12, abs=1e-9)
        measurements: dict = {}
        detail = _q12_neighbours(source, after, residual=-0.12, measurements=measurements)
        assert detail is None, detail
        assert measurements["max_inshow_dev"] < 1e-4 and measurements["inshow_glyphs_ink_checked"] == 2
        assert len(calls) == 3
    finally:
        source.close()
        after.close()


def test_neighbours_ink_leg_leaves_an_unmoved_successor_to_the_position_leg():
    """``[(ABXY) 0 (EF)] TJ`` holds E and F in place, but the caller claims the 0.1 pt residual (unit 2): the position leg
    fails (``inshow_moved``) and the ink leg stays silent, because a successor pixel counts only when it differs on BOTH
    renders and the plain renders agree on the unmoved glyphs (the compensated render alone would show them 0.2 px
    off).  The swapped-successor test below is what kills a fix that exempted the successors from the ink leg."""
    source, after = q12_documents(2, operand=b"[(ABXY) 0 (EF)] TJ")
    try:
        detail = _q12_neighbours(source, after, residual=0.1)
        assert detail is not None
        assert "inshow_moved: 2 glyph(s)" in detail and "ink_changed" not in detail, detail
    finally:
        source.close()
        after.close()


def _draw_on_both(source: fitz.Document, after: fitz.Document, lines) -> tuple[fitz.Document, fitz.Document]:
    """The same lines drawn on both documents (page space, unrotated page), reopened from bytes."""
    for doc in (source, after):
        for start, end, width in lines:
            doc[0].draw_line(start, end, width=width)
    out = fitz.open("pdf", source.tobytes()), fitz.open("pdf", after.tobytes())
    source.close()
    after.close()
    return out


@pytest.mark.parametrize("user_unit", [1, 2])
@pytest.mark.parametrize("mode", ["rule", "underline"])
def test_neighbours_ink_leg_ignores_stationary_ink_inside_a_shifted_successor_box(user_unit, mode):
    """Review finding on the first S5 cut (compensated render alone): a 0.7 pt rule standing inside E's box, or an underline
    ending inside F's box, did not move, so on the compensated render IT is 0.1-0.2 px off and the honest row failed
    ``ink_changed`` (6 of 6 rule positions at unit 1, where S4 passed).  A successor pixel now counts only when it differs on
    the plain AND the compensated render: the rule differs on one, the shifted glyph on the other, neither on both."""
    source, after = q12_documents(user_unit)
    with helpers._measurement_copy(source) as copy_before:
        flat = helpers._flatten_trace(copy_before[0])
    first, e_box, last = (fitz.Rect(flat[i].bbox) for i in (0, 4, 5))
    if mode == "rule":
        x = e_box.x0 + 0.37 * e_box.width
        lines = [((x, e_box.y0), (x, e_box.y1), 0.7)]
    else:
        y = first.y1 - 0.25 * first.height
        lines = [((first.x0, y), (last.x0 + 0.51 * last.width, y), 1.0)]
    source, after = _draw_on_both(source, after, lines)
    try:
        measurements: dict = {}
        detail = _q12_neighbours(source, after, residual=0.05 * user_unit, measurements=measurements)
        assert detail is None, detail
        assert measurements["inshow_glyphs_ink_checked"] == 2
    finally:
        source.close()
        after.close()


@pytest.mark.parametrize("user_unit", [1, 2])
def test_neighbours_ink_leg_catches_swapped_successors_at_the_shifted_position(user_unit):
    """``[(ABXY) -0.5 (FE)] TJ``: the successors keep their (equal-width) positions and the exact residual, but each box now
    draws the other glyph: ``gid_mismatch`` and ``ink_changed`` both name 2 glyphs, with or without compensation.  Kills a
    fix that compared successors only when their gid matched."""
    source, after = q12_documents(user_unit, operand=b"[(ABXY) -0.5 (FE)] TJ")
    try:
        detail = _q12_neighbours(source, after, residual=0.05 * user_unit)
        assert detail is not None
        assert "gid_mismatch: 2 glyph(s)" in detail and "ink_changed: 2 glyph(s)" in detail, detail
        assert "inshow_moved" not in detail, detail
        # the target halos are subtracted from a successor's region on the combined difference too: a halo wide enough
        # to cover the successors silences the ink leg while the gid leg still names them
        detail = _q12_neighbours(source, after, residual=0.05 * user_unit, halo_pt=500.0)
        assert detail is not None and "gid_mismatch: 2 glyph(s)" in detail and "ink_changed" not in detail, detail
    finally:
        source.close()
        after.close()


# ----------------------------------------------------------------------------------------------
# S3b premise tests: the byte/wrapper twins test what they claim (observed at HEAD, Step 0)
# ----------------------------------------------------------------------------------------------
def test_twin_ii_deletes_the_closing_emc_inside_the_edited_stream(oracle_runs):
    """(ii): the wrapper closes in the edited stream before the defect and stays open after it.

    The render is unchanged by the deletion (the runner's pixel-mask assert only allows the halo to change),
    the replay is not malformed and counts no EMC underflow."""
    (run,) = oracle_runs["ii"]
    before = replay_page_streams(helpers.page_streams(run.source, 0))
    (wrapper_before,) = before.wrappers_for(run.before_show)
    assert wrapper_before.closed and wrapper_before.close_stream_xref == run.replacement.stream_xref
    after = replay_page_streams(helpers.page_streams(run.after, 0))
    (wrapper_after,) = after.wrappers_for(helpers._shows(run.after, 0)[0])
    assert not wrapper_after.closed and wrapper_after.close_stream_xref is None
    assert not after.malformed and after.mc_emc_underflows == 0 and len(after.shows) == len(before.shows)
    rep = run.replacement
    shrink = len(run.source.xref_stream(rep.stream_xref)) - len(run.after.xref_stream(rep.stream_xref))
    assert shrink == len(b" EMC") - (len(rep.replacement_bytes) - (rep.end - rep.start))


def test_twin_ii_split_stream_wrapper_is_refused_by_the_product():
    """Written with the helper (pins the Step 0 observation).  Why (ii) deletes an inline EMC: a BDC in stream A closed by an EMC in stream B (``oc_layer="split"``) is
    refused ``mc_splice_crosses_wrapper_boundary``, so the cross-stream shift rule is covered by the helper unit
    test (``test_wrapper_check_follows_an_emc_in_another_stream``) and not by a twin."""
    doc = frontier_twins._identity_h(far_show=True, oc_layer="split")()
    try:
        streams = helpers.page_streams(doc, 0)
        assert len(streams) == 2 and streams[1][1] == b"EMC"
        replay = replay_page_streams(streams)
        (wrapper,) = replay.wrappers_for(replay.shows[0])
        assert wrapper.stream_xref == streams[0][0] and wrapper.close_stream_xref == streams[1][0]
        prepared = TieredCommitEngine(doc, max_tier=1).prepare(
            doc[0],
            target_text=tb.CJK_TEXT,
            replacement_text=tb.REPLACEMENT_EQUAL_ADVANCE,
            **frontier_twins.located_arguments(doc, tb.CJK_TEXT),
        )
        assert isinstance(prepared, PlanRejection)
        assert str(prepared.reason) == "mc_splice_crosses_wrapper_boundary"
    finally:
        doc.close()


def test_twin_iii_rect_lies_inside_the_halo_over_the_tail_glyph(oracle_runs):
    """(iii): the 1 pt square is inside ``halo_mask`` (so neighbours must pass) and inside the first tail glyph's box."""
    (run,) = oracle_runs["iii"]
    prepared = run.prepared
    assert prepared is not None
    box = prepared.target_bbox_page
    height = run.after[0].rect.height
    rect = fitz.Rect(box[2] + 0.5, height - 703, box[2] + 1.5, height - 702)
    with helpers._measurement_copy(run.after) as copy:
        flat = helpers._flatten_trace(copy[0])
        after_trace = helpers._trace_for(copy[0], helpers._shows(run.after, 0)[0], tb.REPLACEMENT_EQUAL_ADVANCE)
    mask = helpers.halo_mask(box, after_trace["bbox"], run.frame)
    assert mask.contains(rect)
    first_tail_glyph = fitz.Rect(flat[len(tb.REPLACEMENT_EQUAL_ADVANCE)].bbox)
    assert first_tail_glyph.contains(rect)


# ----------------------------------------------------------------------------------------------
# S3b: the glyph-identity legs on the builder kinds (plan section 3; the s3b spec matrix)
# ----------------------------------------------------------------------------------------------
_LEVEL_A = "Level A 2024"
#: kind -> (leg, expected detail or None).  Index 6 is the A; 10 glyphs are non-space.
_MATRIX = {
    "winansi": ("glyph_name_agl", None),
    "post3_cmap31": ("cmap_31_reverse", None),
    "symbolic_post3": ("cmap_31_reverse", None),
    "symbolic_ascii": ("glyph_name_agl", None),
    "tounicode_lie": (
        "glyph_name_agl",
        "glyph_identity: glyph_name_agl: leg_char_differs: 1 of 10 glyph(s), first index 6",
    ),
    "symbolic_post3_wrongglyph": (
        "cmap_31_reverse",
        "glyph_identity: cmap_31_reverse: leg_char_differs: 1 of 10 glyph(s), first index 6",
    ),
    "symbolic_wrongname": (
        "glyph_name_agl",
        "glyph_identity: glyph_name_agl: leg_char_differs: 1 of 10 glyph(s), first index 6",
    ),
}


def _unedited_inputs(doc: fitz.Document, *, code_bytes: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """``(codes, gids)`` of the first show of an UNEDITED document (the show as its own before and after)."""
    show = helpers._shows(doc, 0)[0]
    edited = helpers.edited_show(show, show, code_bytes=code_bytes)
    inputs = helpers.glyph_identity_inputs(
        doc, 0, edited, frame=helpers.visual_frame(doc[0]), code_bytes=code_bytes
    )
    assert isinstance(inputs, tuple), inputs
    return inputs


def _identity(doc, font_xref, text, kind, *, code_bytes, measurements=None, codes=None, gids=None):
    own_codes, own_gids = _unedited_inputs(doc, code_bytes=code_bytes)
    return helpers.check_glyph_identity(
        doc,
        0,
        font_xref,
        text,
        kind,
        gid_after=own_gids if gids is None else gids,
        codes=own_codes if codes is None else codes,
        measurements=measurements,
    )


assert sorted(_MATRIX) == sorted(sfb.KINDS)  # every builder kind has a row


@pytest.mark.parametrize("kind", sfb.KINDS)
def test_glyph_identity_legs_on_the_builder_kinds(kind):
    leg, expected = _MATRIX[kind]
    fixture = sfb.build_embedded_simple_fixture(kind, _LEVEL_A)
    measurements: dict = {}
    detail = _identity(
        fixture.doc, fixture.font_xref, _LEVEL_A, "simple", code_bytes=1, measurements=measurements
    )
    assert detail == expected
    assert measurements["leg"] == leg
    assert measurements["glyphs_checked"] == 10
    assert measurements["outline_checked"] == 10  # an embedded TrueType program: every glyph has an outline


def _remove_the_unicode_cmap(fixture) -> None:
    program = fixture.doc.xref_stream(fixture.fontfile_xref)
    font = TTFont(BytesIO(program))
    font["cmap"].tables = [
        table for table in font["cmap"].tables if (table.platformID, table.platEncID) != (3, 1)
    ]
    out = BytesIO()
    font.save(out)
    fixture.doc.update_stream(fixture.fontfile_xref, out.getvalue())


def test_glyph_identity_has_no_leg_for_a_nameless_program_without_a_unicode_cmap():
    """U6, and the fontTools trap: a post-format-3 program has no names, yet ``getGlyphOrder()`` hands out the AGL
    names of its (3,1) cmap, so an AGL leg reading them is the cmap leg in disguise; the leg is therefore chosen
    from the post format and not from the names, and without a (3,1) table nothing is left to read."""
    fixture = sfb.build_embedded_simple_fixture("symbolic_post3", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    trap = TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))
    assert trap.getGlyphOrder()[sfb.glyph_id("A")] == "A" and trap["post"].formatType == 3.0  # the trap, pinned
    _remove_the_unicode_cmap(fixture)
    font = TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))
    assert font["post"].formatType == 3.0
    assert "A" not in font.getGlyphOrder()  # synthesized names, not the builder's
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_has_no_leg_for_an_unembedded_non_base14_font():
    """U2: an unembedded font outside the base-14 table has no program and no table to read."""
    doc = ssf.open_case("a")
    try:
        codes, gids = _unedited_inputs(doc, code_bytes=1)
        doc.xref_set_key(4, "BaseFont", "/NoSuchFaceAnywhere")
        with pytest.raises(helpers.IndependentLegUnavailable):
            helpers.check_glyph_identity(doc, 0, 4, ssf.TARGET, "simple", gid_after=gids, codes=codes)
    finally:
        doc.close()


@pytest.mark.parametrize("key", ["FontFile", "FontFile3"])
def test_glyph_identity_defers_type1_and_cff_programs(key):
    """U3/U4: the Type1 and CFF recipes are written down for I1 and not implemented; raising keeps them from passing."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    descriptor = int(fixture.doc.xref_get_key(fixture.font_xref, "FontDescriptor")[1].split()[0])
    fixture.doc.xref_set_key(descriptor, key, f"{fixture.fontfile_xref} 0 R")
    if key == "FontFile3":  # PyMuPDF's get_fonts() needs the stream /Subtype of a FontFile3
        fixture.doc.xref_set_key(fixture.fontfile_xref, "Subtype", "/OpenType")
    fixture.doc.xref_set_key(descriptor, "FontFile2", "null")
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_defers_a_differences_encoding():
    """U7: ``/Differences`` is I8's (F31); the encoding cannot name the code, so the leg is unavailable."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    fixture.doc.xref_set_key(
        fixture.font_xref, "Encoding", "<</BaseEncoding/WinAnsiEncoding/Differences[65/B]>>"
    )
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_type0_leg_catches_a_forged_gid_or_code():
    fixture = tb.build_identity_h_fixture()
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    assert len(set(gids)) == 4
    measurements: dict = {}
    assert (
        _identity(fixture.doc, fixture.font_xref, tb.CJK_TEXT, "type0", code_bytes=2, measurements=measurements)
        is None
    )
    assert measurements["leg"] == "cid_program_cmap"
    assert measurements["glyphs_checked"] == measurements["outline_checked"] == 4
    reversed_gids = _identity(
        fixture.doc, fixture.font_xref, tb.CJK_TEXT, "type0", code_bytes=2, gids=tuple(reversed(gids))
    )
    assert reversed_gids == "glyph_identity: cid_program_cmap: leg_gid_differs: 4 of 4 glyph(s), first index 0"
    swapped = _identity(
        fixture.doc, fixture.font_xref, tb.CJK_TEXT, "type0", code_bytes=2, codes=tuple(reversed(codes))
    )
    assert swapped == (
        "glyph_identity: cid_program_cmap: leg_gid_differs: 4 of 4 glyph(s), first index 0; "
        "leg_char_differs: 4 of 4 glyph(s), first index 0; "
        "tounicode_disagrees: 4 of 4 glyph(s), first index 0"
    )


def test_glyph_identity_standard14_leg_catches_a_forged_code():
    doc = ssf.open_case("a")
    try:
        codes, gids = _unedited_inputs(doc, code_bytes=1)
        measurements: dict = {}
        assert _identity(doc, 4, ssf.TARGET, "simple", code_bytes=1, measurements=measurements) is None
        assert measurements["leg"] == "standard_14_table"
        assert measurements["glyphs_checked"] == 9 and measurements["outline_checked"] == 0
        forged = (*codes[:-1], ord("5"))  # the last glyph is still drawn as '4', but the code written is '5'
        detail = _identity(doc, 4, ssf.TARGET, "simple", code_bytes=1, codes=forged)
        assert detail == (
            "glyph_identity: standard_14_table: leg_gid_differs: 1 of 9 glyph(s), first index 9; "
            "leg_char_differs: 1 of 9 glyph(s), first index 9"
        )
    finally:
        doc.close()


def test_glyph_identity_reports_a_glyph_without_an_outline():
    """Written with the helper.  ``no_outline``: the code written reaches the empty space glyph, drawn and walked consistently, for an 'A'."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    space_gid = sfb.glyph_id(" ")
    forged_codes = (*codes[:6], 0x20, *codes[7:])
    forged_gids = (*gids[:6], space_gid, *gids[7:])
    detail = helpers.check_glyph_identity(
        fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=forged_gids, codes=forged_codes
    )
    assert detail == (
        "glyph_identity: glyph_name_agl: no_outline: 1 of 10 glyph(s), first index 6; "
        "leg_char_differs: 1 of 10 glyph(s), first index 6"
    )


def test_glyph_identity_has_no_leg_for_a_type0_font_without_a_capability():
    """Written with the helper.  U1: a Type0 font whose ToUnicode is gone has no Identity-H capability, so no ToUnicode leg."""
    fixture = tb.build_identity_h_fixture()
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    tb.strip_tounicode(fixture)
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes
        )


def test_glyph_identity_has_no_leg_for_an_unreadable_program():
    """Written with the helper.  U5: an embedded stream that is not a font."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    fixture.doc.update_stream(fixture.fontfile_xref, b"this is not a font program")
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_rejects_contradicting_inputs():
    """Written with the helper: inputs that contradict each other are a caller bug (``ValueError``)."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    base = (fixture.doc, 0, fixture.font_xref, _LEVEL_A)
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(*base, "cff", gid_after=gids, codes=codes)  # unknown font kind
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(*base, "simple", gid_after=gids[:-1], codes=codes)  # lengths differ
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(*base, "type0", gid_after=gids, codes=codes)  # not a Type0 font
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(
            fixture.doc, 0, 9999, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )  # not a font of the page


def test_glyph_identity_type0_leg_is_the_program_cmap_not_the_tounicode():
    """Written with the helper.  Two ToUnicode claims swapped: ToUnicode alone would pass the page, the program's
    own (3,1) cmap does not.  The product commits the edit through the lie (twin ``v-type0``); here the unedited page
    is judged against the text it claims to say and against the text the program really draws."""
    fixture = tb.build_identity_h_fixture()
    mappings = tb.default_tounicode_mappings(fixture)
    mappings[0], mappings[1] = (mappings[0][0], mappings[1][1]), (mappings[1][0], mappings[0][1])
    tb.write_minimal_tounicode(fixture, mappings)
    lie_text = frontier_twins.TYPE0_LIE_TARGET  # what the page claims to say
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    # the claimed text agrees with ToUnicode and the walk, but not with the program's own cmap
    assert (
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, lie_text, "type0", gid_after=gids, codes=codes
        )
        == "glyph_identity: cid_program_cmap: leg_char_differs: 2 of 4 glyph(s), first index 0"
    )
    # the true text is what the program draws: the cmap leg passes and the ToUnicode cross-check disagrees
    assert (
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes
        )
        == "glyph_identity: cid_program_cmap: tounicode_disagrees: 2 of 4 glyph(s), first index 0"
    )


def test_glyph_identity_type0_catches_a_permuted_cidtogid_map():
    """Refuter nit: every other synthetic Type0 fixture has an identity CIDToGIDMap.  Here code(你) draws the 好
    outline: the walk follows the map, the rendering agrees with it, ToUnicode still says 你, and only the
    program's cmap sees that the glyph is not the character."""
    fixture = tb.build_identity_h_fixture()
    first, second = tb.cid_for(tb.CJK_TEXT[0]), tb.cid_for(tb.CJK_TEXT[1])
    table = tb.identity_cidtogid_bytes(
        max(tb.cid_for(char) for char in tb.CJK_TEXT) + 1, {first: second, second: first}
    )
    tb.set_cidtogid_stream(fixture, table)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    assert gids[0] == second and gids[1] == first  # the rendering follows the map
    measurements: dict = {}
    detail = helpers.check_glyph_identity(
        fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes, measurements=measurements
    )
    assert detail == "glyph_identity: cid_program_cmap: leg_char_differs: 2 of 4 glyph(s), first index 0"
    assert measurements["leg"] == "cid_program_cmap"


def test_glyph_identity_has_no_leg_for_a_type0_program_without_a_unicode_cmap():
    """U8 (written with the helper): no (3,1) and no (0,x) table, so there is no independent Type0 leg and no fallback."""
    fixture = tb.build_identity_h_fixture()
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    font = TTFont(BytesIO(read_embedded_font_program(fixture.doc, fixture.font_xref)))
    macintosh = CmapSubtable.newSubtable(0)
    macintosh.platformID, macintosh.platEncID, macintosh.language, macintosh.cmap = 1, 0, 0, {}
    font["cmap"].tables = [macintosh]
    out = BytesIO()
    font.save(out)
    fixture.doc.update_stream(tb.fontfile2_xref(fixture), out.getvalue())
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes
        )


def _rename_glyph_a(fixture) -> None:
    """Rename the glyph ``A`` of the embedded post-2 program to ``g123`` (an AGL-less name), everywhere."""
    font = TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))
    order = ["g123" if name == "A" else name for name in font.getGlyphOrder()]
    font["glyf"].glyphs["g123"] = font["glyf"].glyphs.pop("A")
    font["hmtx"].metrics["g123"] = font["hmtx"].metrics.pop("A")
    for table in font["cmap"].tables:
        table.cmap = {code: ("g123" if name == "A" else name) for code, name in table.cmap.items()}
    font.setGlyphOrder(order)
    out = BytesIO()
    font.save(out)
    fixture.doc.update_stream(fixture.fontfile_xref, out.getvalue())


def test_glyph_identity_post_names_without_agl_text_are_unavailable_not_a_mismatch():
    """U7 on post names (written with the helper): a post-2 program whose glyph names the AGL cannot read has no
    independent leg; reporting ``leg_char_differs`` would claim a finding about the glyph that the oracle cannot make."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    _rename_glyph_a(fixture)
    assert TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref))).getGlyphOrder()[sfb.glyph_id("A")] == "g123"
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )
